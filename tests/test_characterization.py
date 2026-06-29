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


def test_auto_create_promotes_integer_named_params(window):
    cmd = _command(window, required=["width", "name"])
    reqs = []
    for p in nc.group_xyz_params(cmd.cmd_def["required"], set()):
        sock = cmd.get_socket(nc.param_spec_name(p))
        if sock:
            reqs.append((p, sock))
    cmd.auto_create_required_parameters(reqs)

    displays = [p.creation_data["display"] for p in _nodes_of(window, nb._BaseParamNode)]
    assert any(d.startswith("[I] width") for d in displays)
    assert any(d.startswith("[S] name") for d in displays)
