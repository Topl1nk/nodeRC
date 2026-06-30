"""
canvas.py — Scene, View, Menu and Main Window
"""

from __future__ import annotations
import sys
import subprocess
import json
import os
from typing import List, Optional, Dict, Any

from localization import t

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QMessageBox, QFileDialog, QApplication, QVBoxLayout
)
from PyQt5.QtGui import QCursor, QColor, QIcon, QPixmap, QPainter, QPen
from PyQt5.QtCore import Qt, QPointF, QRectF

from configuration import (
    RC_EXECUTABLE, COMMAND_DB_JSON,
    WINDOW_BACKGROUND_COLOR, UNDO_HISTORY_LIMIT,
    DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_CAPTION_COLOR, DWMWA_TEXT_COLOR,
    TEXT_COLOR, VECTOR_PARAM_TYPES,
    KEY_SPAWN_MENU, KEY_DELETE, KEY_SAVE, KEY_OPEN,
    KEY_COPY, KEY_PASTE, KEY_UNDO, KEY_REDO,
    KEY_TOGGLE_GRID, KEY_FIT_VIEW, KEY_FULLSCREEN,
    KEY_RENAME_NODE, KEY_SELECT_ALL, KEY_GROUP, KEY_DUPLICATE,
    KEY_PREV_LANG, KEY_NEXT_LANG,
    MOD_NONE, MOD_CTRL, MOD_CTRL_SHIFT,
    GROUP_FRAME_PAD_LEFT, GROUP_FRAME_PAD_TOP,
    GROUP_FRAME_PAD_RIGHT, GROUP_FRAME_PAD_BOTTOM,
    WINDOW_INITIAL_X, WINDOW_INITIAL_Y, WINDOW_INITIAL_WIDTH, WINDOW_INITIAL_HEIGHT,
    START_NODE_INITIAL_X, START_NODE_INITIAL_Y,
    GROUP_FRAME_DEFAULT_WIDTH, GROUP_FRAME_DEFAULT_HEIGHT,
    DUPLICATE_OFFSET_X, DUPLICATE_OFFSET_Y,
)
from diagnostics import log_and_explain
from nodeRC import builtin_command_defaults

from view import GraphicsView
from scene import NodeScene
from nodes_base import Connection, MetaNode, _BaseParamNode, GroupFrameItem
from nodes_concrete import (
    StartNode, CommandNode, PARAM_NODE_TYPES, group_xyz_params, StringParamNode, EnumParamNode
)



# ── NodeEditorWindow ──────────────────────────────────────────────────────────

class NodeEditorWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setGeometry(WINDOW_INITIAL_X, WINDOW_INITIAL_Y, WINDOW_INITIAL_WIDTH, WINDOW_INITIAL_HEIGHT)
        self.setStyleSheet(f"QMainWindow{{background:{WINDOW_BACKGROUND_COLOR};}}")

        self.command_categories: Dict[str, Any] = {}
        self.command_defs: List[dict] = []
        self._load_command_database()

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

    def _load_command_database(self):
        if os.path.exists(COMMAND_DB_JSON):
            with open(COMMAND_DB_JSON, "r", encoding="utf-8") as f:
                self.command_categories = json.load(f)
            for subsections in self.command_categories.values():
                for commands in subsections.values():
                    self.command_defs.extend(commands)
        else:
            defaults = builtin_command_defaults()
            self.command_defs = defaults
            self.command_categories = {"Commands": {"__root__": defaults}}

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
        node = self._build_param_node(creation_data)
        node.setPos(pos)
        self.scene.addItem(node)
        self.push_undo_state()
        return node

    # ── Project (de)serialization ─────────────────────────────────────────────
    # One source of truth shared by save/load, clipboard and undo. Each path only
    # supplies the parts that genuinely differ: absolute vs relative position,
    # whether selection is part of the snapshot, and the destination of the bytes.

    def _build_param_node(self, creation_data: dict) -> _BaseParamNode:
        ptype = creation_data.get("param_type", "string")
        node_class = PARAM_NODE_TYPES.get(ptype, StringParamNode)
        name   = creation_data.get("display") or creation_data.get("name")
        
        # Translate default titles dynamically when language switches
        if name:
            from localization import get_all_translations, t
            title_key = "param_path_title" if ptype in ("filepath", "dirpath", "path") else f"param_{ptype}_title"
            if name in get_all_translations(title_key):
                name = t(title_key)
                creation_data["display"] = name
                if "name" in creation_data:
                    creation_data["name"] = name
                    
        values = creation_data.get("values", [])
        if node_class is EnumParamNode and values:
            node = node_class(name, values) if name else node_class(values=values)
        else:
            node = node_class(name) if name else node_class()
        node.creation_data = creation_data
        return node

    def _serialize_node(self, node: MetaNode) -> dict:
        record = {"type": type(node).__name__, **node.serialize_payload()}
        if node.color_override():
            record["color"] = node.color_override()
            if node.color_only_header():
                record["color_only_header"] = True
        return record

    def _deserialize_node(self, record: dict, pos: QPointF) -> Optional[MetaNode]:
        node_type = record["type"]
        if node_type == "StartNode":
            node = StartNode()
        elif node_type == "CommandNode":
            node = CommandNode(record["cmd_def"])
        elif node_type.endswith("ParamNode"):
            node = self._build_param_node(
                record.get("creation_data", {"param_type": "string", "display": "value"}))
        else:
            return None
        node.setPos(pos)
        self.scene.addItem(node)
        if record.get("color"):
            node.set_color(record["color"],
                           only_header=bool(record.get("color_only_header")),
                           record_undo=False)
        if isinstance(node, _BaseParamNode) and record.get("current_value") is not None:
            node.set_value_state(record["current_value"])
        return node

    def _serialize_connections(self, node_id_map: Dict[MetaNode, int],
                               include_selection: bool = False) -> List[dict]:
        records = []
        for conn in self.connections:
            src_id = node_id_map.get(conn.source.meta_node)
            dst_id = node_id_map.get(conn.dest.meta_node)
            if src_id is None or dst_id is None:
                continue
            record = {
                "src_node": src_id, "src_socket": conn.source.sock_def.name,
                "dst_node": dst_id, "dst_socket": conn.dest.sock_def.name,
            }
            if include_selection:
                record["selected"] = conn.isSelected()
            records.append(record)
        return records

    def _rebuild_connections(self, records: List[dict], id_to_node: Dict[int, MetaNode],
                             restore_selection: bool = False):
        for record in records:
            # Isolate per connection: a malformed wire must not abort the load.
            try:
                src_node = id_to_node.get(record["src_node"])
                dst_node = id_to_node.get(record["dst_node"])
                if not (src_node and dst_node):
                    continue
                src_sock = src_node.get_socket(record["src_socket"])
                dst_sock = dst_node.get_socket(record["dst_socket"])
                if not (src_sock and dst_sock):
                    continue
                self.scene._enforce_connection_rules(src_sock, dst_sock)
                conn = Connection(src_sock, dst_sock)
                self.scene.addItem(conn)
                self.connections.append(conn)
                if restore_selection and record.get("selected", False):
                    conn.setSelected(True)
            except Exception as exc:
                log_and_explain("Skipped unreadable connection", exc)
                continue

    def _capture(self, include_selection: bool) -> dict:
        node_id_map: Dict[MetaNode, int] = {}
        node_records = []
        group_records = []
        for idx, item in enumerate(self.scene.items()):
            if isinstance(item, MetaNode):
                node_id_map[item] = idx
                pos = item.scenePos()
                record = {"id": idx, "x": pos.x(), "y": pos.y(), **self._serialize_node(item)}
                if include_selection:
                    record["selected"] = item.isSelected()
                node_records.append(record)
            elif isinstance(item, GroupFrameItem):
                pos = item.pos()
                rect = item.rect()
                record = {
                    "title": item.title,
                    "x": pos.x(),
                    "y": pos.y(),
                    "width": rect.width(),
                    "height": rect.height(),
                    "color": item.color(),
                }
                if include_selection:
                    record["selected"] = item.isSelected()
                group_records.append(record)
        return {
            "nodes": node_records,
            "connections": self._serialize_connections(node_id_map, include_selection),
            "groups": group_records,
        }

    def _restore(self, payload: dict, restore_selection: bool):
        self._linked_group = []
        for item in [i for i in self.scene.items() if isinstance(i, (MetaNode, Connection, GroupFrameItem))]:
            self.scene.removeItem(item)
        self.connections.clear()

        id_to_node: Dict[int, MetaNode] = {}
        for record in payload.get("nodes", []):
            # Isolate per node: one corrupt record must not discard the whole project.
            try:
                node = self._deserialize_node(record, QPointF(record["x"], record["y"]))
            except Exception as exc:
                log_and_explain(f"Skipped unreadable node ({record.get('type', 'unknown')})", exc)
                continue
            if node is None:
                continue
            id_to_node[record["id"]] = node
            if restore_selection and record.get("selected", False):
                node.setSelected(True)

        for record in payload.get("groups", []):
            try:
                rect = QRectF(0, 0, record.get("width", GROUP_FRAME_DEFAULT_WIDTH), record.get("height", GROUP_FRAME_DEFAULT_HEIGHT))
                frame = GroupFrameItem(rect, title=record.get("title", t("default_group_title")))
                frame.setPos(record["x"], record["y"])
                if record.get("color"):
                    frame.set_color(record["color"], record_undo=False)
                self.scene.addItem(frame)
                if restore_selection and record.get("selected", False):
                    frame.setSelected(True)
            except Exception as exc:
                log_and_explain("Skipped unreadable group frame", exc)

        self._rebuild_connections(payload.get("connections", []), id_to_node, restore_selection)
        for node in id_to_node.values():
            node._refresh_connections()
        self.scene.recalculate_scene_rect()
        for item in self.scene.items():
            if isinstance(item, GroupFrameItem):
                item.commit_members(force_all=True)

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
            self.scene._show_node_creation_menu(cursor_in_scene, QCursor.pos())
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
        elif (key == KEY_PREV_LANG or nvk == 0xDB or event.text() in ('[', '{', 'х', 'Х', 'ї', 'Ї')) and mods == MOD_NONE:
            self.cycle_language(-1)
            event.accept()
        elif (key == KEY_NEXT_LANG or nvk == 0xDD or event.text() in (']', '}', 'ъ', 'Ъ', 'і', 'І')) and mods == MOD_NONE:
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
                            self.scene._enforce_connection_rules(incoming_exec.source, outgoing_exec.dest)
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
        finally:
            self._block_undo_push = False
        self.push_undo_state()

    def copy_nodes(self):
        selected_nodes = [i for i in self.scene.selectedItems()
                          if isinstance(i, MetaNode) and not isinstance(i, StartNode)]
        selected_groups = [i for i in self.scene.selectedItems() if isinstance(i, GroupFrameItem)]
        if not selected_nodes and not selected_groups:
            return

        all_items = selected_nodes + selected_groups
        center_x = sum(item.scenePos().x() for item in all_items) / len(all_items)
        center_y = sum(item.scenePos().y() for item in all_items) / len(all_items)

        node_id_map: Dict[MetaNode, int] = {}
        node_records = []
        for idx, node in enumerate(selected_nodes):
            node_id_map[node] = idx
            pos = node.scenePos()
            node_records.append({
                "id": idx, "rel_x": pos.x() - center_x, "rel_y": pos.y() - center_y,
                **self._serialize_node(node),
            })
            
        group_records = []
        for g in selected_groups:
            pos = g.pos()
            rect = g.rect()
            group_records.append({
                "title": g.title,
                "rel_x": pos.x() - center_x,
                "rel_y": pos.y() - center_y,
                "width": rect.width(),
                "height": rect.height(),
                "color": g.color(),
            })

        clipboard_payload = {
            "nodes": node_records,
            "connections": self._serialize_connections(node_id_map),
            "groups": group_records,
        }
        try:
            QApplication.clipboard().setText("NODERC_CLIPBOARD:" + json.dumps(clipboard_payload))
        except Exception as exc:
            log_and_explain("Failed to copy nodes to clipboard", exc)

    def paste_nodes(self):
        clipboard_text = QApplication.clipboard().text()
        if not clipboard_text.startswith("NODERC_CLIPBOARD:"):
            return
        try:
            clipboard_payload = json.loads(clipboard_text.replace("NODERC_CLIPBOARD:", "", 1))
        except Exception as exc:
            log_and_explain("Failed to parse nodes from clipboard", exc)
            return

        self._block_undo_push = True
        try:
            self.scene.clearSelection()
            cursor = self.view.mapToScene(self.view.mapFromGlobal(QCursor.pos()))
            id_to_node: Dict[int, MetaNode] = {}
            for record in clipboard_payload.get("nodes", []):
                pos = QPointF(cursor.x() + record["rel_x"], cursor.y() + record["rel_y"])
                node = self._deserialize_node(record, pos)
                if node is None:
                    continue
                id_to_node[record["id"]] = node
                node.setSelected(True)
            
            pasted_frames = []
            for record in clipboard_payload.get("groups", []):
                rect = QRectF(0, 0, record.get("width", GROUP_FRAME_DEFAULT_WIDTH), record.get("height", GROUP_FRAME_DEFAULT_HEIGHT))
                frame = GroupFrameItem(rect, title=record.get("title", t("default_group_title")))
                pos = QPointF(cursor.x() + record["rel_x"], cursor.y() + record["rel_y"])
                frame.setPos(pos)
                if record.get("color"):
                    frame.set_color(record["color"], record_undo=False)
                self.scene.addItem(frame)
                frame.setSelected(True)
                pasted_frames.append(frame)

            self._rebuild_connections(clipboard_payload.get("connections", []), id_to_node)
            for node in id_to_node.values():
                node._refresh_connections()
            for frame in pasted_frames:
                frame.commit_members(force_all=True)
        finally:
            self._block_undo_push = False
        self.push_undo_state()

    def duplicate_nodes(self):
        self.copy_nodes()
        clipboard_text = QApplication.clipboard().text()
        if not clipboard_text.startswith("NODERC_CLIPBOARD:"):
            return
        try:
            clipboard_payload = json.loads(clipboard_text.replace("NODERC_CLIPBOARD:", "", 1))
        except Exception as exc:
            log_and_explain("Failed to parse nodes for duplication", exc)
            return

        self._block_undo_push = True
        try:
            self.scene.clearSelection()
            cursor = self.view.mapToScene(self.view.viewport().rect().center())
            id_to_node: Dict[int, MetaNode] = {}
            for record in clipboard_payload.get("nodes", []):
                pos = QPointF(cursor.x() + record["rel_x"] + DUPLICATE_OFFSET_X, cursor.y() + record["rel_y"] + DUPLICATE_OFFSET_Y)
                node = self._deserialize_node(record, pos)
                if node is None:
                    continue
                id_to_node[record["id"]] = node
                node.setSelected(True)
                
            duplicated_frames = []
            for record in clipboard_payload.get("groups", []):
                rect = QRectF(0, 0, record.get("width", GROUP_FRAME_DEFAULT_WIDTH), record.get("height", GROUP_FRAME_DEFAULT_HEIGHT))
                frame = GroupFrameItem(rect, title=record.get("title", t("default_group_title")))
                pos = QPointF(cursor.x() + record["rel_x"] + DUPLICATE_OFFSET_X, cursor.y() + record["rel_y"] + DUPLICATE_OFFSET_Y)
                frame.setPos(pos)
                if record.get("color"):
                    frame.set_color(record["color"], record_undo=False)
                self.scene.addItem(frame)
                frame.setSelected(True)
                duplicated_frames.append(frame)

            self._rebuild_connections(clipboard_payload.get("connections", []), id_to_node)
            for node in id_to_node.values():
                node._refresh_connections()
            for frame in duplicated_frames:
                frame.commit_members(force_all=True)
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

    def save_project(self, save_as: bool = False):
        path = self._project_path
        if save_as or not path:
            path, _ = QFileDialog.getSaveFileName(
                self, t("dialog_save_project"), path or "", t("dialog_project_filter"))
            if not path:
                return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._capture(include_selection=False), f, indent=2)
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

    def get_project_state(self) -> dict:
        return self._capture(include_selection=True)

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

    def _set_dirty(self, dirty: bool):
        self._dirty = dirty
        self._update_title()

    def _update_title(self):
        name = os.path.basename(self._project_path) if self._project_path else t("untitled")
        self.setWindowTitle(f"{t('window_title_prefix')}{name}{'*' if self._dirty else ''}")
        from localization import get_language
        self._update_window_icon(get_language())

    def _update_window_icon(self, lang: str):
        """Draw a custom flag icon programmatically for the window icon based on the active language.
        
        Why: Replaces the default program icon with the flag icon of the selected locale in memory.
        """
        w, h = 32, 24
        pixmap = QPixmap(w, h)
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        if lang == "uk":
            # Ukrainian flag: blue top half, yellow bottom half
            stripe_h = h // 2
            painter.fillRect(0, 0, w, stripe_h, QColor("#0057B7"))
            painter.fillRect(0, stripe_h, w, h - stripe_h, QColor("#FFD700"))
        else:
            # Dual USA/UK Flag (default/English): USA flag on the left, UK flag on the right
            # USA Flag on the left (clipped to 0, 0, 16, 24)
            painter.save()
            painter.setClipRect(0, 0, 16, 24)
            # Background white
            painter.fillRect(0, 0, 16, 24, QColor("#FFFFFF"))
            # 7 red stripes (alternating)
            stripe_h = 24.0 / 7.0
            for i in range(0, 7, 2):
                painter.fillRect(0, int(i * stripe_h), 16, int(stripe_h), QColor("#B22234"))
            # Canton (blue rect)
            painter.fillRect(0, 0, 9, 12, QColor("#3C3B6E"))
            # Some white dots for stars
            painter.setPen(QColor("#FFFFFF"))
            painter.drawPoint(2, 3)
            painter.drawPoint(6, 3)
            painter.drawPoint(4, 6)
            painter.drawPoint(2, 9)
            painter.drawPoint(6, 9)
            painter.restore()

            # UK Flag on the right (clipped to 16, 0, 16, 24)
            painter.save()
            painter.setClipRect(16, 0, 16, 24)
            painter.fillRect(16, 0, 16, 24, QColor("#012169"))
            
            # White diagonals
            pen_white_diag = QPen(QColor("#FFFFFF"), 3)
            painter.setPen(pen_white_diag)
            painter.drawLine(16, 0, 32, 24)
            painter.drawLine(16, 24, 32, 0)
            
            # Red diagonals
            pen_red_diag = QPen(QColor("#C8102E"), 1)
            painter.setPen(pen_red_diag)
            painter.drawLine(16, 0, 32, 24)
            painter.drawLine(16, 24, 32, 0)
            
            # White cross
            painter.fillRect(24 - 3, 0, 6, 24, QColor("#FFFFFF"))
            painter.fillRect(16, 12 - 3, 16, 6, QColor("#FFFFFF"))
            
            # Red cross
            painter.fillRect(24 - 1, 0, 2, 24, QColor("#C8102E"))
            painter.fillRect(16, 12 - 1, 16, 2, QColor("#C8102E"))
            painter.restore()
            
        # Draw a thin gray border outline
        painter.setPen(QPen(QColor("#555555"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(0, 0, w - 1, h - 1)
        
        painter.end()
        self.setWindowIcon(QIcon(pixmap))

    def undo(self):
        if self.history_index > 0:
            self.history_index -= 1
            self.set_project_state(self.history[self.history_index])

    def redo(self):
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self.set_project_state(self.history[self.history_index])

    def cycle_language(self, direction: int):
        """
        Cycle the UI language through the available languages in gettext.
        Why: Allows translators and testers to check different locales on keypress.
        """
        from localization import available_languages, set_language, get_language
        langs = available_languages()
        if not langs:
            return
        curr = get_language()
        try:
            idx = langs.index(curr)
        except ValueError:
            idx = 0
        new_idx = (idx + direction) % len(langs)
        new_lang = langs[new_idx]
        set_language(new_lang)

        # Refresh the UI in the new language
        self._update_title()
        state = self.get_project_state()
        self.set_project_state(state)

    def _build_exec_chain(self) -> Optional[List[MetaNode]]:
        all_nodes = {i for i in self.scene.items() if isinstance(i, MetaNode)}
        start_nodes = [n for n in all_nodes if isinstance(n, StartNode)]
        if not start_nodes:
            return None

        next_node: Dict[MetaNode, Optional[MetaNode]] = {n: None for n in all_nodes}
        for conn in self.connections:
            if not conn.is_exec:
                continue
            if conn.source.sock_def.name in ("exec_out", "__exec_out__"):
                next_node[conn.source.meta_node] = conn.dest.meta_node

        chain: List[MetaNode] = []
        current: Optional[MetaNode] = start_nodes[0]
        visited: set = set()
        while current and current not in visited:
            chain.append(current)
            visited.add(current)
            current = next_node.get(current)
        return chain

    def _resolve_connected_param_value(self, node: MetaNode, param_name: str) -> str:
        socket = node.get_socket(param_name)
        if not socket:
            return ""
        for conn in self.connections:
            if conn.dest is socket:
                source_node = conn.source.meta_node
                if isinstance(source_node, _BaseParamNode):
                    return source_node.get_value(conn.source.sock_def.name)
                elif isinstance(source_node, CommandNode):
                    out_sock_name = conn.source.sock_def.name
                    in_sock_name = out_sock_name.replace("_out", "") if out_sock_name.endswith("_out") else out_sock_name
                    return self._resolve_connected_param_value(source_node, in_sock_name)
        return ""

    def execute_chain(self):
        chain = self._build_exec_chain()
        if not chain or len(chain) < 2:
            QMessageBox.warning(self, t("dialog_incomplete_chain_title"),
                                t("msg_incomplete_chain_desc"))
            return

        tokens = [RC_EXECUTABLE]
        for node in chain[1:]:
            if not isinstance(node, CommandNode):
                continue
            tokens.append(node.cmd_def["command"])
            expanded = getattr(node, "expanded_vectors", set())
            for key in ("required", "optional"):
                for p in group_xyz_params(node.cmd_def.get(key, []), expanded):
                    name  = p if isinstance(p, str) else p["name"]
                    ptype = "string" if isinstance(p, str) else p.get("type", "string")
                    value = self._resolve_connected_param_value(node, name)
                    if not value:
                        continue
                    if ptype in VECTOR_PARAM_TYPES:
                        tokens.extend(value.split())
                    else:
                        tokens.append(value)

        try:
            subprocess.Popen(tokens)
        except Exception as exc:
            QMessageBox.critical(
                self, t("dialog_launch_error_title"),
                log_and_explain(t("msg_launch_failed"), exc),
            )