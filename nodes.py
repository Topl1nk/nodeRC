"""
nodes.py — Declarative Meta-Node Architecture
• SocketItem draws diamond (exec) or circle (param) — single unified class
• All child positions computed from index arithmetic in NodeDef (zero positional drift)
• BoundingRect expanded by shadow offset — prevents trail artifact on move
• Typed ParameterNodes: String, Bool, Int, Enum, FilePath, DirPath, KeyValue
• Exec connections only connect to exec sockets; param to param (type-safe)
"""

from __future__ import annotations
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Dict, Optional, TYPE_CHECKING

from PyQt5.QtWidgets import (
    QGraphicsObject, QGraphicsItem, QGraphicsTextItem,
    QGraphicsProxyWidget, QPushButton, QLineEdit, QCheckBox,
    QSpinBox, QComboBox, QGraphicsPathItem, QWidget,
    QHBoxLayout, QToolButton, QFileDialog, QStyle,
)
from PyQt5.QtGui import (
    QPen, QBrush, QColor, QPainterPath, QFont, QPainter, QPolygonF,
    QDoubleValidator, QPalette,
)
from PyQt5.QtCore import QRectF, Qt, QPointF

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
)

if TYPE_CHECKING:
    from canvas import NodeEditorWindow


# ── Widget QSS primitives (single source for every embedded widget) ────────────

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
    f"color:{TEXT_COLOR};border-radius:0px;padding:2px 4px;font:9pt Consolas;}}"
    f"QComboBox::drop-down{{border-left:1px solid {NODE_BORDER_COLOR};"
    f"width:{BROWSE_BTN_WIDTH}px;background:{BUTTON_BG_COLOR};}}"
    f"QComboBox::drop-down:hover{{background:{BUTTON_HOVER_COLOR};border-color:{NODE_SELECTED_COLOR};}}"
    f"QComboBox QAbstractItemView{{border:1px solid {NODE_BORDER_COLOR};"
    f"background:{CANVAS_BACKGROUND_COLOR};color:{TEXT_COLOR};"
    f"selection-background-color:{BUTTON_HOVER_COLOR};selection-color:{TEXT_COLOR};outline:0px;}}"
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


def resolve_color_schema(socket_type: str) -> dict:
    return SOCKET_COLOR_SCHEMA.get(socket_type.lower(), SOCKET_COLOR_SCHEMA["any"])


# ── Schema ────────────────────────────────────────────────────────────────────

@dataclass
class SocketDef:
    name: str
    kind: str               # "input" | "output"
    row: int = 0
    label: Optional[str] = None
    optional: bool = False
    color: str = SOCKET_COLOR_SCHEMA["any"]["socket"]
    is_exec: bool = False
    param_type: str = "string"
    values: List[str] = field(default_factory=list)


@dataclass
class NodeDef:
    title: str              # HTML-capable string
    header_color: str
    body_color: str
    sockets: List[SocketDef] = field(default_factory=list)
    width: int = NODE_DEFAULT_WIDTH
    has_footer: bool = False

    @property
    def body_height(self) -> int:
        param_rows = [s.row for s in self.sockets if not s.is_exec]
        rows = max(param_rows, default=-1) + 1
        return NODE_HEADER_HEIGHT + rows * NODE_ROW_HEIGHT + (
            NODE_FOOTER_HEIGHT if self.has_footer else NODE_BOTTOM_PAD
        )

    def socket_y(self, row: int, is_exec: bool = False) -> float:
        """Index-based Y centre. Exec sockets are vertically centered on the header."""
        if is_exec:
            return NODE_HEADER_HEIGHT / 2.0
        return NODE_HEADER_HEIGHT + row * NODE_ROW_HEIGHT + NODE_ROW_HEIGHT / 2.0

    def socket_x(self, kind: str) -> float:
        return 0.0 if kind == "input" else float(self.width)


# ── SocketItem ────────────────────────────────────────────────────────────────

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
        self.meta_node: "MetaNode" = parent
        self._radius  = NODE_EXEC_SOCKET_HALFSIZE if sock_def.is_exec else NODE_PARAM_SOCKET_RADIUS
        self._hovered = False

        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self.setAcceptHoverEvents(True)
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


# ── Connection ────────────────────────────────────────────────────────────────

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
            # Qt C++ object may be deleted before Python GC — safe to ignore
            pass

    def paint(self, painter, option, widget=None):
        if option.state & QStyle.State_Selected:
            option.state &= ~QStyle.State_Selected
        self.setPen(self._pen_selected if self.isSelected() else self._pen)
        painter.setRenderHint(QPainter.Antialiasing)
        super().paint(painter, option, widget)


# ── MetaNode ──────────────────────────────────────────────────────────────────

class MetaNode(QGraphicsObject):
    """
    Declarative base. _generate() creates ALL children from NodeDef once.
    BoundingRect includes shadow area — prevents trail artifact on move.
    """

    def __init__(self, node_def: NodeDef):
        super().__init__()
        self.node_def = node_def
        self.sockets: Dict[str, SocketItem] = {}
        self.setFlags(
            QGraphicsItem.ItemIsMovable |
            QGraphicsItem.ItemIsSelectable |
            QGraphicsItem.ItemSendsScenePositionChanges,
        )
        self._generate()

    def _generate(self):
        d = self.node_def

        title_item = QGraphicsTextItem(self)
        title_item.setHtml(d.title)
        title_item.setPos(
            NODE_HORIZONTAL_PAD,
            (NODE_HEADER_HEIGHT - title_item.boundingRect().height()) / 2.0,
        )

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
                    label.setPos(NODE_EXEC_SOCKET_HALFSIZE * 2 + 5, label_y)
                else:
                    label.setPos(d.width - NODE_EXEC_SOCKET_HALFSIZE * 2 - 5 - label_width, label_y)

                label.setDefaultTextColor(QColor(socket_def.color))

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
        d    = self.node_def
        body = QRectF(0, 0, d.width, d.body_height)

        painter.setPen(
            QPen(QColor(NODE_SELECTED_COLOR), 2.0) if self.isSelected()
            else QPen(QColor(NODE_BORDER_COLOR), 1.0)
        )
        painter.setBrush(QBrush(QColor(d.body_color)))
        painter.drawRect(body)

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
            self.scene().recalculate_scene_rect()
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        scene = self.scene()
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

    def get_socket(self, name: str) -> Optional[SocketItem]:
        return self.sockets.get(name)


# ── NodeDef factories ─────────────────────────────────────────────────────────

def _html_title(text: str, bold_first: bool = False) -> str:
    parts = text.split(" ", 1)
    first = f"<b>{parts[0]}</b>" if bold_first and parts else parts[0] if parts else ""
    rest  = f" {parts[1]}" if len(parts) > 1 else ""
    return (f'<span style="font-family:Consolas;font-size:9pt;color:white;">'
            f'{first}{rest}</span>')


def _start_node_def() -> NodeDef:
    exec_schema = resolve_color_schema("exec")
    return NodeDef(
        title=_html_title("> START"),
        header_color=exec_schema["hdr"],
        body_color=exec_schema["body"],
        sockets=[SocketDef(
            "exec_out", "output", row=-1, label="",
            color=exec_schema["socket"], is_exec=True,
        )],
        width=185,
        has_footer=True,
    )


def _command_node_def(cmd_def: dict) -> NodeDef:
    display = cmd_def.get("display", cmd_def.get("command", ""))
    exec_schema = resolve_color_schema("exec")
    sockets: List[SocketDef] = [
        SocketDef("__exec_in__",  "input",  row=-1, label="", color=exec_schema["socket"], is_exec=True),
        SocketDef("__exec_out__", "output", row=-1, label="", color=exec_schema["socket"], is_exec=True),
    ]
    row_idx = 0
    for p in cmd_def.get("required", []):
        name   = p if isinstance(p, str) else p["name"]
        ptype  = "string" if isinstance(p, str) else p.get("type", "string")
        values = [] if isinstance(p, str) else p.get("values", [])
        sockets.append(SocketDef(
            name, "input", row=row_idx, label=name, optional=False,
            color=resolve_color_schema(ptype)["socket"], param_type=ptype, values=values,
        ))
        if name.startswith("new"):
            sockets.append(SocketDef(
                f"{name}_out", "output", row=row_idx, label="", optional=False,
                color=resolve_color_schema(ptype)["socket"], param_type=ptype, values=values,
            ))
        row_idx += 1
    for p in cmd_def.get("optional", []):
        name   = p if isinstance(p, str) else p["name"]
        ptype  = "string" if isinstance(p, str) else p.get("type", "string")
        values = [] if isinstance(p, str) else p.get("values", [])
        sockets.append(SocketDef(
            name, "input", row=row_idx, label=f"{name}  (opt)", optional=True,
            color=resolve_color_schema(ptype)["socket"], param_type=ptype, values=values,
        ))
        if name.startswith("new"):
            sockets.append(SocketDef(
                f"{name}_out", "output", row=row_idx, label="", optional=True,
                color=resolve_color_schema(ptype)["socket"], param_type=ptype, values=values,
            ))
        row_idx += 1
    return NodeDef(
        title=_html_title(display, bold_first=True),
        header_color=exec_schema["hdr"],
        body_color=exec_schema["body"],
        sockets=sockets,
        width=235,
    )


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


# ── Concrete Nodes ────────────────────────────────────────────────────────────

class StartNode(MetaNode):
    def __init__(self):
        super().__init__(_start_node_def())
        launch_button = QPushButton("> Launch")
        launch_button.setStyleSheet(_PUSHBTN_QSS)
        launch_button.clicked.connect(self._request_chain_execution)
        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(launch_button)
        param_rows = [s.row for s in self.node_def.sockets if not s.is_exec]
        rows = max(param_rows, default=-1) + 1
        proxy.setPos(
            NODE_HORIZONTAL_PAD,
            NODE_HEADER_HEIGHT + rows * NODE_ROW_HEIGHT + NODE_WIDGET_V_OFFSET,
        )

    def _request_chain_execution(self):
        scene = self.scene()
        if scene and scene.nodeEditorWindow:
            scene.nodeEditorWindow.execute_chain()


class CommandNode(MetaNode):
    def __init__(self, cmd_def: dict):
        self.cmd_def = cmd_def
        super().__init__(_command_node_def(cmd_def))


# ── Typed Parameter Nodes ─────────────────────────────────────────────────────

class _BaseParamNode(MetaNode):
    def __init__(self, node_def: NodeDef):
        super().__init__(node_def)
        self._update_scheduled = False

    def itemChange(self, change, value):
        result = super().itemChange(change, value)
        if change == QGraphicsItem.ItemSceneHasChanged and not self._update_scheduled:
            self._update_scheduled = True
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(100, self._on_scene_loaded)
        return result

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
                       fixed_width: bool = True) -> QComboBox:
        w = QComboBox()
        w.setEditable(True)
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
        for conn in self.scene().nodeEditorWindow.connections:
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

    def _propagate_connections_changed(self, visited):
        if self in visited:
            return
        visited.add(self)
        scene = self.scene()
        if not scene or not scene.nodeEditorWindow:
            return
        for conn in scene.nodeEditorWindow.connections:
            if conn.source.meta_node is self:
                dest_node = conn.dest.meta_node
                if hasattr(dest_node, "_update_connected_values"):
                    dest_node._update_connected_values()
                    dest_node._propagate_connections_changed(visited)

    def _update_connected_values(self):
        """Override in subclasses to update UI when connections change"""
        pass

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
        proxy.setZValue(1000 - row)

    def _attach_input_widget(self, widget: QWidget):
        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(widget)
        param_rows = [s.row for s in self.node_def.sockets if not s.is_exec]
        rows = max(param_rows, default=-1) + 1
        proxy.setPos(
            NODE_HORIZONTAL_PAD,
            NODE_HEADER_HEIGHT + rows * NODE_ROW_HEIGHT + NODE_WIDGET_V_OFFSET,
        )

    def get_value(self, socket_name: str = None) -> str:
        raise NotImplementedError


class StringParamNode(_BaseParamNode):
    TYPE_ID = "string"

    def __init__(self, param_name="[S] String", default=""):
        super().__init__(_param_node_def(param_name, self.TYPE_ID))
        self._editor = self._make_field(default, "text value...")
        self._editor.textChanged.connect(self._notify_connections_changed)
        self._attach_input_widget(self._editor)

    def get_value(self, socket_name: str = None) -> str:
        return self._editor.text().strip()


class BoolParamNode(_BaseParamNode):
    TYPE_ID = "bool"

    def __init__(self, param_name="[B] Boolean", default=False):
        super().__init__(_param_node_def(param_name, self.TYPE_ID))
        self._checkbox = self._make_checkbox("true", default)
        self._checkbox.toggled.connect(
            lambda checked: self._checkbox.setText("true" if checked else "false")
        )
        self._checkbox.toggled.connect(self._notify_connections_changed)
        self._attach_input_widget(self._checkbox)

    def get_value(self, socket_name: str = None) -> str:
        return "true" if self._checkbox.isChecked() else "false"


class IntParamNode(_BaseParamNode):
    TYPE_ID = "integer"

    def __init__(self, param_name="[I] Integer", default=0):
        super().__init__(_param_node_def(param_name, self.TYPE_ID))
        self._spinbox = self._make_spinbox(-999999, 999999, default)
        self._spinbox.valueChanged.connect(self._notify_connections_changed)
        self._attach_input_widget(self._spinbox)

    def get_value(self, socket_name: str = None) -> str:
        return str(self._spinbox.value())


class FloatParamNode(_BaseParamNode):
    TYPE_ID = "float"

    def __init__(self, param_name="[#] Float", default=0.0):
        super().__init__(_param_node_def(param_name, self.TYPE_ID))
        self._editor = self._make_field(str(default))
        self._editor.setValidator(QDoubleValidator())
        self._editor.textChanged.connect(self._notify_connections_changed)
        self._attach_input_widget(self._editor)

    def get_value(self, socket_name: str = None) -> str:
        return self._editor.text().strip()


class EnumParamNode(_BaseParamNode):
    TYPE_ID = "enum"

    def __init__(self, param_name="[E] Enum", values=None):
        schema        = resolve_color_schema("enum")
        string_schema = resolve_color_schema("string")
        node_def = NodeDef(
            title=_html_title(param_name),
            header_color=schema["hdr"],
            body_color=schema["body"],
            sockets=[
                SocketDef("src", "input", row=1, label="",
                          color=string_schema["socket"], param_type="string",
                          optional=True),
                SocketDef("value_out", "output", row=1, label="",
                          color=schema["socket"], param_type="string"),
            ],
            has_footer=False,
        )
        super().__init__(node_def)

        self._new_item = self._make_field(placeholder="new item…", fixed_width=False)
        self._add_btn = self._make_toolbtn("+", self._add_enum_item)
        self._remove_btn = self._make_toolbtn("−", self._remove_enum_item)
        editor_row = QWidget()
        editor_row.setStyleSheet("background:transparent;")
        editor_layout = QHBoxLayout(editor_row)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(3)
        editor_layout.addWidget(self._new_item)
        editor_layout.addWidget(self._add_btn)
        editor_layout.addWidget(self._remove_btn)
        editor_row.setFixedWidth(self._widget_width())
        self._attach_widget_at_row(editor_row, 0)

        self._combobox = self._make_combobox(values or ["option1", "option2"])
        self._combobox.currentTextChanged.connect(self._notify_connections_changed)
        self._attach_widget_at_row(self._combobox, 1)

    def _add_enum_item(self):
        text = self._new_item.text().strip()
        if text and self._combobox.findText(text) == -1:
            self._combobox.addItem(text)
            self._combobox.setCurrentText(text)
            self._new_item.clear()

    def _remove_enum_item(self):
        idx = self._combobox.currentIndex()
        if idx >= 0:
            self._combobox.removeItem(idx)

    def _populate_from_source(self, source: str):
        if not source:
            return
        if source.lower().endswith(".xml") and os.path.isfile(source):
            try:
                root = ET.parse(source).getroot()
                items = [el.text.strip() for el in root.iter()
                         if el.text and el.text.strip()]
            except Exception:
                items = []
        else:
            items = [s.strip() for s in source.split(",") if s.strip()]
        if items:
            current = self._combobox.currentText()
            self._combobox.blockSignals(True)
            self._combobox.clear()
            self._combobox.addItems(items)
            new_text = current if current in items else items[0]
            self._combobox.setCurrentText(new_text)
            self._combobox.blockSignals(False)
            if new_text != current:
                self._notify_connections_changed()

    def _update_connected_values(self):
        src_val = self._get_connected_input_value("src")
        if src_val:
            self._new_item.clear()
            self._new_item.setReadOnly(True)
            self._add_btn.setVisible(False)
            self._remove_btn.setVisible(False)
            self._populate_from_source(src_val)
        else:
            self._new_item.setReadOnly(False)
            self._add_btn.setVisible(True)
            self._remove_btn.setVisible(True)

    def get_value(self, socket_name: str = None) -> str:
        src_socket = self.get_socket("src")
        if src_socket and self.scene():
            win = self.scene().nodeEditorWindow
            for conn in win.connections:
                if conn.dest is src_socket:
                    self._populate_from_source(
                        conn.source.meta_node.get_value(conn.source.sock_def.name)
                    )
                    break
        return self._combobox.currentText()


class PathParamNode(_BaseParamNode):
    TYPE_ID = "path"

    def __init__(self, param_name="[F/F] Load"):
        dir_schema    = resolve_color_schema("dirpath")
        file_schema   = resolve_color_schema("filepath")
        string_schema = resolve_color_schema("string")

        node_def = NodeDef(
            title=_html_title(param_name),
            header_color=dir_schema["hdr"],
            body_color=dir_schema["body"],
            sockets=[
                SocketDef("dirpath_out", "output", row=0, label="",
                          color=dir_schema["socket"], param_type="dirpath"),
                SocketDef("path_out", "output", row=0, label="",
                          color=file_schema["socket"], param_type="filepath"),
                SocketDef("filename", "input", row=1, label="",
                          color=string_schema["socket"], param_type="string",
                          optional=True),
                SocketDef("filetype", "input", row=2, label="",
                          color=string_schema["socket"], param_type="string",
                          optional=True),
            ],
            width=260,
            has_footer=False,
        )
        super().__init__(node_def)

        self._ext_filter = self._make_field("", "*.ext")
        self._ext_filter.textChanged.connect(
            lambda: self._on_dir_changed(self._dir_editor.text())
        )
        self._ext_filter.textChanged.connect(self._notify_connections_changed)

        self._dir_editor = self._make_field(placeholder="dirpath…", fixed_width=False)
        self._dir_editor.textChanged.connect(self._on_dir_changed)
        self._dir_editor.textChanged.connect(self._notify_connections_changed)

        dir_widget = QWidget()
        dir_widget.setStyleSheet("background:transparent;")
        dir_layout = QHBoxLayout(dir_widget)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        dir_layout.setSpacing(3)
        dir_layout.addWidget(self._dir_editor)
        dir_layout.addWidget(self._make_toolbtn("…", self._browse_for_folder))
        dir_widget.setFixedWidth(self._widget_width())

        self._file_combo = self._make_combobox()
        self._file_combo.lineEdit().setPlaceholderText("filename…")
        self._file_combo.currentTextChanged.connect(self._notify_connections_changed)

        self._attach_widget_at_row(dir_widget, 0)
        self._attach_widget_at_row(self._file_combo, 1)
        self._attach_widget_at_row(self._ext_filter, 2)

    def _browse_for_folder(self):
        path = QFileDialog.getExistingDirectory(None, "Select folder", self._dir_editor.text())
        if path:
            self._dir_editor.setText(path)

    def _update_connected_values(self):
        self._show_connected_combobox(self._file_combo,
                                      self._get_connected_input_value("filename"))
        self._show_connected_value(self._ext_filter,
                                   self._get_connected_input_value("filetype"))

    def _on_dir_changed(self, text):
        self._file_combo.blockSignals(True)
        self._file_combo.clear()
        if os.path.isdir(text):
            try:
                raw = (self._get_connected_input_value("filetype")
                       or self._ext_filter.text()).strip()
                ext = raw.lstrip("*").lstrip(".").lower()
                files = sorted(
                    f for f in os.listdir(text)
                    if os.path.isfile(os.path.join(text, f))
                    and (not ext or f.lower().endswith("." + ext))
                )
                self._file_combo.addItem("")
                self._file_combo.addItems(files)
                self._file_combo.setCurrentText("")
            except Exception:
                pass
        self._file_combo.blockSignals(False)
        self._notify_connections_changed()

    def get_value(self, socket_name: str = None) -> str:
        d = self._dir_editor.text().strip().replace("\\", "/")
        if socket_name == "dirpath_out":
            return d
        filename = self._get_connected_input_value("filename") or self._file_combo.currentText().strip()
        raw_type = (self._get_connected_input_value("filetype") or self._ext_filter.text()).strip()
        ext = raw_type.lstrip("*").lstrip(".")
        if ext and filename:
            suffix = "." + ext
            if not filename.lower().endswith(suffix.lower()):
                filename += suffix
        if d and filename:
            return (d + "/" + filename).replace("\\", "/")
        return d



class KeyValueParamNode(_BaseParamNode):
    TYPE_ID = "keyvalue"

    def __init__(self, param_name="[K] Key=Value"):
        super().__init__(_param_node_def(param_name, self.TYPE_ID))
        self._editor = self._make_field("key=value", "key=value")
        self._editor.textChanged.connect(self._notify_connections_changed)
        self._attach_input_widget(self._editor)

    def get_value(self, socket_name: str = None) -> str:
        return self._editor.text().strip()


# ── Registry ──────────────────────────────────────────────────────────────────

PARAM_NODE_TYPES: Dict[str, type] = {
    "string":   StringParamNode,
    "bool":     BoolParamNode,
    "integer":  IntParamNode,
    "float":    FloatParamNode,
    "enum":     EnumParamNode,
    "enum_int": EnumParamNode,
    "filepath": PathParamNode,
    "dirpath":  PathParamNode,
    "keyvalue": KeyValueParamNode,
}