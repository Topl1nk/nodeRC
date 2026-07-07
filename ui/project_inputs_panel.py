"""project_inputs_panel.py — Left "Project Inputs" Dock

Lists every param node flagged via ParamNode.set_project_input(True) so the
project's exposed values can be edited from one place instead of hunting them
across the canvas. Each row binds to the node's existing get_value_state()/
set_value_state() contract (core/graph_model.py's is_project_input, ui/
graph_items.py's set_project_input) — the row is a second *view* of that one
stored value, not a second source of truth.

A row mirrors the node's own socket row rather than inventing a new look:
drag handle (reorder) — socket label (same text/color as the node's own
socket label) — value editor (ui/value_widgets.py's build_text_field/
build_checkbox/build_spinbox/build_combobox — the exact same primitives
ParamNode's own _make_field/_make_checkbox/_make_spinbox/_make_combobox
delegate to, so a row's editor is pixel-identical to the node's own, minus
the node's tint since it's never parented under the node for
_update_children_colors to reach) — a small socket dot (SocketItem's own
circle recipe) that previews the node with the same white hover outline
GraphicsView already draws, and jumps to it on click.

All rows are cells of ONE QGridLayout (self._layout below), not each row its
own independent QHBoxLayout — that's what lines every row's name/value
boundary up on a single column instead of each row negotiating its own
widths. Every editor also gets the same fixed PROJECT_INPUTS_FIELD_WIDTH
regardless of the underlying node's own width, for the same reason.

Scope (deliberate, ст 9.3 — no speculative generality): scalar types (string,
float, bool, integer, enum, keyvalue — all single-widget value contracts) get
a live editor here. Composite multi-widget types (path, float2/3) get a
read-only field with the same primitive/width — editing those still happens
on the node itself.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from PyQt5.QtWidgets import QApplication, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from PyQt5.QtGui import QBrush, QColor, QCursor, QPainter, QPen, QLinearGradient
from PyQt5.QtCore import QEvent, QObject, QPoint, QPointF, Qt

from localization import t
from configuration import (
    NODE_PARAM_SOCKET_RADIUS, PROJECT_INPUTS_FIELD_WIDTH,
    PROJECT_INPUTS_PANEL_BACKGROUND_COLOR, PROJECT_INPUTS_PANEL_BORDER_COLOR,
    PROJECT_INPUTS_PANEL_HOVER_HIDE_MARGIN, PROJECT_INPUTS_PANEL_HOVER_REVEAL_MARGIN,
    PROJECT_INPUTS_PANEL_MAX_WIDTH, PROJECT_INPUTS_PANEL_MIN_WIDTH,
    PROJECT_INPUTS_PANEL_RESIZE_GRIP_WIDTH, PROJECT_INPUTS_PANEL_WIDTH,
    SOCKET_BORDER_DARKEN, SOCKET_BORDER_WIDTH, SOCKET_HOVER_COLOR, TEXT_COLOR, TEXT_MUTED_COLOR,
)
from ui.param_nodes import ParamNode
from ui.title_item import editor_window_of
from ui.value_widgets import build_checkbox, build_combobox, build_spinbox, build_text_field
from ui.widgets import InsetFillCheckBox

# Single-QLineEdit value contract (ParamNode._SingleFieldParamNode and
# EnumParamNode-adjacent scalars) — these get a live text field in the panel.
_TEXT_FIELD_TYPES = ("string", "float", "keyvalue")


def _jump_to_node(node: ParamNode) -> None:
    scene = node.scene()
    if not scene or not scene.views():
        return
    scene.clearSelection()
    node.setSelected(True)
    scene.views()[0].centerOn(node)


def _format_composite_value(value) -> str:
    """Human-readable text for a value this panel can't live-edit (path's
    dir/file/ext dict, a vector's list of axis floats) — never the raw
    repr(), which is what a plain str(value) on a dict/list gives you.
    """
    if isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value)


class _DragHandle(QWidget):
    """Left-edge grab zone — drag vertically to reorder the row within the panel."""

    _DOT_COLS, _DOT_ROWS, _DOT_SIZE, _DOT_GAP = 2, 3, 2, 3

    def __init__(self, node: ParamNode, panel: "ProjectInputsPanel"):
        super().__init__()
        self._node = node
        self._panel = panel
        self.setCursor(Qt.SizeAllCursor)
        self.setFixedWidth(14)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._panel.begin_row_drag(self._node)
            event.accept()
        else:
            event.ignore()

    def mouseMoveEvent(self, event):
        self._panel.drag_row_to(self._node, event.globalPos().y())
        event.accept()

    def mouseReleaseEvent(self, event):
        self._panel.end_row_drag()
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(TEXT_MUTED_COLOR)))
        grid_w = self._DOT_COLS * self._DOT_SIZE + (self._DOT_COLS - 1) * self._DOT_GAP
        grid_h = self._DOT_ROWS * self._DOT_SIZE + (self._DOT_ROWS - 1) * self._DOT_GAP
        x0 = (self.width() - grid_w) / 2.0
        y0 = (self.height() - grid_h) / 2.0
        for row in range(self._DOT_ROWS):
            for col in range(self._DOT_COLS):
                x = x0 + col * (self._DOT_SIZE + self._DOT_GAP)
                y = y0 + row * (self._DOT_SIZE + self._DOT_GAP)
                painter.drawEllipse(QPointF(x, y), self._DOT_SIZE / 2.0, self._DOT_SIZE / 2.0)


class _SocketDot(QWidget):
    """The output socket's own circle primitive (see SocketItem.paint), reused
    as a preview/jump affordance: hovering it toggles the node's own white
    hover outline (MetaNode._set_hovered) and clicking it centers on the node.
    """

    def __init__(self, node: ParamNode, color: str):
        super().__init__()
        self._node = node
        self._color = QColor(color)
        self._hovered = False
        size = int(NODE_PARAM_SOCKET_RADIUS * 2 + 6)
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(t("project_inputs_jump_tooltip"))

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        self._node._set_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        self._node._set_hovered(False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            _jump_to_node(self._node)
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(SOCKET_HOVER_COLOR) if self._hovered else self._color
        painter.setPen(QPen(color.darker(SOCKET_BORDER_DARKEN), SOCKET_BORDER_WIDTH))
        painter.setBrush(QBrush(color))
        r = NODE_PARAM_SOCKET_RADIUS
        c = QPointF(self.rect().center())
        painter.drawEllipse(c, r, r)


class ElidedLabel(QLabel):
    """QLabel that elides text with '...' on the right if it doesn't fit its width.
    Allows layouts to shrink the label column without text clipping/overflowing.
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._full_text = text

    def setText(self, text: str) -> None:
        self._full_text = text
        super().setText(text)

    def minimumSizeHint(self):
        sh = super().minimumSizeHint()
        sh.setWidth(30)
        return sh

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        metrics = painter.fontMetrics()
        elided = metrics.elidedText(self._full_text, Qt.ElideRight, self.width())
        color = self.palette().color(self.foregroundRole())
        painter.setPen(color)
        painter.setFont(self.font())
        painter.drawText(self.rect(), self.alignment(), elided)


class _PanelRow:
    """One project-input node's four grid cells: drag handle, socket label,
    value editor, socket dot. Not a QWidget itself — the four widgets are
    cells of ProjectInputsPanel's shared QGridLayout (see module docstring),
    so their columns line up across every row automatically.
    """

    def __init__(self, node: ParamNode, panel: "ProjectInputsPanel"):
        self.node = node
        self.panel = panel
        self._updating = False

        self.handle = _DragHandle(node, panel)

        socket_def = node.primary_output_socket_def()
        label_text = node.node_def.plain_title
        socket_color = socket_def.color if socket_def else TEXT_COLOR
        if socket_def is not None:
            label_text = socket_def.name if socket_def.label is None else socket_def.label
        
        self.label = ElidedLabel(label_text)
        self.label.setStyleSheet(f"color:{socket_color};")
        self.label.setToolTip(node.node_def.plain_title)

        self.editor = self._build_editor()
        self.editor.setMinimumWidth(50)
        self.dot = _SocketDot(node, socket_color)

        self.set_value_from_node(node.get_value_state())

    def widgets(self):
        return (self.handle, self.label, self.editor, self.dot)

    # ── Editor construction — ui/value_widgets.py's shared primitives ───────

    def _build_editor(self) -> QWidget:
        type_id = getattr(self.node, "TYPE_ID", None)
        if type_id in _TEXT_FIELD_TYPES:
            editor = build_text_field(str(self.node.get_value_state()))
            editor.editingFinished.connect(self._on_editor_committed)
            return editor
        if type_id == "bool":
            editor = build_checkbox()
            editor.toggled.connect(self._on_editor_committed)
            return editor
        if type_id == "integer":
            editor = build_spinbox()
            editor.editingFinished.connect(self._on_editor_committed)
            return editor
        if type_id == "enum":
            editor = build_combobox(self.node, editable=False)
            editor.activated.connect(self._on_editor_committed)
            return editor
        # Composite value (path/float2/float3): same field primitive,
        # read-only — editing these still happens on the node itself.
        editor = build_text_field()
        editor.setReadOnly(True)
        return editor

    # ── Node -> row ──────────────────────────────────────────────────────────

    def set_value_from_node(self, value) -> None:
        self._updating = True
        try:
            type_id = getattr(self.node, "TYPE_ID", None)
            if type_id in _TEXT_FIELD_TYPES:
                self.editor.setText(str(value))
            elif type_id == "bool":
                self.editor.setChecked(bool(value))
                self.editor.setText("true" if value else "false")
            elif type_id == "integer":
                self.editor.setValue(int(value))
            elif type_id == "enum":
                self.editor.blockSignals(True)
                self.editor.clear()
                if isinstance(value, dict):
                    self.editor.addItems(value.get("items", []))
                    self.editor.setCurrentText(value.get("current", ""))
                self.editor.blockSignals(False)
            else:
                self.editor.setText(_format_composite_value(value))
        finally:
            self._updating = False

    # ── Row -> node ──────────────────────────────────────────────────────────

    def _on_editor_committed(self, *_args) -> None:
        if self._updating:
            return
        type_id = getattr(self.node, "TYPE_ID", None)
        if type_id in _TEXT_FIELD_TYPES:
            self.node.set_value_state(self.editor.text())
        elif type_id == "bool":
            checked = self.editor.isChecked()
            self.editor.setText("true" if checked else "false")
            self.node.set_value_state(checked)
        elif type_id == "integer":
            self.node.set_value_state(self.editor.value())
        elif type_id == "enum":
            current = self.node.get_value_state()
            items = current.get("items", []) if isinstance(current, dict) else []
            self.node.set_value_state({"items": items, "current": self.editor.currentText()})
        win = editor_window_of(self.node)
        if win is not None:
            win.push_undo_state()


class _ResizeGrip(QWidget):
    """Thin strip along the panel's right edge — drag to resize its width.

    A dedicated child sitting on top of the panel's own layout, not a
    mousePressEvent override on the panel itself: the title bar and row
    widgets already cover the panel's full width, so a handler on the panel
    would never see a press landing on them. Living as its own widget makes
    the grip's hit area independent of whatever content the panel holds.
    """

    def __init__(self, panel: "ProjectInputsPanel"):
        super().__init__(panel)
        self._panel = panel
        self.setCursor(Qt.SizeHorCursor)
        self.setFixedWidth(PROJECT_INPUTS_PANEL_RESIZE_GRIP_WIDTH)
        self._dragging = False
        self._hovered = False
        self._drag_start_x = 0
        self._drag_start_width = 0

    def mousePressEvent(self, event):
        self._dragging = True
        self._drag_start_x = event.globalPos().x()
        self._drag_start_width = self._panel.width()
        self.update()
        event.accept()

    def mouseMoveEvent(self, event):
        if not self._dragging:
            return
        delta = event.globalPos().x() - self._drag_start_x
        new_width = max(PROJECT_INPUTS_PANEL_MIN_WIDTH,
                         min(PROJECT_INPUTS_PANEL_MAX_WIDTH, self._drag_start_width + delta))
        self._panel.resize(new_width, self._panel.height())
        event.accept()

    def mouseReleaseEvent(self, event):
        self._dragging = False
        self.update()
        event.accept()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        if self._hovered or self._dragging:
            painter = QPainter(self)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(PROJECT_INPUTS_PANEL_BORDER_COLOR)))
            line_width = 4
            x = (self.width() - line_width) // 2
            painter.drawRect(x, 0, line_width, self.height())


class ProjectInputsShadow(QWidget):
    def __init__(self, panel: "ProjectInputsPanel"):
        super().__init__(panel.parentWidget())
        self.panel = panel
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(15)
        panel.installEventFilter(self)
        if not panel.isVisibleTo(panel.parentWidget()):
            self.hide()

    def eventFilter(self, obj, event):
        if obj is self.panel:
            if event.type() in (QEvent.Move, QEvent.Resize):
                self.setGeometry(self.panel.geometry().right(), self.panel.y(), 15, self.panel.height())
            elif event.type() == QEvent.Show:
                self.setGeometry(self.panel.geometry().right(), self.panel.y(), 15, self.panel.height())
                self.show()
                self.raise_()
            elif event.type() == QEvent.Hide:
                self.hide()
        return False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        grad = QLinearGradient(0, 0, self.width(), 0)
        grad.setColorAt(0, QColor(0, 0, 0, 50))
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        painter.fillRect(self.rect(), grad)


class ProjectInputsPanel(QWidget):
    """Left sidebar listing every node marked as a project input in the active tab.

    A plain widget, not a QDockWidget and not part of any layout: it's a
    child of the central widget, positioned with an explicit setGeometry
    call and raised above the graph view (see NodeEditorWindow's
    _reposition_project_inputs_panel). Two reasons, both from user-visible
    breakage the layout-managed versions actually had:

    - QMainWindow's dock areas wrap the *entire* central widget top-to-bottom,
      so a docked panel's own title row landed flush against this frameless
      window's custom title bar (ui/title_bar.py) and could be dragged as if
      it were part of it.
    - Sharing a QHBoxLayout row with the view meant showing/hiding the panel
      resized the view on every toggle, which re-tiled the whole scene and
      visibly flashed. Floating above the view instead of squeezing it means
      opening/closing the panel never touches the view's geometry at all.
    """

    def __init__(self, window, parent=None):
        super().__init__(parent or window)
        self._window = window
        self._rows: Dict[ParamNode, _PanelRow] = {}
        self._order: List[ParamNode] = []
        self._dragging_node: Optional[ParamNode] = None
        self._stretch_row: Optional[int] = None
        self._pinned = False
        self.setObjectName("ProjectInputsPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#ProjectInputsPanel {{ background-color: {PROJECT_INPUTS_PANEL_BACKGROUND_COLOR}; "
            f"border: none; border-right: 1px solid {PROJECT_INPUTS_PANEL_BORDER_COLOR}; }}"
        )
        self.resize(PROJECT_INPUTS_PANEL_WIDTH, self.height())
        self._shadow = ProjectInputsShadow(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, PROJECT_INPUTS_PANEL_RESIZE_GRIP_WIDTH, 0)
        outer.setSpacing(0)

        title_bar = QWidget()
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(6, 2, 6, 2)
        title_label = QLabel(t("project_inputs_panel_title"))
        title_label.setStyleSheet(f"color:{TEXT_COLOR}; font-weight:bold;")
        title_layout.addWidget(title_label, 1)
        self._pin_check = InsetFillCheckBox(t("project_inputs_pin_label"))
        self._pin_check.setToolTip(t("project_inputs_pin_tooltip"))
        self._pin_check.toggled.connect(self._set_pinned)
        title_layout.addWidget(self._pin_check)
        outer.addWidget(title_bar)

        from PyQt5.QtWidgets import QScrollArea
        from ui.widgets import UnifiedScrollBar
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBar(UnifiedScrollBar())
        scroll_area.setStyleSheet("QScrollArea { background: transparent; } QScrollArea > QWidget > QWidget { background: transparent; }")

        rows_container = QWidget()
        self._layout = QGridLayout(rows_container)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setHorizontalSpacing(6)
        self._layout.setVerticalSpacing(2)
        # Column stretch: Col 2 (editor) gets stretch 1 to expand dynamically.
        self._layout.setColumnStretch(2, 1)
        
        scroll_area.setWidget(rows_container)
        outer.addWidget(scroll_area, 1)

        self._grip = _ResizeGrip(self)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._grip.setGeometry(self.width() - self._grip.width(), 0, self._grip.width(), self.height())

    def reload(self) -> None:
        """Resync the row set with the active tab's project-input nodes.

        Cheap no-op when the set hasn't changed (tab switch, undo/redo and
        plain value edits all funnel through this) — existing rows keep
        their focus/cursor instead of being torn down every keystroke. The
        user's own drag-reordering (self._order) survives this: nodes that
        are still present keep their position, new ones are appended.
        """
        scene = self._window.scene
        current_nodes = [i for i in scene.items()
                          if isinstance(i, ParamNode) and i.is_project_input()]
        current_set = set(current_nodes)
        if current_set == set(self._rows.keys()):
            return
        self._order = [n for n in self._order if n in current_set]
        for node in list(self._rows.keys()):
            if node not in current_set:
                row = self._rows.pop(node)
                for w in row.widgets():
                    self._layout.removeWidget(w)
                    w.deleteLater()
        for node in current_nodes:
            if node not in self._rows:
                self._rows[node] = _PanelRow(node, self)
                self._order.append(node)
        self._relayout_rows()

    def refresh_node(self, node: ParamNode) -> None:
        """Live-sync one row after its node's value changed on the canvas."""
        row = self._rows.get(node)
        if row:
            row.set_value_from_node(node.get_value_state())

    def _set_pinned(self, checked: bool) -> None:
        self._pinned = checked

    def is_pinned(self) -> bool:
        return self._pinned

    def is_interacting(self) -> bool:
        """True if the user is currently resizing the panel or dragging a row to reorder."""
        return self._dragging_node is not None or self._grip._dragging

    # ── Row drag-to-reorder ──────────────────────────────────────────────────

    def begin_row_drag(self, node: ParamNode) -> None:
        self._dragging_node = node

    def drag_row_to(self, node: ParamNode, global_y: int) -> None:
        if self._dragging_node is not node or node not in self._order:
            return
        rows_container = self._layout.parentWidget()
        local_y = rows_container.mapFromGlobal(QPoint(0, global_y)).y()
        idx_from = self._order.index(node)
        target_idx = len(self._order) - 1
        for i, other in enumerate(self._order):
            row = self._rows[other]
            if local_y < row.handle.y() + row.handle.height() / 2.0:
                target_idx = i
                break
        if target_idx != idx_from:
            self._order.insert(target_idx, self._order.pop(idx_from))
            self._relayout_rows()

    def end_row_drag(self) -> None:
        self._dragging_node = None

    def _relayout_rows(self) -> None:
        for row in self._rows.values():
            for w in row.widgets():
                self._layout.removeWidget(w)
        for idx, node in enumerate(self._order):
            row = self._rows[node]
            self._layout.addWidget(row.handle, idx, 0)
            self._layout.addWidget(row.label, idx, 1, Qt.AlignRight | Qt.AlignVCenter)
            self._layout.addWidget(row.editor, idx, 2)
            self._layout.addWidget(row.dot, idx, 3, Qt.AlignCenter)
        if self._stretch_row is not None:
            self._layout.setRowStretch(self._stretch_row, 0)
        self._stretch_row = len(self._order)
        self._layout.setRowStretch(self._stretch_row, 1)


class ProjectInputsHoverFilter(QObject):
    """Install once on the QApplication instance (see nodeRC.py) — reveals an
    unpinned Project Inputs panel when the cursor nears the window's left
    edge, and hides it again once the cursor clears the panel (Ст.0.2: the
    panel is available without a click, but doesn't sit open eating canvas
    space when nobody asked for it).
    """

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseMove:
            self._sync_all_windows()
        return super().eventFilter(obj, event)

    @staticmethod
    def _sync_all_windows():
        from ui.editor_window import NodeEditorWindow  # deferred: avoids an import cycle

        app = QApplication.instance()
        if not app:
            return
        for widget in app.topLevelWidgets():
            if isinstance(widget, NodeEditorWindow):
                ProjectInputsHoverFilter._sync_window(widget)

    @staticmethod
    def _sync_window(window):
        panel = getattr(window, "project_inputs_panel", None)
        if panel is None or panel.is_pinned() or panel.is_interacting():
            return
        local = window.mapFromGlobal(QCursor.pos())
        if not window.rect().contains(local):
            return
        if panel.isVisibleTo(window):
            focus_widget = QApplication.focusWidget()
            focus_inside_panel = focus_widget is not None and panel.isAncestorOf(focus_widget)
            if local.x() > panel.width() + PROJECT_INPUTS_PANEL_HOVER_HIDE_MARGIN and not focus_inside_panel:
                panel.setVisible(False)
        elif local.x() <= PROJECT_INPUTS_PANEL_HOVER_REVEAL_MARGIN:
            panel.setVisible(True)
