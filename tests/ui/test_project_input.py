"""Characterization tests for the project-input flag on param nodes.

A project-input node exposes its value on the (future) left panel; visually it
must always read as a full-tinted body, never the header-only scope every
other param node defaults to (see ui/graph_items.py set_color/set_project_input).
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QCursor, QKeyEvent, QMouseEvent
from PyQt5.QtWidgets import QLabel

from ui.color_picker import ColorPickerPopup
from ui.param_nodes import StringParamNode, Float3ParamNode
from ui.project_inputs_panel import ProjectInputsHoverFilter
from configuration import (
    PROJECT_INPUTS_PANEL_HOVER_HIDE_MARGIN, PROJECT_INPUTS_PANEL_HOVER_REVEAL_MARGIN,
)


def _param(window, x=0, y=0):
    return window.add_param_node(QPointF(x, y), {"param_type": "string", "display": "s"})


def _nodes(window, cls):
    return [i for i in window.scene.items() if isinstance(i, cls)]


def test_marking_project_input_strips_default_only_header_scope(window):
    node = _param(window)
    assert node.color_only_header() is True  # PARAM_NODE_HEADER_FROM_SOCKET default

    node.set_project_input(True, record_undo=False)

    assert node.is_project_input() is True
    assert node.color_only_header() is False
    assert node.color_override() is not None  # the tint itself survives, only the scope changes


def test_set_color_clamps_only_header_for_project_input_node(window):
    node = _param(window)
    node.set_project_input(True, record_undo=False)

    node.set_color("#ff0000", only_header=True, record_undo=False)

    assert node.color_only_header() is False


def test_unmarking_restores_the_only_header_scope_it_overrode(window):
    node = _param(window)
    assert node.color_only_header() is True  # default scope before marking

    node.set_project_input(True, record_undo=False)
    assert node.color_only_header() is False

    node.set_project_input(False, record_undo=False)

    assert node.is_project_input() is False
    assert node.color_only_header() is True  # restored, not left stuck full-tint


def test_unmarking_leaves_a_never_only_header_node_untouched(window):
    node = _param(window)
    node.set_color("#ff0000", only_header=False, record_undo=False)

    node.set_project_input(True, record_undo=False)
    node.set_project_input(False, record_undo=False)

    assert node.color_only_header() is False
    assert node.color_override() == "#ff0000"


def test_toggle_context_action_marks_every_selected_param_node(window):
    a = _param(window, 0, 0)
    b = _param(window, 100, 0)
    c = _param(window, 200, 0)  # left unselected — must stay untouched
    a.setSelected(True)
    b.setSelected(True)

    a._toggle_project_input()

    assert a.is_project_input() is True
    assert b.is_project_input() is True
    assert c.is_project_input() is False


def test_toggle_context_action_unmarks_every_selected_param_node(window):
    a = _param(window, 0, 0)
    b = _param(window, 100, 0)
    a.set_project_input(True, record_undo=False)
    b.set_project_input(True, record_undo=False)
    a.setSelected(True)
    b.setSelected(True)

    a._toggle_project_input()  # a is marked -> target is "unmark everyone selected"

    assert a.is_project_input() is False
    assert b.is_project_input() is False
    assert a.color_only_header() is True
    assert b.color_only_header() is True


def test_project_input_survives_state_roundtrip(window):
    node = _param(window)
    node.set_project_input(True, record_undo=False)

    window.set_project_state(window.get_project_state())

    restored = _nodes(window, StringParamNode)[0]
    assert restored.is_project_input() is True
    assert restored.color_only_header() is False


def test_project_input_flag_carries_over_vector_split_merge(window):
    node = window.add_param_node(QPointF(0, 0), {"param_type": "float3", "display": "V"})
    node.set_project_input(True, record_undo=False)

    node.toggle_vector_expansion(next(iter(node._vector_buttons)))

    new_node = _nodes(window, Float3ParamNode)[0]
    assert new_node.is_project_input() is True


def test_panel_reload_adds_and_removes_rows_as_flag_toggles(window):
    node = _param(window)
    assert window.project_inputs_panel._rows == {}

    node.set_project_input(True, record_undo=False)
    window.project_inputs_panel.reload()
    assert list(window.project_inputs_panel._rows.keys()) == [node]

    node.set_project_input(False, record_undo=False)
    window.project_inputs_panel.reload()
    assert window.project_inputs_panel._rows == {}


def test_panel_row_edit_writes_back_to_node(window):
    node = _param(window)
    node.set_project_input(True, record_undo=False)
    window.project_inputs_panel.reload()

    row = window.project_inputs_panel._rows[node]
    row.editor.setText("hello from panel")
    row._on_editor_committed()

    assert node.get_value_state() == "hello from panel"


def test_node_edit_refreshes_panel_row(window):
    node = _param(window)
    node.set_project_input(True, record_undo=False)
    window.project_inputs_panel.reload()

    node._editor.setText("edited on canvas")

    row = window.project_inputs_panel._rows[node]
    assert row.editor.text() == "edited on canvas"


def test_push_undo_state_keeps_panel_in_sync(window):
    node = _param(window)
    node.set_project_input(True)  # record_undo=True -> push_undo_state -> reload()

    assert list(window.project_inputs_panel._rows.keys()) == [node]


def test_tab_switch_shows_only_active_tab_project_inputs(window):
    node_a = _param(window)
    node_a.set_project_input(True)

    window.new_tab()
    node_b = _param(window)
    node_b.set_project_input(True)

    assert list(window.project_inputs_panel._rows.keys()) == [node_b]

    window.switch_to_adjacent_tab(-1)
    assert list(window.project_inputs_panel._rows.keys()) == [node_a]


def test_color_popup_disables_only_header_checkbox_for_project_input(window):
    node = _param(window)
    node.set_project_input(True, record_undo=False)

    popup = ColorPickerPopup(
        on_color_selected=lambda *a: None,
        initial_color=node.color_override(),
        initial_only_header=node.color_only_header(),
        only_header_locked=True,
    )
    assert popup.only_header_check.isEnabled() is False
    assert popup.only_header_check.isChecked() is False


# ── Phase D: hotkey, pin, hover-reveal ───────────────────────────────────────

def test_panel_is_closed_at_startup(window):
    """The Project Inputs panel must not be open before the user asked for
    it (ст. 0.2) — hover-reveal and the Q/Ctrl+I toggle still work against a
    hidden widget."""
    assert window.project_inputs_panel.isVisibleTo(window) is False


def test_ctrl_i_toggles_panel_visibility(window):
    panel = window.project_inputs_panel
    before = panel.isVisibleTo(window)

    event = QKeyEvent(QEvent.KeyPress, Qt.Key_I, Qt.ControlModifier)
    window.keyPressEvent(event)

    assert panel.isVisibleTo(window) is not before

    window.keyPressEvent(event)
    assert panel.isVisibleTo(window) is before


def test_hover_filter_reveals_panel_near_left_edge(window, monkeypatch):
    panel = window.project_inputs_panel
    panel.setVisible(False)
    local = QPoint(PROJECT_INPUTS_PANEL_HOVER_REVEAL_MARGIN, 100)
    monkeypatch.setattr(QCursor, "pos", staticmethod(lambda: window.mapToGlobal(local)))

    ProjectInputsHoverFilter._sync_window(window)

    assert panel.isVisibleTo(window) is True


def test_hover_filter_hides_panel_once_cursor_clears_it(window, monkeypatch):
    panel = window.project_inputs_panel
    panel.setVisible(True)
    far_x = panel.width() + PROJECT_INPUTS_PANEL_HOVER_HIDE_MARGIN + 10
    local = QPoint(far_x, 100)
    monkeypatch.setattr(QCursor, "pos", staticmethod(lambda: window.mapToGlobal(local)))

    ProjectInputsHoverFilter._sync_window(window)

    assert panel.isVisibleTo(window) is False


def test_pinned_panel_ignores_hover_hide(window, monkeypatch):
    panel = window.project_inputs_panel
    panel.setVisible(True)
    panel._pin_check.setChecked(True)
    far_x = panel.width() + PROJECT_INPUTS_PANEL_HOVER_HIDE_MARGIN + 10
    local = QPoint(far_x, 100)
    monkeypatch.setattr(QCursor, "pos", staticmethod(lambda: window.mapToGlobal(local)))

    ProjectInputsHoverFilter._sync_window(window)

    assert panel.isVisibleTo(window) is True


# ── Panel geometry: border, overlay, resize ─────────────────────────────────

def test_panel_has_a_one_pixel_right_border_in_the_configured_color(window):
    from configuration import PROJECT_INPUTS_PANEL_BORDER_COLOR
    style = window.project_inputs_panel.styleSheet()
    assert f"border-right: 1px solid {PROJECT_INPUTS_PANEL_BORDER_COLOR}" in style


def test_panel_floats_over_the_view_without_resizing_it(window):
    window.resize(900, 600)
    window.show()
    view_width_before = window.view.width()

    window.project_inputs_panel.setVisible(True)
    assert window.view.width() == view_width_before
    window.project_inputs_panel.setVisible(False)
    assert window.view.width() == view_width_before


def test_panel_sits_below_the_title_bar_not_overlapping_it(window):
    window.resize(900, 600)
    window.show()
    assert window.project_inputs_panel.y() == window.title_bar.height()


def test_resize_grip_drags_panel_width_within_bounds(window):
    from configuration import PROJECT_INPUTS_PANEL_MAX_WIDTH, PROJECT_INPUTS_PANEL_MIN_WIDTH
    panel = window.project_inputs_panel
    grip = panel._grip
    start_width = panel.width()

    press = QMouseEvent(QEvent.MouseButtonPress, QPoint(2, 50), QPoint(2, 50),
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    grip.mousePressEvent(press)
    move = QMouseEvent(QEvent.MouseMove, QPoint(52, 50), QPoint(52, 50),
                       Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    grip.mouseMoveEvent(move)
    assert panel.width() == start_width + 50

    far_left = QMouseEvent(QEvent.MouseMove, QPoint(-5000, 50), QPoint(-5000, 50),
                           Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    grip.mouseMoveEvent(far_left)
    assert panel.width() == PROJECT_INPUTS_PANEL_MIN_WIDTH

    far_right = QMouseEvent(QEvent.MouseMove, QPoint(5000, 50), QPoint(5000, 50),
                            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    grip.mouseMoveEvent(far_right)
    assert panel.width() == PROJECT_INPUTS_PANEL_MAX_WIDTH


# ── Row layout: drag handle, socket label, editor, socket dot ───────────────

def test_row_children_are_handle_label_editor_dot_in_order(window):
    from ui.project_inputs_panel import _DragHandle, _SocketDot
    node = _param(window)
    node.set_project_input(True, record_undo=False)
    window.project_inputs_panel.reload()
    row = window.project_inputs_panel._rows[node]

    assert isinstance(row.handle, _DragHandle)
    assert isinstance(row.label, QLabel)
    assert isinstance(row.dot, _SocketDot)


def test_row_widgets_are_positioned_in_the_shared_grid(window):
    node = _param(window)
    node.set_project_input(True, record_undo=False)
    window.project_inputs_panel.reload()
    panel = window.project_inputs_panel
    row = panel._rows[node]

    idx = panel._layout.indexOf(row.handle)
    assert panel._layout.getItemPosition(idx)[1] == 0
    idx = panel._layout.indexOf(row.label)
    assert panel._layout.getItemPosition(idx)[1] == 1
    idx = panel._layout.indexOf(row.editor)
    assert panel._layout.getItemPosition(idx)[1] == 2
    idx = panel._layout.indexOf(row.dot)
    assert panel._layout.getItemPosition(idx)[1] == 3


def test_row_label_matches_the_nodes_own_socket_label_and_color(window):
    node = _param(window)
    node.set_project_input(True, record_undo=False)
    window.project_inputs_panel.reload()
    row = window.project_inputs_panel._rows[node]
    socket_def = node.primary_output_socket_def()

    assert row.label.text() == socket_def.label
    assert socket_def.color in row.label.styleSheet()


def test_all_rows_editors_share_the_same_width_and_left_edge(window):
    # Editors stretch with the panel (grid column 2 carries the stretch)
    # rather than sitting at one hardcoded width — the alignment invariant
    # is that every row's editor occupies the same column span, so all
    # widths and left edges match each other.
    a = window.add_param_node(QPointF(0, 0), {"param_type": "string", "display": "a"})
    b = window.add_param_node(QPointF(0, 0), {"param_type": "bool", "display": "b"})
    c = window.add_param_node(QPointF(0, 0), {"param_type": "float3", "display": "c"})
    for n in (a, b, c):
        n.set_project_input(True, record_undo=False)
    panel = window.project_inputs_panel
    panel.reload()
    window.resize(900, 600)
    window.show()

    widths = {panel._rows[n].editor.width() for n in (a, b, c)}
    left_edges = {panel._rows[n].editor.mapTo(panel, QPoint(0, 0)).x() for n in (a, b, c)}
    assert len(widths) == 1
    assert len(left_edges) == 1


def test_keyvalue_param_gets_a_live_text_field_not_a_readonly_label(window):
    node = window.add_param_node(QPointF(0, 0), {"param_type": "keyvalue", "display": "kv"})
    node.set_project_input(True, record_undo=False)
    window.project_inputs_panel.reload()
    row = window.project_inputs_panel._rows[node]

    assert row.editor.isReadOnly() is False
    row.editor.setText("a=b")
    row._on_editor_committed()
    assert node.get_value_state() == "a=b"


def test_composite_value_is_formatted_not_raw_repr(window):
    node = window.add_param_node(QPointF(0, 0), {"param_type": "float3", "display": "v"})
    node.set_project_input(True, record_undo=False)
    window.project_inputs_panel.reload()
    row = window.project_inputs_panel._rows[node]

    assert row.editor.isReadOnly() is True
    assert "[" not in row.editor.text() and "'" not in row.editor.text()


def test_row_editor_is_the_nodes_own_factory_widget_uncolored_by_the_node(window):
    node = _param(window)
    node.set_color("#ff0000", record_undo=False)
    node.set_project_input(True, record_undo=False)
    window.project_inputs_panel.reload()
    row = window.project_inputs_panel._rows[node]

    # Built via ui.value_widgets.build_text_field — the same primitive
    # node._make_field delegates to — but it was never parented under the
    # node, so _update_children_colors never re-skinned it with its red tint.
    assert "#ff0000" not in row.editor.styleSheet().lower()


def test_socket_dot_hover_toggles_the_nodes_own_white_outline(window):
    node = _param(window)
    node.set_project_input(True, record_undo=False)
    window.project_inputs_panel.reload()
    row = window.project_inputs_panel._rows[node]

    assert node._hovered is False
    row.dot.enterEvent(QEvent(QEvent.Enter))
    assert node._hovered is True
    row.dot.leaveEvent(QEvent(QEvent.Leave))
    assert node._hovered is False


def test_socket_dot_click_selects_and_centers_the_node(window):
    node = _param(window)
    node.set_project_input(True, record_undo=False)
    window.project_inputs_panel.reload()
    row = window.project_inputs_panel._rows[node]
    node.setSelected(False)

    press = QMouseEvent(QEvent.MouseButtonPress, QPoint(5, 5), QPoint(5, 5),
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    row.dot.mousePressEvent(press)

    assert node.isSelected() is True


# ── Row drag-to-reorder ──────────────────────────────────────────────────────

def test_drag_handle_reorders_rows(window):
    a = _param(window, 0, 0)
    b = _param(window, 100, 0)
    c = _param(window, 200, 0)
    for n in (a, b, c):
        n.set_project_input(True, record_undo=False)
    panel = window.project_inputs_panel
    panel.reload()
    # reload() draws initial order from scene.items(), which is not
    # creation order — pin it explicitly so the drag assertion below is
    # about the drag, not about incidental scene ordering.
    panel._order = [a, b, c]
    panel._relayout_rows()

    row_c = panel._rows[c]
    panel.begin_row_drag(a)
    # Dragging "a" to just above the bottom of "c"'s row moves it to the end.
    target_y = row_c.handle.y() + row_c.handle.height() - 1
    panel.drag_row_to(a, panel.mapToGlobal(QPoint(0, target_y)).y())
    panel.end_row_drag()

    assert panel._order == [b, c, a]


def test_reorder_survives_reload(window):
    a = _param(window, 0, 0)
    b = _param(window, 100, 0)
    for n in (a, b):
        n.set_project_input(True, record_undo=False)
    panel = window.project_inputs_panel
    panel.reload()
    panel._order = [b, a]
    panel._relayout_rows()

    panel.reload()  # no membership change -> must not reset the manual order

    assert panel._order == [b, a]
