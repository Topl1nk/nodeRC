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

from PyQt5.QtCore import QEvent, QObject
from PyQt5.QtGui import QColor, QPalette

from configuration import (
    DEFAULT_HEADER_COLOR, DEFAULT_BODY_COLOR, CANVAS_BACKGROUND_COLOR, WINDOW_BACKGROUND_COLOR,
    TEXT_COLOR, TEXT_MUTED_COLOR, BUTTON_TEXT_COLOR, NODE_SELECTED_COLOR,
    UI_FONT_FAMILY, WIDGET_FONT_PT, BROWSE_BTN_WIDTH,
    CHECKBOX_INDICATOR_SIZE, CHECKBOX_LABEL_SPACING,
    TINT_FIELD_DARKEN, TINT_BUTTON_DARKEN, TINT_HOVER_DARKEN,
    TINT_PRESSED_DARKEN, TINT_SELECTION_LIGHTEN, TINT_BODY_DARKEN,
    TINT_BORDER_MIN_LUMINANCE, TINT_BORDER_LIGHTEN_STEP,
    VECTOR_AXIS_LABEL_COLOR, SOCKET_COLOR_SCHEMA, FIELD_PLACEHOLDER_COLOR,
)

WIDGET_FONT = f"{WIDGET_FONT_PT}pt {UI_FONT_FAMILY}"


class PlaceholderPaletteFilter(QObject):
    """Event filter to ensure text and placeholder colors remain pinned when Qt polishes the widget style.
    
    Why: Qt's stylesheet application and widget style polishing (especially during lazy tab switching
    or initial paint events) automatically recompute/override custom palette configurations set on QWidget
    and QLineEdit. Intercepting these events allows us to re-apply the pinned colors right as the layout
    engine resets them, bypassing the QSS-cache cold-start black-text bug.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._recursion_guard = False

    def eventFilter(self, obj, event) -> bool:
        if event.type() in (QEvent.Polish, QEvent.StyleChange, QEvent.PaletteChange):
            if not self._recursion_guard:
                self._recursion_guard = True
                try:
                    pal = obj.palette()
                    expected_placeholder = QColor(FIELD_PLACEHOLDER_COLOR)
                    expected_text = QColor(TEXT_COLOR)
                    if (pal.color(QPalette.PlaceholderText) != expected_placeholder or
                            pal.color(QPalette.Text) != expected_text or
                            pal.color(QPalette.WindowText) != expected_text):
                        pal.setColor(QPalette.Text, expected_text)
                        pal.setColor(QPalette.WindowText, expected_text)
                        pal.setColor(QPalette.PlaceholderText, expected_placeholder)
                        obj.setPalette(pal)
                finally:
                    self._recursion_guard = False
        return super().eventFilter(obj, event)


def apply_field_placeholder_palette(widget) -> None:
    """Pin a text widget's real-text and placeholder-text colours via
    QPalette instead of leaving them to Qt's own (stylesheet-cache-dependent)
    derivation — see FIELD_PLACEHOLDER_COLOR's docstring in configuration.py
    for why. The QSS ``color:`` property is supposed to cover this, but the
    very first widget built with a given stylesheet in the process's
    lifetime can render text with a stale/uncomputed colour (black) until a
    second widget with the same stylesheet primes Qt's style cache —
    pinning the palette directly sidesteps that entirely."""
    pal = widget.palette()
    pal.setColor(QPalette.Text, QColor(TEXT_COLOR))
    pal.setColor(QPalette.WindowText, QColor(TEXT_COLOR))
    pal.setColor(QPalette.PlaceholderText, QColor(FIELD_PLACEHOLDER_COLOR))
    widget.setPalette(pal)

    if not getattr(widget, "_palette_filter_installed", False):
        filt = PlaceholderPaletteFilter(widget)
        widget.installEventFilter(filt)
        widget._palette_filter_installed = True

    # A QComboBox's dropdown list is a separate popup widget (a QListView)
    # that Qt creates lazily — its own palette is independent of the combo
    # box's, so it needs the same pinning or its item text hits the same
    # cold-cache black-text bug the first time the popup opens.
    # An *editable* QComboBox (e.g. the [F/F] Load node's file-name combo)
    # never draws its own visible text directly — that's delegated to an
    # internal child QLineEdit, a separate widget with its own independent
    # palette that this function was never patching. A non-editable combo
    # (e.g. the [E] Enum node) has no such child and paints fine, which is
    # why only editable combos ever showed black text here.
    line_edit = getattr(widget, "lineEdit", None)
    if callable(line_edit):
        line_edit_widget = line_edit()
        if line_edit_widget is not None:
            apply_field_placeholder_palette(line_edit_widget)

    view = getattr(widget, "view", None)
    if callable(view):
        view_widget = view()
        if view_widget is not None:
            _pin_view_palette(view_widget)

        # A combo box built on a tab that isn't the active one yet (e.g. a
        # background tab restored from a saved session) never gets a real
        # on-screen show before the user switches to it — Qt only actually
        # polishes/repaints the popup's style the first time showPopup() runs
        # for real, and that first-real-polish silently overwrites the
        # palette we just pinned above. Re-pinning right after every
        # showPopup() call closes that gap for good, regardless of which tab
        # (or how many tabs deep) the combo box lives on.
        show_popup = getattr(widget, "showPopup", None)
        if callable(show_popup) and not getattr(widget, "_placeholder_popup_patched", False):
            def _show_popup_and_repin(_original=show_popup, _widget=widget):
                _original()
                view_widget = _widget.view()
                if view_widget is not None:
                    _pin_view_palette(view_widget)
            widget.showPopup = _show_popup_and_repin
            widget._placeholder_popup_patched = True


def _pin_view_palette(view_widget) -> None:
    view_pal = view_widget.palette()
    view_pal.setColor(QPalette.Text, QColor(TEXT_COLOR))
    view_pal.setColor(QPalette.WindowText, QColor(TEXT_COLOR))
    view_widget.setPalette(view_pal)


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
            f"border-radius:0px;padding:2px 4px;font:{WIDGET_FONT};combobox-popup:0;"
            f"margin-right:{BROWSE_BTN_WIDTH}px;}}"
            # [nodeHover] rather than :hover — see the note on "field" below.
            f"QComboBox[nodeHover=\"true\"]{{border-color:{p.highlight};}}"
            f"QComboBox::drop-down{{subcontrol-origin:margin;subcontrol-position:top right;"
            f"width:{BROWSE_BTN_WIDTH}px;background:{p.button_bg};border:1px solid {p.border};}}"
            f"QComboBox::drop-down:hover{{background:{p.hover_bg};border-color:{p.highlight};}}"
            f"QComboBox QAbstractItemView{{border:1px solid {p.border};"
            f"background:{p.field_bg};color:{TEXT_COLOR};"
            f"selection-background-color:{p.list_accent};selection-color:{p.field_bg};outline:0px;}}"
            f"QComboBox QAbstractItemView::item:hover{{background-color:{p.list_accent};color:{p.field_bg};}}"
            f"QComboBox QAbstractItemView::item:selected{{background-color:{p.list_accent};color:{p.field_bg};}}"
            f"QComboBox[connected=\"true\"]{{color:{TEXT_MUTED_COLOR};margin-right:0px;}}"
            f"QComboBox[connected=\"true\"] QLineEdit{{color:{TEXT_MUTED_COLOR};}}"
            f"QComboBox[connected=\"true\"]::drop-down{{width:0px;border:none;}}"
        ),
        "field": (
            f"QLineEdit{{border:1px solid {p.border};background:{p.field_bg};color:{TEXT_COLOR};"
            f"border-radius:0px;padding:2px 4px;font:{WIDGET_FONT};}}"
            # A widget's native :hover pseudo-state depends on Qt correctly
            # delivering Enter/Leave to it — which QGraphicsProxyWidget does
            # not reliably do for a widget nested inside a wrapper container
            # (EnumParamNode's new-item row, PathParamNode's row containers):
            # moving between sibling widgets in the same wrapper can leave
            # the previous one stuck "hovered" forever. [nodeHover="true"] is
            # instead driven by GraphicsView's own cursor poll (view.py,
            # _update_hovered_widget) — the same ground-truth-every-tick
            # approach already used for the node border — so it can't get
            # stuck regardless of whether the widget is standalone or wrapped.
            f"QLineEdit[nodeHover=\"true\"]{{border-color:{p.highlight};}}"
            f"QLineEdit:read-only{{color:{TEXT_MUTED_COLOR};}}"
        ),
        "spin": (
            # No ::up-button/::down-button rules: IntParamNode hides the
            # native arrows (QAbstractSpinBox.NoButtons) and builds separate
            # square buttons instead — see ParamNode._make_stepper. Qt's
            # native spin arrows paint as sub-controls *inside* the widget's
            # own border, overlapping it rather than living in their own
            # space, which is exactly what every other button in this app
            # avoids.
            f"QSpinBox{{border:1px solid {p.border};background:{p.field_bg};color:{TEXT_COLOR};"
            f"border-radius:0px;padding:2px;font:{WIDGET_FONT};}}"
            f"QSpinBox[nodeHover=\"true\"]{{border-color:{p.highlight};}}"
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
            f"border:1px solid {p.border};border-radius:0px;font:{WIDGET_FONT};outline:none;}}"
            # [nodeHover="true"] only — no native :hover branch. Every
            # QToolButton in the app goes through _make_toolbtn
            # (param_nodes.py), which always lives inside a
            # QGraphicsProxyWidget on the canvas; there is no standalone
            # QToolButton anywhere that would need the native pseudo-state.
            # Keeping :hover as a belt-and-suspenders OR actively caused a
            # stuck-lit outline: when the cursor left the button fast enough
            # that the proxy never delivered a real Leave, Qt's native
            # :hover latched true and the OR condition kept matching even
            # after our own poll (view.py's _update_hovered_widget) correctly
            # cleared nodeHover back to false — nothing could un-stick it.
            f"QToolButton[nodeHover=\"true\"]{{background:{p.hover_bg};border-color:{p.highlight};}}"
            f"QToolButton:pressed{{background:{p.pressed_bg};}}"
        ),
        "push": (
            f"QPushButton{{background:{p.button_bg};color:{BUTTON_TEXT_COLOR};"
            f"border:1px solid {p.border};border-radius:0px;"
            f"padding:5px 8px;font:bold {WIDGET_FONT};}}"
            f"QPushButton:hover,QPushButton[nodeHover=\"true\"]{{background:{p.hover_bg};border-color:{p.highlight};}}"
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
    background:{BUTTON_HOVER_COLOR}; color:{TEXT_COLOR};
    border:1px solid {NODE_BORDER_COLOR}; border-radius:0px;
    padding:4px 2px; font:{WIDGET_FONT};
}}
QMenu::item {{ padding:4px 20px 4px 10px; border-radius:0px; }}
/* Swapped with the menu's own background (BUTTON_BG_COLOR/BUTTON_HOVER_COLOR
   are the same pair, just reused the other way round) rather than reaching
   for a new color: a selected item still has to read against the menu face
   it now sits on, and this is the one other tone already established as
   "the other end" of that same button-state pair. */
QMenu::item:selected {{ background:{BUTTON_BG_COLOR}; border:1px solid {NODE_SELECTED_COLOR}; }}
QMenu::item:disabled {{ color:{NODE_BORDER_COLOR}; }}
QMenu::separator {{ height:1px; background:{NODE_BORDER_COLOR}; margin:3px 8px; }}
QMenu::icon {{ padding-left:6px; }}
"""

# Only for menus that drop down flush against the title bar's own chrome
# (the hamburger's project menu, the tab context menu — both anchored to a
# button/tab's bottom-left corner): their top edge sits right at the seam
# with whatever they dropped from, so a border there would just double up
# against that seam. Every other context menu in the app (node, group,
# canvas — anywhere a right-click isn't anchored to the title bar) keeps
# CONTEXT_MENU_STYLESHEET's full 4-sided border unmodified.
TITLE_BAR_MENU_STYLESHEET = CONTEXT_MENU_STYLESHEET + "QMenu { border-top: none; }"

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
QTreeWidget::item {{
    padding: 3px 2px;
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
QFrame#descFrame {{
    border-top: 1px solid {NODE_BORDER_COLOR};
    border-bottom: 1px solid {NODE_BORDER_COLOR};
    background: transparent;
}}
"""

# Same primitive a graph node paints — a colored header band over a body,
# one outer border wrapping both (see graph_items.py's MetaNode.paint() and
# FramelessDialogBase, which this pairs with).
_DIALOG_BODY_COLOR = DEFAULT_BODY_COLOR

RESTORE_DIALOG_QSS = f"""
#RestoreChoiceDialog {{
    border: 1px solid {NODE_BORDER_COLOR};
}}
#RestoreChoiceDialog QLabel#dialogHeader {{
    background-color: #cc4e63;
    color: {TEXT_COLOR};
    font-family: {UI_FONT_FAMILY};
    font-weight: bold;
    font-size: 11pt;
    padding-left: 10px;
}}
#RestoreChoiceDialog QWidget#dialogBody {{
    background-color: {_DIALOG_BODY_COLOR};
}}
#RestoreChoiceDialog QLabel {{
    color: {TEXT_COLOR};
    font-family: {UI_FONT_FAMILY};
    background: transparent;
}}
#RestoreChoiceDialog QLabel#restoreBody {{
    color: {TEXT_MUTED_COLOR};
}}
"""

# Every QToolTip in the app, regardless of which widget shows it — node
# titles, title bar buttons, sockets, menu items, everything — same
# primitive as the dialog header/body colors (CANVAS_BACKGROUND_COLOR,
# DEFAULT_HEADER_COLOR, TEXT_COLOR), not Qt's native OS tooltip style. Set on
# the QApplication itself (see nodeRC.py) so it applies uniformly no matter
# where a tooltip pops up from — a per-widget stylesheet wouldn't reach a
# tooltip triggered from a widget styled elsewhere.
TOOLTIP_QSS = f"""
QToolTip {{
    background-color: {CANVAS_BACKGROUND_COLOR};
    color: {TEXT_COLOR};
    border: 1px solid {DEFAULT_HEADER_COLOR};
    margin: 0px;
    padding: 2px 4px;
    font-family: {UI_FONT_FAMILY};
}}

"""

# ── Custom title bar / tab strip ───────────────────────────────────────────────
# The close button's hover reuses the same muted red the "bool" param type
# already uses (SOCKET_COLOR_SCHEMA) — one palette for the whole app, no
# one-off color invented just for this button.
TITLE_BAR_CLOSE_HOVER_COLOR = SOCKET_COLOR_SCHEMA["bool"]["socket"]

TITLE_BAR_QSS = f"""
#TitleBarWidget {{
    background: {WINDOW_BACKGROUND_COLOR};
    border: none;
}}
#TitleBarWidget QLabel {{
    color: {TEXT_COLOR};
    font-family: {UI_FONT_FAMILY};
    background: transparent;
}}
QToolButton#titleBarWinBtn {{
    background: transparent;
    color: {TEXT_COLOR};
    border: 1px solid transparent;
    font-family: {UI_FONT_FAMILY};
}}
QToolButton#titleBarWinBtn:hover, QToolButton#titleBarWinBtn[nativeHover="true"] {{
    /* [nativeHover] covers the maximize button once Windows starts
       reporting its rect as HTMAXBUTTON for Snap Layouts support — that
       makes Windows treat it as non-client, so it stops getting the
       ordinary mouse-move/enter events :hover relies on (see
       NodeEditorWindow._hit_test_native_message /
       TitleBarWidget.set_max_button_native_hover). */
    background: {BUTTON_HOVER_COLOR};
    /* Same 1px, same color as the menus these buttons open
       (CONTEXT_MENU_STYLESHEET's border) — one outline vocabulary for the
       title bar's own interactive chrome. */
    border: 1px solid {NODE_BORDER_COLOR};
}}
QToolButton#titleBarCloseBtn {{
    background: transparent;
    color: {TEXT_COLOR};
    border: 1px solid transparent;
    font-family: {UI_FONT_FAMILY};
}}
QToolButton#titleBarCloseBtn:hover {{
    background: {TITLE_BAR_CLOSE_HOVER_COLOR};
    border: 1px solid {NODE_BORDER_COLOR};
}}
"""

TAB_STRIP_QSS = f"""
#TabStripWidget {{
    background: transparent;
}}
"""

# The two stops of the tab-face gradient. Named (rather than inlined in the
# QSS below) because TabButton's hover close button paints the same chrome
# with QPainter — one pair of constants keeps the two renderings identical.
TAB_GRADIENT_DARK  = "#04152B"
TAB_GRADIENT_LIGHT = "#122337"

TAB_BUTTON_QSS = f"""
#TabButton {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {TAB_GRADIENT_DARK}, stop:1 {TAB_GRADIENT_LIGHT});
    border: none;
}}
#TabButton[active="true"] {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {TAB_GRADIENT_LIGHT}, stop:1 {TAB_GRADIENT_DARK});
    border: none;
}}
#TabButton QLabel {{
    color: {TEXT_COLOR};
    font-family: {UI_FONT_FAMILY};
    background: transparent;
}}
#TabButton QToolButton {{
    background: transparent;
    color: {TEXT_MUTED_COLOR};
    border: none;
    font-family: {UI_FONT_FAMILY};
}}
#TabButton QToolButton:hover {{
    background: {TITLE_BAR_CLOSE_HOVER_COLOR};
    color: {TEXT_COLOR};
}}
"""
