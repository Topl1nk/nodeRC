"""graph_items.py — The Scene's Visual Vocabulary

Sockets, Bézier wires, node bodies with embedded-widget tinting, the selection
overlay, and the node combo box. GroupFrameItem, InsetFillCheckBox, and the
rename machinery live in their own modules; this file re-exports them so
existing ``from ui.graph_items import …`` lines keep working.
"""
from __future__ import annotations

from typing import Dict, Optional

from PyQt5.QtWidgets import (
    QGraphicsObject, QGraphicsItem, QGraphicsTextItem,
    QGraphicsProxyWidget, QLineEdit, QCheckBox,
    QSpinBox, QComboBox, QGraphicsPathItem, QWidget,
    QToolButton, QStyle, QMenu, QPushButton,
)
from PyQt5.QtGui import (
    QPen, QBrush, QColor, QPainterPath, QFont, QPainter, QPolygonF,
    QCursor,
)
from PyQt5.QtCore import QRectF, Qt, QPointF, QTimer

from localization import t
from configuration import (
    NODE_HEADER_HEIGHT,
    NODE_EXEC_SOCKET_HALFSIZE, NODE_PARAM_SOCKET_RADIUS,
    NODE_HORIZONTAL_PAD,
    NODE_SHADOW_OFFSET_X, NODE_SHADOW_OFFSET_Y, NODE_SHADOW_BLUR, NODE_BOUNDS_MARGIN,
    SOCKET_HOVER_COLOR, NODE_SELECTED_COLOR, CONNECTION_SELECTED_COLOR, TEXT_COLOR,
    BEZIER_CTRL_FACTOR, BEZIER_CTRL_MIN,
    GRID_SIZE_SMALL, NODE_POPUP_Z,
    VECTOR_COLLAPSE_GLYPH, VECTOR_EXPAND_GLYPH,
    NODE_SELECTION_OVERLAY_RGBA, NODE_SELECTION_OVERLAY_Z, NODE_SOCKET_Z,
    CONNECTION_Z,
    UI_FONT_FAMILY, NODE_LABEL_FONT_SIZE,
    TINT_BODY_DARKEN, TINT_TITLE_LUMINANCE_THRESHOLD,
    PARAM_NODE_HEADER_FROM_SOCKET,
)
from ui.theme import (
    NODE_BORDER_COLOR,
    relative_luminance, brightened_for_canvas,
    DEFAULT_WIDGET_QSS, widget_stylesheets, tinted_widget_palette,
    VECTOR_TOGGLE_QSS, CONTEXT_MENU_STYLESHEET,
    DEFAULT_WIDGET_PALETTE,
)
from core.node_blueprint import NodeDef, SocketDef, html_title
from ui.color_picker import ColorPickerPopup

# Re-exports from extracted modules — keep ``from ui.graph_items import …`` working.
from ui.title_item import (                                          # noqa: F401
    _EditableTitleItem, RenamableTitleMixin,
    editor_window_of, _merge_hsv_component,
)
from ui.group_frame import GroupFrameItem                            # noqa: F401
from ui.widgets import InsetFillCheckBox                             # noqa: F401


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
        if self.sock_def.is_exec:
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
        border = QPen(color.darker(160), 1.5)
        r = self._radius
        painter.setPen(border)
        painter.setBrush(QBrush(color))
        if self.sock_def.is_exec:
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
            self._pen     = QPen(QColor(source.sock_def.color), 3.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            self._pen_selected = QPen(QColor(CONNECTION_SELECTED_COLOR), 3.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        else:
            self._pen     = QPen(QColor(source.sock_def.color), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            self._pen_selected = QPen(QColor(CONNECTION_SELECTED_COLOR), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
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
        if option.state & QStyle.State_Selected:
            option.state &= ~QStyle.State_Selected
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


class MetaNode(RenamableTitleMixin, QGraphicsObject):
    """
    Why: BoundingRect includes shadow area to prevent trail artifacts on move.
    """

    is_protected = False  # the single source for "bulk delete must spare this node"
    supports_plain_rename = False  # param nodes enable the generic Rename entry

    def __init__(self, node_def: NodeDef):
        super().__init__()
        self.node_def = node_def
        self.sockets: Dict[str, SocketItem] = {}
        self._vector_buttons: Dict[str, tuple] = {}
        self._color_override: Optional[str] = None  # user-picked header tint, if any
        # When True the override only repaints the header + its border; the body
        # and embedded widgets keep their default scheme. Lets the user mark a
        # node visually without re-skinning every inner control.
        self._color_only_header: bool = False
        self.setFlags(
            QGraphicsItem.ItemIsMovable |
            QGraphicsItem.ItemIsSelectable |
            QGraphicsItem.ItemSendsScenePositionChanges,
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
        self.title_item.setHtml(d.title)
        self.title_item.setDefaultTextColor(QColor("white"))
        self._center_title()

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

                if socket_def.kind == "input":
                    label_x = NODE_EXEC_SOCKET_HALFSIZE * 2 + 5
                    label.setPos(label_x, label_y)

                    if socket_def.is_collapsed_vector or socket_def.is_expanded_vector_start:
                        toggle = QToolButton()
                        toggle.setText(
                            VECTOR_COLLAPSE_GLYPH if socket_def.is_collapsed_vector
                            else VECTOR_EXPAND_GLYPH
                        )
                        toggle.setStyleSheet(VECTOR_TOGGLE_QSS)
                        toggle.setCursor(Qt.PointingHandCursor)
                        proxy = QGraphicsProxyWidget(self)
                        proxy.setWidget(toggle)
                        proxy.setPos(label_x + label_width + 2, label_y)
                        base_name = socket_def.vector_base
                        toggle.clicked.connect(
                            lambda _, base=base_name: self.toggle_vector_expansion(base)
                        )
                        self._vector_buttons[base_name] = (toggle, proxy)
                else:
                    label.setPos(d.width - NODE_EXEC_SOCKET_HALFSIZE * 2 - 5 - label_width, label_y)

                label.setDefaultTextColor(QColor(socket_def.color))
        self.update_vector_buttons_visibility()

    def _center_title(self):
        text_h = QGraphicsTextItem.boundingRect(self.title_item).height()
        self.title_item.setPos(
            NODE_HORIZONTAL_PAD,
            (NODE_HEADER_HEIGHT - text_h) / 2.0,
        )

    # ── In-place rename ───────────────────────────────────────────────────────

    def _commit_title(self, name: str):
        self._apply_title(name)
        self._on_renamed(name)

    def _revert_title(self, backup: str):
        self._apply_title(backup)

    def _apply_title(self, text: str):
        self.title_item.setHtml(html_title(text))
        self._center_title()
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
        if not PARAM_NODE_HEADER_FROM_SOCKET:
            return
        # Only apply to output sockets on non-exec types.
        for sd in self.node_def.sockets:
            if sd.kind == "output" and not sd.is_exec:
                self._color_override = sd.color
                self._color_only_header = True
                return

    def color_override(self) -> Optional[str]:
        return self._color_override

    def color_only_header(self) -> bool:
        return self._color_only_header

    def set_color(self, color_hex: Optional[str], *, only_header: bool = False,
                  record_undo: bool = True):
        self._color_override = color_hex
        self._color_only_header = bool(only_header) and color_hex is not None
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

    # Buttons that toggle a vector axis are visually neutral chevrons living over
    # a socket label, not editable controls — they keep their inline glyph style
    # regardless of any tint. Discriminate them by the actual glyph rather than
    # by "+" / "-" text, which would also catch the Enum add/remove buttons.
    _VECTOR_TOGGLE_GLYPHS = frozenset((VECTOR_COLLAPSE_GLYPH, VECTOR_EXPAND_GLYPH))
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
            return
        if isinstance(widget, QSpinBox):
            widget.setStyleSheet(qss["spin"])
            return
        if isinstance(widget, QLineEdit):
            widget.setStyleSheet(qss["field"])
        elif isinstance(widget, QCheckBox):
            widget.setStyleSheet(qss["check"])
            if isinstance(widget, InsetFillCheckBox):
                widget.update_indicator_colors(qss["check_border"], qss["check_bg"])
        elif isinstance(widget, QToolButton):
            if widget.text() in cls._VECTOR_TOGGLE_GLYPHS:
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

        selected_nodes = [item for item in self.scene().selectedItems() if isinstance(item, MetaNode)]
        if self not in selected_nodes:
            selected_nodes.append(self)

        for node in selected_nodes:
            node._selection_overlay.setVisible(False)

        def on_close():
            for node in selected_nodes:
                node._selection_overlay.setVisible(node.isSelected())
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
                               record_undo=False)

        initial = self._color_override or self.node_def.header_color
        popup = ColorPickerPopup(
            on_color_selected=apply_color_to_all,
            on_only_header_changed=apply_scope_to_all if len(selected_nodes) > 1 else None,
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
        if option.state & QStyle.State_Selected:
            option.state &= ~QStyle.State_Selected
        painter.setRenderHint(QPainter.Antialiasing)
        d = self.node_def

        win = editor_window_of(self)
        is_linked = win is not None and self in getattr(win, '_linked_group', [])
        visually_selected = self.isSelected() or is_linked

        # A picked color tints the header; in full-scope mode the body and outer
        # border take the same tint family, in only-header mode body and outer
        # border stay on the default scheme and only the header (with the divider
        # line beneath it) gets the pick.
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

        painter.setPen(
            QPen(QColor(NODE_SELECTED_COLOR), 2.0) if visually_selected
            else QPen(body_border_color, 1.0)
        )
        painter.setBrush(QBrush(body_color))
        painter.drawRect(QRectF(0, 0, d.width, d.body_height))

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(header_color))
        painter.drawRect(QRectF(0, 0, d.width, NODE_HEADER_HEIGHT))

        # Header outline: in only-header mode the picked colour traces the entire
        # header rectangle (top, sides, bottom) so the band reads as a self-
        # contained region. In full-tint mode just the divider line at the bottom
        # is enough, because the outer body border already carries the tint.
        if only_header and not visually_selected:
            painter.setPen(QPen(header_edge, 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(0, 0, d.width, NODE_HEADER_HEIGHT))
        else:
            painter.setPen(QPen(header_edge, 1))
            painter.drawLine(
                QPointF(0, NODE_HEADER_HEIGHT),
                QPointF(d.width, NODE_HEADER_HEIGHT),
            )

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
            if hasattr(self, "_refresh_selection_visuals"):
                self._refresh_selection_visuals()
            else:
                show = bool(value) and not self._has_open_combo_popup()
                self._selection_overlay.setVisible(show)
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if scene:
            scene.recalculate_scene_rect()
            self._adopt_containing_frame(scene)
        win = editor_window_of(self)
        if win:
            self._splice_into_dropped_connection(scene, win)

    def _adopt_containing_frame(self, scene):
        """Commit this node to the top-most frame under its center, if any."""
        best_frame = None
        for item in scene.items():
            if isinstance(item, GroupFrameItem):
                frame_rect = item.mapToScene(item.rect()).boundingRect()
                if frame_rect.contains(self.sceneBoundingRect().center()):
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
                for combo in child.widget().findChildren(NodeComboBox):
                    if combo._popup_open:
                        return True
                if isinstance(child.widget(), NodeComboBox) and child.widget()._popup_open:
                    return True
        return False

    def _refresh_connections(self):
        scene = self.scene()
        if not scene:
            return
        # Iterate the window's connection list (small) rather than scanning — and
        # sorting — every scene item; this runs on each frame of a node drag.
        win = editor_window_of(self)
        for conn in (win.connections if win else ()):
            if (conn.source and conn.source.meta_node is self) or \
               (conn.dest   and conn.dest.meta_node   is self):
                conn.refresh()
        self.update_vector_buttons_visibility()

    def _is_vector_connected(self, base_name: str) -> bool:
        win = editor_window_of(self)
        if not win:
            return False
        for c in win.connections:
            if c.source.meta_node is self and c.source.sock_def.vector_base == base_name:
                return True
            if c.dest.meta_node is self and c.dest.sock_def.vector_base == base_name:
                return True
        return False

    def update_vector_buttons_visibility(self):
        for base_name, (_, proxy) in self._vector_buttons.items():
            proxy.setVisible(not self._is_vector_connected(base_name))

    def toggle_vector_expansion(self, base_name: str):
        """
        Placeholder method to handle expansion of multi-component parameters.
        Why: Concrete node classes override this to dynamically spawn/collapse axis sockets.
        """
        return

    def get_socket(self, name: str) -> Optional[SocketItem]:
        return self.sockets.get(name)

    def _editor_window(self):
        return editor_window_of(self)

    def _run_context_menu(self, event, actions):
        """Show a node context menu.

        Each entry in `actions` is either:
          - ``(label, callback, enabled)`` — a normal action
          - ``None``                       — a visual separator
        """
        menu = QMenu()
        menu.setStyleSheet(CONTEXT_MENU_STYLESHEET)
        handlers = {}
        for item in actions:
            if item is None:
                menu.addSeparator()
                continue
            label, callback, enabled = item
            entry = menu.addAction(label)
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

    def contextMenuEvent(self, event):
        win = editor_window_of(self)
        if not win:
            super().contextMenuEvent(event)
            return

        self._run_context_menu(event, [
            (t("ctx_rename"),       getattr(self, "_begin_rename", None), self.supports_plain_rename),
            (t("ctx_change_color"), self._pick_color,                           True),
            None,
            (t("ctx_duplicate"),    getattr(win, "duplicate_nodes",      None), True),
            (t("ctx_copy"),         getattr(win, "copy_nodes",           None), True),
            (t("ctx_paste"),        getattr(win, "paste_nodes",          None), True),
            (t("ctx_group_frame"),  getattr(win, "group_selected_nodes", None), True),
            None,
            (t("ctx_delete_node"),  self._delete_self,                          True),
        ])

    def serialize_payload(self) -> dict:
        """Type-specific fields needed to reconstruct this node (sans id/position).

        Overridden per node type so persistence never has to branch on the class.
        """
        return {}


class NodeComboBox(QComboBox):
    _popup_open = False

    def __init__(self, node: MetaNode):
        super().__init__()
        self.node = node

    def _find_proxy(self):
        """Walk up the widget parent chain to find the QGraphicsProxyWidget."""
        w = self
        while w is not None:
            proxy = w.graphicsProxyWidget()
            if proxy is not None:
                return proxy
            w = w.parentWidget()
        return None

    def showPopup(self):
        self._popup_open = True
        try:
            self.node.setZValue(NODE_POPUP_Z)
            proxy = self._find_proxy()
            if proxy is not None:
                self._original_proxy_z = proxy.zValue()
                proxy.setZValue(4000)
            overlay = getattr(self.node, "_selection_overlay", None)
            if overlay is not None:
                overlay.setVisible(False)
        except RuntimeError:
            pass
        super().showPopup()

    def hidePopup(self):
        super().hidePopup()
        self._popup_open = False
        try:
            self.node.setZValue(0)
            proxy = self._find_proxy()
            if proxy is not None and hasattr(self, '_original_proxy_z'):
                proxy.setZValue(self._original_proxy_z)
                delattr(self, '_original_proxy_z')
        except RuntimeError:
            pass
        QTimer.singleShot(0, self._restore_overlay)

    def _restore_overlay(self):
        try:
            overlay = getattr(self.node, "_selection_overlay", None)
            if overlay is not None:
                overlay.setVisible(self.node.isSelected())
        except RuntimeError:
            pass
