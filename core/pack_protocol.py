"""pack_protocol.py — The Node-Pack Contract

Defines the manifest and command-catalog shapes every node pack (RealityCapture
today, other 3D-software CLIs/APIs later) must expose, and the abstract
executor interface a pack's runtime implements. This is the one boundary
(CODEX.md Ст.4.2) through which pack_registry discovers packs and
graph_executor drives them — no other module reaches into a pack's internals.

Zero Qt or ui imports: packs are discovered and driven headlessly (Ст.3).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

PROTOCOL_VERSION = 1


class PackManifestError(Exception):
    """A pack's manifest is missing, malformed, or speaks an incompatible
    protocol_version. Carries a human-readable cause (Ст.8.3) — callers
    surface str(exc) directly instead of translating a bare error code."""


@dataclass(frozen=True)
class PackDeclares:
    """What a pack asks permission for before installation (Доктрина III.2).
    filesystem is a subset of {"read", "write"}."""
    executable: bool = False
    filesystem: List[str] = field(default_factory=list)
    network: bool = False

    @classmethod
    def from_dict(cls, payload: dict) -> "PackDeclares":
        return cls(
            executable=bool(payload.get("executable", False)),
            filesystem=list(payload.get("filesystem", [])),
            network=bool(payload.get("network", False)),
        )

    def to_dict(self) -> dict:
        return {
            "executable": self.executable,
            "filesystem": list(self.filesystem),
            "network": self.network,
        }


@dataclass(frozen=True)
class PackManifest:
    """One pack's identity and how the registry launches it. Loaded from a
    pack.json living at the root of each drop-in pack folder (Phase 2)."""
    pack_id: str
    display_name: str
    version: str
    protocol_version: int
    entry_point: str
    declares: PackDeclares
    commands_source: Optional[str] = None
    # Doctrine V's segment cache assumes re-running with the same resolved
    # inputs is safe to skip — true for a pure batch computation, false for
    # a pack that launches an interactive program (RealityCapture's own
    # window): the user clicking Launch twice means "run it again", not
    # "run it again unless nothing changed". Defaults to False — a pack
    # must opt in, the same way it must opt in to filesystem/network access
    # (Доктрина III.2): caching is also a capability with consequences,
    # not a free optimization every pack automatically gets.
    cacheable: bool = False

    _REQUIRED_FIELDS = ("pack_id", "display_name", "version", "protocol_version", "entry_point")

    @classmethod
    def from_dict(cls, payload: dict) -> "PackManifest":
        missing = [k for k in cls._REQUIRED_FIELDS if k not in payload]
        if missing:
            raise PackManifestError(
                f"Manifest missing required field(s): {', '.join(missing)}"
            )
        return cls(
            pack_id=payload["pack_id"],
            display_name=payload["display_name"],
            version=payload["version"],
            protocol_version=payload["protocol_version"],
            entry_point=payload["entry_point"],
            declares=PackDeclares.from_dict(payload.get("declares", {})),
            commands_source=payload.get("commands_source"),
            cacheable=bool(payload.get("cacheable", False)),
        )

    def to_dict(self) -> dict:
        d = {
            "pack_id": self.pack_id,
            "display_name": self.display_name,
            "version": self.version,
            "protocol_version": self.protocol_version,
            "entry_point": self.entry_point,
            "declares": self.declares.to_dict(),
            "cacheable": self.cacheable,
        }
        if self.commands_source is not None:
            d["commands_source"] = self.commands_source
        return d

    def check_protocol_compatible(self) -> None:
        """Reject an incompatible pack with an explained cause (Ст.8.3)
        instead of a silent skip or a cryptic crash deep inside the
        registry or executor."""
        if self.protocol_version != PROTOCOL_VERSION:
            raise PackManifestError(
                f"Pack '{self.pack_id}' declares protocol_version="
                f"{self.protocol_version}, but this nodeRC build speaks "
                f"protocol_version={PROTOCOL_VERSION}. Update the pack or the editor."
            )


@dataclass(frozen=True)
class ParamDef:
    """One command parameter. The {name, type, values} shape is the one
    core/rs_documentation_extractor.py already produces for RealityScan,
    generalised — it carries no RS-specific assumption."""
    name: str
    type: str = "string"
    values: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> ParamDef:
        return cls(name=data["name"], type=data.get("type", "string"), values=data.get("values", []))

    def to_dict(self) -> dict:
        return {"name": self.name, "type": self.type, "values": self.values}


@dataclass(frozen=True)
class CommandDef:
    """One invocable operation a pack exposes as a node. Mirrors the JSON
    shape rs_documentation_extractor.py already writes to rs_commands.json
    (command, display, action, required/optional param lists, section,
    subsection) — unchanged, so RS's existing catalog needs no transformation
    when it becomes the first pack's commands_source (Phase 3)."""
    command: str
    display: str = ""
    action: str = ""
    required: List[ParamDef] = field(default_factory=list)
    optional: List[ParamDef] = field(default_factory=list)
    section: Optional[str] = None
    subsection: Optional[str] = None

    @classmethod
    def from_dict(cls, payload: dict) -> "CommandDef":
        return cls(
            command=payload["command"],
            display=payload.get("display", ""),
            action=payload.get("action", ""),
            required=[ParamDef.from_dict(p) for p in payload.get("required", [])],
            optional=[ParamDef.from_dict(p) for p in payload.get("optional", [])],
            section=payload.get("section"),
            subsection=payload.get("subsection"),
        )

    def to_dict(self) -> dict:
        d = {
            "command": self.command,
            "display": self.display,
            "action": self.action,
            "required": [p.to_dict() for p in self.required],
            "optional": [p.to_dict() for p in self.optional],
        }
        if self.section is not None:
            d["section"] = self.section
        if self.subsection is not None:
            d["subsection"] = self.subsection
        return d


@dataclass(frozen=True)
class ExecutionResult:
    """What a pack's executor hands back for one node run. Defined now so
    the call contract exists before any transport (Phase 4) or the
    incremental graph executor (Phase 5) implements it."""
    ok: bool
    output: str = ""
    error: str = ""


class PackExecutor:
    """Abstract interface every pack's runtime implements. Concrete
    implementations (Phase 4) launch the pack in its own process per
    Доктрина III.1 — this class fixes the call contract, not the transport.

    run_commands is the primitive: a pack with cross-command state (RC's CLI
    keeps a project loaded in memory across -load/-align/-export flags) must
    receive a whole contiguous run as one call, one process — splitting it
    into one process per command would silently lose that state. A pack with
    no such state can still return one clean success/failure per call; it
    just never needs more than a single-element list.
    """

    def run_commands(self, commands: List[Tuple[CommandDef, Dict[str, str]]], *,
                      cancel_check: Optional[Callable[[], bool]] = None) -> ExecutionResult:
        """cancel_check, if given, is polled while waiting for the pack to
        finish; when it returns True the implementation must stop the pack's
        process (its whole tree, not just the wrapper — Доктрина III.1's
        isolation cuts both ways: a cancel must actually stop external work,
        not just stop waiting for it) and report ok=False, not hang or leave
        it running unattended."""
        raise NotImplementedError

    def run_command(self, command: CommandDef, params: Dict[str, str], *,
                     cancel_check: Optional[Callable[[], bool]] = None) -> ExecutionResult:
        """Convenience for the common one-command case — not a second
        implementation (Ст.1.2), just a call-shape adapter over run_commands."""
        return self.run_commands([(command, params)], cancel_check=cancel_check)
