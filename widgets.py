"""Shared UI widget primitives used by both the canvas and the color picker.

Living in its own module so both ``nodes_base`` (Bool param node) and
``color_picker`` (only-header flag) reach for one and the same checkbox class
— if the look needs to evolve, there is one place to change.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt, QRect
from PyQt5.QtGui import QBrush, QColor, QPainter, QPen
from PyQt5.QtWidgets import QCheckBox

from configuration import (
    CANVAS_BACKGROUND_COLOR, CHECKBOX_FILL_INSET, CHECKBOX_INDICATOR_SIZE,
    CHECKBOX_LABEL_SPACING, NODE_SELECTED_COLOR, TEXT_COLOR, UI_FONT_FAMILY,
)
# NODE_BORDER_COLOR and BUTTON_BG_COLOR are derived dynamically from
# DEFAULT_HEADER_COLOR in color_picker, so we import them from there.
from color_picker import BUTTON_BG_COLOR, NODE_BORDER_COLOR


class InsetFillCheckBox(QCheckBox):
    """QCheckBox whose checked state shows a smaller inner filled square.

    The outer indicator border stays the same in either state; the white fill on
    ``:checked`` is inset by CHECKBOX_FILL_INSET on every side, so the indicator
    reads as a tickbox rather than a fully painted swatch.
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        # Only the label uses the QSS — the indicator is drawn manually below.
        self.setStyleSheet(
            f"QCheckBox{{font:9pt {UI_FONT_FAMILY};color:{TEXT_COLOR};"
            f"background:{BUTTON_BG_COLOR};spacing:{CHECKBOX_LABEL_SPACING}px;}}"
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        size = CHECKBOX_INDICATOR_SIZE
        ind_y = (self.height() - size) // 2
        # Qt's rect-pen draws on the centreline; subtracting 1 from the right /
        # bottom edges keeps the visible square exactly `size`×`size` instead of
        # spilling one pixel past it.
        ind_rect = QRect(0, ind_y, size - 1, size - 1)

        border_color = QColor(
            NODE_SELECTED_COLOR if self.underMouse() else NODE_BORDER_COLOR
        )
        painter.setPen(QPen(border_color, 1))
        painter.setBrush(QBrush(QColor(CANVAS_BACKGROUND_COLOR)))
        painter.drawRect(ind_rect)

        if self.isChecked():
            inset = CHECKBOX_FILL_INSET
            inner = ind_rect.adjusted(inset, inset, -inset, -inset)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(NODE_SELECTED_COLOR)))
            painter.drawRect(inner)

        text_x = size + CHECKBOX_LABEL_SPACING
        text_rect = QRect(text_x, 0, self.width() - text_x, self.height())
        painter.setFont(self.font())
        painter.setPen(QPen(QColor(TEXT_COLOR)))
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self.text())
