"""graph_serialization.py — One Graph Snapshot Format for Everything

Project save/load, the undo history and the clipboard all speak this single
payload schema: nodes, connections and group frames with absolute scene
coordinates. Paste and duplicate are the same materialization with an offset
applied — there is no second serializer to keep in sync.

Payload schema:
  nodes:       [{id, x, y, type, …type-specific payload, [selected]}]
  connections: [{src_node, src_socket, dst_node, dst_socket, [selected]}]
  groups:      [{title, x, y, width, height, color, [selected]}]

Lives in ui/, not core/: every function here reads/writes a live
QGraphicsScene and concrete Qt graphics items (MetaNode, Connection,
GroupFrameItem) — it's the scene<->payload bridge, not headless business
logic. scene_to_graph_model() is the one function that actually produces a
pure core.graph_model.GraphModel for chain_execution; everything else here
needs Qt by nature and has no reason to pretend otherwise (see CODEX.md Ст.7).
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore import QPointF, QRectF, Qt

# Qt.SortOrder(-1) tells QGraphicsScene.items() to skip its Z-order sort and
# return items in whatever arbitrary internal order it already has them —
# every use of scene.items() below only builds a dict/list keyed by uid or
# an ephemeral per-call index, so the order was never meaningful, but the
# sort itself is real, avoidable O(n log n) work on every call, several of
# which run on every single edit (push_undo_state -> serialize_graph).
_UNORDERED = Qt.SortOrder(-1)

from localization import resolve_default_title, t
from configuration import GROUP_FRAME_DEFAULT_WIDTH, GROUP_FRAME_DEFAULT_HEIGHT
from diagnostics import log_and_explain
from core.graph_model import GraphModel, NodeModel, ConnectionModel, GroupModel
from core.node_blueprint import PARAM_TITLE_KEY
from ui.graph_items import Connection, GroupFrameItem, MetaNode
from ui.param_nodes import (
    EnumParamNode, Float2ParamNode, Float3ParamNode, PARAM_NODE_TYPES, ParamNode,
    PathParamNode, StringParamNode,
)
from ui.command_nodes import CommandNode, StartNode


def build_param_node(creation_data: dict) -> ParamNode:
    ptype = creation_data.get("param_type", "string")
    node_class = PARAM_NODE_TYPES.get(ptype, StringParamNode)
    name = creation_data.get("display") or creation_data.get("name")

    # Default titles are language-dependent: when the stored name is a known
    # default in ANY catalog, re-resolve it so the node follows the active UI
    # language instead of freezing in the language it was created under.
    if name:
        resolved = resolve_default_title(name, PARAM_TITLE_KEY.get(ptype))
        if resolved != name:
            name = resolved
            creation_data["display"] = name
            if "name" in creation_data:
                creation_data["name"] = name

    values = creation_data.get("values", [])
    if node_class is EnumParamNode and values:
        node = node_class(name, values) if name else node_class(values=values)
    elif node_class is PathParamNode:
        # PathParamNode always exposes both a dirpath and a filepath output —
        # ptype tells it which one to lead with for its header/socket color.
        node = node_class(name, param_type=ptype) if name else node_class(param_type=ptype)
    elif node_class in (Float2ParamNode, Float3ParamNode):
        # Restores whichever split/merged shape the node was last toggled to.
        split = bool(creation_data.get("split", False))
        node = node_class(name, split=split) if name else node_class(split=split)
    else:
        node = node_class(name) if name else node_class()
    node.creation_data = creation_data
    return node


def serialize_node(node: MetaNode) -> dict:
    record = {"type": type(node).__name__, "uid": node.uid, **node.serialize_payload()}
    if node.color_override():
        record["color"] = node.color_override()
        if node.color_only_header():
            record["color_only_header"] = True
    return record


def _deserialize_node(scene, record: dict, pos: QPointF, *, preserve_uid: bool = True) -> Optional[MetaNode]:
    node_type = record["type"]
    if node_type == "StartNode":
        node = StartNode()
    elif node_type == "CommandNode":
        node = CommandNode(record["cmd_def"], set(record.get("expanded_vectors", [])))
    elif node_type.endswith("ParamNode"):
        node = build_param_node(
            record.get("creation_data", {"param_type": "string", "display": "value"}))
    else:
        return None
    if preserve_uid and "uid" in record:
        node.uid = record["uid"]
        MetaNode._observe_uid(record["uid"])
    # else: keep the fresh uid MetaNode.__init__ already handed out — this
    # is a copy living alongside the original (paste/duplicate), not a
    # restore of it, and undo/redo's try_apply_state_diff indexes nodes by
    # uid, so two live nodes sharing one would silently collapse to a
    # single entry in its live_by_uid map, corrupting the fast path for
    # either node the next time undo/redo runs.
    node.setPos(pos)
    scene.addItem(node)
    # Unconditionally re-pin every embedded widget's QSS/palette through
    # _update_children_colors(), not just nodes with a saved override:
    # editable comboboxes (PathParamNode's file field) rely entirely on a
    # QPalette pinned at construction time for their non-connected text
    # colour, and a node built on a background tab (restored session)
    # never gets a real on-screen paint until the user switches to it —
    # Qt's first real style polish then silently drops that palette back
    # to black. reset_color() re-derives the node's correct default (or
    # per-socket-type) colour AND re-pins every widget the same way a
    # saved override already does, closing the gap for the common case.
    if record.get("color"):
        node.set_color(record["color"],
                       only_header=bool(record.get("color_only_header")),
                       record_undo=False)
    else:
        node.reset_color(record_undo=False)
    if isinstance(node, ParamNode) and record.get("current_value") is not None:
        node.set_value_state(record["current_value"])
    return node


def serialize_graph(scene, connections: List[Connection], *,
                    only_selected: bool = False,
                    include_selection: bool = False) -> dict:
    """Snapshot the scene. ``only_selected`` drops unselected items and the
    protected StartNode — the clipboard shape of the same schema."""
    node_id_map: Dict[MetaNode, int] = {}
    node_records: List[dict] = []
    group_records: List[dict] = []

    for idx, item in enumerate(scene.items(_UNORDERED)):
        if isinstance(item, MetaNode):
            if only_selected and (not item.isSelected() or isinstance(item, StartNode)):
                continue
            node_id_map[item] = idx
            pos = item.scenePos()
            record = {"id": idx, "x": pos.x(), "y": pos.y(), **serialize_node(item)}
            if include_selection:
                record["selected"] = item.isSelected()
            node_records.append(record)
        elif isinstance(item, GroupFrameItem):
            if only_selected and not item.isSelected():
                continue
            pos = item.pos()
            rect = item.rect()
            record = {
                "title": item.title,
                "x": pos.x(),
                "y": pos.y(),
                "width": rect.width(),
                "height": rect.height(),
                "color": item.color(),
            }
            if include_selection:
                record["selected"] = item.isSelected()
            group_records.append(record)

    connection_records = []
    for conn in connections:
        src_id = node_id_map.get(conn.source.meta_node)
        dst_id = node_id_map.get(conn.dest.meta_node)
        if src_id is None or dst_id is None:
            continue
        record = {
            "src_node": src_id, "src_socket": conn.source.sock_def.name,
            "dst_node": dst_id, "dst_socket": conn.dest.sock_def.name,
        }
        if include_selection:
            record["selected"] = conn.isSelected()
        connection_records.append(record)

    return {
        "version": 1,
        "nodes": node_records,
        "connections": connection_records,
        "groups": group_records,
    }


def payload_center(payload: dict) -> Optional[QPointF]:
    """Mean position of the payload's nodes and frames — the paste anchor."""
    positions = [(r["x"], r["y"])
                 for r in payload.get("nodes", []) + payload.get("groups", [])]
    if not positions:
        return None
    return QPointF(sum(x for x, _ in positions) / len(positions),
                   sum(y for _, y in positions) / len(positions))


def clear_graph(scene, connections: List[Connection]):
    for item in [i for i in scene.items(_UNORDERED)
                 if isinstance(i, (MetaNode, Connection, GroupFrameItem))]:
        scene.removeItem(item)
    connections.clear()


def materialize_graph(scene, connections: List[Connection], payload: dict, *,
                      offset: Optional[QPointF] = None,
                      select_created: bool = False,
                      restore_selection: bool = False,
                      ) -> Tuple[Dict[int, MetaNode], List[GroupFrameItem]]:
    """Instantiate a payload into the scene, shifted by ``offset``.

    Every record is isolated: one corrupt node/wire/frame must not discard the
    rest of the payload.

    ``select_created`` doubles as "this is an additive copy, not a restore":
    every caller that passes it is paste/duplicate inserting alongside
    whatever is already in the scene (see ui/editor_window.py's
    _insert_payload, its only user), while every restore-shaped caller
    (undo/redo, load, session restore) clears the scene first and never
    sets it. That's exactly when the incoming nodes' saved uids must NOT be
    reused — they'd collide with the still-live originals — so it doubles
    as the fresh-uid signal for _deserialize_node below.
    """
    shift = offset or QPointF(0, 0)
    preserve_uid = not select_created

    id_to_node: Dict[int, MetaNode] = {}
    for record in payload.get("nodes", []):
        try:
            node = _deserialize_node(scene, record, QPointF(
                record["x"] + shift.x(), record["y"] + shift.y()), preserve_uid=preserve_uid)
        except Exception as exc:
            log_and_explain(f"Skipped unreadable node ({record.get('type', 'unknown')})", exc)
            continue
        if node is None:
            continue
        id_to_node[record["id"]] = node
        if select_created or (restore_selection and record.get("selected", False)):
            node.setSelected(True)

    frames: List[GroupFrameItem] = []
    for record in payload.get("groups", []):
        try:
            rect = QRectF(0, 0,
                          record.get("width", GROUP_FRAME_DEFAULT_WIDTH),
                          record.get("height", GROUP_FRAME_DEFAULT_HEIGHT))
            frame = GroupFrameItem(rect, title=record.get("title", t("default_group_title")))
            frame.setPos(record["x"] + shift.x(), record["y"] + shift.y())
            if record.get("color"):
                frame.set_color(record["color"], record_undo=False)
            scene.addItem(frame)
            if select_created or (restore_selection and record.get("selected", False)):
                frame.setSelected(True)
            frames.append(frame)
        except Exception as exc:
            log_and_explain("Skipped unreadable group frame", exc)

    for record in payload.get("connections", []):
        try:
            src_node = id_to_node.get(record["src_node"])
            dst_node = id_to_node.get(record["dst_node"])
            if not (src_node and dst_node):
                continue
            src_sock = src_node.get_socket(record["src_socket"])
            dst_sock = dst_node.get_socket(record["dst_socket"])
            if not (src_sock and dst_sock):
                continue
            scene.enforce_connection_rules(src_sock, dst_sock)
            conn = Connection(src_sock, dst_sock)
            scene.addItem(conn)
            connections.append(conn)
            if restore_selection and record.get("selected", False):
                conn.setSelected(True)
        except Exception as exc:
            log_and_explain("Skipped unreadable connection", exc)

    for node in id_to_node.values():
        node._refresh_connections()
    scene.recalculate_scene_rect()
    # Collect the freshly materialized nodes once and hand the same list to
    # every frame's commit_members — otherwise each frame re-scans and
    # re-sorts the whole scene by Z-order for itself (O(frames x node count)
    # on a graph with many group frames).
    all_nodes = list(id_to_node.values())
    for frame in frames:
        frame.commit_members(force_all=True, candidates=all_nodes)
    return id_to_node, frames


def scene_to_graph_model(scene, connections: List[Connection]) -> GraphModel:
    """Build a GraphModel from the live scene for chain execution."""
    node_id_map: Dict[MetaNode, int] = {}
    nodes = []
    groups = []

    for idx, item in enumerate(scene.items(_UNORDERED)):
        if isinstance(item, MetaNode):
            node_id_map[item] = idx
            pos = item.scenePos()
            nm = NodeModel(
                uid=idx,
                node_type=type(item).__name__,
                x=pos.x(), y=pos.y(),
                color=item.color_override(),
                color_only_header=item.color_only_header(),
            )
            if isinstance(item, CommandNode):
                nm.cmd_def = item.cmd_def
                nm.expanded_vectors = getattr(item, "expanded_vectors", None)
            if isinstance(item, ParamNode):
                nm.creation_data = getattr(item, "creation_data", None)
                nm.current_value = item.get_value_state()
                for name, sock in item.sockets.items():
                    nm.socket_values[name] = item.get_value(name)
            nodes.append(nm)
        elif isinstance(item, GroupFrameItem):
            pos = item.pos()
            rect = item.rect()
            groups.append(GroupModel(
                title=item.title,
                x=pos.x(), y=pos.y(),
                width=rect.width(), height=rect.height(),
                color=item.color(),
            ))

    conns = []
    for conn in connections:
        src_id = node_id_map.get(conn.source.meta_node)
        dst_id = node_id_map.get(conn.dest.meta_node)
        if src_id is not None and dst_id is not None:
            conns.append(ConnectionModel(
                src_node_uid=src_id,
                src_socket=conn.source.sock_def.name,
                dst_node_uid=dst_id,
                dst_socket=conn.dest.sock_def.name,
            ))

    return GraphModel(nodes=nodes, connections=conns, groups=groups)


# ── Fast in-place undo/redo ──────────────────────────────────────────────────
#
# undo()/redo() used to always clear_graph()+materialize_graph() the whole
# scene from the target history snapshot — correct, but on a many-thousand-
# node scene that turns "move one node back" into "rebuild every node's
# widgets from scratch". try_apply_state_diff() instead matches nodes between
# the current live state and the target snapshot by MetaNode.uid (stable
# across snapshots, unlike serialize_graph's positional "id") and, whenever
# the two states have exactly the same nodes/connections/groups and only
# differ in position/value/color/selection, patches the existing live
# objects in place. Any structural difference (a node or wire added/removed,
# a vector split/merge, an expanded X/Y/Z command) makes it bail out and
# report failure — the caller then falls back to the always-correct full
# rebuild, so a gap in this fast path only costs speed, never correctness.

def _same_shape(cur_rec: dict, tgt_rec: dict) -> bool:
    """Whether two same-uid, same-type node records describe the same socket
    layout — i.e. every difference between them is a patchable property
    (position/value/color/title), not a structural rebuild (vector
    split/merge, X/Y/Z expand/collapse) that changes the node's sockets."""
    if cur_rec["type"] == "CommandNode":
        return (sorted(cur_rec.get("expanded_vectors", []))
                == sorted(tgt_rec.get("expanded_vectors", [])))
    cur_split = (cur_rec.get("creation_data") or {}).get("split")
    tgt_split = (tgt_rec.get("creation_data") or {}).get("split")
    return cur_split == tgt_split


def _connections_by_uid(state: dict, id_to_uid: Dict[int, int]) -> Optional[set]:
    """Connection endpoints as (src_uid, src_socket, dst_uid, dst_socket)
    tuples instead of serialize_graph's positional node ids — those ids are
    scene.items() enumeration indices, which shift under Z-order changes
    even when the topology hasn't, so comparing them directly across two
    snapshots would misreport an unchanged graph as different."""
    result = set()
    for c in state.get("connections", []):
        src_uid = id_to_uid.get(c["src_node"])
        dst_uid = id_to_uid.get(c["dst_node"])
        if src_uid is None or dst_uid is None:
            return None
        result.add((src_uid, c["src_socket"], dst_uid, c["dst_socket"]))
    return result


def _group_record_key(record: dict) -> str:
    """A group record's identity for matching purposes — everything except
    selection, canonicalized to a string. Group frames have no uid the way
    nodes do, so this (title, position, size, color) tuple is the closest
    thing to a stable key available; shared by _canon_groups (which only
    needs the key) and try_apply_state_diff's group-selection restore
    (which also needs to look a record back up by it)."""
    return json.dumps({k: v for k, v in record.items() if k != "selected"}, sort_keys=True)


def _canon_groups(state: dict) -> List[str]:
    """Group records as an order-independent fingerprint (selection excluded)
    — scene.items() order for group frames can shift the same way node ids
    do, so a plain list == list check would spuriously treat an unchanged
    set of frames as different."""
    return sorted(_group_record_key(g) for g in state.get("groups", []))


def _live_group_key(item: GroupFrameItem) -> str:
    """A live GroupFrameItem's own current key, in the exact shape
    serialize_graph would record it in — so it can be looked up against
    _group_record_key(target_record) directly."""
    pos = item.pos()
    rect = item.rect()
    return _group_record_key({
        "title": item.title, "x": pos.x(), "y": pos.y(),
        "width": rect.width(), "height": rect.height(), "color": item.color(),
    })


def _patch_node(node: MetaNode, tgt_rec: dict) -> Tuple[bool, bool]:
    """Apply tgt_rec's position/color/value/title onto an existing live
    node. Returns (changed, moved): ``changed`` is True if anything at all
    changed (so the caller knows whether a connection refresh / scene-rect
    recalc is needed); ``moved`` is True specifically when position changed
    (so the caller knows whether this node's group-frame membership needs
    re-checking — see try_apply_state_diff)."""
    changed = False
    moved = False
    pos = node.scenePos()
    tgt_x, tgt_y = tgt_rec.get("x"), tgt_rec.get("y")
    if (pos.x(), pos.y()) != (tgt_x, tgt_y):
        node.setPos(tgt_x, tgt_y)
        changed = True
        moved = True

    tgt_color = tgt_rec.get("color")
    tgt_only_header = bool(tgt_rec.get("color_only_header"))
    if tgt_color != node.color_override() or (tgt_color and tgt_only_header != node.color_only_header()):
        if tgt_color:
            node.set_color(tgt_color, only_header=tgt_only_header, record_undo=False)
        else:
            node.reset_color(record_undo=False)
        changed = True

    if isinstance(node, ParamNode):
        tgt_creation = tgt_rec.get("creation_data") or {}
        cur_creation = getattr(node, "creation_data", None) or {}
        tgt_display = tgt_creation.get("display")
        cur_display = cur_creation.get("display") or node.node_def.plain_title
        if tgt_display and tgt_display != cur_display:
            node._set_title_text(tgt_display)
            merged = dict(cur_creation)
            merged["display"] = tgt_display
            node.creation_data = merged
            changed = True
        tgt_value = tgt_rec.get("current_value")
        if tgt_value != node.get_value_state():
            node.set_value_state(tgt_value)
            changed = True

    if changed:
        node._refresh_connections()
    return changed, moved


def try_apply_state_diff(scene, connections: List[Connection],
                         current_state: dict, target_state: dict) -> bool:
    """Patch the live scene from ``current_state`` to ``target_state`` in
    place if they describe the same graph shape; return False (touching
    nothing) if the caller must fall back to a full clear_graph +
    materialize_graph instead.
    """
    cur_nodes = current_state.get("nodes", [])
    tgt_nodes = target_state.get("nodes", [])
    if len(cur_nodes) != len(tgt_nodes):
        return False

    cur_by_uid: Dict[int, dict] = {}
    for r in cur_nodes:
        uid = r.get("uid")
        if uid is None:
            return False  # predates the uid field — can't match safely
        cur_by_uid[uid] = r
    tgt_by_uid: Dict[int, dict] = {}
    for r in tgt_nodes:
        uid = r.get("uid")
        if uid is None:
            return False
        tgt_by_uid[uid] = r
    if set(cur_by_uid) != set(tgt_by_uid):
        return False  # a node was added or removed

    for uid, cur_rec in cur_by_uid.items():
        tgt_rec = tgt_by_uid[uid]
        if cur_rec["type"] != tgt_rec["type"] or not _same_shape(cur_rec, tgt_rec):
            return False

    cur_id_to_uid = {r["id"]: r["uid"] for r in cur_nodes}
    tgt_id_to_uid = {r["id"]: r["uid"] for r in tgt_nodes}
    cur_conns = _connections_by_uid(current_state, cur_id_to_uid)
    tgt_conns = _connections_by_uid(target_state, tgt_id_to_uid)
    if cur_conns is None or tgt_conns is None or cur_conns != tgt_conns:
        return False

    if _canon_groups(current_state) != _canon_groups(target_state):
        return False

    # Every check passed — the two states have identical shape, so it's safe
    # to patch properties on the existing live objects instead of rebuilding.
    live_by_uid: Dict[int, MetaNode] = {
        item.uid: item for item in scene.items(_UNORDERED) if isinstance(item, MetaNode)
    }
    if set(live_by_uid) != set(tgt_by_uid):
        return False  # scene drifted from current_state somehow — bail out safely

    any_changed = False
    moved_nodes: List[MetaNode] = []
    for uid, tgt_rec in tgt_by_uid.items():
        node = live_by_uid[uid]
        changed, moved = _patch_node(node, tgt_rec)
        if changed:
            any_changed = True
        if moved:
            moved_nodes.append(node)
    if any_changed:
        scene.recalculate_scene_rect()
    for node in moved_nodes:
        # A moved node's group-frame membership (which frame drags it along,
        # see NodeScene.mousePressEvent seeding _dragged_inner_nodes from
        # _group_members) isn't part of what _same_shape/_canon_groups
        # compares — reusing the same "which frame is under my center now"
        # logic a real drag-release runs (MetaNode._adopt_containing_frame)
        # keeps it correct here too, instead of leaving it stale until some
        # unrelated structural edit forces a full rebuild.
        node._adopt_containing_frame(scene)

    for uid, tgt_rec in tgt_by_uid.items():
        node = live_by_uid[uid]
        want_selected = bool(tgt_rec.get("selected", False))
        if node.isSelected() != want_selected:
            node.setSelected(want_selected)

    tgt_conn_selected = {}
    for c in target_state.get("connections", []):
        key = (tgt_id_to_uid[c["src_node"]], c["src_socket"],
               tgt_id_to_uid[c["dst_node"]], c["dst_socket"])
        tgt_conn_selected[key] = bool(c.get("selected", False))
    for conn in connections:
        key = (conn.source.meta_node.uid, conn.source.sock_def.name,
               conn.dest.meta_node.uid, conn.dest.sock_def.name)
        want_selected = tgt_conn_selected.get(key, False)
        if conn.isSelected() != want_selected:
            conn.setSelected(want_selected)

    # Group frames have no uid to match by, but _canon_groups already
    # guaranteed every frame's (title/position/size/color) key is identical
    # between current_state and target_state — matching live frames to
    # target records by that same key is exact here, not an approximation.
    tgt_group_selected = {
        _group_record_key(g): bool(g.get("selected", False))
        for g in target_state.get("groups", [])
    }
    for item in scene.items(_UNORDERED):
        if isinstance(item, GroupFrameItem):
            want_selected = tgt_group_selected.get(_live_group_key(item), False)
            if item.isSelected() != want_selected:
                item.setSelected(want_selected)

    return True
