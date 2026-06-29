from __future__ import annotations
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

from PyQt5.QtWidgets import (
    QGraphicsObject, QGraphicsItem, QGraphicsTextItem,
    QGraphicsProxyWidget, QPushButton, QLineEdit, QCheckBox,
    QSpinBox, QComboBox, QGraphicsPathItem, QWidget,
    QHBoxLayout, QToolButton, QStyle, QLabel,
    QApplication, QAbstractSpinBox,
)
from PyQt5.QtGui import (
    QPen, QBrush, QColor, QPainterPath, QFont, QPainter, QPolygonF,
    QDoubleValidator, QPalette, QTextCursor,
)
from PyQt5.QtCore import QRectF, Qt, QPointF, QEvent, QTimer

from configuration import (
    NODE_HEADER_HEIGHT, NODE_ROW_HEIGHT,
    NODE_EXEC_SOCKET_HALFSIZE, NODE_PARAM_SOCKET_RADIUS,
    NODE_DEFAULT_WIDTH, NODE_HORIZONTAL_PAD,
    NODE_FOOTER_HEIGHT, NODE_BOTTOM_PAD, NODE_WIDGET_V_OFFSET, NODE_WIDGET_HEIGHT,
    NODE_SHADOW_OFFSET_X, NODE_SHADOW_OFFSET_Y, NODE_SHADOW_BLUR,
    SOCKET_COLOR_SCHEMA, SOCKET_HOVER_COLOR,
    NODE_SELECTED_COLOR, NODE_BORDER_COLOR, CONNECTION_SELECTED_COLOR,
    BUTTON_BG_COLOR, BUTTON_HOVER_COLOR, BUTTON_PRESSED_COLOR,
    BUTTON_TEXT_COLOR, CANVAS_BACKGROUND_COLOR, TEXT_COLOR, TEXT_MUTED_COLOR,
    BEZIER_CTRL_FACTOR, BEZIER_CTRL_MIN, BROWSE_BTN_WIDTH,
    GRID_SIZE_SMALL,
    INTEGER_PARAM_NAMES, NODE_POPUP_Z,
    VECTOR_COLLAPSE_GLYPH, VECTOR_EXPAND_GLYPH, VECTOR_AXIS_LABEL_COLOR,
    NODE_SELECTION_OVERLAY_RGBA, NODE_SELECTION_OVERLAY_Z,
    NODE_SOCKET_Z, NODE_WIDGET_Z_BASE,
)

_FIELD_QSS = (
    f"QLineEdit{{"
    f"border:1px solid {NODE_BORDER_COLOR};"
    f"background:{CANVAS_BACKGROUND_COLOR};"
    f"color:{TEXT_COLOR};"
    f"border-radius:0px;"
    f"padding:2px 4px;"
    f"font:9pt Consolas;"
    f"}}"
    f"QLineEdit:read-only{{"
    f"color:{TEXT_MUTED_COLOR};"
    f"}}"
)

_COMBOBOX_QSS = (
    f"QComboBox{{border:1px solid {NODE_BORDER_COLOR};background:{CANVAS_BACKGROUND_COLOR};"
    f"color:{TEXT_COLOR};border-radius:0px;padding:2px 4px;font:9pt Consolas;combobox-popup:0;}}"
    f"QComboBox::drop-down{{border-left:1px solid {NODE_BORDER_COLOR};"
    f"width:{BROWSE_BTN_WIDTH}px;background:{BUTTON_BG_COLOR};}}"
    f"QComboBox::drop-down:hover{{background:{BUTTON_HOVER_COLOR};border-color:{NODE_SELECTED_COLOR};}}"
    f"QComboBox QAbstractItemView{{border:1px solid {NODE_BORDER_COLOR};"
    f"background:{CANVAS_BACKGROUND_COLOR};color:{TEXT_COLOR};"
    f"selection-background-color:{NODE_SELECTED_COLOR};selection-color:{CANVAS_BACKGROUND_COLOR};outline:0px;}}"
    f"QComboBox QAbstractItemView::item:hover{{background-color:{NODE_SELECTED_COLOR};color:{CANVAS_BACKGROUND_COLOR};}}"
    f"QComboBox QAbstractItemView::item:selected{{background-color:{NODE_SELECTED_COLOR};color:{CANVAS_BACKGROUND_COLOR};}}"
    f"QScrollBar:vertical{{border:none;background:{CANVAS_BACKGROUND_COLOR};width:8px;margin:0px;}}"
    f"QScrollBar::handle:vertical{{background:{NODE_BORDER_COLOR};min-height:20px;border-radius:0px;}}"
    f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0px;}}"
    f"QComboBox[connected=\"true\"]{{color:{TEXT_MUTED_COLOR};}}"
    f"QComboBox[connected=\"true\"] QLineEdit{{color:{TEXT_MUTED_COLOR};}}"
    f"QComboBox[connected=\"true\"]::drop-down{{width:0px;border:none;}}"
)

_SPINBOX_QSS = (
    f"QSpinBox{{border:1px solid {NODE_BORDER_COLOR};background:{CANVAS_BACKGROUND_COLOR};"
    f"color:{TEXT_COLOR};border-radius:0px;padding:2px;font:9pt Consolas;}}"
    f"QSpinBox::up-button{{background:{BUTTON_BG_COLOR};"
    f"border-left:1px solid {NODE_BORDER_COLOR};"
    f"border-bottom:1px solid {NODE_BORDER_COLOR};width:16px;}}"
    f"QSpinBox::down-button{{background:{BUTTON_BG_COLOR};"
    f"border-left:1px solid {NODE_BORDER_COLOR};width:16px;}}"
    f"QSpinBox::up-button:hover,QSpinBox::down-button:hover{{"
    f"background:{BUTTON_HOVER_COLOR};border-color:{NODE_SELECTED_COLOR};}}"
    f"QSpinBox:hover{{border-color:{NODE_SELECTED_COLOR};}}"
)

_CHECKBOX_QSS = (
    f"QCheckBox{{font:9pt Consolas;color:{TEXT_COLOR};background:{BUTTON_BG_COLOR};spacing:6px;}}"
    f"QCheckBox::indicator{{width:13px;height:13px;"
    f"border:1px solid {NODE_BORDER_COLOR};background:{CANVAS_BACKGROUND_COLOR};}}"
    f"QCheckBox::indicator:checked{{background:{NODE_SELECTED_COLOR};border-color:{NODE_SELECTED_COLOR};}}"
    f"QCheckBox::indicator:hover{{border-color:{NODE_SELECTED_COLOR};}}"
)

_TOOLBTN_QSS = (
    f"QToolButton{{background:{BUTTON_BG_COLOR};color:{BUTTON_TEXT_COLOR};"
    f"border:1px solid {NODE_BORDER_COLOR};border-radius:0px;font:9pt Consolas;}}"
    f"QToolButton:hover{{background:{BUTTON_HOVER_COLOR};border-color:{NODE_SELECTED_COLOR};}}"
    f"QToolButton:pressed{{background:{BUTTON_PRESSED_COLOR};}}"
)

_PUSHBTN_QSS = (
    f"QPushButton{{background:{BUTTON_BG_COLOR};color:{BUTTON_TEXT_COLOR};"
    f"border:1px solid {NODE_BORDER_COLOR};border-radius:0px;"
    f"padding:5px 8px;font:bold 9pt Consolas;}}"
    f"QPushButton:hover{{background:{BUTTON_HOVER_COLOR};border-color:{NODE_SELECTED_COLOR};}}"
    f"QPushButton:pressed{{background:{BUTTON_PRESSED_COLOR};}}"
)

_VECTOR_TOGGLE_QSS = (
    f"QToolButton{{color:{TEXT_MUTED_COLOR};font:bold 8pt;padding:0px 2px;border:none;background:transparent;}}"
    f"QToolButton:hover{{color:{NODE_SELECTED_COLOR};}}"
)

_VECTOR_AXIS_LABEL_QSS = f"color:{VECTOR_AXIS_LABEL_COLOR};font:9pt Consolas;"


def resolve_color_schema(socket_type: str) -> dict:
    return SOCKET_COLOR_SCHEMA.get(socket_type.lower(), SOCKET_COLOR_SCHEMA["any"])


def param_spec_name(param) -> str:
    return param if isinstance(param, str) else param.get("name", "")


@dataclass
class SocketDef:
    name: str
    kind: str
    row: int = 0
    label: Optional[str] = None
    optional: bool = False
    color: str = SOCKET_COLOR_SCHEMA["any"]["socket"]
    is_exec: bool = False
    param_type: str = "string"
    values: List[str] = field(default_factory=list)
    is_collapsed_vector: bool = False
    is_expanded_vector_start: bool = False
    vector_base: str = ""


@dataclass
class NodeDef:
    title: str
    header_color: str
    body_color: str
    sockets: List[SocketDef] = field(default_factory=list)
    width: int = NODE_DEFAULT_WIDTH
    has_footer: bool = False
    extra_rows: float = 0.0

    @property
    def body_height(self) -> int:
        param_rows = [s.row for s in self.sockets if not s.is_exec]
        rows = max(param_rows, default=-1) + 1
        return int(NODE_HEADER_HEIGHT + (rows + self.extra_rows) * NODE_ROW_HEIGHT + (
            NODE_FOOTER_HEIGHT if self.has_footer else NODE_BOTTOM_PAD
        ))

    def socket_y(self, row: int, is_exec: bool = False) -> float:
        """Index-based Y centre. Exec sockets are vertically centered on the header."""
        if is_exec:
            return NODE_HEADER_HEIGHT / 2.0
        return NODE_HEADER_HEIGHT + row * NODE_ROW_HEIGHT + NODE_ROW_HEIGHT / 2.0

    def socket_x(self, kind: str) -> float:
        return 0.0 if kind == "input" else float(self.width)


class SocketItem(QGraphicsObject):
    """
    Single socket visual.
    is_exec=True  → diamond (blue), type-safe exec-only connections
    is_exec=False → circle  (colored), param-only connections
    Position set once from row-index arithmetic; never recomputed.
    """

    def __init__(self, sock_def: SocketDef, row: int,
                 node_def: NodeDef, parent: MetaNode):
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
        self.setZValue(-1)
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
            pass

    def paint(self, painter, option, widget=None):
        if option.state & QStyle.State_Selected:
            option.state &= ~QStyle.State_Selected
        self.setPen(self._pen_selected if self.isSelected() else self._pen)
        painter.setRenderHint(QPainter.Antialiasing)
        super().paint(painter, option, widget)


class _SelectionOverlay(QGraphicsItem):
    """Translucent-white wash above all node contents while selected."""

    def __init__(self, node: MetaNode):
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


class MetaNode(QGraphicsObject):
    """
    Declarative base. _generate() creates ALL children from NodeDef once.
    BoundingRect includes shadow area — prevents trail artifact on move.
    """

    def __init__(self, node_def: NodeDef):
        super().__init__()
        self.node_def = node_def
        self.sockets: Dict[str, SocketItem] = {}
        self._vector_buttons: Dict[str, tuple] = {}
        self.setFlags(
            QGraphicsItem.ItemIsMovable |
            QGraphicsItem.ItemIsSelectable |
            QGraphicsItem.ItemSendsScenePositionChanges,
        )
        self._generate()

    def _generate(self):
        d = self.node_def
        self._vector_buttons.clear()

        self._selection_overlay = _SelectionOverlay(self)

        self.title_item = self._build_title_item(d.title)
        self._center_title()

        for socket_def in d.sockets:
            socket = SocketItem(socket_def, socket_def.row, d, self)
            self.sockets[socket_def.name] = socket

            text_to_show = socket_def.name if socket_def.label is None else socket_def.label
            if text_to_show:
                label = QGraphicsTextItem(text_to_show, self)
                label.setFont(QFont("Consolas", 8))
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
                        toggle.setStyleSheet(_VECTOR_TOGGLE_QSS)
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

    def _build_title_item(self, html: str) -> QGraphicsTextItem:
        item = QGraphicsTextItem(self)
        item.setHtml(html)
        return item

    def _center_title(self):
        self.title_item.setPos(
            NODE_HORIZONTAL_PAD,
            (NODE_HEADER_HEIGHT - self.title_item.boundingRect().height()) / 2.0,
        )

    def boundingRect(self) -> QRectF:
        d = self.node_def
        return QRectF(
            0, 0,
            d.width       + NODE_SHADOW_OFFSET_X + NODE_SHADOW_BLUR,
            d.body_height + NODE_SHADOW_OFFSET_Y + NODE_SHADOW_BLUR,
        )

    def paint(self, painter: QPainter, option, widget=None):
        if option.state & QStyle.State_Selected:
            option.state &= ~QStyle.State_Selected
        painter.setRenderHint(QPainter.Antialiasing)
        d = self.node_def

        painter.setPen(
            QPen(QColor(NODE_SELECTED_COLOR), 2.0) if self.isSelected()
            else QPen(QColor(NODE_BORDER_COLOR), 1.0)
        )
        painter.setBrush(QBrush(QColor(d.body_color)))
        painter.drawRect(QRectF(0, 0, d.width, d.body_height))

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(d.header_color)))
        painter.drawRect(QRectF(0, 0, d.width, NODE_HEADER_HEIGHT))

        painter.setPen(QPen(QColor(NODE_BORDER_COLOR), 1))
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
            self._selection_overlay.setVisible(bool(value))
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if scene:
            scene.recalculate_scene_rect()
        if not scene or not hasattr(scene, 'nodeEditorWindow'): return
        win = scene.nodeEditorWindow
        if not win: return

        has_connections = any(
            c.source.meta_node is self or c.dest.meta_node is self
            for c in win.connections
        )
        if has_connections: return

        for item in self.collidingItems():
            if isinstance(item, Connection):
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

                    scene._enforce_connection_rules(conn.source, in_sock)
                    conn1 = Connection(conn.source, in_sock)
                    scene.addItem(conn1)
                    win.connections.append(conn1)

                    scene._enforce_connection_rules(out_sock, conn.dest)
                    conn2 = Connection(out_sock, conn.dest)
                    scene.addItem(conn2)
                    win.connections.append(conn2)

                    self._refresh_connections()
                    conn.source.meta_node._refresh_connections()
                    conn.dest.meta_node._refresh_connections()
                    win.push_undo_state()
                    break

    def _refresh_connections(self):
        scene = self.scene()
        if not scene:
            return
        for item in scene.items():
            if isinstance(item, Connection):
                if (item.source and item.source.meta_node is self) or \
                   (item.dest   and item.dest.meta_node   is self):
                    item.refresh()
        self.update_vector_buttons_visibility()

    def _is_vector_connected(self, base_name: str) -> bool:
        scene = self.scene()
        win = getattr(scene, 'nodeEditorWindow', None) if scene else None
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
        pass

    def get_socket(self, name: str) -> Optional[SocketItem]:
        return self.sockets.get(name)


class NodeComboBox(QComboBox):
    def __init__(self, node: MetaNode):
        super().__init__()
        self.node = node

    def showPopup(self):
        self.node.setZValue(NODE_POPUP_Z)
        super().showPopup()

    def hidePopup(self):
        super().hidePopup()
        self.node.setZValue(0)


class _EditableTitleItem(QGraphicsTextItem):
    """Header title that edits in place; commits on Enter/focus-out, reverts on Esc."""

    def __init__(self, node: _BaseParamNode):
        super().__init__(node)
        self._node = node

    def paint(self, painter: QPainter, option, widget=None):
        if self.textInteractionFlags() != Qt.NoTextInteraction:
            painter.fillRect(
                self.boundingRect().adjusted(-2, -1, 2, 1),
                QColor(self._node.node_def.header_color),
            )
        super().paint(painter, option, widget)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._node._commit_rename()
            event.accept()
        elif event.key() == Qt.Key_Escape:
            self._node._cancel_rename()
            event.accept()
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._node._commit_rename()


class _BaseParamNode(MetaNode):
    def __init__(self, node_def: NodeDef):
        super().__init__(node_def)
        self._update_scheduled = False

    def _build_title_item(self, html: str) -> QGraphicsTextItem:
        item = _EditableTitleItem(self)
        item.setHtml(html)
        return item

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._begin_rename()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def _begin_rename(self):
        item = self.title_item
        self._rename_backup = item.toPlainText()
        item.setDefaultTextColor(QColor(TEXT_COLOR))
        item.setFont(QFont("Consolas", 9))
        item.setPlainText(self._rename_backup)
        item.setZValue(NODE_SOCKET_Z)
        item.setTextInteractionFlags(Qt.TextEditorInteraction)
        item.setFocus(Qt.MouseFocusReason)
        cursor = item.textCursor()
        cursor.select(QTextCursor.Document)
        item.setTextCursor(cursor)

    def _end_rename(self) -> bool:
        item = self.title_item
        if item.textInteractionFlags() == Qt.NoTextInteraction:
            return False
        item.setTextInteractionFlags(Qt.NoTextInteraction)
        item.setZValue(0)
        return True

    def _commit_rename(self):
        if not self._end_rename():
            return
        name = self.title_item.toPlainText().strip() or self._rename_backup
        self._apply_title(name)
        creation_data = dict(getattr(self, "creation_data", {}) or {})
        creation_data.setdefault("param_type", self.TYPE_ID)
        creation_data["display"] = name
        self.creation_data = creation_data
        scene = self.scene()
        win = getattr(scene, 'nodeEditorWindow', None) if scene else None
        if win:
            win.push_undo_state()

    def _cancel_rename(self):
        if not self._end_rename():
            return
        self._apply_title(self._rename_backup)

    def _apply_title(self, text: str):
        self.title_item.setHtml(_html_title(text))
        self._center_title()

    def itemChange(self, change, value):
        result = super().itemChange(change, value)
        if change == QGraphicsItem.ItemSceneHasChanged and not self._update_scheduled:
            self._update_scheduled = True
            QTimer.singleShot(100, self._on_scene_loaded)
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self._apply_widget_selection_tint(bool(value))
        return result

    def _apply_widget_selection_tint(self, selected: bool):
        """Blend all embedded QWidgets toward white when node is selected."""
        for child in self.childItems():
            if not hasattr(child, 'widget'):
                continue
            w = child.widget()
            if w is None:
                continue
            self._tint_widget(w, False)

    def _tint_widget(self, w: QWidget, selected: bool):
        from PyQt5.QtWidgets import QAbstractButton, QAbstractSpinBox
        T = 0.18

        def blended(hex_color: str) -> str:
            c = QColor(hex_color)
            r = int(c.red()   + (255 - c.red())   * T)
            g = int(c.green() + (255 - c.green()) * T)
            b = int(c.blue()  + (255 - c.blue())  * T)
            return f"#{r:02X}{g:02X}{b:02X}"

        if selected:
            bg_field  = blended(CANVAS_BACKGROUND_COLOR)
            bg_button = blended(BUTTON_BG_COLOR)
        else:
            bg_field  = CANVAS_BACKGROUND_COLOR
            bg_button = BUTTON_BG_COLOR

        if isinstance(w, QLineEdit):
            w.setStyleSheet(_FIELD_QSS.replace(CANVAS_BACKGROUND_COLOR, bg_field))
        elif isinstance(w, QComboBox):
            w.setStyleSheet(_COMBOBOX_QSS.replace(CANVAS_BACKGROUND_COLOR, bg_field)
                                         .replace(BUTTON_BG_COLOR, bg_button))
        elif isinstance(w, QAbstractSpinBox):
            w.setStyleSheet(_SPINBOX_QSS.replace(CANVAS_BACKGROUND_COLOR, bg_field)
                                        .replace(BUTTON_BG_COLOR, bg_button))
        elif isinstance(w, QCheckBox):
            pass

        elif isinstance(w, (QToolButton, QAbstractButton)):
            w.setStyleSheet(_TOOLBTN_QSS.replace(BUTTON_BG_COLOR, bg_button))
        else:
            for child in w.findChildren(QWidget):
                self._tint_widget(child, selected)

    def _on_scene_loaded(self):
        self._update_scheduled = False
        self._update_connected_values()

    def _widget_width(self) -> int:
        return self.node_def.width - NODE_HORIZONTAL_PAD * 2 - 4

    def _make_field(self, text: str = "", placeholder: str = "", *,
                    fixed_width: bool = True) -> QLineEdit:
        w = QLineEdit(text)
        if placeholder:
            w.setPlaceholderText(placeholder)
        if fixed_width:
            w.setFixedWidth(self._widget_width())
        w.setFixedHeight(NODE_WIDGET_HEIGHT)
        w.setStyleSheet(_FIELD_QSS)
        return w

    def _make_combobox(self, items: List[str] = None, *,
                       fixed_width: bool = True, editable: bool = True) -> QComboBox:
        w = NodeComboBox(self)
        w.setEditable(editable)
        for item in (items or []):
            w.addItem(item)
        if fixed_width:
            w.setFixedWidth(self._widget_width())
        w.setFixedHeight(NODE_WIDGET_HEIGHT)
        w.setStyleSheet(_COMBOBOX_QSS)
        pal = w.palette()
        pal.setColor(QPalette.ButtonText, QColor(TEXT_COLOR))
        w.setPalette(pal)
        return w

    def _make_spinbox(self, lo: int = -999999, hi: int = 999999,
                      value: int = 0) -> QSpinBox:
        w = QSpinBox()
        w.setRange(lo, hi)
        w.setValue(value)
        w.setFixedWidth(self._widget_width())
        w.setFixedHeight(NODE_WIDGET_HEIGHT)
        w.setStyleSheet(_SPINBOX_QSS)
        pal = w.palette()
        pal.setColor(QPalette.ButtonText, QColor(TEXT_COLOR))
        w.setPalette(pal)
        return w

    def _make_checkbox(self, text: str = "true", checked: bool = False) -> QCheckBox:
        w = QCheckBox(text)
        w.setChecked(checked)
        w.setFixedWidth(self._widget_width())
        w.setFixedHeight(NODE_WIDGET_HEIGHT)
        w.setStyleSheet(_CHECKBOX_QSS)
        return w

    def _make_toolbtn(self, text: str, callback=None) -> QToolButton:
        w = QToolButton()
        w.setText(text)
        w.setStyleSheet(_TOOLBTN_QSS)
        w.setFixedWidth(BROWSE_BTN_WIDTH)
        w.setFixedHeight(NODE_WIDGET_HEIGHT)
        if callback:
            w.clicked.connect(callback)
        return w

    def _get_connected_input_value(self, socket_name: str) -> Optional[str]:
        sock = self.get_socket(socket_name)
        if not sock or not self.scene():
            return None
        win = getattr(self.scene(), 'nodeEditorWindow', None)
        if not win:
            return None
        for conn in win.connections:
            if conn.dest is sock:
                return conn.source.meta_node.get_value(conn.source.sock_def.name)
        return None

    def _show_connected_value(self, line_edit: QLineEdit, value: Optional[str]):
        if value:
            line_edit.blockSignals(True)
            line_edit.setText(value)
            line_edit.setReadOnly(True)
            line_edit.blockSignals(False)
        else:
            line_edit.setReadOnly(False)

    def _show_connected_combobox(self, combo: QComboBox, value: Optional[str]):
        if value:
            combo.blockSignals(True)
            combo.setCurrentText(value)
            if combo.lineEdit():
                combo.lineEdit().setReadOnly(True)
            combo.setFocusPolicy(Qt.NoFocus)
            combo.setProperty("connected", "true")
            combo.style().unpolish(combo)
            combo.style().polish(combo)
            combo.blockSignals(False)
        else:
            if combo.lineEdit():
                combo.lineEdit().setReadOnly(False)
            combo.setFocusPolicy(Qt.StrongFocus)
            combo.setProperty("connected", "false")
            combo.style().unpolish(combo)
            combo.style().polish(combo)

    def _notify_connections_changed(self, *args):
        self._propagate_connections_changed(set())
        self._broadcast_to_linked_peers()

    _broadcasting: bool = False

    def _editor_window(self) -> Optional[Any]:
        scene = self.scene()
        return getattr(scene, "nodeEditorWindow", None) if scene else None

    def _watch_field_focus(self, widget: QWidget):
        from PyQt5.QtWidgets import QAbstractButton
        for w in (widget, *widget.findChildren(QWidget)):
            if isinstance(w, (QLineEdit, QComboBox, QAbstractSpinBox, QAbstractButton)):
                w.installEventFilter(self)

    def _owns_widget(self, widget: Optional[QWidget]) -> bool:
        if widget is None:
            return False
        for child in self.childItems():
            if isinstance(child, QGraphicsProxyWidget):
                w = child.widget()
                if w is not None and (w is widget or w.isAncestorOf(widget)):
                    return True
        return False

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.FocusIn, QEvent.MouseButtonPress):
            win = self._editor_window()
            if win:
                counter = getattr(win, '_focus_event_counter', 0) + 1
                win._focus_event_counter = counter
                for child in self.childItems():
                    if isinstance(child, QGraphicsProxyWidget):
                        w = child.widget()
                        if w is not None and (w is obj or w.isAncestorOf(obj)):
                            active_key = getattr(child, '_field_key', None)
                            if active_key is not None:
                                win._active_field_key = active_key
                            break
            self._enter_linked_editing()
        elif event.type() == QEvent.FocusOut:
            win = self._editor_window()
            ct = getattr(win, '_focus_event_counter', 0) if win else 0
            QTimer.singleShot(0, lambda: self._exit_linked_editing_if_focus_left(ct))
        return super().eventFilter(obj, event)

    def _enter_linked_editing(self):
        win   = self._editor_window()
        scene = self.scene()
        if not win or not scene:
            return
        same_type = [
            n for n in scene.selectedItems()
            if isinstance(n, _BaseParamNode) and n.TYPE_ID == self.TYPE_ID
        ]
        group = same_type if self in same_type else [self, *same_type]
        if set(win._linked_group) == set(group):
            for node in win._linked_group:
                if node.scene():
                    node._adjust_proxy_z_values()
            return
        
        saved_key = getattr(win, '_active_field_key', None)
        self._dissolve_linked_group()
        win._active_field_key = saved_key
        
        win._linked_group = group
        for node in group:
            node._set_selection_effect(False)

    def _exit_linked_editing_if_focus_left(self, queued_ct: int):
        win = self._editor_window()
        if not win or not win._linked_group:
            return
        if self not in win._linked_group:
            return
        current_ct = getattr(win, '_focus_event_counter', 0)
        if current_ct > queued_ct:
            return
        focused = QApplication.focusWidget()
        if any(n.scene() and n._owns_widget(focused) for n in win._linked_group):
            return
        self._dissolve_linked_group()

    def _dissolve_linked_group(self):
        win = self._editor_window()
        if not win or not win._linked_group:
            return
        win._active_field_key = None
        group, win._linked_group = win._linked_group, []
        for node in group:
            if node.scene():
                node._set_selection_effect(node.isSelected())
        win.push_undo_state()

    def _set_selection_effect(self, on: bool):
        self._selection_overlay.setVisible(self.isSelected())
        self._apply_widget_selection_tint(on)
        self._adjust_proxy_z_values()

    def _adjust_proxy_z_values(self):
        win = self._editor_window()
        is_edited = win is not None and self in win._linked_group
        active_key = getattr(win, '_active_field_key', None) if is_edited else None

        for child in self.childItems():
            if isinstance(child, QGraphicsProxyWidget):
                child_key = getattr(child, '_field_key', None)
                if is_edited and active_key is not None and child_key == active_key:
                    if not hasattr(child, '_original_z_value'):
                        child._original_z_value = child.zValue()
                    child.setZValue(2500)
                    child.update()
                else:
                    if hasattr(child, '_original_z_value'):
                        child.setZValue(child._original_z_value)
                        child.update()
        
        self.update()
        if hasattr(self, '_selection_overlay'):
            self._selection_overlay.update()

    def _broadcast_to_linked_peers(self):
        if _BaseParamNode._broadcasting:
            return
        win = self._editor_window()
        if not win or self not in win._linked_group:
            return
        active_key = getattr(win, '_active_field_key', None)
        _BaseParamNode._broadcasting = True
        try:
            for peer in win._linked_group:
                if peer is not self and peer.scene():
                    peer._apply_linked_sync(self, active_key)
        finally:
            _BaseParamNode._broadcasting = False

    def _apply_linked_sync(self, source_node: _BaseParamNode, active_key: Optional[str]):
        self.set_value_state(source_node.get_value_state())

    def _propagate_connections_changed(self, visited):
        if self in visited:
            return
        visited.add(self)
        scene = self.scene()
        win = getattr(scene, 'nodeEditorWindow', None) if scene else None
        if not win:
            return
        for conn in win.connections:
            if conn.source.meta_node is self:
                dest_node = conn.dest.meta_node
                if hasattr(dest_node, "_update_connected_values"):
                    dest_node._update_connected_values()
                    dest_node._propagate_connections_changed(visited)

    def _update_connected_values(self):
        pass

    def _on_widget_user_edit(self):
        scene = self.scene()
        win = getattr(scene, 'nodeEditorWindow', None) if scene else None
        if win:
            win.push_undo_state()

    def _format_float_input(self, line_edit: QLineEdit):
        text = line_edit.text().strip()
        if not text:
            return
        try:
            val = float(text.replace(",", "."))
            if "." not in text and "e" not in text.lower():
                line_edit.setText(f"{int(val)}.0")
            elif text.endswith("."):
                line_edit.setText(text + "0")
        except ValueError:
            pass

    def _on_float_editing_finished(self):
        sender = self.sender()
        if isinstance(sender, QLineEdit):
            self._format_float_input(sender)
        self._on_widget_user_edit()

    def _refresh_connections(self):
        super()._refresh_connections()
        self._update_connected_values()

    def _attach_widget_at_row(self, widget: QWidget, row: int):
        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(widget)
        proxy.setPos(
            NODE_HORIZONTAL_PAD,
            NODE_HEADER_HEIGHT + row * NODE_ROW_HEIGHT + NODE_WIDGET_V_OFFSET,
        )
        proxy.setZValue(NODE_WIDGET_Z_BASE - row)
        proxy._field_key = f"row_{row}"
        self._watch_field_focus(widget)

    def _attach_input_widget(self, widget: QWidget):
        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(widget)
        param_rows = [s.row for s in self.node_def.sockets if not s.is_exec]
        rows = max(param_rows, default=-1) + 1
        proxy.setPos(
            NODE_HORIZONTAL_PAD,
            NODE_HEADER_HEIGHT + rows * NODE_ROW_HEIGHT + NODE_WIDGET_V_OFFSET,
        )
        proxy.setZValue(NODE_WIDGET_Z_BASE - rows)
        proxy._field_key = f"row_{rows}"
        self._watch_field_focus(widget)

    def get_value_state(self) -> Any:
        return None

    def set_value_state(self, val: Any):
        pass

    def get_value(self, socket_name: str = None) -> str:
        raise NotImplementedError


class _VectorParamNode(_BaseParamNode):
    AXES: tuple = ()

    def __init__(self, param_name: str):
        super().__init__(_param_node_def(param_name, self.TYPE_ID))

        param_rows = [s.row for s in self.node_def.sockets if not s.is_exec]
        rows = max(param_rows, default=-1) + 1

        total_w = self._widget_width()
        n_axes = len(self.AXES)
        spacing = 4
        col_w = int((total_w - spacing * (n_axes - 1)) / n_axes)

        self._editors: List[QLineEdit] = []
        for i, axis in enumerate(self.AXES):
            cell_widget = QWidget()
            cell_widget.setStyleSheet("background:transparent;")
            layout = QHBoxLayout(cell_widget)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(2)

            editor = self._make_field("0.0", axis.lower(), fixed_width=False)
            editor.setValidator(QDoubleValidator())
            editor.textChanged.connect(self._notify_connections_changed)
            editor.editingFinished.connect(self._on_float_editing_finished)

            label = QLabel(f"{axis}:")
            label.setStyleSheet(_VECTOR_AXIS_LABEL_QSS)

            layout.addWidget(label)
            layout.addWidget(editor)
            self._editors.append(editor)

            cell_widget.setFixedWidth(col_w)

            proxy = QGraphicsProxyWidget(self)
            proxy.setWidget(cell_widget)
            proxy.setPos(
                NODE_HORIZONTAL_PAD + i * (col_w + spacing),
                NODE_HEADER_HEIGHT + rows * NODE_ROW_HEIGHT + NODE_WIDGET_V_OFFSET,
            )
            proxy.setZValue(NODE_WIDGET_Z_BASE - rows)
            proxy._field_key = f"vector_{axis}"

            self._watch_field_focus(cell_widget)

    def get_value_state(self) -> Any:
        return [editor.text() for editor in self._editors]

    def set_value_state(self, val: Any):
        if isinstance(val, list):
            for editor, component in zip(self._editors, val):
                editor.setText(str(component))

    def _apply_linked_sync(self, source_node: _BaseParamNode, active_key: Optional[str]):
        if active_key and active_key.startswith("vector_"):
            axis = active_key.split("_")[1]
            try:
                idx = self.AXES.index(axis)
                if hasattr(source_node, '_editors') and idx < len(source_node._editors):
                    self._editors[idx].setText(source_node._editors[idx].text())
                return
            except ValueError:
                pass
        self.set_value_state(source_node.get_value_state())

    def get_value(self, socket_name: str = None) -> str:
        return " ".join(editor.text().strip() or "0.0" for editor in self._editors)


def _html_title(text: str, bold_first: bool = False) -> str:
    parts = text.split(" ", 1)
    first = f"<b>{parts[0]}</b>" if bold_first and parts else parts[0] if parts else ""
    rest  = f" {parts[1]}" if len(parts) > 1 else ""
    return (f'<span style="font-family:Consolas;font-size:9pt;color:white;">'
            f'{first}{rest}</span>')


def _param_node_def(label: str, param_type: str, width: int = 200) -> NodeDef:
    schema = resolve_color_schema(param_type)
    return NodeDef(
        title=_html_title(label),
        header_color=schema["hdr"],
        body_color=schema["body"],
        sockets=[SocketDef(
            "value_out", "output", row=0, label=f"{param_type}",
            color=schema["socket"], param_type=param_type,
        )],
        width=width,
        has_footer=True,
    )
