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
    QMainWindow, QWidget, QMessageBox, QFileDialog, QDialog, QApplication, QVBoxLayout
)
from PyQt5.QtGui import QCursor, QColor
from PyQt5.QtCore import Qt, QPointF

from configuration import (
    RC_EXECUTABLE, COMMAND_DB_JSON, COMMAND_DB_TXT,
    WINDOW_BACKGROUND_COLOR, UNDO_HISTORY_LIMIT,
    DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_CAPTION_COLOR, DWMWA_TEXT_COLOR,
    TEXT_COLOR
)
from diagnostics import log_and_explain
from nodeRC import load_legacy_command_definitions
from search_menu import SearchMenuDialog

from view import GraphicsView
from scene import NodeScene
from nodes_base import Connection, SocketItem, MetaNode, _BaseParamNode
from nodes_concrete import (
    StartNode, CommandNode, PARAM_NODE_TYPES, group_xyz_params, StringParamNode, EnumParamNode
)



# ── NodeEditorWindow ──────────────────────────────────────────────────────────

class NodeEditorWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("NodeRC Editor")
        self.setGeometry(100, 100, 1280, 800)
        self.setStyleSheet(f"QMainWindow{{background:{WINDOW_BACKGROUND_COLOR};}}")

        self.command_categories: Dict[str, Any] = {}
        self.command_defs: List[dict] = []
        self._load_command_database()

        self.connections: List[Connection] = []
        self._linked_group: List[MetaNode] = []
        self._active_field_key: Optional[str] = None

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
            flat = load_legacy_command_definitions(COMMAND_DB_TXT)
            self.command_defs = flat
            self.command_categories = {"Commands": {"__root__": flat}}

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

    def add_param_node(self, pos: QPointF, node_metadata: dict):
        param_type = node_metadata.get("param_type", "string")
        values     = node_metadata.get("values", [])
        node_class = PARAM_NODE_TYPES.get(param_type, StringParamNode)

        kwargs = {}
        param_display = node_metadata.get("display") or node_metadata.get("name")
        if param_display:
            kwargs["param_name"] = param_display
        if node_class is EnumParamNode and values:
            kwargs["values"] = values

        node = node_class(**kwargs)
        node.creation_data = node_metadata
        node.setPos(pos)
        self.scene.addItem(node)
        self.push_undo_state()
        return node

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
        selected_nodes = [item for item in self.scene.selectedItems() if isinstance(item, MetaNode)]
        if not selected_nodes:
            return

        clipboard_payload = {"nodes": [], "connections": []}
        node_id_map = {}

        xs = [n.scenePos().x() for n in selected_nodes]
        ys = [n.scenePos().y() for n in selected_nodes]
        center_x = sum(xs) / len(xs)
        center_y = sum(ys) / len(ys)

        for idx, item in enumerate(selected_nodes):
            node_id_map[item] = idx
            pos = item.scenePos()
            node_data = {
                "id": idx,
                "type": type(item).__name__,
                "rel_x": pos.x() - center_x,
                "rel_y": pos.y() - center_y
            }
            if isinstance(item, CommandNode):
                node_data["cmd_def"] = item.cmd_def
            elif isinstance(item, _BaseParamNode):
                node_data["creation_data"] = getattr(item, "creation_data", {"param_type": item.TYPE_ID, "display": item.TYPE_ID})
                node_data["current_value"] = item.get_value_state()
            clipboard_payload["nodes"].append(node_data)

        for conn in self.connections:
            if conn.source.meta_node in node_id_map and conn.dest.meta_node in node_id_map:
                clipboard_payload["connections"].append({
                    "src_node": node_id_map[conn.source.meta_node],
                    "src_socket": conn.source.sock_def.name,
                    "dst_node": node_id_map[conn.dest.meta_node],
                    "dst_socket": conn.dest.sock_def.name
                })

        try:
            json_str = json.dumps(clipboard_payload)
            QApplication.clipboard().setText("NODERC_CLIPBOARD:" + json_str)
        except Exception as exc:
            from diagnostics import log_and_explain
            log_and_explain("Failed to copy nodes to clipboard", exc)

    def paste_nodes(self):
        clipboard_text = QApplication.clipboard().text()
        if not clipboard_text.startswith("NODERC_CLIPBOARD:"):
            return

        try:
            json_str = clipboard_text.replace("NODERC_CLIPBOARD:", "")
            clipboard_payload = json.loads(json_str)
        except Exception as exc:
            from diagnostics import log_and_explain
            log_and_explain("Failed to parse nodes from clipboard", exc)
            return

        self._block_undo_push = True
        try:
            self.scene.clearSelection()
            cursor_in_scene = self.view.mapToScene(self.view.mapFromGlobal(QCursor.pos()))
            paste_x = cursor_in_scene.x()
            paste_y = cursor_in_scene.y()

            id_to_node = {}
            new_nodes = []

            for n_data in clipboard_payload.get("nodes", []):
                pos = QPointF(paste_x + n_data["rel_x"], paste_y + n_data["rel_y"])
                new_node = None
                if "cmd_def" in n_data:
                    new_node = self.add_command_node(pos, n_data["cmd_def"])
                elif "creation_data" in n_data:
                    new_node = self.add_param_node(pos, n_data["creation_data"])
                    if new_node and "current_value" in n_data:
                        new_node.set_value_state(n_data["current_value"])

                if new_node:
                    id_to_node[n_data["id"]] = new_node
                    new_node.setSelected(True)
                    new_nodes.append(new_node)

            for c_data in clipboard_payload.get("connections", []):
                src_node = id_to_node.get(c_data["src_node"])
                dst_node = id_to_node.get(c_data["dst_node"])
                if src_node and dst_node:
                    src_sock = src_node.get_socket(c_data["src_socket"])
                    dst_sock = dst_node.get_socket(c_data["dst_socket"])
                    if src_sock and dst_sock:
                        self.scene._enforce_connection_rules(src_sock, dst_sock)
                        conn = Connection(src_sock, dst_sock)
                        self.scene.addItem(conn)
                        self.connections.append(conn)

            for n in new_nodes:
                n._refresh_connections()
        finally:
            self._block_undo_push = False
        self.push_undo_state()

    def save_project(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Project", "", "NodeRC Project (*.json)")
        if not path:
            return

        project_payload = {"nodes": [], "connections": []}
        node_id_map = {}

        for idx, item in enumerate(self.scene.items()):
            if isinstance(item, MetaNode):
                node_id_map[item] = idx
                pos = item.scenePos()
                node_data = {
                    "id": idx,
                    "type": type(item).__name__,
                    "x": pos.x(),
                    "y": pos.y()
                }
                if isinstance(item, CommandNode):
                    node_data["cmd_def"] = item.cmd_def
                elif isinstance(item, _BaseParamNode):
                    node_data["creation_data"] = getattr(item, "creation_data", {"param_type": item.TYPE_ID, "display": item.TYPE_ID})
                    node_data["current_value"] = item.get_value_state()

                project_payload["nodes"].append(node_data)

        for conn in self.connections:
            src_node_id = node_id_map.get(conn.source.meta_node)
            dst_node_id = node_id_map.get(conn.dest.meta_node)
            if src_node_id is not None and dst_node_id is not None:
                project_payload["connections"].append({
                    "src_node": src_node_id,
                    "src_socket": conn.source.sock_def.name,
                    "dst_node": dst_node_id,
                    "dst_socket": conn.dest.sock_def.name
                })

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(project_payload, f, indent=2)
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", log_and_explain("Failed to save project", exc))

    def load_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Project", "", "NodeRC Project (*.json)")
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                project_payload = json.load(f)

            items_to_delete = [i for i in self.scene.items() if isinstance(i, MetaNode) or isinstance(i, Connection)]
            for item in items_to_delete:
                self.scene.removeItem(item)
            self.connections.clear()

            node_id_map = {}
            for n_data in project_payload.get("nodes", []):
                node_type = n_data["type"]
                pos       = QPointF(n_data["x"], n_data["y"])
                node      = None
                if node_type == "StartNode":
                    node = StartNode()
                    node.setPos(pos)
                    self.scene.addItem(node)
                elif node_type == "CommandNode":
                    node = CommandNode(n_data["cmd_def"])
                    node.setPos(pos)
                    self.scene.addItem(node)
                elif node_type.endswith("ParamNode"):
                    c_data = n_data.get("creation_data", {"param_type": "string", "display": "value"})
                    param_type = c_data.get("param_type", "string")
                    param_name = c_data.get("display") or c_data.get("name", "value")
                    values     = c_data.get("values", [])
                    node_class = PARAM_NODE_TYPES.get(param_type, StringParamNode)
                    node = (
                        node_class(param_name, values)
                        if node_class is EnumParamNode and values
                        else node_class(param_name)
                    )
                    node.creation_data = c_data
                    node.setPos(pos)
                    self.scene.addItem(node)

                    val = n_data.get("current_value")
                    if val is not None:
                        node.set_value_state(val)

                if node:
                    node_id_map[n_data["id"]] = node

            for c_data in project_payload.get("connections", []):
                src_node = node_id_map.get(c_data["src_node"])
                dst_node = node_id_map.get(c_data["dst_node"])
                if src_node and dst_node:
                    src_sock = src_node.get_socket(c_data["src_socket"])
                    dst_sock = dst_node.get_socket(c_data["dst_socket"])
                    if src_sock and dst_sock:
                        self.scene._enforce_connection_rules(src_sock, dst_sock)
                        conn = Connection(src_sock, dst_sock)
                        self.scene.addItem(conn)
                        self.connections.append(conn)
            for n in node_id_map.values():
                n._refresh_connections()

        except Exception as exc:
            QMessageBox.critical(self, "Load Error", log_and_explain("Failed to load project", exc))
            self._add_start_node()

    def get_project_state(self) -> dict:
        project_payload = {"nodes": [], "connections": []}
        node_id_map = {}

        for idx, item in enumerate(self.scene.items()):
            if isinstance(item, MetaNode):
                node_id_map[item] = idx
                pos = item.scenePos()
                node_data = {
                    "id": idx,
                    "type": type(item).__name__,
                    "x": pos.x(),
                    "y": pos.y(),
                    "selected": item.isSelected()
                }
                if isinstance(item, CommandNode):
                    node_data["cmd_def"] = item.cmd_def
                elif isinstance(item, _BaseParamNode):
                    node_data["creation_data"] = getattr(item, "creation_data", {"param_type": item.TYPE_ID, "display": item.TYPE_ID})
                    node_data["current_value"] = item.get_value_state()

                project_payload["nodes"].append(node_data)

        for conn in self.connections:
            src_node_id = node_id_map.get(conn.source.meta_node)
            dst_node_id = node_id_map.get(conn.dest.meta_node)
            if src_node_id is not None and dst_node_id is not None:
                project_payload["connections"].append({
                    "src_node": src_node_id,
                    "src_socket": conn.source.sock_def.name,
                    "dst_node": dst_node_id,
                    "dst_socket": conn.dest.sock_def.name,
                    "selected": conn.isSelected()
                })
        return project_payload

    def set_project_state(self, project_payload: dict):
        self._block_undo_push = True
        try:
            self._linked_group = []
            items_to_delete = [i for i in self.scene.items() if isinstance(i, MetaNode) or isinstance(i, Connection)]
            for item in items_to_delete:
                self.scene.removeItem(item)
            self.connections.clear()

            node_id_map = {}
            for n_data in project_payload.get("nodes", []):
                node_type = n_data["type"]
                pos       = QPointF(n_data["x"], n_data["y"])
                node      = None
                if node_type == "StartNode":
                    node = StartNode()
                    node.setPos(pos)
                    self.scene.addItem(node)
                elif node_type == "CommandNode":
                    node = CommandNode(n_data["cmd_def"])
                    node.setPos(pos)
                    self.scene.addItem(node)
                elif node_type.endswith("ParamNode"):
                    c_data = n_data.get("creation_data", {"param_type": "string", "display": "value"})
                    param_type = c_data.get("param_type", "string")
                    param_name = c_data.get("display") or c_data.get("name", "value")
                    values     = c_data.get("values", [])
                    node_class = PARAM_NODE_TYPES.get(param_type, StringParamNode)
                    node = (
                        node_class(param_name, values)
                        if node_class is EnumParamNode and values
                        else node_class(param_name)
                    )
                    node.creation_data = c_data
                    node.setPos(pos)
                    self.scene.addItem(node)

                    val = n_data.get("current_value")
                    if val is not None:
                        node.set_value_state(val)

                if node:
                    node_id_map[n_data["id"]] = node
                    if n_data.get("selected", False):
                        node.setSelected(True)

            for c_data in project_payload.get("connections", []):
                src_node = node_id_map.get(c_data["src_node"])
                dst_node = node_id_map.get(c_data["dst_node"])
                if src_node and dst_node:
                    src_sock = src_node.get_socket(c_data["src_socket"])
                    dst_sock = dst_node.get_socket(c_data["dst_socket"])
                    if src_sock and dst_sock:
                        self.scene._enforce_connection_rules(src_sock, dst_sock)
                        conn = Connection(src_sock, dst_sock)
                        self.scene.addItem(conn)
                        self.connections.append(conn)
                        if c_data.get("selected", False):
                            conn.setSelected(True)

            for n in node_id_map.values():
                n._refresh_connections()
            self.scene.recalculate_scene_rect()
        finally:
            self._block_undo_push = False

    def push_undo_state(self):
        if getattr(self, "_block_undo_push", False):
            return
        state = self.get_project_state()
        if self.history_index >= 0 and self.history[self.history_index] == state:
            return
        self.history = self.history[:self.history_index + 1]
        self.history.append(state)
        if len(self.history) > UNDO_HISTORY_LIMIT:
            self.history.pop(0)
        self.history_index = len(self.history) - 1

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