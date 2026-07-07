"""search_ranking.py — Shared "What's Likely Wanted Here" Scoring

One scoring/ranking core used by two surfaces that both need to guess which
node the user is about to reach for: the search menu's "Suggested" shortlist
(ui/search_menu.py) and the socket ghost's side-button candidate cycling
(ui/graph_items.py, SocketItem/_SocketGhostPreview). Ст.14.3 — a repeated
concept lives in one place, not reimplemented per call site, so the two
surfaces can never quietly drift out of agreement about what "usually comes
next" means.

Deliberately Qt-free (only reads plain attributes off whatever socket-like
object it's given — is_exec/kind/param_type — never imports PyQt5), even
though both its callers live under ui/ and could get away with importing
Qt. Nothing here needs it.
"""
from __future__ import annotations

from typing import Optional

from core.node_blueprint import resolve_param_type
from core.app_prefs import get_search_usage, get_search_usage_after


def usage_key(payload: dict) -> Optional[str]:
    if "command" in payload:
        return f"cmd:{payload.get('command', '')}"
    if "param_type" in payload:
        return f"param:{payload['param_type']}"
    return None


def context_key_for_socket(source_socket) -> Optional[str]:
    """Identifies "what this menu/ghost was opened from", for the
    usage-after bigram: the owning command's name for an exec socket,
    "start" for the chain root, or None for a param socket / no socket at
    all — param context is ranked by type compatibility instead (see
    is_compatible), which needs no history."""
    if source_socket is None or not source_socket.sock_def.is_exec:
        return None
    node = source_socket.meta_node
    cmd_def = getattr(node, "cmd_def", None)
    if cmd_def:
        return f"cmd:{cmd_def.get('command', '')}"
    return "start"


def payload_param_types(payload: dict) -> set:
    """Every data type this command's required/optional params accept —
    derived straight from cmd_def, no node instantiation needed."""
    types = set()
    for key in ("required", "optional"):
        for param in payload.get(key, []):
            name = param if isinstance(param, str) else param.get("name", "")
            types.add(resolve_param_type(name, param) if isinstance(param, dict) else "string")
    return types


def is_compatible(payload: dict, source_socket) -> bool:
    """Whether ``payload`` matches the drag source's data type — only
    meaningful for a param (non-exec) source, where sockets carry a real
    type; an exec source (chain flow) reports every command compatible,
    since virtually all of them are, and lets usage ranking sort instead."""
    if source_socket is None or source_socket.sock_def.is_exec:
        return True
    src_type = source_socket.sock_def.param_type
    if source_socket.sock_def.kind == "output":
        return "command" not in payload or src_type in payload_param_types(payload)
    return payload.get("param_type") == src_type


def score_components(payload: dict, source_socket, context_key: Optional[str],
                      usage: dict, usage_after: dict) -> tuple:
    """(usage_score, compat_bonus) for one entry. usage_score reflects prior
    picks — raw popularity plus the "usually follows this node" bigram for
    the current exec context; compat_bonus rewards a real data-type match on
    a param source."""
    usage_score = 0.0
    key = usage_key(payload)
    if key:
        usage_score += min(usage.get(key, 0), 20) * 3
        if context_key:
            usage_score += min(usage_after.get(context_key, {}).get(key, 0), 20) * 15
    compat_bonus = 40.0 if is_compatible(payload, source_socket) else 0.0
    return usage_score, compat_bonus


def collect_command_entries(command_categories: dict) -> list:
    """Every command across every pack, flattened to {"payload", "label"} —
    the same shape ranked_candidates/score_components expect."""
    entries = []
    for pack_sections in command_categories.values():
        for subsections in pack_sections.values():
            for commands in subsections.values():
                for cmd in commands:
                    entries.append({"payload": cmd, "label": cmd["display"]})
    return entries


def ranked_candidates(entries: list, source_socket, context_key: Optional[str],
                       limit: Optional[int] = None) -> list:
    """``entries`` ranked by real usage signal only (never an arbitrary
    top-N with no history behind it) — empty on a fresh install, filling in
    as the user picks things. Reads current usage stats itself, so callers
    never have to thread them through."""
    usage = get_search_usage()
    usage_after = get_search_usage_after()
    scored = []
    for entry in entries:
        usage_score, compat_bonus = score_components(entry["payload"], source_socket, context_key, usage, usage_after)
        if usage_score > 0:
            scored.append((usage_score + compat_bonus, entry))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    ranked = [entry for _, entry in scored]
    return ranked[:limit] if limit is not None else ranked
