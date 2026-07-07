"""
Characterization tests — lock the editor's observable behavior before refactoring.

These assert *what the program does today* (serialization round-trips, clipboard,
undo/redo, linked editing, rename), so any structural refactor that changes
behavior fails loudly. They are the safety net required by step 0 of refactoring.
"""
import os
import json

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QPointF, QEvent, QRectF
from PyQt5.QtGui import QFocusEvent

from ui.graph_items import MetaNode, Connection
from ui.param_nodes import (
    ParamNode, StringParamNode, IntParamNode, EnumParamNode, FileParamNode,
)
from ui.command_nodes import CommandNode, StartNode
from ui.graph_serialization import serialize_graph

# app/window fixtures moved to tests/ui/conftest.py (shared across the Qt suite)


def _param(window, param_type, x=0, y=0, **extra):
    metadata = {"param_type": param_type, "display": param_type, **extra}
    return window.add_param_node(QPointF(x, y), metadata)


def _nodes_of(window, cls):
    return [i for i in window.scene.items() if isinstance(i, cls)]


# ── value-state round-trips (one per type) ──────────────────────────────────────

@pytest.mark.parametrize("param_type, setup, expected", [
    ("string",  lambda n: n.set_value_state("hello"),               "hello"),
    ("integer", lambda n: n.set_value_state(42),                     42),
    ("bool",    lambda n: n.set_value_state(True),                   True),
    ("float",   lambda n: n.set_value_state("3.14"),                 "3.14"),
    ("float2",  lambda n: n.set_value_state(["1.0", "2.0"]),         ["1.0", "2.0"]),
    ("float3",  lambda n: n.set_value_state(["1.0", "2.0", "3.0"]),  ["1.0", "2.0", "3.0"]),
    ("keyvalue", lambda n: n.set_value_state("k=v"),                 "k=v"),
])
def test_value_state_roundtrip(window, param_type, setup, expected):
    node = _param(window, param_type)
    setup(node)
    assert node.get_value_state() == expected


def test_enum_custom_items_survive_state_roundtrip(window):
    enum = _param(window, "enum", values=["opt1", "opt2"])
    enum._new_item.setText("Custom_A"); enum._add_enum_item()
    enum._combobox.setCurrentText("Custom_A")

    window.set_project_state(window.get_project_state())

    restored = _nodes_of(window, EnumParamNode)[0]
    items = [restored._combobox.itemText(i) for i in range(restored._combobox.count())]
    assert items == ["opt1", "opt2", "Custom_A"]
    assert restored._combobox.currentText() == "Custom_A"


def test_path_ext_filter_survives_state_roundtrip(window):
    path = _param(window, "filepath")
    path._dir_path_cache = "C:/tmp"
    path._ext_filter.setText("*.jpg")

    window.set_project_state(window.get_project_state())

    restored = _nodes_of(window, FileParamNode)[0]
    assert restored._ext_filter.text() == "*.jpg"
    assert restored._dir_path_cache == "C:/tmp"


def test_enum_legacy_string_state_still_loads(window):
    enum = _param(window, "enum", values=["a", "b"])
    enum.set_value_state("b")  # legacy saves stored only the selected text
    assert enum._combobox.currentText() == "b"


# ── project save / load ─────────────────────────────────────────────────────────

def test_file_save_load_preserves_graph(window, tmp_path):
    _param(window, "string", x=0).set_value_state("kept")
    _param(window, "integer", x=120).set_value_state(7)
    before = len(_nodes_of(window, MetaNode))

    path = tmp_path / "proj.json"
    path.write_text(json.dumps(serialize_graph(window.scene, window.connections)))
    window._restore(json.loads(path.read_text()), restore_selection=False)

    assert len(_nodes_of(window, MetaNode)) == before
    assert _nodes_of(window, StringParamNode)[0].get_value_state() == "kept"
    assert _nodes_of(window, IntParamNode)[0].get_value_state() == 7


def test_load_project_centers_view_on_last_added_node(window, tmp_path):
    """Opening a save file must scroll the canvas to whichever node was
    created most recently (highest MetaNode.uid), not wherever the view
    happened to be left — _load_into_tab -> _center_on_last_added_node."""
    _param(window, "string", x=0, y=0)
    newest = _param(window, "integer", x=900, y=700)
    assert newest.uid == max(n.uid for n in _nodes_of(window, MetaNode))

    path = tmp_path / "proj.json"
    path.write_text(json.dumps(serialize_graph(window.scene, window.connections)))

    window.view.centerOn(0, 0)
    tab = window.active_tab
    tab.project_path = None
    tab.dirty = False
    assert window._load_into_tab(tab, str(path)) is True

    center = window.view.mapToScene(window.view.viewport().rect().center())
    node_center = newest.sceneBoundingRect().center()
    assert abs(center.x() - node_center.x()) < 10
    assert abs(center.y() - node_center.y()) < 10


# ── clipboard ───────────────────────────────────────────────────────────────────

def test_copy_paste_duplicates_param_nodes(window):
    node = _param(window, "string")
    node.set_value_state("dup")
    node.setSelected(True)

    window.copy_nodes()
    before = len(_nodes_of(window, StringParamNode))
    window.paste_nodes()

    strings = _nodes_of(window, StringParamNode)
    assert len(strings) == before + 1
    assert all(s.get_value_state() == "dup" for s in strings)


def test_start_node_is_not_copied(window):
    start = _nodes_of(window, StartNode)[0]
    start.setSelected(True)
    window.copy_nodes()
    window.paste_nodes()
    assert len(_nodes_of(window, StartNode)) == 1


# ── undo / redo ─────────────────────────────────────────────────────────────────

def test_undo_redo_param_value(window):
    node = _param(window, "string")
    node.set_value_state("v1")
    node._on_widget_user_edit()  # commits an undo snapshot

    node.set_value_state("v2")
    node._on_widget_user_edit()

    window.undo()
    assert _nodes_of(window, StringParamNode)[0].get_value_state() == "v1"
    window.redo()
    assert _nodes_of(window, StringParamNode)[0].get_value_state() == "v2"


# ── linked editing across a selection ───────────────────────────────────────────

def test_linked_editing_broadcasts_to_same_type(window):
    a = _param(window, "string", x=0)
    b = _param(window, "string", x=80)
    other = _param(window, "integer", x=160)
    for n in (a, b, other):
        n.setSelected(True)

    QApplication.instance().sendEvent(a._editor, QFocusEvent(QEvent.FocusIn))
    a._editor.setText("synced")

    assert b.get_value_state() == "synced"
    assert other.get_value_state() == 0  # different type is untouched


def test_enum_linked_sync_keeps_peer_items(window):
    a = _param(window, "enum", x=0, values=["a", "b", "c"])
    b = _param(window, "enum", x=80, values=["a", "b", "c"])
    for n in (a, b):
        n.setSelected(True)

    QApplication.instance().sendEvent(a._combobox, QFocusEvent(QEvent.FocusIn))
    a._combobox.setCurrentText("c")

    assert b._combobox.currentText() == "c"
    assert [b._combobox.itemText(i) for i in range(b._combobox.count())] == ["a", "b", "c"]


# ── rename ──────────────────────────────────────────────────────────────────────

def test_rename_persists_in_creation_data(window):
    node = _param(window, "string")
    node.setSelected(True)
    node._begin_rename()
    node.title_item.setPlainText("My Param")
    node._commit_rename()
    assert node.creation_data["display"] == "My Param"


def test_title_escapes_html_special_chars(window):
    node = _param(window, "string")
    node._apply_title("A & B <x>")
    assert node.title_item.toPlainText() == "A & B <x>"


def test_long_title_elides_instead_of_overflowing_node(window):
    node = _param(window, "string")
    long_name = "A Very Long Parameter Name That Cannot Possibly Fit"
    node._apply_title(long_name)
    shown = node.title_item.toPlainText()
    assert shown != long_name
    assert shown.endswith("…")
    assert node.toolTip() == long_name


def test_short_title_is_not_elided_and_has_no_tooltip(window):
    node = _param(window, "string")
    node._apply_title("short")
    assert node.title_item.toPlainText() == "short"
    assert node.toolTip() == ""


# ── command node / vector grouping ──────────────────────────────────────────────

def _command(window, **over):
    cmd_def = {"command": "-cmd", "required": [], "optional": [],
               "display": "Cmd", "action": "cmd"}
    cmd_def.update(over)
    return window.add_command_node(QPointF(0, 0), cmd_def)


def test_xyz_params_collapse_into_vector_toggle(window):
    cmd = _command(window, required=["posX", "posY", "posZ"])
    assert "pos" in cmd._vector_buttons


def test_vector_toggle_preserves_selection(window):
    cmd = _command(window, required=["posX", "posY", "posZ"])
    cmd.setSelected(True)
    cmd.toggle_vector_expansion(next(iter(cmd._vector_buttons)))
    rebuilt = _nodes_of(window, CommandNode)[0]
    assert rebuilt.isSelected()


def test_expanded_vector_and_its_wiring_survive_save_load(window):
    # A save/load round-trip used to silently drop an expanded vector's state:
    # CommandNode.serialize_payload() never wrote expanded_vectors, so a
    # reload collapsed the socket back to "pos" — orphaning any connection
    # into "posX"/"posY"/"posZ" (the values just vanished from CLI output).
    cmd = _command(window, required=["posX", "posY", "posZ"])
    cmd.toggle_vector_expansion(next(iter(cmd._vector_buttons)))
    cmd = _nodes_of(window, CommandNode)[0]

    x_val = _param(window, "float", x=-200, y=0)
    x_val.set_value_state("1.5")
    conn = Connection(x_val.get_socket("value_out"), cmd.get_socket("posX"))
    window.scene.addItem(conn)
    window.connections.append(conn)
    conn.refresh()

    window.set_project_state(window.get_project_state())

    reloaded = _nodes_of(window, CommandNode)[0]
    assert reloaded.expanded_vectors == {"pos"}
    assert set(reloaded.sockets) & {"posX", "posY", "posZ"} == {"posX", "posY", "posZ"}
    assert any(
        c.dest.meta_node is reloaded and c.dest.sock_def.name == "posX"
        for c in window.connections
    )


def test_socket_connection_count_tracks_wiring_through_scene_add_remove(window):
    """SocketItem.is_connected() must flip on/off purely by going through
    scene.addItem/removeItem(Connection) — the single choke point every
    connection-creating call site funnels through (editor_window,
    graph_serialization, NodeScene's own drag-release, splice-into-wire) —
    regardless of which one actually created/removed this particular wire."""
    src = _param(window, "float", x=-200, y=0)
    dst = _command(window, required=["posX"])
    src_sock = src.get_socket("value_out")
    dst_sock = dst.get_socket("posX")

    assert src_sock.is_connected() is False
    assert dst_sock.is_connected() is False

    window.scene.enforce_connection_rules(src_sock, dst_sock)
    conn = Connection(src_sock, dst_sock)
    window.scene.addItem(conn)
    window.connections.append(conn)

    assert src_sock.is_connected() is True
    assert dst_sock.is_connected() is True

    window.scene.removeItem(conn)
    window.connections.remove(conn)

    assert src_sock.is_connected() is False
    assert dst_sock.is_connected() is False


def test_unconnected_socket_center_is_a_gradient_not_a_masked_hole(window):
    """Sockets no longer cut a hole in the node's body/header/border — an
    attempt at that (MetaNode._rect_with_holes / _border_path_with_gaps) hit
    a Qt rasterization quirk where a node with sockets on both sides lost
    part of its mask on every socket except the last one processed, under
    the real QGraphicsScene paint pipeline specifically (not reproducible via
    an isolated fillPath/QPainterPath.contains() check). Reverted in favor of
    a plain radial gradient painted by the socket itself: cheap, and immune
    to inter-item paint-order effects since it never touches the parent's own
    geometry at all."""
    from configuration import SOCKET_UNCONNECTED_CENTER_COLOR, CANVAS_BACKGROUND_COLOR

    node = _param(window, "float", x=0, y=0)
    sock = node.get_socket("value_out")
    assert not sock.is_connected()

    # No masking method should exist on MetaNode any more.
    assert not hasattr(node, "_rect_with_holes")
    assert not hasattr(node, "_border_path_with_gaps")
    assert not hasattr(sock, "_mask_radius")

    assert SOCKET_UNCONNECTED_CENTER_COLOR == "#0A1A2F"
    assert CANVAS_BACKGROUND_COLOR == "#04152B"


def test_socket_ring_width_and_trim_are_configured(window):
    """Locks the requested ring geometry: main ring thickened by 1px (2.5,
    was 1.5) with a 1px keyline trim on each side."""
    from configuration import SOCKET_BORDER_WIDTH, SOCKET_RING_TRIM_WIDTH
    assert SOCKET_BORDER_WIDTH == 2.5
    assert SOCKET_RING_TRIM_WIDTH == 1


def test_socket_ring_outer_trim_whitens_on_node_selection_inner_does_not(window):
    """The ring's outer 1px keyline switches to NODE_SELECTED_COLOR while the
    owning node is selected; the inner keyline always stays canvas-colored,
    selected or not."""
    from configuration import CANVAS_BACKGROUND_COLOR, NODE_SELECTED_COLOR

    node = _param(window, "float", x=0, y=0)
    sock = node.get_socket("value_out")

    assert not node.isSelected()
    unselected_outer = NODE_SELECTED_COLOR if sock.meta_node._is_visually_selected() else CANVAS_BACKGROUND_COLOR
    assert unselected_outer == CANVAS_BACKGROUND_COLOR

    node.setSelected(True)
    selected_outer = NODE_SELECTED_COLOR if sock.meta_node._is_visually_selected() else CANVAS_BACKGROUND_COLOR
    assert selected_outer == NODE_SELECTED_COLOR
    # Inner keyline color is a fixed literal in SocketItem.paint (never
    # selection-conditional) — this asserts the constant it must stay
    # anchored to, so a future refactor that accidentally makes it
    # selection-aware breaks loudly here.
    assert CANVAS_BACKGROUND_COLOR == "#04152B"


def test_exec_socket_grows_and_shows_plus_glyph_on_hover(window):
    """Only exec sockets get the hover enlarge/"+" affordance — param
    sockets keep their existing hover behavior (color change only, no size
    change, no glyph)."""
    from configuration import SOCKET_EXEC_HOVER_GROW

    start = next(i for i in window.scene.items() if isinstance(i, StartNode))
    exec_sock = next(s for s in start.sockets.values() if s.sock_def.is_exec)
    param_node = _param(window, "float", x=0, y=0)
    param_sock = param_node.get_socket("value_out")

    assert exec_sock._effective_radius() == exec_sock._radius
    assert param_sock._effective_radius() == param_sock._radius

    exec_sock._hovered = True
    param_sock._hovered = True

    assert exec_sock._effective_radius() == exec_sock._radius + SOCKET_EXEC_HOVER_GROW
    assert param_sock._effective_radius() == param_sock._radius  # unaffected


def test_selecting_a_node_repaints_its_sockets(window):
    """Regression: SocketItem.paint()'s ring reads
    meta_node._is_visually_selected() for its outer keyline color, but a
    socket is a separate child item with its own dirty region — calling
    self.update() on the node alone (the old behavior) doesn't reliably
    repaint it, since a socket's ring can extend past the node's own
    boundingRect margin (worse once hover-grown). Symptom in the app: select
    a node, deselect it, and a stale ring color survives on one socket edge
    until an unrelated repaint happens to touch that pixel region.
    _refresh_selection_visuals must call update() on every socket."""
    node = _param(window, "float", x=0, y=0)
    sock = node.get_socket("value_out")

    calls = []
    sock.update = lambda *a, **k: calls.append(True)

    node.setSelected(True)
    assert calls, "selecting the node must repaint its sockets"

    calls.clear()
    node.setSelected(False)
    assert calls, "deselecting the node must repaint its sockets too"


def test_selecting_a_node_forces_an_explicit_viewport_repaint(window):
    """Regression: the translucent selection wash (_selection_overlay)
    toggling visible/invisible left a ghost trail on screen — self.update()
    only *schedules* a repaint through Qt's own dirty-region tracking, which
    GraphicsView._update_hovered_node (view.py) already documents as
    unreliable under SmartViewportUpdate for cross-item visual changes like
    this. _refresh_selection_visuals must force the same explicit
    view.viewport().update(mapped_rect) _update_hovered_node uses, not just
    rely on update()."""
    node = _param(window, "float", x=0, y=0)

    calls = []
    window.view.viewport().update = lambda *a, **k: calls.append(a)

    node.setSelected(True)
    assert calls, "selecting a node must force an explicit viewport repaint"

    calls.clear()
    node.setSelected(False)
    assert calls, "deselecting a node must force an explicit viewport repaint too"


def test_rubber_band_drag_forces_a_full_viewport_repaint_on_move(window):
    """Regression: Qt's own native rubber-band selection rectangle (the
    dashed marquee you drag to multi-select) isn't reliably fully
    invalidated by its own dirty-region tracking under SmartViewportUpdate —
    shrink it to a thin sliver (a fast, near-axis-aligned drag) and its two
    opposite edges' semi-transparent strokes overlap, leaving a residual
    colored stripe behind once the rectangle moves. GraphicsView.
    mouseMoveEvent must force a full viewport repaint on every move while a
    left-button rubber-band drag is active."""
    from PyQt5.QtCore import QEvent, QPoint, Qt
    from PyQt5.QtGui import QMouseEvent
    from PyQt5.QtWidgets import QGraphicsView

    view = window.view
    assert view.dragMode() == QGraphicsView.RubberBandDrag

    calls = []
    view.viewport().update = lambda *a, **k: calls.append(True)

    move = QMouseEvent(QEvent.MouseMove, QPoint(40, 40), QPoint(40, 40),
                        Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    view.mouseMoveEvent(move)

    assert calls, "a left-button drag move must force a full viewport repaint"


def test_exec_socket_hover_shows_ghost_on_correct_side(window):
    """Hovering an exec socket shows _SocketGhostPreview automatically on the
    side matching its kind — output to the right, input to the left — with
    no ambiguity or per-drag decision needed."""
    start = next(i for i in window.scene.items() if isinstance(i, StartNode))
    exec_out = next(s for s in start.sockets.values() if s.sock_def.is_exec and s.sock_def.kind == "output")

    assert exec_out._ghost is None  # never hovered yet -> lazily unbuilt

    exec_out.hoverEnterEvent(None)
    assert exec_out._ghost is not None
    assert exec_out._ghost.isVisible()
    ghost_rect = exec_out._ghost._local_rect()
    assert ghost_rect.left() > 0  # sits to the right of the socket (local x=0)

    exec_out.hoverLeaveEvent(None)
    assert not exec_out._ghost.isVisible()


def test_ghost_show_hide_forces_an_explicit_viewport_repaint(window):
    """Regression: the same trail bug as the selection wash and the rubber
    band — setVisible() alone only schedules a repaint through Qt's own
    dirty-region tracking (unreliable under SmartViewportUpdate for this
    kind of translucent overlay). _show_ghost/_hide_ghost must force an
    explicit view.viewport().update(mapped_rect), the same idiom used
    everywhere else this bug has shown up."""
    start = next(i for i in window.scene.items() if isinstance(i, StartNode))
    exec_out = next(s for s in start.sockets.values() if s.sock_def.is_exec and s.sock_def.kind == "output")

    calls = []
    window.view.viewport().update = lambda *a, **k: calls.append(a)

    exec_out._show_ghost()
    assert calls, "showing the ghost must force an explicit viewport repaint"

    calls.clear()
    exec_out._hide_ghost()
    assert calls, "hiding the ghost must force an explicit viewport repaint too"


def test_ghost_preview_looks_like_a_real_node_silhouette(window):
    """The ghost is a realistic (header + body + facing socket) but
    colorless node silhouette, not just a bare rectangle — no title/field
    content, but everything a real node's shape has otherwise."""
    from configuration import NODE_HEADER_HEIGHT, NODE_EXEC_SOCKET_HALFSIZE

    start = next(i for i in window.scene.items() if isinstance(i, StartNode))
    exec_out = next(s for s in start.sockets.values() if s.sock_def.is_exec and s.sock_def.kind == "output")
    ghost = exec_out._ensure_ghost()

    body_rect = ghost._local_rect()
    header_rect = ghost._header_rect()
    assert header_rect.top() == body_rect.top()
    assert header_rect.height() == NODE_HEADER_HEIGHT
    assert header_rect.width() == body_rect.width()
    assert header_rect.height() < body_rect.height()  # header is only part of the silhouette

    # The facing socket sits on the ghost's own left edge (it's an output
    # socket, so the ghost — the thing it would connect *into* — sits to
    # its right, facing back with an edge on its own left side) at header
    # mid-height, exactly like a real exec socket's own position.
    sock_pos = ghost._facing_socket_pos()
    assert sock_pos.x() == body_rect.left()
    assert sock_pos.y() == body_rect.top() + NODE_HEADER_HEIGHT / 2.0


def test_ghost_spawn_pos_matches_side_and_is_used_for_actual_spawn(window):
    """SocketItem.ghost_spawn_pos() is what NodeScene.mouseReleaseEvent's
    show_node_creation_menu call actually uses for an exec source — the
    ghost is a direct instruction for the spawn, not just a preview.
    Measured from the source node's own edge at GHOST_NODE_GAP_CELLS grid
    cells, then snapped to the grid via snap_to_grid — the same snap every
    node position already gets (MetaNode.itemChange), so the ghost never
    promises an off-grid position the real spawn wouldn't land on."""
    from configuration import GHOST_NODE_GAP_CELLS, GHOST_NODE_WIDTH, GRID_SIZE_SMALL
    from ui.graph_items import snap_to_grid

    gap = GRID_SIZE_SMALL * GHOST_NODE_GAP_CELLS
    start = next(i for i in window.scene.items() if isinstance(i, StartNode))
    exec_out = next(s for s in start.sockets.values() if s.sock_def.is_exec and s.sock_def.kind == "output")

    pos = exec_out.ghost_spawn_pos()
    assert pos.x() == snap_to_grid(start.pos().x() + start.node_def.width + gap)
    assert pos.x() % GRID_SIZE_SMALL == 0
    assert pos.y() == start.pos().y()  # dead right, never one cell up/down

    cmd = _command(window, required=[])
    exec_in = next(s for s in cmd.sockets.values() if s.sock_def.is_exec and s.sock_def.kind == "input")
    in_pos = exec_in.ghost_spawn_pos()
    assert in_pos.x() == snap_to_grid(cmd.pos().x() - gap - GHOST_NODE_WIDTH)
    assert in_pos.x() % GRID_SIZE_SMALL == 0
    assert in_pos.y() == cmd.pos().y()  # dead left, never one cell up/down


def test_ghost_connection_line_is_perfectly_straight(window):
    """Regression: the ghost used to land one grid cell higher than the
    source node — its Y was computed by centering the whole ghost body on
    the socket's own Y and then independently grid-snapping that, which
    doesn't reproduce the source socket's Y (itself not a grid multiple —
    NODE_HEADER_HEIGHT/2 isn't one). ghost_spawn_pos's Y now equals the
    source node's own top-left Y directly (already grid-aligned via
    itemChange, no separate snap needed) — since an exec socket always sits
    at the same header-mid-height offset from its own node's top regardless
    of node width, this puts the ghost's own facing socket at exactly the
    same absolute Y as the real one: dead straight, not diagonal."""
    start = next(i for i in window.scene.items() if isinstance(i, StartNode))
    exec_out = next(s for s in start.sockets.values() if s.sock_def.is_exec and s.sock_def.kind == "output")
    ghost = exec_out._ensure_ghost()

    source_y = exec_out.scene_center().y()
    # _facing_socket_pos() is in socket-local coordinates — map it to scene
    # space (matching source_y's own frame) before comparing.
    ghost_socket_y = exec_out.mapToScene(ghost._facing_socket_pos()).y()
    assert ghost_socket_y == source_y


def test_socket_label_has_an_outline_and_stays_a_qgraphicstextitem(window):
    """Socket name labels get a thin outline (SOCKET_LABEL_OUTLINE_WIDTH,
    CANVAS_BACKGROUND_COLOR) so they stay legible over whatever's directly
    behind them (canvas grid through an unconnected socket's masked-out
    area, a bright embedded widget, an overlapping wire) — a bare
    QGraphicsTextItem can only fill its glyphs, never stroke them.
    _OutlinedTextItem still subclasses QGraphicsTextItem (not a
    from-scratch QGraphicsItem) rather than reimplementing metrics/hit-test
    from zero, so existing label-layout math (label_width/label_height in
    MetaNode._generate) and MetaNode._paint_lod_primitives's
    isinstance(child, QGraphicsTextItem) check for the far-LOD stand-in bar
    both keep working unmodified — a from-scratch item would silently drop
    out of the LOD check."""
    from PyQt5.QtWidgets import QGraphicsTextItem
    from ui.graph_items import _OutlinedTextItem

    cmd = _command(window, required=["posX"])
    labels = [c for c in cmd.childItems()
              if isinstance(c, QGraphicsTextItem) and c is not cmd.title_item]
    assert labels, "expected at least one socket label"
    label = labels[0]

    assert isinstance(label, _OutlinedTextItem)
    assert isinstance(label, QGraphicsTextItem)
    # Document margin must be 0 — otherwise the manually-drawn outline path
    # (drawn at the glyph's own origin) would be offset from Qt's own fill
    # pass underneath it, which assumes the same zero margin.
    assert label.document().documentMargin() == 0


def test_restore_isolates_a_corrupt_node(window):
    # Article 5.2: a single unreadable node must not lose the whole project.
    good_a = _param(window, "string", x=0); good_a.set_value_state("A")
    good_b = _param(window, "integer", x=120); good_b.set_value_state(9)
    payload = window.get_project_state()
    payload["nodes"].insert(1, {"id": 999, "type": "CommandNode", "x": 0, "y": 0})  # no cmd_def

    window.set_project_state(payload)

    assert _nodes_of(window, StringParamNode)[0].get_value_state() == "A"
    assert _nodes_of(window, IntParamNode)[0].get_value_state() == 9


def test_restore_isolates_a_corrupt_connection(window):
    a = _param(window, "string", x=0)
    payload = window.get_project_state()
    payload["connections"].append({"src_node": a.scenePos and 1})  # malformed record

    window.set_project_state(payload)  # must not raise

    assert len(_nodes_of(window, StringParamNode)) == 1


# ── file UX: remembered path, dirty marker, window title ────────────────────────

def test_new_window_title_is_untitled_and_clean(window):
    assert "Untitled" in window.windowTitle()
    assert not window.windowTitle().endswith("*")
    assert window._dirty is False


def test_edit_marks_dirty_and_save_to_known_path_clears_it(window, tmp_path):
    _param(window, "string")  # add_param_node pushes an undo state → an edit
    assert window._dirty is True
    assert window.windowTitle().endswith("*")

    path = str(tmp_path / "proj.json")
    window._project_path = path
    window.save_project()  # known path → no dialog

    assert os.path.exists(path)
    assert window._dirty is False
    assert os.path.basename(path) in window.windowTitle()
    assert not window.windowTitle().endswith("*")


def test_load_clears_dirty_and_resets_undo_baseline(window, tmp_path, monkeypatch):
    node = _param(window, "string"); node.set_value_state("saved")
    path = str(tmp_path / "y.json")
    window._project_path = path
    window.save_project()

    node.set_value_state("changed_after_save"); node._on_widget_user_edit()
    assert window._dirty is True

    from PyQt5.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (path, ""))
    window.load_project()

    assert window._dirty is False
    assert window.history_index == 0  # loaded graph is the new baseline
    assert _nodes_of(window, StringParamNode)[0].get_value_state() == "saved"


# ── view framing / zoom clamp ───────────────────────────────────────────────────

def test_frame_content_keeps_zoom_within_bounds(window):
    import configuration as cfg
    window.resize(800, 600)
    _param(window, "string", x=0)
    window.view.frame_content(None)
    assert window.view.transform().m11() <= cfg.VIEW_ZOOM_MAX + 1e-6


def test_frame_content_is_safe_on_empty_scene(window):
    for item in list(window.scene.items()):
        window.scene.removeItem(item)
    window.view.frame_content(None)  # must not raise


# ── search menu keyboard flow ───────────────────────────────────────────────────

def test_search_menu_enter_creates_first_match(app):
    from ui.search_menu import SearchMenuDialog
    dialog = SearchMenuDialog({}, None)
    dialog.search_bar.setText("string")
    assert dialog.tree.currentItem() is not None  # first match auto-selected
    dialog._activate_selection()
    assert dialog.payload is not None
    assert dialog.payload.get("param_type") == "string"


def test_search_menu_arrow_moves_selection(app):
    from ui.search_menu import SearchMenuDialog
    dialog = SearchMenuDialog({}, None)
    dialog.search_bar.setText("")  # show every parameter type
    dialog._select_first_match()
    first = dialog.tree.currentItem()
    dialog._move_selection(1)
    assert dialog.tree.currentItem() is not None
    assert dialog.tree.currentItem() is not first


def _search_dialog(app):
    from ui.search_menu import SearchMenuDialog
    cats = {"Geometry": {"__root__": [
        {"command": "-align", "display": "Align Cameras", "action": "align",
         "description": "register photos together", "required": [], "optional": []},
        {"command": "-calculateModel", "display": "Calculate Model", "action": "calculate",
         "description": "build a dense mesh from the alignment", "required": [], "optional": []},
    ]}}
    return SearchMenuDialog(cats, None)


def _result_payloads(dialog):
    from PyQt5.QtCore import Qt
    return [dialog.tree.topLevelItem(i).data(0, Qt.UserRole)
            for i in range(dialog.tree.topLevelItemCount())]


def test_search_empty_shows_browse_categories(app):
    dialog = _search_dialog(app)
    dialog.search_bar.setText("")
    tops = [dialog.tree.topLevelItem(i).text(0) for i in range(dialog.tree.topLevelItemCount())]
    assert any("Parameters" in t for t in tops)
    assert any("Commands" in t for t in tops)


def test_search_ranks_label_match_first_and_flattens(app):
    dialog = _search_dialog(app)
    dialog.search_bar.setText("align")
    payloads = _result_payloads(dialog)
    # Flat result list (no category rows), best label match first.
    assert payloads and payloads[0].get("display") == "Align Cameras"
    assert dialog.tree.currentItem() is dialog.tree.topLevelItem(0)


def test_search_multiword_and_across_fields(app):
    dialog = _search_dialog(app)
    dialog.search_bar.setText("calc model")
    payloads = _result_payloads(dialog)
    assert payloads[0].get("display") == "Calculate Model"


def test_search_matches_description_keyword(app):
    dialog = _search_dialog(app)
    dialog.search_bar.setText("dense")  # appears only in the description
    displays = [p.get("display") for p in _result_payloads(dialog)]
    assert "Calculate Model" in displays


def test_search_fuzzy_subsequence(app):
    dialog = _search_dialog(app)
    dialog.search_bar.setText("almod")  # subsequence of "Calculate Model"
    displays = [p.get("display") for p in _result_payloads(dialog)]
    assert "Calculate Model" in displays


def test_search_enter_creates_best_match(app):
    dialog = _search_dialog(app)
    dialog.search_bar.setText("calc")
    dialog._activate_selection()
    assert dialog.payload is not None
    assert dialog.payload.get("command") == "-calculateModel"


# ── performance invariants ──────────────────────────────────────────────────────

def test_node_bounds_include_selection_margin(window):
    import configuration as cfg
    node = _param(window, "string")
    bounds = node.boundingRect()
    assert bounds.left() == -cfg.NODE_BOUNDS_MARGIN
    assert bounds.top() == -cfg.NODE_BOUNDS_MARGIN


def test_view_uses_partial_updates(window):
    from PyQt5.QtWidgets import QGraphicsView
    assert window.view.viewportUpdateMode() == QGraphicsView.SmartViewportUpdate


def test_vignette_is_under_items_not_dimming_them(window, app):
    from PyQt5.QtWidgets import QGraphicsRectItem
    from PyQt5.QtGui import QColor, QBrush
    from PyQt5.QtCore import QRectF
    window.resize(600, 400)
    window.show()
    app.processEvents()
    bright = QGraphicsRectItem(QRectF(-5000, -5000, 10000, 10000))
    bright.setBrush(QBrush(QColor(255, 255, 255)))
    bright.setZValue(-5)  # above the background/vignette, like any node
    window.scene.addItem(bright)
    app.processEvents()

    image = window.view.viewport().grab().toImage()
    corner = image.pixelColor(3, 3)
    # An item over the strongest vignette corner must stay fully bright — the
    # vignette darkens only the canvas/grid beneath, never the items.
    assert (corner.red(), corner.green(), corner.blue()) == (255, 255, 255)
    assert window.view._vignette_brush is not None


def test_scene_rect_recalc_is_debounced(window):
    # Adding nodes schedules a single coalesced recalc rather than one per node.
    window.scene._rect_recalc_pending = False
    _param(window, "string", x=0)
    _param(window, "string", x=40)
    assert window.scene._rect_recalc_pending is True


def test_auto_create_promotes_integer_named_params(window):
    cmd = _command(window, required=["width", "name"])
    cmd.auto_create_required_parameters()

    displays = [p.creation_data["display"] for p in _nodes_of(window, ParamNode)]
    assert any(d.startswith("[I] width") for d in displays)
    assert any(d.startswith("[S] name") for d in displays)


def test_auto_create_works_when_some_params_already_connected(window):
    cmd = _command(window, required=["width", "height"])
    # pre-connect one param
    p = _param(window, "integer")
    ws = cmd.get_socket("width")
    o = p.get_socket("value_out")
    window.scene.enforce_connection_rules(o, ws)
    c = Connection(o, ws)
    window.scene.addItem(c)
    window.connections.append(c)
    assert len(window.connections) == 1

    cmd.auto_create_required_parameters()
    # both params created/wired; original manual wire replaced
    created = _nodes_of(window, ParamNode)
    assert len(created) >= 2
    assert len(window.connections) >= 2


def test_f2_rename_param_node(window):
    p = _param(window, "string")
    p._begin_rename()
    assert p.title_item.textInteractionFlags() != 0
    p.title_item.setPlainText("renamed")
    p._commit_rename()
    assert "renamed" in p.title_item.toHtml()
    assert p.creation_data["display"] == "renamed"


def test_f2_rename_command_node(window):
    cmd = _command(window)
    cmd._begin_rename()
    assert cmd.title_item.textInteractionFlags() != 0
    cmd.title_item.setPlainText("my command")
    cmd._commit_rename()
    assert "my command" in cmd.title_item.toHtml()


def test_rename_cancel_restores_title(window):
    p = _param(window, "string", x=0)
    original = p.title_item.toPlainText()
    p._begin_rename()
    p.title_item.setPlainText("garbage")
    p._cancel_rename()
    assert p.title_item.toPlainText() == original


# ── import boundary: core/ must not pull in Qt or ui ───────────────────────────
#
# Checking sys.modules in-process (the old approach) is a false-positive trap:
# by the time these tests run, earlier GUI-driving tests have already loaded
# PyQt5 and ui.* into sys.modules, so a core module that secretly imports them
# too shows up as "no new modules" and the check passes even when the
# boundary is broken. Each of these instead imports the module in a brand new
# interpreter process, where the only way PyQt5/ui.* end up loaded is if the
# core module under test pulled them in itself.

def _assert_importable_without_qt_or_ui(module_name: str):
    import subprocess, sys
    probe = (
        "import sys, importlib;"
        f"importlib.import_module({module_name!r});"
        "bad = [m for m in sys.modules if m.startswith('PyQt') or m.startswith('ui.')];"
        "print(bad, file=sys.stderr);"
        "sys.exit(1 if bad else 0)"
    )
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    assert result.returncode == 0, (
        f"{module_name} pulled in Qt/ui: {result.stderr.strip()}"
    )


def test_core_graph_model_has_no_qt_or_ui_deps():
    _assert_importable_without_qt_or_ui("core.graph_model")


def test_core_node_blueprint_has_no_qt_or_ui_deps():
    _assert_importable_without_qt_or_ui("core.node_blueprint")


def test_default_body_color_matches_qt_darker():
    """configuration.DEFAULT_BODY_COLOR is a frozen copy of
    ui.theme.darker_hex(DEFAULT_HEADER_COLOR, TINT_BODY_DARKEN), kept that way
    (instead of computed at import time) so core/node_blueprint.py doesn't need
    Qt. If either input changes, this catches the drift instead of letting the
    node body colour silently go stale."""
    from configuration import DEFAULT_HEADER_COLOR, DEFAULT_BODY_COLOR, TINT_BODY_DARKEN
    from ui.theme import darker_hex
    assert DEFAULT_BODY_COLOR == darker_hex(DEFAULT_HEADER_COLOR, TINT_BODY_DARKEN)


def test_graph_model_dict_roundtrip():
    from core.graph_model import GraphModel, NodeModel, ConnectionModel, GroupModel
    original = GraphModel(
        nodes=[
            NodeModel(uid=1, node_type="StartNode", x=0, y=0),
            NodeModel(uid=2, node_type="CommandNode", x=100, y=0,
                      cmd_def={"command": "-align"}, color="#ff0000"),
            NodeModel(uid=3, node_type="StringParamNode", x=-100, y=0,
                      creation_data={"param_type": "string", "display": "val"},
                      current_value="hello"),
        ],
        connections=[ConnectionModel(src_node_uid=1, src_socket="exec_out",
                                     dst_node_uid=2, dst_socket="exec_in")],
        groups=[GroupModel(title="G", x=0, y=0, width=200, height=150, color="#00ff00")],
    )
    d = original.to_dict(include_selection=True)
    restored = GraphModel.from_dict(d)
    assert len(restored.nodes) == 3
    assert len(restored.connections) == 1
    assert len(restored.groups) == 1
    assert restored.nodes[1].cmd_def["command"] == "-align"
    assert restored.nodes[2].current_value == "hello"
    assert restored.groups[0].color == "#00ff00"
    assert d == restored.to_dict(include_selection=True)


def test_core_graph_executor_has_no_qt_or_ui_deps():
    _assert_importable_without_qt_or_ui("core.graph_executor")


# ── duplicate param names: same-typed inputs a command's own docs don't
#    distinguish (e.g. -exportModel's "modelName fileName" both infer to the
#    generic "filepath") must not collide in the name-keyed socket dict or in
#    connection-value resolution — see dedupe_param_name in node_blueprint.py.

def test_dedupe_param_name_disambiguates_repeats():
    from core.node_blueprint import dedupe_param_name
    seen = {}
    assert dedupe_param_name("filepath", seen) == "filepath"
    assert dedupe_param_name("filepath", seen) == "filepath_2"
    assert dedupe_param_name("filepath", seen) == "filepath_3"
    assert dedupe_param_name("boolean", seen) == "boolean"


def test_command_node_def_gives_duplicate_named_params_unique_sockets():
    from core.node_blueprint import command_node_def
    cmd_def = {
        "command": "-exportModel", "display": "Export Model",
        "required": [{"name": "filepath", "type": "filepath", "values": []},
                     {"name": "filepath", "type": "filepath", "values": []}],
        "optional": [{"name": "xml_file", "type": "filepath", "values": []}],
    }
    ndef = command_node_def(cmd_def)
    names = [s.name for s in ndef.sockets if not s.is_exec]
    assert names == ["filepath", "filepath_2", "xml_file"]
    assert len(names) == len(set(names))


# Chain-to-tokens resolution for duplicate-named inputs now lives in
# tests/core/test_graph_executor.py (test_resolved_params_for_node_handles_
# duplicate_named_inputs_independently) — core.chain_execution.build_launch_tokens
# was replaced by core.graph_executor's segmented executor in Phase 5.


# ── param type inference: axis suffix vs. lookalike words ──────────────────────

def test_infer_param_type_distinguishes_real_axis_from_lookalike_words():
    from packs.realitycapture.rc_documentation_extractor import _infer_param_type
    assert _infer_param_type("x") == "float"
    assert _infer_param_type("offsetX") == "float"
    assert _infer_param_type("rotateX") == "float"
    # "index"/"box.rsbox" end in a bare lowercase 'x' too, but aren't axes.
    assert _infer_param_type("index") == "integer"
    assert _infer_param_type("box.rsbox") == "filepath"
    assert _infer_param_type("width") == "integer"
    assert _infer_param_type("height") == "integer"


# ── named vector grouping: yaw/pitch/roll folds like x/y/z, independently ──────

def test_yaw_pitch_roll_collapses_into_its_own_vector_distinct_from_xyz():
    from core.node_blueprint import group_xyz_params
    params = [
        {"name": "x", "type": "float", "values": []},
        {"name": "y", "type": "float", "values": []},
        {"name": "z", "type": "float", "values": []},
        {"name": "yaw", "type": "float", "values": []},
        {"name": "pitch", "type": "float", "values": []},
        {"name": "roll", "type": "float", "values": []},
    ]
    grouped = group_xyz_params(params)
    assert [g["name"] for g in grouped] == ["XYZ", "yaw_pitch_roll"]
    assert grouped[1]["label"] == "Yaw,Pitch,Roll"
    assert grouped[1]["type"] == "float3"
    # Expanding one must not disturb the other, and each must round-trip
    # back to its own collapsed group via the same key it was expanded with.
    expanded = group_xyz_params(params, {"yaw_pitch_roll"})
    assert [g["name"] for g in expanded] == ["XYZ", "yaw", "pitch", "roll"]
    assert all(g["vector_base"] == "yaw_pitch_roll" for g in expanded[1:])


def test_expanded_axis_vector_propagates_base_to_every_member():
    from core.node_blueprint import group_xyz_params
    params = [
        {"name": "offsetX", "type": "float", "values": []},
        {"name": "offsetY", "type": "float", "values": []},
        {"name": "offsetZ", "type": "float", "values": []},
    ]
    collapsed = group_xyz_params(params)
    assert collapsed[0]["vector_base"] == "offset"
    expanded = group_xyz_params(params, {collapsed[0]["vector_base"]})
    assert [p["name"] for p in expanded] == ["offsetX", "offsetY", "offsetZ"]
    assert all(p["vector_base"] == "offset" for p in expanded)
