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
from PyQt5.QtCore import QPointF, QEvent
from PyQt5.QtGui import QFocusEvent

import canvas
import nodes_base as nb
import nodes_concrete as nc


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    return canvas.NodeEditorWindow()


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

    restored = _nodes_of(window, nc.EnumParamNode)[0]
    items = [restored._combobox.itemText(i) for i in range(restored._combobox.count())]
    assert items == ["opt1", "opt2", "Custom_A"]
    assert restored._combobox.currentText() == "Custom_A"


def test_path_ext_filter_survives_state_roundtrip(window):
    path = _param(window, "filepath")
    path._dir_editor.setText("C:/tmp")
    path._ext_filter.setText("*.jpg")

    window.set_project_state(window.get_project_state())

    restored = _nodes_of(window, nc.PathParamNode)[0]
    assert restored._ext_filter.text() == "*.jpg"
    assert restored._dir_editor.text() == "C:/tmp"


def test_enum_legacy_string_state_still_loads(window):
    enum = _param(window, "enum", values=["a", "b"])
    enum.set_value_state("b")  # legacy saves stored only the selected text
    assert enum._combobox.currentText() == "b"


# ── project save / load ─────────────────────────────────────────────────────────

def test_file_save_load_preserves_graph(window, tmp_path):
    _param(window, "string", x=0).set_value_state("kept")
    _param(window, "integer", x=120).set_value_state(7)
    before = len(_nodes_of(window, nb.MetaNode))

    path = tmp_path / "proj.json"
    path.write_text(json.dumps(window._capture(include_selection=False)))
    window._restore(json.loads(path.read_text()), restore_selection=False)

    assert len(_nodes_of(window, nb.MetaNode)) == before
    assert _nodes_of(window, nc.StringParamNode)[0].get_value_state() == "kept"
    assert _nodes_of(window, nc.IntParamNode)[0].get_value_state() == 7


# ── clipboard ───────────────────────────────────────────────────────────────────

def test_copy_paste_duplicates_param_nodes(window):
    node = _param(window, "string")
    node.set_value_state("dup")
    node.setSelected(True)

    window.copy_nodes()
    before = len(_nodes_of(window, nc.StringParamNode))
    window.paste_nodes()

    strings = _nodes_of(window, nc.StringParamNode)
    assert len(strings) == before + 1
    assert all(s.get_value_state() == "dup" for s in strings)


def test_start_node_is_not_copied(window):
    start = _nodes_of(window, nc.StartNode)[0]
    start.setSelected(True)
    window.copy_nodes()
    window.paste_nodes()
    assert len(_nodes_of(window, nc.StartNode)) == 1


# ── undo / redo ─────────────────────────────────────────────────────────────────

def test_undo_redo_param_value(window):
    node = _param(window, "string")
    node.set_value_state("v1")
    node._on_widget_user_edit()  # commits an undo snapshot

    node.set_value_state("v2")
    node._on_widget_user_edit()

    window.undo()
    assert _nodes_of(window, nc.StringParamNode)[0].get_value_state() == "v1"
    window.redo()
    assert _nodes_of(window, nc.StringParamNode)[0].get_value_state() == "v2"


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
    node._apply_title("Tom & Jerry <x>")
    assert node.title_item.toPlainText() == "Tom & Jerry <x>"


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
    rebuilt = _nodes_of(window, nc.CommandNode)[0]
    assert rebuilt.isSelected()


def test_restore_isolates_a_corrupt_node(window):
    # Article 5.2: a single unreadable node must not lose the whole project.
    good_a = _param(window, "string", x=0); good_a.set_value_state("A")
    good_b = _param(window, "integer", x=120); good_b.set_value_state(9)
    payload = window.get_project_state()
    payload["nodes"].insert(1, {"id": 999, "type": "CommandNode", "x": 0, "y": 0})  # no cmd_def

    window.set_project_state(payload)

    assert _nodes_of(window, nc.StringParamNode)[0].get_value_state() == "A"
    assert _nodes_of(window, nc.IntParamNode)[0].get_value_state() == 9


def test_restore_isolates_a_corrupt_connection(window):
    a = _param(window, "string", x=0)
    payload = window.get_project_state()
    payload["connections"].append({"src_node": a.scenePos and 1})  # malformed record

    window.set_project_state(payload)  # must not raise

    assert len(_nodes_of(window, nc.StringParamNode)) == 1


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
    assert _nodes_of(window, nc.StringParamNode)[0].get_value_state() == "saved"


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
    from search_menu import SearchMenuDialog
    dialog = SearchMenuDialog({}, None)
    dialog.search_bar.setText("string")
    assert dialog.tree.currentItem() is not None  # first match auto-selected
    dialog._activate_selection()
    assert dialog.payload is not None
    assert dialog.payload.get("param_type") == "string"


def test_search_menu_arrow_moves_selection(app):
    from search_menu import SearchMenuDialog
    dialog = SearchMenuDialog({}, None)
    dialog.search_bar.setText("")  # show every parameter type
    dialog._select_first_match()
    first = dialog.tree.currentItem()
    dialog._move_selection(1)
    assert dialog.tree.currentItem() is not None
    assert dialog.tree.currentItem() is not first


def _search_dialog(app):
    from search_menu import SearchMenuDialog
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
    from PyQt5.QtWidgets import QGraphicsView, QGraphicsRectItem
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

    displays = [p.creation_data["display"] for p in _nodes_of(window, nb._BaseParamNode)]
    assert any(d.startswith("[I] width") for d in displays)
    assert any(d.startswith("[S] name") for d in displays)


def test_auto_create_works_when_some_params_already_connected(window):
    cmd = _command(window, required=["width", "height"])
    # pre-connect one param
    p = _param(window, "integer")
    ws = cmd.get_socket("width")
    o = p.get_socket("value_out")
    from nodes_base import Connection
    window.scene._enforce_connection_rules(o, ws)
    c = Connection(o, ws)
    window.scene.addItem(c)
    window.connections.append(c)
    assert len(window.connections) == 1

    cmd.auto_create_required_parameters()
    # both params created/wired; original manual wire replaced
    created = _nodes_of(window, nb._BaseParamNode)
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
