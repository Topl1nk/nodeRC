"""editor_window.py — Main Editor Window

The interaction shell: keyboard routing, selection-wide commands, the undo
stack, project dialogs and the dirty-state title. Graph snapshots live in
graph_serialization, chain launching in chain_execution — the window only
orchestrates them.
"""
from __future__ import annotations

import json
import os
import sys
from typing import List, Optional

from PyQt5.QtWidgets import (
    QApplication, QFileDialog, QMainWindow, QVBoxLayout, QWidget,
)
from PyQt5.QtGui import QCursor
from PyQt5.QtCore import QPoint, QPointF, Qt, QTimer

from localization import available_languages, get_language, set_language, t
from configuration import (
    WINDOW_BACKGROUND_COLOR, UNDO_HISTORY_LIMIT,
    WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT,
    TITLE_BAR_HEIGHT, TITLE_BAR_RESIZE_MARGIN,
    AUTOSAVE_INTERVAL_MS,
    KEY_SPAWN_MENU, KEY_DELETE, KEY_SAVE, KEY_OPEN,
    KEY_COPY, KEY_PASTE, KEY_UNDO, KEY_REDO,
    KEY_TOGGLE_GRID, KEY_FIT_VIEW, KEY_FULLSCREEN,
    KEY_RENAME_NODE, KEY_SELECT_ALL, KEY_GROUP, KEY_DUPLICATE,
    MOD_NONE, MOD_CTRL, MOD_CTRL_SHIFT,
    GROUP_FRAME_PAD_LEFT, GROUP_FRAME_PAD_TOP,
    GROUP_FRAME_PAD_RIGHT, GROUP_FRAME_PAD_BOTTOM,
    WINDOW_INITIAL_X, WINDOW_INITIAL_Y, WINDOW_INITIAL_WIDTH, WINDOW_INITIAL_HEIGHT,
    START_NODE_INITIAL_X, START_NODE_INITIAL_Y,
    DUPLICATE_OFFSET_X, DUPLICATE_OFFSET_Y,
    CLIPBOARD_PAYLOAD_PREFIX,
)
from diagnostics import log_and_explain
from core.command_database import load_command_database

from ui.view import GraphicsView
from ui.scene import NodeScene
from ui.graph_items import Connection, GroupFrameItem, MetaNode
from ui.command_nodes import CommandNode, StartNode
from ui.project_tab import ProjectTab
from ui.title_bar import TitleBarWidget
from core.graph_serialization import (
    build_param_node, clear_graph, materialize_graph, payload_center,
    scene_to_graph_model, serialize_graph,
)
from core.chain_execution import build_exec_chain, build_launch_tokens, launch
from core import autosave, app_prefs, session
from ui.flag_icon import language_flag_icon
from ui.session_restore_dialog import SessionRestoreDialog
from ui.message_dialog import MessageDialog
from ui.window_chrome import apply_rounded_corners

# WM_NCHITTEST result codes used by NodeEditorWindow.nativeEvent to give a
# frameless window back its native resize/move/edge-snap behavior on Windows.
_WM_NCHITTEST = 0x0084
_HTCLIENT = 1
_HTCAPTION = 2
_HTLEFT, _HTRIGHT, _HTTOP, _HTBOTTOM = 10, 11, 12, 15
_HTTOPLEFT, _HTTOPRIGHT, _HTBOTTOMLEFT, _HTBOTTOMRIGHT = 13, 14, 16, 17


class NodeEditorWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setGeometry(WINDOW_INITIAL_X, WINDOW_INITIAL_Y, WINDOW_INITIAL_WIDTH, WINDOW_INITIAL_HEIGHT)
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.setStyleSheet(f"QMainWindow{{background:{WINDOW_BACKGROUND_COLOR};}}")
        self._apply_rounded_corners()

        self.command_categories, self.command_defs = load_command_database()

        self._linked_group: List[MetaNode] = []      # selected same-type nodes under linked editing
        self._active_field_key: Optional[str] = None  # which field key the linked group mirrors
        self._focus_event_counter: int = 0            # serializes focus in/out to settle the active group

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.title_bar = TitleBarWidget(self)
        layout.addWidget(self.title_bar)

        self.view = GraphicsView()
        layout.addWidget(self.view)

        # A session is a folder of per-tab autosave snapshots (core/session.py
        # + core/autosave.py) — this run gets its own fresh folder to write
        # into; whichever folder the previous run left behind is offered
        # below for restore.
        self._session_dir, previous_session_dir = session.start_new_session()

        # Every open project lives in a ProjectTab (its own scene, connection
        # list, undo history, dirty flag and file path); the window proxies
        # scene/connections/_block_undo_push through to whichever tab is
        # active (see the properties below) so the rest of the codebase can
        # keep reaching through win.scene/win.connections unchanged.
        self.tabs: List[ProjectTab] = []
        self.active_tab: ProjectTab = self._create_tab()
        self.active_tab.untitled_number = self._next_untitled_number()
        self.view.setScene(self.active_tab.scene)
        self.title_bar.tab_strip.rebuild(self.tabs, self.active_tab)

        self._update_title()
        self.push_undo_state()

        # Whether to offer/replace the fresh blank tab above with whatever
        # was open last run — see _maybe_restore_session(). Deferred to the
        # first event-loop tick (after this window is actually shown):
        # restoring synchronously here, before show()/app.exec_(), builds
        # every embedded widget before Qt ever polishes its style for a
        # real, visible window — those widgets can render with a stale
        # unstyled/unpolished appearance (e.g. placeholder text far too
        # dark) that a normal, interactively-created node never hits.
        if session.session_tab_files(previous_session_dir):
            QTimer.singleShot(0, lambda: self._maybe_restore_session(previous_session_dir))

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(AUTOSAVE_INTERVAL_MS)
        self._autosave_timer.timeout.connect(self._run_autosave_pass)
        self._autosave_timer.start()

    # ── Autosave / whole-session recovery ────────────────────────────────────

    def _write_tab_snapshot(self, tab: ProjectTab):
        if not tab.dirty and tab.project_path is None:
            # A blank "Untitled" tab nobody has touched yet — nothing worth
            # persisting, and it shouldn't clutter (or by itself populate)
            # next launch's session-restore prompt.
            autosave.discard_snapshot(self._session_dir, tab.tab_id)
            return
        try:
            tab_index = self.tabs.index(tab)
        except ValueError:
            tab_index = len(self.tabs)
        autosave.write_snapshot(self._session_dir, tab.tab_id, tab.project_path,
                                 tab.dirty, tab_index, tab.scene, tab.connections)

    def _run_autosave_pass(self):
        # A periodic safety net — every edit already snapshots immediately
        # (see push_undo_state), this just re-covers any tab that somehow
        # missed that (e.g. a bulk operation run under _block_undo_push).
        for tab in self.tabs:
            self._write_tab_snapshot(tab)

    def closeEvent(self, event):
        # One last flush so a crash or an OS-initiated shutdown right after
        # this doesn't lose edits the periodic timer hadn't gotten to yet.
        self._run_autosave_pass()
        super().closeEvent(event)

    def _maybe_restore_session(self, previous_session_dir):
        """Offer to bring back the tabs from the previous run's session
        folder, replacing the single fresh blank tab __init__ just created."""
        if app_prefs.get_session_restore_always():
            self._restore_session(previous_session_dir)
            return
        dialog = SessionRestoreDialog(parent=self)
        dialog.exec_()
        if dialog.choice == "always":
            app_prefs.set_session_restore_always(True)
            self._restore_session(previous_session_dir)
        elif dialog.choice == "yes":
            self._restore_session(previous_session_dir)
        # "no" — keep the fresh blank tab, nothing to do.

    def _restore_session(self, previous_session_dir):
        placeholder = self.tabs[0] if len(self.tabs) == 1 else None

        # Snapshot filenames sort by tab_id (random), which carries no
        # ordering — read every envelope first and rebuild tabs in their
        # original left-to-right order via each one's own tab_index.
        entries = []
        for snapshot_file in session.session_tab_files(previous_session_dir):
            try:
                with open(snapshot_file, "r", encoding="utf-8") as f:
                    envelope = json.load(f)
            except Exception as exc:
                log_and_explain("Session tab file unreadable", exc)
                continue
            entries.append((envelope.get("tab_index", 0), snapshot_file.stem, envelope))
        entries.sort(key=lambda e: e[0])

        if not entries:
            return
        # Drop the placeholder before restoring so _next_untitled_number()
        # (used below for any restored tab with no manual path) doesn't see
        # it and shift every restored "Untitled N" number up by one.
        if placeholder is not None:
            self.tabs.remove(placeholder)

        restored: List[ProjectTab] = []
        for _, tab_id, envelope in entries:
            dirty = bool(envelope.get("dirty", False))
            path = autosave.resolve_manual_path(envelope)

            tab = self._create_tab()
            tab.tab_id = tab_id

            # Attach this tab's scene to the real, on-screen view *before*
            # rebuilding its graph — exactly what new_tab()/_load_into_tab()
            # does for a normal File > Open (switch_to_tab(), then load).
            # The previous version only flipped self.active_tab and left the
            # view pointed at whatever tab was already showing, so every
            # field widget in a background tab got constructed while its
            # scene was never the one actually on screen. Qt only fully
            # polishes a stylesheet-styled widget's colors the first time it
            # becomes part of a shown window — build it "hidden" like that
            # and it can stick with stale/black text forever after, which is
            # exactly what a plain Open (built on an already-visible tab)
            # never hits.
            self.switch_to_tab(tab)
            if "graph" in envelope:
                self._restore(envelope["graph"], restore_selection=False)
            # Note: deliberately NOT forcing a QApplication.processEvents()
            # flush here. It was tried as a belt-and-suspenders complement to
            # switch_to_tab() above, but pumping the event loop mid-restore
            # let stray deferred callbacks (e.g. NodeComboBox's
            # QTimer.singleShot(0, self._safe_refresh) from hidePopup) fire
            # against a tab's widgets while a *later* tab in this same loop
            # was still being torn down/rebuilt — crashing with "NodeComboBox
            # object has no attribute 'node'" on next launch. switch_to_tab()
            # alone (making each tab briefly the real, on-screen scene while
            # its graph is restored) already gets these widgets a proper
            # paint pass without that risk.
            tab.project_path = path
            tab.untitled_number = None if path else self._next_untitled_number()
            tab.history = []
            tab.history_index = -1
            self.push_undo_state()
            # A dirty tab keeps its unsaved-edit mark; a clean one just
            # reflects whatever was last snapshotted (in sync with disk).
            self._set_dirty(dirty)
            restored.append(tab)

        if not restored:
            return
        self.switch_to_tab(restored[0])
        self._update_title()
        self._refresh_tab_strip()

    # ── Tabs ──────────────────────────────────────────────────────────────────

    def _create_tab(self) -> ProjectTab:
        scene = NodeScene(self)
        scene.nodeEditorWindow = self
        tab = ProjectTab(scene)
        self.tabs.append(tab)
        self._add_start_node(scene)
        return tab

    def _next_untitled_number(self) -> int:
        used = {tab.untitled_number for tab in self.tabs
                if tab.project_path is None and tab.untitled_number}
        n = 1
        while n in used:
            n += 1
        return n

    def new_tab(self, path: Optional[str] = None) -> ProjectTab:
        """Open a fresh tab, optionally loading ``path`` into it."""
        tab = self._create_tab()
        if path is None:
            tab.untitled_number = self._next_untitled_number()
        self.switch_to_tab(tab)
        if path:
            self._load_into_tab(tab, path)  # handles its own undo baseline/dirty
        else:
            self.push_undo_state()
            self._set_dirty(False)
        self._refresh_tab_strip()
        return tab

    def switch_to_tab(self, tab: ProjectTab):
        if tab is self.active_tab:
            return
        self.active_tab = tab
        self.view.setScene(tab.scene)
        self._update_title()
        self.title_bar.tab_strip.refresh_active(tab)

    def close_tab(self, tab: ProjectTab):
        # Every open tab has a snapshot file in this run's session folder
        # (see push_undo_state) — drop it so a closed tab can't reappear on
        # the next restore prompt.
        autosave.discard_snapshot(self._session_dir, tab.tab_id)
        was_active = tab is self.active_tab
        self.tabs.remove(tab)
        if not self.tabs:
            # Closing the last tab leaves a fresh, empty Untitled tab behind
            # rather than closing the window (confirmed product decision).
            replacement = self._create_tab()
            replacement.untitled_number = self._next_untitled_number()
            self.active_tab = replacement
            self.view.setScene(replacement.scene)
            self.push_undo_state()
        elif was_active:
            self.active_tab = self.tabs[-1]
            self.view.setScene(self.active_tab.scene)
        self._update_title()
        self._refresh_tab_strip()

    def _refresh_tab_strip(self):
        self.title_bar.tab_strip.rebuild(self.tabs, self.active_tab)

    def reorder_tab(self, tab: ProjectTab, new_index: int):
        """Move ``tab`` to ``new_index`` in the tab order — purely a UI
        arrangement, not part of undo history."""
        if tab not in self.tabs:
            return
        self.tabs.remove(tab)
        new_index = max(0, min(new_index, len(self.tabs)))
        self.tabs.insert(new_index, tab)
        self._refresh_tab_strip()

    # ── Active-tab state proxies ─────────────────────────────────────────────
    # Scene items, popups and other windows-adjacent code reach through
    # win.scene / win.connections / win._block_undo_push directly (some of
    # them as plain attribute writes, e.g. `win._block_undo_push = True`) —
    # these properties keep every such call site working unchanged while the
    # actual state lives on whichever ProjectTab is active.

    @property
    def scene(self) -> NodeScene:
        return self.active_tab.scene

    @property
    def connections(self) -> List[Connection]:
        return self.active_tab.connections

    @property
    def _block_undo_push(self) -> bool:
        return self.active_tab._block_undo_push

    @_block_undo_push.setter
    def _block_undo_push(self, value: bool):
        self.active_tab._block_undo_push = value

    @property
    def _dirty(self) -> bool:
        return self.active_tab.dirty

    @_dirty.setter
    def _dirty(self, value: bool):
        self.active_tab.dirty = value

    @property
    def _project_path(self) -> Optional[str]:
        return self.active_tab.project_path

    @_project_path.setter
    def _project_path(self, value: Optional[str]):
        self.active_tab.project_path = value

    @property
    def history(self) -> List[dict]:
        return self.active_tab.history

    @history.setter
    def history(self, value: List[dict]):
        self.active_tab.history = value

    @property
    def history_index(self) -> int:
        return self.active_tab.history_index

    @history_index.setter
    def history_index(self, value: int):
        self.active_tab.history_index = value

    # ── Windows chrome ────────────────────────────────────────────────────────
    # The window is frameless (see __init__), so Windows itself no longer
    # knows this is "a window" for drag/resize/edge-snap purposes. Intercepting
    # WM_NCHITTEST and answering with the same hit codes a native title bar
    # would gives all of that back — including Aero edge-snap — for free.

    def _apply_rounded_corners(self):
        apply_rounded_corners(self)

    def nativeEvent(self, eventType, message):
        if sys.platform == "win32" and eventType == b"windows_generic_MSG":
            try:
                result = self._hit_test_native_message(int(message))
                if result is not None:
                    return True, result
            except Exception as exc:
                log_and_explain("Native hit-test failed", exc)
        return super().nativeEvent(eventType, message)

    def _hit_test_native_message(self, message_ptr: int) -> Optional[int]:
        import ctypes
        from ctypes import wintypes

        class _MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD), ("pt", wintypes.POINT),
            ]

        msg = _MSG.from_address(message_ptr)
        if msg.message != _WM_NCHITTEST:
            return None

        x = ctypes.c_short(msg.lParam & 0xFFFF).value
        y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
        local = self.mapFromGlobal(QPoint(x, y))

        if self.isMaximized() or self.isFullScreen():
            # Deliberately NOT returning HTCAPTION here: a frameless window
            # never gets the real Win32 WS_MAXIMIZE style, so Windows' own
            # "drag the caption to restore-and-follow-the-cursor" behavior
            # never kicks in for it — the click would just be swallowed.
            # Returning None instead lets Qt's own mouse events reach
            # TitleBarWidget, which restores the window and drags it itself.
            return None

        # A click inside the title bar's own rect is resolved by ITS content
        # first — a tab or a window-control button always wins there, even
        # within the resize margin below — otherwise a narrow window makes
        # its own close button unreachable (the last few px of a full-width
        # control sit inside the right-edge resize band).
        if 0 <= local.y() < TITLE_BAR_HEIGHT:
            tb_pos = self.title_bar.mapFrom(self, local)
            if self.title_bar.rect().contains(tb_pos):
                if self.title_bar.is_drag_region(tb_pos):
                    return _HTCAPTION
                return None

        m = TITLE_BAR_RESIZE_MARGIN
        rect = self.rect()
        on_left = local.x() <= m
        on_right = local.x() >= rect.width() - m
        on_top = local.y() <= m
        on_bottom = local.y() >= rect.height() - m

        if on_top and on_left:
            return _HTTOPLEFT
        if on_top and on_right:
            return _HTTOPRIGHT
        if on_bottom and on_left:
            return _HTBOTTOMLEFT
        if on_bottom and on_right:
            return _HTBOTTOMRIGHT
        if on_left:
            return _HTLEFT
        if on_right:
            return _HTRIGHT
        if on_top:
            return _HTTOP
        if on_bottom:
            return _HTBOTTOM
        return None

    # ── Node creation ─────────────────────────────────────────────────────────

    def _add_start_node(self, scene: Optional[NodeScene] = None):
        scene = scene if scene is not None else self.scene
        if not any(isinstance(i, StartNode) for i in scene.items()):
            node = StartNode()
            node.setPos(START_NODE_INITIAL_X, START_NODE_INITIAL_Y)
            scene.addItem(node)

    def add_command_node(self, pos: QPointF, cmd_def: dict):
        node = CommandNode(cmd_def)
        node.setPos(pos)
        self.scene.addItem(node)
        self.push_undo_state()
        return node

    def add_param_node(self, pos: QPointF, creation_data: dict):
        node = build_param_node(creation_data)
        node.setPos(pos)
        self.scene.addItem(node)
        self.push_undo_state()
        return node

    # ── Selection commands ────────────────────────────────────────────────────

    def select_all(self):
        selectable = [
            item for item in self.scene.items()
            if isinstance(item, (MetaNode, Connection, GroupFrameItem))
        ]
        if not selectable:
            return
        all_selected = all(item.isSelected() for item in selectable)
        for item in selectable:
            item.setSelected(not all_selected)

    def keyPressEvent(self, event):
        key = event.key()
        # Fallback to the physical keyboard letter (QWERTY layout equivalent) using
        # native virtual key codes on Windows. VK_A (0x41) through VK_Z (0x5A) align
        # perfectly with Qt.Key_A through Qt.Key_Z, providing layout-independence.
        nvk = event.nativeVirtualKey()
        if 0x41 <= nvk <= 0x5A:
            key = nvk

        mods = event.modifiers()
        if key == KEY_SPAWN_MENU:
            cursor_in_scene = self.view.mapToScene(
                self.view.mapFromGlobal(QCursor.pos()))
            self.scene.show_node_creation_menu(cursor_in_scene, QCursor.pos())
            event.accept()
        elif key == KEY_DELETE:
            self._delete_selected_items()
            event.accept()
        elif key == KEY_SAVE and mods == MOD_CTRL:
            self.save_project()
            event.accept()
        elif key == KEY_SAVE and mods == MOD_CTRL_SHIFT:
            self.save_project(save_as=True)
            event.accept()
        elif key == KEY_OPEN and mods == MOD_CTRL:
            self.load_project()
            event.accept()
        elif key == KEY_COPY and mods == MOD_CTRL:
            self.copy_nodes()
            event.accept()
        elif key == KEY_PASTE and mods == MOD_CTRL:
            self.paste_nodes()
            event.accept()
        elif key == KEY_UNDO and mods == MOD_CTRL:
            self.undo()
            event.accept()
        elif key == KEY_UNDO and mods == MOD_CTRL_SHIFT:
            self.redo()
            event.accept()
        elif key == KEY_REDO and mods == MOD_CTRL:
            self.redo()
            event.accept()
        elif key == KEY_TOGGLE_GRID and mods == MOD_NONE:
            self.scene.grid_visible = not getattr(self.scene, "grid_visible", True)
            self.scene.update()
            event.accept()
        elif key == KEY_FIT_VIEW and mods == MOD_NONE:
            selected_nodes = [i for i in self.scene.selectedItems() if isinstance(i, MetaNode)]
            target = selected_nodes or [i for i in self.scene.items() if isinstance(i, MetaNode)]
            if target:
                self.view.frame_content(target)
            event.accept()
        elif key == KEY_RENAME_NODE and mods == MOD_NONE:
            selected = [
                i for i in self.scene.selectedItems()
                if hasattr(i, "_begin_rename")
            ]
            if len(selected) == 1:
                selected[0]._begin_rename()
                self.view.setFocus(Qt.OtherFocusReason)
            event.accept()
        elif key == KEY_SELECT_ALL and mods == MOD_CTRL:
            self.select_all()
            event.accept()
        elif key == KEY_GROUP and mods == MOD_CTRL:
            self.group_selected_nodes()
            event.accept()
        elif key == KEY_DUPLICATE and mods == MOD_CTRL:
            self.duplicate_nodes()
            event.accept()
        elif key == KEY_FULLSCREEN:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()
            event.accept()
        # Language-cycle (KEY_PREV_LANG/KEY_NEXT_LANG) is handled globally by
        # ui/global_hotkeys.py's QApplication-level event filter instead of
        # here, so it works no matter which window (this one, an error
        # dialog, the session-restore prompt) currently has focus.
        else:
            super().keyPressEvent(event)

    def _delete_selected_items(self):
        items_to_delete = self.scene.selectedItems()
        if not items_to_delete:
            return

        self._block_undo_push = True
        try:
            for item in items_to_delete:
                if isinstance(item, Connection):
                    dest_node = item.dest.meta_node if item.dest else None
                    self.scene.removeItem(item)
                    if item in self.connections:
                        self.connections.remove(item)
                    if dest_node:
                        dest_node._refresh_connections()
                elif isinstance(item, GroupFrameItem):
                    self.scene.removeItem(item)
                elif isinstance(item, MetaNode) and not item.is_protected:
                    self._delete_node_bridging_exec(item, items_to_delete)
        finally:
            self._block_undo_push = False
        self.push_undo_state()

    def _delete_node_bridging_exec(self, item: MetaNode, items_to_delete: list):
        """Remove a node; if it sat mid-chain, bridge its exec neighbours."""
        incoming_exec = None
        outgoing_exec = None
        for c in self.connections:
            if c.is_exec:
                if c.dest.meta_node is item:
                    incoming_exec = c
                elif c.source.meta_node is item:
                    outgoing_exec = c

        if incoming_exec and outgoing_exec:
            left_node = incoming_exec.source.meta_node
            right_node = outgoing_exec.dest.meta_node
            if left_node not in items_to_delete and right_node not in items_to_delete:
                self.scene.enforce_connection_rules(incoming_exec.source, outgoing_exec.dest)
                new_conn = Connection(incoming_exec.source, outgoing_exec.dest)
                self.scene.addItem(new_conn)
                self.connections.append(new_conn)
                left_node._refresh_connections()
                right_node._refresh_connections()

        dead_connections = [
            c for c in self.connections
            if c.source.meta_node is item or c.dest.meta_node is item
        ]
        other_nodes = set()
        for conn in dead_connections:
            other_node = conn.dest.meta_node if conn.source.meta_node is item else conn.source.meta_node
            if other_node and other_node not in items_to_delete:
                other_nodes.add(other_node)
            self.scene.removeItem(conn)
            if conn in self.connections:
                self.connections.remove(conn)
        self.scene.removeItem(item)
        for n in other_nodes:
            n._refresh_connections()

    # ── Clipboard / duplicate ─────────────────────────────────────────────────

    def _serialize_selection(self) -> Optional[dict]:
        payload = serialize_graph(self.scene, self.connections, only_selected=True)
        if not payload["nodes"] and not payload["groups"]:
            return None
        return payload

    def copy_nodes(self):
        payload = self._serialize_selection()
        if payload is None:
            return
        try:
            QApplication.clipboard().setText(CLIPBOARD_PAYLOAD_PREFIX + json.dumps(payload))
        except Exception as exc:
            log_and_explain("Failed to copy nodes to clipboard", exc)

    def paste_nodes(self):
        clipboard_text = QApplication.clipboard().text()
        if not clipboard_text.startswith(CLIPBOARD_PAYLOAD_PREFIX):
            return
        try:
            payload = json.loads(clipboard_text[len(CLIPBOARD_PAYLOAD_PREFIX):])
        except Exception as exc:
            log_and_explain("Failed to parse nodes from clipboard", exc)
            return
        anchor = self.view.mapToScene(self.view.mapFromGlobal(QCursor.pos()))
        self._insert_payload(payload, anchor)

    def duplicate_nodes(self):
        payload = self._serialize_selection()
        if payload is None:
            return
        anchor = self.view.mapToScene(self.view.viewport().rect().center())
        self._insert_payload(
            payload, anchor + QPointF(DUPLICATE_OFFSET_X, DUPLICATE_OFFSET_Y))

    def _insert_payload(self, payload: dict, anchor: QPointF):
        """Materialize a selection payload centered at ``anchor``, selected."""
        center = payload_center(payload)
        if center is None:
            return
        self._block_undo_push = True
        try:
            self.scene.clearSelection()
            materialize_graph(self.scene, self.connections, payload,
                              offset=anchor - center, select_created=True)
        finally:
            self._block_undo_push = False
        self.push_undo_state()

    def group_selected_nodes(self):
        selected = [i for i in self.scene.selectedItems() if isinstance(i, MetaNode)]
        if not selected:
            return
        rect = selected[0].sceneBoundingRect()
        for node in selected[1:]:
            rect = rect.united(node.sceneBoundingRect())
        rect = rect.adjusted(-GROUP_FRAME_PAD_LEFT, -GROUP_FRAME_PAD_TOP,
                             GROUP_FRAME_PAD_RIGHT, GROUP_FRAME_PAD_BOTTOM)
        frame = GroupFrameItem(rect, title=t("logical_group_title"))
        self.scene.addItem(frame)
        frame.commit_members(force_all=True)

        self.push_undo_state()

    # ── Project persistence ───────────────────────────────────────────────────

    def save_project(self, save_as: bool = False):
        path = self.active_tab.project_path
        if save_as or not path:
            path, _ = QFileDialog.getSaveFileName(
                self, t("dialog_save_project"), path or "", t("dialog_project_filter"))
            if not path:
                return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(serialize_graph(self.scene, self.connections), f, indent=2)
        except Exception as exc:
            MessageDialog.critical(self, t("dialog_save_error_title"), log_and_explain(t("msg_save_failed"), exc))
            return
        self.active_tab.project_path = path
        self.active_tab.untitled_number = None
        self._set_dirty(False)
        self._refresh_tab_strip()

    def load_project(self):
        path, _ = QFileDialog.getOpenFileName(self, t("dialog_open_project"), "", t("dialog_project_filter"))
        if not path:
            return
        tab = self.active_tab
        if tab.project_path is not None or tab.dirty:
            # The current tab already holds something — Notepad-style: Open
            # gets a new tab unless the current one is still a blank Untitled.
            self.new_tab(path)
            return
        self._load_into_tab(tab, path)  # handles its own undo baseline/dirty
        self._refresh_tab_strip()

    def _load_into_tab(self, tab: ProjectTab, path: str) -> bool:
        """Load ``path`` into ``tab``, which must already be the active tab.

        A loaded project is the new undo baseline: undo must not cross back
        into whatever the tab held before. Returns False (and leaves the tab
        untouched) if the file can't be read.
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            self._restore(payload, restore_selection=False)
        except Exception as exc:
            MessageDialog.critical(self, t("dialog_load_error_title"), log_and_explain(t("msg_load_failed"), exc))
            return False
        tab.project_path = path
        tab.untitled_number = None
        tab.history = []
        tab.history_index = -1
        self.push_undo_state()
        self._set_dirty(False)
        return True

    def _restore(self, payload: dict, restore_selection: bool):
        self._linked_group = []
        clear_graph(self.scene, self.connections)
        materialize_graph(self.scene, self.connections, payload,
                          restore_selection=restore_selection)

    # ── Undo / redo ───────────────────────────────────────────────────────────

    def get_project_state(self) -> dict:
        return serialize_graph(self.scene, self.connections, include_selection=True)

    def set_project_state(self, payload: dict):
        self._block_undo_push = True
        try:
            self._restore(payload, restore_selection=True)
        finally:
            self._block_undo_push = False

    def push_undo_state(self):
        tab = self.active_tab
        if tab._block_undo_push:
            return
        state = self.get_project_state()
        if tab.history_index >= 0 and tab.history[tab.history_index] == state:
            return
        had_history = tab.history_index >= 0  # the very first push is the baseline, not an edit
        tab.history = tab.history[:tab.history_index + 1]
        tab.history.append(state)
        if len(tab.history) > UNDO_HISTORY_LIMIT:
            tab.history.pop(0)
        tab.history_index = len(tab.history) - 1
        if had_history:
            self._set_dirty(True)
        # Snapshot immediately rather than waiting for the periodic timer —
        # otherwise anything added/edited within the last autosave interval
        # is lost if the app closes uncleanly before the next tick.
        self._write_tab_snapshot(tab)

    def undo(self):
        tab = self.active_tab
        if tab.history_index > 0:
            tab.history_index -= 1
            self.set_project_state(tab.history[tab.history_index])

    def redo(self):
        tab = self.active_tab
        if tab.history_index < len(tab.history) - 1:
            tab.history_index += 1
            self.set_project_state(tab.history[tab.history_index])

    # ── Window title and language ─────────────────────────────────────────────

    def _set_dirty(self, dirty: bool):
        self.active_tab.dirty = dirty
        self._update_title()
        if hasattr(self, "title_bar"):
            self.title_bar.tab_strip.refresh_tab(self.active_tab)
        if hasattr(self, "_session_dir"):
            # Keeps the on-disk snapshot's dirty flag in sync even when the
            # change didn't come through push_undo_state (e.g. save_project
            # clearing dirty without pushing a new undo entry) — otherwise a
            # cleanly-saved tab could still restore marked dirty next launch.
            self._write_tab_snapshot(self.active_tab)

    def _update_title(self):
        tab = self.active_tab
        if tab.project_path:
            name = os.path.basename(tab.project_path)
        elif tab.untitled_number:
            name = f"{t('untitled')} {tab.untitled_number}"
        else:
            name = t("untitled")
        self.setWindowTitle(f"{t('window_title_prefix')}{name}{'*' if tab.dirty else ''}")
        self.setWindowIcon(language_flag_icon(get_language()))

    def cycle_language(self, direction: int):
        """
        Cycle the UI language through the available languages in gettext.
        Why: Allows translators and testers to check different locales on keypress.
        """
        langs = available_languages()
        if not langs:
            return
        curr = get_language()
        try:
            idx = langs.index(curr)
        except ValueError:
            idx = 0
        set_language(langs[(idx + direction) % len(langs)])

        # Refresh every open tab in the new language: rebuilding each graph
        # re-resolves every translatable default title and button label, not
        # just the ones in the currently active tab.
        self._update_title()
        original_active = self.active_tab
        for tab in self.tabs:
            self.active_tab = tab
            self.set_project_state(self.get_project_state())
        self.active_tab = original_active

    # ── Chain execution ───────────────────────────────────────────────────────

    def execute_chain(self):
        graph = scene_to_graph_model(self.scene, self.connections)
        chain = build_exec_chain(graph)
        if not chain or len(chain) < 2:
            MessageDialog.warning(self, t("dialog_incomplete_chain_title"),
                                t("msg_incomplete_chain_desc"))
            return
        tokens = build_launch_tokens(chain, graph)
        try:
            launch(tokens)
        except Exception as exc:
            MessageDialog.critical(
                self, t("dialog_launch_error_title"),
                log_and_explain(t("msg_launch_failed"), exc),
            )
