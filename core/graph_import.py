"""graph_import.py — Building a Graph from a Pack-Parsed Text Script

The import counterpart of graph_export.py: hands raw text to a pack's own
parse_import (PackExecutor.parse_import, e.g. RealityScan's .bat/.rscmd
reader), then turns the structured [{"command": cmd_def, "params": {...}}]
it recovers into a real GraphModel — Start, one CommandNode per recovered
command wired into a linear exec chain, and one typed ParamNode per
non-empty param wired into that command's matching input socket.

Nothing here knows how any pack's text format is actually shaped; that
stays entirely inside the pack (Ст.4.2), same boundary graph_export.py
already keeps. Zero Qt or ui imports (Ст.3) — ui/editor_window.py turns the
returned GraphModel into live canvas items via the same
ui.graph_serialization.materialize_graph path project-load already uses,
by calling GraphModel.to_dict().
"""
from __future__ import annotations

from typing import Callable, Optional, Tuple

from core.graph_model import ConnectionModel, GraphModel, NodeModel
from core.node_blueprint import PARAM_NODE_TYPE_NAMES, PARAM_OUTPUT_SOCKETS, PARAM_TYPE_PREFIX, resolve_param_type
from core.pack_protocol import PackExecutor

_START_X, _START_Y = -900.0, 80.0
_COMMAND_X_STEP = 220.0
_PARAM_X_OFFSET = -20.0
_PARAM_Y_STEP = 90.0


def _param_creation_data(name: str, param, value: str) -> Tuple[str, dict]:
    """(node_type_string, creation_data) for a ParamNode holding ``value``
    for one command param spec — the headless equivalent of
    ui/command_nodes.py's CommandNode.auto_create_required_parameters,
    which builds the identical creation_data shape from live Qt code for
    the existing "Auto-Create Parameters" context action (Ст.1.1: same
    param_type -> prefix/node-type resolution, not a second guess at it)."""
    ptype = resolve_param_type(name, param)
    prefix = PARAM_TYPE_PREFIX.get(ptype, "")
    values = param.get("values", []) if isinstance(param, dict) else []
    creation_data = {
        "param_type": ptype,
        "display": f"{prefix} {name}" if prefix else name,
        "values": values,
    }
    node_type = PARAM_NODE_TYPE_NAMES.get(ptype, "StringParamNode")
    return node_type, creation_data


def _param_current_value(node_type: str, value: str, values: list):
    """The ``current_value`` shape each ParamNode subtype's own
    get_value_state/set_value_state expects (ui/param_nodes.py) — a plain
    string import value has to be reshaped per type, since e.g. DirParamNode
    stores {"dir": ...} and EnumParamNode stores {"items": [...], "current":
    ...}, not a bare string. FileParamNode isn't handled here at all — see
    _spawn_filepath_nodes, which decomposes it into its own wired-in
    dirpath/filename/filetype sub-nodes instead of one flat current_value."""
    if node_type == "DirParamNode":
        return {"dir": value}
    if node_type == "EnumParamNode":
        return {"items": values or [value], "current": value}
    if node_type == "BoolParamNode":
        return value.strip().lower() in ("true", "1", "yes")
    if node_type == "IntParamNode":
        try:
            return int(float(value))
        except ValueError:
            return 0
    if node_type in ("Float2ParamNode", "Float3ParamNode"):
        return value.split()
    return value


def _spawn_filepath_nodes(alloc, x: float, y: float, value: str):
    """A FileParamNode plus its own decomposed dirpath/filename/filetype
    sub-nodes, wired into its three input sockets — the same shape a user
    gets from wiring separate Dir/String param nodes into "[Add] File" by
    hand (dirpath_in <- DirParamNode, filename <- StringParamNode, filetype
    <- StringParamNode), not one flat {"dir","file","ext"} current_value
    crammed into the FileParamNode itself. FileParamNode.get_value() reads
    its connected inputs' live values first (ui/param_nodes.py's
    _get_connected_input_value), falling back to its own widget state only
    when nothing is wired — so the FileParamNode's own current_value is
    left at its default (empty) and never needs to duplicate what its
    children already carry.

    Returns (extra_nodes, extra_connections, file_uid, out_socket,
    rows_used) — the caller splices extra_nodes/extra_connections into its
    own lists and wires ``out_socket`` on ``file_uid`` into whatever
    command param this filepath value was for.
    """
    normalized = value.replace("\\", "/")
    dirname, _, rest = normalized.rpartition("/")
    filename, dot, ext = rest.rpartition(".") if "." in rest else ("", "", "")
    if not filename:
        filename, ext = rest, ""

    file_uid = alloc()
    # No explicit "display": build_param_node (ui/graph_serialization.py)
    # falls back to the type's own default title ("[Add] File") when name
    # is falsy — exactly what a fresh FileParamNode gets when spawned any
    # other way, e.g. via CommandNode.auto_create_required_parameters.
    nodes = [NodeModel(uid=file_uid, node_type="FileParamNode", x=x, y=y,
                        creation_data={"param_type": "filepath", "display": "", "values": []})]
    connections = []
    row_y = y + _PARAM_Y_STEP
    rows = 0

    if dirname:
        dir_uid = alloc()
        prefix = PARAM_TYPE_PREFIX.get("dirpath", "")
        nodes.append(NodeModel(uid=dir_uid, node_type="DirParamNode", x=x + _PARAM_X_OFFSET, y=row_y,
                                creation_data={"param_type": "dirpath", "display": f"{prefix} folder", "values": []},
                                current_value={"dir": dirname}))
        connections.append(ConnectionModel(dir_uid, "value_out", file_uid, "dirpath_in"))
        row_y += _PARAM_Y_STEP
        rows += 1

    if filename:
        name_uid = alloc()
        prefix = PARAM_TYPE_PREFIX.get("string", "")
        nodes.append(NodeModel(uid=name_uid, node_type="StringParamNode", x=x + _PARAM_X_OFFSET, y=row_y,
                                creation_data={"param_type": "string", "display": f"{prefix} filename", "values": []},
                                current_value=filename))
        connections.append(ConnectionModel(name_uid, "value_out", file_uid, "filename"))
        row_y += _PARAM_Y_STEP
        rows += 1

    if ext:
        ext_uid = alloc()
        prefix = PARAM_TYPE_PREFIX.get("string", "")
        nodes.append(NodeModel(uid=ext_uid, node_type="StringParamNode", x=x + _PARAM_X_OFFSET, y=row_y,
                                creation_data={"param_type": "string", "display": f"{prefix} extension", "values": []},
                                current_value=ext))
        connections.append(ConnectionModel(ext_uid, "value_out", file_uid, "filetype"))
        rows += 1

    return nodes, connections, file_uid, "path_out", rows


def build_graph_from_script(text: str, format_id: str, pack_id: str,
                             executor_factory: Callable[[str], Optional[PackExecutor]]) -> Tuple[Optional[GraphModel], str]:
    """Parses ``text`` via ``pack_id``'s own parse_import and turns the
    result into a fresh GraphModel (Start -> one CommandNode per recovered
    command, in order, each non-empty param backed by its own ParamNode).
    Returns (None, error_message) if the pack isn't installed or its own
    parser reports failure — never raises, mirroring render_graph_export's
    error-reporting shape.
    """
    executor = executor_factory(pack_id)
    if executor is None:
        return None, f"No pack installed for '{pack_id}'."

    result = executor.parse_import(text, format_id)
    if not result.ok:
        return None, result.error

    next_uid = 1

    def alloc() -> int:
        nonlocal next_uid
        uid = next_uid
        next_uid += 1
        return uid

    start_uid = alloc()
    nodes = [NodeModel(uid=start_uid, node_type="StartNode", x=_START_X, y=_START_Y)]
    connections = []
    prev_uid, prev_socket = start_uid, "exec_out"
    x = _START_X + _COMMAND_X_STEP

    for entry in result.commands:
        cmd_def = entry["command"]
        params = entry.get("params", {})

        cmd_uid = alloc()
        nodes.append(NodeModel(uid=cmd_uid, node_type="CommandNode", x=x, y=_START_Y, cmd_def=cmd_def))
        connections.append(ConnectionModel(prev_uid, prev_socket, cmd_uid, "__exec_in__"))
        prev_uid, prev_socket = cmd_uid, "__exec_out__"

        declared = list(cmd_def.get("required", [])) + list(cmd_def.get("optional", []))
        param_y = _START_Y + _PARAM_Y_STEP
        for param in declared:
            name = param["name"] if isinstance(param, dict) else param
            value = str(params.get(name, "") or "").strip()
            if not value:
                continue
            node_type, creation_data = _param_creation_data(name, param, value)
            if node_type == "FileParamNode":
                extra_nodes, extra_connections, param_uid, out_socket, rows = _spawn_filepath_nodes(
                    alloc, x + _PARAM_X_OFFSET, param_y, value)
                nodes.extend(extra_nodes)
                connections.extend(extra_connections)
                connections.append(ConnectionModel(param_uid, out_socket, cmd_uid, name))
                param_y += _PARAM_Y_STEP * (rows + 1)
                continue

            param_uid = alloc()
            current_value = _param_current_value(node_type, value, creation_data.get("values", []))
            nodes.append(NodeModel(uid=param_uid, node_type=node_type, x=x + _PARAM_X_OFFSET, y=param_y,
                                    creation_data=creation_data, current_value=current_value))
            out_socket = PARAM_OUTPUT_SOCKETS.get(creation_data["param_type"], "value_out")
            connections.append(ConnectionModel(param_uid, out_socket, cmd_uid, name))
            param_y += _PARAM_Y_STEP

        x += _COMMAND_X_STEP

    return GraphModel(nodes=nodes, connections=connections), ""
