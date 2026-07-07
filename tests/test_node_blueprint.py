"""NodeDef dimension quantization — core/node_blueprint.py, no Qt involved
(ст. 3: core/ tests run without QApplication).

A node's width and height are always an exact multiple of GRID_SIZE_SMALL —
the same grid every node's *position* already snaps to (MetaNode.itemChange /
ui.graph_items.snap_to_grid) — so a node's whole footprint lines up with the
canvas grid, not just where it sits.
"""
from core.node_blueprint import NodeDef, SocketDef, start_node_def, command_node_def, param_node_def
from configuration import GRID_SIZE_SMALL, NODE_WIDTH_MIN_CELLS, NODE_WIDTH_MAX_CELLS, NODE_HEIGHT_MIN_CELLS


def _def(**overrides) -> NodeDef:
    kwargs = dict(title="t", header_color="#000000", body_color="#000000")
    kwargs.update(overrides)
    return NodeDef(**kwargs)


def test_node_width_and_height_are_always_grid_multiples():
    for width in (1, 50, 185, 200, 235, 300, 1000):
        d = _def(width=width)
        assert d.width % GRID_SIZE_SMALL == 0
        assert d.body_height % GRID_SIZE_SMALL == 0


def test_node_width_is_clamped_to_min_and_max_cells():
    tiny = _def(width=1)
    assert tiny.width == NODE_WIDTH_MIN_CELLS * GRID_SIZE_SMALL

    huge = _def(width=10_000)
    assert huge.width == NODE_WIDTH_MAX_CELLS * GRID_SIZE_SMALL


def test_node_width_rounds_up_never_down():
    # 235 needs 12 cells (240px) to fit — rounding down to 11 (220px) would
    # clip whatever needed the extra 15px in the first place.
    d = _def(width=235)
    assert d.width == 240


def test_node_height_has_a_minimum_but_no_maximum():
    # NODE_FIRST_ROW_CELLS already pushes an empty node's own raw computed
    # height above the abstract NODE_HEIGHT_MIN_CELLS floor, so body_height
    # alone can't exercise the clamp for a realistic node — test the
    # underlying clamp function directly instead.
    from core.node_blueprint import _snap_dimension
    assert _snap_dimension(1, min_cells=NODE_HEIGHT_MIN_CELLS) == NODE_HEIGHT_MIN_CELLS * GRID_SIZE_SMALL

    many_sockets = [SocketDef(f"p{i}", "input", row=i) for i in range(40)]
    tall = _def(sockets=many_sockets)
    assert tall.body_height % GRID_SIZE_SMALL == 0
    assert tall.body_height > NODE_HEIGHT_MIN_CELLS * GRID_SIZE_SMALL


def test_real_node_defs_are_grid_quantized():
    defs = [
        start_node_def(),
        command_node_def({"command": "-cmd", "required": [], "optional": [], "display": "Cmd"}),
        param_node_def("x", "string"),
    ]
    for d in defs:
        assert d.width % GRID_SIZE_SMALL == 0
        assert d.body_height % GRID_SIZE_SMALL == 0


def test_first_row_center_sits_between_grid_cell_3_and_4_from_the_top():
    """socket_y(row=0) — and every embedded widget's own row_top(0) — must
    land on the boundary between grid cell 3 and cell 4, counted from the
    node's own top (y=0, the header's top edge), not from wherever
    NODE_HEADER_HEIGHT happens to end (it isn't itself a grid multiple)."""
    from configuration import NODE_FIRST_ROW_CELLS, NODE_ROW_HEIGHT

    d = _def()
    expected = NODE_FIRST_ROW_CELLS * GRID_SIZE_SMALL
    assert d.socket_y(0) == expected
    assert d.row_top(0) == expected - NODE_ROW_HEIGHT / 2.0
    # Later rows keep the same NODE_ROW_HEIGHT spacing from that anchor.
    assert d.socket_y(1) == expected + NODE_ROW_HEIGHT
    assert d.socket_y(2) == expected + 2 * NODE_ROW_HEIGHT
