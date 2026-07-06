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
    QToolButton, QMenu, QPushButton,
)
from PyQt5.QtGui import (
    QPen, QBrush, QColor, QPainterPath, QFont, QFontMetrics, QPainter, QPolygonF,
    QCursor,
)
from PyQt5.QtCore import QRectF, Qt, QPoint, QPointF, QTimer

from localization import t
from configuration import (
    NODE_HEADER_HEIGHT,
    NODE_EXEC_SOCKET_HALFSIZE, NODE_PARAM_SOCKET_RADIUS,
    NODE_HORIZONTAL_PAD,
    NODE_SHADOW_OFFSET_X, NODE_SHADOW_OFFSET_Y, NODE_SHADOW_BLUR, NODE_BOUNDS_MARGIN,
    SOCKET_HOVER_COLOR, NODE_SELECTED_COLOR, NODE_HOVER_COLOR, NODE_HOVER_BORDER_WIDTH,
    CONNECTION_SELECTED_COLOR, TEXT_COLOR,
    BEZIER_CTRL_FACTOR, BEZIER_CTRL_MIN,
    SOCKET_BORDER_DARKEN, SOCKET_BORDER_WIDTH,
    CONNECTION_EXEC_WIDTH, CONNECTION_EXEC_SELECTED_WIDTH,
    CONNECTION_PARAM_WIDTH, CONNECTION_PARAM_SELECTED_WIDTH,
    GRID_SIZE_SMALL, NODE_POPUP_Z, NODE_COMBO_POPUP_PROXY_Z,
    VECTOR_COLLAPSE_GLYPH, VECTOR_COLLAPSE_GLYPH_MIRRORED, VECTOR_EXPAND_GLYPH, VECTOR_TOGGLE_WIDTH,
    NODE_SELECTION_OVERLAY_RGBA, NODE_SELECTION_OVERLAY_Z, NODE_SOCKET_Z,
    CONNECTION_Z,
    UI_FONT_FAMILY, NODE_LABEL_FONT_SIZE, NODE_RENAME_FONT_SIZE,
    TINT_BODY_DARKEN, TINT_TITLE_LUMINANCE_THRESHOLD,
    PARAM_NODE_HEADER_FROM_SOCKET, HOTKEY_HINTS,
)
from ui.theme import (
    NODE_BORDER_COLOR,
    relative_luminance, brightened_for_canvas,
    DEFAULT_WIDGET_QSS, widget_stylesheets, tinted_widget_palette,
    VECTOR_TOGGLE_QSS, CONTEXT_MENU_STYLESHEET,
    apply_field_placeholder_palette,
)
from core.node_blueprint import NodeDef, SocketDef, html_title
from ui.color_picker import ColorPickerPopup

# Re-exports from extracted modules — keep ``from ui.graph_items import …`` working.
from ui.title_item import (                                          # noqa: F401
    _EditableTitleItem, RenamableTitleMixin,
    editor_window_of, _merge_hsv_component, selected_of_type_including,
)
from ui.group_frame import GroupFrameItem                            # noqa: F401
from ui.widgets import InsetFillCheckBox, suppress_default_selection_chrome  # noqa: F401


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

        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setAcceptHoverEvents(True)
        self.setZValue(NODE_SOCKET_Z)
        self.setPos(node_def.socket_x(sock_def.kind), node_def.socket_y(row, sock_def.is_exec))

    def boundingRect(self) -> QRectF:
        r = self._radius + 3
        return QRectF(-r, -r, 2 * r, 2 * r)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        r = self._radius
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

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        color  = QColor(SOCKET_HOVER_COLOR if self._hovered else self.sock_def.color)
        border = QPen(color.darker(SOCKET_BORDER_DARKEN), SOCKET_BORDER_WIDTH)
        r = self._radius
        painter.setPen(border)
        painter.setBrush(QBrush(color))
        if self.meta_node._lod_far:
            # A square reads as a socket "dot" from a distance without the
            # extra vertices a diamond/circle costs to rasterize — plenty at
            # a zoom where the exec/param shape distinction isn't legible
            # anyway.
            painter.drawRect(QRectF(-r, -r, 2 * r, 2 * r))
        elif self.sock_def.is_exec:
            painter.drawPolygon(QPolygonF([
                QPointF(0, -r), QPointF(r, 0),
                QPointF(0,  r), QPointF(-r, 0),
            ]))
        else:
            painter.drawEllipse(QPointF(0, 0), r, r)

    def hoverEnterEvent(self, event):
        self._hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.scene().start_connection_drag(self)
            event.accept()
        else:
            event.ignore()

    def scene_center(self) -> QPointF:
        return self.mapToScene(QPointF(0, 0))


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
        self.refresh()

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
        self.setPen(self._pen_selected if self.isSelected() else self._pen)
        painter.setRenderHint(QPainter.Antialiasing)
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
                label = QGraphicsTextItem(text_to_show, self)
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

    def default_color_override(self) -> Tuple[Optional[str], bool]:
        """The (color, only_header) pair this node is born with — reset target.

        Mirrors ``_apply_initial_socket_color``: the first non-exec output
        socket's colour, painted header-only, for param nodes; ``(None,
        False)`` for exec/command nodes so they fall back to the plain
        ``DEFAULT_HEADER_COLOR`` scheme.
        """
        if not PARAM_NODE_HEADER_FROM_SOCKET:
            return None, False
        for sd in self.node_def.sockets:
            if sd.kind == "output" and not sd.is_exec:
                return sd.color, True
        return None, False

    def reset_color(self, *, record_undo: bool = True):
        color, only_header = self.default_color_override()
        self.set_color(color, only_header=only_header, record_undo=record_undo, is_default=True)

    def color_override(self) -> Optional[str]:
        return self._color_override

    def color_only_header(self) -> bool:
        return self._color_only_header

    def set_color(self, color_hex: Optional[str], *, only_header: bool = False,
                  record_undo: bool = True, is_default: bool = False):
        self._color_override = color_hex
        self._color_only_header = bool(only_header) and color_hex is not None
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

        # A picked color tints the header; in full-scope mode the body and outer
        # border take the same tint family, in only-header mode body and outer
        # border stay on the default scheme and only the header gets the pick.
        only_header = bool(self._color_override) and self._color_only_header
        if self._color_override:
            header_color = QColor(self._color_override)
            header_edge = brightened_for_canvas(header_color)
            if only_header:
                body_color = QColor(d.body_color)
                body_color.setAlpha(header_color.alpha())
                body_border_color = QColor(NODE_BORDER_COLOR)
                body_border_color.setAlpha(header_color.alpha())
                header_edge.setAlpha(header_color.alpha())
            else:
                body_color = header_color.darker(TINT_BODY_DARKEN)
                body_border_color = header_edge
        else:
            header_color = QColor(d.header_color)
            header_edge = QColor(NODE_BORDER_COLOR)
            body_color = QColor(d.body_color)
            body_border_color = QColor(NODE_BORDER_COLOR)

        if visually_selected:
            border_pen = QPen(QColor(NODE_SELECTED_COLOR), 2.0)
        elif self._hovered:
            # This one rect spans the whole node (header included — the header
            # fill just paints over its top portion), so a single hover pen
            # here outlines the entire node whether the cursor is over the
            # header or the body.
            border_pen = QPen(QColor(NODE_HOVER_COLOR), NODE_HOVER_BORDER_WIDTH)
        else:
            border_pen = QPen(body_border_color, 1.0)
        painter.setPen(border_pen)
        painter.setBrush(QBrush(body_color))
        painter.drawRect(QRectF(0, 0, d.width, d.body_height))

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(header_color))
        painter.drawRect(QRectF(0, 0, d.width, NODE_HEADER_HEIGHT))

        # Header outline: in only-header mode the picked colour traces the entire
        # header rectangle (top, sides, bottom) so the band reads as a self-
        # contained region. In full-tint mode the outer body border already
        # carries the tint, so no extra line is needed at the header/body seam
        # — one used to be drawn there, but for the common (uncustomized)
        # case it matched the header colour exactly and just looked like a
        # stray line for no reason.
        if only_header and not visually_selected:
            painter.setPen(QPen(header_edge, 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(0, 0, d.width, NODE_HEADER_HEIGHT))

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
            x = round(new_pos.x() / GRID_SIZE_SMALL) * GRID_SIZE_SMALL
            y = round(new_pos.y() / GRID_SIZE_SMALL) * GRID_SIZE_SMALL
            return QPointF(x, y)
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
        """Single setter for the hover outline. Called from exactly one place:
        GraphicsView's mouse-move tracking (view.py) — not from this item's
        own hover events, which QGraphicsProxyWidget children make unreliable
        (see the note by ``self._hovered`` in ``__init__``). Deriving hover
        from one authoritative poll instead of per-item hover events sidesteps
        that entirely instead of working around it per widget type.
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
        """Show a node context menu.

        Each entry in `actions` is either:
          - ``(label, callback, enabled)`` or ``(label, callback, enabled, hint)``
            — a normal action; ``hint`` (e.g. "Ctrl+D") is shown right-aligned,
            display-only — see HOTKEY_HINTS in configuration.py
          - ``None``                       — a visual separator
        """
        menu = QMenu()
        menu.setStyleSheet(CONTEXT_MENU_STYLESHEET)
        handlers = {}
        for item in actions:
            if item is None:
                menu.addSeparator()
                continue
            label, callback, enabled, *rest = item
            hint = rest[0] if rest else None
            text = f"{label}\t{hint}" if hint else label
            entry = menu.addAction(text)
            entry.setEnabled(enabled and callback is not None)
            handlers[entry] = callback
        chosen = menu.exec_(event.screenPos())
        if chosen is not None and handlers.get(chosen):
            handlers[chosen]()
        event.accept()

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
        super().__init__()
        self.node = node

    @property
    def popup_is_open(self) -> bool:
        view = self.view()
        return view is not None and view.isVisible()

    def showPopup(self):
        super().showPopup()
        self._safe_refresh()

    def hidePopup(self):
        super().hidePopup()
        self._safe_refresh()
        # Belt-and-suspenders: on some platforms popup teardown can still be
        # mid-flight when hidePopup() returns, so re-settle once the event
        # loop catches up.
        QTimer.singleShot(0, self._safe_refresh)

    def _safe_refresh(self):
        try:
            self.node._refresh_selection_visuals()
        except (RuntimeError, AttributeError):
            # RuntimeError: the underlying C++ node was already deleted.
            # AttributeError: this callback was deferred (see hidePopup's
            # QTimer.singleShot above) and fired after the widget got
            # reparented/rebuilt elsewhere (e.g. mid session-restore) without
            # its Python __init__ running again, so self.node was never set.
            # Either way, there's nothing left to refresh.
            pass
