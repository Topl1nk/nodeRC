"""
Characterization tests for GroupFrameItem.

These lock the behavior repaired in the group-frame pass: frames must survive
every (de)serialization path, their context-menu operations must not crash, the
title must rename safely, and the new manual resize plus keyboard shortcuts must
behave as designed.
"""
import os
import json

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtCore import QEvent

import canvas
import nodes_base as nb
import nodes_concrete as nc
import configuration as cfg


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    return canvas.NodeEditorWindow()


def _param(window, x=0, y=0):
    return window.add_param_node(QPointF(x, y), {"param_type": "string", "display": "s"})


def _frames(window):
    return [i for i in window.scene.items() if isinstance(i, nb.GroupFrameItem)]


def _add_frame(window, x=0, y=0, w=200, h=150, title="G"):
    frame = nb.GroupFrameItem(QRectF(0, 0, w, h), title=title)
    frame.setPos(x, y)
    window.scene.addItem(frame)
    return frame


# ── serialization: the frame must survive every round-trip ──────────────────────

def test_group_survives_state_roundtrip(window):
    _add_frame(window, x=40, y=40, title="Region")
    window.set_project_state(window.get_project_state())
    frames = _frames(window)
    assert len(frames) == 1
    assert frames[0].title == "Region"


def test_group_survives_undo_redo(window):
    _add_frame(window, title="U")
    window.push_undo_state()
    window.undo()
    assert len(_frames(window)) == 0
    window.redo()
    assert len(_frames(window)) == 1


def test_group_survives_file_save_load(window, tmp_path):
    _add_frame(window, x=10, y=10, w=240, h=160, title="Saved")
    path = tmp_path / "p.json"
    path.write_text(json.dumps(window._capture(include_selection=False)))
    window._restore(json.loads(path.read_text()), restore_selection=False)
    frames = _frames(window)
    assert len(frames) == 1
    assert frames[0].rect().width() == 240
    assert frames[0].rect().height() == 160


def test_group_survives_copy_paste(window):
    frame = _add_frame(window, title="Clip")
    frame.setSelected(True)
    window.copy_nodes()
    window.paste_nodes()
    assert len(_frames(window)) == 2


# ── context-menu operations must not crash and must respect protection ──────────

def test_clear_frame_deletes_contents_keeps_frame_and_start(window):
    node = _param(window, x=80, y=80)
    frame = _add_frame(window, x=0, y=0, w=400, h=400)
    frame._clear_frame()
    assert node.scene() is None              # contained node removed
    assert frame.scene() is window.scene     # frame itself stays
    assert len(_nodes(window, nc.StartNode)) == 1  # protected node spared


def test_delete_group_removes_contents_and_frame_keeps_start(window):
    node = _param(window, x=80, y=80)
    frame = _add_frame(window, x=0, y=0, w=400, h=400)
    frame._delete_group()
    assert node.scene() is None
    assert frame.scene() is None
    assert len(_nodes(window, nc.StartNode)) == 1


def test_remove_frame_keeps_contained_nodes(window):
    node = _param(window, x=80, y=80)
    frame = _add_frame(window, x=0, y=0, w=400, h=400)
    frame._remove_frame()
    assert frame.scene() is None
    assert node.scene() is window.scene


def _nodes(window, cls):
    return [i for i in window.scene.items() if isinstance(i, cls)]


# ── rename ──────────────────────────────────────────────────────────────────────

def test_group_rename_commits(window):
    frame = _add_frame(window, title="old")
    frame._begin_rename()
    frame.title_item.setPlainText("new name")
    frame._commit_rename()
    assert frame.title == "new name"
    assert "new name" in frame.title_item.toHtml()


def test_group_rename_escapes_html(window):
    frame = _add_frame(window, title="old")
    frame._begin_rename()
    frame.title_item.setPlainText("A & B <x>")
    frame._commit_rename()
    assert frame.title == "A & B <x>"  # stored verbatim, escaped only in HTML


def test_group_rename_cancel_restores_title(window):
    frame = _add_frame(window, title="keep")
    frame._begin_rename()
    frame.title_item.setPlainText("garbage")
    frame._cancel_rename()
    assert frame.title == "keep"


# ── manual resize ────────────────────────────────────────────────────────────────

def test_edge_detection_distinguishes_body_from_border(window):
    frame = _add_frame(window, x=0, y=0, w=200, h=200)
    assert frame._edge_at(QPointF(100, 100)) is None          # body
    assert frame._edge_at(QPointF(0, 0)) == (True, True, False, False)   # top-left
    assert frame._edge_at(QPointF(200, 100)) == (False, False, True, False)  # right


def test_resize_grows_from_bottom_right(window):
    frame = _add_frame(window, x=0, y=0, w=200, h=200)
    frame._resizing = True
    frame._resize_edges = (False, False, True, True)
    frame._apply_resize(QPointF(320, 300))
    frame._resizing = False
    assert frame.rect().width() == 320
    assert frame.rect().height() == 300
    assert frame.pos() == QPointF(0, 0)  # anchored corner unmoved


def test_resize_enforces_minimum_size(window):
    frame = _add_frame(window, x=0, y=0, w=200, h=200)
    frame._resizing = True
    frame._resize_edges = (False, False, True, True)
    frame._apply_resize(QPointF(-50, -50))  # collapse past zero
    frame._resizing = False
    assert frame.rect().width() == cfg.GROUP_FRAME_MIN_SIZE
    assert frame.rect().height() == cfg.GROUP_FRAME_MIN_SIZE


def test_resize_left_edge_moves_origin_and_clamps(window):
    frame = _add_frame(window, x=100, y=100, w=200, h=200)  # scene right edge = 300
    frame._resizing = True
    frame._resize_edges = (True, False, False, False)
    frame._apply_resize(QPointF(400, 100))  # drag left edge past the right edge
    frame._resizing = False
    assert frame.rect().width() == cfg.GROUP_FRAME_MIN_SIZE
    assert frame.pos().x() == 300 - cfg.GROUP_FRAME_MIN_SIZE


# ── coordinate convention: pos holds placement, rect is anchored at origin ──────

def test_group_selected_nodes_normalizes_coordinates(window):
    a = _param(window, x=300, y=200)
    b = _param(window, x=500, y=300)
    a.setSelected(True)
    b.setSelected(True)
    window.group_selected_nodes()
    frame = _frames(window)[0]
    # The scene offset must live in pos(), never in rect().
    assert frame.rect().topLeft() == QPointF(0, 0)
    assert frame.pos() != QPointF(0, 0)
    # Title sits at the frame's own top-left corner, not at the scene origin.
    corner = frame.mapToScene(frame.rect().topLeft())
    title = frame.title_item.scenePos()
    assert abs(title.x() - corner.x()) < 2 * cfg.GROUP_FRAME_TITLE_MARGIN
    assert abs(title.y() - corner.y()) < 2 * cfg.GROUP_FRAME_TITLE_MARGIN


def test_creation_snaps_frame_to_grid(window):
    frame = nb.GroupFrameItem(QRectF(277, 157, 206, 203), title="P")
    window.scene.addItem(frame)
    g = cfg.GRID_SIZE_SMALL
    assert frame.pos().x() % g == 0 and frame.pos().y() % g == 0
    assert frame.rect().width() % g == 0 and frame.rect().height() % g == 0


@pytest.mark.parametrize("edges, drag", [
    ((True, False, False, False), lambda r: QPointF(r.left() - 40, r.center().y())),   # left
    ((False, True, False, False), lambda r: QPointF(r.center().x(), r.top() - 40)),     # top
    ((False, False, True, False), lambda r: QPointF(r.right() + 40, r.center().y())),   # right
    ((False, False, False, True), lambda r: QPointF(r.center().x(), r.bottom() + 40)),  # bottom
])
def test_single_edge_resize_leaves_other_edges_fixed(window, edges, drag):
    # Start from an off-grid frame — the case that exposed the anchor-jump bug.
    frame = nb.GroupFrameItem(QRectF(277, 157, 206, 203), title="P")
    window.scene.addItem(frame)

    def scene_rect():
        return frame.mapToScene(frame.rect()).boundingRect()

    before = scene_rect()
    frame._resizing = True
    frame._resize_edges = edges
    frame._apply_resize(drag(before))
    frame._resizing = False
    after = scene_rect()

    left, top, right, bottom = edges
    if not left:   assert after.left() == before.left()
    if not top:    assert after.top() == before.top()
    if not right:  assert after.right() == before.right()
    if not bottom: assert after.bottom() == before.bottom()


def test_resize_keeps_anchor_for_scene_positioned_frame(window):
    # Build a frame the way Ctrl+G does — from a scene-positioned bounding rect.
    frame = nb.GroupFrameItem(QRectF(280, 160, 200, 200), title="P")
    window.scene.addItem(frame)
    top_left = frame.mapToScene(frame.rect()).boundingRect().topLeft()
    bottom_right = frame.mapToScene(frame.rect()).boundingRect().bottomRight()
    frame._resizing = True
    frame._resize_edges = (False, False, True, True)  # drag bottom-right outward
    frame._apply_resize(QPointF(bottom_right.x() + 60, bottom_right.y() + 60))
    frame._resizing = False
    after = frame.mapToScene(frame.rect()).boundingRect()
    assert after.topLeft() == top_left          # anchored corner never moves
    assert after.width() > 200 and after.height() > 200  # frame actually grew


# ── moving the frame carries its contained nodes ────────────────────────────────

def test_move_carries_contained_nodes(window):
    node = _param(window, x=100, y=100)
    node.setSelected(False)
    frame = _add_frame(window, x=0, y=0, w=400, h=400)
    frame._dragged_inner_nodes = [node]
    before = node.pos()
    frame.setPos(20, 0)  # grid-aligned move
    assert node.pos().x() == before.x() + 20


def test_resize_does_not_carry_contained_nodes(window):
    node = _param(window, x=100, y=100)
    node.setSelected(False)
    frame = _add_frame(window, x=0, y=0, w=400, h=400)
    frame._dragged_inner_nodes = [node]
    before = node.pos()
    frame._resizing = True
    frame._resize_edges = (True, False, False, False)
    frame._apply_resize(QPointF(40, 0))  # moves the frame origin while resizing
    frame._resizing = False
    assert node.pos() == before  # contents stay put during a resize


# ── dragged-node Z restoration (regression for the duplicate release method) ────

def test_restore_dragged_z_resets_zvalue(window):
    node = _param(window)
    node._original_z = node.zValue()
    node.setZValue(10000)
    window.scene._dragged_nodes = [node]
    window.scene._restore_dragged_z()
    assert node.zValue() == 0
    assert not hasattr(node, "_original_z")
    assert window.scene._dragged_nodes == []


# ── keyboard shortcuts ──────────────────────────────────────────────────────────

def _press(window, key, mods=Qt.NoModifier):
    window.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, mods))


def test_ctrl_g_groups_selection(window):
    a = _param(window, x=0)
    b = _param(window, x=120)
    a.setSelected(True)
    b.setSelected(True)
    _press(window, cfg.KEY_GROUP, Qt.ControlModifier)
    assert len(_frames(window)) == 1


def test_ctrl_d_duplicates_selection(window):
    node = _param(window)
    node.setSelected(True)
    before = len(_nodes(window, nc.StringParamNode))
    _press(window, cfg.KEY_DUPLICATE, Qt.ControlModifier)
    assert len(_nodes(window, nc.StringParamNode)) == before + 1


def test_bare_g_toggles_grid_not_group(window):
    grid_before = window.scene.grid_visible
    _press(window, cfg.KEY_TOGGLE_GRID, Qt.NoModifier)
    assert window.scene.grid_visible is not grid_before
    assert len(_frames(window)) == 0  # bare G must not create a group


def test_start_node_is_protected_normal_nodes_are_not(window):
    assert nc.StartNode.is_protected is True
    assert _param(window).is_protected is False
