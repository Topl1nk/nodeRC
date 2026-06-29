"""
rc_documentation_extractor.py — RealityCapture HTML Documentation Parser
Parses allcommands.htm and writes:
  • rc_commands.json — rich format with categories, display names, typed params
  • rc_commands.txt  — legacy flat format for backward compatibility

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
from typing import Dict, List, Optional, Set

from configuration import RC_HELP_HTML, COMMAND_DB_JSON

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
    if any(lower.endswith(x) or lower == x for x in (
        "x", "y", "z", "distance", "focallength", "yaw", "pitch", "roll", 
        "offsetx", "offsety", "offsetz", "movex", "movey", "movez",
        "scalex", "scaley", "scalez", "errorvalue", "heightvalue",
        "upx", "upy", "upz", "step", "axis", "number", "size"
    )):
        return "float"
    if any(lower.endswith(x) or lower == x for x in (
        "count", "length", "index", "threshold"
    )):
        return "integer"
    if any(lower.endswith(x) or lower == x for x in (
        ".xml", ".rcproj", ".rsproj", ".abc", ".obj", ".las", ".laz",
        ".rscmd", ".rsbox", ".rsalign", ".cmi",
        "file", "filepath", "rsboxfile", "rsorthofile", "filename", "file path",
        "xmlfilepath", "cpmfilename", "flfilename", "gcpfilename", "orthoname", "modelname", "shapename", "contoursname", "crosssectionsname", "layername"
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


def _build_param_record(raw_token: str) -> dict:
    ptype = _infer_param_type(raw_token)
    name = raw_token
    lower_name = name.lower()
    
    # Semantic Renaming
    if ptype == "filepath":
        if ".xml" in lower_name: name = "xml_file"
        elif ".rsproj" in lower_name or ".rcproj" in lower_name: name = "project_file"
        elif ".rscmd" in lower_name: name = "command_file"
        elif "list" in lower_name: name = "list_file"
        elif "folder" in lower_name or "dir" in lower_name:
            name = "dirpath"
            ptype = "dirpath"
        else: name = "filepath"
    elif ptype == "dirpath":
        name = "dirpath"
    elif ptype == "bool":
        name = "boolean"
    elif ptype == "keyvalue":
        name = "key_value"
    elif ptype in ("enum", "enum_int"):
        if "union" in lower_name and "sub" in lower_name:
            name = "selection_mode"
        else:
            name = "choice"

    return {
        "name":   name,
        "type":   ptype,
        "values": [v.strip() for v in raw_token.split("|")] if ptype in ("enum", "enum_int") else [],
    }


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


# ── Writers ────────────────────────────────────────────────────────────────────

def _write_json_database(categories: CommandCategoryTree, path: str) -> int:
    total = sum(len(c) for s in categories.values() for c in s.values())
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(categories, fh, indent=2, ensure_ascii=False)
    return total


# ── Public API ─────────────────────────────────────────────────────────────────

def rebuild_command_database_from_html(
    html_path: str      = RC_HELP_HTML,
    json_output: str    = COMMAND_DB_JSON,
) -> bool:
    """
    Parse html_path and write rich JSON output database.
    Returns True on success, False if html_path not found.
    """
    if not os.path.exists(html_path):
        _logger.warning("Documentation file not found: %s", html_path)
        return False

    with open(html_path, "r", encoding="utf-8", errors="replace") as fh:
        soup = BeautifulSoup(fh, "html.parser")

    categories = _extract_categories(soup)
    if not categories:
        _logger.warning("No commands found in documentation.")
        return False

    n_json = _write_json_database(categories, json_output)
    _logger.info("%d commands successfully extracted to %s", n_json, json_output)
    return True


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else RC_HELP_HTML
    sys.exit(0 if rebuild_command_database_from_html(path) else 1)
