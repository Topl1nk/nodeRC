from __future__ import annotations
import html
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

from PyQt5.QtWidgets import (
    QGraphicsObject, QGraphicsItem, QGraphicsTextItem,
    QGraphicsProxyWidget, QLineEdit, QCheckBox,
    QSpinBox, QComboBox, QGraphicsPathItem, QWidget,
    QHBoxLayout, QToolButton, QStyle, QLabel,
    QApplication, QAbstractSpinBox, QMenu, QGraphicsRectItem,
    QGridLayout, QPushButton,
)
from PyQt5.QtGui import (
    QPen, QBrush, QColor, QPainterPath, QFont, QPainter, QPolygonF,
    QDoubleValidator, QPalette, QTextCursor, QCursor,
)
from PyQt5.QtCore import QRectF, Qt, QPointF, QEvent, QTimer
from localization import t

from color_picker import (
    ColorPickerPopup, adjust_hex_color, brightened_for_canvas_hex, relative_luminance_hex,
    NODE_BORDER_COLOR, FIELD_QSS, COMBOBOX_QSS, SPINBOX_QSS, CHECKBOX_QSS,
    TOOLBTN_QSS, PUSHBTN_QSS, VECTOR_TOGGLE_QSS, VECTOR_AXIS_LABEL_QSS,
    CONTEXT_MENU_STYLESHEET, GROUP_FRAME_BORDER_COLOR
)

from configuration import (
    NODE_HEADER_HEIGHT, NODE_ROW_HEIGHT,
    NODE_EXEC_SOCKET_HALFSIZE, NODE_PARAM_SOCKET_RADIUS,
    NODE_DEFAULT_WIDTH, NODE_HORIZONTAL_PAD,
    NODE_FOOTER_HEIGHT, NODE_BOTTOM_PAD, NODE_WIDGET_V_OFFSET, NODE_WIDGET_HEIGHT,
    NODE_SHADOW_OFFSET_X, NODE_SHADOW_OFFSET_Y, NODE_SHADOW_BLUR, NODE_BOUNDS_MARGIN,
    COLOR_PRESETS, CANVAS_BACKGROUND_COLOR,

    SOCKET_COLOR_SCHEMA, SOCKET_HOVER_COLOR,
    NODE_SELECTED_COLOR, CONNECTION_SELECTED_COLOR,
    TEXT_COLOR,
    BEZIER_CTRL_FACTOR, BEZIER_CTRL_MIN, BROWSE_BTN_WIDTH,
    GRID_SIZE_SMALL, NODE_POPUP_Z,
    VECTOR_COLLAPSE_GLYPH, VECTOR_EXPAND_GLYPH,
    NODE_SELECTION_OVERLAY_RGBA, NODE_SELECTION_OVERLAY_Z,
    NODE_SOCKET_Z, NODE_WIDGET_Z_BASE, NODE_LINKED_FIELD_Z,
    KEY_COMMIT_EDIT, KEY_CANCEL_EDIT,
    GROUP_FRAME_Z, GROUP_FRAME_FILL_RGBA, GROUP_FRAME_FILL_ALPHA,
    GROUP_FRAME_BORDER_WIDTH, GROUP_FRAME_TITLE_COLOR,
    GROUP_FRAME_TITLE_FONT, GROUP_FRAME_TITLE_FONT_SIZE, GROUP_FRAME_TITLE_MARGIN,
    GROUP_FRAME_HEADER_HEIGHT, GROUP_FRAME_HEADER_DARKEN,
    GROUP_FRAME_HANDLE, GROUP_FRAME_MIN_SIZE, GROUP_FRAME_BORDER_INSET,
    CONNECTION_Z, NODE_DRAG_Z,
    UI_FONT_FAMILY, NODE_LABEL_FONT_SIZE, NODE_RENAME_FONT_SIZE,
    TINT_BODY_DARKEN, TINT_FIELD_DARKEN, TINT_BUTTON_DARKEN,
    TINT_HOVER_DARKEN, TINT_PRESSED_DARKEN, TINT_SELECTION_LIGHTEN,
    TINT_TITLE_LUMINANCE_THRESHOLD,
    TINT_BORDER_MIN_LUMINANCE, TINT_BORDER_LIGHTEN_STEP,
    TEXT_MUTED_COLOR, BUTTON_TEXT_COLOR,
)




def _relative_luminance(color: QColor) -> float:
    """Perceived brightness 0–255 using the standard Rec. 601 weights."""
    return 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()


def brightened_for_canvas(color: QColor) -> QColor:
    """Lighten ``color`` until it crosses the visible-on-canvas luminance floor.

    A user-picked near-black sits invisibly on top of CANVAS_BACKGROUND_COLOR; we
    lift it just enough to stay readable as a node/frame outline. Bright picks
    pass through untouched.
    """
    if _relative_luminance(color) >= TINT_BORDER_MIN_LUMINANCE:
        return QColor(color)
    # Qt's lighter() multiplies the HSV value channel, so it cannot brighten
    # absolute black (V==0): seed a minimum value first, then iterate.
    out = QColor(color)
    if out.valueF() == 0.0:
        out.setHsvF(out.hueF() if out.hueF() >= 0 else 0.0, out.saturationF(), 0.1)
    # Bounded loop: each lighten() strictly increases V toward 1, so this
    # terminates well before the (capped) iteration limit.
    for _ in range(16):
        if _relative_luminance(out) >= TINT_BORDER_MIN_LUMINANCE:
            break
        out = out.lighter(TINT_BORDER_LIGHTEN_STEP)
    return out


def editor_window_of(item):
    """The editor window owning a scene item, or None when it is unparented.

    Single source for "the window lives at scene.nodeEditorWindow", so every
    item — whatever its base class — resolves it the same way.
    """
    scene = item.scene()
    return getattr(scene, "nodeEditorWindow", None) if scene else None


def resolve_color_schema(socket_type: str) -> dict:
    from configuration import DEFAULT_HEADER_COLOR
    schema = SOCKET_COLOR_SCHEMA.get(socket_type.lower(), SOCKET_COLOR_SCHEMA["any"])
    return {
        "hdr": DEFAULT_HEADER_COLOR,
        "body": adjust_hex_color(DEFAULT_HEADER_COLOR, TINT_BODY_DARKEN),
        "socket": schema["socket"]
    }


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


class GroupFrameItem(QGraphicsRectItem):
    """A backdrop frame that holds nodes: drag the body to move it (and its
    contents), drag any edge or corner to resize it, drag to fit, or refit it to
    the nodes it overlaps."""

    _RESIZE_NONE = (False, False, False, False)

    def __init__(self, rect: QRectF, title: Optional[str] = None):
        # One coordinate convention everywhere: the item's own rect is anchored at
        # (0, 0) and its scene placement lives entirely in pos(). Callers may hand
        # us a scene-positioned rect (e.g. the bounding box of grouped nodes); we
        # split it so the title, hit-testing and resize math never have to guess
        # whether the offset sits in rect() or in pos(). Snapping here keeps every
        # edge on the grid, so later drags and resizes stay jump-free.
        super().__init__(QRectF(
            0, 0,
            max(GROUP_FRAME_MIN_SIZE, self._snap(rect.width())),
            max(GROUP_FRAME_MIN_SIZE, self._snap(rect.height())),
        ))
        self.setPos(self._snap(rect.x()), self._snap(rect.y()))
        # Resolve the default lazily so the label honours the active UI language.
        self.title = title if title is not None else t("default_group_title")
        self.setZValue(GROUP_FRAME_Z)
        self.setFlags(
            QGraphicsItem.ItemIsSelectable |
            QGraphicsItem.ItemIsMovable |
            QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self._color = GROUP_FRAME_BORDER_COLOR
        self._apply_color()

        self._resizing = False
        self._resize_edges = self._RESIZE_NONE

        # Persistent group membership: nodes that follow this frame on subsequent
        # drags, committed at every release. Press-time recapture stays as a fast
        # path during the live drag itself.
        self._dragged_inner_nodes: list = []
        self._group_members: list = []

        self.title_item = _EditableTitleItem(self)
        self.title_item.setFont(QFont(GROUP_FRAME_TITLE_FONT, GROUP_FRAME_TITLE_FONT_SIZE))
        self.title_item.setHtml(self._title_html(self.title))
        self._center_title()

    # ── Appearance ────────────────────────────────────────────────────────────

    @staticmethod
    def _title_html(name: str) -> str:
        return (f"<font color='{GROUP_FRAME_TITLE_COLOR}'>"
                f"<b>{html.escape(name)}</b></font>")

    def _center_title(self):
        if hasattr(self, 'title_item'):
            # Vertically centre the title inside the header strip — same idiom
            # MetaNode uses, so node and frame headers read as one design.
            r = self.rect()
            y = r.top() + (GROUP_FRAME_HEADER_HEIGHT - self.title_item.boundingRect().height()) / 2.0
            self.title_item.setPos(r.left() + GROUP_FRAME_TITLE_MARGIN, y)

    def title_edit_background(self) -> Optional[str]:
        # No filled box behind the frame title while editing — the faint frame
        # wash already sets it off, and a solid swatch read as a stray blue block.
        return None

    # ── Frame color ───────────────────────────────────────────────────────────

    def _apply_color(self):
        c = QColor(self._color)
        fill = QColor(c)

        # The color picker outputs a 9-char hex (#AARRGGBB) if the alpha slider was used.
        # If the user explicitly sets an alpha, we respect it for the fill.
        # Otherwise (legacy 7-char #RRGGBB), we force the fill to be faintly transparent.
        if len(self._color) < 9:
            fill.setAlpha(GROUP_FRAME_FILL_ALPHA)

        # paint() draws the dashed outline manually so it can sit inset from the
        # fill edge — Qt's rect pen would otherwise hug the edge exactly.
        self.setBrush(QBrush(fill))
        self.setPen(QPen(Qt.NoPen))

    def color(self) -> str:
        return self._color

    def set_color(self, color_hex: str, *, record_undo: bool = True):
        self._color = color_hex
        self._apply_color()
        self.update()
        win = self._editor_window()
        if record_undo and win:
            win.push_undo_state()

    def _pick_color(self):
        win = self._editor_window()
        if not win:
            return
            
        selected_frames = [item for item in self.scene().selectedItems() if isinstance(item, GroupFrameItem)]
        if self not in selected_frames:
            selected_frames.append(self)
            
        for node in selected_frames:
            if hasattr(node, '_selection_overlay'):
                node._selection_overlay.setVisible(False)
            
        def on_close():
            for node in selected_frames:
                if hasattr(node, '_selection_overlay'):
                    node._selection_overlay.setVisible(node.isSelected())
            win.push_undo_state()
            
        def apply_color_to_all(c, only_header):
            # only-header is meaningless for a frame (no body widgets to recolor),
            # so we just apply the picked colour uniformly.
            for node in selected_frames:
                node.set_color(c, record_undo=False)

        from configuration import GROUP_FRAME_FILL_ALPHA
        current = QColor(self._color)
        if len(self._color) < 9:
            current.setAlpha(GROUP_FRAME_FILL_ALPHA)

        popup = ColorPickerPopup(
            on_color_selected=apply_color_to_all,
            initial_color=current.name(QColor.HexArgb),
            on_close=on_close,
            parent=win
        )
        popup.move(QCursor.pos())
        popup.show()

    def _editor_window(self):
        return editor_window_of(self)

    def boundingRect(self) -> QRectF:
        # Include the outset dashed ring + its pen width so Qt repaints all of it
        # cleanly when the frame moves or resizes.
        margin = GROUP_FRAME_BORDER_INSET + GROUP_FRAME_BORDER_WIDTH
        return super().boundingRect().adjusted(-margin, -margin, margin, margin)

    def paint(self, painter, option, widget):
        # Order: body fill (super) → header strip → divider → single outset dashed
        # ring. The ring is the sole selection indicator — it just swaps colour
        # between accent (unselected) and white (selected). We strip the default
        # State_Selected flag so QGraphicsRectItem doesn't also stamp its own
        # dotted selection border on top of ours.
        if option.state & QStyle.State_Selected:
            option.state &= ~QStyle.State_Selected
        painter.setRenderHint(QPainter.Antialiasing)
        super().paint(painter, option, widget)

        r = self.rect()
        header_color = QColor(self._color).darker(GROUP_FRAME_HEADER_DARKEN)
        header_color.setAlpha(255)
        header_rect = QRectF(r.left(), r.top(), r.width(),
                             min(GROUP_FRAME_HEADER_HEIGHT, r.height()))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(header_color))
        painter.drawRect(header_rect)

        accent = brightened_for_canvas(QColor(self._color))
        # Divider under the header uses the same accent colour as the dashed
        # outline, keeping every frame ornament on one shade.
        painter.setPen(QPen(accent, 1))
        painter.drawLine(
            QPointF(header_rect.left(), header_rect.bottom()),
            QPointF(header_rect.right(), header_rect.bottom()),
        )

        outset = GROUP_FRAME_BORDER_INSET
        outline = r.adjusted(-outset, -outset, outset, outset)
        outline_color = QColor(NODE_SELECTED_COLOR) if self.isSelected() else accent
        painter.setPen(QPen(outline_color, GROUP_FRAME_BORDER_WIDTH, Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(outline)

    @staticmethod
    def _snap(value: float) -> float:
        return round(value / GRID_SIZE_SMALL) * GRID_SIZE_SMALL

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            # A resize drives pos() to an exact, already-snapped corner; re-snapping
            # here would nudge the anchored corner off the grid and drag the
            # opposite edge with it, so leave a resize's position untouched.
            if self._resizing:
                return value
            snapped = QPointF(self._snap(value.x()), self._snap(value.y()))
            delta = snapped - self.pos()
            if delta.manhattanLength() > 0.01:
                for item in getattr(self, '_dragged_inner_nodes', []):
                    if item.scene() and not item.isSelected():
                        item.moveBy(delta.x(), delta.y())
            return snapped
        return super().itemChange(change, value)

    # ── Manual resize ─────────────────────────────────────────────────────────

    def _edge_at(self, pos: QPointF):
        """Which edges the point grabs, as (left, top, right, bottom); None if the
        point is on the body rather than the resize strip."""
        r = self.rect()
        h = GROUP_FRAME_HANDLE
        within_x = r.left() - h <= pos.x() <= r.right() + h
        within_y = r.top() - h <= pos.y() <= r.bottom() + h
        left   = abs(pos.x() - r.left())   <= h and within_y
        right  = abs(pos.x() - r.right())  <= h and within_y
        top    = abs(pos.y() - r.top())    <= h and within_x
        bottom = abs(pos.y() - r.bottom()) <= h and within_x
        edges = (left, top, right, bottom)
        return edges if edges != self._RESIZE_NONE else None

    @staticmethod
    def _cursor_for_edges(edges) -> Qt.CursorShape:
        left, top, right, bottom = edges
        if (left and top) or (right and bottom):
            return Qt.SizeFDiagCursor
        if (right and top) or (left and bottom):
            return Qt.SizeBDiagCursor
        if left or right:
            return Qt.SizeHorCursor
        return Qt.SizeVerCursor

    def hoverMoveEvent(self, event):
        edges = self._edge_at(event.pos())
        if edges:
            self.setCursor(self._cursor_for_edges(edges))
        else:
            self.unsetCursor()
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        edges = self._edge_at(event.pos()) if event.button() == Qt.LeftButton else None
        if edges:
            self._resizing = True
            self._resize_edges = edges
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            self._apply_resize(event.scenePos())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
            self._resize_edges = self._RESIZE_NONE
            win = self._editor_window()
            if win:
                win.push_undo_state()
            event.accept()
        else:
            super().mouseReleaseEvent(event)
        # Always commit membership after the frame's mouse release
        self.commit_members()

    def commit_members(self, force_all: bool = False):
        """Update group membership.
        
        If force_all is True (e.g. during project load or duplicate), we scan the scene
        to find all nodes whose center lies inside this frame.
        Otherwise, we only retain current members that are still inside the frame (excluding
        newly overlapped nodes).
        """
        scene = self.scene()
        if not scene:
            self._group_members = []
            return
        frame_rect = self.mapToScene(self.rect()).boundingRect()
        if force_all:
            self._group_members = [
                item for item in scene.items()
                if isinstance(item, MetaNode) and item is not self
                and frame_rect.contains(item.sceneBoundingRect().center())
            ]
            for node in self._group_members:
                node._group_frame = self
        else:
            still_inside = []
            for node in getattr(self, '_group_members', []):
                if node.scene() is scene and frame_rect.contains(node.sceneBoundingRect().center()):
                    still_inside.append(node)
                else:
                    if getattr(node, '_group_frame', None) is self:
                        node._group_frame = None
            self._group_members = still_inside

    def _apply_resize(self, scene_pos: QPointF):
        left, top, right, bottom = self._resize_edges
        rect = self.rect()
        # Work in scene space from the rect's actual scene corners, so the math is
        # correct regardless of any offset that lives in rect() rather than pos().
        x0, y0 = self.pos().x() + rect.left(), self.pos().y() + rect.top()
        x1, y1 = x0 + rect.width(), y0 + rect.height()
        sx, sy = self._snap(scene_pos.x()), self._snap(scene_pos.y())
        m = GROUP_FRAME_MIN_SIZE
        if left:   x0 = min(sx, x1 - m)
        if right:  x1 = max(sx, x0 + m)
        if top:    y0 = min(sy, y1 - m)
        if bottom: y1 = max(sy, y0 + m)
        self.setPos(x0, y0)
        self.setRect(0, 0, x1 - x0, y1 - y0)
        self._center_title()

    # ── Rename ────────────────────────────────────────────────────────────────

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton and not self._edge_at(event.pos()):
            self._begin_rename()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def _begin_rename(self):
        item = self.title_item
        self._rename_backup = self.title
        item.setDefaultTextColor(QColor(GROUP_FRAME_TITLE_COLOR))
        item.setFont(QFont(GROUP_FRAME_TITLE_FONT, GROUP_FRAME_TITLE_FONT_SIZE))
        item.setPlainText(self._rename_backup)
        item.setZValue(NODE_SOCKET_Z)
        item.setTextInteractionFlags(Qt.TextEditorInteraction)
        item.begin_editing()
        item.setFocus(Qt.OtherFocusReason)
        cursor = item.textCursor()
        cursor.select(QTextCursor.Document)
        item.setTextCursor(cursor)

    def _end_rename(self) -> bool:
        item = self.title_item
        if item.textInteractionFlags() == Qt.NoTextInteraction:
            return False
        item.setTextInteractionFlags(Qt.NoTextInteraction)
        item.end_editing()
        item.setZValue(0)
        return True

    def _commit_rename(self):
        if not self._end_rename():
            return
        name = self.title_item.toPlainText().strip() or self._rename_backup
        self.title = name
        self.title_item.setHtml(self._title_html(name))
        self._center_title()
        win = self._editor_window()
        if win:
            win.push_undo_state()

    def _cancel_rename(self):
        if not self._end_rename():
            return
        self.title_item.setHtml(self._title_html(self._rename_backup))
        self._center_title()

    # ── Context menu and contained-node operations ────────────────────────────

    def contextMenuEvent(self, event):
        win = self._editor_window()
        if not win:
            super().contextMenuEvent(event)
            return

        menu = QMenu()
        menu.setStyleSheet(CONTEXT_MENU_STYLESHEET)

        rename_act = menu.addAction(t("ctx_rename_group"))
        color_act  = menu.addAction(t("ctx_change_color"))
        menu.addSeparator()
        remove_frame_act = menu.addAction(t("ctx_remove_frame"))
        clear_frame_act  = menu.addAction(t("ctx_clear_frame"))
        delete_group_act = menu.addAction(t("ctx_delete_group"))

        chosen = menu.exec_(event.screenPos())
        if chosen == rename_act:
            self._begin_rename()
        elif chosen == color_act:
            self._pick_color()
        elif chosen == remove_frame_act:
            self._remove_frame()
        elif chosen == clear_frame_act:
            self._clear_frame()
        elif chosen == delete_group_act:
            self._delete_group()
        event.accept()

    def _contained_nodes(self) -> list:
        """Nodes whose center lies inside the frame — the group's real members."""
        scene = self.scene()
        if not scene:
            return []
        frame_rect = self.mapToScene(self.rect()).boundingRect()
        return [item for item in scene.items()
                if isinstance(item, MetaNode) and item is not self
                and frame_rect.contains(item.sceneBoundingRect().center())]

    def _remove_frame(self):
        scene = self.scene()
        win = self._editor_window()
        if scene:
            scene.removeItem(self)
            if win:
                win.push_undo_state()

    def _delete_contained(self, also_remove_frame: bool):
        scene = self.scene()
        win = self._editor_window()
        if not (scene and win):
            return
        targets = [n for n in self._contained_nodes() if not n.is_protected]
        win._block_undo_push = True
        try:
            scene.clearSelection()
            for node in targets:
                node.setSelected(True)
            if targets:
                win._delete_selected_items()
            if also_remove_frame:
                scene.removeItem(self)
        finally:
            win._block_undo_push = False
        win.push_undo_state()

    def _clear_frame(self):
        self._delete_contained(also_remove_frame=False)

    def _delete_group(self):
        self._delete_contained(also_remove_frame=True)



class _SelectionOverlay(QGraphicsItem):


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
    Why: BoundingRect includes shadow area to prevent trail artifacts on move.
    """

    is_protected = False  # the single source for "bulk delete must spare this node"

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

        self.title_item = self._build_title_item(d.title)
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

    def _build_title_item(self, html: str) -> QGraphicsTextItem:
        item = _EditableTitleItem(self)
        item.setHtml(html)
        return item

    def _center_title(self):
        self.title_item.setPos(
            NODE_HORIZONTAL_PAD,
            (NODE_HEADER_HEIGHT - self.title_item.boundingRect().height()) / 2.0,
        )

    # ── In-place rename ───────────────────────────────────────────────────────

    def _begin_rename(self):
        item = self.title_item
        self._rename_backup = item.toPlainText()
        item.setDefaultTextColor(QColor(TEXT_COLOR))
        item.setFont(QFont(UI_FONT_FAMILY, NODE_RENAME_FONT_SIZE))
        item.setPlainText(self._rename_backup)
        item.setZValue(NODE_SOCKET_Z)
        item.setTextInteractionFlags(Qt.TextEditorInteraction)
        item.begin_editing()
        item.setFocus(Qt.OtherFocusReason)
        cursor = item.textCursor()
        cursor.select(QTextCursor.Document)
        item.setTextCursor(cursor)

    def _end_rename(self) -> bool:
        item = self.title_item
        if item.textInteractionFlags() == Qt.NoTextInteraction:
            return False
        item.setTextInteractionFlags(Qt.NoTextInteraction)
        item.end_editing()
        item.setZValue(0)
        return True

    def _commit_rename(self):
        if not self._end_rename():
            return
        name = self.title_item.toPlainText().strip() or self._rename_backup
        self._apply_title(name)
        self._on_renamed(name)
        win = self._editor_window()
        if win:
            win.push_undo_state()

    def _cancel_rename(self):
        if not self._end_rename():
            return
        self._apply_title(self._rename_backup)

    def _apply_title(self, text: str):
        self.title_item.setHtml(_html_title(text))
        self._center_title()

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
        from configuration import PARAM_NODE_HEADER_FROM_SOCKET
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
        win = self._editor_window()
        if record_undo and win:
            win.push_undo_state()

    def _update_children_colors(self):
        """Push the node's current colour (default or override) into every embedded widget.

        Builds one tinted palette (border/field/button/hover/pressed/selection)
        from the picked colour using the named TINT_* factors in configuration,
        then renders Qt stylesheets that mirror the static defaults shipped with
        the app. Defaults and tinted paths share one builder so the two never drift.
        """
        # only-header scope keeps the body and embedded widgets on the default
        # scheme; the override touches just the painted header and its border.
        if not self._color_override or self._color_only_header:
            qss = self._default_widget_qss()
        else:
            qss = self._tinted_widget_qss(QColor(self._color_override))

        if self._color_override:
            painted = QColor(self._color_override)
            title_dark = _relative_luminance(painted) > TINT_TITLE_LUMINANCE_THRESHOLD
            self.title_item.setDefaultTextColor(QColor("#000000" if title_dark else "#FFFFFF"))
        else:
            self.title_item.setDefaultTextColor(QColor(TEXT_COLOR))

        for child in self.childItems():
            if isinstance(child, QGraphicsProxyWidget) and child.widget():
                self._apply_widget_qss(child.widget(), qss)

    @staticmethod
    def _default_widget_qss() -> Dict[str, str]:
        return {
            "combo": COMBOBOX_QSS, "field": FIELD_QSS, "spin": SPINBOX_QSS,
            "check": CHECKBOX_QSS, "tool": TOOLBTN_QSS, "push": PUSHBTN_QSS,
            "separator": NODE_BORDER_COLOR,
        }

    def _tinted_widget_qss(self, color: QColor) -> Dict[str, str]:
        border     = brightened_for_canvas(color).name()
        field_bg   = color.darker(TINT_FIELD_DARKEN).name()
        btn_bg     = color.darker(TINT_BUTTON_DARKEN).name()
        hover      = color.darker(TINT_HOVER_DARKEN).name()
        pressed    = color.darker(TINT_PRESSED_DARKEN).name()
        sel        = color.lighter(TINT_SELECTION_LIGHTEN).name()
        return {
            "combo": (
                f"QComboBox{{border:1px solid {border};background:{field_bg};color:{TEXT_COLOR};"
                f"border-radius:0px;padding:2px 4px;font:9pt {UI_FONT_FAMILY};combobox-popup:0;}}"
                f"QComboBox::drop-down{{border-left:1px solid {border};width:{BROWSE_BTN_WIDTH}px;background:{btn_bg};}}"
                f"QComboBox::drop-down:hover{{background:{hover};border-color:{sel};}}"
                f"QComboBox QAbstractItemView{{border:1px solid {border};background:{field_bg};color:{TEXT_COLOR};"
                f"selection-background-color:{sel};selection-color:{field_bg};outline:0px;}}"
                f"QComboBox QAbstractItemView::item:hover{{background-color:{sel};color:{field_bg};}}"
                f"QComboBox QAbstractItemView::item:selected{{background-color:{sel};color:{field_bg};}}"
                f"QScrollBar:vertical{{border:none;background:{field_bg};width:8px;margin:0px;}}"
                f"QScrollBar::handle:vertical{{background:{border};min-height:20px;border-radius:0px;}}"
                f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0px;}}"
                f"QComboBox[connected=\"true\"]{{color:{TEXT_MUTED_COLOR};}}"
                f"QComboBox[connected=\"true\"] QLineEdit{{color:{TEXT_MUTED_COLOR};}}"
                f"QComboBox[connected=\"true\"]::drop-down{{width:0px;border:none;}}"
            ),
            "field": (
                f"QLineEdit{{border:1px solid {border};background:{field_bg};color:{TEXT_COLOR};"
                f"border-radius:0px;padding:2px 4px;font:9pt {UI_FONT_FAMILY};}}"
                f"QLineEdit:read-only{{color:{TEXT_MUTED_COLOR};}}"
            ),
            "spin": (
                f"QSpinBox{{border:1px solid {border};background:{field_bg};color:{TEXT_COLOR};"
                f"border-radius:0px;padding:2px;font:9pt {UI_FONT_FAMILY};}}"
                f"QSpinBox::up-button{{background:{btn_bg};border-left:1px solid {border};"
                f"border-bottom:1px solid {border};width:16px;}}"
                f"QSpinBox::down-button{{background:{btn_bg};border-left:1px solid {border};width:16px;}}"
                f"QSpinBox::up-button:hover,QSpinBox::down-button:hover{{"
                f"background:{hover};border-color:{sel};}}"
                f"QSpinBox:hover{{border-color:{sel};}}"
            ),
            "check": (
                f"QCheckBox{{font:9pt {UI_FONT_FAMILY};color:{TEXT_COLOR};background:{btn_bg};spacing:6px;}}"
                f"QCheckBox::indicator{{width:13px;height:13px;border:1px solid {border};background:{field_bg};}}"
                f"QCheckBox::indicator:checked{{background:{sel};border-color:{sel};}}"
                f"QCheckBox::indicator:hover{{border-color:{sel};}}"
            ),
            "tool": (
                f"QToolButton{{background:{btn_bg};color:{BUTTON_TEXT_COLOR};"
                f"border:1px solid {border};border-radius:0px;font:9pt {UI_FONT_FAMILY};}}"
                f"QToolButton:hover{{background:{hover};border-color:{sel};}}"
                f"QToolButton:pressed{{background:{pressed};}}"
            ),
            "push": (
                f"QPushButton{{background:{btn_bg};color:{BUTTON_TEXT_COLOR};"
                f"border:1px solid {border};border-radius:0px;padding:5px 8px;font:bold 9pt {UI_FONT_FAMILY};}}"
                f"QPushButton:hover{{background:{hover};border-color:{sel};}}"
                f"QPushButton:pressed{{background:{pressed};}}"
            ),
            # Same brightened shade as the painted border so separators inside dark
            # picks stay visible against the canvas.
            "separator": border,
        }

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
        win = self._editor_window()
        if not win:
            return
            
        selected_nodes = [item for item in self.scene().selectedItems() if isinstance(item, MetaNode)]
        if self not in selected_nodes:
            selected_nodes.append(self)
            
        for node in selected_nodes:
            if hasattr(node, '_selection_overlay'):
                node._selection_overlay.setVisible(False)
            
        def on_close():
            for node in selected_nodes:
                if hasattr(node, '_selection_overlay'):
                    node._selection_overlay.setVisible(node.isSelected())
            win.push_undo_state()
            
        def apply_color_to_all(c, only_header):
            for node in selected_nodes:
                node.set_color(c, only_header=only_header, record_undo=False)

        initial = self._color_override or self.node_def.header_color
        popup = ColorPickerPopup(
            on_color_selected=apply_color_to_all,
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

        win = self._editor_window()
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
                body_border_color = QColor(NODE_BORDER_COLOR)
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
                self._selection_overlay.setVisible(bool(value))
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if scene:
            scene.recalculate_scene_rect()
            
            # Find the top-most containing frame for this node
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
        win = self._editor_window()
        if win:
            self.setSelected(True)
            win._delete_selected_items()

    def contextMenuEvent(self, event):
        win = self._editor_window()
        if not win:
            super().contextMenuEvent(event)
            return

        is_param = isinstance(self, _BaseParamNode)

        self._run_context_menu(event, [
            (t("ctx_rename"),         getattr(self, "_begin_rename", None), is_param),
            (t("ctx_change_color"),   self._pick_color,                           True),
            None,
            (t("ctx_duplicate"),      getattr(win, "duplicate_nodes",      None), True),
            (t("ctx_copy"),           getattr(win, "copy_nodes",           None), True),
            (t("ctx_paste"),          getattr(win, "paste_nodes",          None), True),
            (t("ctx_group_frame"), getattr(win, "group_selected_nodes", None), True),
            None,
            (t("ctx_delete_node"),    self._delete_self,                          True),
        ])

    def serialize_payload(self) -> dict:
        """Type-specific fields needed to reconstruct this node (sans id/position).

        Overridden per node type so persistence never has to branch on the class.
        """
        return {}


class NodeComboBox(QComboBox):
    def __init__(self, node: MetaNode):
        super().__init__()
        self.node = node

    def showPopup(self):
        # Lift the node above its siblings AND drop the selection wash, which is
        # a child item at NODE_SELECTION_OVERLAY_Z and would otherwise paint over
        # the dropped-down list (every embedded proxy sits below the overlay).
        try:
            self.node.setZValue(NODE_POPUP_Z)
            overlay = getattr(self.node, "_selection_overlay", None)
            if overlay is not None:
                overlay.setVisible(False)
        except RuntimeError:
            pass
        super().showPopup()

    def hidePopup(self):
        super().hidePopup()
        try:
            self.node.setZValue(0)
            overlay = getattr(self.node, "_selection_overlay", None)
            if overlay is not None:
                overlay.setVisible(self.node.isSelected())
        except RuntimeError:
            pass


class _EditableTitleItem(QGraphicsTextItem):
    """Header title that edits in place; commits on Enter/focus-out, reverts on Esc."""

    def __init__(self, node: MetaNode):
        super().__init__(node)
        self._node = node
        # Out of rename mode the title is purely decorative: empty shape +
        # NoButton makes it invisible to Qt's mouse routing, so a click on the
        # title text drags the parent (frame/node) instead of grabbing the inert
        # text item. begin/end_editing flips both at once.
        self._editing = False
        self.setAcceptedMouseButtons(Qt.NoButton)

    def begin_editing(self):
        self._editing = True
        self.setAcceptedMouseButtons(Qt.AllButtons)
        self.prepareGeometryChange()

    def end_editing(self):
        self._editing = False
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.prepareGeometryChange()

    def shape(self):
        if not self._editing:
            return QPainterPath()  # empty → invisible to hit-testing
        return super().shape()

    def boundingRect(self):
        return super().boundingRect()

    def paint(self, painter: QPainter, option, widget=None):
        if self.textInteractionFlags() != Qt.NoTextInteraction:
            backdrop = self._node.title_edit_background()
            if backdrop:
                painter.fillRect(
                    self.boundingRect().adjusted(-2, -1, 2, 1),
                    QColor(backdrop),
                )
        super().paint(painter, option, widget)

    def keyPressEvent(self, event):
        if event.key() in KEY_COMMIT_EDIT:
            self._node._commit_rename()
            event.accept()
        elif event.key() == KEY_CANCEL_EDIT:
            self._node._cancel_rename()
            event.accept()
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._node._commit_rename()

    def _is_editing(self) -> bool:
        return self.textInteractionFlags() != Qt.NoTextInteraction

    def mousePressEvent(self, event):
        # Out of rename mode the title is just a label — let the click fall through
        # to the parent (the node or frame) so it can be selected/dragged. Without
        # this the title text would grab the press and the parent would never see it.
        if not self._is_editing():
            event.ignore()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self._is_editing():
            event.ignore()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if not self._is_editing():
            event.ignore()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        # Allow the parent's mouseDoubleClickEvent to trigger rename when the
        # user double-clicks the title text directly.
        if not self._is_editing():
            event.ignore()
            return
        super().mouseDoubleClickEvent(event)


class _BaseParamNode(MetaNode):
    def __init__(self, node_def: NodeDef):
        super().__init__(node_def)
        self._update_scheduled = False

    def serialize_payload(self) -> dict:
        return {
            "creation_data": getattr(self, "creation_data",
                                     {"param_type": self.TYPE_ID, "display": self.TYPE_ID}),
            "current_value": self.get_value_state(),
        }

    def _on_renamed(self, name: str):
        creation_data = dict(getattr(self, "creation_data", {}) or {})
        creation_data.setdefault("param_type", self.TYPE_ID)
        creation_data["display"] = name
        self.creation_data = creation_data

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._begin_rename()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def itemChange(self, change, value):
        result = super().itemChange(change, value)
        if change == QGraphicsItem.ItemSceneHasChanged and not self._update_scheduled:
            self._update_scheduled = True
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
        w.setStyleSheet(FIELD_QSS)
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
        w.setStyleSheet(COMBOBOX_QSS)
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
        w.setStyleSheet(SPINBOX_QSS)
        pal = w.palette()
        pal.setColor(QPalette.ButtonText, QColor(TEXT_COLOR))
        w.setPalette(pal)
        return w

    def _make_checkbox(self, text: str = "true", checked: bool = False) -> QCheckBox:
        w = QCheckBox(text)
        w.setChecked(checked)
        w.setFixedWidth(self._widget_width())
        w.setFixedHeight(NODE_WIDGET_HEIGHT)
        w.setStyleSheet(CHECKBOX_QSS)
        return w

    def _make_toolbtn(self, text: str, callback=None) -> QToolButton:
        w = QToolButton()
        w.setText(text)
        w.setStyleSheet(TOOLBTN_QSS)
        w.setFixedWidth(BROWSE_BTN_WIDTH)
        w.setFixedHeight(NODE_WIDGET_HEIGHT)
        if callback:
            w.clicked.connect(callback)
        return w

    def _get_connected_input_value(self, socket_name: str) -> Optional[str]:
        sock = self.get_socket(socket_name)
        win = editor_window_of(self)
        if not sock or not win:
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
        
        pre_click = getattr(scene, '_pre_click_selection', None)
        selected_items = pre_click if pre_click is not None else scene.selectedItems()
        
        same_type = [
            n for n in selected_items
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
            node._refresh_selection_visuals()

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
                node._refresh_selection_visuals()
        win.push_undo_state()

    def _refresh_selection_visuals(self):
        win = self._editor_window()
        is_linked = win is not None and self in getattr(win, '_linked_group', [])
        self._selection_overlay.setVisible(self.isSelected() or is_linked)
        self.update()
        self._adjust_proxy_z_values()

    def _adjust_proxy_z_values(self):
        """
        MASS EDIT / LINKED EDIT DESIGN MECHANICS:
        
        1. Linked Grouping: Clicking any parameter widget (QLineEdit, QComboBox, etc.) 
           gathers all selected parameter nodes of the same type into `win._linked_group`.
        2. Pre-Click Selection Tracking: By default, clicking a widget triggers a deselection 
           pass in QGraphicsScene before focus is established. To counter this, `NodeScene` 
           stores the pre-click selection state in `scene._pre_click_selection`, allowing 
           us to reconstruct the full group correctly inside `_enter_linked_editing`.
        3. Visual Wash Overlay: All selected/linked nodes have a white translucent 
           `_SelectionOverlay` (Z = 2000) visible on top of their body.
        4. Field Key Isolation: Only the actively edited field matches `win._active_field_key`. 
           Its proxy Z-value is raised to `NODE_LINKED_FIELD_Z` (2500) so it paints above 
           the selection overlay, removing the white haze only from the active input.
        5. Inactive fields and other nodes in the selection group keep their original Z-values 
           (below 2000), leaving them covered by the selection wash as expected.
        """
        win = self._editor_window()
        is_edited = win is not None and self in win._linked_group
        active_key = getattr(win, '_active_field_key', None) if is_edited else None

        for child in self.childItems():
            if isinstance(child, QGraphicsProxyWidget):
                child_key = getattr(child, '_field_key', None)
                if is_edited and active_key is not None and child_key == active_key:
                    if not hasattr(child, '_original_z_value'):
                        child._original_z_value = child.zValue()
                    child.setZValue(NODE_LINKED_FIELD_Z)
                    child.update()
                else:
                    if hasattr(child, '_original_z_value'):
                        child.setZValue(child._original_z_value)
                        delattr(child, '_original_z_value')
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
        win = editor_window_of(self)
        if not win:
            return
        for conn in win.connections:
            if conn.source.meta_node is self:
                dest_node = conn.dest.meta_node
                if hasattr(dest_node, "_update_connected_values"):
                    dest_node._update_connected_values()
                    dest_node._propagate_connections_changed(visited)

    def _update_connected_values(self):
        """
        Hook method called when connections are established or updated.
        Why: Parameter classes override this to pull input data or lock widgets.
        """
        return

    def _on_widget_user_edit(self):
        win = editor_window_of(self)
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
            # Non-numeric text is a valid in-progress edit, not an error — leave it
            # untouched and let the field keep what the user is still typing.
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
        """
        Get the internal state of the parameter value for serialization.
        Why: Backing files need a standard format to serialize all parameter nodes.
        """
        return None

    def set_value_state(self, val: Any):
        """
        Set the internal state of the parameter value from serialized data.
        Why: Backing files need a standard format to restore parameter widgets.
        """
        return

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
            label.setStyleSheet(VECTOR_AXIS_LABEL_QSS)

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
                # The active key named an axis this vector lacks; fall through to a
                # whole-value sync below instead of mirroring a single component.
                pass
        self.set_value_state(source_node.get_value_state())

    def get_value(self, socket_name: str = None) -> str:
        return " ".join(editor.text().strip() or "0.0" for editor in self._editors)


def _html_title(text: str, bold_first: bool = False) -> str:
    parts = text.split(" ", 1)
    first = html.escape(parts[0]) if parts else ""
    if bold_first and parts:
        first = f"<b>{first}</b>"
    rest = f" {html.escape(parts[1])}" if len(parts) > 1 else ""
    return (f'<span style="font-family:{UI_FONT_FAMILY};font-size:{NODE_RENAME_FONT_SIZE}pt;">'
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
