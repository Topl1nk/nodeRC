"""rs_pack.py — RealityScan Pack Entry Point

The subprocess core/pack_executor.py launches for every execution segment:
one JSON request on stdin, one JSON response on stdout (see PackExecutor in
core/pack_protocol.py). All commands of a segment become a single
RealityScan.exe invocation — RS keeps a project loaded in memory across
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
    from packs.realityscan.config import RS_EXECUTABLE
except ImportError:
    # Launched directly as a script (the executor invokes this file by path,
    # so the repo root may not be on sys.path) — fall back to the sibling
    # module import that works from inside the pack folder.
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from config import RS_EXECUTABLE  # type: ignore


_VECTOR_PARAM_TYPES = {"float2", "float3"}


def build_command_tokens(command_payload: dict, params: dict) -> list:
    """CLI tokens for one command: the flag itself, then every filled-in
    parameter value in declaration order (required first, then optional).
    An empty/missing value is skipped, not passed as an empty token.

    Only a declared vector param (float2/float3 — "1.0 2.0 3.0") splits
    into one token per component, since RealityScan's CLI takes vector
    components as separate arguments; every other param's value becomes
    exactly one token, spaces and all — splitting on whitespace
    unconditionally used to also shred any ordinary path containing a
    space ("D:/My Photos" -> two silently wrong tokens, "D:/My" and
    "Photos") into an invalid command line. subprocess.run/list2cmdline
    quote a multi-word single token correctly on their own; nothing here
    needs to pre-split it.
    """
    tokens = [command_payload["command"]]
    declared = list(command_payload.get("required", [])) + list(command_payload.get("optional", []))
    for param in declared:
        name = param["name"] if isinstance(param, dict) else param
        value = str(params.get(name, "") or "").strip()
        if not value:
            continue
        param_type = param.get("type") if isinstance(param, dict) else None
        if param_type in _VECTOR_PARAM_TYPES:
            tokens.extend(value.split())
        else:
            tokens.append(value)
    return tokens


def render_export(commands: list, format_id: str) -> dict:
    """Formats one segment's ordered commands as plain export text — pure
    string building, no subprocess, no I/O. Still reached only through the
    stdin/stdout contract main() dispatches on (see the "mode" field), not
    a second in-process import path, because core.pack_protocol's own rule
    is that nothing outside a pack ever reaches into its internals except
    through that one boundary (Ст.4.2) — formatting text has no need for
    process isolation on its own, but going through it anyway keeps every
    pack call shaped the same way.

    "bat": every command's tokens, concatenated into the single RealityScan
    invocation this segment would actually run as (see run_request's own
    "All commands of a segment become one invocation") — a naive
    one-line-per-command .bat would relaunch RealityScan per command and
    silently lose the in-memory project state real execution keeps.
    "rscmd": one command per line, no executable prefix — the format
    RealityScan itself parses when a .rscmd file is dragged onto it or
    passed to -execrscmd (see Help/en-US/tutorials/commandline_rscmd.htm in
    the vendor docs).
    """
    if format_id == "bat":
        tokens = [RS_EXECUTABLE]
        for entry in commands:
            tokens.extend(build_command_tokens(entry["command"], entry.get("params", {})))
        text = subprocess.list2cmdline(tokens)
    elif format_id == "rscmd":
        lines = [subprocess.list2cmdline(build_command_tokens(entry["command"], entry.get("params", {})))
                 for entry in commands]
        text = "\n".join(lines)
    else:
        return {"ok": False, "output": "", "error": f"Unknown export format_id: {format_id!r}"}
    return {"ok": True, "output": text, "error": ""}


def _load_command_catalog() -> dict:
    """{command_flag: cmd_def} straight from the generated rs_commands.json,
    read directly rather than through command_database.py's richer loader —
    that module imports rs_documentation_extractor.py, which hard-requires
    BeautifulSoup (raises SystemExit if it's missing) for HTML re-parsing
    this subprocess never needs; parse_import only ever needs the flat
    {command: {required, optional, ...}} shape already sitting on disk,
    read with the standard library alone (this file's own docstring's
    promise)."""
    try:
        from packs.realityscan.config import COMMAND_DB_JSON
    except ImportError:
        import os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from config import COMMAND_DB_JSON  # type: ignore
    try:
        with open(COMMAND_DB_JSON, "r", encoding="utf-8") as f:
            categories = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    catalog = {}
    for sections in categories.values():
        for commands in sections.values():
            for cmd in commands:
                catalog[cmd["command"]] = cmd
    return catalog


def _tokenize_command_line(line: str) -> list:
    """The inverse of subprocess.list2cmdline: splits one command-line
    string into argv tokens following the same Win32 quoting convention
    list2cmdline writes them in (a run of backslashes only escapes if
    immediately followed by a literal quote — an even run stays literal
    backslashes, an odd run's last backslash escapes the quote; a bare
    quote toggles quoted mode) — the documented inverse of that exact
    escaping scheme, so anything render_export itself wrote parses back
    exactly. Hand-edited files that never needed quoting (the common case:
    plain flags and unquoted paths) round-trip trivially either way."""
    args = []
    current = []
    in_quotes = False
    i, n = 0, len(line)
    while i < n:
        ch = line[i]
        if ch in (" ", "\t") and not in_quotes:
            if current:
                args.append("".join(current))
                current = []
            i += 1
            continue
        if ch == "\\":
            run = 0
            while i < n and line[i] == "\\":
                run += 1
                i += 1
            if i < n and line[i] == '"':
                current.append("\\" * (run // 2))
                if run % 2 == 1:
                    current.append('"')
                else:
                    in_quotes = not in_quotes
                i += 1
            else:
                current.append("\\" * run)
            continue
        if ch == '"':
            in_quotes = not in_quotes
            i += 1
            continue
        current.append(ch)
        i += 1
    if current:
        args.append("".join(current))
    return args


def _rscmd_lines(text: str) -> list:
    """Real command lines from .rscmd text: drops blank lines and comment
    lines (#, //, REM/rem — case-insensitive), and joins a ``^``-terminated
    line onto the next one (see the vendor docs at
    Help/en-US/tutorials/commandline_rscmd.htm). $(argN)/$For(...) template
    syntax is deliberately not evaluated here — those need real argument
    substitution/loop-unrolling context this headless parser doesn't have;
    a file using them fails the "no recognized commands" check in
    parse_import rather than silently importing something wrong."""
    lines = []
    buffer = ""
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith(("#", "//")) or stripped.upper().startswith("REM"):
            continue
        if stripped.endswith("^"):
            buffer += stripped[:-1] + " "
            continue
        lines.append(buffer + stripped)
        buffer = ""
    if buffer:
        lines.append(buffer)
    return lines


def _tokenize_bat(text: str) -> list:
    """Every argv token across a .bat's surviving lines, in order — skips
    blank lines and batch-file comment/directive conventions (@, ::, REM),
    and drops a line's own leading executable path (render_export always
    writes RS_EXECUTABLE as the first token of its one invocation line)."""
    tokens = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith(("@", "::")) or stripped.upper().startswith("REM"):
            continue
        line_tokens = _tokenize_command_line(stripped)
        if line_tokens and line_tokens[0].lower().endswith(".exe"):
            line_tokens = line_tokens[1:]
        tokens.extend(line_tokens)
    return tokens


def parse_import(text: str, format_id: str) -> dict:
    """The reverse of render_export: recovers [{"command": cmd_def,
    "params": {...}}, ...] from previously-exported (or hand-written) text.

    Token-to-command assignment is positional, not name-tagged (the text
    format itself carries no field names — see build_command_tokens, whose
    output this inverts): everything between one recognized command flag
    and the next becomes that command's raw values, zipped in
    required-then-optional declaration order against however many tokens
    each param actually consumes (2 for float2, 3 for float3, 1 otherwise
    — mirrors core.graph_executor's own group_xyz_params on the way out).
    A command whose real usage supplied fewer values than declared params
    just leaves the trailing ones unset, same as an ordinary empty field.
    """
    catalog = _load_command_catalog()
    if not catalog:
        return {"ok": False, "commands": [],
                "error": "No RealityScan command catalog available — run the app once "
                         "so it can be generated from the local install's help docs."}

    if format_id == "bat":
        tokens = _tokenize_bat(text)
    elif format_id == "rscmd":
        tokens = []
        for line in _rscmd_lines(text):
            tokens.extend(_tokenize_command_line(line))
    else:
        return {"ok": False, "commands": [], "error": f"Unknown import format_id: {format_id!r}"}

    commands = []
    i, n = 0, len(tokens)
    while i < n:
        cmd_def = catalog.get(tokens[i])
        if cmd_def is None:
            i += 1  # a stray value, unrecognized command, or a leftover exe path — skip, don't fail the whole import
            continue
        i += 1
        raw_values = []
        while i < n and tokens[i] not in catalog:
            raw_values.append(tokens[i])
            i += 1

        declared = list(cmd_def.get("required", [])) + list(cmd_def.get("optional", []))
        params, pos = {}, 0
        for param in declared:
            name = param["name"] if isinstance(param, dict) else param
            ptype = param.get("type", "string") if isinstance(param, dict) else "string"
            width = {"float2": 2, "float3": 3}.get(ptype, 1)
            if pos >= len(raw_values):
                break
            params[name] = " ".join(raw_values[pos:pos + width])
            pos += width
        commands.append({"command": cmd_def, "params": params})

    if not commands:
        return {"ok": False, "commands": [], "error": "No recognized RealityScan commands found in the file."}
    return {"ok": True, "commands": commands, "error": ""}


def run_request(request: dict) -> dict:
    """Execute one segment request: every command concatenated into a single
    RealityScan invocation. Any failure — launch error, non-zero exit —
    comes back as ok=False with a human-readable error, never an exception
    (the editor-side contract in core/pack_executor.py expects exactly the
    {ok, output, error} shape).
    """
    tokens = [RS_EXECUTABLE]
    for entry in request.get("commands", []):
        tokens.extend(build_command_tokens(entry["command"], entry.get("params", {})))

    try:
        completed = subprocess.run(tokens, capture_output=True, text=True)
    except OSError as exc:
        return {"ok": False, "output": "", "error": str(exc)}

    error_msg = completed.stderr
    if completed.returncode != 0 and not error_msg:
        error_msg = f"RealityScan exited with code {completed.returncode}."
        if completed.stdout.strip():
            error_msg += f"\nOutput:\n{completed.stdout.strip()}"

    return {
        "ok": completed.returncode == 0,
        "output": completed.stdout,
        "error": error_msg,
    }


def main() -> int:
    try:
        request = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        json.dump({"ok": False, "output": "", "error": f"Malformed request: {exc}"}, sys.stdout)
        return 1
    mode = request.get("mode")
    if mode == "export":
        response = render_export(request.get("commands", []), request.get("format_id", ""))
    elif mode == "import":
        response = parse_import(request.get("text", ""), request.get("format_id", ""))
    else:
        response = run_request(request)
    json.dump(response, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
