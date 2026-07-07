"""graph_executor.py — Incremental, Segmented Graph Execution (Доктрина V)

Walks the exec chain from StartNode, groups consecutive CommandNodes into
segments by the pack they belong to, resolves each segment's live parameter
values, and hands the whole segment to that pack's executor as one atomic
call. A pack with cross-command state (RC keeps a project loaded in memory
across -load/-align/-export) needs its whole segment in one process — see
core/pack_protocol.py's PackExecutor.run_commands — so segmentation, not
single-node calls, is the unit of both execution and caching here.

Segments whose resolved inputs are unchanged since the last run are served
from an in-memory cache instead of re-invoked (V.1). A cancel_check polled
between segments lets a run stop cleanly without leaving a segment
half-done (V.2): a segment's own process either completes or fails as a
whole, so there is no partial-segment state to leave inconsistent.

Replaces core/chain_execution.py entirely. Zero Qt or ui imports.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from core.graph_model import GraphModel, NodeModel
from core.node_blueprint import dedupe_param_name, group_xyz_params
from core.pack_protocol import CommandDef, ExecutionResult, PackExecutor
from diagnostics import log_and_explain

# Every CommandNode is assumed to belong to this pack until node_blueprint
# carries a real pack_id per node — today exactly one pack (RealityCapture)
# exists and nothing in the UI's node-creation path (Phase 6 scope) tags a
# node with anything else. Ст.12: explicit, reasoned placeholder, not a
# silent assumption.
_DEFAULT_PACK_ID = "realitycapture"


def _pack_id_for_node(node: NodeModel) -> str:
    return _DEFAULT_PACK_ID


def build_exec_chain(graph: GraphModel) -> Optional[List[NodeModel]]:
    """The linear node sequence reachable from the StartNode over exec wires.

    A visited-set guards against cycles: a looped chain terminates at the
    first revisited node instead of hanging the editor."""
    start_nodes = [n for n in graph.nodes if n.node_type == "StartNode"]
    if not start_nodes:
        return None

    next_node: Dict[str, NodeModel] = {}
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


def _resolve_param_value(graph: GraphModel, node: NodeModel, param_name: str) -> str:
    """The live value feeding a command input — following pass-through
    outputs on upstream command nodes (their ``new*_out`` sockets mirror the
    input)."""
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


def _resolved_params_for_node(graph: GraphModel, node: NodeModel, command: CommandDef) -> Dict[str, str]:
    """name -> live value for every non-empty resolved parameter of one
    command node, in required-then-optional order — mirrors the param
    resolution core/chain_execution.py used to run per node inside its
    whole-chain token loop."""
    expanded = node.expanded_vectors or set()
    params: Dict[str, str] = {}
    seen: Dict[str, int] = {}
    for param_list in (command.required, command.optional):
        raw_params = [p.to_dict() for p in param_list]
        for p in group_xyz_params(raw_params, expanded):
            base_name = p if isinstance(p, str) else p["name"]
            name = dedupe_param_name(base_name, seen)
            value = _resolve_param_value(graph, node, name)
            if value:
                params[name] = value
    return params


@dataclass
class Segment:
    """A maximal run of consecutive CommandNodes sharing one pack_id — the
    unit of execution, caching and cancellation."""
    pack_id: str
    nodes: List[NodeModel] = field(default_factory=list)


def segment_chain_by_pack(chain: List[NodeModel]) -> List[Segment]:
    segments: List[Segment] = []
    for node in chain:
        if node.node_type != "CommandNode" or not node.cmd_def:
            continue
        pack_id = _pack_id_for_node(node)
        if segments and segments[-1].pack_id == pack_id:
            segments[-1].nodes.append(node)
        else:
            segments.append(Segment(pack_id=pack_id, nodes=[node]))
    return segments


def _segment_commands(graph: GraphModel, segment: Segment):
    """[(CommandDef, resolved params), ...] for every node in the segment,
    in order — the exact payload run_commands() needs."""
    commands = []
    for node in segment.nodes:
        command = CommandDef.from_dict(node.cmd_def)
        params = _resolved_params_for_node(graph, node, command)
        commands.append((command, params))
    return commands


def _segment_cache_key(commands, pack_version: str) -> str:
    payload = {
        "pack_version": pack_version,
        "commands": [{"command": c.to_dict(), "params": p} for c, p in commands],
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass
class SegmentRun:
    pack_id: str
    node_uids: List[str]
    result: ExecutionResult
    cache_hit: bool


class GraphExecutor:
    """Drives one graph's exec chain segment by segment.

    executor_factory resolves a pack_id to the PackExecutor that runs it —
    injected explicitly (Ст.2.1) rather than reached into globally, so tests
    can supply a fake without process isolation, and core/pack_registry.py
    stays the only place that knows how a real pack is found on disk.
    pack_version_for resolves a pack_id to its installed manifest version,
    used only to invalidate the cache when a pack itself is upgraded.
    is_pack_cacheable resolves a pack_id to its manifest's cacheable flag —
    a segment is only ever served from cache if its pack opted in. Without
    this, a pack that launches an interactive program (RealityCapture's own
    window) would have its second "Launch" click silently do nothing on an
    unchanged graph: the cache would report success without ever running
    the pack again, because nothing about the resolved inputs changed.

    The cache is process-lifetime only (in memory): it does not persist
    across editor restarts. Disk persistence (Ст.10.2) is deferred until a
    concrete need for it is measured (Ст.9.3), not built pre-emptively.
    """

    def __init__(self, executor_factory: Callable[[str], Optional[PackExecutor]],
                 pack_version_for: Callable[[str], str],
                 is_pack_cacheable: Callable[[str], bool] = lambda pack_id: False):
        self._executor_factory = executor_factory
        self._pack_version_for = pack_version_for
        self._is_pack_cacheable = is_pack_cacheable
        self._cache: Dict[str, ExecutionResult] = {}

    def execute(self, graph: GraphModel, *,
                cancel_check: Optional[Callable[[], bool]] = None) -> List[SegmentRun]:
        chain = build_exec_chain(graph)
        if not chain:
            return []

        runs: List[SegmentRun] = []
        for segment in segment_chain_by_pack(chain):
            if cancel_check and cancel_check():
                break
            runs.append(self._run_segment(graph, segment, cancel_check))
        return runs

    def _run_segment(self, graph: GraphModel, segment: Segment,
                      cancel_check: Optional[Callable[[], bool]]) -> SegmentRun:
        node_uids = [n.uid for n in segment.nodes]
        commands = _segment_commands(graph, segment)
        cacheable = self._is_pack_cacheable(segment.pack_id)
        cache_key = None

        if cacheable:
            pack_version = self._pack_version_for(segment.pack_id)
            cache_key = _segment_cache_key(commands, pack_version)
            cached = self._cache.get(cache_key)
            if cached is not None:
                return SegmentRun(pack_id=segment.pack_id, node_uids=node_uids, result=cached, cache_hit=True)

        executor = self._executor_factory(segment.pack_id)
        if executor is None:
            log_and_explain(
                f"Cannot run segment for pack '{segment.pack_id}'",
                RuntimeError("no installed pack provides this pack_id"),
            )
            result = ExecutionResult(ok=False, error=f"No pack installed for '{segment.pack_id}'")
        else:
            # cancel_check reaches into the segment itself, not just between
            # segments — a segment that's a long RC job must be killable
            # mid-run, not only once it happens to finish (see
            # core/pack_executor.py's poll loop).
            result = executor.run_commands(commands, cancel_check=cancel_check)

        if cacheable and result.ok:
            self._cache[cache_key] = result
        return SegmentRun(pack_id=segment.pack_id, node_uids=node_uids, result=result, cache_hit=False)
