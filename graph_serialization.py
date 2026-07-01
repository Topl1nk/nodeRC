"""graph_serialization.py — One Graph Snapshot Format for Everything

Project save/load, the undo history and the clipboard all speak this single
payload schema: nodes, connections and group frames with absolute scene
coordinates. Paste and duplicate are the same materialization with an offset
applied — there is no second serializer to keep in sync.

Payload schema:
  nodes:       [{id, x, y, type, …type-specific payload, [selected]}]
  connections: [{src_node, src_socket, dst_node, dst_socket, [selected]}]
  groups:      [{title, x, y, width, height, color, [selected]}]
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore import QPointF, QRectF

from localization import get_all_translations, t
from configuration import GROUP_FRAME_DEFAULT_WIDTH, GROUP_FRAME_DEFAULT_HEIGHT
from diagnostics import log_and_explain
from graph_items import Connection, GroupFrameItem, MetaNode
from param_nodes import EnumParamNode, PARAM_NODE_TYPES, ParamNode, StringParamNode
from command_nodes import CommandNode, StartNode


def build_param_node(creation_data: dict) -> ParamNode:
    ptype = creation_data.get("param_type", "string")
    node_class = PARAM_NODE_TYPES.get(ptype, StringParamNode)
    name = creation_data.get("display") or creation_data.get("name")

    # Default titles are language-dependent: when the stored name is a known
    # default in ANY catalog, re-resolve it so the node follows the active UI
    # language instead of freezing in the language it was created under.
    if name:
        title_key = ("param_path_title" if ptype in ("filepath", "dirpath", "path")
                     else f"param_{ptype}_title")
        if name in get_all_translations(title_key):
            name = t(title_key)
            creation_data["display"] = name
            if "name" in creation_data:
                creation_data["name"] = name

    values = creation_data.get("values", [])
    if node_class is EnumParamNode and values:
        node = node_class(name, values) if name else node_class(values=values)
    else:
        node = node_class(name) if name else node_class()
    node.creation_data = creation_data
    return node


def serialize_node(node: MetaNode) -> dict:
    record = {"type": type(node).__name__, **node.serialize_payload()}
    if node.color_override():
        record["color"] = node.color_override()
        if node.color_only_header():
            record["color_only_header"] = True
    return record


def _deserialize_node(scene, record: dict, pos: QPointF) -> Optional[MetaNode]:
    node_type = record["type"]
    if node_type == "StartNode":
        node = StartNode()
    elif node_type == "CommandNode":
        node = CommandNode(record["cmd_def"])
    elif node_type.endswith("ParamNode"):
        node = build_param_node(
            record.get("creation_data", {"param_type": "string", "display": "value"}))
    else:
        return None
    node.setPos(pos)
    scene.addItem(node)
    if record.get("color"):
        node.set_color(record["color"],
                       only_header=bool(record.get("color_only_header")),
                       record_undo=False)
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

    for idx, item in enumerate(scene.items()):
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
    for item in [i for i in scene.items()
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
    """
    shift = offset or QPointF(0, 0)

    id_to_node: Dict[int, MetaNode] = {}
    for record in payload.get("nodes", []):
        try:
            node = _deserialize_node(scene, record, QPointF(
                record["x"] + shift.x(), record["y"] + shift.y()))
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
    for frame in frames:
        frame.commit_members(force_all=True)
    return id_to_node, frames
