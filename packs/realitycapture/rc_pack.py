"""rc_pack.py — RealityCapture Pack Entry Point

The subprocess core/pack_executor.py launches for every execution segment:
one JSON request on stdin, one JSON response on stdout (see PackExecutor in
core/pack_protocol.py). All commands of a segment become a single
RealityCapture.exe invocation — RC keeps a project loaded in memory across
its CLI flags (-load/-align/-exportModel), so splitting a segment into one
process per command would silently lose that state.

Runs standalone (Доктрина III.1: this file executes in its own process,
never inside the editor) — imports only the standard library plus the
pack's own config.
"""
from __future__ import annotations

import json
import subprocess
import sys

try:
    from packs.realitycapture.config import RC_EXECUTABLE
except ImportError:
    # Launched directly as a script (the executor invokes this file by path,
    # so the repo root may not be on sys.path) — fall back to the sibling
    # module import that works from inside the pack folder.
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from config import RC_EXECUTABLE  # type: ignore


def build_command_tokens(command_payload: dict, params: dict) -> list:
    """CLI tokens for one command: the flag itself, then every filled-in
    parameter value in declaration order (required first, then optional).
    An empty/missing value is skipped, not passed as an empty token; a
    vector value ("1.0 2.0 3.0") splits into one token per component —
    RealityCapture's CLI takes vector components as separate arguments.
    """
    tokens = [command_payload["command"]]
    declared = list(command_payload.get("required", [])) + list(command_payload.get("optional", []))
    for param in declared:
        value = str(params.get(param["name"], "") or "").strip()
        if not value:
            continue
        tokens.extend(value.split())
    return tokens


def run_request(request: dict) -> dict:
    """Execute one segment request: every command concatenated into a single
    RealityCapture invocation. Any failure — launch error, non-zero exit —
    comes back as ok=False with a human-readable error, never an exception
    (the editor-side contract in core/pack_executor.py expects exactly the
    {ok, output, error} shape).
    """
    tokens = [RC_EXECUTABLE]
    for entry in request.get("commands", []):
        tokens.extend(build_command_tokens(entry["command"], entry.get("params", {})))

    try:
        completed = subprocess.run(tokens, capture_output=True, text=True)
    except OSError as exc:
        return {"ok": False, "output": "", "error": str(exc)}

    return {
        "ok": completed.returncode == 0,
        "output": completed.stdout,
        "error": completed.stderr,
    }


def main() -> int:
    try:
        request = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        json.dump({"ok": False, "output": "", "error": f"Malformed request: {exc}"}, sys.stdout)
        return 1
    json.dump(run_request(request), sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
