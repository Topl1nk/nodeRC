"""widgets.py — Standalone UI Primitives

Custom Qt widgets that have no dependency on graph items (nodes, sockets,
connections). They can be used by any graph item or dialog.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QCheckBox, QStyle, QScrollBar
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor
from PyQt5.QtCore import QRect, Qt

from configuration import (
    NODE_SELECTED_COLOR, TEXT_COLOR,
    CHECKBOX_FILL_INSET, CHECKBOX_INDICATOR_SIZE, CHECKBOX_LABEL_SPACING,
)
from ui.theme import DEFAULT_WIDGET_PALETTE, WIDGET_FONT, DEFAULT_FIELD_BG, NODE_BORDER_COLOR


def suppress_default_selection_chrome(option) -> None:
    """Clear State_Selected on a paint() option before delegating to the base
    class paint — every selectable graph item (nodes, connections, group
    frames) draws its own selection outline and must not also get Qt's
    default dashed-rectangle selection decoration doubled on top of it."""
    if option.state & QStyle.State_Selected:
        option.state &= ~QStyle.State_Selected


class InsetFillCheckBox(QCheckBox):
    """QCheckBox whose checked state shows a smaller inner filled square.

    The outer indicator border stays the same in either state; the fill on
    ``:checked`` is inset by CHECKBOX_FILL_INSET on every side.

    Indicator colors are stored as instance attributes so the node tinting
    system can update them via ``update_indicator_colors()`` without relying
    on QSS ``::indicator`` rules (which are ignored by the custom paintEvent).
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._ind_border_color: str = DEFAULT_WIDGET_PALETTE.border
        self._ind_bg_color: str = DEFAULT_WIDGET_PALETTE.indicator_bg
        self.setStyleSheet(
            f"QCheckBox{{font:{WIDGET_FONT};color:{TEXT_COLOR};"
            f"background:{DEFAULT_WIDGET_PALETTE.button_bg};"
            f"spacing:{CHECKBOX_LABEL_SPACING}px;}}"
        )

    def update_indicator_colors(self, border: str, bg: str) -> None:
        """Update the indicator's border and background to tinted values."""
        self._ind_border_color = border
        self._ind_bg_color = bg
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        size = CHECKBOX_INDICATOR_SIZE
        ind_y = (self.height() - size) // 2
        ind_rect = QRect(0, ind_y, size - 1, size - 1)

        border_color = QColor(
            NODE_SELECTED_COLOR if self.underMouse() else self._ind_border_color
        )
        painter.setPen(QPen(border_color, 1))
        painter.setBrush(QBrush(QColor(self._ind_bg_color)))
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

class UnifiedScrollBar(QScrollBar):
    """
    A globally reused, indestructible scrollbar primitive.
    Uses dynamic stylesheet updates on enter/leave to guarantee TRUE layout
    width expansion (4px -> 8px) so no dead background space is left behind.
    Optionally allows fixed-width (expand_on_hover=False) for main views.
    """
    def __init__(self, orientation=Qt.Vertical, expand_on_hover: bool = True, parent=None):
        super().__init__(orientation, parent)
        self.expand_on_hover = expand_on_hover
        self.setCursor(Qt.ArrowCursor)
        self._hovered = False
        self._apply_style()

    def enterEvent(self, event):
        self._hovered = True
        self._apply_style()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._apply_style()
        super().leaveEvent(event)

    def _apply_style(self):
        size = 8 if (self._hovered or not self.expand_on_hover) else 4
        handle_bg = NODE_SELECTED_COLOR if self._hovered else NODE_BORDER_COLOR
        self.setStyleSheet(f"""
            QScrollBar:vertical {{
                border: none;
                background: {DEFAULT_FIELD_BG};
                width: {size}px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {handle_bg};
                min-height: 20px;
                border-radius: 0px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

            QScrollBar:horizontal {{
                border: none;
                background: {DEFAULT_FIELD_BG};
                height: {size}px;
                margin: 0px;
            }}
            QScrollBar::handle:horizontal {{
                background: {handle_bg};
                min-width: 20px;
                border-radius: 0px;
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}
        """)
