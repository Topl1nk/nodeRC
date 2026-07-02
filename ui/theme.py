"""theme.py — Derived Colors and Widget Stylesheets

configuration.py owns the raw palette numbers; this module owns everything
computed from them: luminance math, canvas-visibility brightening, the widget
palette derived from a header colour, and every Qt stylesheet in the editor.

One builder produces the stylesheet set for both the default scheme and any
user-picked tint, so the two can never drift apart. The default constants
(FIELD_QSS, COMBOBOX_QSS, …) are simply the builder's output for
DEFAULT_HEADER_COLOR with the white selection highlight.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from PyQt5.QtGui import QColor

from configuration import (
    DEFAULT_HEADER_COLOR, CANVAS_BACKGROUND_COLOR,
    TEXT_COLOR, TEXT_MUTED_COLOR, BUTTON_TEXT_COLOR, NODE_SELECTED_COLOR,
    UI_FONT_FAMILY, WIDGET_FONT_PT, BROWSE_BTN_WIDTH,
    CHECKBOX_INDICATOR_SIZE, CHECKBOX_LABEL_SPACING,
    TINT_FIELD_DARKEN, TINT_BUTTON_DARKEN, TINT_HOVER_DARKEN,
    TINT_PRESSED_DARKEN, TINT_SELECTION_LIGHTEN,
    TINT_BORDER_MIN_LUMINANCE, TINT_BORDER_LIGHTEN_STEP,
    VECTOR_AXIS_LABEL_COLOR,
)

WIDGET_FONT = f"{WIDGET_FONT_PT}pt {UI_FONT_FAMILY}"


# ── Color math ─────────────────────────────────────────────────────────────────

def relative_luminance(color: QColor) -> float:
    """Perceived brightness 0–255 using the standard Rec. 601 weights."""
    return 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()


def brightened_for_canvas(color: QColor) -> QColor:
    """Lighten ``color`` until it crosses the visible-on-canvas luminance floor.

    A user-picked near-black sits invisibly on top of CANVAS_BACKGROUND_COLOR; we
    lift it just enough to stay readable as a node/frame outline. Bright picks
    pass through untouched.
    """
    if relative_luminance(color) >= TINT_BORDER_MIN_LUMINANCE:
        return QColor(color)
    out = QColor(color)
    alpha = out.alpha()
    # Qt's lighter() multiplies the HSV value channel, so it cannot brighten
    # absolute black (V==0): seed a minimum value first, then iterate.
    if out.valueF() == 0.0:
        out.setHsvF(out.hueF() if out.hueF() >= 0 else 0.0, out.saturationF(), 0.1)
    # Bounded loop: each lighter() strictly increases V toward 1, so this
    # terminates well before the (capped) iteration limit.
    for _ in range(16):
        if relative_luminance(out) >= TINT_BORDER_MIN_LUMINANCE:
            break
        out = out.lighter(TINT_BORDER_LIGHTEN_STEP)
    out.setAlpha(alpha)
    return out


def darker_hex(hex_color: str, factor: int) -> str:
    """Hex-in/hex-out shade of QColor.darker() for stylesheet composition."""
    return QColor(hex_color).darker(factor).name()


# ── Widget palette ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class WidgetPalette:
    """Every colour an embedded node widget needs, derived from one pick."""
    border: str        # field/button outlines, separators
    field_bg: str      # text/combo/spin editing surfaces, deepest shade
    button_bg: str     # combo drop-down, spin arrows, checkbox label strip
    hover_bg: str      # button hover state
    pressed_bg: str    # button pressed state
    list_accent: str   # drop-down list selection background
    highlight: str     # hover borders and the checkbox check fill
    indicator_bg: str  # InsetFillCheckBox indicator backdrop


def tinted_widget_palette(color: QColor) -> WidgetPalette:
    """Palette for a user-picked node colour: every shade follows the pick."""
    accent = color.lighter(TINT_SELECTION_LIGHTEN).name()
    field_bg = color.darker(TINT_FIELD_DARKEN).name()
    return WidgetPalette(
        border=brightened_for_canvas(color).name(),
        field_bg=field_bg,
        button_bg=color.darker(TINT_BUTTON_DARKEN).name(),
        hover_bg=color.darker(TINT_HOVER_DARKEN).name(),
        pressed_bg=color.darker(TINT_PRESSED_DARKEN).name(),
        list_accent=accent,
        highlight=accent,
        indicator_bg=field_bg,
    )


def _default_widget_palette() -> WidgetPalette:
    # The default scheme is the tinted scheme of DEFAULT_HEADER_COLOR with two
    # deliberate exceptions: hover/check highlights read white (the selection
    # colour of the whole editor) and the checkbox indicator sits on the canvas
    # shade so an unchecked box looks like a hole in the node body.
    base = tinted_widget_palette(QColor(DEFAULT_HEADER_COLOR))
    return WidgetPalette(
        border=base.border,
        field_bg=base.field_bg,
        button_bg=base.button_bg,
        hover_bg=base.hover_bg,
        pressed_bg=base.pressed_bg,
        list_accent=base.list_accent,
        highlight=NODE_SELECTED_COLOR,
        indicator_bg=CANVAS_BACKGROUND_COLOR,
    )


DEFAULT_WIDGET_PALETTE = _default_widget_palette()

NODE_BORDER_COLOR        = DEFAULT_WIDGET_PALETTE.border
GROUP_FRAME_BORDER_COLOR = NODE_BORDER_COLOR
DEFAULT_FIELD_BG         = DEFAULT_WIDGET_PALETTE.field_bg
BUTTON_BG_COLOR          = DEFAULT_WIDGET_PALETTE.button_bg
BUTTON_HOVER_COLOR       = DEFAULT_WIDGET_PALETTE.hover_bg
BUTTON_PRESSED_COLOR     = DEFAULT_WIDGET_PALETTE.pressed_bg
DEFAULT_SELECTION_ACCENT = DEFAULT_WIDGET_PALETTE.list_accent


# ── Widget stylesheets (single builder for default and tinted schemes) ────────

def widget_stylesheets(p: WidgetPalette) -> Dict[str, str]:
    """Render the full embedded-widget stylesheet set from one palette.

    Keys: combo/field/spin/check/tool/push are Qt stylesheets; separator,
    check_border and check_bg are raw colours for widgets that paint manually
    (inline separators and InsetFillCheckBox ignore QSS ::indicator rules).
    """
    return {
        "combo": (
            f"QComboBox{{border:1px solid {p.border};background:{p.field_bg};color:{TEXT_COLOR};"
            f"border-radius:0px;padding:2px 4px;font:{WIDGET_FONT};combobox-popup:0;}}"
            f"QComboBox::drop-down{{border-left:1px solid {p.border};"
            f"width:{BROWSE_BTN_WIDTH}px;background:{p.button_bg};}}"
            f"QComboBox::drop-down:hover{{background:{p.hover_bg};border-color:{p.highlight};}}"
            f"QComboBox QAbstractItemView{{border:1px solid {p.border};"
            f"background:{p.field_bg};color:{TEXT_COLOR};"
            f"selection-background-color:{p.list_accent};selection-color:{p.field_bg};outline:0px;}}"
            f"QComboBox QAbstractItemView::item:hover{{background-color:{p.list_accent};color:{p.field_bg};}}"
            f"QComboBox QAbstractItemView::item:selected{{background-color:{p.list_accent};color:{p.field_bg};}}"
            f"QScrollBar:vertical{{border:none;background:{p.field_bg};width:8px;margin:0px;}}"
            f"QScrollBar::handle:vertical{{background:{p.border};min-height:20px;border-radius:0px;}}"
            f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0px;}}"
            f"QComboBox[connected=\"true\"]{{color:{TEXT_MUTED_COLOR};}}"
            f"QComboBox[connected=\"true\"] QLineEdit{{color:{TEXT_MUTED_COLOR};}}"
            f"QComboBox[connected=\"true\"]::drop-down{{width:0px;border:none;}}"
        ),
        "field": (
            f"QLineEdit{{border:1px solid {p.border};background:{p.field_bg};color:{TEXT_COLOR};"
            f"border-radius:0px;padding:2px 4px;font:{WIDGET_FONT};}}"
            f"QLineEdit:read-only{{color:{TEXT_MUTED_COLOR};}}"
        ),
        "spin": (
            f"QSpinBox{{border:1px solid {p.border};background:{p.field_bg};color:{TEXT_COLOR};"
            f"border-radius:0px;padding:2px;font:{WIDGET_FONT};}}"
            f"QSpinBox::up-button{{background:{p.button_bg};border-left:1px solid {p.border};"
            f"border-bottom:1px solid {p.border};width:16px;}}"
            f"QSpinBox::down-button{{background:{p.button_bg};border-left:1px solid {p.border};width:16px;}}"
            f"QSpinBox::up-button:hover,QSpinBox::down-button:hover{{"
            f"background:{p.hover_bg};border-color:{p.highlight};}}"
            f"QSpinBox:hover{{border-color:{p.highlight};}}"
        ),
        "check": (
            f"QCheckBox{{font:{WIDGET_FONT};color:{TEXT_COLOR};background:{p.button_bg};"
            f"spacing:{CHECKBOX_LABEL_SPACING}px;}}"
            f"QCheckBox::indicator{{width:{CHECKBOX_INDICATOR_SIZE}px;height:{CHECKBOX_INDICATOR_SIZE}px;"
            f"border:1px solid {p.border};background:{p.field_bg};}}"
            f"QCheckBox::indicator:checked{{background:{p.highlight};border-color:{p.highlight};}}"
            f"QCheckBox::indicator:hover{{border-color:{p.highlight};}}"
        ),
        "tool": (
            f"QToolButton{{background:{p.button_bg};color:{BUTTON_TEXT_COLOR};"
            f"border:1px solid {p.border};border-radius:0px;font:{WIDGET_FONT};}}"
            f"QToolButton:hover{{background:{p.hover_bg};border-color:{p.highlight};}}"
            f"QToolButton:pressed{{background:{p.pressed_bg};}}"
        ),
        "push": (
            f"QPushButton{{background:{p.button_bg};color:{BUTTON_TEXT_COLOR};"
            f"border:1px solid {p.border};border-radius:0px;"
            f"padding:5px 8px;font:bold {WIDGET_FONT};}}"
            f"QPushButton:hover{{background:{p.hover_bg};border-color:{p.highlight};}}"
            f"QPushButton:pressed{{background:{p.pressed_bg};}}"
        ),
        "separator": p.border,
        "check_border": p.border,
        "check_bg": p.indicator_bg,
    }


DEFAULT_WIDGET_QSS = widget_stylesheets(DEFAULT_WIDGET_PALETTE)

FIELD_QSS    = DEFAULT_WIDGET_QSS["field"]
COMBOBOX_QSS = DEFAULT_WIDGET_QSS["combo"]
SPINBOX_QSS  = DEFAULT_WIDGET_QSS["spin"]
CHECKBOX_QSS = DEFAULT_WIDGET_QSS["check"]
TOOLBTN_QSS  = DEFAULT_WIDGET_QSS["tool"]
PUSHBTN_QSS  = DEFAULT_WIDGET_QSS["push"]


# ── Fixed chrome stylesheets ───────────────────────────────────────────────────

VECTOR_TOGGLE_QSS = (
    f"QToolButton{{color:{TEXT_MUTED_COLOR};font:bold 8pt;padding:0px 2px;border:none;background:transparent;}}"
    f"QToolButton:hover{{color:{NODE_SELECTED_COLOR};}}"
)

VECTOR_AXIS_LABEL_QSS = f"color:{VECTOR_AXIS_LABEL_COLOR};font:{WIDGET_FONT};"

CONTEXT_MENU_STYLESHEET = f"""
QMenu {{
    background:{BUTTON_BG_COLOR}; color:{TEXT_COLOR};
    border:1px solid {NODE_BORDER_COLOR}; border-radius:0px;
    padding:4px 2px; font:{WIDGET_FONT};
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
