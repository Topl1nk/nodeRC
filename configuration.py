"""
configuration.py — Single Source of Truth
All external dependencies, visual constants and layout dimensions live here and nowhere else.
"""
from __future__ import annotations

import math
import os

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
# Pinned result of ui.theme.darker_hex(DEFAULT_HEADER_COLOR, TINT_BODY_DARKEN) —
# node_blueprint.py needs this default body shade but must stay Qt-free (see
# CODEX.md Ст.7), so the value is computed once and frozen here rather than
# calling into Qt at import time. tests/test_characterization.py's
# test_default_body_color_matches_qt_darker keeps this from silently drifting
# if DEFAULT_HEADER_COLOR or TINT_BODY_DARKEN ever change.
DEFAULT_BODY_COLOR = "#1a385f"
# When True, parameter nodes use their socket colour as the header colour
# (e.g. String → pink, Integer → blue). Exec/command nodes keep DEFAULT_HEADER_COLOR.
PARAM_NODE_HEADER_FROM_SOCKET = True
NODE_SELECTED_COLOR = "#FFFFFF"
NODE_HOVER_COLOR = "#FFFFFF"          # outline shown while the cursor is over a node, unselected
NODE_HOVER_BORDER_WIDTH = 1.5         # thinner than the 2.0 selected border so selection still reads stronger
# How often the view polls the real cursor position for the hover outline (ms).
# Driven by a timer rather than mouse-move events because QGraphicsProxyWidget
# does not reliably deliver mouse-move to the view once a focusable/editable
# embedded widget (QLineEdit, QComboBox) is under the cursor — see view.py.
NODE_HOVER_POLL_INTERVAL_MS = 40
CONNECTION_SELECTED_COLOR = "#FFFFFF"
BUTTON_TEXT_COLOR = "#FFFFFF"
TEXT_COLOR = "#FFFFFF"
TEXT_MUTED_COLOR = "#A0C0E0"
# Placeholder text ("new item...", "folder...") is set explicitly via
# QPalette rather than left to Qt's own derivation — the first QLineEdit
# built with any given stylesheet text in a process's lifetime can render
# its placeholder far too dark (a Fusion-style QSS-cache cold-start quirk)
# until a second widget with the same stylesheet primes the cache.
FIELD_PLACEHOLDER_COLOR = "#878F9A"


# ── Node packs (core/pack_registry.py) ──────────────────────────────────────────
# RC's own paths (RC_EXECUTABLE, RC_HELP_HTML, COMMAND_DB_JSON) live in
# packs/realitycapture/config.py, not here — RealityCapture is one pack among
# others this editor can drive, not a constant of the editor itself.
# Packs bundled with the editor live in a repo-relative folder (same
# cwd-relative convention as COMMAND_DB_JSON above); user-installed drop-in
# packs live under the same %APPDATA%/nodeRC root as autosave/prefs, one
# level down so they don't mix with those files.
BUNDLED_PACKS_DIR_NAME = "packs"
PACKS_DIR_NAME         = "packs"

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

# A node's own width/height are always an exact multiple of GRID_SIZE_SMALL
# (see core.node_blueprint.NodeDef.__post_init__) — the same grid every
# node's *position* already snaps to, so a node's whole footprint lines up
# with the canvas grid, not just where it sits.
NODE_WIDTH_MIN_CELLS  = 10   # minimum node width, in grid cells
NODE_WIDTH_MAX_CELLS  = 15   # maximum node width, in grid cells
NODE_HEIGHT_MIN_CELLS = 2    # minimum node height, in grid cells — no max: height grows with content

# The first param row's own center (row=0 in NodeDef.socket_y) sits exactly
# on the boundary between grid cell 3 and cell 4, counted from the node's
# very top (y=0, the header's own top edge) — not from wherever the header
# happens to end (NODE_HEADER_HEIGHT itself isn't a grid multiple). Every
# later row continues at +NODE_ROW_HEIGHT from there, same as before.
NODE_FIRST_ROW_CELLS  = 3

# ── Grid ───────────────────────────────────────────────────────────────────────
GRID_SIZE_SMALL = 20   # minor grid lines and node snap resolution
GRID_SIZE_LARGE = 100  # major grid lines
# Below this on-screen spacing (px), a grid tier is escalated to the next
# coarser step (see NodeScene._grid_steps) instead of staying put — packing
# multiple scene-space lines into a couple of screen pixels is what made
# lines seem to merge/vanish when zooming out.
GRID_MIN_SPACING_PX = 6

# ── Connection ─────────────────────────────────────────────────────────────────
BEZIER_CTRL_FACTOR = 0.55  # horizontal spread relative to endpoint distance
BEZIER_CTRL_MIN    = 60.0  # minimum control-point offset — prevents flat S-curves
SOCKET_BORDER_DARKEN     = 160  # socket outline = darker shade of the socket's own colour
SOCKET_BORDER_WIDTH      = 2.5  # main ring thickness (was 1.5, +1px)
# Thin keyline flanking the ring on both sides — outer edge (canvas color,
# or NODE_SELECTED_COLOR while the owning node is selected) and inner edge
# (always canvas color, never changes with selection) — see SocketItem.paint.
SOCKET_RING_TRIM_WIDTH   = 1
# An unconnected socket's center is a radial gradient from the inner keyline
# color (CANVAS_BACKGROUND_COLOR, at the rim) down to this darker center —
# a cheap paint-only fake of "the canvas shows through here" with no masking
# of the node body/header/border needed (that approach hit a Qt rasterization
# quirk with multiple holes on one node and was reverted).
SOCKET_UNCONNECTED_CENTER_COLOR = "#0A1A2F"
CONNECTION_EXEC_WIDTH             = 3.0
CONNECTION_EXEC_SELECTED_WIDTH    = 3.5
CONNECTION_PARAM_WIDTH            = 1.8
CONNECTION_PARAM_SELECTED_WIDTH   = 2.2

# ── Exec socket hover: grow + "+"/"-" glyph + ghost node preview ────────────────
SOCKET_EXEC_HOVER_GROW   = 3     # px added to an exec socket's radius while hovered
SOCKET_PLUS_GLYPH_SCALE  = 0.55  # "+"/"-" arm half-length, as a fraction of the (grown) radius
SOCKET_PLUS_GLYPH_WIDTH  = 1.6   # "+"/"-" stroke width
SOCKET_MINUS_GLYPH_COLOR = "#04152B"  # "-" (disconnect) glyph color — "+" (spawn) keeps NODE_SELECTED_COLOR

# _SocketGhostPreview (ui/graph_items.py) — a colorless (monochrome white)
# node silhouette + wire, shown while hovering an exec socket, previewing
# exactly where a node spawned from it will land (SocketItem.ghost_spawn_pos):
# to the right of an output socket, to the left of an input one — automatic,
# never ambiguous. Header/body/border/socket are all the same white, just at
# different opacities, and carry no title or field content — it's a shape,
# not a specific node.
GHOST_NODE_GAP_CELLS     = 3     # gap between the source node's own edge and the
                                  # ghost's near edge, in grid cells (GRID_SIZE_SMALL
                                  # each) — computed at runtime, not baked in px, so
                                  # it stays correct if the grid size ever changes
# Both dimensions are snapped UP to the nearest grid-cell multiple, same as a
# real node's own width/height (core/node_blueprint.py's _snap_dimension) —
# the ghost is a preview of where a real (always grid-quantized) node will
# land, so its own silhouette must obey that same rule instead of showing an
# off-grid placeholder size.
GHOST_NODE_WIDTH         = math.ceil(160 / GRID_SIZE_SMALL) * GRID_SIZE_SMALL   # ghost placeholder width
GHOST_NODE_HEIGHT        = math.ceil((NODE_HEADER_HEIGHT + NODE_ROW_HEIGHT) / GRID_SIZE_SMALL) * GRID_SIZE_SMALL  # header + one row, grid-snapped
GHOST_NODE_BORDER_WIDTH  = 1.5
GHOST_NODE_FILL_RGBA     = (255, 255, 255, 18)   # body — near-invisible, a hint not a solid node
GHOST_NODE_HEADER_RGBA   = (255, 255, 255, 45)   # header band — a little brighter than the body
GHOST_NODE_BORDER_RGBA   = (255, 255, 255, 90)
GHOST_SOCKET_RGBA        = (255, 255, 255, 140)  # the facing socket's own outline — brightest of all
GHOST_CONNECTION_RGBA    = (255, 255, 255, 90)
GHOST_CONNECTION_WIDTH   = 1.8
# Dragging a connection off an already-connected socket previews the ghost
# node spliced in between both existing nodes (a wire to each) as long as
# the cursor stays within this many px of the original straight source->far-
# socket line (NodeScene._splice_still_attached) — beyond it (dragged far
# away, or off at a sharp angle/"kink"), the splice preview — and the actual
# far connection made on release — drops, leaving the ghost wired only to
# the socket it was dragged from.
GHOST_SPLICE_DETACH_DISTANCE = 40

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
# Same glyph, pointing the other way — used on output rows, where the arrow
# sits to the left of the label and should point *into* it, not away.
VECTOR_COLLAPSE_GLYPH_MIRRORED = "▶"
VECTOR_EXPAND_GLYPH     = "▼"        # expand a vector socket back into X/Y/Z sockets
VECTOR_AXIS_LABEL_COLOR = "#AAAAAA"  # axis prefix ("X:", "Y:", "Z:") on vector editors
VECTOR_TOGGLE_WIDTH     = 16         # fixed width for an output-side toggle, so its
                                     # mirrored (left-of-label) position is deterministic

# ── Editor history ─────────────────────────────────────────────────────────────
UNDO_HISTORY_LIMIT = 100  # retained editor snapshots for undo/redo
CLOSED_TABS_HISTORY_LIMIT = 20  # retained closed-tab snapshots for Ctrl+T reopen
# How many of the live UNDO_HISTORY_LIMIT snapshots get written into the
# save file / autosave envelope so Ctrl+Z still works after reopening —
# deliberately smaller than UNDO_HISTORY_LIMIT: each entry is a full graph
# snapshot, so persisting all 100 of them on every single edit would mean
# writing up to 100x a many-thousand-node graph's size on every autosave
# tick. 20 steps of undo surviving a reload/crash-recovery is already a
# large safety margin without that blowup.
SAVED_UNDO_HISTORY_LIMIT = 20

# ── Node z-order ───────────────────────────────────────────────────────────────
NODE_POPUP_Z = 100  # node z-value while its combobox popup is open — above siblings
# StartNode's fixed resting Z: always above every regular node, including ones
# brought to front by a drag (see NodeScene._next_node_z) — a drag-front counter
# would need ~100k moves in one session to ever reach this.
NODE_START_Z = 100_000.0
# _SocketGhostPreview (ui/graph_items.py) is a top-level scene item (not a
# node's child — Qt only orders children within their own parent's z-slot,
# so a merely-high local z would still lose to a *different* top-level node
# with a higher one, e.g. StartNode). This is always above every node,
# including StartNode and a node mid-drag (NODE_DRAG_Z), so the ghost is
# never hidden behind whatever it's hovering over or colliding with.
GHOST_NODE_Z = NODE_START_Z + 1000.0

# Child stacking inside a node, ascending. The selection wash sits above every
# embedded widget yet below the sockets so connectors stay vivid when selected.
NODE_WIDGET_Z_BASE       = 1000  # embedded editor proxies; higher rows stack first
NODE_SELECTION_OVERLAY_Z = 2000
NODE_LINKED_FIELD_Z      = 2500  # the field being linked-edited, lifted above the wash
NODE_SOCKET_Z            = 3000
NODE_COMBO_POPUP_PROXY_Z = 4000  # a proxy's own Z while its combobox popup is open

# ── Selection highlight ────────────────────────────────────────────────────────
# One translucent-white wash painted above the whole node (body, embedded widgets,
# title) when selected — the single source for the entire selected appearance.
NODE_SELECTION_OVERLAY_RGBA = (255, 255, 255, 40)

# ── Custom title bar (frameless window chrome) ─────────────────────────────────
TITLE_BAR_HEIGHT       = 36   # px, hosts the tab strip + min/max/close buttons
TITLE_BAR_BTN_WIDTH    = 46   # px, each window-control button (min/max/close)
TITLE_BAR_RESIZE_MARGIN = 6   # px, edge hit-test band for WM_NCHITTEST resize
TAB_HEIGHT             = 30   # px
TAB_MIN_WIDTH          = 90
TAB_MAX_WIDTH          = 200

# DwmSetWindowAttribute identifier + DWMWCP_* values (Windows 11) — restores
# the native rounded window corners a frameless window otherwise loses.
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2

# Single source of truth for the window's rounded-corner radius — shared by
# NodeEditorWindow._update_window_rounding (central widget's bottom corners)
# and TitleBarWidget's corner mask (top corners), so both stay in sync.
WINDOW_CORNER_RADIUS = 8

# ── Square button footprint ────────────────────────────────────────────────────
# Every button-like control (browse "…", combobox drop-down, +/- toolbuttons, a
# spinbox's combined up/down arrow area) is a square the same size as the field
# row height — one constant instead of each matching it with its own number.
BROWSE_BTN_WIDTH = NODE_WIDGET_HEIGHT

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

# Canvas scrollbar inset from the view edge, applied as a QSS margin on the
# scrollbar's own groove (not setGeometry — see ui/scrollbar.py docstring for
# why an external setGeometry desyncs QAbstractScrollArea's scroll range).
CANVAS_SCROLLBAR_EDGE_MARGIN = 6

# UnifiedScrollBar (ui/scrollbar.py) colors — every scrollbar in the app
# (canvas, side panels, search tree, combo boxes) shares these three colors.
SCROLLBAR_HANDLE_COLOR        = "#1e2c40"  # handle, at rest
SCROLLBAR_HANDLE_ACTIVE_COLOR = "#3c7ed1"  # handle, hovered
SCROLLBAR_TRACK_COLOR         = "#04152b"  # groove/track background

# ── View zoom ──────────────────────────────────────────────────────────────────
VIEW_ZOOM_STEP = 1.20  # multiplicative zoom per wheel notch
VIEW_ZOOM_MIN  = 0.15  # furthest zoom-out (scale factor) — keeps the graph from vanishing
VIEW_ZOOM_MAX  = 3.0   # closest zoom-in — prevents runaway magnification
VIEW_FRAME_MARGIN = 60  # padding (scene px) around framed content when fitting to view

# ── Node level-of-detail ────────────────────────────────────────────────────────
# Below this view scale, node text and embedded field widgets are unreadable
# anyway — MetaNode hides them and paints a single flat color bar instead (see
# MetaNode._set_lod_far), which is what actually makes a many-thousand-node
# scene affordable to pan/zoom: a QGraphicsTextItem's text layout and a real
# QWidget's style-sheet paint are each far more expensive per node than one
# drawRect call.
NODE_LOD_DETAIL_SCALE = 0.35

# ── Auto-spawned parameter placement ───────────────────────────────────────────
AUTOSPAWN_X_GAP    = 280  # distance left of the command node for a created param node
AUTOSPAWN_Y_OFFSET = -40  # vertical start offset of the first created param node
AUTOSPAWN_V_GAP    = 14   # vertical gap between stacked created param nodes (no overlap)

# ── Socket/node color schema per type ─────────────────────────────────────────
# Unreal-Engine-flavoured pin colors (exec=grey, bool=red, int=cyan, float=
# green, string=magenta, ...), each param type given its own unique hue so no
# two node headers/sockets are ever confusable. All non-achromatic entries
# share one tuned saturation/brightness band for a coherent look.
# exec is grey rather than white — white is reserved for the selection/hover
# highlight (NODE_SELECTED_COLOR / NODE_HOVER_COLOR), so an exec pin/wire
# can't be mistaken for a selected one.
SOCKET_COLOR_SCHEMA: dict[str, dict[str, str]] = {
    "exec":     {"socket": "#9AA0A6"},
    "bool":     {"socket": "#CC4E63"},
    "string":   {"socket": "#E055B2"},
    "keyvalue": {"socket": "#BB62D9"},
    "dirpath":  {"socket": "#876CD9"},
    "filepath": {"socket": "#6787E6"},
    "integer":  {"socket": "#59BAEB"},
    "float":    {"socket": "#62D99D"},
    "float2":   {"socket": "#89D962"},
    "float3":   {"socket": "#C9E055"},
    "vector":   {"socket": "#EBC452"},
    "enum":     {"socket": "#B88A49"},
    "enum_int": {"socket": "#C76646"},
    "any":      {"socket": "#C8C8C8"},
}
SOCKET_HOVER_COLOR = "#FFFFFF"

# ── UI Dimensions & Colors ─────────────────────────────────────────────────────

# Keyboard shortcut key codes and modifiers live in ui/keymap.py, not here — they
# need Qt.Key_*/Qt.*Modifier, and core/ imports this module for its Qt-free
# constants (colours, layout, paths), so a PyQt5 import at this module's top
# level would drag Qt into every headless core import. See Ст.7 in CODEX.md.

# ── Hotkey display hints ──────────────────────────────────────────────────────
# Menu items show their keyboard shortcut as plain text (see ui/title_bar.py's
# _add_action_with_hint, ui/graph_items.py's _run_context_menu), not a live
# QAction.setShortcut() binding — the actual dispatch stays entirely in
# NodeEditorWindow.keyPressEvent, which is layout-independent via a
# nativeVirtualKey() remap; a live Qt shortcut wouldn't share that guarantee
# and would fire in parallel with the manual dispatch above. One dict here is
# the single place a future rebind needs to touch.
HOTKEY_HINTS = {
    "save": "Ctrl+S", "save_as": "Ctrl+Shift+S", "open": "Ctrl+O",
    "new_tab": "Ctrl+Shift+N", "new_tab_alt": "Ctrl+N", "close_tab": "Ctrl+Shift+X",
    "duplicate_tab": "Ctrl+Shift+D", "close_others": "Ctrl+Shift+W",
    "close_right": "Ctrl+Shift+E", "close_left": "Ctrl+Shift+Q",
    "reopen_closed_tab": "Ctrl+Shift+T",
    "next_tab": "Ctrl+Tab", "prev_tab": "Ctrl+Shift+Tab",
    "execute_chain": "F5", "undo": "Ctrl+Z", "redo": "Ctrl+Y",
    "copy": "Ctrl+C", "paste": "Ctrl+V", "select_all": "Ctrl+A",
    "group": "Ctrl+G", "duplicate": "Ctrl+D", "fullscreen": "F11", "rename": "F2",
    "delete": "Delete", "toggle_project_inputs_panel": "Ctrl+I",
}

# ── Typography ─────────────────────────────────────────────────────────────────
# Single source for the monospace UI face; every QFont and stylesheet draws from it.
UI_FONT_FAMILY        = "Consolas"
NODE_LABEL_FONT_SIZE  = 8   # socket-row labels
NODE_RENAME_FONT_SIZE = 9   # in-place title editor
# Socket-row label outline — keeps the (often type-tinted) label text legible
# over whatever's directly behind it: the canvas grid through an unconnected
# socket's masked-out area, a bright embedded widget, an overlapping wire.
# Color reuses CANVAS_BACKGROUND_COLOR verbatim (same hex, #04152B) rather
# than a second literal — this is that same color, not a coincidence.
SOCKET_LABEL_OUTLINE_WIDTH = 1
WIDGET_FONT_PT        = 9   # embedded editors, buttons, menus (stylesheet font size)

# General Node Defaults
NODE_CORNER_RADIUS = 5.0


# Colors for the custom color picker palette popup. All 3 rows in the color picker
# have the same palette of colors, with only alpha channel differing (1.0, 0.66, 0.33).
COLOR_PRESETS = [
    "#E74C3C", "#E67E22", "#F1C40F", "#27AE60", "#3498DB", "#8E44AD", "#E91E63", "#00BCD4",
]


# ── Project Inputs panel geometry ─────────────────────────────────────────────
PROJECT_INPUTS_PANEL_WIDTH = 260       # initial width — the user can drag-resize from there
PROJECT_INPUTS_PANEL_MIN_WIDTH = 180
PROJECT_INPUTS_PANEL_MAX_WIDTH = 480
PROJECT_INPUTS_PANEL_RESIZE_GRIP_WIDTH = 6
PROJECT_INPUTS_PANEL_BACKGROUND_COLOR = "#04152b"
PROJECT_INPUTS_PANEL_BORDER_COLOR = "#1a385f"
# Every row's value editor gets this exact width regardless of the node's own
# width, so every row's name/value boundary lines up on one straight column —
# matches ParamNode._widget_width() for the common 200px-wide param node.
PROJECT_INPUTS_FIELD_WIDTH = 172
# Cursor within this many px of the window's left edge reveals the panel;
# once open, it hides again only after the cursor clears the panel width plus
# this much slack, so crossing back over the panel itself never flickers it shut.
PROJECT_INPUTS_PANEL_HOVER_REVEAL_MARGIN = 8
PROJECT_INPUTS_PANEL_HOVER_HIDE_MARGIN = 40

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

# Transparency checkerboard backdrop, shared by the alpha slider and any preview
# swatch holding a translucent colour. Two colour pairs: the slider's is a mid
# grey so it stays visible under every hue overlaid on top; the swatch preview's
# is the lighter, higher-contrast pair used for a translucency indicator.
CHECKERBOARD_CELL_SIZE            = 4
CHECKERBOARD_ALPHA_SLIDER_COLORS  = ((100, 100, 100), (150, 150, 150))
CHECKERBOARD_PREVIEW_COLORS       = ((255, 255, 255), (180, 180, 180))

GRID_COLOR_SMALL = (255, 255, 255, 10)
GRID_COLOR_LARGE = (255, 255, 255, 30)

SCROLLBAR_TOGGLE_BG = "rgba(38,50,56,180)"
SCROLLBAR_TOGGLE_HOVER = "rgba(38,50,56,240)"

# ── Group frame ────────────────────────────────────────────────────────────────
# A backdrop region that holds nodes. Sits below everything (negative Z) so its
# body never intercepts clicks meant for the nodes it contains; only the border
# strip — the resize zone — stays reachable.
GROUP_FRAME_Z                = -100
GROUP_FRAME_FILL_ALPHA       = 28   # opacity of the body wash behind the frame border color
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
WINDOW_BORDER_COLOR      = "#1a385f"

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
# Generous enough that the title bar always has room for its own content —
# see the nativeEvent hit-test note in editor_window.py.
WINDOW_MIN_WIDTH = 480
WINDOW_MIN_HEIGHT = 320

# ── Autosave (core/autosave.py) ─────────────────────────────────────────────────
APP_DATA_DIR_NAME  = "nodeRC"    # folder under %APPDATA% for autosave + prefs
AUTOSAVE_DIR_NAME  = "autosave"
AUTOSAVE_INTERVAL_MS = 60_000    # background snapshot cadence for dirty tabs
PREFS_FILE_NAME    = "prefs.json"

# ── Whole-session recovery (core/session.py) ────────────────────────────────────
SESSION_DIR_NAME     = "sessions"
SESSION_HISTORY_LIMIT = 5   # rotating history of past sessions kept on disk

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


