"""scene.py — Canvas Scene: Grid, Connection Drags and Item Picking

Manages typed connections between nodes (exec↔exec / param↔param), the
connection drag preview, frame-header picking, and the pre-click selection
snapshot the linked mass-edit machinery relies on.
"""
from __future__ import annotations
from typing import Optional, Tuple

from PyQt5.QtWidgets import QGraphicsScene, QGraphicsLineItem, QGraphicsProxyWidget, QDialog, QApplication
from PyQt5.QtCore import Qt, QPointF, QRectF, QTimer
from PyQt5.QtGui import QPen, QColor, QPainter, QTransform

from configuration import (
    CANVAS_BACKGROUND_COLOR, GRID_SIZE_SMALL, GRID_SIZE_LARGE, GRID_MIN_SPACING_PX,
    GRID_COLOR_SMALL, GRID_COLOR_LARGE, SCENE_PADDING,
    SCENE_INITIAL_X, SCENE_INITIAL_Y, SCENE_INITIAL_WIDTH, SCENE_INITIAL_HEIGHT,
    DRAG_PREVIEW_LINE_WIDTH, NODE_DRAG_Z, GROUP_FRAME_HEADER_HEIGHT,
    NODE_LOD_DETAIL_SCALE,
)
from ui.search_menu import SearchMenuDialog
from ui.graph_items import Connection, SocketItem, MetaNode, GroupFrameItem


class NodeScene(QGraphicsScene):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.nodeEditorWindow = None
        self._drag_source: Optional[SocketItem] = None
        self._drag_preview_line: Optional[QGraphicsLineItem] = None
        self._drag_active = False
        self._drag_original_dest: Optional[SocketItem] = None
        self._rect_recalc_pending = False
        # Bring-to-front counter for nodes just dragged (see _restore_dragged_z):
        # each drag hands out the next value, so the most recently moved node
        # always reads as "on top" of siblings that haven't moved since.
        self._next_node_z = 1.0
        # Maintained alongside addItem/removeItem so hot paths (recalculate_
        # scene_rect on every drag-release, _adopt_containing_frame on every
        # node drop, GroupFrameItem._contained_nodes' fallback) don't each
        # pay for their own scene.items() scan — which also re-sorts the
        # whole scene by Z-order — just to filter down to MetaNode/
        # GroupFrameItem. Nothing removes an item from this scene except via
        # removeItem (clear_graph loops removeItem per item; scene.clear()
        # is never called on a NodeScene), so these stay accurate.
        self._meta_nodes: list = []
        self._group_frames: list = []
        self.setSceneRect(SCENE_INITIAL_X, SCENE_INITIAL_Y, SCENE_INITIAL_WIDTH, SCENE_INITIAL_HEIGHT)
        self.setBackgroundBrush(QColor(CANVAS_BACKGROUND_COLOR))
        self.grid_visible = True

    def _grid_steps(self, scale: float) -> Tuple[float, float]:
        """(minor, major) grid step in scene units, coarsened together as
        needed so neither tier's on-screen spacing drops below
        GRID_MIN_SPACING_PX.

        Why escalate instead of just skipping the minor tier when it gets
        too dense: escalating both steps by the same ratio (major stays
        exactly 5x minor, same as the base 20/100 pair) reproduces the usual
        "zoom out and the grid re-tiles to a coarser unit" behavior instead
        of the minor grid abruptly disappearing while the major one stays
        fixed — the visual rhythm of the grid stays consistent across the
        whole zoom range instead of changing shape at one particular level.
        """
        minor = float(GRID_SIZE_SMALL)
        major = float(GRID_SIZE_LARGE)
        ratio = major / minor
        for _ in range(8):  # 5**8 is far beyond any zoom this app allows
            if minor * scale >= GRID_MIN_SPACING_PX:
                break
            minor *= ratio
            major *= ratio
        return minor, major

    def drawBackground(self, painter: QPainter, rect: QRectF):
        painter.fillRect(rect, QColor(CANVAS_BACKGROUND_COLOR))
        if not getattr(self, "grid_visible", True):
            return

        # Cosmetic pens (width 0) always rasterize as exactly one device
        # pixel regardless of the view's current zoom transform, and drawing
        # without antialiasing snaps that pixel to a single hard row/column
        # instead of splitting its coverage (softly) across two — together
        # these keep every line crisp at any zoom instead of thinning into a
        # blurred, partially-transparent smear the way a pre-rendered grid
        # bitmap does when the view scales it away from its native size.
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)
        scale = painter.transform().m11()
        minor_step, major_step = self._grid_steps(scale)
        # An integer count of minor cells per major cell, always exact since
        # both steps are scaled up from GRID_SIZE_SMALL/LARGE by the same
        # factor together (see _grid_steps) — used to tell a minor line that
        # coincides with a major one apart by integer line *index* instead of
        # a float `x % major_step` check, which drifts by accumulated
        # floating-point error over a wide rect and can misfire right at the
        # seam it exists to avoid.
        minor_per_major = round(major_step / minor_step)

        painter.setPen(QPen(QColor(*GRID_COLOR_SMALL), 0))
        i = int(rect.left() // minor_step)
        i_end = int(rect.right() // minor_step) + 1
        while i <= i_end:
            if i % minor_per_major != 0:
                x = i * minor_step
                painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            i += 1
        j = int(rect.top() // minor_step)
        j_end = int(rect.bottom() // minor_step) + 1
        while j <= j_end:
            if j % minor_per_major != 0:
                y = j * minor_step
                painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            j += 1

        painter.setPen(QPen(QColor(*GRID_COLOR_LARGE), 0))
        mi = int(rect.left() // major_step)
        mi_end = int(rect.right() // major_step) + 1
        while mi <= mi_end:
            x = mi * major_step
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            mi += 1
        mj = int(rect.top() // major_step)
        mj_end = int(rect.bottom() // major_step) + 1
        while mj <= mj_end:
            y = mj * major_step
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            mj += 1
        painter.restore()

    def recalculate_scene_rect(self):
        nodes = self._meta_nodes
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
            self._meta_nodes.append(item)
            self._schedule_rect_recalc()
            # A node created while this scene is already on screen and
            # zoomed out past the LOD threshold should start simplified
            # too — otherwise it would paint in full detail (and cost a
            # widget/text layout it's about to have hidden anyway) until
            # the next zoom/tab-switch event re-applies LOD (see
            # GraphicsView._apply_lod). No view yet (a background tab
            # being materialized) just means there's nothing to match.
            views = self.views()
            if views:
                far = views[0].transform().m11() < NODE_LOD_DETAIL_SCALE
                item._set_lod_far(far)
        elif isinstance(item, GroupFrameItem):
            self._group_frames.append(item)
            # Its __init__ already centered the title assuming near/1:1 LOD
            # (there was no scene — and so no view scale — to check yet) —
            # apply the real current state now, for a frame created directly
            # into an already-zoomed-out scene.
            views = self.views()
            if views:
                far = views[0].transform().m11() < NODE_LOD_DETAIL_SCALE
                item._set_lod_far(far)
        elif isinstance(item, Connection):
            # The one choke point every Connection passes through on its way
            # into the scene, regardless of which of the many call sites
            # created it (editor_window, graph_serialization, scene's own
            # drag-release, splice-into-wire) — see SocketItem._connection_count
            # docstring. Repainting both endpoint nodes (not just the socket's
            # own small rect) is what actually reveals/re-covers the punched
            # hole in MetaNode.paint()'s body/header fill.
            item.source._connection_count += 1
            item.dest._connection_count += 1
            item.source.meta_node.update()
            item.dest.meta_node.update()

    def removeItem(self, item):
        super().removeItem(item)
        if isinstance(item, MetaNode):
            try:
                self._meta_nodes.remove(item)
            except ValueError:
                pass
        elif isinstance(item, GroupFrameItem):
            try:
                self._group_frames.remove(item)
            except ValueError:
                pass
        elif isinstance(item, Connection):
            for sock in (item.source, item.dest):
                try:
                    sock._connection_count = max(0, sock._connection_count - 1)
                    sock.meta_node.update()
                except RuntimeError:
                    pass  # the endpoint node/socket was already deleted

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
        # The ghost preview (hover-only affordance) would otherwise keep
        # showing its own dashed wire alongside the live drag preview line
        # below — redundant and visually competing with it.
        source._hide_ghost()
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
        for item in self._group_frames:
            committed = list(getattr(item, '_group_members', []) or [])
            item._dragged_inner_nodes = [n for n in committed if n.scene() is self]

        # Frame header is a drag handle the user expects to always reach — like a
        # node's header. The frame paints below nodes (Z=GROUP_FRAME_Z), so once
        # nodes overlap, clicks on the header land on the node instead. Lift the
        # frame's Z just for this press so the default item picker routes to it;
        # restore right after super() runs.
        self._frame_z_boost = None
        scene_pos = event.scenePos()
        for frame in self._group_frames:
            local = frame.mapFromScene(scene_pos)
            rect = frame.rect()
            in_header = (rect.left() <= local.x() <= rect.right()
                         and rect.top() <= local.y() <= rect.top() + GROUP_FRAME_HEADER_HEIGHT)
            if in_header and frame._edge_at(local) is None:
                self._frame_z_boost = (frame, frame.zValue())
                frame.setZValue(NODE_DRAG_Z + 1)
                break

        # Use the view's actual transform, not an identity one — itemAt's hit
        # test depends on it (e.g. SocketItem/GroupFrameItem shape() changes
        # at LOD-far scale), so an identity transform here could resolve a
        # different item than contextMenuEvent does for the same scene_pos.
        view = self.views()[0] if self.views() else None
        transform = view.transform() if view else QTransform()
        clicked_item = self.itemAt(event.scenePos(), transform)

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

    def _restore_dragged_z(self, bring_to_front: bool = False):
        """Reverts the drag-time Z lift. When the drag actually moved
        something (``bring_to_front``), the node keeps a freshly-assigned,
        permanently higher resting Z instead of reverting to what it had
        before — it now reads as on top of siblings that haven't moved since,
        the way raising a window works elsewhere. A node opting out via
        ``always_on_top`` (the StartNode) is left exactly where it is and
        never joins this stacking order.
        """
        for node in getattr(self, '_dragged_nodes', []):
            original_z = getattr(node, '_original_z', 0.0)
            if hasattr(node, '_original_z'):
                del node._original_z
            if bring_to_front and not getattr(node, 'always_on_top', False):
                node._set_resting_z(self._next_node_z)
                self._next_node_z += 1
            else:
                node._set_resting_z(original_z)
        self._dragged_nodes = []
        for item in self._group_frames:
            item._dragged_inner_nodes = []

    def mouseMoveEvent(self, event):
        if self._drag_active and self._drag_preview_line and self._drag_source:
            origin = self._drag_source.scene_center()
            cursor = event.scenePos()
            self._drag_preview_line.setLine(origin.x(), origin.y(), cursor.x(), cursor.y())
        super().mouseMoveEvent(event)

    def enforce_connection_rules(self, out_sock, in_sock):
        """One wire per input; one exec wire out of an exec output."""
        win = self.nodeEditorWindow
        if not win:
            return
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
        moved = False
        if self._drag_active:
            target        = self._find_compatible_socket(event.scenePos())
            source_socket = self._drag_source
            original_dest = self._drag_original_dest
            self._cancel_connection_drag()
            if target:
                out_sock = source_socket if source_socket.sock_def.kind == "output" else target
                in_sock  = target if source_socket.sock_def.kind == "output" else source_socket
                self.enforce_connection_rules(out_sock, in_sock)
                conn = Connection(out_sock, in_sock)
                self.addItem(conn)
                if self.nodeEditorWindow:
                    self.nodeEditorWindow.connections.append(conn)
                    in_sock.meta_node._refresh_connections()
                    self.nodeEditorWindow.push_undo_state()
            else:
                if self.nodeEditorWindow:
                    # An exec source spawns exactly where its hover ghost
                    # promised (SocketItem.ghost_spawn_pos) — automatically
                    # right of an output / left of an input — rather than
                    # wherever the drag happened to end; the ghost is a
                    # direct instruction for the spawn, not just a preview.
                    # A param source keeps the previous drop-position behavior.
                    spawn_pos = (source_socket.ghost_spawn_pos() if source_socket.sock_def.is_exec
                                 else event.scenePos())
                    self.show_node_creation_menu(
                        spawn_pos, event.screenPos(),
                        source_socket=source_socket,
                        original_dest=original_dest
                    )
        else:
            super().mouseReleaseEvent(event)
            moved = self._reconcile_dragged_node_state()
            if moved and self.nodeEditorWindow:
                self.nodeEditorWindow.push_undo_state()
        self._restore_dragged_z(bring_to_front=moved)

    def _reconcile_dragged_node_state(self) -> bool:
        """After a plain (non-connection) drag release: which selected nodes
        actually moved, and re-adopt each into whichever group frame now sits
        under it. Every selected MetaNode here, not just the one Qt actually
        delivered the mouse events to — when several nodes are selected
        together, dragging any one of them moves the rest of the selection
        too via Qt's own internal group-move, but only the grabber gets its
        own mouseReleaseEvent (which is where MetaNode._adopt_containing_frame
        normally runs). Every other moved node's group-frame membership was
        never re-evaluated, letting a node dragged out of (or into) a frame's
        bounds as part of a multi-select drag keep stale membership until
        some unrelated later action forced a full commit_members(force_all=
        True) rebuild. Re-running it here for every node that actually moved
        closes that gap; it's a cheap no-op for the grabber, which already
        did this once via its own event.

        Returns whether anything actually moved (for the undo-push decision).
        """
        moved = False
        if not hasattr(self, "_drag_start_positions"):
            return moved
        for item, start_pos in self._drag_start_positions.items():
            if item.scene() and item.pos() != start_pos:
                moved = True
                item._adopt_containing_frame(self)
        self._drag_start_positions = {}
        return moved

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
        # The cursor is very likely still resting on the source socket right
        # after a release (no hoverEnterEvent fires again to tell us that —
        # Qt already considers it "entered"), so re-show the ghost we hid in
        # start_connection_drag instead of leaving it gone until the cursor
        # happens to leave and re-enter.
        if (self._drag_source is not None and self._drag_source.sock_def.is_exec
                and self._drag_source._hovered):
            self._drag_source._show_ghost()
        self._drag_active = False
        self._drag_source = None

    def contextMenuEvent(self, event):
        view      = self.views()[0] if self.views() else None
        transform        = view.transform() if view else None
        item_under_cursor = self.itemAt(event.scenePos(), transform) if transform else None
        if not item_under_cursor or isinstance(item_under_cursor, Connection):
            self.show_node_creation_menu(event.scenePos(), event.screenPos())
            event.accept()
        else:
            super().contextMenuEvent(event)

    def show_node_creation_menu(self, scene_pos: QPointF, screen_pos, source_socket=None, original_dest=None):
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
                    self.enforce_connection_rules(out_sock, in_sock)
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
                                self.enforce_connection_rules(c_out_sock, original_dest)
                                conn2 = Connection(c_out_sock, original_dest)
                            else:
                                self.enforce_connection_rules(original_dest, c_out_sock)
                                conn2 = Connection(original_dest, c_out_sock)
                            self.addItem(conn2)
                            win.connections.append(conn2)
            finally:
                win._block_undo_push = False
            win.push_undo_state()
