from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit, QCheckBox
)
from PyQt5.QtGui import (
    QPainter, QColor, QLinearGradient, QBrush, QPen, QPixmap
)
from PyQt5.QtCore import Qt, pyqtSignal

import colorsys
from localization import t
from configuration import (
    COLOR_PRESETS, CANVAS_BACKGROUND_COLOR, TEXT_COLOR,
    NODE_SELECTED_COLOR, UI_FONT_FAMILY,
    COLOR_PICKER_WIDTH, COLOR_PICKER_PADDING, COLOR_PICKER_ROW_HEIGHT,
    COLOR_PICKER_SQUARE_HEIGHT, COLOR_PICKER_SLIDER_HEIGHT,
    COLOR_PICKER_PREVIEW_SIZE, COLOR_PICKER_PRESET_SIZE,
    COLOR_PICKER_PRESET_COLS, COLOR_PICKER_PRESET_GAP,
    DEFAULT_HEADER_COLOR, TINT_BODY_DARKEN, TINT_FIELD_DARKEN, TINT_BUTTON_DARKEN,
    TINT_HOVER_DARKEN, TINT_PRESSED_DARKEN, TINT_SELECTION_LIGHTEN,
    TINT_BORDER_MIN_LUMINANCE, TINT_BORDER_LIGHTEN_STEP,
    TEXT_MUTED_COLOR, BUTTON_TEXT_COLOR, BROWSE_BTN_WIDTH, VECTOR_AXIS_LABEL_COLOR
)

def relative_luminance_hex(hex_str: str) -> float:
    """Perceived brightness 0–255 using the standard Rec. 601 weights."""
    hex_str = hex_str.lstrip('#')
    if len(hex_str) == 8:
        hex_str = hex_str[2:]
    if len(hex_str) != 6:
        return 0.0
    r = int(hex_str[0:2], 16)
    g = int(hex_str[2:4], 16)
    b = int(hex_str[4:6], 16)
    return 0.299 * r + 0.587 * g + 0.114 * b

def adjust_hex_color(hex_str: str, factor: float, method: str = "darker") -> str:
    """Adjust color brightness (factor > 100 darkens or lightens)."""
    hex_str = hex_str.lstrip('#')
    alpha = ""
    if len(hex_str) == 8:
        alpha = hex_str[:2]
        hex_str = hex_str[2:]
    if len(hex_str) != 6:
        return "#" + hex_str
        
    r = int(hex_str[0:2], 16) / 255.0
    g = int(hex_str[2:4], 16) / 255.0
    b = int(hex_str[4:6], 16) / 255.0
    
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if method == "darker":
        v = v / (factor / 100.0)
    else: # lighter
        v = min(1.0, v * (factor / 100.0))
        
    r_new, g_new, b_new = colorsys.hsv_to_rgb(h, s, v)
    r_hex = f"{int(r_new * 255.0):02X}"
    g_hex = f"{int(g_new * 255.0):02X}"
    b_hex = f"{int(b_new * 255.0):02X}"
    return f"#{alpha}{r_hex}{g_hex}{b_hex}"

def brightened_for_canvas_hex(hex_str: str) -> str:
    """Lighten hex_str until it crosses the visible-on-canvas luminance floor."""
    if relative_luminance_hex(hex_str) >= TINT_BORDER_MIN_LUMINANCE:
        return hex_str
        
    hex_str_clean = hex_str.lstrip('#')
    alpha = ""
    if len(hex_str_clean) == 8:
        alpha = hex_str_clean[:2]
        hex_str_clean = hex_str_clean[2:]
    if len(hex_str_clean) != 6:
        return hex_str
        
    r = int(hex_str_clean[0:2], 16) / 255.0
    g = int(hex_str_clean[2:4], 16) / 255.0
    b = int(hex_str_clean[4:6], 16) / 255.0
    
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if v == 0.0:
        v = 0.1
        if h < 0:
            h = 0.0
            
    for _ in range(16):
        r_temp, g_temp, b_temp = colorsys.hsv_to_rgb(h, s, v)
        temp_hex = f"#{alpha}{int(r_temp*255.0):02X}{int(g_temp*255.0):02X}{int(b_temp*255.0):02X}"
        if relative_luminance_hex(temp_hex) >= TINT_BORDER_MIN_LUMINANCE:
            return temp_hex
        v = min(1.0, v * (TINT_BORDER_LIGHTEN_STEP / 100.0))
        
    r_temp, g_temp, b_temp = colorsys.hsv_to_rgb(h, s, v)
    return f"#{alpha}{int(r_temp*255.0):02X}{int(g_temp*255.0):02X}{int(b_temp*255.0):02X}"

NODE_BORDER_COLOR = brightened_for_canvas_hex(DEFAULT_HEADER_COLOR)
GROUP_FRAME_BORDER_COLOR = NODE_BORDER_COLOR
BUTTON_BG_COLOR = adjust_hex_color(DEFAULT_HEADER_COLOR, TINT_BUTTON_DARKEN)
BUTTON_HOVER_COLOR = adjust_hex_color(DEFAULT_HEADER_COLOR, TINT_HOVER_DARKEN)
BUTTON_PRESSED_COLOR = adjust_hex_color(DEFAULT_HEADER_COLOR, TINT_PRESSED_DARKEN)

DEFAULT_FIELD_BG = adjust_hex_color(DEFAULT_HEADER_COLOR, TINT_FIELD_DARKEN)
DEFAULT_SELECTION_ACCENT = adjust_hex_color(DEFAULT_HEADER_COLOR, TINT_SELECTION_LIGHTEN, "lighter")

FIELD_QSS = (
    f"QLineEdit{{"
    f"border:1px solid {NODE_BORDER_COLOR};"
    f"background:{DEFAULT_FIELD_BG};"
    f"color:{TEXT_COLOR};"
    f"border-radius:0px;"
    f"padding:2px 4px;"
    f"font:9pt {UI_FONT_FAMILY};"
    f"}}"
    f"QLineEdit:read-only{{"
    f"color:{TEXT_MUTED_COLOR};"
    f"}}"
)

COMBOBOX_QSS = (
    f"QComboBox{{border:1px solid {NODE_BORDER_COLOR};background:{DEFAULT_FIELD_BG};"
    f"color:{TEXT_COLOR};border-radius:0px;padding:2px 4px;font:9pt {UI_FONT_FAMILY};combobox-popup:0;}}"
    f"QComboBox::drop-down{{border-left:1px solid {NODE_BORDER_COLOR};"
    f"width:{BROWSE_BTN_WIDTH}px;background:{BUTTON_BG_COLOR};}}"
    f"QComboBox::drop-down:hover{{background:{BUTTON_HOVER_COLOR};border-color:{NODE_SELECTED_COLOR};}}"
    f"QComboBox QAbstractItemView{{border:1px solid {NODE_BORDER_COLOR};"
    f"background:{DEFAULT_FIELD_BG};color:{TEXT_COLOR};"
    f"selection-background-color:{DEFAULT_SELECTION_ACCENT};selection-color:{DEFAULT_FIELD_BG};outline:0px;}}"
    f"QComboBox QAbstractItemView::item:hover{{background-color:{DEFAULT_SELECTION_ACCENT};color:{DEFAULT_FIELD_BG};}}"
    f"QComboBox QAbstractItemView::item:selected{{background-color:{DEFAULT_SELECTION_ACCENT};color:{DEFAULT_FIELD_BG};}}"
    f"QScrollBar:vertical{{border:none;background:{DEFAULT_FIELD_BG};width:8px;margin:0px;}}"
    f"QScrollBar::handle:vertical{{background:{NODE_BORDER_COLOR};min-height:20px;border-radius:0px;}}"
    f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0px;}}"
    f"QComboBox[connected=\"true\"]{{color:{TEXT_MUTED_COLOR};}}"
    f"QComboBox[connected=\"true\"] QLineEdit{{color:{TEXT_MUTED_COLOR};}}"
    f"QComboBox[connected=\"true\"]::drop-down{{width:0px;border:none;}}"
)

SPINBOX_QSS = (
    f"QSpinBox{{border:1px solid {NODE_BORDER_COLOR};background:{DEFAULT_FIELD_BG};"
    f"color:{TEXT_COLOR};border-radius:0px;padding:2px;font:9pt {UI_FONT_FAMILY};}}"
    f"QSpinBox::up-button{{background:{BUTTON_BG_COLOR};"
    f"border-left:1px solid {NODE_BORDER_COLOR};"
    f"border-bottom:1px solid {NODE_BORDER_COLOR};width:16px;}}"
    f"QSpinBox::down-button{{background:{BUTTON_BG_COLOR};"
    f"border-left:1px solid {NODE_BORDER_COLOR};width:16px;}}"
    f"QSpinBox::up-button:hover,QSpinBox::down-button:hover{{"
    f"background:{BUTTON_HOVER_COLOR};border-color:{NODE_SELECTED_COLOR};}}"
    f"QSpinBox:hover{{border-color:{NODE_SELECTED_COLOR};}}"
)

CHECKBOX_QSS = (
    f"QCheckBox{{font:9pt {UI_FONT_FAMILY};color:{TEXT_COLOR};background:{BUTTON_BG_COLOR};spacing:6px;}}"
    f"QCheckBox::indicator{{width:13px;height:13px;"
    f"border:1px solid {NODE_BORDER_COLOR};background:{DEFAULT_FIELD_BG};}}"
    f"QCheckBox::indicator:checked{{background:{NODE_SELECTED_COLOR};border-color:{NODE_SELECTED_COLOR};}}"
    f"QCheckBox::indicator:hover{{border-color:{NODE_SELECTED_COLOR};}}"
)

TOOLBTN_QSS = (
    f"QToolButton{{background:{BUTTON_BG_COLOR};color:{BUTTON_TEXT_COLOR};"
    f"border:1px solid {NODE_BORDER_COLOR};border-radius:0px;font:9pt {UI_FONT_FAMILY};}}"
    f"QToolButton:hover{{background:{BUTTON_HOVER_COLOR};border-color:{NODE_SELECTED_COLOR};}}"
    f"QToolButton:pressed{{background:{BUTTON_PRESSED_COLOR};}}"
)

PUSHBTN_QSS = (
    f"QPushButton{{background:{BUTTON_BG_COLOR};color:{BUTTON_TEXT_COLOR};"
    f"border:1px solid {NODE_BORDER_COLOR};border-radius:0px;"
    f"padding:5px 8px;font:bold 9pt {UI_FONT_FAMILY};}}"
    f"QPushButton:hover{{background:{BUTTON_HOVER_COLOR};border-color:{NODE_SELECTED_COLOR};}}"
    f"QPushButton:pressed{{background:{BUTTON_PRESSED_COLOR};}}"
)

VECTOR_TOGGLE_QSS = (
    f"QToolButton{{color:{TEXT_MUTED_COLOR};font:bold 8pt;padding:0px 2px;border:none;background:transparent;}}"
    f"QToolButton:hover{{color:{NODE_SELECTED_COLOR};}}"
)

VECTOR_AXIS_LABEL_QSS = f"color:{VECTOR_AXIS_LABEL_COLOR};font:9pt {UI_FONT_FAMILY};"

CONTEXT_MENU_STYLESHEET = f"""
QMenu {{
    background:{BUTTON_BG_COLOR}; color:{TEXT_COLOR};
    border:1px solid {NODE_BORDER_COLOR}; border-radius:0px;
    padding:4px 2px; font:9pt {UI_FONT_FAMILY};
}}
QMenu::item {{ padding:4px 20px 4px 10px; border-radius:0px; }}
QMenu::item:selected {{ background:{BUTTON_HOVER_COLOR}; border:1px solid {NODE_SELECTED_COLOR}; }}
QMenu::item:disabled {{ color:{NODE_BORDER_COLOR}; }}
QMenu::separator {{ height:1px; background:{NODE_BORDER_COLOR}; margin:3px 8px; }}
QMenu::icon {{ padding-left:6px; }}
"""

SEARCH_DIALOG_STYLESHEET = f"""
QDialog {{
    background-color: {CANVAS_BACKGROUND_COLOR};
    border: 1px solid {NODE_BORDER_COLOR};
}}
QLineEdit {{
    background-color: {BUTTON_BG_COLOR};
    color: {TEXT_COLOR};
    border: 1px solid {NODE_BORDER_COLOR};
    padding: 4px;
    font-family: {UI_FONT_FAMILY}, monospace;
}}
QLineEdit:focus {{
    border: 1px solid {NODE_SELECTED_COLOR};
}}
QTreeWidget {{
    background-color: transparent;
    color: {TEXT_COLOR};
    border: none;
    font-family: {UI_FONT_FAMILY}, monospace;
    outline: none;
    selection-background-color: {NODE_SELECTED_COLOR};
    selection-color: {CANVAS_BACKGROUND_COLOR};
}}
QTreeWidget::item:hover, QTreeWidget::item:selected {{
    background-color: {NODE_SELECTED_COLOR};
    color: {CANVAS_BACKGROUND_COLOR};
}}
QGraphicsView#previewView {{
    background: transparent;
    border: none;
}}
QLabel#descriptionLabel {{
    color: {TEXT_MUTED_COLOR};
    font-family: {UI_FONT_FAMILY}, monospace;
    padding: 6px;
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 14px;
    margin: 0px 0px 0px 0px;
}}
QScrollBar::handle:vertical {{
    background: {NODE_BORDER_COLOR};
    min-height: 20px;
    border-radius: 7px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}
QFrame#descFrame {{
    border-top: 1px solid {NODE_BORDER_COLOR};
    border-bottom: 1px solid {NODE_BORDER_COLOR};
    background: transparent;
}}
"""


class GradientSlider(QWidget):
    valueChanged = pyqtSignal(float)

    def __init__(self, color_type='hue', parent=None):
        super().__init__(parent)
        self.setFixedHeight(COLOR_PICKER_SLIDER_HEIGHT)
        self.color_type = color_type
        self.value = 0.5
        self.hsv = (0.0, 1.0, 1.0, 1.0)
        self.setCursor(Qt.PointingHandCursor)

    def set_hsv(self, h, s, v, a):
        self.hsv = (h, s, v, a)
        self.update()

    def set_value(self, val):
        self.value = max(0.0, min(1.0, val))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        rect = self.rect()
        gradient = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.top())
        
        h, s, v, a = self.hsv
        
        if self.color_type == 'hue':
            for i in range(7):
                gradient.setColorAt(i / 6.0, QColor.fromHsvF(i / 6.0, 1.0, 1.0, 1.0))
        elif self.color_type == 'sat':
            gradient.setColorAt(0.0, QColor.fromHsvF(h, 0.0, v, 1.0))
            gradient.setColorAt(1.0, QColor.fromHsvF(h, 1.0, v, 1.0))
        elif self.color_type == 'val':
            gradient.setColorAt(0.0, QColor.fromHsvF(h, s, 0.0, 1.0))
            gradient.setColorAt(1.0, QColor.fromHsvF(h, s, 1.0, 1.0))
        elif self.color_type == 'alpha':
            ch_size = 4
            for x in range(0, rect.width(), ch_size):
                for y in range(0, rect.height(), ch_size):
                    color = QColor(100, 100, 100) if (x // ch_size + y // ch_size) % 2 == 0 else QColor(150, 150, 150)
                    painter.fillRect(x, y, ch_size, ch_size, color)
            gradient.setColorAt(0.0, QColor.fromHsvF(h, s, v, 0.0))
            gradient.setColorAt(1.0, QColor.fromHsvF(h, s, v, 1.0))

        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, 3, 3)

        handle_x = int(self.value * (rect.width() - 8)) + 4
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(handle_x - 4, rect.center().y() - 4, 8, 8)
        painter.setPen(QPen(QColor(0, 0, 0), 1))
        painter.drawEllipse(handle_x - 5, rect.center().y() - 5, 10, 10)

    def _update_from_mouse(self, pos):
        val = (pos.x() - 4) / (self.width() - 8)
        val = max(0.0, min(1.0, val))
        self.set_value(val)
        self.valueChanged.emit(val)

    def mousePressEvent(self, event):
        self._update_from_mouse(event.pos())

    def mouseMoveEvent(self, event):
        self._update_from_mouse(event.pos())


class ColorSquare(QWidget):
    colorChanged = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Fixed height keeps the popup's vertical rhythm; width stretches with
        # the popup so the square fills the available content row edge-to-edge.
        self.setFixedHeight(COLOR_PICKER_SQUARE_HEIGHT)
        self.setMinimumWidth(0)
        self.hue = 0.0
        self.sat = 1.0
        self.val = 1.0
        self.setCursor(Qt.CrossCursor)

    def set_hue(self, h):
        self.hue = h
        self.update()

    def set_sv(self, s, v):
        self.sat = s
        self.val = v
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self.rect()
        
        painter.fillRect(rect, QColor.fromHsvF(self.hue, 1.0, 1.0))
        
        sat_grad = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.top())
        sat_grad.setColorAt(0.0, QColor(255, 255, 255, 255))
        sat_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillRect(rect, sat_grad)
        
        val_grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        val_grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        val_grad.setColorAt(1.0, QColor(0, 0, 0, 255))
        painter.fillRect(rect, val_grad)
        
        cx = int(self.sat * rect.width())
        cy = int((1.0 - self.val) * rect.height())
        
        painter.setPen(QPen(QColor(0, 0, 0), 2))
        painter.drawEllipse(cx - 5, cy - 5, 10, 10)
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.drawEllipse(cx - 4, cy - 4, 8, 8)

    def _update_from_mouse(self, pos):
        s = pos.x() / self.width()
        v = 1.0 - (pos.y() / self.height())
        s = max(0.0, min(1.0, s))
        v = max(0.0, min(1.0, v))
        self.set_sv(s, v)
        self.colorChanged.emit(s, v)

    def mousePressEvent(self, event):
        self._update_from_mouse(event.pos())

    def mouseMoveEvent(self, event):
        self._update_from_mouse(event.pos())


class ColorPickerPopup(QWidget):
    def __init__(self, on_color_selected, initial_color=None, on_close=None,
                 initial_only_header=False, on_only_header_changed=None, parent=None):
        """Custom in-app palette popup.

        ``on_color_selected`` is invoked as ``(hex_color, only_header)`` on every
        live color edit. ``on_only_header_changed``, when provided, is called as
        ``(only_header)`` when the checkbox is toggled WITHOUT emitting a color
        change — callers use this to update scope across multi-node selections
        without forcing every node to adopt the picker's current color.
        """
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.on_color_selected = on_color_selected
        self.on_only_header_changed = on_only_header_changed
        self.on_close = on_close
        self.setAttribute(Qt.WA_DeleteOnClose)
        # Object name scopes the popup-level border to the popup root — without
        # the #ColorPickerPopup selector, every child QWidget would inherit a
        # 1-px border and stamp ugly rectangles around every label and swatch.
        self.setObjectName("ColorPickerPopup")
        # Popup background uses the editor's button-family colour (BUTTON_BG_COLOR
        # = #0A315C) so the picker reads as part of the same chrome as buttons and
        # node bodies, not as a deeper canvas layer.
        self.setStyleSheet(
            f"#ColorPickerPopup {{"
            f"  background-color: {BUTTON_BG_COLOR};"
            f"  border: 1px solid {NODE_BORDER_COLOR};"
            f"}}"
            f"#ColorPickerPopup QWidget {{"
            f"  color: {TEXT_COLOR};"
            f"  font-family: {UI_FONT_FAMILY};"
            f"  border: none;"
            f"  background: transparent;"
            f"}}"
        )

        self.current_color = QColor(initial_color or "#3A76B8")
        self._only_header = bool(initial_only_header)

        self.setFixedWidth(COLOR_PICKER_WIDTH)

        main_layout = QVBoxLayout(self)
        pad = COLOR_PICKER_PADDING
        main_layout.setContentsMargins(pad, pad, pad, pad)
        main_layout.setSpacing(6)

        self.square = ColorSquare()
        main_layout.addWidget(self.square)

        self.hue_slider = GradientSlider('hue')
        self.sat_slider = GradientSlider('sat')
        self.val_slider = GradientSlider('val')
        self.alpha_slider = GradientSlider('alpha')

        for label_text, slider in [("H:", self.hue_slider), ("S:", self.sat_slider),
                                   ("V:", self.val_slider), ("A:", self.alpha_slider)]:
            row = QHBoxLayout()
            row.setSpacing(4)
            lbl = QLabel(label_text)
            lbl.setFixedWidth(14)
            lbl.setAlignment(Qt.AlignCenter)
            row.addWidget(lbl)
            row.addWidget(slider)
            main_layout.addLayout(row)

        hex_row = QHBoxLayout()
        hex_row.setSpacing(8)

        self.preview = QLabel()
        self.preview.setFixedSize(COLOR_PICKER_PREVIEW_SIZE, COLOR_PICKER_PREVIEW_SIZE)
        # The preview needs its own visible border because the scoped popup
        # stylesheet strips inherited borders from every inner widget.
        self.preview.setStyleSheet(f"border: 1px solid {NODE_BORDER_COLOR};")
        hex_row.addWidget(self.preview)

        # HEX label and input live in a zero-gap subgroup so they read as one
        # control; the label has no border (scoped QSS handles that).
        hex_group = QHBoxLayout()
        hex_group.setSpacing(0)
        hex_label = QLabel("HEX:")
        hex_label.setFixedHeight(COLOR_PICKER_ROW_HEIGHT)
        hex_label.setAlignment(Qt.AlignVCenter)
        hex_group.addWidget(hex_label)

        # No '#' shown; the field accepts AARRGGBB or RRGGBB with or without it
        # and reformats on the fly. Width fits 8 hex digits exactly.
        font_metrics = self.fontMetrics()
        hex_field_width = font_metrics.horizontalAdvance("AABBCCDD") + 14
        self.hex_input = QLineEdit()
        self.hex_input.setFixedWidth(hex_field_width)
        self.hex_input.setFixedHeight(COLOR_PICKER_ROW_HEIGHT)
        self.hex_input.setMaxLength(9)   # one extra slot tolerates a leading '#'
        self.hex_input.setStyleSheet(
            f"background: #111;"
            f"border: 1px solid {NODE_BORDER_COLOR};"
            f"color: {TEXT_COLOR};"
            f"padding: 1px 4px;"
        )
        hex_group.addWidget(self.hex_input)
        hex_row.addLayout(hex_group)

        # Same checkbox primitive the [B] Boolean param node uses, so the
        # picker's flag reads as a first-class part of the editor's vocabulary.
        from widgets import InsetFillCheckBox
        self.only_header_check = InsetFillCheckBox(t("color_only_header"))
        self.only_header_check.setChecked(self._only_header)
        self.only_header_check.setFixedHeight(COLOR_PICKER_ROW_HEIGHT)
        self.only_header_check.toggled.connect(self._on_only_header_toggled)
        hex_row.addWidget(self.only_header_check)
        hex_row.addStretch()
        main_layout.addLayout(hex_row)

        def make_preset_callback(hex_str):
            return lambda checked=False: self.set_from_hex(hex_str)

        presets_layout = QGridLayout()
        presets_layout.setSpacing(COLOR_PICKER_PRESET_GAP)
        for i, color_hex in enumerate(COLOR_PRESETS):
            btn = QPushButton()
            btn.setFixedSize(COLOR_PICKER_PRESET_SIZE, COLOR_PICKER_PRESET_SIZE)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{"
                f"  background-color: {color_hex};"
                f"  border: 1px solid #000;"
                f"  border-radius: 2px;"
                f"}}"
                f"QPushButton:hover {{"
                f"  border: 1px solid {NODE_SELECTED_COLOR};"
                f"}}"
            )
            btn.clicked.connect(make_preset_callback(color_hex))
            presets_layout.addWidget(btn, i // COLOR_PICKER_PRESET_COLS,
                                     i % COLOR_PICKER_PRESET_COLS)

        main_layout.addLayout(presets_layout)
        
        self.square.colorChanged.connect(self._on_square_changed)
        self.hue_slider.valueChanged.connect(lambda v: self._on_slider_changed('h', v))
        self.sat_slider.valueChanged.connect(lambda v: self._on_slider_changed('s', v))
        self.val_slider.valueChanged.connect(lambda v: self._on_slider_changed('v', v))
        self.alpha_slider.valueChanged.connect(lambda v: self._on_slider_changed('a', v))
        # Live application: every keystroke commits if it parses as a colour.
        self.hex_input.textChanged.connect(self._on_hex_text_changed)

        self._sync_to_current_color()

    def _on_only_header_toggled(self, checked: bool):
        self._only_header = bool(checked)
        if self.on_only_header_changed is not None:
            # Scope-only change: let the caller decide per-node color; do not
            # broadcast the picker's current color to nodes that may have a
            # different color of their own.
            self.on_only_header_changed(checked)
        else:
            # Single-node path: re-emit so the node repaints with the new scope.
            self._emit_color()

    def set_from_hex(self, hex_str):
        c = QColor(hex_str)
        if c.isValid():
            self.current_color = c
            self._sync_to_current_color()
            self._emit_color()

    def _sync_to_current_color(self, write_hex: bool = True):
        h = max(0.0, self.current_color.hsvHueF())
        s = self.current_color.hsvSaturationF()
        v = self.current_color.valueF()
        a = self.current_color.alphaF()

        self.square.blockSignals(True)
        self.square.set_hue(h)
        self.square.set_sv(s, v)
        self.square.blockSignals(False)

        for slider, val in [(self.hue_slider, h), (self.sat_slider, s), (self.val_slider, v), (self.alpha_slider, a)]:
            slider.blockSignals(True)
            slider.set_value(val)
            slider.set_hsv(h, s, v, a)
            slider.blockSignals(False)

        # Refresh the swatch always; only refresh the hex text when the change
        # didn't originate from the hex field itself (avoids stomping the caret).
        self._update_preview(write_hex=write_hex)

    def _on_square_changed(self, s, v):
        h = self.hue_slider.value
        a = self.alpha_slider.value
        self.current_color = QColor.fromHsvF(h, s, v, a)
        self._sync_to_current_color()
        self._emit_color()
        
    def _on_slider_changed(self, comp, val):
        h = self.hue_slider.value if comp != 'h' else val
        s = self.sat_slider.value if comp != 's' else val
        v = self.val_slider.value if comp != 'v' else val
        a = self.alpha_slider.value if comp != 'a' else val
        
        self.current_color = QColor.fromHsvF(h, s, v, a)
        self._sync_to_current_color()
        self._emit_color()

    def _on_hex_text_changed(self, text: str):
        # Accept "abcdef", "#abcdef", "AARRGGBB", or "#AARRGGBB" — auto-prefix '#'
        # for QColor and only commit when the parse is unambiguous (3/6/8 hex
        # digits). Anything else is treated as an in-progress edit and ignored.
        stripped = text.strip().lstrip("#")
        if len(stripped) not in (3, 6, 8) or any(ch not in "0123456789abcdefABCDEF" for ch in stripped):
            return
        c = QColor("#" + stripped)
        if not c.isValid():
            return
        self.current_color = c
        self._sync_to_current_color(write_hex=False)
        self._emit_color()

    def _update_preview(self, write_hex: bool = True):
        if write_hex:
            # Display without the leading '#' — pure hex glyphs are what the user
            # most often pastes from external tools and it shaves a glyph of width.
            if self.current_color.alpha() < 255:
                text = self.current_color.name(QColor.HexArgb)[1:]
            else:
                text = self.current_color.name()[1:]
            self.hex_input.blockSignals(True)
            self.hex_input.setText(text)
            self.hex_input.blockSignals(False)

        pix = QPixmap(24, 24)
        pix.fill(Qt.white)
        p = QPainter(pix)
        for x in range(0, 24, 4):
            for y in range(0, 24, 4):
                if (x//4 + y//4) % 2 == 0:
                    p.fillRect(x, y, 4, 4, QColor(150, 150, 150))
        p.fillRect(0, 0, 24, 24, self.current_color)
        p.end()

        self.preview.setPixmap(pix)

    def _emit_color(self):
        # Always emit HexArgb (9 chars) so we can distinguish it from legacy #RRGGBB (7 chars).
        # Pair with the only-header flag so callers can apply scope without polling.
        color_str = self.current_color.name(QColor.HexArgb)
        self.on_color_selected(color_str, self._only_header)

    def hideEvent(self, event):
        super().hideEvent(event)
        if self.on_close:
            self.on_close()
