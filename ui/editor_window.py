"""editor_window.py — Main Editor Window

The interaction shell: keyboard routing, selection-wide commands, the undo
stack, project dialogs and the dirty-state title. Graph snapshots live in
graph_serialization, chain launching in core.graph_executor — the window
only orchestrates them.
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
from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt, QThread, QTimer

from localization import available_languages, get_language, set_language, t
from configuration import (
    WINDOW_BACKGROUND_COLOR, UNDO_HISTORY_LIMIT, SAVED_UNDO_HISTORY_LIMIT, CLOSED_TABS_HISTORY_LIMIT,
    WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT,
    TITLE_BAR_HEIGHT, TITLE_BAR_RESIZE_MARGIN,
    AUTOSAVE_INTERVAL_MS,
    GROUP_FRAME_PAD_LEFT, GROUP_FRAME_PAD_TOP,
    GROUP_FRAME_PAD_RIGHT, GROUP_FRAME_PAD_BOTTOM,
    WINDOW_INITIAL_X, WINDOW_INITIAL_Y, WINDOW_INITIAL_WIDTH, WINDOW_INITIAL_HEIGHT,
    START_NODE_INITIAL_X, START_NODE_INITIAL_Y,
    DUPLICATE_OFFSET_X, DUPLICATE_OFFSET_Y,
    CLIPBOARD_PAYLOAD_PREFIX,
    DWMWCP_ROUND, DWMWCP_DONOTROUND, WINDOW_CORNER_RADIUS,
)
from ui.keymap import (
    KEY_SPAWN_MENU, KEY_DELETE, KEY_SAVE, KEY_OPEN, KEY_NEW_TAB, KEY_NEW_TAB_ALT,
    KEY_DUPLICATE_TAB, KEY_CLOSE_TAB, KEY_CLOSE_OTHERS, KEY_CLOSE_RIGHT, KEY_CLOSE_LEFT,
    KEY_REOPEN_TAB, KEY_NEXT_TAB, KEY_EXECUTE,
    KEY_COPY, KEY_PASTE, KEY_UNDO, KEY_REDO,
    KEY_TOGGLE_GRID, KEY_FIT_VIEW, KEY_FULLSCREEN,
    KEY_RENAME_NODE, KEY_SELECT_ALL, KEY_GROUP, KEY_DUPLICATE,
    KEY_TOGGLE_PROJECT_INPUTS_PANEL, KEY_TOGGLE_PROJECT_INPUTS_PANEL_ALT,
    MOD_NONE, MOD_CTRL, MOD_CTRL_SHIFT,
)
from diagnostics import log_and_explain

try:
    # The realityscan pack is optional like any other discovered pack
    # (Доктрина III.1) — a system without it installed must still launch,
    # not crash on this import, so the command palette just starts empty
    # instead (still fully usable: any other installed pack still merges in
    # below, and RC's own nodes simply aren't offered).
    from packs.realityscan.command_database import load_command_database
except ImportError as _rc_import_error:
    log_and_explain("RealityCapture pack not installed — command palette starts empty",
                    _rc_import_error)

    def load_command_database():
        return {}, []

from ui.view import GraphicsView
from ui.scene import NodeScene
from ui.graph_items import Connection, GroupFrameItem, MetaNode
from ui.command_nodes import CommandNode, StartNode
from ui.project_tab import ProjectTab
from ui.title_bar import TitleBarWidget
from ui.graph_serialization import (
    build_param_node, clear_graph, materialize_graph, payload_center,
    scene_to_graph_model, serialize_graph, try_apply_state_diff,
)
from ui.project_inputs_panel import ProjectInputsPanel
from core.graph_executor import GraphExecutor, build_exec_chain
from core.pack_catalog import flatten_commands, load_pack_catalog, merge_catalogs
from core.pack_executor import build_executor_factory, pack_cacheable_lookup, pack_version_lookup
from core.pack_registry import default_pack_search_dirs, discover_packs
from ui.graph_execution_worker import GraphExecutionWorker
from core import autosave, app_prefs, session
from ui.flag_icon import language_flag_icon
from ui.session_restore_dialog import SessionRestoreDialog
from ui.message_dialog import MessageDialog
from ui.window_chrome import (
    apply_rounded_corners, show_system_menu, apply_immersive_dark_mode,
    extend_frame_into_client_area,
)
from ui.theme import TITLE_BAR_QSS

# WM_NCHITTEST result codes used by NodeEditorWindow.nativeEvent to give a
# frameless window back its native resize/move/edge-snap behavior on Windows.
_WM_NCHITTEST = 0x0084
_HTCLIENT = 1
_HTCAPTION = 2
_HTLEFT, _HTRIGHT, _HTTOP, _HTBOTTOM = 10, 11, 12, 15
_HTTOPLEFT, _HTTOPRIGHT, _HTBOTTOMLEFT, _HTBOTTOMRIGHT = 13, 14, 16, 17
# Reported for the maximize button's own rect: this is the one hit-test
# value that makes Windows 11 show its native Snap Layouts flyout on hover —
# entirely DWM-driven once WM_NCHITTEST answers this consistently, nothing
# else to draw. WM_NCLBUTTONDOWN/UP carry it back as wParam once we do.
_HTMAXBUTTON = 9
_WM_NCLBUTTONDOWN = 0x00A1
_WM_NCLBUTTONUP = 0x00A2
# Windows' native caption-drag modal loop starts on WM_NCLBUTTONDOWN(HTCAPTION)
# and ends on WM_EXITSIZEMOVE — the only two messages left for us to see
# either side of it, since DefWindowProc owns everything in between (see
# NodeEditorWindow._native_caption_drag_active).
_WM_EXITSIZEMOVE = 0x0232


class NodeEditorWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        # On Windows, we keep the native title bar and borders in window flags,
        # but remove their visuals in WM_NCCALCSIZE. This enables native edge-snapping (Aero Snap),
        # Win+Arrow keys, and native shadows/rounded corners. On other platforms, we fall back
        # to Qt.FramelessWindowHint.
        if sys.platform != "win32":
            self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setGeometry(WINDOW_INITIAL_X, WINDOW_INITIAL_Y, WINDOW_INITIAL_WIDTH, WINDOW_INITIAL_HEIGHT)
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet("QMainWindow{background: transparent;}")
        self._apply_rounded_corners()
        if sys.platform == "win32":
            apply_immersive_dark_mode(self)
            extend_frame_into_client_area(self)

        installed_packs = discover_packs(default_pack_search_dirs())

        # RealityCapture keeps its own richer loader (falls back to a small
        # built-in command set when no local RC docs were parsed — see
        # packs/realityscan/command_database.py). Any other installed
        # pack contributes only what its own commands_source JSON declares
        # (core/pack_catalog.py) — no pack Python code runs to build the
        # palette (Доктрина III.1: only core/pack_executor.py ever runs a
        # pack's code, and only in its own process).
        rc_categories, self.command_defs = load_command_database()
        self.command_categories = {"RealityScan": rc_categories}
        
        other_packs = [p for p in installed_packs if p.manifest.pack_id != "realityscan"]
        if other_packs:
            for p in other_packs:
                pack_cat = load_pack_catalog(p)
                if pack_cat:
                    self.command_categories[p.manifest.display_name] = pack_cat
                    self.command_defs.extend(flatten_commands(pack_cat))

        # Segment-by-pack incremental execution (Доктрина V) — one
        # GraphExecutor per window, its cache lives for the process lifetime
        # (see core/graph_executor.py's own docstring on why not on disk yet).
        self._graph_executor = GraphExecutor(
            executor_factory=build_executor_factory(installed_packs),
            pack_version_for=pack_version_lookup(installed_packs),
            is_pack_cacheable=pack_cacheable_lookup(installed_packs),
        )
        # Set only while execute_chain()'s worker/thread are alive — see
        # _on_execution_finished/_on_execution_failed, which both clear it.
        self._execution_thread: Optional[QThread] = None
        self._execution_worker: Optional[GraphExecutionWorker] = None

        self._linked_group: List[MetaNode] = []      # selected same-type nodes under linked editing
        self._active_field_key: Optional[str] = None  # which field key the linked group mirrors
        self._focus_event_counter: int = 0            # serializes focus in/out to settle the active group
        # True from a native caption drag's WM_NCLBUTTONDOWN(HTCAPTION) to
        # its WM_EXITSIZEMOVE — see nativeEvent's handling of both. Windows
        # drives the entire drag itself in that window (DefWindowProc's own
        # modal move loop; our own mouseMoveEvent/mouseReleaseEvent in
        # title_bar.py never run), so this is the only way to notice the
        # drag ended and still offer the custom bottom-of-screen snap zone
        # (_snap_to_edge_if_dropped_there) — a resize's own WM_EXITSIZEMOVE
        # must NOT trigger it, hence tracking specifically a caption drag.
        self._native_caption_drag_active: bool = False

        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.title_bar = TitleBarWidget(self)
        layout.addWidget(self.title_bar)

        self.view = GraphicsView()
        layout.addWidget(self.view, 1)

        # Floats above the view instead of sharing a layout row with it — see
        # ProjectInputsPanel's docstring for why (dock-area/title-bar
        # collision, and a layout-managed panel resizing the view — and
        # re-tiling the whole visible scene — on every show/hide).
        self.project_inputs_panel = ProjectInputsPanel(self, central)
        self.project_inputs_panel.raise_()
        self._reposition_project_inputs_panel()

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
        # (tab_id, envelope) pairs (see core/autosave.py) for recently closed
        # tabs, most recent last — reopen_closed_tab() (Ctrl+Shift+T) pops
        # from here.
        self._closed_tabs: List[tuple] = []
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
        self._update_window_rounding(self.isMaximized())

    # ── Autosave / whole-session recovery ────────────────────────────────────

    def _write_tab_snapshot(self, tab: ProjectTab, state: Optional[dict] = None):
        """Queue tab's current graph for a snapshot write. ``state`` is a
        graph payload the caller already has on hand (push_undo_state always
        computes one for the undo history) — passing it through avoids
        re-serializing the whole scene a second time for the same edit.
        The actual disk write runs off the UI thread (see
        core.autosave.write_snapshot_async) so it never stalls interaction.
        """
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
        graph = state if state is not None else serialize_graph(tab.scene, tab.connections)
        history, history_index = self._trimmed_history(tab)
        autosave.write_snapshot_async(self._session_dir, tab.tab_id, tab.project_path,
                                       tab.dirty, tab_index, graph,
                                       history=history, history_index=history_index)

    @staticmethod
    def _trimmed_history(tab: ProjectTab):
        """A window of at most SAVED_UNDO_HISTORY_LIMIT entries around
        ``tab.history_index`` — bounding what gets written to disk on every
        autosave. The live in-memory ``tab.history`` can hold up to
        UNDO_HISTORY_LIMIT (100) full graph snapshots; persisting all of
        them on every single edit would mean writing up to 100x a
        many-thousand-node graph's size each time. Centering the kept window
        on the current position (rather than always keeping the tail)
        guarantees the just-saved state is always inside it, so the returned
        index is always valid.
        """
        history = tab.history
        limit = SAVED_UNDO_HISTORY_LIMIT
        total = len(history)
        if total <= limit:
            return history, tab.history_index
        start = max(0, min(tab.history_index - limit // 2, total - limit))
        return history[start:start + limit], tab.history_index - start

    def _run_autosave_pass(self):
        # A periodic safety net — every edit already snapshots immediately
        # (see push_undo_state), this just re-covers any tab that somehow
        # missed that (e.g. a bulk operation run under _block_undo_push).
        for tab in self.tabs:
            self._write_tab_snapshot(tab)

    def closeEvent(self, event):
        # One last flush so a crash or an OS-initiated shutdown right after
        # this doesn't lose edits the periodic timer hadn't gotten to yet.
        # autosave.flush() blocks until every write queued above (and by
        # anything before it, e.g. the last edit's push_undo_state) has
        # actually landed on disk — writes run on a background thread now,
        # so without this a just-closed window's last snapshot could still
        # be sitting in the queue when the process exits.
        self._run_autosave_pass()
        autosave.flush()
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
            restored.append(self._restore_tab_from_envelope(tab_id, envelope))

        if not restored:
            return
        self.switch_to_tab(restored[0])
        self._update_title()
        self._refresh_tab_strip()

    def _restore_tab_from_envelope(self, tab_id: str, envelope: dict) -> ProjectTab:
        """Rebuild one tab from an autosave envelope (see core/autosave.py) —
        shared by whole-session restore and reopen_closed_tab()."""
        dirty = bool(envelope.get("dirty", False))
        path = autosave.resolve_manual_path(envelope)

        tab = self._create_tab()
        tab.tab_id = tab_id

        # Attach this tab's scene to the real, on-screen view *before*
        # rebuilding its graph — exactly what new_tab()/_load_into_tab()
        # does for a normal File > Open (switch_to_tab(), then load).
        # Flipping self.active_tab without switching the view first leaves
        # every field widget in a background tab constructed while its scene
        # was never the one actually on screen — Qt only fully polishes a
        # stylesheet-styled widget's colors the first time it becomes part of
        # a shown window, and it can stick with stale/black text forever
        # after, which is exactly what a plain Open (built on an
        # already-visible tab) never hits.
        self.switch_to_tab(tab)
        if "graph" in envelope:
            self._restore(envelope["graph"], restore_selection=False)
        # Note: deliberately NOT forcing a QApplication.processEvents()
        # flush here. It was tried as a belt-and-suspenders complement to
        # switch_to_tab() above, but pumping the event loop mid-restore let
        # stray deferred callbacks (e.g. NodeComboBox's
        # QTimer.singleShot(0, self._safe_refresh) from hidePopup) fire
        # against a tab's widgets while a *later* tab in the same restore
        # loop was still being torn down/rebuilt — crashing with
        # "NodeComboBox object has no attribute 'node'" on next launch.
        # switch_to_tab() alone (making each tab briefly the real, on-screen
        # scene while its graph is restored) already gets these widgets a
        # proper paint pass without that risk.
        tab.project_path = path
        tab.untitled_number = None if path else self._next_untitled_number()
        saved_history = envelope.get("history")
        if saved_history:
            # Crash/session recovery carries the undo history across the
            # restart (see core.autosave.write_snapshot) — unlike a manual
            # File > Open, which intentionally starts a fresh undo baseline
            # (see _load_into_tab), a restored session is meant to look
            # exactly like nothing happened, Ctrl+Z included.
            tab.history = saved_history
            tab.history_index = max(0, min(
                envelope.get("history_index", len(saved_history) - 1),
                len(saved_history) - 1))
        else:
            tab.history = []
            tab.history_index = -1
            self.push_undo_state()
        # A dirty tab keeps its unsaved-edit mark; a clean one just reflects
        # whatever was last snapshotted (in sync with disk).
        self._set_dirty(dirty)
        if tab is self.active_tab:
            self.project_inputs_panel.reload()
        return tab

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
        self.project_inputs_panel.reload()

    def switch_to_adjacent_tab(self, direction: int):
        """Ctrl+Tab / Ctrl+Shift+Tab — cycle to the next/previous project, wrapping around."""
        if len(self.tabs) < 2:
            return
        idx = self.tabs.index(self.active_tab)
        self.switch_to_tab(self.tabs[(idx + direction) % len(self.tabs)])

    def close_tab(self, tab: ProjectTab):
        # Grab the tab's own up-to-date snapshot (see push_undo_state) before
        # dropping it, so Ctrl+Shift+T can bring it back later — same
        # envelope shape whole-session restore already reads.
        envelope = autosave.load_snapshot(self._session_dir, tab.tab_id)
        if envelope is not None:
            self._closed_tabs.append((tab.tab_id, envelope))
            del self._closed_tabs[:-CLOSED_TABS_HISTORY_LIMIT]
        # Every open tab has a snapshot file in this run's session folder —
        # drop it so a closed tab can't reappear on the next restore prompt.
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
            self.project_inputs_panel.reload()
        self._update_title()
        self._refresh_tab_strip()

    def reopen_closed_tab(self):
        """Ctrl+Shift+T — bring back the most recently closed tab, Chrome-
        style. No-op if nothing's been closed this run."""
        if not self._closed_tabs:
            return
        tab_id, envelope = self._closed_tabs.pop()
        tab = self._restore_tab_from_envelope(tab_id, envelope)
        self.switch_to_tab(tab)
        self._update_title()
        self._refresh_tab_strip()

    def close_other_tabs(self, keep: ProjectTab):
        for tab in [t for t in self.tabs if t is not keep]:
            self.close_tab(tab)

    def close_tabs_to_the_right(self, tab: ProjectTab):
        if tab not in self.tabs:
            return
        for other in self.tabs[self.tabs.index(tab) + 1:]:
            self.close_tab(other)

    def close_tabs_to_the_left(self, tab: ProjectTab):
        if tab not in self.tabs:
            return
        # Copy the slice because closing a tab removes it from self.tabs
        for other in self.tabs[:self.tabs.index(tab)][:]:
            self.close_tab(other)

    def duplicate_tab(self, tab: ProjectTab):
        """Open a new tab with a copy of ``tab``'s current graph — an
        in-memory clone, not tied to ``tab``'s save file (the copy starts as
        an unsaved Untitled tab, same as a manual Save As would give you)."""
        payload = serialize_graph(tab.scene, tab.connections)
        new = self._create_tab()
        new.untitled_number = self._next_untitled_number()
        self.switch_to_tab(new)
        self._restore(payload, restore_selection=False)
        self.push_undo_state()
        self._set_dirty(True)
        self.reorder_tab(new, self.tabs.index(tab) + 1)

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
        # Why: on Windows, DWM would normally auto-round/auto-square this window's
        # corners since we keep WS_CAPTION, but Qt's showMaximized() never gives
        # it a real WS_MAXIMIZE style, so that auto-detection isn't reliable — see
        # _update_window_rounding, which sets the DWM preference explicitly on
        # every state change instead. On other platforms (truly frameless), we
        # apply the initial rounding here since there's no OS default to rely on.
        if sys.platform != "win32":
            apply_rounded_corners(self)

    def nativeEvent(self, eventType, message):
        if sys.platform == "win32" and eventType == b"windows_generic_MSG":
            try:
                import ctypes
                from ctypes import wintypes

                class _MSG(ctypes.Structure):
                    _fields_ = [
                        ("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                        ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                        ("time", wintypes.DWORD), ("pt", wintypes.POINT),
                    ]

                msg = _MSG.from_address(int(message))

                # Handle WM_NCACTIVATE: on activation changes (minimize, restore,
                # alt-tab), Windows' default handling repaints the real non-client
                # caption — briefly flashing the native (accent-colored) title bar
                # through our WM_NCCALCSIZE-hidden one. Passing lParam=-1 to
                # DefWindowProc is the documented way to keep the activation-state
                # bookkeeping but suppress that repaint.
                if msg.message == 0x0086:  # WM_NCACTIVATE
                    user32 = ctypes.windll.user32
                    user32.DefWindowProcW.restype = ctypes.c_ssize_t
                    user32.DefWindowProcW.argtypes = [
                        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_ssize_t,
                    ]
                    result = user32.DefWindowProcW(msg.hwnd, msg.message, msg.wParam, -1)
                    return True, result

                # Handle WM_NCCALCSIZE
                if msg.message == 0x0083:  # WM_NCCALCSIZE
                    if msg.wParam:
                        # If window is maximized, adjust margins to prevent client area
                        # from spilling over the screen edges (cutoff).
                        #
                        # Deliberately IsZoomed(hwnd) here, not self.isMaximized():
                        # dragging the title bar to the top edge triggers Windows'
                        # own native Aero Snap maximize (see _native_drag_handles_this
                        # in title_bar.py — a non-maximized window's drag is handled
                        # entirely natively), which resizes the real HWND straight
                        # through DefWindowProc. Qt's own isMaximized() flag only
                        # updates reactively afterward (via WM_SIZE), so it can still
                        # read False while THIS WM_NCCALCSIZE — fired mid-transition —
                        # is being processed, skipping the border compensation below
                        # and leaving the client area overhanging the screen edges
                        # (visibly clipped). Clicking the maximize button doesn't hit
                        # this, since showMaximized() sets Qt's flag before the native
                        # resize happens. IsZoomed() asks Windows directly, so it's
                        # correct regardless of which path triggered the transition.
                        if ctypes.windll.user32.IsZoomed(msg.hwnd):
                            class RECT(ctypes.Structure):
                                _fields_ = [
                                    ("left", ctypes.c_long), ("top", ctypes.c_long),
                                    ("right", ctypes.c_long), ("bottom", ctypes.c_long),
                                ]
                            class NCCALCSIZE_PARAMS(ctypes.Structure):
                                _fields_ = [
                                    ("rgrc", RECT * 3), ("lppos", ctypes.c_void_p),
                                ]
                            params = NCCALCSIZE_PARAMS.from_address(msg.lParam)
                            user32 = ctypes.windll.user32
                            # SM_CXSIZEFRAME = 32, SM_CYSIZEFRAME = 33, SM_CXPADDEDBORDER = 92
                            border_w = user32.GetSystemMetrics(32) + user32.GetSystemMetrics(92)
                            border_h = user32.GetSystemMetrics(33) + user32.GetSystemMetrics(92)
                            params.rgrc[0].top += border_h
                            params.rgrc[0].left += border_w
                            params.rgrc[0].right -= border_w
                            params.rgrc[0].bottom -= border_h
                        return True, 0
                    return True, 0

                # Once WM_NCHITTEST reports HTMAXBUTTON for the maximize
                # button's rect (see _hit_test_native_message), Windows
                # treats clicks there as non-client messages instead of
                # ordinary ones — the button's own Qt click handler never
                # fires for them, so the actual toggle has to happen here.
                if msg.message == _WM_NCLBUTTONUP and msg.wParam == _HTMAXBUTTON:
                    self.title_bar._toggle_maximize()
                    return True, 0
                if msg.message == _WM_NCLBUTTONDOWN and msg.wParam == _HTMAXBUTTON:
                    return True, 0  # consumed; the actual toggle happens on button-up, like a normal click

                # Observe only — must NOT consume this one, or Windows never
                # starts its own native caption-drag loop at all (see
                # _native_caption_drag_active's docstring in __init__). Also
                # the one point to catch "picked a bottom-snapped window back
                # up to drag it": that click hits HTCAPTION and goes straight
                # to DefWindowProc's native loop, bypassing TitleBarWidget's
                # own mousePressEvent entirely (same reason WM_EXITSIZEMOVE
                # was needed for the bottom-drop zone itself).
                if msg.message == _WM_NCLBUTTONDOWN and msg.wParam == _HTCAPTION:
                    self._native_caption_drag_active = True
                    x = ctypes.c_short(msg.lParam & 0xFFFF).value
                    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                    self.title_bar._begin_drag_unsnapping_bottom(QPoint(x, y))

                if msg.message == _WM_EXITSIZEMOVE and self._native_caption_drag_active:
                    self._native_caption_drag_active = False
                    # Only the bottom zone, not the full
                    # _snap_to_edge_if_dropped_there: Aero Snap already
                    # handled top/left/right natively for this drag before
                    # WM_EXITSIZEMOVE ever fired, so re-running those would
                    # double-apply on top of what Windows just did — bottom
                    # is the one zone with no native equivalent.
                    self.title_bar._snap_to_bottom_if_dropped_there(QCursor.pos())

                result = self._hit_test_native_message(int(message))
                if result is not None:
                    return True, result
            except Exception as exc:
                log_and_explain("Native event handling failed", exc)
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

        # Cleared by default — the one branch below that finds the cursor
        # genuinely over the maximize button sets it back to True before
        # returning HTMAXBUTTON. Every early return past this point (full
        # screen, below the title bar, elsewhere in the title bar) means
        # "not hovering it" just as much as an explicit miss would, so this
        # covers all of them from one place instead of every return site.
        self.title_bar.set_max_button_native_hover(False)

        if self.isFullScreen():
            return None

        # A click inside the title bar's own rect is resolved by ITS content
        # first — a tab or a window-control button always wins there, even
        # within the resize margin below — otherwise a narrow window makes
        # its own close button unreachable (the last few px of a full-width
        # control sit inside the right-edge resize band).
        if 0 <= local.y() < TITLE_BAR_HEIGHT:
            tb_pos = self.title_bar.mapFrom(self, local)
            if self.title_bar.rect().contains(tb_pos):
                # Reporting HTMAXBUTTON for the maximize button's own rect —
                # not just letting it fall through to a plain HTCLIENT click
                # like every other title bar control — is what makes Windows
                # 11 show its native Snap Layouts flyout on hover; DWM does
                # the rest, nothing else to draw for that part. But it also
                # means Windows stops delivering ordinary mouse-move/click
                # there as client-area messages, so the button's own Qt
                # :hover paint state has to be kept in sync by hand (see
                # set_max_button_native_hover) and the actual toggle has to
                # be wired to WM_NCLBUTTONUP instead of the button's click
                # signal (see nativeEvent).
                max_btn = self.title_bar.max_btn
                over_max_btn = max_btn.rect().contains(max_btn.mapFrom(self.title_bar, tb_pos))
                if over_max_btn:
                    self.title_bar.set_max_button_native_hover(True)
                    return _HTMAXBUTTON
                # Only claim the drag region natively when NOT maximized. A
                # maximized frameless window never gets the real Win32
                # WS_MAXIMIZE style, so Windows' native "drag the caption to
                # restore, tracking the cursor" gesture computes the restored
                # window's position using its own (wrong) assumptions about
                # nonclient/caption metrics — it visibly desyncs, snapping the
                # window to a stale/mismatched position for a frame. Returning
                # None here instead makes this a plain HTCLIENT click, so
                # TitleBarWidget's own mousePressEvent/mouseMoveEvent (see
                # _native_drag_handles_this) do the restore-and-drag manually,
                # which is consistent everywhere.
                if self.title_bar.is_drag_region(tb_pos) and not self.isMaximized():
                    return _HTCAPTION
                return None

        if self.isMaximized():
            return None

        m = TITLE_BAR_RESIZE_MARGIN
        rect = self.rect()
        on_left = local.x() <= m
        on_right = local.x() >= rect.width() - m
        on_top = local.y() <= m
        on_bottom = local.y() >= rect.height() - m

        # A click that lands on a canvas scrollbar must never be stolen by a
        # resize hit code — the scrollbar and the resize band fight over the
        # same pixel column/row.  Map the scrollbars' view-local geometry into
        # window coordinates and bail out early if the cursor is over either.
        # This is the single authoritative guard; no other callsite needs it
        # (ст. 14.3: fix in the one common source, not at each resize branch).
        mgr = getattr(getattr(self, "view", None), "_scrollbar_manager", None)
        if mgr is not None and (on_right or on_bottom or on_left or on_top):
            view = self.view
            view_origin = view.mapTo(self, QPoint(0, 0))
            for bar in (mgr.vbar, mgr.hbar):
                if not bar.isVisible():
                    continue
                bg = bar.geometry()  # view-local
                # translate to window-local
                bar_rect_win = bg.translated(view_origin)
                if bar_rect_win.contains(local):
                    return None  # HTCLIENT — let Qt process the scrollbar click

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
        elif key == KEY_NEW_TAB_ALT and mods == MOD_CTRL:
            self.new_tab()
            event.accept()
        elif key == KEY_NEW_TAB and mods == MOD_CTRL_SHIFT:
            self.new_tab()
            event.accept()
        elif key == KEY_DUPLICATE_TAB and mods == MOD_CTRL_SHIFT:
            self.duplicate_tab(self.active_tab)
            event.accept()
        elif key == KEY_CLOSE_TAB and mods == MOD_CTRL_SHIFT:
            self.close_tab(self.active_tab)
            event.accept()
        elif key == KEY_CLOSE_OTHERS and mods == MOD_CTRL_SHIFT:
            self.close_other_tabs(self.active_tab)
            event.accept()
        elif key == KEY_CLOSE_RIGHT and mods == MOD_CTRL_SHIFT:
            self.close_tabs_to_the_right(self.active_tab)
            event.accept()
        elif key == KEY_CLOSE_LEFT and mods == MOD_CTRL_SHIFT:
            self.close_tabs_to_the_left(self.active_tab)
            event.accept()
        elif key == KEY_REOPEN_TAB and mods == MOD_CTRL_SHIFT:
            self.reopen_closed_tab()
            event.accept()
        elif key == KEY_NEXT_TAB and mods == MOD_CTRL:
            self.switch_to_adjacent_tab(1)
            event.accept()
        elif key == KEY_NEXT_TAB and mods == MOD_CTRL_SHIFT:
            self.switch_to_adjacent_tab(-1)
            event.accept()
        elif key == KEY_EXECUTE and mods == MOD_NONE:
            self.execute_chain()
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
        elif key == KEY_TOGGLE_PROJECT_INPUTS_PANEL and mods == MOD_CTRL:
            panel = self.project_inputs_panel
            panel.setVisible(not panel.isVisibleTo(self))
            event.accept()
        elif key == KEY_TOGGLE_PROJECT_INPUTS_PANEL_ALT and mods == MOD_NONE:
            panel = self.project_inputs_panel
            panel.setVisible(not panel.isVisibleTo(self))
            event.accept()
        elif key == KEY_FULLSCREEN:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()
            event.accept()
        elif mods == Qt.AltModifier and key == Qt.Key_Space:
            # Alt+Space is the native OS shortcut to show the system window
            # menu. Intercepting it here shows the native Win32 system menu
            # for this frameless window at its top-left caption corner.
            show_system_menu(self, self.mapToGlobal(QPoint(0, TITLE_BAR_HEIGHT)))
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
        self._center_on_last_added_node()
        return True

    def _center_on_last_added_node(self) -> None:
        """Scroll the canvas to whichever node was created most recently.

        MetaNode.uid is a monotonic counter assigned at construction and
        preserved verbatim through save/load (_observe_uid fast-forwards the
        allocator past it), so the loaded node with the highest uid is
        exactly the one the project's author added last — regardless of the
        arbitrary order scene.items() returns them in.
        """
        nodes = [i for i in self.scene.items() if isinstance(i, MetaNode)]
        if not nodes:
            return
        newest = max(nodes, key=lambda n: n.uid)
        self.view.centerOn(newest)

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
        # Snapshot immediately rather than waiting for the periodic timer —
        # otherwise anything added/edited within the last autosave interval
        # is lost if the app closes uncleanly before the next tick. Passing
        # `state` through (already computed above for the undo history)
        # instead of letting either call re-serialize the scene: this used
        # to run serialize_graph() twice per edit — once here, once again
        # inside _set_dirty()'s own snapshot write.
        if had_history:
            self._set_dirty(True, state=state)
        else:
            self._write_tab_snapshot(tab, state)
        self.project_inputs_panel.reload()

    def undo(self):
        tab = self.active_tab
        if tab.history_index > 0:
            current = self.get_project_state()
            tab.history_index -= 1
            self._apply_history_state(current, tab.history[tab.history_index])

    def redo(self):
        tab = self.active_tab
        if tab.history_index < len(tab.history) - 1:
            current = self.get_project_state()
            tab.history_index += 1
            self._apply_history_state(current, tab.history[tab.history_index])

    def _apply_history_state(self, current_state: dict, target_state: dict):
        """Move to ``target_state`` for an undo/redo step. Tries the in-place
        patch first (see try_apply_state_diff) — on a scene with thousands
        of nodes, a plain property edit (move/rename/recolor/value change)
        would otherwise cost a full clear+rebuild of every node's widgets
        just to reach a state that differs from the current one by a single
        field. Falls back to the always-correct full rebuild for anything
        structural (added/removed node or wire, vector split/merge, X/Y/Z
        expand/collapse) that the fast path declines to touch.
        """
        if try_apply_state_diff(self.scene, self.connections, current_state, target_state):
            self.project_inputs_panel.reload()
            return
        self.set_project_state(target_state)
        self.project_inputs_panel.reload()

    # ── Window title and language ─────────────────────────────────────────────

    def _set_dirty(self, dirty: bool, *, state: Optional[dict] = None):
        self.active_tab.dirty = dirty
        self._update_title()
        if hasattr(self, "title_bar"):
            self.title_bar.tab_strip.refresh_tab(self.active_tab)
        if hasattr(self, "_session_dir"):
            # Keeps the on-disk snapshot's dirty flag in sync even when the
            # change didn't come through push_undo_state (e.g. save_project
            # clearing dirty without pushing a new undo entry) — otherwise a
            # cleanly-saved tab could still restore marked dirty next launch.
            # ``state``, when the caller already has one on hand
            # (push_undo_state), skips re-serializing the same scene twice.
            self._write_tab_snapshot(self.active_tab, state)

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

        # Refresh every open tab in the new language: each node/frame
        # re-resolves its own translatable text in place (see
        # MetaNode.retranslate) instead of the graph being serialized,
        # torn down and rebuilt from scratch — on a large scene that used to
        # mean recreating every embedded widget just to change some labels.
        self._update_title()
        for tab in self.tabs:
            for item in tab.scene.items():
                if isinstance(item, (MetaNode, GroupFrameItem)):
                    item.retranslate()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_project_inputs_panel()

    def leaveEvent(self, event):
        # Safety net for the maximize button's native-hover flag (see
        # _hit_test_native_message): once the cursor leaves the window
        # entirely, WM_NCHITTEST stops arriving for it altogether, so the
        # "cleared by default on every hit test" logic there never gets a
        # last call to actually clear it.
        self.title_bar.set_max_button_native_hover(False)
        super().leaveEvent(event)

    def _reposition_project_inputs_panel(self):
        """Keep the floating panel pinned to the view's left edge, full height.

        Only y/height ever come from the window — width is whatever the user
        last dragged the resize grip to (see ProjectInputsPanel/_ResizeGrip),
        untouched here.
        """
        panel = self.project_inputs_panel
        top = self.title_bar.height()
        panel.setGeometry(0, top, panel.width(), self.centralWidget().height() - top)

    def changeEvent(self, event):
        if event.type() == QEvent.WindowStateChange:
            self._update_window_rounding(self.isMaximized())
            was_minimized = bool(event.oldState() & Qt.WindowMinimized)
            if was_minimized and not self.isMinimized() and sys.platform == "win32":
                self._reassert_native_chrome()
        super().changeEvent(event)

    def _reassert_native_chrome(self):
        # Why: after restoring from minimized, Windows can leave the non-client
        # region stale — a sliver of the real caption, painted in our own
        # caption color, lingers where the tab strip should be — until
        # something forces it to recompute. SWP_FRAMECHANGED forces an
        # immediate WM_NCCALCSIZE re-evaluation without moving or resizing
        # the window.
        try:
            from ctypes import windll
            hwnd = int(self.winId())
            SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x2, 0x1, 0x4, 0x10, 0x20
            flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
            windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, flags)
        except Exception as exc:
            log_and_explain("Failed to force non-client recompute after restore", exc)

    def _update_window_rounding(self, square_corners: bool):
        """square_corners is True both when the window is really maximized
        and when TitleBarWidget wants square corners for another reason (a
        manual half-screen edge-snap — see set_corners_square()); either way
        the corners should look square, so this treats them identically.

        Corner rounding is DWM's job on Windows, full stop: our own Qt
        content stays a plain rectangle, and DWMWA_WINDOW_CORNER_PREFERENCE
        clips the whole window from the outside — exactly like a real
        native window, with exactly one rounding curve involved. Two
        earlier attempts at ALSO rounding our own widgets on top of that
        (a QSS radius on the title bar, then a title bar mask) each ended
        up compounding with DWM's own curve instead of replacing it —
        visibly squashing the corner, because DWM's clip shape and ours
        never quite agreed. There's no DWM off Windows, so the title bar
        mask + central widget QSS radius are the fallback there instead.
        """
        is_native_rounding = sys.platform == "win32"
        radius = 0 if (square_corners or is_native_rounding) else WINDOW_CORNER_RADIUS

        if is_native_rounding:
            apply_rounded_corners(self, DWMWCP_DONOTROUND if square_corners else DWMWCP_ROUND)

        if hasattr(self, "title_bar") and self.title_bar:
            self.title_bar.setStyleSheet(TITLE_BAR_QSS)
            self.title_bar.set_corner_radius(radius)

        central = self.centralWidget()
        if central:
            central.setStyleSheet(
                f"#centralWidget {{ background: {WINDOW_BACKGROUND_COLOR}; "
                f"border-bottom-left-radius: {radius}px; border-bottom-right-radius: {radius}px; }}"
            )

    def set_corners_square(self, square: bool) -> None:
        """Force the window's corner rounding on/off regardless of real
        Qt window state. Used by TitleBarWidget's manual edge-snap (a plain
        setGeometry() to a screen half, which unlike showMaximized() raises
        no WindowStateChange for _update_window_rounding to react to on its
        own) so a snapped window still gets flush, square corners."""
        self._update_window_rounding(square)

    def remember_normal_geometry(self) -> None:
        """Cache the window's current geometry so a later restore-from-
        maximized drag can use it instead of Qt's own normalGeometry().
        Call this right before showMaximized() (see TitleBarWidget's
        _toggle_maximize / _snap_to_edge_if_dropped_there), while the window
        is still in its real, non-maximized geometry.

        Why: diagnostic logging during a maximize->drag-restore->maximize->...
        cycle showed Qt's normalGeometry() itself getting corrupted to a
        near-fullscreen rect after repeated transitions on this frameless
        window — showNormal() doesn't always finish updating the native
        HWND's geometry synchronously, and Qt appears to cache that stale,
        still-maximized-sized rect as if it were the legitimate "normal"
        geometry. Keeping our own independent snapshot, taken proactively
        before the transition even starts, sidesteps that bookkeeping.
        """
        if not self.isMaximized():
            self._remembered_normal_geometry = self.geometry()

    def normal_geometry_for_restore(self):
        """The geometry to restore to for a maximized-window drag — see
        remember_normal_geometry(). Falls back to Qt's normalGeometry() if
        nothing was ever remembered (shouldn't happen once every showMaximized()
        call site remembers first, but keeps this safe to call regardless)."""
        return getattr(self, "_remembered_normal_geometry", None) or self.normalGeometry()

    # ── Chain execution ───────────────────────────────────────────────────────

    def execute_chain(self):
        if self._execution_thread is not None:
            return  # already running — the launch button is disabled meanwhile, this is belt-and-suspenders
        graph = scene_to_graph_model(self.scene, self.connections)
        chain = build_exec_chain(graph)
        if not chain or len(chain) < 2:
            MessageDialog.warning(self, t("dialog_incomplete_chain_title"),
                                t("msg_incomplete_chain_desc"))
            return

        self._execution_worker = GraphExecutionWorker(self._graph_executor, graph)
        self._execution_thread = QThread(self)
        self._execution_worker.moveToThread(self._execution_thread)
        self._execution_thread.started.connect(self._execution_worker.run)
        self._execution_worker.finished.connect(self._on_execution_finished)
        self._execution_worker.failed.connect(self._on_execution_failed)
        self._execution_worker.finished.connect(self._execution_thread.quit)
        self._execution_worker.failed.connect(self._execution_thread.quit)
        self._execution_thread.finished.connect(self._cleanup_execution_thread)
        self._set_launch_controls_running(True)
        self._execution_thread.start()

    def cancel_chain_execution(self):
        """Not wired to any control yet — a future run-tracking UI (once
        there's more than one pack to juggle) will call this. The mechanism
        it needs already works: GraphExecutionWorker.cancel_event reaches
        core/pack_executor.py's poll loop, which kills the pack's whole
        process tree, not just stops waiting for it."""
        if self._execution_worker is not None:
            self._execution_worker.cancel_event.set()

    def _on_execution_finished(self, runs):
        failed = next((run for run in runs if not run.result.ok), None)
        if failed:
            MessageDialog.critical(
                self, t("dialog_launch_error_title"),
                log_and_explain(t("msg_launch_failed"), RuntimeError(failed.result.error)),
            )

    def _on_execution_failed(self, exc):
        MessageDialog.critical(
            self, t("dialog_launch_error_title"),
            log_and_explain(t("msg_launch_failed"), exc),
        )

    def _cleanup_execution_thread(self):
        self._execution_thread = None
        self._execution_worker = None
        self._set_launch_controls_running(False)

    def _set_launch_controls_running(self, running: bool) -> None:
        for tab in self.tabs:
            start_node = next((i for i in tab.scene.items() if isinstance(i, StartNode)), None)
            if start_node:
                start_node.set_launch_running(running)
