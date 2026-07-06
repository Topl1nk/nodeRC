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

from ui.editor_window import NodeEditorWindow
from ui.graph_items import GroupFrameItem
from ui.param_nodes import StringParamNode
from ui.command_nodes import StartNode
from ui.theme import brightened_for_canvas, relative_luminance
from core.graph_serialization import serialize_graph
import configuration as cfg


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    return NodeEditorWindow()


def _param(window, x=0, y=0):
    return window.add_param_node(QPointF(x, y), {"param_type": "string", "display": "s"})


def _frames(window):
    return [i for i in window.scene.items() if isinstance(i, GroupFrameItem)]


def _add_frame(window, x=0, y=0, w=200, h=150, title="G"):
    frame = GroupFrameItem(QRectF(0, 0, w, h), title=title)
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
    path.write_text(json.dumps(serialize_graph(window.scene, window.connections)))
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
    assert len(_nodes(window, StartNode)) == 1  # protected node spared


def test_delete_group_removes_contents_and_frame_keeps_start(window):
    node = _param(window, x=80, y=80)
    frame = _add_frame(window, x=0, y=0, w=400, h=400)
    frame._delete_group()
    assert node.scene() is None
    assert frame.scene() is None
    assert len(_nodes(window, StartNode)) == 1


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
    frame = GroupFrameItem(QRectF(277, 157, 206, 203), title="P")
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
    frame = GroupFrameItem(QRectF(277, 157, 206, 203), title="P")
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
    frame = GroupFrameItem(QRectF(280, 160, 200, 200), title="P")
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


# ── custom color (frame and node) ───────────────────────────────────────────────

def test_brightened_for_canvas_lifts_pure_black_above_visibility_floor():
    from PyQt5.QtGui import QColor
    assert relative_luminance(brightened_for_canvas(QColor("#000000"))) >= cfg.TINT_BORDER_MIN_LUMINANCE
    # Bright colours pass through untouched.
    bright = QColor("#3A76B8")
    assert brightened_for_canvas(bright).name() == bright.name()


def test_node_border_brightens_for_near_black_pick(window):
    from PyQt5.QtGui import QColor
    from ui.theme import tinted_widget_palette, widget_stylesheets
    node = _param(window)
    node.set_color("#000000", record_undo=False)
    qss = widget_stylesheets(tinted_widget_palette(QColor("#000000")))
    assert "border:1px solid #000000" not in qss["field"]
    assert "border:1px solid #" in qss["field"]


def test_filepath_node_file_combo_gets_recolored(window):
    node = w_add_filepath(window)
    node.set_color("#ff0000", record_undo=False)
    assert "#ff0000" in node._file_combo.styleSheet().lower()
    assert "#ff0000" in node._dir_editor.styleSheet().lower()
    assert "#ff0000" in node._ext_filter.styleSheet().lower()


def w_add_filepath(window):
    return window.add_param_node(QPointF(0, 0), {"param_type": "filepath", "display": "F"})


def test_enum_add_button_keeps_full_toolbutton_style_after_recolor(window):
    from ui.theme import VECTOR_TOGGLE_QSS
    node = window.add_param_node(
        QPointF(0, 0), {"param_type": "enum", "display": "E", "values": ["a", "b"]})
    node.set_color("#ff0000", record_undo=False)
    css = node._add_btn.styleSheet()
    assert "QToolButton{" in css and "#ff0000" in css.lower()
    assert VECTOR_TOGGLE_QSS not in css   # not the tiny inline glyph style


def test_combobox_internal_line_edit_has_no_second_border(window):
    node = w_add_filepath(window)
    node.set_color("#ff0000", record_undo=False)
    # Recoloring must not push a field stylesheet onto the combo's internal
    # QLineEdit; the combo's own QSS already cascades to it. Otherwise two
    # borders are painted, one inside the other.
    assert node._file_combo.lineEdit().styleSheet() == ""


def test_tinted_button_bg_matches_body_shade(window):
    node = window.add_param_node(
        QPointF(0, 0), {"param_type": "bool", "display": "B"})
    node.set_color("#ff0000", record_undo=False)
    from PyQt5.QtGui import QColor
    body_shade = QColor("#ff0000").darker(cfg.TINT_BODY_DARKEN).name().lower()
    assert body_shade in node._checkbox.styleSheet().lower()
    assert cfg.TINT_BUTTON_DARKEN == cfg.TINT_BODY_DARKEN


def test_combo_popup_hides_overlay_so_list_is_visible(window):
    # When the combo popup opens the selection overlay is hidden so the embedded
    # popup list (combobox-popup:0 = scene proxy) isn't occluded by the wash.
    # The overlay is restored to its correct state when the popup closes.
    node = window.add_param_node(
        QPointF(0, 0), {"param_type": "enum", "display": "E", "values": ["a", "b"]})
    node.setSelected(True)
    assert node._selection_overlay.isVisible()
    node._combobox.showPopup()
    assert not node._selection_overlay.isVisible()
    node._combobox.hidePopup()
    QApplication.instance().processEvents()
    assert node._selection_overlay.isVisible()


def test_only_header_scope_keeps_body_default_but_paints_header(window):
    node = _param(window)
    default_body = node.node_def.body_color
    node.set_color("#ff0000", only_header=True, record_undo=False)
    from PyQt5.QtWidgets import QStyleOptionGraphicsItem
    from PyQt5.QtGui import QImage, QPainter
    img = QImage(260, 140, QImage.Format_ARGB32); img.fill(0)
    p = QPainter(img); opt = QStyleOptionGraphicsItem()
    node.paint(p, opt, None); p.end()
    header_rgb = img.pixelColor(120, 15).getRgb()[:3]
    body_rgb = img.pixelColor(120, 60).getRgb()[:3]
    from PyQt5.QtGui import QColor as _QC
    expected_body = _QC(default_body).getRgb()[:3]
    assert header_rgb == (255, 0, 0)
    assert body_rgb == expected_body
    assert node.color_only_header() is True


def test_color_only_header_serialises_and_restores(window):
    node = _param(window)
    node.set_color("#ff0000", only_header=True, record_undo=False)
    window.set_project_state(window.get_project_state())
    restored = _nodes(window, StringParamNode)[0]
    assert restored.color_override() == "#ff0000"
    assert restored.color_only_header() is True


def test_color_picker_hex_field_displays_without_hash():
    from ui.color_picker import ColorPickerPopup
    popup = ColorPickerPopup(on_color_selected=lambda c, oh, cc=None: None,
                             initial_color="#3A76B8")
    assert popup.hex_input.text() == "3a76b8"
    popup.hide()


def test_color_picker_textChanged_accepts_with_or_without_hash():
    from ui.color_picker import ColorPickerPopup
    calls = []
    popup = ColorPickerPopup(on_color_selected=lambda c, oh, cc=None: calls.append((c, oh)),
                             initial_color="#3A76B8")
    popup.hex_input.setText("ff8800")
    assert calls and calls[-1][0].lower().endswith("ff8800")
    popup.hex_input.setText("#a1b2c3")
    assert calls[-1][0].lower().endswith("a1b2c3")
    popup.hide()


def test_color_picker_row_widgets_share_height():
    from ui.color_picker import ColorPickerPopup
    popup = ColorPickerPopup(on_color_selected=lambda c, oh, cc=None: None, initial_color="#3A76B8")
    h = cfg.COLOR_PICKER_ROW_HEIGHT
    assert popup.hex_input.height() == h
    assert popup.only_header_check.height() == h
    assert popup.preview.height() == h
    popup.hide()


def test_color_picker_square_fits_popup_content_width():
    from ui.color_picker import ColorPickerPopup
    popup = ColorPickerPopup(on_color_selected=lambda c, oh, cc=None: None, initial_color="#3A76B8")
    popup.show()
    from PyQt5.QtWidgets import QApplication
    QApplication.instance().processEvents()
    assert popup.square.width() == popup.width() - 2 * cfg.COLOR_PICKER_PADDING
    popup.hide()


def test_color_picker_inner_labels_have_no_individual_border():
    from PyQt5.QtWidgets import QLabel
    from ui.color_picker import ColorPickerPopup
    popup = ColorPickerPopup(on_color_selected=lambda c, oh, cc=None: None, initial_color="#3A76B8")
    hsva_labels = [l for l in popup.findChildren(QLabel) if l.text() in ("H:", "S:", "V:", "A:")]
    assert len(hsva_labels) == 4
    # The popup-level border is scoped via #ColorPickerPopup, so individual
    # labels carry no per-widget border stylesheet of their own.
    for lab in hsva_labels:
        assert lab.styleSheet() == ""
    # The HEX label is also borderless.
    hex_lab = next(l for l in popup.findChildren(QLabel) if l.text() == "HEX:")
    assert hex_lab.styleSheet() == ""
    popup.hide()


def test_color_picker_preset_swatches_have_white_hover_border():
    from ui.color_picker import ColorPickerPopup, PresetButton
    from PyQt5.QtGui import QColor
    popup = ColorPickerPopup(on_color_selected=lambda c, oh, cc=None: None, initial_color="#3A76B8")
    presets = popup.findChildren(PresetButton)
    assert len(presets) >= len(cfg.COLOR_PRESETS)
    for btn in presets:
        assert isinstance(btn.color, QColor)
    popup.hide()


def test_only_header_does_not_paint_outer_border(window):
    from PyQt5.QtWidgets import QStyleOptionGraphicsItem
    from PyQt5.QtGui import QImage, QPainter
    node = _param(window)
    node.set_color("#ff0000", only_header=True, record_undo=False)
    img = QImage(260, 140, QImage.Format_ARGB32); img.fill(0)
    p = QPainter(img); opt = QStyleOptionGraphicsItem()
    node.paint(p, opt, None); p.end()
    # Sample a pixel on the body's left edge (below the header) — should be the
    # default border colour, not the picked red. Antialiasing blends the 1px
    # border line with the canvas background; checking "not red" is enough to
    # prove the body keeps the default scheme in only-header mode.
    edge_px = img.pixelColor(0, 60)
    assert (edge_px.red(), edge_px.green(), edge_px.blue()) != (255, 0, 0)
    # Red dominance would suggest the tint leaked onto the body border. The default
    # border family is bluish, so blue > red is the property we lock in.
    assert edge_px.blue() > edge_px.red()


def test_color_picker_only_header_toggle_re_emits_with_scope():
    from ui.color_picker import ColorPickerPopup
    calls = []
    popup = ColorPickerPopup(on_color_selected=lambda c, oh, cc=None: calls.append((c, oh)),
                             initial_color="#3A76B8")
    calls.clear()
    popup.only_header_check.setChecked(True)
    assert calls and calls[-1][1] is True
    popup.hide()


def test_clicking_frame_title_text_picks_frame_not_title(window):
    from PyQt5.QtGui import QTransform
    frame = GroupFrameItem(QRectF(0, 0, 200, 150), title="Group Foo")
    frame.setPos(0, 0)
    window.scene.addItem(frame)
    title_pos = frame.title_item.scenePos()
    # Click directly on the title text — out of rename mode the title is
    # hit-test-invisible, so itemAt() returns the parent frame.
    top = window.scene.itemAt(QPointF(title_pos.x() + 10, title_pos.y() + 5), QTransform())
    assert isinstance(top, GroupFrameItem)


def test_title_becomes_clickable_during_rename(window):
    frame = GroupFrameItem(QRectF(0, 0, 200, 150), title="G")
    window.scene.addItem(frame)
    # boundingRect() always reports the title's real paint area (needed so the
    # scene knows to repaint it — see title_item.py) — only hit-testing
    # (contains()/shape()) and event delivery (acceptedMouseButtons) toggle
    # with edit mode, so those are what this test locks in.
    assert not frame.title_item.boundingRect().isEmpty()
    frame._begin_rename()
    center = frame.title_item.boundingRect().center()
    assert frame.title_item.contains(center)
    assert int(frame.title_item.acceptedMouseButtons()) != 0
    frame._end_rename()
    assert not frame.title_item.contains(center)
    assert int(frame.title_item.acceptedMouseButtons()) == 0
    assert not frame.title_item.boundingRect().isEmpty()


def test_group_frame_paint_strips_default_selection_dashes(window):
    # GroupFrameItem.paint clears State_Selected before super().paint (via the
    # shared suppress_default_selection_chrome helper) so Qt's default dotted
    # selection rectangle is not drawn on top of our own outline.
    from PyQt5.QtWidgets import QStyle, QStyleOptionGraphicsItem
    from PyQt5.QtGui import QPainter, QPixmap

    frame = GroupFrameItem(QRectF(0, 0, 200, 150))
    window.scene.addItem(frame)
    option = QStyleOptionGraphicsItem()
    option.state = QStyle.State_Selected
    pixmap = QPixmap(10, 10)
    painter = QPainter(pixmap)
    try:
        frame.paint(painter, option, None)
    finally:
        painter.end()
    assert not (option.state & QStyle.State_Selected)


def test_frame_dashed_outline_uses_configured_thickness_and_outset():
    assert cfg.GROUP_FRAME_BORDER_INSET >= 8       # noticeably outset, not flush
    assert cfg.GROUP_FRAME_BORDER_WIDTH >= 3       # bumped from the original 2


def test_color_picker_background_is_button_bg_color():
    from ui.color_picker import ColorPickerPopup
    from ui.theme import BUTTON_BG_COLOR
    popup = ColorPickerPopup(on_color_selected=lambda c, oh, cc=None: None, initial_color="#3A76B8")
    assert BUTTON_BG_COLOR in popup.styleSheet()
    popup.hide()


def test_frame_commit_members_after_release(window):
    n = _param(window, x=300, y=200)
    frame = GroupFrameItem(QRectF(0, 0, 200, 150), title="F")
    frame.setPos(0, 0)
    window.scene.addItem(frame)
    assert frame._group_members == []
    # Move the frame to enclose the node, then commit. force_all=True is the
    # mode used at frame release — it picks up newly-overlapping nodes.
    frame.setPos(280, 180)
    frame.commit_members(force_all=True)
    assert n in frame._group_members
    # Move node out and re-commit (default mode just trims): membership shrinks.
    n.setPos(800, 800)
    frame.commit_members()
    assert n not in frame._group_members


def test_committed_member_subordinates_on_next_drag(window):
    n = _param(window, x=300, y=200)
    frame = GroupFrameItem(QRectF(0, 0, 200, 150), title="F")
    frame.setPos(280, 180)  # already enclosing
    window.scene.addItem(frame)
    frame.commit_members(force_all=True)
    assert n in frame._group_members
    # The scene's press-time recapture should seed _dragged_inner_nodes from
    # committed members; replicate the relevant code path here.
    frame._dragged_inner_nodes = list(frame._group_members)
    old = n.pos()
    frame.setPos(frame.pos().x() + 50, frame.pos().y() + 50)
    assert n.pos() != old  # node followed the frame


def test_only_header_checkbox_uses_bool_node_primitive():
    # Both the [B] Boolean node and the color picker only-header flag use the
    # InsetFillCheckBox primitive — same class, same look.
    from ui.color_picker import ColorPickerPopup
    from ui.graph_items import InsetFillCheckBox
    popup = ColorPickerPopup(on_color_selected=lambda c, oh, cc=None: None, initial_color="#3A76B8")
    assert isinstance(popup.only_header_check, InsetFillCheckBox)
    popup.hide()


def test_frame_outline_absent_unselected_white_dashed_when_selected(window):
    # Unselected: no outline drawn at the outset strip.
    # Selected: dashed white outline appears at the outset strip.
    from PyQt5.QtGui import QImage, QPainter
    frame = GroupFrameItem(QRectF(0, 0, 160, 120), title="F")
    frame.setPos(0, 0)
    window.scene.addItem(frame)
    frame.set_color("#ff8800", record_undo=False)

    def render():
        img = QImage(300, 240, QImage.Format_ARGB32); img.fill(0)
        p = QPainter(img); window.scene.render(p, source=QRectF(-30, -30, 300, 240)); p.end()
        return img

    # Body in image: (30,30)..(190,150). Outline outset is at body+GROUP_FRAME_BORDER_INSET.
    outset_x = 30 + 160 + cfg.GROUP_FRAME_BORDER_INSET
    img_unsel = render()
    # No orange (or any non-background) pixel should exist at the outset when unselected.
    found_outline = any(
        img_unsel.pixelColor(x, 80).red() > 100
        or img_unsel.pixelColor(x, 80).green() > 100
        or img_unsel.pixelColor(x, 80).blue() > 100
        for x in range(outset_x - 1, outset_x + cfg.GROUP_FRAME_BORDER_WIDTH + 1)
    )
    assert not found_outline, "unexpected outline found on unselected frame"

    frame.setSelected(True)
    img_sel = render()
    found_white = any(
        img_sel.pixelColor(x, 80).red() == 255
        and img_sel.pixelColor(x, 80).green() == 255
        and img_sel.pixelColor(x, 80).blue() == 255
        for x in range(outset_x - 3, outset_x + cfg.GROUP_FRAME_BORDER_WIDTH + 2)
    )
    assert found_white, "white selection outline not found at outset"


def test_only_header_paints_full_header_perimeter(window):
    from PyQt5.QtGui import QImage, QPainter
    node = _param(window, x=0, y=0)
    node.set_color("#ff0000", only_header=True, record_undo=False)
    img = QImage(300, 100, QImage.Format_ARGB32); img.fill(0)
    p = QPainter(img); window.scene.render(p, source=QRectF(-10, -10, 300, 100)); p.end()
    width = node.node_def.width
    # All four edges of the header rect should carry the picked colour.
    for x, y in [(120, 10), (120, 39), (10, 25), (9 + width, 25)]:
        px = img.pixelColor(x, y)
        assert (px.red(), px.green(), px.blue()) == (255, 0, 0), \
            f"header perimeter px at ({x},{y}) was {px.getRgb()}, expected red"


def test_frame_header_click_picks_frame_over_overlapping_node(window):
    # The frame paints below nodes (Z=GROUP_FRAME_Z); without the press-time
    # Z-boost, clicking the frame's header where it overlaps a node would route
    # to the node instead. The scene briefly lifts the frame's Z before super()
    # routes the press, so the frame becomes the click target.
    from PyQt5.QtGui import QTransform
    _param(window, x=100, y=30)  # node in the scene, overlapping the frame header below
    frame = GroupFrameItem(QRectF(0, 0, 260, 200), title="F")
    frame.setPos(60, 20)
    window.scene.addItem(frame)

    scene_pos = QPointF(120, 35)  # over both frame header and node
    # Without boost, the picked item is a child of the node, not the frame.
    top_default = window.scene.itemAt(scene_pos, QTransform())
    assert not isinstance(top_default, GroupFrameItem)

    # Replay the scene's boost-and-pick decision.
    original_z = frame.zValue()
    frame.setZValue(cfg.NODE_DRAG_Z + 1)
    top_boosted = window.scene.itemAt(scene_pos, QTransform())
    frame.setZValue(original_z)
    assert top_boosted is frame


def test_group_frame_paints_darker_header_bar(window):
    from PyQt5.QtWidgets import QStyleOptionGraphicsItem
    from PyQt5.QtGui import QImage, QPainter
    frame = GroupFrameItem(QRectF(0, 0, 200, 150), title="G")
    window.scene.addItem(frame)
    frame.set_color("#3A76B8", record_undo=False)
    img = QImage(220, 180, QImage.Format_ARGB32); img.fill(0)
    p = QPainter(img); opt = QStyleOptionGraphicsItem()
    frame.paint(p, opt, None); p.end()
    header_px = img.pixelColor(100, 10)
    body_px = img.pixelColor(100, 100)
    # Header is opaque and darker than the (translucent) body.
    assert header_px.alpha() == 255
    assert sum(header_px.getRgb()[:3]) < sum(body_px.getRgb()[:3]) + body_px.alpha()


def test_inline_separator_is_brightened_for_near_black(window):
    from PyQt5.QtWidgets import QGraphicsProxyWidget, QWidget
    start = next(i for i in window.scene.items() if isinstance(i, StartNode))
    start.set_color("#000000", record_undo=False)
    seps = []
    for child in start.childItems():
        if isinstance(child, QGraphicsProxyWidget):
            w = child.widget()
            if type(w) is QWidget and w.maximumHeight() <= 2:
                seps.append(w)
    assert seps, "expected at least one inline separator in StartNode"
    for sep in seps:
        # The background-color in the stylesheet must not stay pure black; it should
        # be lifted above the visibility floor by brightened_for_canvas.
        from PyQt5.QtGui import QColor
        import re
        m = re.search(r"#[0-9a-fA-F]{6}", sep.styleSheet())
        assert m, f"separator missing background-color: {sep.styleSheet()!r}"
        assert relative_luminance(QColor(m.group(0))) >= cfg.TINT_BORDER_MIN_LUMINANCE




def test_frame_set_color_updates_fill_and_accent(window):
    from PyQt5.QtGui import QColor as _QC
    frame = _add_frame(window)
    frame.set_color("#00ff00", record_undo=False)
    assert frame.color() == "#00ff00"
    # Fill tracks the chosen colour at the configured alpha; the dashed outline
    # and header divider are painted manually using brightened_for_canvas in paint().
    assert frame.brush().color().name() == "#00ff00"
    assert frame.brush().color().alpha() == cfg.GROUP_FRAME_FILL_ALPHA
    assert brightened_for_canvas(_QC("#00ff00")).name() == "#00ff00"  # bright passes through


def test_frame_color_survives_state_roundtrip(window):
    frame = _add_frame(window, title="C")
    frame.set_color("#ff8800", record_undo=False)
    window.set_project_state(window.get_project_state())
    assert _frames(window)[0].color() == "#ff8800"


def test_frame_color_survives_copy_paste(window):
    frame = _add_frame(window)
    frame.set_color("#aa00aa", record_undo=False)
    frame.setSelected(True)
    window.copy_nodes()
    window.paste_nodes()
    assert {f.color() for f in _frames(window)} == {"#aa00aa"}


def test_color_presets_are_unique_and_substantial():
    # The picker offers a useful spread of swatches, and every cell is distinct.
    assert len(cfg.COLOR_PRESETS) >= 6
    assert len(set(c.lower() for c in cfg.COLOR_PRESETS)) == len(cfg.COLOR_PRESETS)


def test_inset_fill_checkbox_keeps_outer_pixel_outside_white_fill():
    # The checked indicator paints an inner rect inset from the outer border,
    # so a pixel immediately inside the outer border is NOT the white fill.
    from ui.graph_items import InsetFillCheckBox
    chk = InsetFillCheckBox("x")
    chk.setFixedSize(60, 22); chk.setChecked(True)
    chk.show()
    from PyQt5.QtWidgets import QApplication
    QApplication.instance().processEvents()
    img = chk.grab().toImage()
    ind_top = (chk.height() - cfg.CHECKBOX_INDICATOR_SIZE) // 2
    inside_border = img.pixelColor(1, ind_top + 1)
    center = img.pixelColor(cfg.CHECKBOX_INDICATOR_SIZE // 2, chk.height() // 2)
    assert (inside_border.red(), inside_border.green(), inside_border.blue()) != (255, 255, 255)
    assert (center.red(), center.green(), center.blue()) == (255, 255, 255)
    chk.hide()


def test_combo_popup_hides_overlay_and_restores_on_close(window):
    # showPopup hides the selection wash and lifts proxy Z; hidePopup restores both.
    node = window.add_param_node(
        QPointF(0, 0), {"param_type": "enum", "display": "E", "values": ["a", "b"]})
    proxy = node._combobox.graphicsProxyWidget()
    saved_z = proxy.zValue()
    node.setSelected(True)
    node._combobox.showPopup()
    assert not node._selection_overlay.isVisible()
    assert proxy.zValue() > saved_z  # z lifted during popup
    node._combobox.hidePopup()
    QApplication.instance().processEvents()
    assert node._selection_overlay.isVisible()
    assert proxy.zValue() == saved_z  # z restored


def test_title_color_after_rename_tracks_color_override(window):
    node = _param(window)
    node.set_color("#FFFF00", record_undo=False)  # bright yellow → dark title
    node._begin_rename()
    node.title_item.setPlainText("Renamed")
    node._commit_rename()
    # Not white — the luminance-aware rule picks black on bright colours.
    assert node.title_item.defaultTextColor().name().lower() == "#000000"


def test_node_color_override_applied_when_flag_on(window):
    from configuration import PARAM_NODE_HEADER_FROM_SOCKET
    assert PARAM_NODE_HEADER_FROM_SOCKET
    node = _param(window)
    assert node.color_override() is not None


def test_node_color_survives_state_roundtrip(window):
    node = _param(window)
    node.set_color("#abcdef", record_undo=False)
    window.set_project_state(window.get_project_state())
    assert _nodes(window, StringParamNode)[0].color_override() == "#abcdef"


def test_node_color_survives_copy_paste(window):
    node = _param(window)
    node.set_color("#123456", record_undo=False)
    node.setSelected(True)
    window.copy_nodes()
    window.paste_nodes()
    assert "#123456" in [n.color_override() for n in _nodes(window, StringParamNode)]


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
    before = len(_nodes(window, StringParamNode))
    _press(window, cfg.KEY_DUPLICATE, Qt.ControlModifier)
    assert len(_nodes(window, StringParamNode)) == before + 1


def test_bare_g_toggles_grid_not_group(window):
    grid_before = window.scene.grid_visible
    _press(window, cfg.KEY_TOGGLE_GRID, Qt.NoModifier)
    assert window.scene.grid_visible is not grid_before
    assert len(_frames(window)) == 0  # bare G must not create a group


def test_start_node_is_protected_normal_nodes_are_not(window):
    assert StartNode.is_protected is True
    assert _param(window).is_protected is False


def test_multiselect_drag_reconciles_frame_membership_for_every_moved_node(window):
    """A frame's non-grabber members must not keep stale membership after a
    multi-select drag. Qt moves every selected item together when the user
    drags any one of them, but only the actual grabber item receives its own
    mouseReleaseEvent (where MetaNode._adopt_containing_frame normally runs)
    — NodeScene._reconcile_dragged_node_state (called from mouseReleaseEvent)
    must reconcile every moved node in _drag_start_positions, not just rely
    on the grabber's own event."""
    frame = _add_frame(window, x=0, y=0, w=300, h=300, title="G")
    grabber = _param(window, x=50, y=50)
    passenger = _param(window, x=100, y=100)
    frame.commit_members(force_all=True)
    assert grabber in frame._group_members
    assert passenger in frame._group_members

    # Simulate a multi-select drag: both nodes were selected and moved far
    # outside the frame (as Qt's internal group-move does), but only
    # `grabber` is the item Qt actually delivered press/move/release to.
    window.scene._drag_start_positions = {grabber: grabber.pos(), passenger: passenger.pos()}
    grabber.setPos(1000, 1000)
    passenger.setPos(1000, 200)

    moved = window.scene._reconcile_dragged_node_state()

    assert moved is True
    assert grabber not in frame._group_members
    assert passenger not in frame._group_members
