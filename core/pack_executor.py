"""pack_executor.py — Running a Pack's Commands in Its Own Process

Доктрина III.1: a pack that crashes or hangs must never take the editor
down with it. ProcessPackExecutor launches installed.pack_dir/entry_point as
a fresh subprocess per call, feeds it one JSON request on stdin, and reads
one JSON response from stdout. A launch failure, a non-zero exit, a timeout
or a malformed response all become a logged ExecutionResult(ok=False) —
never an exception that would propagate into the caller (core/graph_executor.py).

One call passes the whole ordered list of commands for one contiguous
execution unit (core/graph_executor.py's segment) — one process, one
result — so a pack with cross-command state (RC keeps a project loaded in
memory across -load/-align/-export) sees them the same way it would if the
editor built one CLI invocation itself.

Waiting for that process polls in short slices instead of one blocking call,
so a cancel_check or a timeout can act mid-wait — killing the whole process
tree, not just the wrapper: on Windows, a wrapper's own child (RealityCapture.exe,
say) survives its parent's death unless killed together (taskkill /T).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from typing import Callable, Dict, List, Optional, Tuple

from core.pack_protocol import CommandDef, ExecutionResult, PackExecutor
from core.pack_registry import InstalledPack
from diagnostics import log_and_explain

_POLL_INTERVAL_SECONDS = 0.2


def _kill_process_tree(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        return
    import os
    import signal
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except ProcessLookupError:
        pass  # already gone


class ProcessPackExecutor(PackExecutor):
    """Bound to one InstalledPack; every run_commands() call launches
    ``sys.executable <pack_dir>/<entry_point>`` fresh, so one pack's crash
    or infinite loop is contained to that single subprocess."""

    def __init__(self, installed: InstalledPack, *, timeout: Optional[float] = None):
        self._installed = installed
        self._timeout = timeout

    def run_commands(self, commands: List[Tuple[CommandDef, Dict[str, str]]], *,
                      cancel_check: Optional[Callable[[], bool]] = None) -> ExecutionResult:
        pack_id = self._installed.manifest.pack_id
        entry_path = self._installed.pack_dir / self._installed.manifest.entry_point
        request = json.dumps({
            "commands": [{"command": command.to_dict(), "params": params} for command, params in commands]
        })

        try:
            proc = subprocess.Popen(
                [sys.executable, str(entry_path)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as exc:
            reason = log_and_explain(f"Pack '{pack_id}' failed to launch", exc)
            return ExecutionResult(ok=False, error=reason)

        try:
            proc.stdin.write(request)
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass  # the process already exited (e.g. missing entry_point) — its exit code/stderr still apply below

        started = time.monotonic()
        stdout = stderr = ""
        while True:
            try:
                stdout, stderr = proc.communicate(timeout=_POLL_INTERVAL_SECONDS)
                break
            except subprocess.TimeoutExpired:
                if cancel_check and cancel_check():
                    _kill_process_tree(proc.pid)
                    proc.communicate()
                    return ExecutionResult(ok=False, error=f"Pack '{pack_id}' cancelled")
                if self._timeout is not None and time.monotonic() - started > self._timeout:
                    _kill_process_tree(proc.pid)
                    proc.communicate()
                    reason = log_and_explain(
                        f"Pack '{pack_id}' timed out",
                        subprocess.TimeoutExpired(str(entry_path), self._timeout),
                    )
                    return ExecutionResult(ok=False, error=reason)

        if proc.returncode != 0:
            reason = log_and_explain(
                f"Pack '{pack_id}' exited with code {proc.returncode}",
                RuntimeError(stderr.strip() or "no stderr output"),
            )
            return ExecutionResult(ok=False, error=reason)

        try:
            response = json.loads(stdout)
        except json.JSONDecodeError as exc:
            reason = log_and_explain(f"Pack '{pack_id}' returned a malformed response", exc)
            return ExecutionResult(ok=False, error=reason)

        return ExecutionResult(
            ok=bool(response.get("ok", False)),
            output=response.get("output", ""),
            error=response.get("error", ""),
        )


def build_executor_factory(installed_packs: List[InstalledPack], *,
                            timeout: Optional[float] = None) -> Callable[[str], Optional[PackExecutor]]:
    """core/graph_executor.py needs a pack_id -> PackExecutor lookup, not a
    dependency on how packs are found on disk (Ст.2.1) — this is the one
    place that turns core/pack_registry.py's discovery result into that
    lookup for the real, process-isolated case."""
    by_id = {p.manifest.pack_id: p for p in installed_packs}

    def factory(pack_id: str) -> Optional[PackExecutor]:
        installed = by_id.get(pack_id)
        return ProcessPackExecutor(installed, timeout=timeout) if installed else None

    return factory


def pack_version_lookup(installed_packs: List[InstalledPack]) -> Callable[[str], str]:
    """core/graph_executor.py's cache key includes the pack's own version so
    upgrading a pack invalidates every segment it previously ran — this
    resolves pack_id -> that version from the same discovery result
    build_executor_factory uses."""
    by_id = {p.manifest.pack_id: p for p in installed_packs}

    def lookup(pack_id: str) -> str:
        installed = by_id.get(pack_id)
        return installed.manifest.version if installed else ""

    return lookup


def pack_cacheable_lookup(installed_packs: List[InstalledPack]) -> Callable[[str], bool]:
    """core/graph_executor.py must not cache a segment unless the pack that
    ran it declared itself safe to skip re-running (manifest.cacheable) —
    an unknown pack_id is treated as not cacheable, the same fail-safe
    default as an absent field in the manifest itself."""
    by_id = {p.manifest.pack_id: p for p in installed_packs}

    def lookup(pack_id: str) -> bool:
        installed = by_id.get(pack_id)
        return bool(installed and installed.manifest.cacheable)

    return lookup
