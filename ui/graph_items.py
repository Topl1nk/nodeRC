"""graph_items.py — The Scene's Visual Vocabulary

Sockets, Bézier wires, node bodies with embedded-widget tinting, the selection
overlay, and the node combo box. GroupFrameItem, InsetFillCheckBox, and the
rename machinery live in their own modules; this file re-exports them so
existing ``from ui.graph_items import …`` lines keep working.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from PyQt5.QtWidgets import (
    QGraphicsObject, QGraphicsItem, QGraphicsTextItem,
    QGraphicsProxyWidget, QLineEdit, QCheckBox,
    QSpinBox, QComboBox, QGraphicsPathItem, QWidget,
    QToolButton, QPushButton,
)
from PyQt5.QtGui import (
    QPen, QBrush, QColor, QPainterPath, QPainterPathStroker, QFont, QFontMetrics, QPainter, QPolygonF,
    QCursor, QRadialGradient, QLinearGradient,
)
from PyQt5.QtCore import QRectF, Qt, QPoint, QPointF, QSizeF, QTimer

from localization import t
from configuration import (
    NODE_HEADER_HEIGHT,
    NODE_EXEC_SOCKET_HALFSIZE, NODE_PARAM_SOCKET_RADIUS,
    NODE_HORIZONTAL_PAD,
    NODE_SHADOW_OFFSET_X, NODE_SHADOW_OFFSET_Y, NODE_SHADOW_BLUR, NODE_BOUNDS_MARGIN,
    SOCKET_HOVER_COLOR, NODE_SELECTED_COLOR, NODE_HOVER_COLOR, NODE_HOVER_BORDER_WIDTH,
    CONNECTION_SELECTED_COLOR, TEXT_COLOR,
    BEZIER_CTRL_FACTOR, BEZIER_CTRL_MIN,
    SOCKET_BORDER_WIDTH, SOCKET_RING_TRIM_WIDTH,
    SOCKET_EXEC_HOVER_GROW, SOCKET_PLUS_GLYPH_SCALE, SOCKET_PLUS_GLYPH_WIDTH, SOCKET_MINUS_GLYPH_COLOR,
    GHOST_NODE_GAP_CELLS, GHOST_NODE_WIDTH, GHOST_NODE_HEIGHT, GHOST_NODE_BORDER_WIDTH,
    GHOST_NODE_FILL_RGBA, GHOST_NODE_HEADER_RGBA, GHOST_NODE_BORDER_RGBA, GHOST_SOCKET_RGBA,
    GHOST_CONNECTION_RGBA, GHOST_CONNECTION_WIDTH,
    CANVAS_BACKGROUND_COLOR, SOCKET_UNCONNECTED_CENTER_COLOR,
    CONNECTION_EXEC_WIDTH, CONNECTION_EXEC_SELECTED_WIDTH,
    CONNECTION_PARAM_WIDTH, CONNECTION_PARAM_SELECTED_WIDTH, CONNECTION_HIT_WIDTH,
    CONNECTION_HOVER_HALO_WIDTH, CONNECTION_HOVER_TRIM_WIDTH,
    GRID_SIZE_SMALL, NODE_POPUP_Z, NODE_COMBO_POPUP_PROXY_Z,
    NODE_WIDTH_MIN_CELLS, NODE_WIDTH_MAX_CELLS,
    VECTOR_COLLAPSE_GLYPH, VECTOR_COLLAPSE_GLYPH_MIRRORED, VECTOR_EXPAND_GLYPH, VECTOR_TOGGLE_WIDTH,
    NODE_SELECTION_OVERLAY_RGBA, NODE_SELECTION_OVERLAY_Z, NODE_SOCKET_Z,
    CONNECTION_Z, GHOST_NODE_Z, GHOST_CANDIDATE_LIMIT,
    UI_FONT_FAMILY, NODE_LABEL_FONT_SIZE, NODE_RENAME_FONT_SIZE, SOCKET_LABEL_OUTLINE_WIDTH,
    TINT_BODY_DARKEN, TINT_TITLE_LUMINANCE_THRESHOLD,
    PARAM_NODE_HEADER_FROM_SOCKET, HOTKEY_HINTS,
)
from ui.theme import (
    NODE_BORDER_COLOR,
    relative_luminance, brightened_for_canvas,
    DEFAULT_WIDGET_QSS, widget_stylesheets, tinted_widget_palette,
    VECTOR_TOGGLE_QSS,
    apply_field_placeholder_palette,
)
from core.node_blueprint import NodeDef, SocketDef, html_title, command_node_def, _snap_dimension
from ui.color_picker import ColorPickerPopup
from ui.search_ranking import context_key_for_socket, collect_command_entries, ranked_candidates

# Re-exports from extracted modules — keep ``from ui.graph_items import …`` working.
from ui.title_item import (                                          # noqa: F401
    _EditableTitleItem, RenamableTitleMixin,
    editor_window_of, _merge_hsv_component, selected_of_type_including,
    run_context_menu,
)
from ui.group_frame import GroupFrameItem                            # noqa: F401
from ui.widgets import InsetFillCheckBox, suppress_default_selection_chrome  # noqa: F401


def snap_to_grid(value: float) -> float:
    """Round ``value`` to the nearest grid line — the exact formula
    MetaNode.itemChange already applies to every node position change
    (drag, paste, spawn), so every node placed anywhere always lands on the
    grid. SocketItem.ghost_spawn_pos reuses this same function so the ghost
    preview shows precisely where a spawned node will actually land, not an
    unsnapped approximation of it."""
    return round(value / GRID_SIZE_SMALL) * GRID_SIZE_SMALL


class SocketItem(QGraphicsObject):
    """
    Single socket visual.
    is_exec=True  → diamond (blue), type-safe exec-only connections
    is_exec=False → circle  (colored), param-only connections
    Position set once from row-index arithmetic; never recomputed.
    """

    def __init__(self, sock_def: SocketDef, row: int,
                 node_def: NodeDef, parent: "MetaNode"):
        super().__init__(parent)
        self.sock_def    = sock_def
        self.socket_type = sock_def.kind
        self.meta_node: MetaNode = parent
        self._radius  = NODE_EXEC_SOCKET_HALFSIZE if sock_def.is_exec else NODE_PARAM_SOCKET_RADIUS
        self._hovered = False
        # Maintained by NodeScene.addItem/removeItem — the single choke point
        # every Connection passes through regardless of which of the many
        # call sites created/removed it (ст. 14.3). A count, not a bool: a
        # param output can fan out to several wires (see
        # NodeScene.enforce_connection_rules — only exec output and any
        # input are capped at one).
        self._connection_count = 0
        # Lazily built on first hover (most sockets are never hovered in a
        # given session) — see _ensure_ghost/_SocketGhostPreview.
        self._ghost: Optional["_SocketGhostPreview"] = None

        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setAcceptHoverEvents(True)
        self.setZValue(NODE_SOCKET_Z)
        self.setPos(node_def.socket_x(sock_def.kind), node_def.socket_y(row, sock_def.is_exec))

    def _outer_radius(self) -> float:
        """Total visual extent — ring + both keylines — at normal zoom;
        bare radius at LOD-far (paint() skips the ring layers there)."""
        if getattr(self.meta_node, "_lod_far", False):
            return self._radius
        return self._effective_radius() + SOCKET_BORDER_WIDTH / 2.0 + SOCKET_RING_TRIM_WIDTH

    def boundingRect(self) -> QRectF:
        r = self._outer_radius() + 3
        return QRectF(-r, -r, 2 * r, 2 * r)

    def _effective_radius(self) -> float:
        """Base radius, grown by SOCKET_EXEC_HOVER_GROW while an exec socket
        is hovered — the enlarge-on-hover the task asked for. Param sockets
        never grow (only their fill color changes on hover, as before); LOD-
        far never grows (see paint(), which skips the ring entirely there)."""
        if self.sock_def.is_exec and self._hovered and not getattr(self.meta_node, "_lod_far", False):
            return self._radius + SOCKET_EXEC_HOVER_GROW
        return self._radius

    def _shape_at(self, r: float) -> QPainterPath:
        """Pure geometry — diamond (exec) / circle (param) / LOD-far square —
        at a caller-chosen radius ``r``. ``shape()`` and ``paint()``'s ring
        layers both build on this instead of repeating the exec/param/LOD
        branch three times over."""
        path = QPainterPath()
        if getattr(self.meta_node, "_lod_far", False):
            path.addRect(QRectF(-r, -r, 2 * r, 2 * r))
        elif self.sock_def.is_exec:
            path.addPolygon(QPolygonF([
                QPointF(0, -r), QPointF(r, 0),
                QPointF(0,  r), QPointF(-r, 0),
            ]))
            path.closeSubpath()
        else:
            path.addEllipse(QPointF(0, 0), r, r)
        return path

    def shape(self) -> QPainterPath:
        return self._shape_at(self._outer_radius())

    def is_connected(self) -> bool:
        return self._connection_count > 0

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        main_color = QColor(SOCKET_HOVER_COLOR if self._hovered else self.sock_def.color)

        if self.meta_node._lod_far:
            # Simplified far-LOD dot: flat fill/hollow, no ring layers — the
            # keyline trim is imperceptible at this zoom and not worth the
            # extra fills across every socket on screen (ст. 9.1).
            painter.setBrush(QBrush(main_color) if self.is_connected() else Qt.NoBrush)
            painter.drawPath(self._shape_at(self._radius))
            return

        # Ring built from outside in: a 1px keyline (canvas color, or the
        # node's own selection white while the owning node is selected),
        # the main colored ring (SOCKET_BORDER_WIDTH), then a second 1px
        # keyline (always canvas color, never selection-tinted) before the
        # true center. A connected socket's center fills solid to read as
        # "wired up"; an unconnected one gets a radial gradient from the
        # inner keyline's own color down to a darker center — a cheap paint
        # trick that *looks* like the canvas shows through, with no actual
        # masking of the node's body/header/border needed.
        r = self._effective_radius()
        main_half = SOCKET_BORDER_WIDTH / 2.0
        trim = SOCKET_RING_TRIM_WIDTH
        outer_edge = self._shape_at(r + main_half + trim)
        outer_main = self._shape_at(r + main_half)
        inner_main = self._shape_at(r - main_half)
        inner_edge = self._shape_at(r - main_half - trim)

        outer_trim_color = NODE_SELECTED_COLOR if self.meta_node._is_visually_selected() else CANVAS_BACKGROUND_COLOR
        painter.setBrush(QBrush(QColor(outer_trim_color)))
        painter.drawPath(outer_edge.subtracted(outer_main))

        painter.setBrush(QBrush(main_color))
        painter.drawPath(outer_main.subtracted(inner_main))

        painter.setBrush(QBrush(QColor(CANVAS_BACKGROUND_COLOR)))
        painter.drawPath(inner_main.subtracted(inner_edge))

        if self.is_connected():
            painter.setBrush(QBrush(main_color))
        else:
            center_r = r - main_half - trim
            gradient = QRadialGradient(QPointF(0, 0), max(center_r, 1.0))
            gradient.setColorAt(0.0, QColor(SOCKET_UNCONNECTED_CENTER_COLOR))
            gradient.setColorAt(1.0, QColor(CANVAS_BACKGROUND_COLOR))
            painter.setBrush(QBrush(gradient))
        painter.drawPath(inner_edge)

        # Exec-only hover affordance: a white "+" marking "click/drag here to
        # spawn a node" on an unconnected socket, or a "-" (its own darker
        # SOCKET_MINUS_GLYPH_COLOR, distinct from the "+"'s white) on an
        # already connected one — "click here to drop the wire" instead,
        # since there is nothing left to spawn into a socket that already
        # has its one allowed exec wire (see mousePressEvent's
        # click-to-disconnect). Sized off the already-grown radius so it
        # scales with the enlarge effect instead of looking fixed against it.
        if self.sock_def.is_exec and self._hovered:
            arm = r * SOCKET_PLUS_GLYPH_SCALE
            glyph_color = SOCKET_MINUS_GLYPH_COLOR if self.is_connected() else NODE_SELECTED_COLOR
            painter.setPen(QPen(QColor(glyph_color), SOCKET_PLUS_GLYPH_WIDTH, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(QPointF(-arm, 0), QPointF(arm, 0))
            if not self.is_connected():
                painter.drawLine(QPointF(0, -arm), QPointF(0, arm))

    def _ensure_ghost(self) -> "_SocketGhostPreview":
        if self._ghost is None:
            self._ghost = _SocketGhostPreview(self)
            # A top-level scene item (see _SocketGhostPreview's own
            # docstring for why), so — unlike a plain child — it must be
            # explicitly added to whatever scene this socket's own node is
            # already in.
            scene = self.scene()
            if scene is not None:
                scene.addItem(self._ghost)
        return self._ghost

    def _ranked_ghost_candidates(self) -> list:
        """Commands most likely wanted next off this socket, ranked the same
        way the search menu's own Suggested shortlist is (ui/search_ranking)
        — empty (no usage history yet, or a param socket) leaves the ghost
        showing its plain generic silhouette exactly as before; side-button
        cycling (mousePressEvent) simply has nothing to cycle through."""
        if not self.sock_def.is_exec:
            return []
        win = editor_window_of(self.meta_node)
        if win is None:
            return []
        entries = collect_command_entries(win.command_categories)
        return ranked_candidates(entries, self, context_key_for_socket(self), limit=GHOST_CANDIDATE_LIMIT)

    def _show_ghost(self) -> None:
        ghost = self._ensure_ghost()
        ghost.setVisible(True)
        ghost.set_candidates(self._ranked_ghost_candidates())
        # Even a plain hover (no drag yet) can already collide with a
        # neighboring node sitting right where ghost_spawn_pos() lands —
        # NodeScene._ghost_collision_socket is the same check
        # _update_drag_ghost runs mid-drag, just against the ghost's fixed
        # hover rect instead of a cursor-tracked one. A short click (no
        # real movement) never runs that mid-drag check at all, so this is
        # what lets such a click still connect directly into the collided
        # node instead of opening the node-creation menu — see
        # NodeScene.mouseReleaseEvent, which reads ghost._collision_target
        # as the one source of truth regardless of which of the two checks
        # actually set it.
        scene = self.scene()
        if scene is not None and hasattr(scene, "_ghost_collision_socket"):
            rect = QRectF(ghost.pos(), QSizeF(ghost._width, ghost._height))
            near = scene._ghost_collision_socket(self, rect)
            ghost.set_collision_target(near)
            # Nothing right next to the ghost's own fixed spot — scan
            # further out along the row for a node roughly level with the
            # source (NodeScene._ghost_ray_socket) before giving up to the
            # plain generic silhouette. A near collision always wins if it
            # already matched, so this only ever runs as a fallback.
            if near is None and hasattr(scene, "_ghost_ray_socket"):
                ghost.set_ray_target(scene._ghost_ray_socket(self))
        self._force_ghost_repaint()

    def _hide_ghost(self) -> None:
        if self._ghost is not None:
            self._ghost.setVisible(False)
            # Resets position/size and clears any cursor-tracked drag
            # position, collision adoption, and splice preview, so the next
            # plain hover starts fresh at the fixed ghost_spawn_pos formula
            # instead of resuming wherever a previous drag left it.
            self._ghost.reset_to_hover_position()
            self._ghost.set_splice_target(None)
            self._force_ghost_repaint()

    def _force_ghost_repaint(self) -> None:
        """``setVisible()`` alone only *schedules* a repaint through Qt's own
        dirty-region tracking — the same unreliable-under-SmartViewportUpdate
        mechanism documented in GraphicsView._update_hovered_node and fixed
        the same way in MetaNode._refresh_selection_visuals and
        GraphicsView.mouseMoveEvent's rubber-band handling: a translucent
        overlay toggling on/off left a ghost trail behind (its own two
        opposite edges' semi-transparent strokes overlapping) until an
        unrelated repaint happened to touch that exact pixel region. A
        precise mapped-rect update() (the first attempt at this) still left
        the trail — the ghost's own dashed border and diamond socket extend
        antialiasing past a tightly computed rect in a way a plain node's
        sceneBoundingRect math doesn't account for — so this forces a full
        viewport repaint instead, the same blanket fix already proven for
        the rubber band: cheap, since showing/hiding the ghost is a rare
        hover transition, not a hot per-frame path.
        """
        win = editor_window_of(self.meta_node)
        if win is None:
            return
        win.view.viewport().update()

    def ghost_spawn_pos(self) -> QPointF:
        """Scene position (top-left — matches add_command_node/add_param_node's
        ``pos`` convention) where a node spawned from this socket lands. The
        exact same anchor _SocketGhostPreview shows on hover, so what the
        ghost promises is what the user gets regardless of where a drag
        happens to actually end (NodeScene.mouseReleaseEvent uses this
        instead of the raw drop position for an exec source). Side is
        automatic — output sockets spawn to the right, input sockets to the
        left — never a per-drag decision.

        The gap is measured from the *source node's own edge* (not the
        socket — though for an exec socket, socket_x() already puts it
        exactly on that edge, so this is really the same X either way) at
        GHOST_NODE_GAP_CELLS grid cells; the X result is snapped to the
        grid via snap_to_grid — the same function MetaNode.itemChange
        applies to every node position change, so a node spawned here lands
        exactly where every other node (dragged, pasted, spawned from empty
        space) already always lands: on the grid.

        Y is the source node's own top-left Y, not an independent
        computation — an exec socket always sits at the same
        NODE_HEADER_HEIGHT/2 offset from its own node's top, regardless of
        that node's width, so matching the ghost's top to the source's top
        puts *both* sockets at exactly the same absolute Y: a perfectly
        straight connection line, dead right or dead left, never one cell
        off. It comes out grid-aligned for free too — the source node's own
        Y is already a grid multiple (itemChange), so there's nothing left
        to snap.
        """
        node = self.meta_node
        gap = GRID_SIZE_SMALL * GHOST_NODE_GAP_CELLS
        if self.sock_def.kind == "output":
            x = node.pos().x() + node.node_def.width + gap
        else:
            x = node.pos().x() - gap - GHOST_NODE_WIDTH
        return QPointF(snap_to_grid(x), node.pos().y())

    def _connections_touching(self) -> list:
        """Every Connection with this socket as either endpoint — at most a
        handful (an exec socket is capped at one; a param output can fan
        out). Used to repaint the wire's own hover gradient (Connection.
        paint) when this socket's hover state flips."""
        win = editor_window_of(self.meta_node)
        if win is None:
            return []
        return [c for c in win.connections if c.source is self or c.dest is self]

    def hoverEnterEvent(self, event):
        self.prepareGeometryChange()  # boundingRect/shape grow for exec sockets — see _effective_radius
        self._hovered = True
        self.update()
        # The node's own border gradient (MetaNode.paint) and this socket's
        # connected wire's own gradient (Connection.paint) both key off
        # SocketItem._hovered — for every socket kind, not just exec.
        self.meta_node.update()
        for conn in self._connections_touching():
            conn.update()
        if self.sock_def.is_exec:
            scene = self.scene()
            # A connected socket has nowhere to spawn a node — its one
            # allowed exec wire is already taken — so hovering it shows the
            # "-" disconnect affordance (paint()) but not the spawn-preview
            # ghost, unlike an unconnected socket's "+".
            if not self.is_connected() and not (scene is not None and getattr(scene, "_drag_active", False)):
                self._show_ghost()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.prepareGeometryChange()
        self._hovered = False
        self.update()
        self.meta_node.update()
        for conn in self._connections_touching():
            conn.update()
        if self.sock_def.is_exec:
            self._hide_ghost()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.scene().start_connection_drag(self, event.scenePos())
            event.accept()
        elif (event.button() in (Qt.XButton1, Qt.XButton2) and self.sock_def.is_exec
                and not self.is_connected() and self._ghost is not None and self._ghost.isVisible()):
            # Side mouse buttons (back/forward) page through the ghost's own
            # ranked candidate list while just hovering — no drag needed.
            # XButton2 (forward) advances, XButton1 (back) goes the other
            # way, matching every browser's own back/forward convention for
            # these buttons. A plain click or drag-release right after this
            # spawns whichever candidate the ghost is currently showing
            # (NodeScene.mouseReleaseEvent) instead of opening the search
            # menu — see _SocketGhostPreview.cycle_candidate/
            # selected_candidate_payload.
            self._ghost.cycle_candidate(1 if event.button() == Qt.XButton2 else -1)
            self._force_ghost_repaint()
            event.accept()
        else:
            event.ignore()

    def scene_center(self) -> QPointF:
        return self.mapToScene(QPointF(0, 0))


class _SocketGhostPreview(QGraphicsItem):
    """A realistic but colorless (monochrome white, at varying opacity) node
    silhouette + wire, shown while hovering an exec socket
    (SocketItem.hoverEnterEvent) — previews exactly where
    SocketItem.ghost_spawn_pos() will place a node spawned from here: a
    header band, a body, and a facing socket on whichever edge points back
    at the real source socket — everything a real node has *except* a title
    or field content, since this isn't previewing any specific node type.

    A top-level scene item (added via NodeScene.addItem in
    SocketItem._ensure_ghost), *not* a child of the socket/node — Qt only
    orders children within their own parent's local z-slot, so however high
    a mere child's own zValue was, it could never win against a *different*
    top-level node with a higher one (StartNode's NODE_START_Z, or another
    node mid-drag at NODE_DRAG_Z). Sitting at the scene's own top level with
    GHOST_NODE_Z lets it paint above literally every node, always. Its own
    position/size (self.pos(), self._width/_height) is plain scene
    geometry, set by reset_to_hover_position/set_drag_override/
    set_collision_target rather than computed lazily from the socket's own
    coordinate space. Never accepts mouse input of its own
    (setAcceptedMouseButtons(NoButton)) since it's purely an indicator, not
    an interactive element.
    """

    def __init__(self, socket: "SocketItem"):
        super().__init__()
        self._socket = socket
        self._width = GHOST_NODE_WIDTH
        self._height = GHOST_NODE_HEIGHT
        # Scene top-left — set by NodeScene._update_drag_ghost while an
        # active drag has pulled the ghost off its fixed hover spot to
        # follow the cursor to an arbitrary drop point; None means "use
        # ghost_spawn_pos()'s fixed formula", the plain-hover (no drag)
        # behavior — see reset_to_hover_position.
        self._drag_override: Optional[QPointF] = None
        # The far socket of a connection being dragged off a *connected*
        # source (NodeScene._drag_original_dest) — set only while the drag
        # is still within splice range (NodeScene._splice_still_attached),
        # so the ghost's own "other" socket (opposite the one facing the
        # real source) previews staying wired to it. None once the drag
        # moves far/sharp enough to count as a plain detach.
        self._splice_target: Optional["SocketItem"] = None
        # A real socket the ghost's own rect currently "collides" with
        # (NodeScene._ghost_collision_socket) — set, the ghost drops its own
        # generic placeholder silhouette/size entirely and instead adopts
        # that socket's own node's exact position and size, highlighting it
        # as "release here to connect directly into this existing node"
        # (see set_collision_target/paint).
        self._collision_target: Optional["SocketItem"] = None
        # A socket found further out along the same row (NodeScene.
        # _ghost_ray_socket, beyond the near _collision_target's own rect)
        # whose node sits roughly level with the source — mutually
        # exclusive with _collision_target (see set_ray_target/
        # set_collision_target, which each clear the other) and kept as its
        # own field, not folded into _collision_target, so
        # NodeScene.mouseReleaseEvent can tell "release here connects
        # straight in" (near collision, nothing moves) apart from "release
        # here connects *and* nudges that node's Y to line up" (ray match —
        # see _align_ray_target).
        self._ray_target: Optional["SocketItem"] = None
        # The ranked next-node candidates for this hover (SocketItem.
        # _ranked_ghost_candidates, set fresh on every _show_ghost) and
        # which one, if any, side-button cycling has landed on — -1 means
        # "none selected", the plain generic silhouette. See
        # set_candidates/cycle_candidate/selected_candidate_payload and the
        # title/counter paint() draws once a candidate is picked.
        self._candidates: list = []
        self._candidate_index: int = -1
        # The selected candidate's own real NodeDef (core.node_blueprint.
        # command_node_def — full param-socket layout), rebuilt on every
        # cycle_candidate so paint() can preview its actual sockets, not
        # just its name. None whenever no candidate is selected.
        self._node_def: Optional[NodeDef] = None
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setZValue(GHOST_NODE_Z)
        self.setVisible(False)
        self.setPos(socket.ghost_spawn_pos())

    def _direction(self) -> int:
        return 1 if self._socket.sock_def.kind == "output" else -1

    def set_candidates(self, candidates: list) -> None:
        """Refreshes the ranked candidate list for a fresh hover — always
        starts unselected (index -1) even if the list content is unchanged,
        so re-hovering the same socket never silently resumes a previous
        pick the user might not even remember making."""
        self._candidates = candidates
        self._candidate_index = -1
        self._apply_candidate_geometry()
        self.update()

    def cycle_candidate(self, direction: int) -> None:
        """Moves the selection by ``direction`` (+1/-1), wrapping around;
        a no-op when there's nothing to cycle (cold start, or a param
        socket, which never gets any candidates at all)."""
        if not self._candidates:
            return
        if self._candidate_index == -1:
            self._candidate_index = 0 if direction > 0 else len(self._candidates) - 1
        else:
            self._candidate_index = (self._candidate_index + direction) % len(self._candidates)
        self._apply_candidate_geometry()
        self.update()

    def selected_candidate_payload(self) -> Optional[dict]:
        """The command payload currently selected via side-button cycling,
        or None — the one source of truth NodeScene.mouseReleaseEvent reads
        to decide whether a click/drag-release here spawns that node
        directly instead of opening the search menu."""
        if 0 <= self._candidate_index < len(self._candidates):
            return self._candidates[self._candidate_index]["payload"]
        return None

    def _apply_candidate_geometry(self) -> None:
        """Resizes the ghost to match whatever cycle_candidate/set_candidates
        just landed on: the selected candidate's own real param-socket
        layout (core.node_blueprint.command_node_def — same row math a real
        CommandNode would use, so every socket paint() later draws is
        exactly where it'll really be) at a width fitted to its title
        instead of every real node's fixed default — clamped to the same
        NODE_WIDTH_MAX_CELLS ceiling a real node's own width is already
        clamped to (core.node_blueprint._snap_dimension), so a long name
        still elides rather than growing the ghost without bound. No
        selection (index -1, the plain generic silhouette) resets to the
        fixed 3-cell placeholder, same as before candidates existed at all.
        """
        self.prepareGeometryChange()
        payload = self.selected_candidate_payload()
        if payload is None:
            self._node_def = None
            self._width = GHOST_NODE_WIDTH
            self._height = GHOST_NODE_HEIGHT
            return
        node_def = command_node_def(payload)
        node_def.width = self._measure_candidate_width(payload.get("display", ""))
        self._node_def = node_def
        self._width = node_def.width
        self._height = node_def.body_height

    @staticmethod
    def _measure_candidate_width(title: str) -> int:
        font = QFont(UI_FONT_FAMILY, NODE_LABEL_FONT_SIZE)
        text_width = QFontMetrics(font).horizontalAdvance(title)
        # Room for the title's own left/right padding (matching a real
        # node's title margin) plus both edge sockets' diamonds, so the
        # text never crowds right up against them.
        measured = text_width + NODE_HORIZONTAL_PAD * 2 + NODE_EXEC_SOCKET_HALFSIZE * 4
        return _snap_dimension(measured, min_cells=NODE_WIDTH_MIN_CELLS, max_cells=NODE_WIDTH_MAX_CELLS)

    def _clear_candidate_selection(self) -> None:
        """Drops any side-button candidate pick — called whenever the ghost
        switches to a drag-driven mode (drag_override/collision/ray) or
        resets to plain hover, all of which set their own _width/_height
        directly. Without this, a candidate picked before a drag started
        would keep being reported by selected_candidate_payload() even
        though paint() stopped showing it the moment the drag took over —
        release would then silently spawn a node the ghost hadn't actually
        been previewing anymore."""
        self._candidate_index = -1
        self._node_def = None

    def reset_to_hover_position(self) -> None:
        """Fixed hover-only placement, at the ghost's own default size —
        SocketItem.ghost_spawn_pos()'s 3-cell default. What a plain hover
        (no drag) always shows, and what a click without real movement
        still spawns at (NodeScene.mouseReleaseEvent)."""
        self.prepareGeometryChange()
        self._width = GHOST_NODE_WIDTH
        self._height = GHOST_NODE_HEIGHT
        self._drag_override = None
        self._collision_target = None
        self._ray_target = None
        self._clear_candidate_selection()
        self.setPos(self._socket.ghost_spawn_pos())

    def set_drag_override(self, scene_top_left: Optional[QPointF]) -> None:
        """Cursor-tracked placement during an active drag, at the ghost's
        own default size (NodeScene._update_drag_ghost's non-collision
        case). ``None`` resets back to the fixed hover position."""
        if scene_top_left is None:
            self.reset_to_hover_position()
            return
        self.prepareGeometryChange()
        self._drag_override = scene_top_left
        self._collision_target = None
        self._ray_target = None
        self._clear_candidate_selection()
        self._width = GHOST_NODE_WIDTH
        self._height = GHOST_NODE_HEIGHT
        self.setPos(scene_top_left)

    def _adopt_target_node(self, target: "SocketItem") -> None:
        """Shared by set_collision_target/set_ray_target: the ghost drops
        its own generic placeholder and takes on ``target``'s own node's
        exact position/size verbatim."""
        node = target.meta_node
        self._width = node.node_def.width
        self._height = node.node_def.body_height
        self.setPos(node.pos())

    def set_collision_target(self, target: Optional["SocketItem"]) -> None:
        """``target`` not None: the ghost adopts that socket's own node's
        exact position and size verbatim, instead of its own generic
        placeholder — see paint(), which also drops the header/body fill in
        this mode (the real node underneath already shows that) for just a
        highlight outline plus a wire straight to ``target``'s own actual
        socket position. Mutually exclusive with a ray target (see
        _ray_target's own docstring) — a near collision always wins if both
        would otherwise apply."""
        self.prepareGeometryChange()
        self._collision_target = target
        self._ray_target = None
        self._clear_candidate_selection()
        if target is not None:
            self._adopt_target_node(target)

    def set_ray_target(self, target: Optional["SocketItem"]) -> None:
        """Same adoption/visual as set_collision_target, for a node found
        further out along the row (NodeScene._ghost_ray_socket) instead of
        directly under the ghost's own near rect — see _ray_target's own
        docstring for why this is a separate field rather than folded into
        _collision_target."""
        self.prepareGeometryChange()
        self._ray_target = target
        self._collision_target = None
        self._clear_candidate_selection()
        if target is not None:
            self._adopt_target_node(target)

    def _active_target(self) -> Optional["SocketItem"]:
        """Whichever of the two mutually-exclusive adopted targets is
        currently set — paint()/_facing_socket_pos treat them identically;
        only NodeScene.mouseReleaseEvent (align-on-connect) cares which."""
        return self._collision_target or self._ray_target

    def set_splice_target(self, other: Optional["SocketItem"]) -> None:
        self._splice_target = other

    def _local_rect(self) -> QRectF:
        return QRectF(0, 0, self._width, self._height)

    def _header_rect(self) -> QRectF:
        return QRectF(0, 0, self._width, NODE_HEADER_HEIGHT)

    def _facing_socket_pos(self) -> QPointF:
        """Where the ghost's own socket sits: on whichever edge faces the
        real source socket, at header mid-height — the same position
        convention a real exec socket uses (NodeDef.socket_y for is_exec).
        In collision mode this is instead the real target socket's own
        actual position (mapped into the ghost's local coordinates) —
        wherever that really is, not a synthetic mirror of it."""
        active_target = self._active_target()
        if active_target is not None:
            return self.mapFromScene(active_target.scene_center())
        x = 0.0 if self._direction() > 0 else self._width
        return QPointF(x, NODE_HEADER_HEIGHT / 2.0)

    def _other_socket_pos(self) -> QPointF:
        """The ghost's second socket, mirroring _facing_socket_pos on the
        opposite edge — every real command node has both an input (left)
        and an output (right) exec socket, so the ghost silhouette always
        shows both too, not just whichever one faces the real drag source.
        Also where a splice-preview wire to _splice_target lands. Not used
        in collision mode (paint() returns before reaching it there)."""
        x = self._width if self._direction() > 0 else 0.0
        return QPointF(x, NODE_HEADER_HEIGHT / 2.0)

    def boundingRect(self) -> QRectF:
        return self._local_rect().adjusted(-6, -6, 6, 6)

    def _draw_socket_diamond(self, painter: QPainter, pos: QPointF) -> None:
        """A diamond matching a real exec socket's own silhouette
        (NODE_EXEC_SOCKET_HALFSIZE) and, like any real unconnected socket
        (SocketItem.paint), filled with the same radial gradient from
        SOCKET_UNCONNECTED_CENTER_COLOR to CANVAS_BACKGROUND_COLOR instead
        of left hollow — so the preview reads as "a real node's socket
        connects here", not an arbitrary dot. Shared by both of the ghost's
        two sockets (_facing_socket_pos/_other_socket_pos)."""
        r = NODE_EXEC_SOCKET_HALFSIZE
        diamond = QPolygonF([
            pos + QPointF(0, -r), pos + QPointF(r, 0),
            pos + QPointF(0,  r), pos + QPointF(-r, 0),
        ])
        gradient = QRadialGradient(pos, max(r - GHOST_NODE_BORDER_WIDTH, 1.0))
        gradient.setColorAt(0.0, QColor(SOCKET_UNCONNECTED_CENTER_COLOR))
        gradient.setColorAt(1.0, QColor(CANVAS_BACKGROUND_COLOR))
        painter.setPen(QPen(QColor(*GHOST_SOCKET_RGBA), GHOST_NODE_BORDER_WIDTH))
        painter.setBrush(QBrush(gradient))
        painter.drawPolygon(diamond)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self._local_rect()
        sock_pos = self._facing_socket_pos()
        source_local = self.mapFromScene(self._socket.scene_center())

        if self._active_target() is not None:
            # Collision or ray match: the ghost has adopted the real target
            # node's own position/size verbatim (set_collision_target/
            # set_ray_target) — the real node underneath already shows its
            # own body/header, so this only adds a bright highlight outline
            # around it plus the wire straight to its own real socket,
            # instead of redrawing a second (redundant, muddying) copy of
            # its body/header fill. Both read identically here — only
            # NodeScene.mouseReleaseEvent (align-on-connect) treats a ray
            # match differently once it's actually confirmed.
            painter.setPen(QPen(QColor(*GHOST_CONNECTION_RGBA), GHOST_CONNECTION_WIDTH, Qt.SolidLine))
            painter.drawLine(source_local, sock_pos)
            painter.setPen(QPen(QColor(*GHOST_NODE_BORDER_RGBA), GHOST_NODE_BORDER_WIDTH * 2, Qt.SolidLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)
            return

        other_pos = self._other_socket_pos()

        # Preview wire: the real source socket's center -> the ghost's own
        # facing socket, not just to the rect's edge — so it visibly lands
        # on the socket silhouette below instead of stopping short of it.
        # Solid, like a real Connection. Only drawn in plain-hover display
        # (no _drag_override) — once an actual drag is tracking the cursor,
        # NodeScene's own dashed drag-preview line is the one and only line
        # (magnetized onto this same facing socket — see
        # NodeScene._drag_line_endpoint), so drawing this one too would just
        # duplicate it.
        if self._drag_override is None:
            painter.setPen(QPen(QColor(*GHOST_CONNECTION_RGBA), GHOST_CONNECTION_WIDTH, Qt.SolidLine))
            painter.drawLine(source_local, sock_pos)

        # Splice preview: while dragging off a *connected* socket and still
        # within splice range (NodeScene._splice_still_attached), a second
        # solid wire from the ghost's other socket to the far node's own
        # socket previews the node landing spliced in between both —
        # exactly what release will create. Gone once the drag detaches.
        if self._splice_target is not None:
            try:
                target_local = self.mapFromScene(self._splice_target.scene_center())
            except RuntimeError:
                target_local = None
            if target_local is not None:
                painter.setPen(QPen(QColor(*GHOST_CONNECTION_RGBA), GHOST_CONNECTION_WIDTH, Qt.SolidLine))
                painter.drawLine(other_pos, target_local)

        # Body then header, same layering (and same NODE_HEADER_HEIGHT) a
        # real node's own paint() uses — just monochrome white at low alpha
        # instead of the node's own header/body colors, and no title/fields.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(*GHOST_NODE_FILL_RGBA)))
        painter.drawRect(rect)
        painter.setBrush(QBrush(QColor(*GHOST_NODE_HEADER_RGBA)))
        painter.drawRect(self._header_rect())

        # A selected candidate (side-button cycling) gets a brighter, solid
        # border instead of the generic dashed one — "this is now a specific
        # choice, not just a placeholder shape" — plus its real title and a
        # position counter (see _draw_candidate_label).
        if self._candidate_index != -1:
            painter.setPen(QPen(QColor(NODE_SELECTED_COLOR), GHOST_NODE_BORDER_WIDTH * 1.5, Qt.SolidLine))
        else:
            painter.setPen(QPen(QColor(*GHOST_NODE_BORDER_RGBA), GHOST_NODE_BORDER_WIDTH, Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect)

        self._draw_socket_diamond(painter, sock_pos)
        self._draw_socket_diamond(painter, other_pos)
        self._draw_candidate_label(painter, rect)
        self._draw_candidate_param_sockets(painter)

    def _draw_candidate_label(self, painter: QPainter, rect: QRectF) -> None:
        """When side-button cycling has landed on a candidate, replaces the
        generic no-title silhouette with its real display name (elided to
        fit the header) plus a small "n/N" counter — the only way the ghost
        can tell the user *which* node a plain click/drag-release would
        spawn right now."""
        payload = self.selected_candidate_payload()
        if payload is None:
            return

        header = self._header_rect().adjusted(6, 0, -6, 0)
        font = QFont(UI_FONT_FAMILY, NODE_LABEL_FONT_SIZE)
        painter.setFont(font)
        elided = QFontMetrics(font).elidedText(payload.get("display", ""), Qt.ElideRight, int(header.width()))
        painter.setPen(QColor(NODE_SELECTED_COLOR))
        painter.drawText(header, int(Qt.AlignVCenter | Qt.AlignLeft), elided)

        counter_font = QFont(UI_FONT_FAMILY, max(NODE_LABEL_FONT_SIZE - 2, 6))
        painter.setFont(counter_font)
        painter.setPen(QColor(*GHOST_SOCKET_RGBA))
        counter_rect = rect.adjusted(0, rect.height() - 16, -4, -2)
        painter.drawText(counter_rect, int(Qt.AlignRight | Qt.AlignBottom),
                          f"{self._candidate_index + 1}/{len(self._candidates)}")

    def _draw_candidate_param_sockets(self, painter: QPainter) -> None:
        """Every param socket the selected candidate would actually have,
        drawn as a small dot in its own real socket color (the same
        SOCKET_COLOR_SCHEMA vocabulary painted on every socket/wire on the
        canvas) at its own real row position — self._node_def is built by
        command_node_def, the exact function a real CommandNode's own
        sockets come from, so this is a true preview of what wiring the
        candidate up would need, not a guess. Lets a hover-and-cycle plan
        the next few steps ahead before ever placing anything."""
        node_def = self._node_def
        if node_def is None:
            return
        font = QFont(UI_FONT_FAMILY, max(NODE_LABEL_FONT_SIZE - 1, 6))
        painter.setFont(font)
        metrics = QFontMetrics(font)
        label_gap = NODE_PARAM_SOCKET_RADIUS + 4
        for sock_def in node_def.sockets:
            if sock_def.is_exec:
                continue
            pos = QPointF(node_def.socket_x(sock_def.kind), node_def.socket_y(sock_def.row))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(sock_def.color))
            painter.drawEllipse(pos, NODE_PARAM_SOCKET_RADIUS, NODE_PARAM_SOCKET_RADIUS)

            label = sock_def.label or sock_def.name
            if not label:
                continue
            is_input = sock_def.kind == "input"
            text_x = pos.x() + label_gap if is_input else NODE_HORIZONTAL_PAD
            avail_width = max(self._width - text_x - NODE_HORIZONTAL_PAD, 10) if is_input \
                else max(pos.x() - label_gap - text_x, 10)
            elided = metrics.elidedText(label, Qt.ElideRight, int(avail_width))
            text_rect = QRectF(text_x, pos.y() - metrics.height() / 2.0, avail_width, metrics.height())
            painter.setPen(QColor(GHOST_SOCKET_RGBA[0], GHOST_SOCKET_RGBA[1], GHOST_SOCKET_RGBA[2], 200))
            align = Qt.AlignLeft if is_input else Qt.AlignRight
            painter.drawText(text_rect, int(align | Qt.AlignVCenter), elided)


class Connection(QGraphicsPathItem):
    """Cubic Bézier wire. Exec = thick; param = thin. Color matches source socket."""

    def __init__(self, source: SocketItem, dest: SocketItem):
        super().__init__()
        self.source  = source
        self.dest    = dest
        self.is_exec = source.sock_def.is_exec
        if self.is_exec:
            self._pen     = QPen(QColor(source.sock_def.color), CONNECTION_EXEC_WIDTH, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            self._pen_selected = QPen(QColor(CONNECTION_SELECTED_COLOR), CONNECTION_EXEC_SELECTED_WIDTH, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        else:
            self._pen     = QPen(QColor(source.sock_def.color), CONNECTION_PARAM_WIDTH, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            self._pen_selected = QPen(QColor(CONNECTION_SELECTED_COLOR), CONNECTION_PARAM_SELECTED_WIDTH, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        self.setZValue(CONNECTION_Z)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self._hovered = False
        self.refresh()

    def hoverEnterEvent(self, event):
        self._hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def shape(self) -> QPainterPath:
        # QGraphicsPathItem's default shape() strokes at the item's own
        # (thin, especially CONNECTION_PARAM_WIDTH's 1.8px) visual pen width
        # — nearly unclickable/unhoverable. Widening just the hit-test
        # stroke (never the painted one) is the standard "generous invisible
        # hitbox around a thin visible line" fix, without changing how the
        # wire actually looks.
        stroker = QPainterPathStroker()
        stroker.setWidth(CONNECTION_HIT_WIDTH)
        return stroker.createStroke(self.path())

    def refresh(self):
        try:
            if self.source.scene() is None or self.dest.scene() is None:
                return
            p1   = self.source.scene_center()
            p2   = self.dest.scene_center()
            ctrl = max(abs(p2.x() - p1.x()) * BEZIER_CTRL_FACTOR, BEZIER_CTRL_MIN)
            path = QPainterPath(p1)
            path.cubicTo(QPointF(p1.x() + ctrl, p1.y()),
                         QPointF(p2.x() - ctrl, p2.y()), p2)
            self.setPath(path)
        except RuntimeError:
            # The C++ socket objects were deleted mid-refresh (node removed during a
            # drag or undo); there is nothing left to redraw, so drop this frame.
            pass

    def boundingRect(self) -> QRectF:
        return super().boundingRect().adjusted(
            -NODE_BOUNDS_MARGIN, -NODE_BOUNDS_MARGIN,
            NODE_BOUNDS_MARGIN, NODE_BOUNDS_MARGIN)

    def paint(self, painter, option, widget=None):
        suppress_default_selection_chrome(option)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = self._pen_selected if self.isSelected() else self._pen
        # Hovering the wire's own body directly — a white halo drawn UNDER
        # the wire's own normal-colored pen, never replacing it: the wire's
        # color is meaningful (source socket type), unlike a node body, so
        # unlike MetaNode.paint's plain _hovered border this must not
        # override it, just outline it. Selection still wins over this.
        # The halo is sandwiched between two 1px canvas-background-colored
        # trim rings — one outside it, one between it and the wire's own
        # color — the same outer-trim/band/inner-trim convention
        # SocketItem.paint uses for its own ring, so the white band reads
        # as a crisp outline on BOTH edges instead of just blurring into
        # whatever's behind it on the outside while bleeding straight into
        # the wire's color on the inside. Four passes, widest first: outer
        # trim, halo, inner trim, then (below) the wire's own normal pen.
        if not self.isSelected() and self._hovered:
            halo_width = pen.widthF() + CONNECTION_HOVER_HALO_WIDTH * 2

            outer_trim_pen = QPen(pen)
            outer_trim_pen.setColor(QColor(CANVAS_BACKGROUND_COLOR))
            outer_trim_pen.setWidthF(halo_width + CONNECTION_HOVER_TRIM_WIDTH * 2)
            painter.setPen(outer_trim_pen)
            painter.drawPath(self.path())

            halo_pen = QPen(pen)
            halo_pen.setColor(QColor(NODE_HOVER_COLOR))
            halo_pen.setWidthF(halo_width)
            painter.setPen(halo_pen)
            painter.drawPath(self.path())

            inner_trim_pen = QPen(pen)
            inner_trim_pen.setColor(QColor(CANVAS_BACKGROUND_COLOR))
            inner_trim_pen.setWidthF(pen.widthF() + CONNECTION_HOVER_TRIM_WIDTH * 2)
            painter.setPen(inner_trim_pen)
            painter.drawPath(self.path())
        # Whichever endpoint currently has its socket hovered (SocketItem.
        # _hovered) lights the wire up white on that end, fading to fully
        # transparent at the far end — the wire's own counterpart to
        # MetaNode.paint's border gradient, so hovering a connected socket
        # highlights the exact wire it owns instead of just the socket dot.
        # Selection's own solid highlight color takes priority over this;
        # a direct wire hover (above) already outlines the whole thing, so
        # this softer directional glow only adds anything when neither
        # applies.
        if not self.isSelected() and not self._hovered:
            hovered_end = self.source if self.source._hovered else (
                self.dest if self.dest._hovered else None)
            if hovered_end is not None:
                pen = QPen(pen)
                p1 = self.source.scene_center()
                p2 = self.dest.scene_center()
                gradient = QLinearGradient(p1, p2)
                white = QColor(NODE_SELECTED_COLOR)
                transparent = QColor(NODE_SELECTED_COLOR)
                transparent.setAlpha(0)
                if hovered_end is self.source:
                    gradient.setColorAt(0.0, white)
                    gradient.setColorAt(1.0, transparent)
                else:
                    gradient.setColorAt(0.0, transparent)
                    gradient.setColorAt(1.0, white)
                pen.setBrush(QBrush(gradient))
        self.setPen(pen)
        super().paint(painter, option, widget)


class _SelectionOverlay(QGraphicsItem):
    """One translucent wash above the whole node — the entire selected look."""

    def __init__(self, node: "MetaNode"):
        super().__init__(node)
        self._node = node
        self.setZValue(NODE_SELECTION_OVERLAY_Z)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setVisible(False)

    def boundingRect(self) -> QRectF:
        d = self._node.node_def
        return QRectF(0, 0, d.width, d.body_height)

    def paint(self, painter: QPainter, option, widget=None):
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(*NODE_SELECTION_OVERLAY_RGBA)))
        painter.drawRect(self.boundingRect())


# Every embedded widget type the far-LOD primitive bars know how to stand
# in for individually — see MetaNode._draw_lod_widget_bar. A compound row
# (PathParamNode's [field, browse button], EnumParamNode's [new-item field,
# "+", "-"], Int's [spinbox, stepper]) is never itself in this tuple, so it
# gets walked for these leaves instead of being drawn as one undifferentiated
# blob — otherwise an empty field sharing a wrapper with a button (exactly
# EnumParamNode's new-item row) visually swallowed the button along with it.
_LOD_LEAF_WIDGET_TYPES = (QComboBox, QLineEdit, QCheckBox, QSpinBox, QToolButton, QPushButton)


def _lod_leaf_widgets(top: QWidget) -> list:
    """``top`` itself if it's already one of _LOD_LEAF_WIDGET_TYPES,
    otherwise every such descendant inside it (a compound row/wrapper)."""
    if isinstance(top, _LOD_LEAF_WIDGET_TYPES):
        return [top]
    return list(top.findChildren(_LOD_LEAF_WIDGET_TYPES))


def _lod_widget_text(widget: QWidget) -> Optional[str]:
    """The text a single leaf widget currently shows, for the far-LOD
    primitive bar — ``None`` means "no single length-meaningful text" (a
    plain button/icon: draw a bar spanning its whole slot), as opposed to
    ``""`` which means "there's a text field here, it's just empty right
    now" (also a full-slot bar — see MetaNode._draw_lod_widget_bar — but a
    distinct reason from "this is a button").
    """
    if isinstance(widget, QComboBox):
        text = widget.currentText()
        if not text and widget.lineEdit():
            text = widget.lineEdit().placeholderText()
        return text
    if isinstance(widget, QLineEdit):
        return widget.text() or widget.placeholderText()
    if isinstance(widget, QCheckBox):
        return widget.text()
    if isinstance(widget, QSpinBox):
        return str(widget.value())
    return None  # QToolButton / QPushButton


class _OutlinedTextItem(QGraphicsTextItem):
    """A QGraphicsTextItem whose glyphs also get a thin outline stroke
    (SOCKET_LABEL_OUTLINE_WIDTH / CANVAS_BACKGROUND_COLOR) — used for socket
    name labels so they stay legible over whatever's directly behind them:
    the canvas grid through an unconnected socket's masked-out area, a
    bright embedded widget, an overlapping wire. Qt's own QGraphicsTextItem
    can only fill its glyphs, never stroke them, so this repaints the same
    text as an outlined QPainterPath underneath Qt's normal (fill-only)
    rich-text paint pass.

    Subclasses QGraphicsTextItem itself (not a from-scratch QGraphicsItem)
    so boundingRect()/defaultTextColor() and every existing label-layout call
    site (MetaNode._generate's label_width/label_height math) keep working
    unmodified, and so MetaNode._paint_lod_primitives's
    ``isinstance(child, QGraphicsTextItem)`` check for the far-LOD stand-in
    bar still finds these labels — a from-scratch item would silently drop
    out of both.

    Document margin is forced to 0 so the manually-drawn outline path
    (drawn at the glyph's own origin, no margin) lines up exactly with
    Qt's own fill pass underneath it — QTextDocument's default 4px margin
    would otherwise offset the two from each other.
    """

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.document().setDocumentMargin(0)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        text = self.toPlainText()
        if text:
            path = QPainterPath()
            metrics = QFontMetrics(self.font())
            path.addText(0, metrics.ascent(), self.font(), text)
            painter.save()
            painter.setPen(QPen(QColor(CANVAS_BACKGROUND_COLOR), SOCKET_LABEL_OUTLINE_WIDTH))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)
            painter.restore()
        super().paint(painter, option, widget)


class MetaNode(RenamableTitleMixin, QGraphicsObject):
    """
    Why: BoundingRect includes shadow area to prevent trail artifacts on move.
    """

    is_protected = False  # the single source for "bulk delete must spare this node"
    supports_plain_rename = False  # param nodes enable the generic Rename entry
    always_on_top = False  # StartNode: never joins the drag-brings-to-front stacking order

    # Hands out a stable identity per node, independent of its position in
    # scene.items() (which serialize_graph's "id" field is, and which shifts
    # under Z-order changes like drag-to-front). undo/redo (see
    # graph_serialization.try_apply_state_diff) matches nodes between two
    # history snapshots by this uid instead, so it can tell "this specific
    # node moved" from "a node was added/removed" and patch the live object
    # in place rather than rebuilding the whole graph for every step.
    _next_uid = 1

    @classmethod
    def _observe_uid(cls, uid: int):
        """Fast-forward the allocator past a uid loaded from disk, so a
        freshly created node can never collide with one restored from a
        save/autosave file written by an earlier run."""
        if uid >= cls._next_uid:
            cls._next_uid = uid + 1

    def __init__(self, node_def: NodeDef):
        super().__init__()
        self.uid = MetaNode._next_uid
        MetaNode._next_uid += 1
        self.node_def = node_def
        self.sockets: Dict[str, SocketItem] = {}
        self._vector_buttons: Dict[str, tuple] = {}
        self._color_override: Optional[str] = None  # user-picked header tint, if any
        # When True the override only repaints the header + its border; the body
        # and embedded widgets keep their default scheme. Lets the user mark a
        # node visually without re-skinning every inner control.
        self._color_only_header: bool = False
        # Marks this node's value as an exposed input of the project (see the
        # left Project Inputs panel) — only meaningful on ParamNode subclasses.
        self._is_project_input: bool = False
        # The only-header scope set_project_input(True) overrode, restored
        # when the node is unmarked — see set_project_input below.
        self._pre_project_input_only_header: bool = False
        # True until the user actually picks a colour (or explicitly resets),
        # so a node-shape rebuild (Float2/3 split/merge, command X/Y/Z
        # expand/collapse — see _swap_node) knows whether to carry the
        # current colour over or let the replacement compute its own
        # type-based default.
        self._color_is_default: bool = True
        # The Z this node returns to once no combo popup is open — 0 by default,
        # bumped by NodeScene after a drag (bring-to-front), fixed high for
        # StartNode. _refresh_selection_visuals is the only place that applies
        # it, so a popup opening/closing can never clobber it.
        self._resting_z: float = 0.0
        # Set by GraphicsView's mouse-move tracking (view.py), the single place
        # hover is computed — not by this item's own hoverEnterEvent, which
        # never fires while the cursor is over an embedded proxy widget
        # (QLineEdit/QComboBox/etc. quietly disable a QGraphicsProxyWidget's
        # own hover delivery unless the embedded widget itself requests hover).
        self._hovered = False
        # Level-of-detail: True once this node has been told the view is
        # zoomed out past NODE_LOD_DETAIL_SCALE (see _set_lod_far) — text and
        # embedded field widgets are hidden and paint() draws one flat color
        # bar in their place instead.
        self._lod_far = False
        self.setFlags(
            QGraphicsItem.ItemIsMovable |
            QGraphicsItem.ItemIsSelectable |
            QGraphicsItem.ItemSendsScenePositionChanges |
            QGraphicsItem.ItemIsFocusable,
        )
        self._generate()
        # When the config flag is set, parameter nodes are born with their
        # socket colour painted on the header via the palette's only-header
        # mechanism — body and widgets stay on the default scheme.
        self._apply_initial_socket_color()
        QTimer.singleShot(0, self._update_children_colors)

    def _generate(self):
        d = self.node_def
        self._vector_buttons.clear()

        self._selection_overlay = _SelectionOverlay(self)

        self.title_item = _EditableTitleItem(self)
        self.title_item.setDefaultTextColor(QColor("white"))
        self._set_title_text(d.plain_title)

        def _make_vector_toggle(socket_def, base_name: str, *, mirrored: bool = False) -> QToolButton:
            toggle = QToolButton()
            if socket_def.is_collapsed_vector:
                glyph = VECTOR_COLLAPSE_GLYPH_MIRRORED if mirrored else VECTOR_COLLAPSE_GLYPH
            else:
                glyph = VECTOR_EXPAND_GLYPH
            toggle.setText(glyph)
            # Marks this button for _apply_widget_qss so it can tell a
            # vector toggle apart from a regular QToolButton without
            # matching on its glyph text — text-based matching is what
            # broke when an unrelated button (a numeric field's ▼
            # stepper) happened to reuse VECTOR_EXPAND_GLYPH's own
            # character and got recolored as a "neutral chevron"
            # (transparent, borderless) instead of a real button.
            toggle.setProperty("vectorToggle", True)
            toggle.setStyleSheet(VECTOR_TOGGLE_QSS)
            toggle.setCursor(Qt.PointingHandCursor)
            toggle.clicked.connect(
                lambda _, base=base_name: self.toggle_vector_expansion(base)
            )
            return toggle

        for socket_def in d.sockets:
            socket = SocketItem(socket_def, socket_def.row, d, self)
            self.sockets[socket_def.name] = socket

            text_to_show = socket_def.name if socket_def.label is None else socket_def.label
            if text_to_show:
                label = _OutlinedTextItem(text_to_show, self)
                label.setFont(QFont(UI_FONT_FAMILY, NODE_LABEL_FONT_SIZE))
                label_height = label.boundingRect().height()
                label_width  = label.boundingRect().width()
                label_y      = d.socket_y(socket_def.row, socket_def.is_exec) - label_height / 2.0
                has_toggle   = socket_def.is_collapsed_vector or socket_def.is_expanded_vector_start

                if socket_def.kind == "input":
                    label_x = NODE_EXEC_SOCKET_HALFSIZE * 2 + 5
                    label.setPos(label_x, label_y)

                    if has_toggle:
                        toggle = _make_vector_toggle(socket_def, socket_def.vector_base)
                        proxy = self._make_proxy(toggle)
                        proxy.setPos(label_x + label_width + 2, label_y)
                        self._vector_buttons[socket_def.vector_base] = (toggle, proxy)
                else:
                    label_x = d.width - NODE_EXEC_SOCKET_HALFSIZE * 2 - 5 - label_width
                    label.setPos(label_x, label_y)

                    if has_toggle:
                        # Mirrored placement: the arrow sits to the left of an
                        # output's label instead of to the right of an input's,
                        # so it still reads as "next to the name it toggles".
                        toggle = _make_vector_toggle(socket_def, socket_def.vector_base, mirrored=True)
                        toggle.setFixedWidth(VECTOR_TOGGLE_WIDTH)
                        proxy = self._make_proxy(toggle)
                        proxy.setPos(label_x - VECTOR_TOGGLE_WIDTH - 2, label_y)
                        self._vector_buttons[socket_def.vector_base] = (toggle, proxy)

                label.setDefaultTextColor(QColor(socket_def.color))
        self.update_vector_buttons_visibility()

    def _center_title(self):
        text_h = QGraphicsTextItem.boundingRect(self.title_item).height()
        self.title_item.setPos(
            NODE_HORIZONTAL_PAD,
            (NODE_HEADER_HEIGHT - text_h) / 2.0,
        )

    def _set_title_text(self, text: str):
        """Set the header title, eliding it (with the full text as a tooltip)
        if it would otherwise overflow the node's fixed width.

        Why: the title is plain QGraphicsTextItem HTML with no wrap/clip of
        its own, so an unbounded long one paints straight through the node's
        right edge and over whatever sits next to it — this is the single
        place every title (initial build and rename) goes through, so no
        node type can reintroduce the overflow by skipping it.
        """
        max_width = self.node_def.width - NODE_HORIZONTAL_PAD * 2
        font = QFont(UI_FONT_FAMILY, NODE_RENAME_FONT_SIZE, QFont.Bold)
        elided = QFontMetrics(font).elidedText(text, Qt.ElideRight, max_width)
        self.title_item.setHtml(html_title(elided))
        self.setToolTip(text if elided != text else "")
        self._center_title()

    # ── In-place rename ───────────────────────────────────────────────────────

    def _commit_title(self, name: str):
        self._apply_title(name)
        self._on_renamed(name)

    def _revert_title(self, backup: str):
        self._apply_title(backup)

    def _apply_title(self, text: str):
        self._set_title_text(text)
        # Restore the tint-aware title colour _begin_rename forced to the edit
        # colour. The picked colour family — or default text colour when there is
        # no override — decides whether the title reads dark or light.
        self.title_item.setDefaultTextColor(QColor(self._title_text_color()))

    def _title_text_color(self) -> str:
        if self._color_override:
            painted = QColor(self._color_override)
            title_dark = relative_luminance(painted) > TINT_TITLE_LUMINANCE_THRESHOLD
            return "#000000" if title_dark else "#FFFFFF"
        return TEXT_COLOR

    def _rename_text_color(self) -> str:
        # While editing, the title should read exactly like it does at rest
        # — whatever the palette already picked for this node's header —
        # not a plain white that can vanish against a bright custom color.
        return self._title_text_color()

    def _on_renamed(self, name: str):
        """Override to react to a committed rename (e.g. update creation_data)."""

    def title_edit_background(self) -> str:
        """Backdrop the title paints behind itself while being edited."""
        return self._color_override or self.node_def.header_color

    # ── Node color ─────────────────────────────────────────────────────────────

    def _apply_initial_socket_color(self):
        """Auto-apply socket colour as a header-only override for param nodes.

        When PARAM_NODE_HEADER_FROM_SOCKET is True in the config, every
        non-exec node is born with its output socket colour painted on the
        header strip via the palette's only-header mechanism.  Body and
        embedded widgets stay on the default scheme — the same behaviour as
        if the user had opened the palette, picked the socket colour, and
        ticked "only header".
        """
        color, only_header = self.default_color_override()
        if color is not None:
            self._color_override = color
            self._color_only_header = only_header

    def primary_output_socket_def(self) -> Optional[SocketDef]:
        """The first non-exec output socket, or ``None`` for exec/command nodes.

        The one param socket a scalar param node exposes — its color and
        label are what the header tint (default_color_override below) and
        the Project Inputs panel's row both read, so both stay in sync with
        whatever the node's own definition says without duplicating the scan.
        """
        for sd in self.node_def.sockets:
            if sd.kind == "output" and not sd.is_exec:
                return sd
        return None

    def default_color_override(self) -> Tuple[Optional[str], bool]:
        """The (color, only_header) pair this node is born with — reset target.

        Mirrors ``_apply_initial_socket_color``: the first non-exec output
        socket's colour, painted header-only, for param nodes; ``(None,
        False)`` for exec/command nodes so they fall back to the plain
        ``DEFAULT_HEADER_COLOR`` scheme.
        """
        if not PARAM_NODE_HEADER_FROM_SOCKET:
            return None, False
        sd = self.primary_output_socket_def()
        return (sd.color, True) if sd else (None, False)

    def reset_color(self, *, record_undo: bool = True):
        color, only_header = self.default_color_override()
        self.set_color(color, only_header=only_header, record_undo=record_undo, is_default=True)

    def color_override(self) -> Optional[str]:
        return self._color_override

    def color_only_header(self) -> bool:
        return self._color_only_header

    def is_project_input(self) -> bool:
        return self._is_project_input

    def set_project_input(self, flag: bool, *, record_undo: bool = True):
        flag = bool(flag)
        if flag == self._is_project_input:
            return
        if flag:
            # Remember the scope being overridden so unmarking below can put
            # it back — marking must not permanently erase a user's earlier
            # "only header" choice.
            self._pre_project_input_only_header = self._color_only_header
            self._is_project_input = True
            if self._color_only_header:
                self.set_color(self._color_override, only_header=False,
                                record_undo=False, is_default=self._color_is_default)
        else:
            self._is_project_input = False
            if self._pre_project_input_only_header:
                self.set_color(self._color_override, only_header=True,
                                record_undo=False, is_default=self._color_is_default)
        self.update()
        win = editor_window_of(self)
        if record_undo and win:
            win.push_undo_state()

    def set_color(self, color_hex: Optional[str], *, only_header: bool = False,
                  record_undo: bool = True, is_default: bool = False):
        self._color_override = color_hex
        # A project-input node must always read as a full-tinted body on the
        # canvas, never header-only — that's its visual distinction from an
        # ordinary param node — so the scope is clamped here, the one place
        # every caller (picker, reset, restore, multi-select) funnels through.
        self._color_only_header = (
            bool(only_header) and color_hex is not None and not self._is_project_input
        )
        self._color_is_default = is_default
        self.update()
        self._update_children_colors()
        win = editor_window_of(self)
        if record_undo and win:
            win.push_undo_state()

    def _update_children_colors(self):
        """Push the node's current colour (default or override) into every embedded widget.

        The default and tinted stylesheet sets come out of the same builder in
        theme.py, parameterized by palette — the two schemes cannot drift.
        """
        # only-header scope keeps the body and embedded widgets on the default
        # scheme; the override touches just the painted header and its border.
        if not self._color_override or self._color_only_header:
            qss = DEFAULT_WIDGET_QSS
        else:
            qss = widget_stylesheets(tinted_widget_palette(QColor(self._color_override)))

        self.title_item.setDefaultTextColor(QColor(self._title_text_color()))

        for child in self.childItems():
            if isinstance(child, QGraphicsProxyWidget) and child.widget():
                self._apply_widget_qss(child.widget(), qss)

    # Inline separators are zero-purpose strips with maximumHeight <= this.
    _SEPARATOR_MAX_HEIGHT = 2

    @classmethod
    def _apply_widget_qss(cls, widget, qss: Dict[str, str]):
        """Walk the widget tree and apply the matching tinted/default stylesheet.

        Qt cascades a QComboBox/QSpinBox stylesheet onto their internal editors,
        so we deliberately do not recurse into them — re-styling their inner
        QLineEdit would draw a second border inside the outer control.
        """
        if isinstance(widget, QComboBox):
            widget.setStyleSheet(qss["combo"])
            apply_field_placeholder_palette(widget)
            return
        if isinstance(widget, QSpinBox):
            widget.setStyleSheet(qss["spin"])
            apply_field_placeholder_palette(widget)
            return
        if isinstance(widget, QLineEdit):
            widget.setStyleSheet(qss["field"])
            apply_field_placeholder_palette(widget)
        elif isinstance(widget, QCheckBox):
            widget.setStyleSheet(qss["check"])
            if isinstance(widget, InsetFillCheckBox):
                widget.update_indicator_colors(qss["check_border"], qss["check_bg"])
        elif isinstance(widget, QToolButton):
            if widget.property("vectorToggle"):
                widget.setStyleSheet(VECTOR_TOGGLE_QSS)
            else:
                widget.setStyleSheet(qss["tool"])
        elif isinstance(widget, QPushButton):
            widget.setStyleSheet(qss["push"])
        elif (type(widget) is QWidget
              and widget.maximumHeight() <= cls._SEPARATOR_MAX_HEIGHT):
            widget.setStyleSheet(f"background-color:{qss['separator']};")
        for child in widget.children():
            if isinstance(child, QWidget):
                cls._apply_widget_qss(child, qss)

    def _pick_color(self):
        win = editor_window_of(self)
        if not win:
            return

        selected_nodes = selected_of_type_including(self, MetaNode)

        # Suppressed for the popup's lifetime so the wash doesn't obscure the
        # color preview; restored via _refresh_selection_visuals() on close so
        # it lands on whatever the real selection/linked state is by then,
        # not a stale isSelected() snapshot.
        for node in selected_nodes:
            node._selection_overlay.setVisible(False)

        def on_close():
            for node in selected_nodes:
                node._refresh_selection_visuals()
            win.push_undo_state()

        def apply_color_to_all(c, only_header, changed_component=None):
            for node in selected_nodes:
                current = node._color_override or node.node_def.header_color
                merged = _merge_hsv_component(current, c, changed_component)
                node.set_color(merged, only_header=only_header, record_undo=False)

        def apply_scope_to_all(only_header):
            # Only-header toggle during multi-node editing: preserve each node's
            # own color, change only the scope flag so no node is re-colored.
            for node in selected_nodes:
                node.set_color(node._color_override, only_header=only_header,
                               record_undo=False, is_default=node._color_is_default)

        def reset_all():
            for node in selected_nodes:
                node.reset_color(record_undo=False)
            color, only_header = self.default_color_override()
            return color or self.node_def.header_color, only_header

        initial = self._color_override or self.node_def.header_color
        popup = ColorPickerPopup(
            on_color_selected=apply_color_to_all,
            on_only_header_changed=apply_scope_to_all if len(selected_nodes) > 1 else None,
            on_reset=reset_all,
            initial_color=initial,
            initial_only_header=self._color_only_header,
            # A project-input node is pinned to a full-tinted body (set_color
            # enforces this regardless), so the toggle is greyed out instead
            # of showing a checkbox that would silently do nothing.
            only_header_locked=any(n.is_project_input() for n in selected_nodes),
            on_close=on_close,
            parent=win
        )
        popup.move(QCursor.pos())
        popup.show()

    def boundingRect(self) -> QRectF:
        d = self.node_def
        m = NODE_BOUNDS_MARGIN
        return QRectF(
            -m, -m,
            d.width       + NODE_SHADOW_OFFSET_X + NODE_SHADOW_BLUR + 2 * m,
            d.body_height + NODE_SHADOW_OFFSET_Y + NODE_SHADOW_BLUR + 2 * m,
        )


    def paint(self, painter: QPainter, option, widget=None):
        suppress_default_selection_chrome(option)
        painter.setRenderHint(QPainter.Antialiasing)
        d = self.node_def

        win = editor_window_of(self)
        is_linked = win is not None and self in getattr(win, '_linked_group', [])
        visually_selected = self.isSelected() or is_linked

        # A picked color tints the header; in full-scope mode the body takes
        # the same tint family too, in only-header mode the body fill and
        # embedded widgets (MetaNode._update_children_colors) stay on the
        # default scheme and only the header gets the pick — but the node's
        # one overall border always follows the header's own tint either
        # way, never the plain default NODE_BORDER_COLOR, so a picked color
        # (full- or header-only-scoped) always reads as "this node's own
        # color" from its silhouette alone, not just its header band.
        only_header = bool(self._color_override) and self._color_only_header
        body_border_brush = None
        if self._color_override:
            header_color = QColor(self._color_override)
            header_edge = brightened_for_canvas(header_color)
            if only_header:
                body_color = QColor(d.body_color)
                body_color.setAlpha(header_color.alpha())
                header_edge.setAlpha(header_color.alpha())
                
                gradient = QLinearGradient(0, 0, 0, d.body_height)
                gradient.setColorAt(0.0, header_edge)
                gradient.setColorAt(1.0, QColor(NODE_BORDER_COLOR))
                body_border_brush = QBrush(gradient)
            else:
                body_color = header_color.darker(TINT_BODY_DARKEN)
                body_border_brush = QBrush(header_edge)
        else:
            header_color = QColor(d.header_color)
            header_edge = QColor(NODE_BORDER_COLOR)
            body_color = QColor(d.body_color)
            
            if self._color_only_header:
                gradient = QLinearGradient(0, 0, 0, d.body_height)
                gradient.setColorAt(0.0, header_color)
                gradient.setColorAt(1.0, QColor(NODE_BORDER_COLOR))
                body_border_brush = QBrush(gradient)
            else:
                body_border_brush = QBrush(QColor(NODE_BORDER_COLOR))

        hovered_socket = next((s for s in self.sockets.values() if s._hovered), None)

        if visually_selected:
            border_pen = QPen(QColor(NODE_SELECTED_COLOR), 2.0)
        elif hovered_socket is not None:
            # A hovered socket's own edge (input=left/x=0, output=right/
            # x=width — NodeDef.socket_x puts every socket kind on that same
            # edge) lights up the whole border white, fading to fully
            # transparent at the opposite edge — a directional cue pointing
            # at exactly which socket is under the cursor, distinct from the
            # flat NODE_HOVER_COLOR outline a plain node-body hover gets.
            gradient = QLinearGradient(0, 0, d.width, 0)
            white = QColor(NODE_SELECTED_COLOR)
            transparent = QColor(NODE_SELECTED_COLOR)
            transparent.setAlpha(0)
            near, far = (0.0, 1.0) if hovered_socket.sock_def.kind == "input" else (1.0, 0.0)
            gradient.setColorAt(near, white)
            gradient.setColorAt(far, transparent)
            border_pen = QPen(QBrush(gradient), NODE_HOVER_BORDER_WIDTH)
        elif self._hovered:
            # This one rect spans the whole node (header included — the header
            # fill just paints over its top portion), so a single hover pen
            # here outlines the entire node whether the cursor is over the
            # header or the body.
            border_pen = QPen(QColor(NODE_HOVER_COLOR), NODE_HOVER_BORDER_WIDTH)
        else:
            border_pen = QPen(body_border_brush, 1.0)

        body_rect   = QRectF(0, 0, d.width, d.body_height)
        header_rect = QRectF(0, 0, d.width, NODE_HEADER_HEIGHT)
        # Sockets no longer need a hole punched under them — an unconnected
        # socket fakes the "canvas shows through" look itself via a radial
        # gradient (SocketItem.paint), so the body/header just draw their
        # plain rects, same as any other node.
        #
        # Fills first, border stroke last — not fill+stroke body_rect then
        # fill header_rect over it. A stroke on drawRect straddles the path
        # (half in, half out), so stroking body_rect first and then filling
        # header_rect (no pen of its own) on top overwrites that stroke's
        # inner half only where the header sits, leaving the border visibly
        # thinner/offset along the header edge than along the body edge
        # right below it — the same silhouette, two different apparent
        # widths. Filling both rects first and stroking the outline once,
        # last, over both keeps the border identical the entire height.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(body_color))
        painter.drawRect(body_rect)
        painter.setBrush(QBrush(header_color))
        painter.drawRect(header_rect)

        painter.setPen(border_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(body_rect)

        # An only-header-mode node used to get a second outline here, traced
        # around just header_rect in header_edge (a brightened header_color)
        # — on top of the border_pen stroke above, which already runs the
        # entire node's height including the header. Every param node is
        # only-header by default (PARAM_NODE_HEADER_FROM_SOCKET), so for the
        # overwhelmingly common uncustomized case this second outline came
        # out nearly the same colour as the header itself: a redundant,
        # barely-distinguishable ring around every param node's header,
        # doubled up with the real border right underneath it. Removed.

        if self._lod_far:
            self._paint_lod_primitives(painter)

    def _paint_lod_primitives(self, painter: QPainter):
        """Stand-ins for everything _set_lod_far hid: title, socket labels
        and embedded field content each get one flat bar sized to their own
        actual text length (not a generic fixed-width block) — a short name
        and a long one still read as visibly different at a glance, the way
        a squint at the real text would, without laying out or painting any
        of it for real.
        """
        painter.setPen(Qt.NoPen)
        self._draw_lod_text_bar(painter, self.title_item, QColor(self._title_text_color()))
        for child in self.childItems():
            if child is self.title_item:
                continue
            if isinstance(child, QGraphicsTextItem):
                self._draw_lod_text_bar(painter, child, child.defaultTextColor())
            elif isinstance(child, QGraphicsProxyWidget) and child.widget():
                self._draw_lod_widget_bar(painter, child)

    def _draw_lod_text_bar(self, painter: QPainter, text_item, color: QColor, *, height_frac: float = 0.55):
        """One bar standing in for ``text_item``'s real text, at the item's
        own position and sized to its own boundingRect width (already the
        actual laid-out text width Qt computed for it — no extra font-metrics
        work needed here)."""
        br = text_item.boundingRect()
        pos = text_item.pos()
        width = min(br.width(), self.node_def.width - pos.x() - NODE_HORIZONTAL_PAD)
        if width <= 0:
            return
        bar_color = QColor(color)
        bar_color.setAlpha(180)
        painter.setBrush(bar_color)
        h = br.height() * height_frac
        painter.drawRect(QRectF(pos.x(), pos.y() + (br.height() - h) / 2.0, width, h))

    def _draw_lod_widget_bar(self, painter: QPainter, proxy: QGraphicsProxyWidget, *, height_frac: float = 0.5):
        """Bars standing in for an embedded proxy's content — one per leaf
        widget (see _lod_leaf_widgets), each at that leaf's own position and
        size within the proxy, not one blob covering the whole slot. A
        compound row (EnumParamNode's new-item field plus its "+"/"-"
        buttons, PathParamNode's field-plus-browse-button rows) is exactly
        why: drawing it as a single bar made every button in it visually
        disappear into (or get swallowed by) the field's own bar — a button
        needs its own distinct mark to still read as "a button is here"
        rather than merging into whatever field sits next to it.
        """
        top = proxy.widget()
        proxy_pos = proxy.pos()
        for leaf in _lod_leaf_widgets(top):
            offset = QPoint(0, 0) if leaf is top else leaf.mapTo(top, leaf.rect().topLeft())
            self._draw_lod_leaf_bar(painter, leaf, proxy_pos + QPointF(offset.x(), offset.y()),
                                     leaf.size(), height_frac)

    @staticmethod
    def _draw_lod_leaf_bar(painter: QPainter, widget: QWidget, pos: QPointF,
                           size, height_frac: float):
        text = _lod_widget_text(widget)
        if text:
            width = min(QFontMetrics(widget.font()).horizontalAdvance(text), size.width())
        else:
            # No text to measure — either a plain button/icon or a
            # genuinely empty field; either way a bar spanning the leaf's
            # own slot reads as "a control is here", the same way a real,
            # empty QLineEdit still shows its own box with nothing typed
            # into it instead of vanishing.
            width = size.width()
        if width <= 0:
            return
        bar_color = QColor(TEXT_COLOR)
        bar_color.setAlpha(140)
        painter.setBrush(bar_color)
        h = size.height() * height_frac
        painter.drawRect(QRectF(pos.x(), pos.y() + (size.height() - h) / 2.0, width, h))

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            new_pos = value
            return QPointF(snap_to_grid(new_pos.x()), snap_to_grid(new_pos.y()))
        if change == QGraphicsItem.ItemPositionHasChanged and self.scene():
            self._refresh_connections()
        if change == QGraphicsItem.ItemSelectedHasChanged:
            if not value:
                if hasattr(self, '_dissolve_linked_group'):
                    self._dissolve_linked_group()
            self._refresh_selection_visuals()
        return super().itemChange(change, value)

    def _refresh_selection_visuals(self):
        """Recompute the selection wash and every embedded proxy's Z-order from
        current state — the single place that decides both. ParamNode overrides
        this to also account for the cross-node linked-editing group; every
        other caller (combo popup open/close, color picker, itemChange) should
        go through this method rather than touching ``_selection_overlay`` or a
        proxy's Z-value directly.

        Deliberately a full recompute rather than an incremental push/pop of a
        stashed "original" value: with push/pop, any skipped teardown step (an
        exception, a reentrant popup, a node torn down mid-interaction) leaves a
        boosted Z or hidden wash stuck forever. A full recompute self-heals on
        the very next selection/popup event because it never trusts leftover
        state — it re-derives the answer from what is true *right now*.
        """
        popup_open = self._has_open_combo_popup()
        self._selection_overlay.setVisible(self._is_visually_selected() and not popup_open)
        self.setZValue(NODE_POPUP_Z if popup_open else self._resting_z)
        self._resync_proxy_z()
        self.update()
        self._selection_overlay.update()
        # Every socket's ring reads self._is_visually_selected() too (the
        # outer keyline goes white while selected) — but a socket is a
        # separate child item with its own dirty region, which self.update()
        # above does not reliably cover: a socket's ring can extend past the
        # node's own boundingRect margin (NODE_BOUNDS_MARGIN), especially
        # once hover-grown, so its stale color could survive this repaint
        # until some unrelated later event happened to touch that exact
        # pixel region. Updating each socket directly closes that gap.
        for sock in self.sockets.values():
            sock.update()
        # QGraphicsItem.update() only *schedules* a repaint through Qt's own
        # dirty-region tracking, which GraphicsView._update_hovered_node
        # (view.py) already documents as unreliable under SmartViewportUpdate
        # for exactly this kind of cross-item visual change — the translucent
        # selection wash toggling on/off left ghost trails on screen for the
        # same reason a stale hover outline used to. Forcing the viewport to
        # actually repaint this node's mapped rect, the same explicit idiom
        # _update_hovered_node uses, is what makes the wash disappear/appear
        # cleanly instead of leaving a trail behind it.
        win = editor_window_of(self)
        if win is not None:
            try:
                rect = win.view.mapFromScene(self.sceneBoundingRect()).boundingRect()
            except RuntimeError:
                return  # deleted from under us
            win.view.viewport().update(rect)

    def _set_resting_z(self, z: float):
        """Change the Z this node returns to once no popup is open (see
        ``_resting_z``) and apply it immediately through the one recompute
        that owns node Z, so a resting-Z change while a popup happens to be
        open can't jump the node in front of its own popup.
        """
        self._resting_z = z
        self._refresh_selection_visuals()

    def _is_visually_selected(self) -> bool:
        """Whether the wash should show while no popup is open. ParamNode
        extends this to also cover the cross-node linked-editing group."""
        return self.isSelected()

    def _resync_proxy_z(self):
        """Set every embedded proxy to its resolved Z (see ``_proxy_target_z``)."""
        for child in self.childItems():
            if not (isinstance(child, QGraphicsProxyWidget) and child.widget()):
                continue
            if not hasattr(child, '_base_z'):
                child._base_z = child.zValue()
            target = self._proxy_target_z(child)
            if child.zValue() != target:
                child.setZValue(target)
                child.update()

    def _proxy_target_z(self, proxy) -> float:
        """Resting Z, or the popup-boost Z while this proxy's own combobox is open.

        ParamNode extends this to also boost the actively linked-edited field.
        """
        widget = proxy.widget()
        popup_open = isinstance(widget, NodeComboBox) and widget.popup_is_open
        if not popup_open:
            popup_open = any(c.popup_is_open for c in widget.findChildren(NodeComboBox))
        return NODE_COMBO_POPUP_PROXY_Z if popup_open else proxy._base_z

    def _set_hovered(self, hovered: bool):
        """Single setter for the hover outline.

        Its own hover events are unreliable — QGraphicsProxyWidget children
        swallow them (see the note by ``self._hovered`` in ``__init__``) — so
        GraphicsView's mouse-move tracking (view.py) derives hover from one
        authoritative poll instead, sidestepping that per widget type. The
        Project Inputs panel's row socket dot (ui/project_inputs_panel.py)
        calls this too, as a "preview which node this row is" affordance —
        same outline, a second legitimate trigger for it.
        """
        if self._hovered == hovered:
            return
        self._hovered = hovered
        self.update()

    def _make_proxy(self, widget: QWidget) -> QGraphicsProxyWidget:
        """Every embedded widget must be attached through this — the single
        place a proxy is created, so any future proxy-level behavior can't be
        wired differently by different node/field types.
        """
        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(widget)
        return proxy

    def _set_lod_far(self, far: bool):
        """Toggle the far-zoom level of detail (see NODE_LOD_DETAIL_SCALE):
        hide every text label and embedded field widget and let paint() draw
        a single flat color bar in the title's place instead. Called from
        GraphicsView whenever its scale actually crosses the threshold (see
        view.py) — not from paint() itself, since visibility is item state,
        not something to mutate on every repaint.

        Sockets are deliberately left alone: they're cheap primitives already
        (one drawEllipse/drawPolygon) and stay useful as topology landmarks
        at any zoom, so hiding them would remove information for no
        performance gain.
        """
        if self._lod_far == far:
            return
        self._lod_far = far
        for child in self.childItems():
            if isinstance(child, (QGraphicsTextItem, QGraphicsProxyWidget)):
                child.setVisible(not far)
        self.update()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if scene:
            # Deferred + coalesced (see _schedule_rect_recalc) rather than
            # recalculated synchronously here: a multi-select drag fires one
            # mouseReleaseEvent per dropped node, and each was redoing this
            # scan immediately — scheduling collapses a batch of releases in
            # the same tick into a single recalculation.
            scene._schedule_rect_recalc()
            self._adopt_containing_frame(scene)
        win = editor_window_of(self)
        if win:
            self._splice_into_dropped_connection(scene, win)

    def _adopt_containing_frame(self, scene):
        """Commit this node to the top-most frame under its center, if any."""
        best_frame = None
        if hasattr(scene, '_group_frames'):
            frames = scene._group_frames
        else:
            frames = [i for i in scene.items() if isinstance(i, GroupFrameItem)]
        for item in frames:
            if item.contains_node(self):
                if best_frame is None or item.zValue() > best_frame.zValue():
                    best_frame = item

        old_frame = getattr(self, '_group_frame', None)
        try:
            if old_frame and old_frame.scene() is None:
                old_frame = None
        except RuntimeError:
            old_frame = None

        if old_frame != best_frame:
            if old_frame:
                try:
                    members = getattr(old_frame, '_group_members', [])
                    if self in members:
                        members.remove(self)
                except RuntimeError:
                    pass
            self._group_frame = best_frame
            if best_frame:
                if not hasattr(best_frame, '_group_members'):
                    best_frame._group_members = []
                if self not in best_frame._group_members:
                    best_frame._group_members.append(self)

    def _splice_into_dropped_connection(self, scene, win):
        """A fully unwired node dropped onto a wire splices itself into it."""
        has_connections = any(
            c.source.meta_node is self or c.dest.meta_node is self
            for c in win.connections
        )
        if has_connections:
            return

        for item in self.collidingItems():
            if not isinstance(item, Connection):
                continue
            conn = item
            in_sock = None
            out_sock = None
            for s in self.sockets.values():
                if s.sock_def.kind == "input" and s.sock_def.is_exec == conn.is_exec:
                    in_sock = s
                    break
            for s in self.sockets.values():
                if s.sock_def.kind == "output" and s.sock_def.is_exec == conn.is_exec:
                    out_sock = s
                    break

            if in_sock and out_sock:
                scene.removeItem(conn)
                if conn in win.connections:
                    win.connections.remove(conn)

                scene.enforce_connection_rules(conn.source, in_sock)
                conn1 = Connection(conn.source, in_sock)
                scene.addItem(conn1)
                win.connections.append(conn1)

                scene.enforce_connection_rules(out_sock, conn.dest)
                conn2 = Connection(out_sock, conn.dest)
                scene.addItem(conn2)
                win.connections.append(conn2)

                self._refresh_connections()
                conn.source.meta_node._refresh_connections()
                conn.dest.meta_node._refresh_connections()
                win.push_undo_state()
                break

    def _has_open_combo_popup(self) -> bool:
        for child in self.childItems():
            if isinstance(child, QGraphicsProxyWidget) and child.widget():
                widget = child.widget()
                if isinstance(widget, NodeComboBox) and widget.popup_is_open:
                    return True
                if any(c.popup_is_open for c in widget.findChildren(NodeComboBox)):
                    return True
        return False

    def _refresh_connections(self):
        scene = self.scene()
        if not scene:
            return
        # Iterate the window's connection list (small) rather than scanning — and
        # sorting — every scene item; this runs on each frame of a node drag.
        # Vector-base names get collected in the same pass rather than update_
        # vector_buttons_visibility rescanning win.connections a second time
        # right after — both used to walk the same list independently on
        # every single drag frame.
        win = editor_window_of(self)
        connected_vector_bases = set()
        for conn in (win.connections if win else ()):
            touches_self = False
            if conn.source and conn.source.meta_node is self:
                touches_self = True
                if conn.source.sock_def.vector_base:
                    connected_vector_bases.add(conn.source.sock_def.vector_base)
            if conn.dest and conn.dest.meta_node is self:
                touches_self = True
                if conn.dest.sock_def.vector_base:
                    connected_vector_bases.add(conn.dest.sock_def.vector_base)
            if touches_self:
                conn.refresh()
        self.update_vector_buttons_visibility(connected_vector_bases)

    def _connected_vector_bases(self) -> set:
        """vector_base names of every vector socket of this node currently
        wired to something — used only where no _refresh_connections pass
        already collected this (e.g. right after the node's sockets are
        first built, before any drag has happened)."""
        win = editor_window_of(self)
        connected = set()
        if not win:
            return connected
        for c in win.connections:
            if c.source.meta_node is self and c.source.sock_def.vector_base:
                connected.add(c.source.sock_def.vector_base)
            if c.dest.meta_node is self and c.dest.sock_def.vector_base:
                connected.add(c.dest.sock_def.vector_base)
        return connected

    def update_vector_buttons_visibility(self, connected: Optional[set] = None):
        # LOD always wins over the connection-based show/hide below — this
        # runs on every _refresh_connections() (so on every move/connect,
        # far LOD or not), and without the _lod_far check it would happily
        # re-show a vector toggle proxy that _set_lod_far just hid, the
        # instant anything nearby moved while still zoomed out.
        if self._lod_far:
            for _, proxy in self._vector_buttons.values():
                proxy.setVisible(False)
            return
        if not self._vector_buttons:
            return
        if connected is None:
            connected = self._connected_vector_bases()
        for base_name, (_, proxy) in self._vector_buttons.items():
            proxy.setVisible(base_name not in connected)

    def toggle_vector_expansion(self, base_name: str):
        """
        Placeholder method to handle expansion of multi-component parameters.
        Why: Concrete node classes override this to dynamically spawn/collapse
        axis sockets. Raises rather than silently doing nothing: the only way
        this gets called is via a vector-toggle button (_make_vector_toggle),
        which a node only has if it already populated _vector_buttons — so
        reaching this base implementation means a node class added a vector
        toggle button without overriding the method that must handle its
        click, which should fail loudly during development, not silently
        no-op the button for a user.
        """
        raise NotImplementedError(
            f"{type(self).__name__} exposes a vector-toggle button but doesn't "
            f"override toggle_vector_expansion({base_name!r})")

    def _swap_node(self, new_node: "MetaNode"):
        """Replace self with ``new_node`` in the scene, migrating any connection
        whose socket name still exists on the replacement.

        Shared by every "this node's socket layout changed shape" toggle
        (CommandNode's X/Y/Z vector expand/collapse, VectorParamNode's
        split/merge) so there is exactly one way a node ever gets rebuilt in
        place: connections on sockets that don't survive the rebuild are
        simply dropped, the same behaviour either caller already relied on.
        """
        scene = self.scene()
        win = editor_window_of(self)
        if not win or not scene:
            return

        was_selected = self.isSelected()
        new_node.setPos(self.pos())
        # A genuinely user-picked color survives the rebuild; an untouched
        # default is left alone so the replacement computes its own
        # type-based default (e.g. Float3 -> float on split).
        if not self._color_is_default:
            new_node.set_color(self._color_override, only_header=self._color_only_header,
                               record_undo=False, is_default=False)
        if self._is_project_input:
            new_node.set_project_input(True, record_undo=False)
        scene.addItem(new_node)
        new_node.setSelected(was_selected)

        for old in list(win.connections):
            if old.source.meta_node is self:
                migrated = new_node.sockets.get(old.source.sock_def.name)
                if migrated:
                    self._rewire(scene, win, migrated, old.dest)
            elif old.dest.meta_node is self:
                migrated = new_node.sockets.get(old.dest.sock_def.name)
                if migrated:
                    self._rewire(scene, win, old.source, migrated)
            else:
                continue
            scene.removeItem(old)
            if old in win.connections:
                win.connections.remove(old)

        scene.removeItem(self)
        win.push_undo_state()

    @staticmethod
    def _rewire(scene, win, out_sock: "SocketItem", in_sock: "SocketItem"):
        scene.enforce_connection_rules(out_sock, in_sock)
        conn = Connection(out_sock, in_sock)
        scene.addItem(conn)
        win.connections.append(conn)
        conn.source.meta_node._refresh_connections()
        conn.dest.meta_node._refresh_connections()

    def get_socket(self, name: str) -> Optional[SocketItem]:
        return self.sockets.get(name)

    def _run_context_menu(self, event, actions):
        """Thin instance-method wrapper — the real implementation is the
        module-level run_context_menu (ui/title_item.py), shared verbatim
        with GroupFrameItem (Ст.1.1/Ст.14.3). Kept as a method since
        CommandNode/ParamNode subclasses already call self._run_context_menu(...)."""
        run_context_menu(event, actions)

    def _delete_self(self):
        win = editor_window_of(self)
        if win:
            self.setSelected(True)
            win._delete_selected_items()

    def _extra_context_actions(self) -> list:
        """Node-type-specific menu entries, inserted right after the color
        picker. Override in a subclass instead of overriding the whole menu.
        """
        return []

    def contextMenuEvent(self, event):
        win = editor_window_of(self)
        if not win:
            super().contextMenuEvent(event)
            return

        extra = self._extra_context_actions()

        self._run_context_menu(event, [
            (t("ctx_rename"),       getattr(self, "_begin_rename", None), self.supports_plain_rename, HOTKEY_HINTS["rename"]),
            (t("ctx_change_color"), self._pick_color,                           True),
            *([None, *extra] if extra else []),
            None,
            (t("ctx_duplicate"),    getattr(win, "duplicate_nodes",      None), True, HOTKEY_HINTS["duplicate"]),
            (t("ctx_copy"),         getattr(win, "copy_nodes",           None), True, HOTKEY_HINTS["copy"]),
            (t("ctx_paste"),        getattr(win, "paste_nodes",          None), True, HOTKEY_HINTS["paste"]),
            (t("ctx_group_frame"),  getattr(win, "group_selected_nodes", None), True, HOTKEY_HINTS["group"]),
            None,
            (t("ctx_delete_node"),  self._delete_self,                          True, HOTKEY_HINTS["delete"]),
        ])

    def serialize_payload(self) -> dict:
        """Type-specific fields needed to reconstruct this node (sans id/position).

        Overridden per node type so persistence never has to branch on the class.
        """
        return {}

    def retranslate(self):
        """Re-resolve this node's translatable text in place for the active
        language — no rebuild, no socket/connection churn.

        Why in-place instead of the old approach (serialize + clear_graph +
        materialize_graph on every tab): that path tore down and recreated
        every node's embedded widgets on a language switch, which turned a
        text-only refresh into an O(n) full graph rebuild — the actual cost
        scales with node count, not with how much text changed. Override in
        subclasses that own translatable defaults (title, placeholders,
        static button text); the base no-op covers CommandNode, whose title
        and socket labels come from the RC command database, not gettext.
        """


class NodeComboBox(QComboBox):
    """Note: deliberately no hand-maintained "is my popup open" flag — see
    ``popup_is_open``. A flag that has to be set on show and unset on hide is
    exactly the kind of paired state that leaks when a step gets skipped
    (an exception, a reentrant popup, a node torn down mid-interaction);
    asking Qt directly cannot go stale.
    """

    def __init__(self, node: MetaNode):
        from ui.scrollbar import UnifiedScrollBar
        from PyQt5.QtWidgets import QListView
        from PyQt5.QtCore import Qt
        super().__init__()
        self.node = node
        
        # Explicitly enforce a list view to bypass native OS menu-style popups
        # which lack standard scrollbars (e.g. for non-editable comboboxes).
        view = QListView()
        self.setView(view)
        # QComboBox.setView() silently resets the view's own scrollbar
        # policy to ScrollBarAlwaysOff (it assumes the popup will manage
        # overflow itself) — setting ScrollBarAsNeeded *before* setView()
        # just gets clobbered, so it has to happen after, or a long list
        # (e.g. the [E] Enum node's dropdown) opens with no scrollbar at all.
        self.view().setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.view().setVerticalScrollBar(UnifiedScrollBar())
        self.setMaxVisibleItems(10)

    @property
    def popup_is_open(self) -> bool:
        view = self.view()
        return view is not None and view.isVisible()

    def showPopup(self):
        super().showPopup()
        self._safe_refresh()
        node = self._safe_node()
        if node is None:
            return
        win = editor_window_of(node)
        if win is not None:
            win.view.register_open_popup(self)

    def hidePopup(self):
        super().hidePopup()
        self._safe_refresh()
        node = self._safe_node()
        if node is not None:
            win = editor_window_of(node)
            if win is not None:
                win.view.unregister_open_popup(self)
        # Belt-and-suspenders: on some platforms popup teardown can still be
        # mid-flight when hidePopup() returns, so re-settle once the event
        # loop catches up.
        QTimer.singleShot(0, self._safe_refresh)

    def _safe_node(self) -> Optional[MetaNode]:
        """``self.node``, or ``None`` if this wrapper's ``__init__`` never
        ran — the one place every ``self.node`` access in this class routes
        through, so the "was this widget's __init__ ever called" question
        only has one answer instead of a try/except repeated at each call
        site (ст. 14.3). See _safe_refresh for why this happens: Qt can
        recreate a fresh Python shim for a still-alive C++ combobox after the
        original wrapper (and its self.node) was garbage-collected, and a
        deferred callback (QTimer.singleShot above, or an event queued before
        teardown) then fires against that shim.
        """
        return getattr(self, "node", None)

    def _safe_refresh(self):
        node = self._safe_node()
        if node is None:
            return
        try:
            node._refresh_selection_visuals()
        except RuntimeError:
            pass  # the underlying C++ node was already deleted
