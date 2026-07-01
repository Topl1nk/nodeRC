"""
configuration.py — Single Source of Truth
All external dependencies, visual constants and layout dimensions live here and nowhere else.
"""
from __future__ import annotations

# ── Custom-tint colour ramp (single source for "user picked a color X") ────────
# A picked colour C drives every painted shade on the node/frame via these named
# factors, so tweaking the palette here propagates to every recoloured surface.
# Factors are Qt's darker()/lighter() arguments (100 = identity, >100 darkens or
# lightens). Luminance is the standard 0.299/0.587/0.114 weighted average over
# 0–255 channels; the title flips to dark text once C reads bright enough.
TINT_BODY_DARKEN        = 220   # node body = darker shade of the picked header colour
TINT_FIELD_DARKEN       = 400   # text/combo backgrounds, deepest shade
# Buttons (combo drop-down panel, spin up/down, checkbox surround) share the body
# shade so embedded controls blend seamlessly with the painted body — the default
# palette has BUTTON_BG_COLOR == body_color and the tinted path mirrors that.
TINT_BUTTON_DARKEN      = TINT_BODY_DARKEN
TINT_HOVER_DARKEN       = 150   # button hover state
TINT_PRESSED_DARKEN     = 500   # button pressed state
TINT_SELECTION_LIGHTEN  = 130   # checkbox check / list selection accent
TINT_TITLE_LUMINANCE_THRESHOLD = 140  # title goes dark on backgrounds brighter than this
# Borders read against CANVAS_BACKGROUND_COLOR; a near-black pick would vanish, so
# brighten the border until its luminance crosses the floor below.
TINT_BORDER_MIN_LUMINANCE = 70   # 0–255 — borders below this get lightened until visible
TINT_BORDER_LIGHTEN_STEP  = 130  # per-iteration lighten factor when brightening borders

DEFAULT_HEADER_COLOR = "#3a7cd1"
# When True, parameter nodes use their socket colour as the header colour
# (e.g. String → pink, Integer → blue). Exec/command nodes keep DEFAULT_HEADER_COLOR.
PARAM_NODE_HEADER_FROM_SOCKET = False
NODE_SELECTED_COLOR = "#FFFFFF"
CONNECTION_SELECTED_COLOR = "#FFFFFF"
BUTTON_TEXT_COLOR = "#FFFFFF"
TEXT_COLOR = "#FFFFFF"
TEXT_MUTED_COLOR = "#A0C0E0"


# ── External paths ─────────────────────────────────────────────────────────────
RC_HELP_HTML    = r"C:\ProgramData\Epic\RealityScan\LanguagePack\help\en-US\appbasics\allcommands.htm"
RC_EXECUTABLE   = r"C:\Program Files\Capturing Reality\RealityCapture\RealityCapture.exe"
COMMAND_DB_JSON = "rc_commands.json"

# ── Node layout ────────────────────────────────────────────────────────────────
NODE_HEADER_HEIGHT        = 30
NODE_ROW_HEIGHT           = 26
NODE_EXEC_SOCKET_HALFSIZE = 8
NODE_PARAM_SOCKET_RADIUS  = 6
NODE_DEFAULT_WIDTH        = 225
NODE_HORIZONTAL_PAD       = 12
NODE_FOOTER_HEIGHT        = 36
NODE_BOTTOM_PAD           = 6
NODE_WIDGET_V_OFFSET      = 6   # top-padding from row/footer start to embedded widget
NODE_WIDGET_HEIGHT        = NODE_ROW_HEIGHT - 4  # 22px — uniform height for all embedded widgets
# Shadow offset to 0 for flat blueprint
NODE_SHADOW_OFFSET_X = 0
NODE_SHADOW_OFFSET_Y = 0
NODE_SHADOW_BLUR     = 0
# Invalidation padding around a node/wire so the selection border (and antialiasing)
# is fully covered — lets the view use partial repaints without leaving trails.
NODE_BOUNDS_MARGIN   = 3

# ── Grid ───────────────────────────────────────────────────────────────────────
GRID_SIZE_SMALL = 20   # minor grid lines and node snap resolution
GRID_SIZE_LARGE = 100  # major grid lines

# ── Connection ─────────────────────────────────────────────────────────────────
BEZIER_CTRL_FACTOR = 0.55  # horizontal spread relative to endpoint distance
BEZIER_CTRL_MIN    = 60.0  # minimum control-point offset — prevents flat S-curves

# ── Parameter typing ───────────────────────────────────────────────────────────
# Command parameters whose name marks them as whole numbers, promoted from the
# default string type so the socket exposes an integer editor.
INTEGER_PARAM_NAMES: frozenset[str] = frozenset({
    "width", "height", "resolution", "jumpslength", "size", "count",
    "margin", "padding", "length", "downscale", "index",
})
# Types whose value string carries several space-separated components.
VECTOR_PARAM_TYPES: frozenset[str] = frozenset({"float2", "float3", "vector"})

# ── Vector socket grouping ─────────────────────────────────────────────────────
VECTOR_COLLAPSE_GLYPH   = "◀"        # collapse X/Y/Z sockets into one vector socket
VECTOR_EXPAND_GLYPH     = "▼"        # expand a vector socket back into X/Y/Z sockets
VECTOR_AXIS_LABEL_COLOR = "#AAAAAA"  # axis prefix ("X:", "Y:", "Z:") on vector editors

# ── Editor history ─────────────────────────────────────────────────────────────
UNDO_HISTORY_LIMIT = 100  # retained editor snapshots for undo/redo

# ── Node z-order ───────────────────────────────────────────────────────────────
NODE_POPUP_Z = 100  # node z-value while its combobox popup is open — above siblings

# Child stacking inside a node, ascending. The selection wash sits above every
# embedded widget yet below the sockets so connectors stay vivid when selected.
NODE_WIDGET_Z_BASE       = 1000  # embedded editor proxies; higher rows stack first
NODE_SELECTION_OVERLAY_Z = 2000
NODE_LINKED_FIELD_Z      = 2500  # the field being linked-edited, lifted above the wash
NODE_SOCKET_Z            = 3000

# ── Selection highlight ────────────────────────────────────────────────────────
# One translucent-white wash painted above the whole node (body, embedded widgets,
# title) when selected — the single source for the entire selected appearance.
NODE_SELECTION_OVERLAY_RGBA = (255, 255, 255, 40)

# ── Windows title bar (DwmSetWindowAttribute identifiers) ──────────────────────
# Caption/text colors mirror WINDOW_BACKGROUND_COLOR / TEXT_COLOR — single source.
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_CAPTION_COLOR           = 35
DWMWA_TEXT_COLOR              = 36

# ── PathParamNode browse button ────────────────────────────────────────────────
BROWSE_BTN_WIDTH = 22  # pixel width shared by the browse "…" button and drop-down area

# ── Checkbox primitive ─────────────────────────────────────────────────────────
# The InsetFillCheckBox draws its indicator manually so the checked fill sits
# inset from the outer border instead of stretching across the whole 13×13 box.
CHECKBOX_INDICATOR_SIZE = 13   # outer indicator side, px
CHECKBOX_FILL_INSET     = 3    # gap between outer border and the inner filled square
CHECKBOX_LABEL_SPACING  = 6    # px between indicator and label text

# ── Scrollbar toggle button ────────────────────────────────────────────────────
SCROLLBAR_BTN_MARGIN = 5   # gap from view edge
SCROLLBAR_BTN_OFFSET = 18  # clearance past the Qt scrollbar track width
SCROLLBAR_BTN_SIZE   = 22  # square edge of the toggle button

# ── View zoom ──────────────────────────────────────────────────────────────────
VIEW_ZOOM_STEP = 1.20  # multiplicative zoom per wheel notch
VIEW_ZOOM_MIN  = 0.15  # furthest zoom-out (scale factor) — keeps the graph from vanishing
VIEW_ZOOM_MAX  = 3.0   # closest zoom-in — prevents runaway magnification
VIEW_FRAME_MARGIN = 60  # padding (scene px) around framed content when fitting to view

# ── Auto-spawned parameter placement ───────────────────────────────────────────
AUTOSPAWN_X_GAP    = 280  # distance left of the command node for a created param node
AUTOSPAWN_Y_OFFSET = -40  # vertical start offset of the first created param node
AUTOSPAWN_V_GAP    = 14   # vertical gap between stacked created param nodes (no overlap)

# ── Socket/node color schema per type ─────────────────────────────────────────
# Blueprint scheme: dark blue backgrounds, distinct pastel outlines/sockets
SOCKET_COLOR_SCHEMA: dict[str, dict[str, str]] = {
    "exec":     {"socket": "#3A76B8"},
    "string":   {"socket": "#F48FB1"},
    "bool":     {"socket": "#A3E4D7"},
    "integer":  {"socket": "#3498DB"},
    "float":    {"socket": "#EC7063"},
    "float2":   {"socket": "#F7DC6F"},
    "float3":   {"socket": "#C39BD3"},
    "vector":   {"socket": "#C39BD3"},
    "enum":     {"socket": "#F39C12"},
    "enum_int": {"socket": "#F39C12"},
    "filepath": {"socket": "#F5B7B1"},
    "dirpath":  {"socket": "#F9E79F"},
    "keyvalue": {"socket": "#D5F5E3"},
    "any":      {"socket": "#3498DB"},
}
SOCKET_HOVER_COLOR = "#FFFFFF"

# ── UI Dimensions & Colors ─────────────────────────────────────────────────────

from PyQt5.QtCore import Qt

# ── Keyboard Shortcuts ─────────────────────────────────────────────────────────
KEY_SPAWN_MENU   = Qt.Key_Space
KEY_DELETE       = Qt.Key_Delete
KEY_SAVE         = Qt.Key_S
KEY_OPEN         = Qt.Key_O
KEY_COPY         = Qt.Key_C
KEY_PASTE        = Qt.Key_V
KEY_UNDO         = Qt.Key_Z
KEY_REDO         = Qt.Key_Y
KEY_TOGGLE_GRID  = Qt.Key_G
KEY_FIT_VIEW     = Qt.Key_F
KEY_FULLSCREEN   = Qt.Key_F11
KEY_COMMIT_EDIT  = [Qt.Key_Return, Qt.Key_Enter]
KEY_CANCEL_EDIT  = Qt.Key_Escape
KEY_RENAME_NODE  = Qt.Key_F2
KEY_SELECT_ALL   = Qt.Key_A
KEY_GROUP        = Qt.Key_G  # with Ctrl — frames the selection (bare G toggles the grid)
KEY_DUPLICATE    = Qt.Key_D  # with Ctrl — clones the selection in place
KEY_PREV_LANG    = Qt.Key_BracketLeft
KEY_NEXT_LANG    = Qt.Key_BracketRight

# ── Keyboard Modifiers ────────────────────────────────────────────────────────
MOD_NONE       = Qt.NoModifier
MOD_CTRL       = Qt.ControlModifier
MOD_CTRL_SHIFT = Qt.ControlModifier | Qt.ShiftModifier

# ── Typography ─────────────────────────────────────────────────────────────────
# Single source for the monospace UI face; every QFont and stylesheet draws from it.
UI_FONT_FAMILY        = "Consolas"
NODE_LABEL_FONT_SIZE  = 8   # socket-row labels
NODE_RENAME_FONT_SIZE = 9   # in-place title editor
WIDGET_FONT_PT        = 9   # embedded editors, buttons, menus (stylesheet font size)

# General Node Defaults
NODE_CORNER_RADIUS = 5.0


# Colors for the custom color picker palette popup — 32 perceptually distinct
# hues laid out in 8 columns × 4 rows. Reds → oranges → yellows → greens →
# cyans/blues → purples → pinks → aquas; each row deepens or shifts to keep
# the swatches unambiguous side-by-side. All entries are unique.
COLOR_PRESETS = [
    "#E74C3C", "#E67E22", "#F1C40F", "#27AE60", "#3498DB", "#8E44AD", "#E91E63", "#00BCD4",
    "#C0392B", "#D35400", "#F39C12", "#16A085", "#2980B9", "#9B59B6", "#AD1457", "#00838F",
    "#FF6B6B", "#FFA94D", "#FFE066", "#51CF66", "#5DADE2", "#C39BD3", "#F48FB1", "#80DEEA",
    "#7B0F1E", "#A04000", "#7F6000", "#196F3D", "#1B4F72", "#4A235A", "#880E4F", "#006064",
]

# ── Color picker popup geometry ───────────────────────────────────────────────
# All controls inside the popup obey a single grid so widths and heights stay
# in lockstep; the colour square auto-fits the popup width minus padding.
COLOR_PICKER_WIDTH         = 290
COLOR_PICKER_PADDING       = 8
COLOR_PICKER_ROW_HEIGHT    = 22   # uniform height for HEX row controls
COLOR_PICKER_SQUARE_HEIGHT = 150
COLOR_PICKER_SLIDER_HEIGHT = 16
COLOR_PICKER_PREVIEW_SIZE  = COLOR_PICKER_ROW_HEIGHT   # square swatch matches row
COLOR_PICKER_PRESET_SIZE   = 22
COLOR_PICKER_PRESET_COLS   = 8
COLOR_PICKER_PRESET_GAP    = 4

GRID_COLOR_SMALL = (255, 255, 255, 10)
GRID_COLOR_LARGE = (255, 255, 255, 30)

SCROLLBAR_TOGGLE_BG = "rgba(38,50,56,180)"
SCROLLBAR_TOGGLE_HOVER = "rgba(38,50,56,240)"

# ── Group frame ────────────────────────────────────────────────────────────────
# A backdrop region that holds nodes. Sits below everything (negative Z) so its
# body never intercepts clicks meant for the nodes it contains; only the border
# strip — the resize zone — stays reachable.
GROUP_FRAME_Z                = -100
GROUP_FRAME_FILL_RGBA        = (58, 118, 184, 28)   # faint wash of default border color
GROUP_FRAME_FILL_ALPHA       = 28   # opacity of the body wash when a custom border color is picked
GROUP_FRAME_BORDER_WIDTH     = 3
GROUP_FRAME_TITLE_COLOR      = TEXT_COLOR
GROUP_FRAME_TITLE_FONT       = UI_FONT_FAMILY
GROUP_FRAME_TITLE_FONT_SIZE  = 12
GROUP_FRAME_TITLE_MARGIN     = 10   # left inset of the title text inside the header
# Header strip across the top of the frame, painted in a darker shade of the
# chosen colour and hosting the title — mirrors the node-header look so groups
# read as containers of nodes, not free-floating washes. Same height as a node
# header keeps everything aligned to one vertical rhythm.
GROUP_FRAME_HEADER_HEIGHT    = NODE_HEADER_HEIGHT
GROUP_FRAME_HEADER_DARKEN    = 160   # darken factor applied to the frame colour
GROUP_FRAME_HANDLE           = 12   # edge/corner pixels that grab a resize
GROUP_FRAME_MIN_SIZE         = 80   # smallest width/height a resize may produce
# Visual gap between the frame's body edge and the dashed outline — keeps the
# dashes from sitting flush against the body fill so the outline reads as a
# decorative ring rather than a raw rect stroke.
GROUP_FRAME_BORDER_INSET     = 10
# Slack added around the bounding box of grouped nodes when a frame is created or
# refitted; the extra top band leaves room for the title above the first node.
GROUP_FRAME_PAD_LEFT         = 20
GROUP_FRAME_PAD_TOP          = 40
GROUP_FRAME_PAD_RIGHT        = 20
GROUP_FRAME_PAD_BOTTOM       = 20

# ── Canvas ─────────────────────────────────────────────────────────────────────
SCENE_PADDING            = 1500
CANVAS_BACKGROUND_COLOR  = "#04152B"
WINDOW_BACKGROUND_COLOR  = "#04152B"

# ── Vignette ───────────────────────────────────────────────────────────────────
VIGNETTE_COLOR  = (4, 21, 43, 255)   # RGBA color of the vignette edges
VIGNETTE_RADIUS = 0.5               # Gradient radius multiplier (relative to max(width, height))


# ── Codex Compliance Layout, Z-Order, Window, and String Constants ───────────
SCENE_INITIAL_X = -500
SCENE_INITIAL_Y = -500
SCENE_INITIAL_WIDTH = 1000
SCENE_INITIAL_HEIGHT = 1000

DRAG_PREVIEW_LINE_WIDTH = 2.0
NODE_DRAG_Z = 10000.0
CONNECTION_Z = -1.0

WINDOW_INITIAL_X = 100
WINDOW_INITIAL_Y = 100
WINDOW_INITIAL_WIDTH = 1280
WINDOW_INITIAL_HEIGHT = 800
WINDOW_STYLE = "Fusion"

START_NODE_INITIAL_X = 60
START_NODE_INITIAL_Y = 80

GROUP_FRAME_DEFAULT_WIDTH = 100
GROUP_FRAME_DEFAULT_HEIGHT = 100
# Group titles are user-facing text and live in the translation catalog
# (default_group_title / logical_group_title), not here — see localization.py.

DUPLICATE_OFFSET_X = 50
DUPLICATE_OFFSET_Y = 50

SEARCH_DIALOG_WIDTH = 700
SEARCH_DIALOG_HEIGHT = 450
SEARCH_RESULTS_LIMIT = 50
SEARCH_DIALOG_X_OFFSET = 700

SCROLLBAR_TOGGLE_SHOW_GLYPH = "⊞"
SCROLLBAR_TOGGLE_HIDE_GLYPH = "⊟"

# ── Clipboard ──────────────────────────────────────────────────────────────────
# Marks NodeRC-owned clipboard text so paste ignores foreign content.
CLIPBOARD_PAYLOAD_PREFIX = "NODERC_CLIPBOARD:"

# ── Layout-independent language cycling ────────────────────────────────────────
# Windows virtual-key codes of the physical bracket keys, plus the glyphs those
# keys produce on the supported layouts (US, Ukrainian, Russian) — so [ and ]
# cycle the UI language whatever layout is active.
VK_OEM_LEFT_BRACKET  = 0xDB
VK_OEM_RIGHT_BRACKET = 0xDD
PREV_LANG_LAYOUT_CHARS = frozenset(("[", "{", "х", "Х", "ї", "Ї"))
NEXT_LANG_LAYOUT_CHARS = frozenset(("]", "}", "ъ", "Ъ", "і", "І"))


