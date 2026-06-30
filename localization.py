"""Runtime translation layer for the NodeRC UI.

The translatable strings live as standard GNU gettext catalogs under ``locale/``
(``nodeRC.pot`` template + one ``<lang>/LC_MESSAGES/nodeRC.po`` per language), the
format every translation service — Crowdin, Weblate, Transifex, Poedit — speaks.
This module is the only thing the UI imports: it resolves a catalog for the active
language, falls back to English for any untranslated key, and exposes ``t(key)``.

Why compile in memory: the ``.po`` files are the single source of truth. We build
their binary ``.mo`` image in RAM at load time, so there is never a stale or
missing ``.mo`` to keep in sync, and nothing is written into a read-only install
dir. ``tools/compile_translations.py`` can still emit ``.mo`` files for external
gettext consumers, reusing the exact functions below.
"""
from __future__ import annotations

import gettext
import io
import locale as _system_locale
import os
import struct
from pathlib import Path
from typing import Dict, List, Optional

DOMAIN = "nodeRC"
LOCALE_DIR = Path(__file__).resolve().parent / "locale"
DEFAULT_LANGUAGE = "en"  # source language; the fallback for every other catalog

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}


# ── gettext PO/MO codec (shared with tools/compile_translations.py) ─────────────

def _unquote(literal: str) -> str:
    body = literal[literal.index('"') + 1:literal.rindex('"')]
    out: List[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            out.append(_ESCAPES.get(body[i + 1], body[i + 1]))
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def parse_po(text: str) -> Dict[str, str]:
    """Parse PO source into a {msgid: msgstr} catalog (msgctxt folded into the key).

    Untranslated entries (empty msgstr) are dropped so gettext falls through to the
    fallback chain — except the header entry (msgid "") that carries the metadata.
    """
    catalog: Dict[str, str] = {}
    ctxt: Optional[str] = None
    msgid: Optional[str] = None
    msgstr: Optional[str] = None
    field: Optional[str] = None

    def flush() -> None:
        if msgid is not None and (msgstr or msgid == ""):
            key = f"{ctxt}\x04{msgid}" if ctxt else msgid
            catalog[key] = msgstr or ""

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            if not line and msgid is not None:
                flush()
                ctxt = msgid = msgstr = field = None
            continue
        if line.startswith("msgctxt "):
            ctxt, field = _unquote(line[8:]), "ctxt"
        elif line.startswith("msgid_plural "):
            field = None
        elif line.startswith("msgid "):
            if msgstr is not None:
                flush()
                ctxt = msgstr = None
            msgid, field = _unquote(line[6:]), "msgid"
        elif line.startswith("msgstr"):
            head = line.split(" ", 1)
            msgstr = _unquote(head[1]) if len(head) > 1 else ""
            field = "msgstr"
        elif line.startswith('"'):
            piece = _unquote(line)
            if field == "msgid":
                msgid = (msgid or "") + piece
            elif field == "msgstr":
                msgstr = (msgstr or "") + piece
            elif field == "ctxt":
                ctxt = (ctxt or "") + piece
    flush()
    return catalog


def generate_mo(catalog: Dict[str, str]) -> bytes:
    """Serialize a catalog to the little-endian GNU MO binary format."""
    keys = sorted(catalog.keys())
    ids = b""
    strs = b""
    offsets = []
    for key in keys:
        kb = key.encode("utf-8")
        vb = catalog[key].encode("utf-8")
        offsets.append((len(ids), len(kb), len(strs), len(vb)))
        ids += kb + b"\x00"
        strs += vb + b"\x00"

    key_table = 7 * 4 + 16 * len(keys)
    value_table = key_table + len(ids)
    key_offsets: List[int] = []
    value_offsets: List[int] = []
    for id_off, id_len, str_off, str_len in offsets:
        key_offsets += [id_len, id_off + key_table]
        value_offsets += [str_len, str_off + value_table]

    out = struct.pack("Iiiiiii", 0x950412DE, 0, len(keys),
                      7 * 4, 7 * 4 + len(keys) * 8, 0, 0)
    out += struct.pack("i" * len(key_offsets), *key_offsets)
    out += struct.pack("i" * len(value_offsets), *value_offsets)
    return out + ids + strs


# ── Catalog discovery and activation ────────────────────────────────────────────

def _po_path(lang: str) -> Path:
    return LOCALE_DIR / lang / "LC_MESSAGES" / f"{DOMAIN}.po"


def available_languages() -> List[str]:
    """Languages with a catalog on disk, default language first."""
    if not LOCALE_DIR.exists():
        return [DEFAULT_LANGUAGE]
    langs = sorted(p.parent.parent.name for p in LOCALE_DIR.glob(f"*/LC_MESSAGES/{DOMAIN}.po"))
    langs = [l for l in langs if l != "ru"]
    if DEFAULT_LANGUAGE in langs:
        langs.remove(DEFAULT_LANGUAGE)
        langs.insert(0, DEFAULT_LANGUAGE)
    return langs or [DEFAULT_LANGUAGE]


def _build_translation(lang: str) -> Optional[gettext.NullTranslations]:
    po = _po_path(lang)
    if not po.exists():
        return None
    try:
        catalog = parse_po(po.read_text(encoding="utf-8"))
        return gettext.GNUTranslations(io.BytesIO(generate_mo(catalog)))
    except Exception:
        # A malformed catalog must never crash the editor; fall through to English.
        return None


def detect_language() -> str:
    """Preferred UI language: NODERC_LANG env, then OS locale, then English."""
    env = os.environ.get("NODERC_LANG")
    available = available_languages()
    if env and env in available:
        return env
    try:
        code = _system_locale.getdefaultlocale()[0]
    except Exception:
        code = None
    if code:
        short = code.split("_")[0].lower()
        if short in available:
            return short
    return DEFAULT_LANGUAGE


_active: gettext.NullTranslations = gettext.NullTranslations()
CURRENT_LANG: str = DEFAULT_LANGUAGE  # kept in sync for callers that read it


def set_language(lang: str) -> None:
    """Activate ``lang`` for subsequent ``t()`` lookups, English-backed."""
    global _active, CURRENT_LANG
    base = _build_translation(DEFAULT_LANGUAGE) or gettext.NullTranslations()
    if lang == DEFAULT_LANGUAGE:
        active = base
    else:
        active = _build_translation(lang)
        if active is None:
            active = base
        else:
            active.add_fallback(base)
    _active = active
    CURRENT_LANG = lang


def get_language() -> str:
    return CURRENT_LANG


def t(key: str) -> str:
    """Translate a symbolic UI key for the active language (English fallback)."""
    return _active.gettext(key)


_po_catalogs_cache: Dict[str, Dict[str, str]] = {}


def get_all_translations(key: str) -> List[str]:
    """Get all translated values for a given key across all available PO catalogs.

    Why: Used to detect if a node's display name is a default (translatable) value
    in any known language.
    """
    results = [key]
    for lang in available_languages():
        if lang not in _po_catalogs_cache:
            po = _po_path(lang)
            if po.exists():
                try:
                    _po_catalogs_cache[lang] = parse_po(po.read_text(encoding="utf-8"))
                except Exception:
                    pass
        catalog = _po_catalogs_cache.get(lang)
        if catalog and key in catalog:
            val = catalog[key]
            if val:
                results.append(val)
    return list(set(results))


set_language(detect_language())
