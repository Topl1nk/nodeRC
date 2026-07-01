"""node_blueprint.py — Node Specifications Before They Are Drawn

SocketDef/NodeDef describe a node's sockets, rows and colours; the builder
functions translate command records and parameter types into those specs.
Vector grouping folds consecutive X/Y/Z parameters into one collapsible socket.
Everything here is computable without a scene — the visual items in
graph_items.py consume these specs verbatim.
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from configuration import (
    NODE_HEADER_HEIGHT, NODE_ROW_HEIGHT, NODE_FOOTER_HEIGHT, NODE_BOTTOM_PAD,
    NODE_DEFAULT_WIDTH, DEFAULT_HEADER_COLOR,
    SOCKET_COLOR_SCHEMA, INTEGER_PARAM_NAMES,
    TINT_BODY_DARKEN, UI_FONT_FAMILY, NODE_RENAME_FONT_SIZE,
)
from theme import darker_hex

# Visual prefix per parameter type — keeps auto-created nodes consistent with the
# titles the typed ParamNode classes assign themselves.
PARAM_TYPE_PREFIX: Dict[str, str] = {
    "string": "[S]", "bool": "[B]", "integer": "[I]", "float": "[#]",
    "float2": "[#2]", "float3": "[#3]", "enum": "[E]", "enum_int": "[E]",
    "filepath": "[F/D]", "dirpath": "[F/D]", "keyvalue": "[K]",
}


def resolve_color_schema(socket_type: str) -> dict:
    schema = SOCKET_COLOR_SCHEMA.get(socket_type.lower(), SOCKET_COLOR_SCHEMA["any"])
    return {
        "hdr": DEFAULT_HEADER_COLOR,
        "body": darker_hex(DEFAULT_HEADER_COLOR, TINT_BODY_DARKEN),
        "socket": schema["socket"],
    }


def param_spec_name(param) -> str:
    return param if isinstance(param, str) else param.get("name", "")


def resolve_param_type(name: str, param) -> str:
    declared = param.get("type", "string") if isinstance(param, dict) else "string"
    if declared == "string" and name.lower() in INTEGER_PARAM_NAMES:
        return "integer"
    return declared


def html_title(text: str, bold_first: bool = False) -> str:
    parts = text.split(" ", 1)
    first = html.escape(parts[0]) if parts else ""
    if bold_first and parts:
        first = f"<b>{first}</b>"
    rest = f" {html.escape(parts[1])}" if len(parts) > 1 else ""
    return (f'<span style="font-family:{UI_FONT_FAMILY};font-size:{NODE_RENAME_FONT_SIZE}pt;">'
            f'{first}{rest}</span>')


@dataclass
class SocketDef:
    name: str
    kind: str
    row: int = 0
    label: Optional[str] = None
    optional: bool = False
    color: str = SOCKET_COLOR_SCHEMA["any"]["socket"]
    is_exec: bool = False
    param_type: str = "string"
    values: List[str] = field(default_factory=list)
    is_collapsed_vector: bool = False
    is_expanded_vector_start: bool = False
    vector_base: str = ""


@dataclass
class NodeDef:
    title: str
    header_color: str
    body_color: str
    sockets: List[SocketDef] = field(default_factory=list)
    width: int = NODE_DEFAULT_WIDTH
    has_footer: bool = False
    extra_rows: float = 0.0

    @property
    def body_height(self) -> int:
        param_rows = [s.row for s in self.sockets if not s.is_exec]
        rows = max(param_rows, default=-1) + 1
        return int(NODE_HEADER_HEIGHT + (rows + self.extra_rows) * NODE_ROW_HEIGHT + (
            NODE_FOOTER_HEIGHT if self.has_footer else NODE_BOTTOM_PAD
        ))

    def socket_y(self, row: int, is_exec: bool = False) -> float:
        if is_exec:
            return NODE_HEADER_HEIGHT / 2.0
        return NODE_HEADER_HEIGHT + row * NODE_ROW_HEIGHT + NODE_ROW_HEIGHT / 2.0

    def socket_x(self, kind: str) -> float:
        return 0.0 if kind == "input" else float(self.width)


# ── X/Y/Z vector grouping ──────────────────────────────────────────────────────

def _vector_axis_run(params: list, start: int, base: str) -> list:
    run = []
    for offset, suffix in enumerate("xyz"):
        position = start + offset
        if position >= len(params):
            break
        if param_spec_name(params[position]).lower() != (base + suffix).lower():
            break
        run.append(params[position])
    return run


def _mark_expanded_start(param, base: str) -> dict:
    marked = {"name": param_spec_name(param)} if isinstance(param, str) else param.copy()
    marked["is_expanded_vector_start"] = True
    marked["vector_base"] = base
    return marked


def _collapse_vector(axis_params: list, base: str) -> dict:
    is_triple = len(axis_params) == 3
    axes_label = "X,Y,Z" if is_triple else "X,Y"
    return {
        "name": base or ("XYZ" if is_triple else "XY"),
        "label": f"{base} ({axes_label})" if base else axes_label,
        "type": "float3" if is_triple else "float2",
        "original": list(axis_params),
        "is_collapsed_vector": True,
        "vector_base": base,
    }


def group_xyz_params(params: list, expanded_bases: set = None) -> list:
    expanded_bases = expanded_bases or set()
    grouped = []
    index = 0
    while index < len(params):
        head_name = param_spec_name(params[index])
        base = head_name[:-1] if head_name.lower().endswith("x") else None
        axis_run = _vector_axis_run(params, index, base) if base is not None else []

        if len(axis_run) >= 2:
            if base in expanded_bases:
                grouped.append(_mark_expanded_start(axis_run[0], base))
                grouped.extend(axis_run[1:])
            else:
                grouped.append(_collapse_vector(axis_run, base))
            index += len(axis_run)
            continue

        grouped.append(params[index])
        index += 1
    return grouped


# ── Node definition builders ───────────────────────────────────────────────────

def param_node_def(label: str, param_type: str, width: int = 200) -> NodeDef:
    schema = resolve_color_schema(param_type)
    return NodeDef(
        title=html_title(label),
        header_color=schema["hdr"],
        body_color=schema["body"],
        sockets=[SocketDef(
            "value_out", "output", row=0, label=f"{param_type}",
            color=schema["socket"], param_type=param_type,
        )],
        width=width,
        has_footer=True,
    )


def start_node_def() -> NodeDef:
    exec_schema = resolve_color_schema("exec")
    return NodeDef(
        title=html_title("> START"),
        header_color=exec_schema["hdr"],
        body_color=exec_schema["body"],
        sockets=[SocketDef(
            "exec_out", "output", row=-1, label="",
            color=exec_schema["socket"], is_exec=True,
        )],
        width=185,
        has_footer=False,
        extra_rows=5.5,
    )


def _append_param_sockets(sockets: List[SocketDef], param, row: int, optional: bool):
    name   = param_spec_name(param)
    ptype  = resolve_param_type(name, param)
    values = param.get("values", []) if isinstance(param, dict) else []
    label  = param.get("label", name) if isinstance(param, dict) else name
    socket_color = resolve_color_schema(ptype)["socket"]

    sockets.append(SocketDef(
        name, "input", row=row, label=f"{label}  (opt)" if optional else label,
        optional=optional, color=socket_color, param_type=ptype, values=values,
        is_collapsed_vector=param.get("is_collapsed_vector", False) if isinstance(param, dict) else False,
        is_expanded_vector_start=param.get("is_expanded_vector_start", False) if isinstance(param, dict) else False,
        vector_base=param.get("vector_base", "") if isinstance(param, dict) else "",
    ))
    if name.startswith("new"):
        sockets.append(SocketDef(
            f"{name}_out", "output", row=row, label="", optional=optional,
            color=socket_color, param_type=ptype, values=values,
        ))


def command_node_def(cmd_def: dict, expanded_vectors: set = None) -> NodeDef:
    display = cmd_def.get("display", cmd_def.get("command", ""))
    exec_schema = resolve_color_schema("exec")
    sockets: List[SocketDef] = [
        SocketDef("__exec_in__",  "input",  row=-1, label="", color=exec_schema["socket"], is_exec=True),
        SocketDef("__exec_out__", "output", row=-1, label="", color=exec_schema["socket"], is_exec=True),
    ]
    row_idx = 0
    for optional, key in ((False, "required"), (True, "optional")):
        for param in group_xyz_params(cmd_def.get(key, []), expanded_vectors):
            _append_param_sockets(sockets, param, row_idx, optional)
            row_idx += 1
    return NodeDef(
        title=html_title(display, bold_first=True),
        header_color=exec_schema["hdr"],
        body_color=exec_schema["body"],
        sockets=sockets,
        width=235,
    )
