"""
configuration.py — Single Source of Truth
All external dependencies, visual constants and layout dimensions live here and nowhere else.
"""
from __future__ import annotations

# ── External paths ─────────────────────────────────────────────────────────────
RC_HELP_HTML    = r"C:\ProgramData\Epic\RealityScan\LanguagePack\help\en-US\appbasics\allcommands.htm"
RC_EXECUTABLE   = r"C:\Program Files\Capturing Reality\RealityCapture\RealityCapture.exe"
COMMAND_DB_JSON = "rc_commands.json"
COMMAND_DB_TXT  = "rc_commands.txt"

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

# ── Scrollbar toggle button ────────────────────────────────────────────────────
SCROLLBAR_BTN_MARGIN = 5   # gap from view edge
SCROLLBAR_BTN_OFFSET = 18  # clearance past the Qt scrollbar track width

# ── Socket/node color schema per type ─────────────────────────────────────────
# Blueprint scheme: dark blue backgrounds, distinct pastel outlines/sockets
SOCKET_COLOR_SCHEMA: dict[str, dict[str, str]] = {
    "exec":     {"hdr": "#062242", "body": "#0A315C", "socket": "#3A76B8"},
    "string":   {"hdr": "#062242", "body": "#0A315C", "socket": "#F48FB1"},
    "bool":     {"hdr": "#062242", "body": "#0A315C", "socket": "#A3E4D7"},
    "integer":  {"hdr": "#062242", "body": "#0A315C", "socket": "#3498DB"},
    "float":    {"hdr": "#062242", "body": "#0A315C", "socket": "#EC7063"},
    "float2":   {"hdr": "#062242", "body": "#0A315C", "socket": "#F7DC6F"},
    "float3":   {"hdr": "#062242", "body": "#0A315C", "socket": "#C39BD3"},
    "vector":   {"hdr": "#062242", "body": "#0A315C", "socket": "#C39BD3"},
    "enum":     {"hdr": "#062242", "body": "#0A315C", "socket": "#F39C12"},
    "enum_int": {"hdr": "#062242", "body": "#0A315C", "socket": "#F39C12"},
    "filepath": {"hdr": "#062242", "body": "#0A315C", "socket": "#F5B7B1"},
    "dirpath":  {"hdr": "#062242", "body": "#0A315C", "socket": "#F9E79F"},
    "keyvalue": {"hdr": "#062242", "body": "#0A315C", "socket": "#D5F5E3"},
    "any":      {"hdr": "#062242", "body": "#0A315C", "socket": "#3498DB"},
}
SOCKET_HOVER_COLOR = "#FFFFFF"

# ── General Interface Colors ───────────────────────────────────────────────────
NODE_BORDER_COLOR = "#3A76B8"
NODE_SELECTED_COLOR = "#FFFFFF"
CONNECTION_SELECTED_COLOR = "#FFFFFF"

BUTTON_BG_COLOR = "#0A315C"
BUTTON_HOVER_COLOR = "#164273"
BUTTON_PRESSED_COLOR = "#062242"
BUTTON_TEXT_COLOR = "#FFFFFF"

TEXT_COLOR = "#FFFFFF"
TEXT_MUTED_COLOR = "#A0C0E0"

GRID_COLOR_SMALL = (255, 255, 255, 10)
GRID_COLOR_LARGE = (255, 255, 255, 30)

SCROLLBAR_TOGGLE_BG = "rgba(38,50,56,180)"
SCROLLBAR_TOGGLE_HOVER = "rgba(38,50,56,240)"

# ── Canvas ─────────────────────────────────────────────────────────────────────
SCENE_PADDING            = 1500
CANVAS_BACKGROUND_COLOR  = "#04152B"
WINDOW_BACKGROUND_COLOR  = "#04152B"

# ── Vignette ───────────────────────────────────────────────────────────────────
VIGNETTE_COLOR  = (4, 21, 43, 255)   # RGBA color of the vignette edges
VIGNETTE_RADIUS = 0.5               # Gradient radius multiplier (relative to max(width, height))


# ── Context menu stylesheet ────────────────────────────────────────────────────
CONTEXT_MENU_STYLESHEET = f"""
QMenu {{
    background:{BUTTON_BG_COLOR}; color:{TEXT_COLOR};
    border:1px solid {NODE_BORDER_COLOR}; border-radius:0px;
    padding:4px 2px; font:9pt Consolas;
}}
QMenu::item {{ padding:4px 20px 4px 10px; border-radius:0px; }}
QMenu::item:selected {{ background:{BUTTON_HOVER_COLOR}; border:1px solid {NODE_SELECTED_COLOR}; }}
QMenu::item:disabled {{ color:{NODE_BORDER_COLOR}; }}
QMenu::separator {{ height:1px; background:{NODE_BORDER_COLOR}; margin:3px 8px; }}
QMenu::icon {{ padding-left:6px; }}
"""
