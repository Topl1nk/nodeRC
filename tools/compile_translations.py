"""Compile gettext ``.po`` catalogs into binary ``.mo`` files.

The app itself does **not** need these — ``localization.py`` builds the binary
image in memory at startup. This tool exists for external gettext consumers and
for shipping pre-compiled catalogs: it reuses the exact PO parser and MO writer
from ``localization`` so the output is identical to what the app loads.

    python tools/compile_translations.py            # compile every locale/**/*.po
    python tools/compile_translations.py ru          # only one language

For plural-form messages or fuzzy review, GNU ``msgfmt`` or ``babel`` produce
identical ``.mo`` output; this covers the singular-key catalogs NodeRC ships.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from localization import DOMAIN, LOCALE_DIR, generate_mo, parse_po  # noqa: E402


def compile_po(po_path: Path) -> int:
    catalog = parse_po(po_path.read_text(encoding="utf-8"))
    po_path.with_suffix(".mo").write_bytes(generate_mo(catalog))
    return len(catalog)


def main(argv: list[str]) -> int:
    wanted = set(argv)
    po_files = sorted(LOCALE_DIR.glob(f"*/LC_MESSAGES/{DOMAIN}.po"))
    if not po_files:
        print(f"No .po files under {LOCALE_DIR}", file=sys.stderr)
        return 1
    compiled = 0
    for po in po_files:
        lang = po.parent.parent.name
        if wanted and lang not in wanted:
            continue
        count = compile_po(po)
        print(f"{lang}: {po.relative_to(LOCALE_DIR.parent)} -> {po.stem}.mo ({count} messages)")
        compiled += 1
    if not compiled:
        print("Nothing compiled (no matching languages).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
