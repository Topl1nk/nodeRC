"""color_picker.py — In-App HSVA Palette Popup

Live-editing colour popup with an SV square, HSVA gradient sliders, hex entry,
preset swatches and the only-header scope flag. Emits every edit immediately so
callers repaint nodes as the user drags.
"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QLineEdit,
)
from PyQt5.QtGui import QPainter, QColor, QLinearGradient, QBrush, QPen, QPixmap
from PyQt5.QtCore import Qt, pyqtSignal

from localization import t
from configuration import (
    COLOR_PRESETS, TEXT_COLOR, NODE_SELECTED_COLOR, UI_FONT_FAMILY,
    COLOR_PICKER_WIDTH, COLOR_PICKER_PADDING, COLOR_PICKER_ROW_HEIGHT,
    COLOR_PICKER_SQUARE_HEIGHT, COLOR_PICKER_SLIDER_HEIGHT,
    COLOR_PICKER_PREVIEW_SIZE, COLOR_PICKER_PRESET_SIZE,
    COLOR_PICKER_PRESET_COLS, COLOR_PICKER_PRESET_GAP,
    DEFAULT_HEADER_COLOR,
)
from ui.theme import BUTTON_BG_COLOR, NODE_BORDER_COLOR, PUSHBTN_QSS


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


class PresetButton(QPushButton):
    """Custom QPushButton for preset swatches with checkerboard support for transparent colors."""
    def __init__(self, color: QColor, parent=None):
        super().__init__(parent)
        self.color = color
        self.hovered = False
        self.setFixedSize(COLOR_PICKER_PRESET_SIZE, COLOR_PICKER_PRESET_SIZE)
        self.setCursor(Qt.PointingHandCursor)

    def enterEvent(self, event):
        self.hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        rect = self.rect()

        # Draw checkerboard pattern if the color has any transparency
        if self.color.alpha() < 255:
            ch_size = 4
            for x in range(0, rect.width(), ch_size):
                for y in range(0, rect.height(), ch_size):
                    bg_col = QColor(255, 255, 255) if (x // ch_size + y // ch_size) % 2 == 0 else QColor(180, 180, 180)
                    painter.fillRect(x, y, ch_size, ch_size, bg_col)

        # Draw the solid/translucent color on top
        painter.fillRect(rect, self.color)

        # Draw border
        pen_color = QColor(NODE_SELECTED_COLOR) if self.hovered else QColor(0, 0, 0)
        painter.setPen(QPen(pen_color, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect.adjusted(0, 0, -1, -1))
        if self.hovered:
            painter.drawRect(rect.adjusted(1, 1, -2, -2))


class ColorPickerPopup(QWidget):
    def __init__(self, on_color_selected, initial_color=None, on_close=None,
                 initial_only_header=False, on_only_header_changed=None,
                 on_reset=None, parent=None):
        """Custom in-app palette popup.

        ``on_color_selected`` is invoked as ``(hex_color, only_header)`` on every
        live color edit. ``on_only_header_changed``, when provided, is called as
        ``(only_header)`` when the checkbox is toggled WITHOUT emitting a color
        change — callers use this to update scope across multi-node selections
        without forcing every node to adopt the picker's current color.
        ``on_reset``, when provided, is called with no arguments when the Reset
        button is clicked; it must restore the target(s) to their default
        color and return ``(hex_color, only_header)`` so the popup can sync
        its own controls to the new state.
        """
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.on_color_selected = on_color_selected
        self.on_only_header_changed = on_only_header_changed
        self.on_reset = on_reset
        self.on_close = on_close
        self.setAttribute(Qt.WA_DeleteOnClose)
        # Object name scopes the popup-level border to the popup root — without
        # the #ColorPickerPopup selector, every child QWidget would inherit a
        # 1-px border and stamp ugly rectangles around every label and swatch.
        self.setObjectName("ColorPickerPopup")
        # Popup background uses the editor's button-family colour so the picker
        # reads as part of the same chrome as buttons and node bodies, not as a
        # deeper canvas layer.
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

        self.current_color = QColor(initial_color or DEFAULT_HEADER_COLOR)
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
        from ui.graph_items import InsetFillCheckBox
        self.only_header_check = InsetFillCheckBox(t("color_only_header"))
        self.only_header_check.setChecked(self._only_header)
        self.only_header_check.setFixedHeight(COLOR_PICKER_ROW_HEIGHT)
        self.only_header_check.toggled.connect(self._on_only_header_toggled)
        hex_row.addWidget(self.only_header_check)

        # Restores whatever color this type/node would have if the user had
        # never opened the picker — same restore target `only_header_check`
        # ends up reflecting after the reset.
        self.reset_button = QPushButton(t("color_reset"))
        self.reset_button.setFixedHeight(COLOR_PICKER_ROW_HEIGHT)
        self.reset_button.setStyleSheet(PUSHBTN_QSS)
        self.reset_button.clicked.connect(self._on_reset_clicked)
        hex_row.addWidget(self.reset_button)
        hex_row.addStretch()
        main_layout.addLayout(hex_row)

        def make_preset_callback(hex_str):
            return lambda checked=False: self.set_from_hex(hex_str)

        presets_layout = QGridLayout()
        presets_layout.setSpacing(COLOR_PICKER_PRESET_GAP)

        alphas = [1.0, 0.66, 0.33]
        base_palette = COLOR_PRESETS[:COLOR_PICKER_PRESET_COLS]

        for row_idx, alpha in enumerate(alphas):
            for col_idx, base_hex in enumerate(base_palette):
                c = QColor(base_hex)
                c.setAlpha(int(alpha * 255))
                color_hex = c.name(QColor.HexArgb)

                btn = PresetButton(c)
                btn.clicked.connect(make_preset_callback(color_hex))
                presets_layout.addWidget(btn, row_idx, col_idx)

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
            self._emit_color('only_header')

    def _on_reset_clicked(self):
        if self.on_reset is None:
            return
        result = self.on_reset()
        if not result:
            return
        hex_color, only_header = result
        self.current_color = QColor(hex_color)
        self._only_header = bool(only_header)
        self.only_header_check.blockSignals(True)
        self.only_header_check.setChecked(self._only_header)
        self.only_header_check.blockSignals(False)
        self._sync_to_current_color()

    def set_from_hex(self, hex_str):
        c = QColor(hex_str)
        if c.isValid():
            self.current_color = c
            self._sync_to_current_color()
            self._emit_color('preset')

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
        self._emit_color('sv')

    def _on_slider_changed(self, comp, val):
        h = self.hue_slider.value if comp != 'h' else val
        s = self.sat_slider.value if comp != 's' else val
        v = self.val_slider.value if comp != 'v' else val
        a = self.alpha_slider.value if comp != 'a' else val

        self.current_color = QColor.fromHsvF(h, s, v, a)
        self._sync_to_current_color()
        self._emit_color(comp)

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
        self._emit_color('hex')

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
                if (x // 4 + y // 4) % 2 == 0:
                    p.fillRect(x, y, 4, 4, QColor(150, 150, 150))
        p.fillRect(0, 0, 24, 24, self.current_color)
        p.end()

        self.preview.setPixmap(pix)

    def _emit_color(self, changed_component=None):
        # Always emit HexArgb (9 chars) so we can distinguish it from legacy #RRGGBB (7 chars).
        # Pair with the only-header flag so callers can apply scope without polling.
        color_str = self.current_color.name(QColor.HexArgb)
        self.on_color_selected(color_str, self._only_header, changed_component)

    def hideEvent(self, event):
        super().hideEvent(event)
        if self.on_close:
            self.on_close()
