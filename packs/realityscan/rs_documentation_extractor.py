"""
rc_documentation_extractor.py — RealityScan HTML Documentation Parser
Parses allcommands.htm and writes:
  • rs_commands.json — rich format with categories, display names, typed params
  • rs_commands.txt  — legacy flat format for backward compatibility

JSON schema per command:
  {
    "command":     "-calculateQualityTexture",
    "display":     "Calculate Quality Texture",
    "action_word": "Calculate",
    "action":      "calculate",
    "required":    [ {"name": "params.xml", "type": "filepath", "values": []} ],
    "optional":    [ {"name": "true|false",  "type": "bool",    "values": ["true","false"]} ],
    "section":     "Reconstruction",
    "subsection":  null
  }
"""

from __future__ import annotations
import os
import re
import json
import logging
import urllib.request
from typing import Dict, List, Optional, Set, Tuple

from packs.realityscan.config import RS_HELP_HTML_CANDIDATES, COMMAND_DB_JSON

_logger = logging.getLogger("nodeRC")


try:
    from bs4 import BeautifulSoup
except ImportError:
    raise SystemExit("beautifulsoup4 required: pip install beautifulsoup4")


# ── Text normalization ─────────────────────────────────────────────────────────

def split_camel_case(s: str) -> str:
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', s)
    s = re.sub(r'([a-z\d])([A-Z])', r'\1 \2', s)
    return s.strip()


def command_display_name(command_flag: str) -> str:
    """-calculateQualityTexture → 'Calculate Quality Texture'"""
    words = split_camel_case(command_flag.lstrip("-")).split()
    if words:
        words[0] = words[0].capitalize()
    return " ".join(words)


def command_action_word(command_flag: str) -> str:
    """First camelCase word, lowercased: 'calculate'"""
    parts = split_camel_case(command_flag.lstrip("-")).split()
    return parts[0].lower() if parts else ""


def _normalise_command_flag(raw: str) -> str:
    cmd = raw.strip()
    return cmd if cmd.startswith("-") else f"-{cmd}"


def _strip_token_punctuation(token: str) -> str:
    return token.strip("<>\"'.,;:")


def _split_param_tokens(text: str) -> List[str]:
    skip = {"none", "n/a", "-", "", "or", "and"}
    seen: Set[str] = set()
    result: List[str] = []
    for raw in text.split():
        token = _strip_token_punctuation(raw)
        if token.lower() not in skip and token not in seen:
            seen.add(token)
            result.append(token)
    return result


# ── Type inference ─────────────────────────────────────────────────────────────

def _is_axis_token(param_token: str) -> bool:
    """True only for a genuine coordinate-axis parameter: the bare letter
    ('x') or a compound name ending in a capitalized axis letter ('offsetX',
    'rotateX', 'atX') — never a word that merely happens to end in that
    letter ('index', 'box.rsbox'). Checked on the original casing: RC's docs
    always capitalize the axis suffix on a compound name, so a *lowercase*
    trailing x/y/z is never one.
    """
    if param_token.lower() in ("x", "y", "z"):
        return True
    return len(param_token) > 1 and param_token[-1] in "XYZ" and param_token[-2].islower()


def _infer_param_type(param_token: str) -> str:
    lower = param_token.lower()
    if "|" in lower:
        options = {x.strip() for x in lower.split("|") if x.strip()}
        if options <= {"true", "false"}:
            return "bool"
        if all(x.isdigit() for x in options if x):
            return "enum_int"
        if any(ext in lower for ext in [".xml", "file", "path", "folder", "dir", "list"]):
            return "filepath"
        return "enum"

    if lower in ("true", "false"):
        return "bool"
    if re.match(r'^-?\d+$', param_token):
        return "integer"
    if _is_axis_token(param_token):
        return "float"
    if any(lower.endswith(x) or lower == x for x in (
        "distance", "focallength", "yaw", "pitch", "roll",
        "errorvalue", "heightvalue", "step", "axis", "number", "size"
    )):
        return "float"
    if any(lower.endswith(x) or lower == x for x in (
        "count", "length", "index", "threshold", "width", "height",
    )):
        return "integer"
    if any(lower.endswith(x) or lower == x for x in (
        ".xml", ".rcproj", ".rsproj", ".abc", ".obj", ".las", ".laz",
        ".rscmd", ".rsbox", ".rsalign", ".cmi", ".rcconfig", ".rclicense",
        "file", "filepath", "rsboxfile", "rsorthofile", "filename", "file path",
        "xmlfilepath", "cpmfilename", "flfilename", "gcpfilename",
        # NOT here: "modelName", "orthoName", "shapeName", "crossSectionsName",
        # "contoursName", "layerName" — every one of their occurrences in RC's
        # docs (checked all 11) names an item *already in the project* for
        # select/rename/duplicate to act on, never a path on disk. A token
        # only earns "filepath" by containing an actual file/path word itself
        # (".xml", "File", "Path", ...); bare "...Name" is an identifier.
    )):
        return "filepath"
    if any(lower.endswith(x) or lower == x for x in (
        "folder", "folderpath", "path", "dir", "location", "foldername", "folder path",
        "extractedvideoframeslocation", "crashreportpath", "dirpath",
    )):
        return "dirpath"
    if "=" in param_token:
        return "keyvalue"
    return "string"


_IDENTIFIER_RE = re.compile(r'^[A-Za-z][A-Za-z0-9]*$')


def _readable_name(raw_token: str) -> str:
    """A doc token turned into a snake_case identifier: 'rsorthoFile' → 'rsortho_file'.

    Pre-splits an acronym run directly abutting a lowercase word ('XMLfilePath',
    a docs typo missing the capital that would normally mark the new word) —
    split_camel_case's own heuristic has no capital to anchor the boundary on
    there and garbles it ('xm_lfile_path') instead of 'xml_file_path'. Non-
    identifier characters ('imagePath|regexp', a docs cell describing two
    accepted formats in one token) collapse to '_' rather than leaking
    through into the socket's name.
    """
    normalized = re.sub(r'([A-Z]{2,})([a-z])', r'\1_\2', raw_token)
    readable = split_camel_case(normalized).lower().replace(" ", "_")
    return re.sub(r'[^a-z0-9_]+', '_', readable).strip('_')


def _enum_choice_name(raw_token: str) -> str:
    """A two-option enum's own values, joined, when they read as plain words
    ('origin|center' → 'origin_center') — falls back to 'choice' for anything
    with a wildcard/instance-name option ('instanceName|*') that wouldn't make
    a sensible identifier, or a join so long ('recoverAutosave|deleteAutosave')
    it would be less readable than the generic name."""
    options = [v.strip() for v in raw_token.split("|") if v.strip()]
    if len(options) == 2 and all(_IDENTIFIER_RE.match(o) for o in options):
        joined = "_".join(o.lower() for o in options)
        if len(joined) <= 24:
            return joined
    return "choice"


# A one-extension file type is more recognizable as its literal extension
# (".xml") than a spelled-out word ("xml_file") — the connection-key `name`
# stays a plain identifier, the `label` is what the user actually reads.
# Matched as a bare substring so it catches both a literally-dotted doc token
# ("component.rsalign") and a compound camelCase one with no dot at all
# ("rsorthoFile", "XMLfilePath") — RC's docs use both forms for the exact
# same file kind, inconsistently, even within one command's own param list.
# Order matters only in that longer/more specific roots should be checked
# before anything they could be a substring of; none currently overlap.
_KNOWN_FILE_KINDS: Tuple[Tuple[str, str, str], ...] = (
    ("xml",        "xml_file",      ".xml"),
    ("rscmd",      "command_file",  ".rscmd"),
    ("rcconfig",   "settings_file", ".rcconfig"),
    ("rsortho",    "rsortho_file",  ".rsortho"),
    ("rsbox",      "rsbox_file",    ".rsbox"),
    ("rsalign",    "rsalign_file",  ".rsalign"),
    ("rclicense",  "license_file",  ".rclicense"),
)


def _build_param_record(raw_token: str) -> dict:
    ptype = _infer_param_type(raw_token)
    name = raw_token
    lower_name = name.lower()

    # Semantic renaming: known filename/path patterns get a fixed, well-known
    # name; anything else keeps its own doc-token identity (as a readable
    # snake_case label) instead of collapsing every same-typed param onto one
    # bare word. RC's own docs often give two same-typed params of a single
    # command genuinely distinct tokens (-exportModel's "modelName fileName",
    # -exportReport's "outputFileName templateFileName") that a blanket
    # rename would otherwise throw away — leaving both inputs on the node
    # identically named and impossible to tell apart without opening the
    # docs. Any pair still left generic after this (e.g. two bare booleans
    # with no name in the docs at all) gets a numeric suffix downstream, in
    # core.node_blueprint.dedupe_param_name.
    label = None
    if ptype == "filepath":
        known = next(((n, l) for root, n, l in _KNOWN_FILE_KINDS if root in lower_name), None)
        if known:
            name, label = known
        elif ".rsproj" in lower_name or ".rcproj" in lower_name:
            # Two different extensions share one concept — a single compact
            # ".rsproj" label would misname a .rcproj instance and vice versa.
            name = "project_file"
        elif "list" in lower_name: name = "list_file"
        elif "folder" in lower_name or "dir" in lower_name:
            name = "dirpath"
            ptype = "dirpath"
        else:
            name = _readable_name(raw_token)
    elif ptype == "dirpath":
        name = _readable_name(raw_token)
    elif ptype == "bool":
        name = "boolean"
    elif ptype == "keyvalue":
        name = "key_value"
    elif ptype in ("enum", "enum_int"):
        if "union" in lower_name and "sub" in lower_name:
            name = "selection_mode"
        else:
            name = _enum_choice_name(raw_token)

    record = {
        "name":   name,
        "type":   ptype,
        "values": [v.strip() for v in raw_token.split("|")] if ptype in ("enum", "enum_int") else [],
    }
    if label:
        record["label"] = label
    return record


# ── HTML parsing ───────────────────────────────────────────────────────────────

CommandCategoryTree = Dict[str, Dict[str, List[dict]]]


def _extract_categories(soup: BeautifulSoup) -> CommandCategoryTree:
    categories: CommandCategoryTree = {}
    current_section    = "Other"
    current_subsection: Optional[str] = None
    current_command    = ""

    for element in soup.find_all(["h2", "h3", "table"]):
        if element.name == "h2":
            current_section    = element.get_text(strip=True)
            current_subsection = None

        elif element.name == "h3":
            current_subsection = element.get_text(strip=True)

        elif element.name == "table" and "tableofcommands" in element.get("class", []):
            for row in element.find_all("tr"):
                cols = row.find_all("td")
                if not cols:
                    continue
                command_cell = row.find("td", class_="command")

                if command_cell:
                    current_command = _normalise_command_flag(
                        command_cell.get_text(separator=" ", strip=True)
                    )
                    required_cell = cols[1] if len(cols) > 1 else None
                    optional_cell = cols[2] if len(cols) > 2 else None
                    desc_cell     = cols[3] if len(cols) > 3 else None
                else:
                    required_cell = cols[0] if len(cols) > 0 else None
                    optional_cell = cols[1] if len(cols) > 1 else None
                    desc_cell     = cols[2] if len(cols) > 2 else None

                if not current_command:
                    continue

                description = ""
                if desc_cell:
                    description = desc_cell.get_text(separator=" ", strip=True)

                required_text = required_cell.get_text(separator=" ", strip=True) if required_cell else ""
                optional_text = optional_cell.get_text(separator=" ", strip=True) if optional_cell else ""

                section    = current_section
                subsection = current_subsection or "__root__"
                categories.setdefault(section, {}).setdefault(subsection, [])

                if not any(e["command"] == current_command for e in categories[section][subsection]):
                    display = command_display_name(current_command)
                    words   = display.split()
                    categories[section][subsection].append({
                        "command":     current_command,
                        "display":     display,
                        "action_word": words[0] if words else "",
                        "action":      command_action_word(current_command),
                        "required":    [_build_param_record(p) for p in _split_param_tokens(required_text)],
                        "optional":    [_build_param_record(p) for p in _split_param_tokens(optional_text)],
                        "section":     current_section,
                        "subsection":  current_subsection,
                        "description": description,
                    })
    return categories


# ── Undocumented commands ────────────────────────────────────────────────────
#
# Real, working CLI flags that Epic's own sample scripts use but that never
# made it into allcommands.htm's table (confirmed absent from the shipped
# docs, not a parsing gap — grepping the raw HTML for either name finds
# nothing). Curated by hand here instead of silently missing from the
# catalog, so a regen from HTML doesn't quietly drop them again.

def _manual_command(command: str, display: str, section: str, subsection: str,
                    required: List[str] = (), optional: List[str] = (),
                    description: str = "") -> dict:
    words = display.split()
    return {
        "command":     command,
        "display":     display,
        "action_word": words[0] if words else "",
        "action":      command_action_word(command),
        "required":    [_build_param_record(p) for p in required],
        "optional":    [_build_param_record(p) for p in optional],
        "section":     section,
        "subsection":  subsection,
        "description": description,
    }


def _add_undocumented_commands(categories: CommandCategoryTree) -> None:
    extra = [
        _manual_command(
            "-importLicense", "Import License",
            "Settings' and Error-handling Commands", None,
            required=["licenseFile.rclicense"],
            description="Import a per-photogroup PPI (pay-per-input) license file, "
                        "consumed by the sample dataset it was issued for.",
        ),
        _manual_command(
            "-exportDepthAndMask", "Export Depth And Mask",
            "Project and Images", "Commands for Selected Images",
            required=["maskSettings.xml"],
            description="Export a depth map and mask for the selected images against "
                        "the current model, using the given export settings.",
        ),
    ]
    for cmd in extra:
        section = categories.setdefault(cmd["section"], {})
        subsection = cmd["subsection"] or "__root__"
        section.setdefault(subsection, []).append(cmd)


# ── Writers ────────────────────────────────────────────────────────────────────

def _write_json_database(categories: CommandCategoryTree, path: str) -> int:
    total = sum(len(c) for s in categories.values() for c in s.values())
    # Write-then-replace: a crash or kill mid-write must never leave a
    # truncated rs_commands.json on disk for the next startup's json.load to
    # choke on (see core.command_database.load_command_database, which now
    # falls back to builtin_command_defaults() on exactly that failure — but
    # only if this file itself isn't the thing that's corrupt).
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(categories, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
    return total


# ── Public API ─────────────────────────────────────────────────────────────────

def _read_html_source(source: str, *, timeout: float = 10.0) -> Optional[str]:
    """The raw HTML text for one candidate path/URL, or None if it can't be
    reached — never raises, so rebuild_command_database_from_html can just
    move on to the next candidate instead of the whole rebuild failing
    because e.g. the network fallback timed out."""
    if source.startswith("http://") or source.startswith("https://"):
        try:
            with urllib.request.urlopen(source, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as exc:
            _logger.warning("Could not fetch documentation from %s: %s", source, exc)
            return None
    if not os.path.exists(source):
        return None
    with open(source, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def rebuild_command_database_from_html(
    html_path=None,
    json_output: str = COMMAND_DB_JSON,
) -> bool:
    """
    Parses the first reachable candidate in ``html_path`` (a single path/URL,
    or a list tried in order — defaults to RS_HELP_HTML_CANDIDATES, so a
    missing local install falls through to Capturing Reality's own hosted
    copy of the same page) and writes the rich JSON output database. Returns
    True on success, False if no candidate was reachable or none contained
    any commands.
    """
    candidates = [html_path] if isinstance(html_path, str) else (html_path or RS_HELP_HTML_CANDIDATES)

    html_text = None
    used = None
    for candidate in candidates:
        html_text = _read_html_source(candidate)
        if html_text is not None:
            used = candidate
            break
    if html_text is None:
        _logger.warning("Documentation not found in any of: %s", candidates)
        return False

    soup = BeautifulSoup(html_text, "html.parser")
    categories = _extract_categories(soup)
    if not categories:
        _logger.warning("No commands found in documentation (%s).", used)
        return False

    _add_undocumented_commands(categories)

    n_json = _write_json_database(categories, json_output)
    _logger.info("%d commands successfully extracted from %s to %s", n_json, used, json_output)
    return True


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(0 if rebuild_command_database_from_html(path) else 1)
