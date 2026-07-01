"""chain_execution.py — From Node Graph to RealityCapture CLI Invocation

Walks the exec wires from the StartNode, resolves every connected parameter to
its live value, and assembles the token list RealityCapture is launched with.
No scene or window knowledge — callers hand in nodes and connections.
"""
from __future__ import annotations

import subprocess
from typing import Dict, Iterable, List, Optional

from configuration import RC_EXECUTABLE, VECTOR_PARAM_TYPES
from graph_items import Connection, MetaNode
from node_blueprint import group_xyz_params
from param_nodes import ParamNode
from command_nodes import CommandNode, StartNode


def build_exec_chain(nodes: Iterable[MetaNode],
                     connections: List[Connection]) -> Optional[List[MetaNode]]:
    """The linear node sequence reachable from the StartNode over exec wires.

    A visited-set guards against cycles: a looped chain terminates at the first
    revisited node instead of hanging the editor.
    """
    all_nodes = set(nodes)
    start_nodes = [n for n in all_nodes if isinstance(n, StartNode)]
    if not start_nodes:
        return None

    next_node: Dict[MetaNode, Optional[MetaNode]] = {n: None for n in all_nodes}
    for conn in connections:
        if not conn.is_exec:
            continue
        if conn.source.sock_def.name in ("exec_out", "__exec_out__"):
            next_node[conn.source.meta_node] = conn.dest.meta_node

    chain: List[MetaNode] = []
    current: Optional[MetaNode] = start_nodes[0]
    visited: set = set()
    while current and current not in visited:
        chain.append(current)
        visited.add(current)
        current = next_node.get(current)
    return chain


def resolve_connected_param_value(node: MetaNode, param_name: str,
                                  connections: List[Connection]) -> str:
    """The live value feeding a command input — following pass-through outputs
    on upstream command nodes (their ``new*_out`` sockets mirror the input)."""
    socket = node.get_socket(param_name)
    if not socket:
        return ""
    for conn in connections:
        if conn.dest is socket:
            source_node = conn.source.meta_node
            if isinstance(source_node, ParamNode):
                return source_node.get_value(conn.source.sock_def.name)
            if isinstance(source_node, CommandNode):
                out_sock_name = conn.source.sock_def.name
                in_sock_name = (out_sock_name[:-len("_out")]
                                if out_sock_name.endswith("_out") else out_sock_name)
                return resolve_connected_param_value(source_node, in_sock_name, connections)
    return ""


def build_launch_tokens(chain: List[MetaNode],
                        connections: List[Connection]) -> List[str]:
    """CLI tokens for the chain: executable, then per command its flag and every
    non-empty resolved parameter (vector values split into components)."""
    tokens = [RC_EXECUTABLE]
    for node in chain[1:]:
        if not isinstance(node, CommandNode):
            continue
        tokens.append(node.cmd_def["command"])
        expanded = getattr(node, "expanded_vectors", set())
        for key in ("required", "optional"):
            for p in group_xyz_params(node.cmd_def.get(key, []), expanded):
                name  = p if isinstance(p, str) else p["name"]
                ptype = "string" if isinstance(p, str) else p.get("type", "string")
                value = resolve_connected_param_value(node, name, connections)
                if not value:
                    continue
                if ptype in VECTOR_PARAM_TYPES:
                    tokens.extend(value.split())
                else:
                    tokens.append(value)
    return tokens


def launch(tokens: List[str]) -> None:
    """Fire-and-forget: RealityCapture runs detached from the editor process."""
    subprocess.Popen(tokens)
