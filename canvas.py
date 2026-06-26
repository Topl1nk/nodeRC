"""
canvas.py — Scene, View, Menu and Main Window
• GraphicsView: FullViewportUpdate + middle-mouse pan (scroll-bar delta only)
• NodeScene:    type-safe drag (exec↔exec, param↔param enforced)
• Context menu: sections → subsections → action-word groups → commands
• execute_chain: resolves param values through typed connections
"""

from __future__ import annotations
import sys
import subprocess
import json
import os
from typing import List, Optional, Dict, Any

from PyQt5.QtWidgets import (
    QMainWindow, QGraphicsScene, QGraphicsItem,
    QVBoxLayout, QWidget, QMenu, QGraphicsLineItem,
    QMessageBox, QGraphicsView, QPushButton, QAction, QFileDialog, QDialog, QApplication
)
from PyQt5.QtGui import QPen, QCursor, QPainter, QColor, QFont
from PyQt5.QtCore import Qt, QPoint, QPointF, QRectF

from configuration import (
    RC_EXECUTABLE, COMMAND_DB_JSON, COMMAND_DB_TXT,
    SCENE_PADDING, CANVAS_BACKGROUND_COLOR, WINDOW_BACKGROUND_COLOR,
    CONTEXT_MENU_STYLESHEET, GRID_COLOR_SMALL, GRID_COLOR_LARGE,
    SCROLLBAR_TOGGLE_BG, SCROLLBAR_TOGGLE_HOVER,
    GRID_SIZE_SMALL, GRID_SIZE_LARGE,
    SCROLLBAR_BTN_MARGIN, SCROLLBAR_BTN_OFFSET,
)
from diagnostics import log_and_explain
from nodeRC import load_legacy_command_definitions
from search_menu import SearchMenuDialog
from nodes import (
    MetaNode, StartNode, CommandNode,
    StringParamNode, BoolParamNode, IntParamNode, EnumParamNode,
    PathParamNode, KeyValueParamNode,
    Connection, SocketItem, PARAM_NODE_TYPES,
    _BaseParamNode,
)


# ── GraphicsView ──────────────────────────────────────────────────────────────

class GraphicsView(QGraphicsView):
    _ZOOM_STEP_IN  = 1.20
    _ZOOM_STEP_OUT = 1 / 1.20

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHints(
            QPainter.Antialiasing |
            QPainter.SmoothPixmapTransform |
            QPainter.TextAntialiasing,
        )
        # FullViewportUpdate: entire viewport redrawn on any change — prevents trails
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setStyleSheet(f"background:{CANVAS_BACKGROUND_COLOR}; border:none;")

        self._panning     = False
        self._pan_origin: Optional[QPoint] = None

        self._scrollbar_toggle_btn = QPushButton("⊞", self)
        self._scrollbar_toggle_btn.setFixedSize(22, 22)
        self._scrollbar_toggle_btn.setToolTip("Toggle scrollbars")
        self._scrollbar_toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background:{SCROLLBAR_TOGGLE_BG};color:white;
                border:none;border-radius:4px;font-size:13px;
            }}
            QPushButton:hover{{background:{SCROLLBAR_TOGGLE_HOVER};}}
        """)
        self._scrollbar_toggle_btn.clicked.connect(self._toggle_scrollbar_visibility)
        self._scrollbars_visible = False

    def wheelEvent(self, event):
        factor = self._ZOOM_STEP_IN if event.angleDelta().y() > 0 else self._ZOOM_STEP_OUT
        self.scale(factor, factor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._panning    = True
            self._pan_origin = event.pos()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._panning    = False
            self._pan_origin = None
            self.viewport().setCursor(Qt.ArrowCursor)
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning and self._pan_origin is not None:
            delta            = event.pos() - self._pan_origin
            self._pan_origin = event.pos()
            # Delta applied directly to scroll bars — no scene-coord conversion needed
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scrollbar_toggle_btn.move(
            self.width()  - self._scrollbar_toggle_btn.width()  - SCROLLBAR_BTN_MARGIN - SCROLLBAR_BTN_OFFSET,
            self.height() - self._scrollbar_toggle_btn.height() - SCROLLBAR_BTN_MARGIN - SCROLLBAR_BTN_OFFSET,
        )

    def _toggle_scrollbar_visibility(self):
        self._scrollbars_visible = not self._scrollbars_visible
        policy = Qt.ScrollBarAsNeeded if self._scrollbars_visible else Qt.ScrollBarAlwaysOff
        self.setHorizontalScrollBarPolicy(policy)
        self.setVerticalScrollBarPolicy(policy)
        self._scrollbar_toggle_btn.setText("⊟" if self._scrollbars_visible else "⊞")


# ── NodeScene ─────────────────────────────────────────────────────────────────

class NodeScene(QGraphicsScene):
    """
    Manages typed connections between nodes.
    Interprets drag actions and enforces exec↔exec / param↔param.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.nodeEditorWindow: Optional[NodeEditorWindow] = None
        self._drag_source: Optional[SocketItem] = None
        self._drag_preview_line: Optional[QGraphicsLineItem] = None
        self._drag_active = False
        self._drag_original_dest: Optional[SocketItem] = None
        self.setSceneRect(-500, -500, 1000, 1000)
        self.setBackgroundBrush(QColor(CANVAS_BACKGROUND_COLOR))

    def drawBackground(self, painter: QPainter, rect: QRectF):
        painter.fillRect(rect, QColor(CANVAS_BACKGROUND_COLOR))

        left = int(rect.left()) - (int(rect.left()) % GRID_SIZE_SMALL)
        top  = int(rect.top())  - (int(rect.top())  % GRID_SIZE_SMALL)

        painter.setPen(QPen(QColor(*GRID_COLOR_SMALL), 1))
        for x in range(left, int(rect.right()), GRID_SIZE_SMALL):
            if x % GRID_SIZE_LARGE != 0:
                painter.drawLine(x, int(rect.top()), x, int(rect.bottom()))
        for y in range(top, int(rect.bottom()), GRID_SIZE_SMALL):
            if y % GRID_SIZE_LARGE != 0:
                painter.drawLine(int(rect.left()), y, int(rect.right()), y)

        painter.setPen(QPen(QColor(*GRID_COLOR_LARGE), 1.5))
        left = int(rect.left()) - (int(rect.left()) % GRID_SIZE_LARGE)
        top  = int(rect.top())  - (int(rect.top())  % GRID_SIZE_LARGE)
        for x in range(left, int(rect.right()), GRID_SIZE_LARGE):
            painter.drawLine(x, int(rect.top()), x, int(rect.bottom()))
        for y in range(top, int(rect.bottom()), GRID_SIZE_LARGE):
            painter.drawLine(int(rect.left()), y, int(rect.right()), y)

    def recalculate_scene_rect(self):
        nodes = [i for i in self.items() if isinstance(i, MetaNode)]
        if not nodes:
            return
        left   = min(n.scenePos().x() for n in nodes)
        top    = min(n.scenePos().y() for n in nodes)
        right  = max(n.scenePos().x() + n.boundingRect().width()  for n in nodes)
        bottom = max(n.scenePos().y() + n.boundingRect().height() for n in nodes)
        pad    = SCENE_PADDING
        self.setSceneRect(QRectF(
            left - pad, top - pad,
            (right - left) + pad * 2,
            (bottom - top) + pad * 2,
        ))

    def addItem(self, item):
        super().addItem(item)
        if isinstance(item, MetaNode):
            self.recalculate_scene_rect()

    def start_connection_drag(self, source: SocketItem):
        self._drag_active = True
        self._drag_source = source
        self._drag_original_dest = None
        win = self.nodeEditorWindow
        if win:
            if source.sock_def.kind == "output":
                for c in win.connections:
                    if c.source == source:
                        self._drag_original_dest = c.dest
                        break
            else:
                for c in win.connections:
                    if c.dest == source:
                        self._drag_original_dest = c.source
                        break
                        
        origin = source.scene_center()
        self._drag_preview_line = QGraphicsLineItem()
        self._drag_preview_line.setPen(QPen(QColor(source.sock_def.color), 2, Qt.DashLine))
        self._drag_preview_line.setZValue(-0.5)
        self._drag_preview_line.setLine(origin.x(), origin.y(), origin.x(), origin.y())
        super().addItem(self._drag_preview_line)

    def mouseMoveEvent(self, event):
        if self._drag_active and self._drag_preview_line and self._drag_source:
            origin = self._drag_source.scene_center()
            cursor = event.scenePos()
            self._drag_preview_line.setLine(origin.x(), origin.y(), cursor.x(), cursor.y())
        super().mouseMoveEvent(event)

    def _enforce_connection_rules(self, out_sock, in_sock):
        win = self.nodeEditorWindow
        if not win: return
        for c in list(win.connections):
            # Rule: exec output can have max 1 connection
            if out_sock.sock_def.is_exec and c.source == out_sock:
                if c.scene():
                    self.removeItem(c)
                if c in win.connections:
                    win.connections.remove(c)
            # Rule: ANY input (exec or param) can have max 1 connection
            if c.dest == in_sock:
                if c.scene():
                    self.removeItem(c)
                if c in win.connections:
                    win.connections.remove(c)

    def mouseReleaseEvent(self, event):
        if self._drag_active:
            target = self._find_compatible_socket(event.scenePos())
            if target:
                out_sock = self._drag_source if self._drag_source.sock_def.kind == "output" else target
                in_sock  = target if self._drag_source.sock_def.kind == "output" else self._drag_source
                self._enforce_connection_rules(out_sock, in_sock)
                conn = Connection(out_sock, in_sock)
                super().addItem(conn)
                if self.nodeEditorWindow:
                    self.nodeEditorWindow.connections.append(conn)
                    in_sock.meta_node._refresh_connections()
            else:
                if self.nodeEditorWindow:
                    self._show_node_creation_menu(
                        event.scenePos(), event.screenPos(), 
                        source_socket=self._drag_source,
                        original_dest=self._drag_original_dest
                    )
            self._cancel_connection_drag()
        super().mouseReleaseEvent(event)

    def _find_compatible_socket(self, scene_pos: QPointF) -> Optional[SocketItem]:
        """
        Returns a compatible socket for the drag source.
        Why: exec and param socket types must never cross-connect;
        enforcing this here keeps CommandNode and ParamNode completely passive.
        """
        for item in self.items(scene_pos):
            if isinstance(item, SocketItem):
                if item.sock_def.kind == self._drag_source.sock_def.kind:
                    continue
                if item.sock_def.is_exec != self._drag_source.sock_def.is_exec:
                    continue
                if item.meta_node is self._drag_source.meta_node:
                    continue
                return item

        for item in self.items(scene_pos):
            if isinstance(item, MetaNode):
                if item is self._drag_source.meta_node:
                    continue
                for s in item.sockets.values():
                    if s.sock_def.kind != self._drag_source.sock_def.kind and s.sock_def.is_exec == self._drag_source.sock_def.is_exec:
                        return s

        return None

    def _cancel_connection_drag(self):
        if self._drag_preview_line:
            self.removeItem(self._drag_preview_line)
            self._drag_preview_line = None
        self._drag_active = False
        self._drag_source = None

    def contextMenuEvent(self, event):
        view      = self.views()[0] if self.views() else None
        transform        = view.transform() if view else None
        item_under_cursor = self.itemAt(event.scenePos(), transform) if transform else None
        if not item_under_cursor or isinstance(item_under_cursor, Connection):
            self._show_node_creation_menu(event.scenePos(), event.screenPos())
            event.accept()
        else:
            super().contextMenuEvent(event)

    def _show_node_creation_menu(self, scene_pos: QPointF, screen_pos, source_socket=None, original_dest=None):
        win = self.nodeEditorWindow
        if not win:
            return
            
        dialog = SearchMenuDialog(win.command_categories, win)
        dialog.set_anchor_pos(screen_pos)
        
        if dialog.exec_() == QDialog.Accepted:
            payload = dialog.payload
            
            new_node = None
            if isinstance(payload, dict) and "command" in payload:
                new_node = win.add_command_node(scene_pos, payload)
            elif isinstance(payload, dict) and "param_type" in payload:
                new_node = win.add_param_node(scene_pos, payload)
                
            target_socket = None
            if new_node and source_socket:
                for s in new_node.sockets.values():
                    if s.socket_type != source_socket.socket_type and s.sock_def.is_exec == source_socket.sock_def.is_exec:
                        target_socket = s
                        break
            if target_socket:
                if source_socket.socket_type == "output":
                    out_sock, in_sock = source_socket, target_socket
                else:
                    out_sock, in_sock = target_socket, source_socket
                self._enforce_connection_rules(out_sock, in_sock)
                conn = Connection(out_sock, in_sock)
                self.addItem(conn)
                win.connections.append(conn)

                if original_dest:
                    c_out_sock = None
                    for s in new_node.sockets.values():
                        if s.socket_type == source_socket.socket_type and s.sock_def.is_exec == source_socket.sock_def.is_exec:
                            c_out_sock = s
                            break
                    if c_out_sock:
                        if original_dest.socket_type == "input":
                            self._enforce_connection_rules(c_out_sock, original_dest)
                            conn2 = Connection(c_out_sock, original_dest)
                        else:
                            self._enforce_connection_rules(original_dest, c_out_sock)
                            conn2 = Connection(original_dest, c_out_sock)
                        self.addItem(conn2)
                        win.connections.append(conn2)



# ── NodeEditorWindow ──────────────────────────────────────────────────────────

class NodeEditorWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("RealityCapture Node Editor")
        self.setGeometry(100, 100, 1280, 800)
        self.setStyleSheet(f"QMainWindow{{background:{WINDOW_BACKGROUND_COLOR};}}")

        self.command_categories: Dict[str, Any] = {}
        self.command_defs: List[dict] = []
        self._load_command_database()

        self.connections: List[Connection] = []

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
        return node

    def add_param_node(self, pos: QPointF, data: dict):
        param_type = data.get("param_type", "string")
        values     = data.get("values", [])
        node_class = PARAM_NODE_TYPES.get(param_type, StringParamNode)
        
        kwargs = {}
        param_display = data.get("display") or data.get("name")
        if param_display:
            kwargs["param_name"] = param_display
        if node_class is EnumParamNode and values:
            kwargs["values"] = values
            
        node = node_class(**kwargs)
        node.creation_data = data
        node.setPos(pos)
        self.scene.addItem(node)
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
        else:
            super().keyPressEvent(event)

    def _delete_selected_items(self):
        items_to_delete = self.scene.selectedItems()
        for item in items_to_delete:
            if isinstance(item, Connection):
                dest_node = item.dest.meta_node if item.dest else None
                self.scene.removeItem(item)
                if item in self.connections:
                    self.connections.remove(item)
                if dest_node:
                    dest_node._refresh_connections()
            elif isinstance(item, MetaNode) and not isinstance(item, StartNode):
                # Search for bypass connection (exec_in -> exec_out)
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
                for conn in dead_connections:
                    self.scene.removeItem(conn)
                    if conn in self.connections:
                        self.connections.remove(conn)
                self.scene.removeItem(item)

    def copy_nodes(self):
        selected_nodes = [item for item in self.scene.selectedItems() if isinstance(item, MetaNode)]
        if not selected_nodes:
            return
            
        data = {"nodes": [], "connections": []}
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
                if hasattr(item, "_dir_editor"):
                    node_data["current_value"] = {"dir": item._dir_editor.text(), "file": item._file_combo.currentText()}
                elif hasattr(item, "_editor"):
                    node_data["current_value"] = item._editor.text()
                elif hasattr(item, "_checkbox"):
                    node_data["current_value"] = item._checkbox.isChecked()
                elif hasattr(item, "_spinbox"):
                    node_data["current_value"] = item._spinbox.value()
                elif hasattr(item, "_combobox"):
                    node_data["current_value"] = item._combobox.currentText()
            data["nodes"].append(node_data)
            
        for conn in self.connections:
            if conn.source.meta_node in node_id_map and conn.dest.meta_node in node_id_map:
                data["connections"].append({
                    "src_node": node_id_map[conn.source.meta_node],
                    "src_socket": conn.source.sock_def.name,
                    "dst_node": node_id_map[conn.dest.meta_node],
                    "dst_socket": conn.dest.sock_def.name
                })
                
        try:
            json_str = json.dumps(data)
            QApplication.clipboard().setText("NODERC_CLIPBOARD:" + json_str)
        except Exception:
            pass

    def paste_nodes(self):
        clipboard_text = QApplication.clipboard().text()
        if not clipboard_text.startswith("NODERC_CLIPBOARD:"):
            return
            
        try:
            json_str = clipboard_text.replace("NODERC_CLIPBOARD:", "")
            data = json.loads(json_str)
        except Exception:
            return
            
        self.scene.clearSelection()
        cursor_in_scene = self.view.mapToScene(self.view.mapFromGlobal(QCursor.pos()))
        paste_x = cursor_in_scene.x()
        paste_y = cursor_in_scene.y()
        
        id_to_node = {}
        new_nodes = []
        
        for n_data in data.get("nodes", []):
            pos = QPointF(paste_x + n_data["rel_x"], paste_y + n_data["rel_y"])
            new_node = None
            if "cmd_def" in n_data:
                new_node = self.add_command_node(pos, n_data["cmd_def"])
            elif "creation_data" in n_data:
                new_node = self.add_param_node(pos, n_data["creation_data"])
                if new_node and "current_value" in n_data:
                    val = n_data["current_value"]
                    if hasattr(new_node, "_dir_editor"):
                        if isinstance(val, dict):
                            new_node._dir_editor.setText(val.get("dir", ""))
                            new_node._file_combo.setCurrentText(val.get("file", ""))
                        else:
                            new_node._dir_editor.setText(str(val))
                    elif hasattr(new_node, "_editor"):
                        new_node._editor.setText(str(val))
                    elif hasattr(new_node, "_checkbox"):
                        new_node._checkbox.setChecked(bool(val))
                    elif hasattr(new_node, "_spinbox"):
                        new_node._spinbox.setValue(int(val))
                    elif hasattr(new_node, "_combobox"):
                        idx = new_node._combobox.findText(str(val))
                        if idx >= 0:
                            new_node._combobox.setCurrentIndex(idx)
                            
            if new_node:
                id_to_node[n_data["id"]] = new_node
                new_node.setSelected(True)
                new_nodes.append(new_node)
                
        for c_data in data.get("connections", []):
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

    def save_project(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Project", "", "NodeRC Project (*.json)")
        if not path:
            return
            
        data = {"nodes": [], "connections": []}
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
                    if hasattr(item, "_dir_editor"):
                        node_data["current_value"] = {"dir": item._dir_editor.text(), "file": item._file_combo.currentText()}
                    elif hasattr(item, "_editor"):
                        node_data["current_value"] = item._editor.text()
                    elif hasattr(item, "_checkbox"):
                        node_data["current_value"] = item._checkbox.isChecked()
                    elif hasattr(item, "_spinbox"):
                        node_data["current_value"] = item._spinbox.value()
                    elif hasattr(item, "_combobox"):
                        node_data["current_value"] = item._combobox.currentText()

                data["nodes"].append(node_data)
                
        for conn in self.connections:
            src_node_id = node_id_map.get(conn.source.meta_node)
            dst_node_id = node_id_map.get(conn.dest.meta_node)
            if src_node_id is not None and dst_node_id is not None:
                data["connections"].append({
                    "src_node": src_node_id,
                    "src_socket": conn.source.sock_def.name,
                    "dst_node": dst_node_id,
                    "dst_socket": conn.dest.sock_def.name
                })
                
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", log_and_explain("Failed to save project", exc))

    def load_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Project", "", "NodeRC Project (*.json)")
        if not path:
            return
            
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            items_to_delete = [i for i in self.scene.items() if isinstance(i, MetaNode) or isinstance(i, Connection)]
            for item in items_to_delete:
                self.scene.removeItem(item)
            self.connections.clear()
            
            node_id_map = {}
            for n_data in data.get("nodes", []):
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
                        if hasattr(node, "_dir_editor"):
                            if isinstance(val, dict):
                                node._dir_editor.setText(val.get("dir", ""))
                                node._file_combo.setCurrentText(val.get("file", ""))
                            else:
                                node._dir_editor.setText(str(val))
                        elif hasattr(node, "_editor"):
                            node._editor.setText(str(val))
                        elif hasattr(node, "_checkbox"):
                            node._checkbox.setChecked(bool(val))
                        elif hasattr(node, "_spinbox"):
                            node._spinbox.setValue(int(val))
                        elif hasattr(node, "_combobox"):
                            node._combobox.setCurrentText(str(val))
                            
                if node:
                    node_id_map[n_data["id"]] = node
                    
            for c_data in data.get("connections", []):
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
                        
        except Exception as exc:
            QMessageBox.critical(self, "Load Error", log_and_explain("Failed to load project", exc))
            self._add_start_node()

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
            for p in node.cmd_def.get("required", []):
                name  = p if isinstance(p, str) else p["name"]
                value = self._resolve_connected_param_value(node, name)
                if value:
                    tokens.append(value)
            for p in node.cmd_def.get("optional", []):
                name  = p if isinstance(p, str) else p["name"]
                value = self._resolve_connected_param_value(node, name)
                if value:
                    tokens.append(value)

        try:
            subprocess.Popen(tokens)
        except Exception as exc:
            QMessageBox.critical(
                self, "Launch Error",
                log_and_explain("Failed to start RealityCapture", exc),
            )