"""chain_execution.py — From Node Graph to RealityCapture CLI Invocation

Walks the exec wires from the StartNode, resolves every connected parameter to
its live value, and assembles the token list RealityCapture is launched with.

Operates entirely on GraphModel — no Qt or ui imports.
"""
from __future__ import annotations

import subprocess
from typing import List, Optional

from configuration import RC_EXECUTABLE, VECTOR_PARAM_TYPES
from core.graph_model import GraphModel, NodeModel
from core.node_blueprint import group_xyz_params


def build_exec_chain(graph: GraphModel) -> Optional[List[NodeModel]]:
    """The linear node sequence reachable from the StartNode over exec wires.

    A visited-set guards against cycles: a looped chain terminates at the first
    revisited node instead of hanging the editor.
    """
    start_nodes = [n for n in graph.nodes if n.node_type == "StartNode"]
    if not start_nodes:
        return None

    next_node = {}
    for conn in graph.connections:
        if conn.src_socket in ("exec_out", "__exec_out__"):
            src = graph.node_by_uid(conn.src_node_uid)
            dst = graph.node_by_uid(conn.dst_node_uid)
            if src and dst:
                next_node[src.uid] = dst

    chain: List[NodeModel] = []
    current: Optional[NodeModel] = start_nodes[0]
    visited: set = set()
    while current and current.uid not in visited:
        chain.append(current)
        visited.add(current.uid)
        current = next_node.get(current.uid)
    return chain


def _resolve_param_value(graph: GraphModel, node: NodeModel,
                         param_name: str) -> str:
    """The live value feeding a command input — following pass-through outputs
    on upstream command nodes (their ``new*_out`` sockets mirror the input)."""
    for conn in graph.connections_to(node.uid, param_name):
        src = graph.node_by_uid(conn.src_node_uid)
        if not src:
            continue
        if src.node_type.endswith("ParamNode"):
            return src.socket_values.get(conn.src_socket, "")
        if src.node_type == "CommandNode":
            out_name = conn.src_socket
            in_name = (out_name[:-len("_out")]
                       if out_name.endswith("_out") else out_name)
            return _resolve_param_value(graph, src, in_name)
    return ""


def build_launch_tokens(chain: List[NodeModel],
                        graph: GraphModel) -> List[str]:
    """CLI tokens for the chain: executable, then per command its flag and every
    non-empty resolved parameter (vector values split into components)."""
    tokens = [RC_EXECUTABLE]
    for node in chain[1:]:
        if node.node_type != "CommandNode" or not node.cmd_def:
            continue
        tokens.append(node.cmd_def["command"])
        expanded = node.expanded_vectors or set()
        for key in ("required", "optional"):
            for p in group_xyz_params(node.cmd_def.get(key, []), expanded):
                name  = p if isinstance(p, str) else p["name"]
                ptype = "string" if isinstance(p, str) else p.get("type", "string")
                value = _resolve_param_value(graph, node, name)
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
