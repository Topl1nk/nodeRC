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

# ── PathParamNode browse button ────────────────────────────────────────────────
BROWSE_BTN_WIDTH = 22  # pixel width shared by the browse "…" button and drop-down area

# ── Scrollbar toggle button ────────────────────────────────────────────────────
SCROLLBAR_BTN_MARGIN = 5   # gap from view edge
SCROLLBAR_BTN_OFFSET = 18  # clearance past the Qt scrollbar track width

# ── Socket/node color schema per type ─────────────────────────────────────────
# Blueprint scheme: dark blue backgrounds, distinct pastel outlines/sockets
SOCKET_COLOR_SCHEMA: dict[str, dict[str, str]] = {
    "exec":     {"hdr": "#062242", "body": "#0A315C", "socket": "#FFFFFF"},
    "string":   {"hdr": "#062242", "body": "#0A315C", "socket": "#D3C4E3"},
    "bool":     {"hdr": "#062242", "body": "#0A315C", "socket": "#A3E4D7"},
    "integer":  {"hdr": "#062242", "body": "#0A315C", "socket": "#85C1E9"},
    "float":    {"hdr": "#062242", "body": "#0A315C", "socket": "#7FB3D5"},
    "vector":   {"hdr": "#062242", "body": "#0A315C", "socket": "#76D7C4"},
    "enum":     {"hdr": "#062242", "body": "#0A315C", "socket": "#F5CBA7"},
    "enum_int": {"hdr": "#062242", "body": "#0A315C", "socket": "#F5CBA7"},
    "filepath": {"hdr": "#062242", "body": "#0A315C", "socket": "#F5B7B1"},
    "dirpath":  {"hdr": "#062242", "body": "#0A315C", "socket": "#F9E79F"},
    "keyvalue": {"hdr": "#062242", "body": "#0A315C", "socket": "#D5F5E3"},
    "any":      {"hdr": "#062242", "body": "#0A315C", "socket": "#FFFFFF"},
}
SOCKET_HOVER_COLOR = "#00FFFF"

# ── General Interface Colors ───────────────────────────────────────────────────
NODE_BORDER_COLOR = "#3A76B8"
NODE_SELECTED_COLOR = "#00FFFF"
CONNECTION_SELECTED_COLOR = "#FF7043"

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
