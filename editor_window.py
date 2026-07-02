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
    QApplication, QFileDialog, QMainWindow, QMessageBox, QVBoxLayout, QWidget,
)
from PyQt5.QtGui import QColor, QCursor
from PyQt5.QtCore import QPointF, Qt

from localization import available_languages, get_language, set_language, t
from configuration import (
    WINDOW_BACKGROUND_COLOR, UNDO_HISTORY_LIMIT,
    DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_CAPTION_COLOR, DWMWA_TEXT_COLOR,
    TEXT_COLOR,
    KEY_SPAWN_MENU, KEY_DELETE, KEY_SAVE, KEY_OPEN,
    KEY_COPY, KEY_PASTE, KEY_UNDO, KEY_REDO,
    KEY_TOGGLE_GRID, KEY_FIT_VIEW, KEY_FULLSCREEN,
    KEY_RENAME_NODE, KEY_SELECT_ALL, KEY_GROUP, KEY_DUPLICATE,
    KEY_PREV_LANG, KEY_NEXT_LANG,
    VK_OEM_LEFT_BRACKET, VK_OEM_RIGHT_BRACKET,
    PREV_LANG_LAYOUT_CHARS, NEXT_LANG_LAYOUT_CHARS,
    MOD_NONE, MOD_CTRL, MOD_CTRL_SHIFT,
    GROUP_FRAME_PAD_LEFT, GROUP_FRAME_PAD_TOP,
    GROUP_FRAME_PAD_RIGHT, GROUP_FRAME_PAD_BOTTOM,
    WINDOW_INITIAL_X, WINDOW_INITIAL_Y, WINDOW_INITIAL_WIDTH, WINDOW_INITIAL_HEIGHT,
    START_NODE_INITIAL_X, START_NODE_INITIAL_Y,
    DUPLICATE_OFFSET_X, DUPLICATE_OFFSET_Y,
    CLIPBOARD_PAYLOAD_PREFIX,
)
from diagnostics import log_and_explain
from command_database import load_command_database

from view import GraphicsView
from scene import NodeScene
from graph_items import Connection, GroupFrameItem, MetaNode
from command_nodes import CommandNode, StartNode
from graph_serialization import (
    build_param_node, clear_graph, materialize_graph, payload_center,
    serialize_graph,
)
from chain_execution import build_exec_chain, build_launch_tokens, launch
from flag_icon import language_flag_icon


class NodeEditorWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setGeometry(WINDOW_INITIAL_X, WINDOW_INITIAL_Y, WINDOW_INITIAL_WIDTH, WINDOW_INITIAL_HEIGHT)
        self.setStyleSheet(f"QMainWindow{{background:{WINDOW_BACKGROUND_COLOR};}}")

        self.command_categories, self.command_defs = load_command_database()

        self.connections: List[Connection] = []
        self._linked_group: List[MetaNode] = []      # selected same-type nodes under linked editing
        self._active_field_key: Optional[str] = None  # which field key the linked group mirrors
        self._focus_event_counter: int = 0            # serializes focus in/out to settle the active group
        self._project_path: Optional[str] = None      # file backing the current graph, if saved
        self._dirty = False                           # unsaved edits since last save/load
        self._update_title()

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        self.scene = NodeScene(self)
        self.scene.nodeEditorWindow = self
        self.view = GraphicsView()
        self.view.setScene(self.scene)
        layout.addWidget(self.view)

        self._add_start_node()

        self._block_undo_push = False
        self.history: List[dict] = []
        self.history_index: int = -1
        self.push_undo_state()

        self._apply_windows_theme()

    # ── Windows chrome ────────────────────────────────────────────────────────

    @staticmethod
    def _to_colorref(hex_color: str) -> int:
        c = QColor(hex_color)
        return c.red() | (c.green() << 8) | (c.blue() << 16)

    def _apply_windows_theme(self):
        if sys.platform != "win32":
            return
        try:
            from ctypes import windll, byref, sizeof, c_int
            hwnd = int(self.winId())
            apply = lambda attr, val: windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, byref(c_int(val)), sizeof(c_int))
            apply(DWMWA_USE_IMMERSIVE_DARK_MODE, 1)
            apply(DWMWA_CAPTION_COLOR, self._to_colorref(WINDOW_BACKGROUND_COLOR))
            apply(DWMWA_TEXT_COLOR, self._to_colorref(TEXT_COLOR))
        except Exception as exc:
            log_and_explain("Windows title bar theming unavailable", exc)

    # ── Node creation ─────────────────────────────────────────────────────────

    def _add_start_node(self):
        if not any(isinstance(i, StartNode) for i in self.scene.items()):
            node = StartNode()
            node.setPos(START_NODE_INITIAL_X, START_NODE_INITIAL_Y)
            self.scene.addItem(node)

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
        elif (key == KEY_PREV_LANG or nvk == VK_OEM_LEFT_BRACKET
              or event.text() in PREV_LANG_LAYOUT_CHARS) and mods == MOD_NONE:
            self.cycle_language(-1)
            event.accept()
        elif (key == KEY_NEXT_LANG or nvk == VK_OEM_RIGHT_BRACKET
              or event.text() in NEXT_LANG_LAYOUT_CHARS) and mods == MOD_NONE:
            self.cycle_language(1)
            event.accept()
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
        path = self._project_path
        if save_as or not path:
            path, _ = QFileDialog.getSaveFileName(
                self, t("dialog_save_project"), path or "", t("dialog_project_filter"))
            if not path:
                return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(serialize_graph(self.scene, self.connections), f, indent=2)
        except Exception as exc:
            QMessageBox.critical(self, t("dialog_save_error_title"), log_and_explain(t("msg_save_failed"), exc))
            return
        self._project_path = path
        self._set_dirty(False)

    def load_project(self):
        path, _ = QFileDialog.getOpenFileName(self, t("dialog_open_project"), "", t("dialog_project_filter"))
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            self._restore(payload, restore_selection=False)
        except Exception as exc:
            QMessageBox.critical(self, t("dialog_load_error_title"), log_and_explain(t("msg_load_failed"), exc))
            self._add_start_node()
            return
        # A loaded project is the new baseline: undo must not cross back into the old graph.
        self._project_path = path
        self.history = []
        self.history_index = -1
        self.push_undo_state()
        self._set_dirty(False)

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
        if getattr(self, "_block_undo_push", False):
            return
        state = self.get_project_state()
        if self.history_index >= 0 and self.history[self.history_index] == state:
            return
        had_history = self.history_index >= 0  # the very first push is the baseline, not an edit
        self.history = self.history[:self.history_index + 1]
        self.history.append(state)
        if len(self.history) > UNDO_HISTORY_LIMIT:
            self.history.pop(0)
        self.history_index = len(self.history) - 1
        if had_history:
            self._set_dirty(True)

    def undo(self):
        if self.history_index > 0:
            self.history_index -= 1
            self.set_project_state(self.history[self.history_index])

    def redo(self):
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self.set_project_state(self.history[self.history_index])

    # ── Window title and language ─────────────────────────────────────────────

    def _set_dirty(self, dirty: bool):
        self._dirty = dirty
        self._update_title()

    def _update_title(self):
        name = os.path.basename(self._project_path) if self._project_path else t("untitled")
        self.setWindowTitle(f"{t('window_title_prefix')}{name}{'*' if self._dirty else ''}")
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

        # Refresh the UI in the new language: rebuilding the graph re-resolves
        # every translatable default title and button label.
        self._update_title()
        self.set_project_state(self.get_project_state())

    # ── Chain execution ───────────────────────────────────────────────────────

    def execute_chain(self):
        nodes = [i for i in self.scene.items() if isinstance(i, MetaNode)]
        chain = build_exec_chain(nodes, self.connections)
        if not chain or len(chain) < 2:
            QMessageBox.warning(self, t("dialog_incomplete_chain_title"),
                                t("msg_incomplete_chain_desc"))
            return
        tokens = build_launch_tokens(chain, self.connections)
        try:
            launch(tokens)
        except Exception as exc:
            QMessageBox.critical(
                self, t("dialog_launch_error_title"),
                log_and_explain(t("msg_launch_failed"), exc),
            )
