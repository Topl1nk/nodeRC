"""graph_export.py — Rendering a Graph's Exec Chain to a Pack-Defined Text Format

The export counterpart of graph_executor.py: same chain-walking and
pack-segmentation (build_exec_chain/segment_chain_by_pack/segment_commands),
but instead of handing each segment to a pack for a real run, it asks the
pack to render that segment as text in one of its own declared formats
(PackManifest.exporters, PackExecutor.render_export) — e.g. RealityScan's
``.bat``/``.rscmd``. Nothing here knows what any pack's formats actually
look like; that stays entirely inside the pack (Ст.4.2).

Zero Qt or ui imports (Ст.3) — the editor's Export dialog only needs to
call render_graph_export and write the result to disk.
"""
from __future__ import annotations

from typing import Callable, Optional

from core.graph_model import GraphModel
from core.graph_executor import build_exec_chain, segment_chain_by_pack, segment_commands
from core.pack_protocol import ExecutionResult, PackExecutor


def render_graph_export(graph: GraphModel, format_id: str,
                         executor_factory: Callable[[str], Optional[PackExecutor]]) -> ExecutionResult:
    """Renders every pack segment of ``graph``'s exec chain into
    ``format_id`` text and joins them in chain order. Stops at the first
    segment that fails to render (unknown format_id, pack not installed, or
    the pack's own render_export reporting ok=False) — the same
    fail-fast-on-first-broken-segment behavior GraphExecutor.execute uses
    for real runs, so a partially-rendered script is never silently handed
    to the user as if it were complete.
    """
    chain = build_exec_chain(graph)
    if not chain:
        return ExecutionResult(ok=False, error="Chain is empty — connect at least one Command Node to Start.")

    rendered_parts = []
    for segment in segment_chain_by_pack(chain):
        executor = executor_factory(segment.pack_id)
        if executor is None:
            return ExecutionResult(ok=False, error=f"No pack installed for '{segment.pack_id}'.")
        result = executor.render_export(segment_commands(graph, segment), format_id)
        if not result.ok:
            return result
        rendered_parts.append(result.output)

    return ExecutionResult(ok=True, output="\n".join(rendered_parts))
