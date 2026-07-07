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
from typing import Dict, List, Optional, Tuple

from configuration import (
    NODE_HEADER_HEIGHT, NODE_ROW_HEIGHT, NODE_FOOTER_HEIGHT, NODE_BOTTOM_PAD,
    NODE_DEFAULT_WIDTH, DEFAULT_HEADER_COLOR, DEFAULT_BODY_COLOR,
    SOCKET_COLOR_SCHEMA, INTEGER_PARAM_NAMES,
    UI_FONT_FAMILY, NODE_RENAME_FONT_SIZE,
)

# Visual prefix per parameter type — keeps auto-created nodes consistent with the
# titles the typed ParamNode classes assign themselves.
PARAM_TYPE_PREFIX: Dict[str, str] = {
    "string": "[S]", "bool": "[B]", "integer": "[I]", "float": "[#]",
    "float2": "[#2]", "float3": "[#3]", "enum": "[E]", "enum_int": "[E]",
    "filepath": "[F/D]", "dirpath": "[F/D]", "keyvalue": "[K]",
}

# The gettext key each param type's default (never-renamed) title resolves
# through — shared by the typed ParamNode classes (ui/param_nodes.py, each
# falls back to this key when constructed with no explicit name) and by
# every place that re-resolves a default title on load/language change
# (build_param_node below, ParamNode.retranslate). One mapping so the two
# can never drift apart the way "integer" -> f"param_{ptype}_title" used to
# silently miss the real "param_int_title" key.
PARAM_TITLE_KEY: Dict[str, str] = {
    "string": "param_string_title", "bool": "param_bool_title",
    "integer": "param_int_title", "float": "param_float_title",
    "float2": "param_float2_title", "float3": "param_float3_title",
    "enum": "param_enum_title", "enum_int": "param_enum_title",
    "filepath": "param_path_title", "dirpath": "param_path_title",
    "path": "param_path_title", "keyvalue": "param_keyvalue_title",
}


def resolve_color_schema(socket_type: str) -> dict:
    schema = SOCKET_COLOR_SCHEMA.get(socket_type.lower(), SOCKET_COLOR_SCHEMA["any"])
    return {
        "hdr": DEFAULT_HEADER_COLOR,
        "body": DEFAULT_BODY_COLOR,
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
    return (f'<span style="font-family:{UI_FONT_FAMILY};font-size:{NODE_RENAME_FONT_SIZE}pt;">'
            f'<b>{html.escape(text)}</b></span>')


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
    plain_title: str = ""

    @property
    def param_row_count(self) -> int:
        param_rows = [s.row for s in self.sockets if not s.is_exec]
        return max(param_rows, default=-1) + 1

    @property
    def body_height(self) -> int:
        rows = self.param_row_count
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
#
# Two ways a run of consecutive params folds into one compact vector socket:
#  - a shared-prefix axis suffix ('offsetX/offsetY/offsetZ', bare 'x/y/z') —
#    detected by stripping a trailing 'x' off the first name and checking the
#    next names match base+'y'/base+'z';
#  - a fixed named triple with no shared prefix at all ('yaw/pitch/roll') —
#    RC's rotation params never follow the X/Y/Z suffix convention, so they
#    need their own exact-name match instead.
# Both paths converge on the same _collapse_vector/expand machinery below so
# there is only one way a vector socket ever gets built, sized, or expanded.

_NAMED_VECTOR_TRIPLES: Tuple[Tuple[str, ...], ...] = (
    ("yaw", "pitch", "roll"),
)


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


def _named_triple_run(params: list, start: int) -> Optional[list]:
    for triple in _NAMED_VECTOR_TRIPLES:
        run = []
        for offset, expected in enumerate(triple):
            position = start + offset
            if position >= len(params):
                break
            if param_spec_name(params[position]).lower() != expected:
                break
            run.append(params[position])
        if len(run) == len(triple):
            return run
    return None


def _mark_expanded(param, base: str, *, is_start: bool) -> dict:
    marked = {"name": param_spec_name(param)} if isinstance(param, str) else dict(param)
    marked["vector_base"] = base
    if is_start:
        marked["is_expanded_vector_start"] = True
    return marked


def _collapse_vector(axis_params: list, base: Optional[str]) -> dict:
    """Fold 2-3 params into one compact vector socket.

    ``base`` is the shared name prefix for a true axis-suffix run
    ('offsetX/Y/Z' → 'offset', bare 'x/y/z' → '') , or ``None`` for a named
    triple with no shared prefix at all ('yaw/pitch/roll') — its own names
    become both the axis labels and the collective identifier, kept distinct
    from '' so it can't collide with a bare x/y/z group in the same command
    (-renderMeshFromCustomPositionYPR has both).
    """
    is_triple = len(axis_params) == 3
    if base is not None:
        axes_label = "X,Y,Z" if is_triple else "X,Y"
        name = base or ("XYZ" if is_triple else "XY")
        # vector_base stays exactly `base` (not `name`) — group_xyz_params's
        # own expanded_bases lookup keys on `base` too, and the toggle button
        # reads this field back as the key it flips on click. They must agree.
        vector_base = base
    else:
        names = [param_spec_name(p) for p in axis_params]
        axes_label = ",".join(n.capitalize() for n in names)
        name = "_".join(n.lower() for n in names)
        vector_base = name
    return {
        "name": name,
        "label": f"{base} ({axes_label})" if base else axes_label,
        "type": "float3" if is_triple else "float2",
        "original": list(axis_params),
        "is_collapsed_vector": True,
        "vector_base": vector_base,
    }


def group_xyz_params(params: list, expanded_bases: set = None) -> list:
    expanded_bases = expanded_bases or set()
    grouped = []
    index = 0
    while index < len(params):
        head_name = param_spec_name(params[index])
        base = head_name[:-1] if head_name.lower().endswith("x") else None
        axis_run = _vector_axis_run(params, index, base) if base is not None else []

        if len(axis_run) < 2:
            named_run = _named_triple_run(params, index)
            if named_run:
                axis_run, base = named_run, None

        if len(axis_run) >= 2:
            group_key = base if base is not None else "_".join(
                param_spec_name(p).lower() for p in axis_run)
            if group_key in expanded_bases:
                grouped.append(_mark_expanded(axis_run[0], group_key, is_start=True))
                grouped.extend(_mark_expanded(p, group_key, is_start=False) for p in axis_run[1:])
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
        plain_title=label,
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
        # Just enough body height for the Launch button — Open/Save/Save As
        # (which used to take the rest) moved to the title bar's hamburger
        # menu (see TabStripWidget._show_project_menu).
        extra_rows=1.5,
        plain_title="> START",
    )


def dedupe_param_name(base_name: str, seen: Dict[str, int]) -> str:
    """Disambiguate a param name against ones already seen earlier in the
    same command's socket list.

    Why: RC's own docs sometimes give two same-typed params of one command no
    distinct name at all (-exportModel's "modelName fileName" both infer to
    the generic "filepath"; -setSelectedClassAsGroundForDTM's "true OR false"
    repeated is genuinely nameless). Without this, two sockets sharing one
    name collide in the name-keyed socket dict (ui/graph_items.py) and in
    connection-value resolution (core/graph_executor.py's connections_to) —
    a wire feeding either one can't be told apart from a wire feeding the
    other, so RC launches with whichever value happened to win the
    collision, silently dropping the other input. core/graph_executor.py
    calls this same helper, in the same param order, to keep its resolution
    keys in sync with these socket names.
    """
    occurrence = seen.get(base_name, 0) + 1
    seen[base_name] = occurrence
    return base_name if occurrence == 1 else f"{base_name}_{occurrence}"


def _append_param_sockets(sockets: List[SocketDef], param, row: int, optional: bool,
                          seen: Dict[str, int]):
    base_name = param_spec_name(param)
    ptype  = resolve_param_type(base_name, param)
    values = param.get("values", []) if isinstance(param, dict) else []
    label  = param.get("label", base_name) if isinstance(param, dict) else base_name
    socket_color = resolve_color_schema(ptype)["socket"]

    name = dedupe_param_name(base_name, seen)
    if name != base_name:
        label = f"{label} {name.rsplit('_', 1)[1]}"

    sockets.append(SocketDef(
        name, "input", row=row, label=f"{label}  (opt)" if optional else label,
        optional=optional, color=socket_color, param_type=ptype, values=values,
        is_collapsed_vector=param.get("is_collapsed_vector", False) if isinstance(param, dict) else False,
        is_expanded_vector_start=param.get("is_expanded_vector_start", False) if isinstance(param, dict) else False,
        vector_base=param.get("vector_base", "") if isinstance(param, dict) else "",
    ))
    if base_name.startswith("new"):
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
    seen: Dict[str, int] = {}
    for optional, key in ((False, "required"), (True, "optional")):
        for param in group_xyz_params(cmd_def.get(key, []), expanded_vectors):
            _append_param_sockets(sockets, param, row_idx, optional, seen)
            row_idx += 1
    return NodeDef(
        title=html_title(display, bold_first=True),
        header_color=exec_schema["hdr"],
        body_color=exec_schema["body"],
        sockets=sockets,
        width=235,
        plain_title=display,
    )
