"""scene.py — Canvas Scene: Grid, Connection Drags and Item Picking

Manages typed connections between nodes (exec↔exec / param↔param), the
connection drag preview, frame-header picking, and the pre-click selection
snapshot the linked mass-edit machinery relies on.
"""
from __future__ import annotations
from typing import Optional, Tuple

from PyQt5.QtWidgets import QGraphicsScene, QGraphicsLineItem, QGraphicsProxyWidget, QDialog, QApplication
from PyQt5.QtCore import Qt, QPointF, QRectF, QSizeF, QTimer
from PyQt5.QtGui import QPen, QColor, QPainter, QTransform

from configuration import (
    CANVAS_BACKGROUND_COLOR, GRID_SIZE_SMALL, GRID_SIZE_LARGE, GRID_MIN_SPACING_PX,
    GRID_COLOR_SMALL, GRID_COLOR_LARGE, SCENE_PADDING,
    SCENE_INITIAL_X, SCENE_INITIAL_Y, SCENE_INITIAL_WIDTH, SCENE_INITIAL_HEIGHT,
    DRAG_PREVIEW_LINE_WIDTH, NODE_DRAG_Z, GROUP_FRAME_HEADER_HEIGHT,
    NODE_LOD_DETAIL_SCALE, GHOST_NODE_WIDTH, GHOST_NODE_HEIGHT, NODE_HEADER_HEIGHT,
    GHOST_SPLICE_DETACH_DISTANCE, GHOST_RAY_Y_TOLERANCE,
)
from ui.search_menu import SearchMenuDialog
from ui.graph_items import Connection, SocketItem, MetaNode, GroupFrameItem, snap_to_grid
from ui.search_ranking import usage_key, context_key_for_socket
from core.app_prefs import record_search_usage


class NodeScene(QGraphicsScene):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.nodeEditorWindow = None
        self._drag_source: Optional[SocketItem] = None
        self._drag_preview_line: Optional[QGraphicsLineItem] = None
        self._drag_active = False
        self._drag_original_dest: Optional[SocketItem] = None
        self._drag_press_scene_pos: Optional[QPointF] = None
        # The real Connection to original_dest, hidden for as long as the
        # splice preview (ghost wired to both nodes) is showing in its
        # place — see _update_drag_ghost/_cancel_connection_drag. Prevents
        # the real wire and the ghost's own preview wire from both being on
        # screen, overlapping, at once.
        self._drag_hidden_connection: Optional[Connection] = None
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
        if item.scene() is not self:
            # Already gone — some other path (MetaNode._swap_node's own
            # scene.removeItem(self), _delete_node_bridging_exec, a second
            # clear_graph pass) already removed this exact item. Qt's own
            # QGraphicsScene.removeItem() prints a loud "item's scene is
            # different from this scene" warning for what is otherwise
            # already a no-op; skip straight to it instead of letting Qt
            # complain about work that was never going to happen anyway.
            return
        super().removeItem(item)
        if isinstance(item, MetaNode):
            try:
                self._meta_nodes.remove(item)
            except ValueError:
                pass
            # A socket's ghost preview (SocketItem._ensure_ghost) is a
            # top-level scene item, never a Qt child of its socket/node —
            # removing the node here would otherwise leave any ghost it
            # ever built for a hover dangling in the scene forever
            # (invisible, but still alive and still holding a reference
            # back to this now-removed node/socket, leaking both).
            for socket in item.sockets.values():
                ghost = getattr(socket, "_ghost", None)
                if ghost is not None and ghost.scene() is self:
                    super().removeItem(ghost)
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

    def start_connection_drag(self, source: SocketItem, press_scene_pos: QPointF):
        self._drag_active = True
        self._drag_source = source
        self._drag_original_dest = None
        self._drag_press_scene_pos = press_scene_pos
        # An unconnected exec socket's ghost stays visible through the drag
        # instead of being hidden — see _update_drag_ghost, called from
        # mouseMoveEvent, which lets it track the cursor to an arbitrary
        # drop spot once the drag moves past a plain click. A connected
        # socket (mid-rewire/splice) or a param socket never had a ghost to
        # begin with (SocketItem.hoverEnterEvent), so there is nothing to
        # hide for those.
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
            self._update_drag_ghost(cursor)
            endpoint = self._drag_line_endpoint(cursor)
            self._drag_preview_line.setLine(origin.x(), origin.y(), endpoint.x(), endpoint.y())
        super().mouseMoveEvent(event)

    def _drag_line_endpoint(self, cursor_scene_pos: QPointF) -> QPointF:
        """The one dashed drag-preview line's own endpoint: magnetized onto
        the ghost's own facing socket (in scene coords) whenever the ghost
        is actually showing, instead of the raw cursor position — so there
        is exactly one line, already snapped to where the spawned node's
        socket will land, not a second cursor-following line competing with
        the ghost's own (see _SocketGhostPreview.paint, which now only ever
        draws its wire in plain-hover display, never mid-drag). Falls back
        to the raw cursor whenever there is no ghost to lock onto — hovering
        a compatible target socket, or a param source, which never gets one.
        """
        source = self._drag_source
        ghost = source._ghost if source is not None else None
        if ghost is not None and ghost.isVisible():
            return ghost.mapToScene(ghost._facing_socket_pos())
        return cursor_scene_pos

    def _update_drag_ghost(self, cursor_scene_pos: QPointF) -> None:
        """Dragging a connection out of an exec socket to empty canvas is
        what pulls the ghost node preview off its fixed hover spot and has
        it follow the cursor instead — to an arbitrary place, snapped to
        the grid the same way ghost_spawn_pos() already is, previewing
        exactly where mouseReleaseEvent will actually spawn the node. Left
        at its fixed hover position until the drag moves past a plain click
        (SocketItem.ghost_spawn_pos's own 3-cell default still applies to
        that case — see mouseReleaseEvent). Hidden outright while hovering
        a compatible target socket, since dropping there connects to that
        existing node instead of spawning a new one. A param source never
        had a ghost to move in the first place (SocketItem.hoverEnterEvent).

        Dragging off an *already-connected* socket additionally previews
        the splice: the ghost's other socket wires to the original far
        socket (_drag_original_dest) as long as the cursor stays within
        splice range of the original straight line between the two real
        sockets (_splice_still_attached) — see set_splice_target.

        If the ghost's own rect at that grid-snapped spot collides with an
        existing node's footprint (_ghost_collision_socket), the ghost
        drops its own placeholder entirely and adopts that node's exact
        position/size instead — release then connects directly into it
        (mouseReleaseEvent), same as landing precisely on one of its
        sockets, just with a much larger, more forgiving target area.
        Collision takes priority over the splice preview: only one "this is
        what happens on release" story is shown at a time.
        """
        source = self._drag_source
        if source is None or not source.sock_def.is_exec:
            return
        if self._drag_press_scene_pos is None:
            return
        moved = (cursor_scene_pos - self._drag_press_scene_pos).manhattanLength() > QApplication.startDragDistance()
        if not moved:
            return
        if self._find_compatible_socket(cursor_scene_pos):
            source._hide_ghost()
            self._set_splice_hidden(None)
            return
        top_left = self._drag_ghost_top_left(source, cursor_scene_pos)
        ghost = source._ensure_ghost()
        ghost_rect = QRectF(top_left, QSizeF(GHOST_NODE_WIDTH, GHOST_NODE_HEIGHT))
        collision_socket = self._ghost_collision_socket(source, ghost_rect)
        if collision_socket is not None:
            ghost.set_collision_target(collision_socket)
            ghost.set_splice_target(None)
            self._set_splice_hidden(None)
        else:
            ray_socket = self._ghost_ray_socket(source, cursor_scene_pos)
            if ray_socket is not None:
                ghost.set_ray_target(ray_socket)
                ghost.set_splice_target(None)
                self._set_splice_hidden(None)
            else:
                ghost.set_drag_override(top_left)
                original_dest = self._drag_original_dest
                if original_dest is not None:
                    spliced = self._splice_still_attached(source, original_dest, cursor_scene_pos)
                    ghost.set_splice_target(original_dest if spliced else None)
                    self._set_splice_hidden(self._find_connection_between(source, original_dest) if spliced else None)
        if ghost.isVisible():
            source._force_ghost_repaint()
        else:
            # Just the first-activation reveal — NOT SocketItem._show_ghost()
            # itself, which would redo its own near-collision detection
            # against the ghost's *own current rect*. That rect was only
            # just set above (set_collision_target/set_ray_target adopt the
            # target node's exact geometry onto the ghost) — re-running that
            # check would trivially "detect" a collision with whatever
            # target's geometry the ghost just adopted, clobbering a
            # ray_target back into a collision_target on the very same node
            # and effectively locking the ghost onto it: cursor_scene_pos no
            # longer had any say once that happened, since every later call
            # would keep re-detecting the same stale self-collision.
            ghost.setVisible(True)
            ghost.set_candidates(source._ranked_ghost_candidates())
            source._force_ghost_repaint()

    def _ghost_collision_socket(self, source: SocketItem, ghost_rect: QRectF) -> Optional[SocketItem]:
        """The first compatible socket on a node whose own footprint
        ``ghost_rect`` overlaps — a "collision" between the ghost preview
        and a real existing node. Compatibility mirrors
        _find_compatible_socket's own node-body fallback (opposite kind,
        same is_exec), just tested against the ghost's whole rect instead
        of the exact cursor point."""
        for node in self._meta_nodes:
            if node is source.meta_node:
                continue
            node_rect = QRectF(node.pos(), QSizeF(node.node_def.width, node.node_def.body_height))
            if not node_rect.intersects(ghost_rect):
                continue
            for s in node.sockets.values():
                if s.sock_def.kind != source.sock_def.kind and s.sock_def.is_exec == source.sock_def.is_exec:
                    return s
        return None

    def _ghost_ray_socket(self, source: SocketItem, cursor_scene_pos: Optional[QPointF] = None) -> Optional[SocketItem]:
        """A compatible socket on a node further out along the same row
        than _ghost_collision_socket's own near rect reaches — scanning
        outward in the drag direction (right off an output socket, left off
        an input one) for the *closest* node whose own exec row sits within
        GHOST_RAY_Y_TOLERANCE of ``cursor_scene_pos`` (falling back to the
        source socket's own Y when there's no cursor to speak of — the
        plain-hover, no-drag case, SocketItem._show_ghost). Restricted to
        nodes at least partially inside the current viewport — an
        off-screen node has no visual confirmation of what "hits" it, so
        hovering never reaches across a huge scene to one the user can't
        actually see land.

        Checking against the *cursor's* row (not always the source's own,
        fixed one) matters once an actual drag is under way
        (NodeScene._update_drag_ghost passes its cursor_scene_pos through):
        a match found once must let go the moment the user drags away from
        that row to place a plain new node elsewhere — otherwise, any node
        merely sitting in-line down the row from the source would keep the
        ghost locked onto it regardless of where the cursor actually moved,
        with no way to drag a fresh node out instead. A plain hover has no
        such cursor to track, so it keeps matching by the source's own row,
        exactly as before.

        Connecting to one found this way additionally snaps its Y to the
        source's row (_align_ray_target); a near collision never does."""
        view = self.views()[0] if self.views() else None
        if view is None or source is None:
            return None
        visible_rect = view.mapToScene(view.viewport().rect()).boundingRect()
        source_center = source.scene_center()
        reference_y = cursor_scene_pos.y() if cursor_scene_pos is not None else source_center.y()
        direction = 1 if source.sock_def.kind == "output" else -1

        best_socket: Optional[SocketItem] = None
        best_distance: Optional[float] = None
        for node in self._meta_nodes:
            if node is source.meta_node:
                continue
            node_rect = QRectF(node.pos(), QSizeF(node.node_def.width, node.node_def.body_height))
            if not visible_rect.intersects(node_rect):
                continue
            node_exec_y = node.pos().y() + NODE_HEADER_HEIGHT / 2.0
            if abs(node_exec_y - reference_y) > GHOST_RAY_Y_TOLERANCE:
                continue
            near_edge_x = node.pos().x() if direction > 0 else node.pos().x() + node.node_def.width
            if (near_edge_x - source_center.x()) * direction <= 0:
                continue  # behind the source, not ahead of it in the drag direction
            distance = abs(near_edge_x - source_center.x())
            if best_distance is not None and distance >= best_distance:
                continue
            for s in node.sockets.values():
                if s.sock_def.kind != source.sock_def.kind and s.sock_def.is_exec == source.sock_def.is_exec:
                    best_socket, best_distance = s, distance
                    break
        return best_socket

    def _align_ray_target(self, source_socket: SocketItem, target_socket: SocketItem) -> None:
        """The "align" half of the ray-target promise (_ghost_ray_socket) —
        matches the far node's own top Y to the source node's. An exec
        socket always sits at the same NODE_HEADER_HEIGHT/2 offset from its
        own node's top regardless of width (the same reasoning
        SocketItem.ghost_spawn_pos already uses for a freshly spawned
        node), so equal top-Y is exactly what makes the two exec rows
        level — turning "roughly aligned" into a perfectly straight wire.
        Never touches X."""
        target_node = target_socket.meta_node
        source_top_y = source_socket.meta_node.pos().y()
        if target_node.pos().y() != source_top_y:
            target_node.setPos(target_node.pos().x(), source_top_y)

    def _set_splice_hidden(self, conn: Optional["Connection"]) -> None:
        """Keeps at most one real Connection hidden at a time — whichever
        one the splice preview (_SocketGhostPreview's own wire to
        set_splice_target) is currently standing in for, so the real wire
        and the ghost's preview of it are never both on screen, overlapping,
        at once. Restores visibility of whatever was hidden before switching
        to a new one (or to none) — always called with ``None`` once the
        drag ends (_cancel_connection_drag), so nothing stays hidden past
        the drag regardless of how it finished."""
        if self._drag_hidden_connection is conn:
            return
        if self._drag_hidden_connection is not None:
            try:
                self._drag_hidden_connection.setVisible(True)
            except RuntimeError:
                pass  # the connection (or an endpoint) was deleted mid-drag
        self._drag_hidden_connection = conn
        if conn is not None:
            conn.setVisible(False)

    @staticmethod
    def _splice_still_attached(source: SocketItem, original_dest: SocketItem,
                                cursor_scene_pos: QPointF) -> bool:
        """Whether the cursor is still close enough to the original
        straight source->original_dest line (perpendicular distance,
        clamped to the segment) to keep previewing — and, on release,
        actually create — the splice connection to that far socket. Beyond
        GHOST_SPLICE_DETACH_DISTANCE (dragged far away, or off at a sharp
        angle/"kink" from that original line) it returns False, meaning the
        ghost is wired only to the socket it was dragged from."""
        p1 = source.scene_center()
        p2 = original_dest.scene_center()
        seg_x, seg_y = p2.x() - p1.x(), p2.y() - p1.y()
        seg_len2 = seg_x * seg_x + seg_y * seg_y
        if seg_len2 == 0:
            return False
        t = ((cursor_scene_pos.x() - p1.x()) * seg_x + (cursor_scene_pos.y() - p1.y()) * seg_y) / seg_len2
        t = max(0.0, min(1.0, t))
        closest_x, closest_y = p1.x() + seg_x * t, p1.y() + seg_y * t
        dx, dy = cursor_scene_pos.x() - closest_x, cursor_scene_pos.y() - closest_y
        return (dx * dx + dy * dy) ** 0.5 <= GHOST_SPLICE_DETACH_DISTANCE

    @staticmethod
    def _drag_ghost_top_left(source: SocketItem, cursor_scene_pos: QPointF) -> QPointF:
        """Where the ghost's own top-left lands for a given cursor position:
        the cursor marks the ghost's own facing socket (same convention as
        _SocketGhostPreview._facing_socket_pos — left edge/header-mid-height
        for an output ghost, right edge for an input one), grid-snapped via
        snap_to_grid exactly like every other node position."""
        x = cursor_scene_pos.x() if source.sock_def.kind == "output" else cursor_scene_pos.x() - GHOST_NODE_WIDTH
        y = cursor_scene_pos.y() - NODE_HEADER_HEIGHT / 2.0
        return QPointF(snap_to_grid(x), snap_to_grid(y))

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
            source_socket = self._drag_source
            # A collision (the ghost's own rect overlapping a compatible
            # node's footprint — _ghost_collision_socket) is a fallback
            # target exactly like landing precisely on a socket, just with
            # a much larger hit area. Read straight off the ghost itself
            # (the one source of truth for it — set either by a plain hover
            # already sitting on a collision, SocketItem._show_ghost, or by
            # _update_drag_ghost once the drag has actually moved) rather
            # than a separately tracked flag, so a short click with no
            # movement — which never runs _update_drag_ghost's own check —
            # still honors a collision that was already there from hover.
            ghost = source_socket._ghost if source_socket is not None else None
            collision_target = ghost._collision_target if ghost is not None else None
            # A ray_target (NodeScene._ghost_ray_socket, a node further out
            # along the row than collision_target's own near rect reaches)
            # connects exactly like collision_target — the only difference
            # is that landing on it also re-aligns that node's Y once the
            # connection below is actually made (_align_ray_target).
            ray_target = ghost._ray_target if ghost is not None else None
            # Read off the ghost before _cancel_connection_drag() below wipes
            # it (a fresh _show_ghost() call resets candidate selection) —
            # side-button cycling (SocketItem.mousePressEvent) may have
            # landed the ghost on a specific next-node pick; a target/
            # collision (an existing socket to wire straight into) still
            # takes priority over it below.
            candidate_payload = ghost.selected_candidate_payload() if ghost is not None else None
            target        = self._find_compatible_socket(event.scenePos()) or collision_target or ray_target
            original_dest = self._drag_original_dest
            press_pos     = self._drag_press_scene_pos
            self._cancel_connection_drag()
            click_in_place = (
                press_pos is not None
                and (event.scenePos() - press_pos).manhattanLength() <= QApplication.startDragDistance()
            )
            if target:
                out_sock = source_socket if source_socket.sock_def.kind == "output" else target
                in_sock  = target if source_socket.sock_def.kind == "output" else source_socket
                self.enforce_connection_rules(out_sock, in_sock)
                conn = Connection(out_sock, in_sock)
                self.addItem(conn)
                if self.nodeEditorWindow:
                    self.nodeEditorWindow.connections.append(conn)
                    in_sock.meta_node._refresh_connections()
                    if target is ray_target and ray_target is not None:
                        self._align_ray_target(source_socket, ray_target)
                    self.nodeEditorWindow.push_undo_state()
            elif click_in_place and original_dest is not None and source_socket.sock_def.is_exec:
                # The "-" affordance (SocketItem.paint/hoverEnterEvent): a
                # plain click (no drag) on an already-connected exec socket
                # just drops its one existing wire — no search menu, unlike
                # the same click on an unconnected socket ("+"), which offers
                # to spawn one.
                self._disconnect_exec_socket(source_socket, original_dest)
            else:
                if self.nodeEditorWindow:
                    # A plain click on an exec socket (no real drag) spawns
                    # at its fixed ghost_spawn_pos default. An actual drag to
                    # empty canvas — connected source or not — spawns
                    # wherever the drag ghost was last tracking the cursor
                    # (_update_drag_ghost/_drag_ghost_top_left) — an
                    # arbitrary, grid-snapped spot, not the fixed default. A
                    # param source keeps the previous drop-position behavior.
                    final_original_dest = original_dest
                    if source_socket.sock_def.is_exec and not click_in_place:
                        spawn_pos = self._drag_ghost_top_left(source_socket, event.scenePos())
                        # A connected source's far socket only comes along
                        # for the ride (splice) if the drag is still within
                        # splice range at release — see
                        # _splice_still_attached/_SocketGhostPreview's
                        # matching splice-preview wire. Dragged too far/
                        # sharply away, and it's a plain detach: the far
                        # node loses its connection instead of being spliced
                        # into the new one.
                        if (original_dest is not None
                                and not self._splice_still_attached(source_socket, original_dest, event.scenePos())):
                            final_original_dest = None
                    elif source_socket.sock_def.is_exec:
                        spawn_pos = source_socket.ghost_spawn_pos()
                    else:
                        spawn_pos = event.scenePos()
                    if candidate_payload is not None:
                        # Side-button cycling already picked a specific node
                        # and the ghost was showing it — honor that promise
                        # and spawn it straight away instead of reopening the
                        # search menu to ask the same question again.
                        self._spawn_ghost_candidate(spawn_pos, candidate_payload, source_socket, final_original_dest)
                    else:
                        self.show_node_creation_menu(
                            spawn_pos, event.screenPos(),
                            source_socket=source_socket,
                            original_dest=final_original_dest
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

    def _find_connection_between(self, a: SocketItem, b: SocketItem) -> Optional[Connection]:
        """The single Connection wiring ``a`` to ``b`` — both an exec input
        and an exec output are capped at one wire (enforce_connection_rules),
        so this pair identifies at most one Connection regardless of which
        end is "source" vs "dest" on it. Shared by _disconnect_exec_socket
        and _update_drag_ghost's real-time splice hide/reveal."""
        win = self.nodeEditorWindow
        if not win:
            return None
        for c in win.connections:
            if {c.source, c.dest} == {a, b}:
                return c
        return None

    def _disconnect_exec_socket(self, source_socket: SocketItem, other: SocketItem) -> None:
        """Removes the single Connection between ``source_socket`` and
        ``other``."""
        win = self.nodeEditorWindow
        if not win:
            return
        conn = self._find_connection_between(source_socket, other)
        if conn is not None:
            if conn.scene():
                self.removeItem(conn)
            win.connections.remove(conn)
            win.push_undo_state()

    def _cancel_connection_drag(self):
        if self._drag_preview_line:
            self.removeItem(self._drag_preview_line)
            self._drag_preview_line = None
        # Whatever real Connection the splice preview stood in for gets its
        # visibility back regardless of how the drag ends — if it's actually
        # being replaced (splice succeeded), mouseReleaseEvent's own
        # enforce_connection_rules call removes it properly right after this;
        # otherwise (detached, cancelled) it simply stays exactly as it was.
        self._set_splice_hidden(None)
        # _update_drag_ghost may have pulled the source's ghost off its
        # fixed hover spot to follow the cursor — always drop that override
        # first (via _hide_ghost) so a re-show below (or the next plain
        # hover) starts fresh at the fixed ghost_spawn_pos formula, not
        # wherever this drag happened to leave it.
        if self._drag_source is not None:
            self._drag_source._hide_ghost()
        # The cursor is very likely still resting on the source socket right
        # after a release (no hoverEnterEvent fires again to tell us that —
        # Qt already considers it "entered"), so re-show the ghost instead
        # of leaving it gone until the cursor happens to leave and re-enter.
        if (self._drag_source is not None and self._drag_source.sock_def.is_exec
                and self._drag_source._hovered and not self._drag_source.is_connected()):
            self._drag_source._show_ghost()
        self._drag_active = False
        self._drag_source = None
        self._drag_press_scene_pos = None

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

        # Anchor on scene_pos — already the exact spot the new node lands at
        # (ghost_spawn_pos()/_drag_ghost_top_left, set by mouseReleaseEvent
        # before calling here) — instead of the raw cursor position, so the
        # menu opens visually out of the ghost silhouette that was already
        # showing "the new node goes here" rather than wherever the mouse
        # happened to be released. Falls back to screen_pos verbatim when
        # there's no view to map through (still exact for the plain
        # right-click case, where scene_pos already *is* the click point).
        view = self.views()[0] if self.views() else None
        anchor_pos = view.mapToGlobal(view.mapFromScene(scene_pos)) if view else screen_pos

        dialog = SearchMenuDialog(win.command_categories, win, source_socket=source_socket)
        dialog.set_anchor_pos(anchor_pos)

        result = dialog.exec_()

        if view and result != QDialog.Accepted and bool(QApplication.mouseButtons() & Qt.LeftButton):
            view._suppress_redelivered_click = True

        if result == QDialog.Accepted:
            win._block_undo_push = True
            try:
                self._spawn_node_payload(scene_pos, dialog.payload, source_socket, original_dest)
            finally:
                win._block_undo_push = False
            win.push_undo_state()

    def _spawn_node_payload(self, scene_pos: QPointF, payload, source_socket=None, original_dest=None):
        """Places ``payload`` (a command or param spec) at ``scene_pos`` and,
        given a ``source_socket``, wires it in exactly like accepting it
        from the search menu — the one path both the dialog's Accepted
        branch and the ghost's side-button quick-spawn (mouseReleaseEvent's
        candidate_payload branch) funnel through, so a node placed either
        way ends up wired identically."""
        win = self.nodeEditorWindow
        if not win:
            return None
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
        return new_node

    def _spawn_ghost_candidate(self, scene_pos: QPointF, payload: dict, source_socket, original_dest=None):
        """Places the node the ghost was showing via side-button cycling —
        same spawn+connect path as accepting it from the search menu
        (_spawn_node_payload), just without ever opening the dialog. Records
        the pick the same way a menu selection does (SearchMenuDialog.
        _on_item_activated), so this path feeds the same ranking data back
        instead of being invisible to it."""
        win = self.nodeEditorWindow
        if not win:
            return
        win._block_undo_push = True
        try:
            self._spawn_node_payload(scene_pos, payload, source_socket, original_dest)
        finally:
            win._block_undo_push = False
        win.push_undo_state()
        key = usage_key(payload)
        if key:
            record_search_usage(key, context_key_for_socket(source_socket))
