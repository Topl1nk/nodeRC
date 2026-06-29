"""
canvas.py — Scene, View, Menu and Main Window
"""

from __future__ import annotations
import sys
import subprocess
import json
import os
from typing import List, Optional, Dict, Any

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QMessageBox, QFileDialog, QApplication, QVBoxLayout
)
from PyQt5.QtGui import QCursor, QColor
from PyQt5.QtCore import Qt, QPointF

from configuration import (
    RC_EXECUTABLE, COMMAND_DB_JSON,
    WINDOW_BACKGROUND_COLOR, UNDO_HISTORY_LIMIT,
    DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_CAPTION_COLOR, DWMWA_TEXT_COLOR,
    TEXT_COLOR, VECTOR_PARAM_TYPES,
)
from diagnostics import log_and_explain
from nodeRC import builtin_command_defaults

from view import GraphicsView
from scene import NodeScene
from nodes_base import Connection, MetaNode, _BaseParamNode
from nodes_concrete import (
    StartNode, CommandNode, PARAM_NODE_TYPES, group_xyz_params, StringParamNode, EnumParamNode
)



# ── NodeEditorWindow ──────────────────────────────────────────────────────────

class NodeEditorWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setGeometry(100, 100, 1280, 800)
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
            node.setPos(60, 80)
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
        node_class = PARAM_NODE_TYPES.get(creation_data.get("param_type", "string"), StringParamNode)
        name   = creation_data.get("display") or creation_data.get("name")
        values = creation_data.get("values", [])
        if node_class is EnumParamNode and values:
            node = node_class(name, values) if name else node_class(values=values)
        else:
            node = node_class(name) if name else node_class()
        node.creation_data = creation_data
        return node

    def _serialize_node(self, node: MetaNode) -> dict:
        return {"type": type(node).__name__, **node.serialize_payload()}

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
        for idx, item in enumerate(self.scene.items()):
            if not isinstance(item, MetaNode):
                continue
            node_id_map[item] = idx
            pos = item.scenePos()
            record = {"id": idx, "x": pos.x(), "y": pos.y(), **self._serialize_node(item)}
            if include_selection:
                record["selected"] = item.isSelected()
            node_records.append(record)
        return {
            "nodes": node_records,
            "connections": self._serialize_connections(node_id_map, include_selection),
        }

    def _restore(self, payload: dict, restore_selection: bool):
        self._linked_group = []
        for item in [i for i in self.scene.items() if isinstance(i, (MetaNode, Connection))]:
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

        self._rebuild_connections(payload.get("connections", []), id_to_node, restore_selection)
        for node in id_to_node.values():
            node._refresh_connections()
        self.scene.recalculate_scene_rect()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            cursor_in_scene = self.view.mapToScene(
                self.view.mapFromGlobal(QCursor.pos()))
            self.scene._show_node_creation_menu(cursor_in_scene, QCursor.pos())
            event.accept()
        elif event.key() == Qt.Key_Delete:
            self._delete_selected_items()
            event.accept()
        elif event.key() == Qt.Key_S and event.modifiers() == Qt.ControlModifier:
            self.save_project()
            event.accept()
        elif event.key() == Qt.Key_S and event.modifiers() == (Qt.ControlModifier | Qt.ShiftModifier):
            self.save_project(save_as=True)
            event.accept()
        elif event.key() == Qt.Key_O and event.modifiers() == Qt.ControlModifier:
            self.load_project()
            event.accept()
        elif event.key() == Qt.Key_C and event.modifiers() == Qt.ControlModifier:
            self.copy_nodes()
            event.accept()
        elif event.key() == Qt.Key_V and event.modifiers() == Qt.ControlModifier:
            self.paste_nodes()
            event.accept()
        elif event.key() == Qt.Key_Z and event.modifiers() == Qt.ControlModifier:
            self.undo()
            event.accept()
        elif event.key() == Qt.Key_Z and event.modifiers() == (Qt.ControlModifier | Qt.ShiftModifier):
            self.redo()
            event.accept()
        elif event.key() == Qt.Key_Y and event.modifiers() == Qt.ControlModifier:
            self.redo()
            event.accept()
        elif event.key() == Qt.Key_G and event.modifiers() == Qt.NoModifier:
            self.scene.grid_visible = not getattr(self.scene, "grid_visible", True)
            self.scene.update()
            event.accept()
        elif event.key() == Qt.Key_F and event.modifiers() == Qt.NoModifier:
            selected = [i for i in self.scene.selectedItems() if isinstance(i, MetaNode)]
            self.view.frame_content(selected or None)
            event.accept()
        elif event.key() == Qt.Key_F11:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()
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
                elif isinstance(item, MetaNode) and not isinstance(item, StartNode):
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
        if not selected_nodes:
            return

        center_x = sum(n.scenePos().x() for n in selected_nodes) / len(selected_nodes)
        center_y = sum(n.scenePos().y() for n in selected_nodes) / len(selected_nodes)

        node_id_map: Dict[MetaNode, int] = {}
        node_records = []
        for idx, node in enumerate(selected_nodes):
            node_id_map[node] = idx
            pos = node.scenePos()
            node_records.append({
                "id": idx, "rel_x": pos.x() - center_x, "rel_y": pos.y() - center_y,
                **self._serialize_node(node),
            })
        clipboard_payload = {
            "nodes": node_records,
            "connections": self._serialize_connections(node_id_map),
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
            self._rebuild_connections(clipboard_payload.get("connections", []), id_to_node)
            for node in id_to_node.values():
                node._refresh_connections()
        finally:
            self._block_undo_push = False
        self.push_undo_state()

    def save_project(self, save_as: bool = False):
        path = self._project_path
        if save_as or not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Project", path or "", "NodeRC Project (*.json)")
            if not path:
                return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._capture(include_selection=False), f, indent=2)
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", log_and_explain("Failed to save project", exc))
            return
        self._project_path = path
        self._set_dirty(False)

    def load_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Project", "", "NodeRC Project (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            self._restore(payload, restore_selection=False)
        except Exception as exc:
            QMessageBox.critical(self, "Load Error", log_and_explain("Failed to load project", exc))
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
        name = os.path.basename(self._project_path) if self._project_path else "Untitled"
        self.setWindowTitle(f"NodeRC Editor — {name}{'*' if self._dirty else ''}")

    def undo(self):
        if self.history_index > 0:
            self.history_index -= 1
            self.set_project_state(self.history[self.history_index])

    def redo(self):
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self.set_project_state(self.history[self.history_index])

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
            QMessageBox.warning(self, "Incomplete chain",
                                "Connect at least one Command Node to Start.")
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
                self, "Launch Error",
                log_and_explain("Failed to start RealityCapture", exc),
            )