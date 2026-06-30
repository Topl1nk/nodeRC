from __future__ import annotations
from typing import Optional

from PyQt5.QtWidgets import QGraphicsScene, QGraphicsLineItem, QDialog, QApplication
from PyQt5.QtCore import Qt, QPointF, QRectF, QTimer
from PyQt5.QtGui import QPen, QColor, QPainter

from configuration import (
    CANVAS_BACKGROUND_COLOR, GRID_SIZE_SMALL, GRID_SIZE_LARGE,
    GRID_COLOR_SMALL, GRID_COLOR_LARGE, SCENE_PADDING,
    SCENE_INITIAL_X, SCENE_INITIAL_Y, SCENE_INITIAL_WIDTH, SCENE_INITIAL_HEIGHT,
    DRAG_PREVIEW_LINE_WIDTH, NODE_DRAG_Z, GROUP_FRAME_HEADER_HEIGHT,
)
from search_menu import SearchMenuDialog
from nodes_base import Connection, SocketItem, MetaNode, GroupFrameItem


class NodeScene(QGraphicsScene):
    """
    Manages typed connections between nodes.
    Interprets drag actions and enforces exec↔exec / param↔param.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.nodeEditorWindow = None
        self._drag_source: Optional[SocketItem] = None
        self._drag_preview_line: Optional[QGraphicsLineItem] = None
        self._drag_active = False
        self._drag_original_dest: Optional[SocketItem] = None
        self._rect_recalc_pending = False
        self.setSceneRect(SCENE_INITIAL_X, SCENE_INITIAL_Y, SCENE_INITIAL_WIDTH, SCENE_INITIAL_HEIGHT)
        self.setBackgroundBrush(QColor(CANVAS_BACKGROUND_COLOR))
        self.grid_visible = True

    def drawBackground(self, painter: QPainter, rect: QRectF):
        painter.fillRect(rect, QColor(CANVAS_BACKGROUND_COLOR))
        if not getattr(self, "grid_visible", True):
            return

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
            self._schedule_rect_recalc()

    def _schedule_rect_recalc(self):
        # Why: Coalesces a burst of additions into a single O(N) pass to avoid O(N²) layout updates.
        if self._rect_recalc_pending:
            return
        self._rect_recalc_pending = True
        QTimer.singleShot(0, self._run_rect_recalc)

    def _run_rect_recalc(self):
        self._rect_recalc_pending = False
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
        self._drag_preview_line.setPen(QPen(QColor(source.sock_def.color), DRAG_PREVIEW_LINE_WIDTH, Qt.DashLine))
        self._drag_preview_line.setZValue(-0.5)
        self._drag_preview_line.setLine(origin.x(), origin.y(), origin.x(), origin.y())
        super().addItem(self._drag_preview_line)

    def mousePressEvent(self, event):
        selected_before = self.selectedItems()
        self._pre_click_selection = selected_before

        # Group frame needs to track relative node movement during drag. We seed
        # the live drag list from the committed _group_members snapshot (refreshed
        # on every release). We no longer augment this list with newly-overlapping
        # nodes at press time, since dragging a frame over a node shouldn't add it.
        for item in self.items():
            if isinstance(item, GroupFrameItem):
                committed = list(getattr(item, '_group_members', []) or [])
                item._dragged_inner_nodes = [n for n in committed if n.scene() is self]

        # Frame header is a drag handle the user expects to always reach — like a
        # node's header. The frame paints below nodes (Z=GROUP_FRAME_Z), so once
        # nodes overlap, clicks on the header land on the node instead. Lift the
        # frame's Z just for this press so the default item picker routes to it;
        # restore right after super() runs.
        self._frame_z_boost = None
        scene_pos = event.scenePos()
        for frame in self.items():
            if not isinstance(frame, GroupFrameItem):
                continue
            local = frame.mapFromScene(scene_pos)
            rect = frame.rect()
            in_header = (rect.left() <= local.x() <= rect.right()
                         and rect.top() <= local.y() <= rect.top() + GROUP_FRAME_HEADER_HEIGHT)
            if in_header and frame._edge_at(local) is None:
                self._frame_z_boost = (frame, frame.zValue())
                frame.setZValue(NODE_DRAG_Z + 1)
                break

        from PyQt5.QtGui import QTransform
        from PyQt5.QtWidgets import QGraphicsProxyWidget
        clicked_item = self.itemAt(event.scenePos(), QTransform())
        
        is_proxy_click = False
        curr = clicked_item
        while curr:
            if isinstance(curr, QGraphicsProxyWidget):
                is_proxy_click = True
                break
            curr = curr.parentItem()

        try:
            super().mousePressEvent(event)
        finally:
            self._pre_click_selection = None
            if self._frame_z_boost is not None:
                frame, original_z = self._frame_z_boost
                frame.setZValue(original_z)
                self._frame_z_boost = None

        if is_proxy_click and selected_before:
            for item in selected_before:
                if item.scene() == self:
                    item.setSelected(True)

        self._drag_start_positions = {item: item.pos() for item in self.selectedItems() if isinstance(item, MetaNode)}
        
        # Why: Raised Z-value prevents dragged nodes from clipping under siblings.
        self._dragged_nodes = []
        selected_meta = [item for item in self.selectedItems() if isinstance(item, MetaNode)]
        self._dragged_nodes.extend(selected_meta)
        for item in self.selectedItems():
            if isinstance(item, GroupFrameItem):
                for other in getattr(item, '_dragged_inner_nodes', []):
                    if other not in self._dragged_nodes:
                        self._dragged_nodes.append(other)
                        
        for node in self._dragged_nodes:
            if not hasattr(node, '_original_z'):
                node._original_z = node.zValue()
            node.setZValue(NODE_DRAG_Z)

    def _restore_dragged_z(self):
        # Why: Reverts Z lift post-drag and clears local group memberships.
        for node in getattr(self, '_dragged_nodes', []):
            if hasattr(node, '_original_z'):
                node.setZValue(node._original_z)
                del node._original_z
        self._dragged_nodes = []
        for item in self.items():
            if isinstance(item, GroupFrameItem):
                item._dragged_inner_nodes = []

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
            if out_sock.sock_def.is_exec and c.source == out_sock:
                if c.scene():
                    self.removeItem(c)
                if c in win.connections:
                    win.connections.remove(c)
            if c.dest == in_sock:
                if c.scene():
                    self.removeItem(c)
                if c in win.connections:
                    win.connections.remove(c)

    def mouseReleaseEvent(self, event):
        if self._drag_active:
            target        = self._find_compatible_socket(event.scenePos())
            source_socket = self._drag_source
            original_dest = self._drag_original_dest
            self._cancel_connection_drag()
            if target:
                out_sock = source_socket if source_socket.sock_def.kind == "output" else target
                in_sock  = target if source_socket.sock_def.kind == "output" else source_socket
                self._enforce_connection_rules(out_sock, in_sock)
                conn = Connection(out_sock, in_sock)
                super().addItem(conn)
                if self.nodeEditorWindow:
                    self.nodeEditorWindow.connections.append(conn)
                    in_sock.meta_node._refresh_connections()
                    self.nodeEditorWindow.push_undo_state()
            else:
                if self.nodeEditorWindow:
                    self._show_node_creation_menu(
                        event.scenePos(), event.screenPos(),
                        source_socket=source_socket,
                        original_dest=original_dest
                    )
        else:
            super().mouseReleaseEvent(event)
            moved = False
            if hasattr(self, "_drag_start_positions"):
                for item, start_pos in self._drag_start_positions.items():
                    if item.scene() and item.pos() != start_pos:
                        moved = True
                        break
                self._drag_start_positions = {}
            if moved and self.nodeEditorWindow:
                self.nodeEditorWindow.push_undo_state()
        self._restore_dragged_z()

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

        result = dialog.exec_()

        view = self.views()[0] if self.views() else None
        if view and result != QDialog.Accepted and bool(QApplication.mouseButtons() & Qt.LeftButton):
            view._suppress_redelivered_click = True

        if result == QDialog.Accepted:
            win._block_undo_push = True
            try:
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
            finally:
                win._block_undo_push = False
            win.push_undo_state()
