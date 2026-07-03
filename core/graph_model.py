"""graph_model.py — Pure-Python Graph Data Model

Headless representation of a node graph: nodes, connections, and group frames
as plain dataclasses with stable UUIDs. Zero Qt or ui imports — this module is
the foundation that serialization and chain execution build on.

The dict format mirrors the on-disk JSON schema so round-tripping is trivial.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


def _new_uid() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class NodeModel:
    uid: str
    node_type: str
    x: float
    y: float
    color: Optional[str] = None
    color_only_header: bool = False
    selected: bool = False

    creation_data: Optional[dict] = None
    cmd_def: Optional[dict] = None
    current_value: Any = None
    expanded_vectors: Optional[Set[str]] = None

    # Socket name → live string value, populated from the scene when needed
    socket_values: Dict[str, str] = field(default_factory=dict)

    def to_dict(self, *, include_selection: bool = False) -> dict:
        d: dict = {"id": self.uid, "x": self.x, "y": self.y, "type": self.node_type}
        if self.node_type == "CommandNode" and self.cmd_def is not None:
            d["cmd_def"] = self.cmd_def
            if self.expanded_vectors:
                d["expanded_vectors"] = sorted(self.expanded_vectors)
        if self.node_type.endswith("ParamNode") or self.node_type == "ParamNode":
            if self.creation_data is not None:
                d["creation_data"] = self.creation_data
            if self.current_value is not None:
                d["current_value"] = self.current_value
        if self.color:
            d["color"] = self.color
            if self.color_only_header:
                d["color_only_header"] = True
        if include_selection:
            d["selected"] = self.selected
        return d

    @classmethod
    def from_dict(cls, record: dict) -> NodeModel:
        return cls(
            uid=record.get("id", _new_uid()),
            node_type=record.get("type", ""),
            x=record.get("x", 0.0),
            y=record.get("y", 0.0),
            color=record.get("color"),
            color_only_header=bool(record.get("color_only_header", False)),
            selected=record.get("selected", False),
            creation_data=record.get("creation_data"),
            cmd_def=record.get("cmd_def"),
            current_value=record.get("current_value"),
            expanded_vectors=set(record["expanded_vectors"]) if record.get("expanded_vectors") else None,
        )


@dataclass
class ConnectionModel:
    src_node_uid: Any
    src_socket: str
    dst_node_uid: Any
    dst_socket: str
    selected: bool = False

    def to_dict(self, *, include_selection: bool = False) -> dict:
        d = {
            "src_node": self.src_node_uid,
            "src_socket": self.src_socket,
            "dst_node": self.dst_node_uid,
            "dst_socket": self.dst_socket,
        }
        if include_selection:
            d["selected"] = self.selected
        return d

    @classmethod
    def from_dict(cls, record: dict) -> ConnectionModel:
        return cls(
            src_node_uid=record["src_node"],
            src_socket=record["src_socket"],
            dst_node_uid=record["dst_node"],
            dst_socket=record["dst_socket"],
            selected=record.get("selected", False),
        )


@dataclass
class GroupModel:
    title: str
    x: float
    y: float
    width: float
    height: float
    color: Optional[str] = None
    selected: bool = False

    def to_dict(self, *, include_selection: bool = False) -> dict:
        d: dict = {
            "title": self.title,
            "x": self.x, "y": self.y,
            "width": self.width, "height": self.height,
            "color": self.color,
        }
        if include_selection:
            d["selected"] = self.selected
        return d

    @classmethod
    def from_dict(cls, record: dict) -> GroupModel:
        return cls(
            title=record.get("title", ""),
            x=record.get("x", 0.0),
            y=record.get("y", 0.0),
            width=record.get("width", 200),
            height=record.get("height", 150),
            color=record.get("color"),
            selected=record.get("selected", False),
        )


@dataclass
class GraphModel:
    version: int = 1
    nodes: List[NodeModel] = field(default_factory=list)
    connections: List[ConnectionModel] = field(default_factory=list)
    groups: List[GroupModel] = field(default_factory=list)

    def to_dict(self, *, include_selection: bool = False) -> dict:
        return {
            "version": self.version,
            "nodes": [n.to_dict(include_selection=include_selection) for n in self.nodes],
            "connections": [c.to_dict(include_selection=include_selection) for c in self.connections],
            "groups": [g.to_dict(include_selection=include_selection) for g in self.groups],
        }

    @classmethod
    def from_dict(cls, payload: dict) -> GraphModel:
        return cls(
            version=payload.get("version", 1),
            nodes=[NodeModel.from_dict(r) for r in payload.get("nodes", [])],
            connections=[ConnectionModel.from_dict(r) for r in payload.get("connections", [])],
            groups=[GroupModel.from_dict(r) for r in payload.get("groups", [])],
        )

    def node_by_uid(self, uid) -> Optional[NodeModel]:
        for n in self.nodes:
            if n.uid == uid:
                return n
        return None

    def connections_to(self, node_uid, socket_name: str) -> List[ConnectionModel]:
        return [c for c in self.connections
                if c.dst_node_uid == node_uid and c.dst_socket == socket_name]

    def connections_from(self, node_uid, socket_name: str) -> List[ConnectionModel]:
        return [c for c in self.connections
                if c.src_node_uid == node_uid and c.src_socket == socket_name]
