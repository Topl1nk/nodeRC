"""Guards the repo's own packs/ folder against manifest drift.

Nothing in production code calls discover_packs() against this real
directory yet (that wiring is Phase 6) — so without this test, a broken
pack.json here would sit unnoticed until then. Ст.14.5: a criterion without
an executing check is an unfinished article.
"""
from pathlib import Path

from core.pack_registry import discover_packs

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BUNDLED_PACKS_DIR = REPO_ROOT / "packs"


def test_realityscan_pack_manifest_is_discoverable():
    packs = discover_packs([BUNDLED_PACKS_DIR])

    assert [p.manifest.pack_id for p in packs] == ["realityscan"]
    rc = packs[0]
    assert rc.manifest.display_name == "RealityScan"
    assert rc.manifest.declares.executable is True
    assert rc.pack_dir == BUNDLED_PACKS_DIR / "realityscan"


def test_realityscan_pack_entry_point_exists():
    """pack.json declares entry_point before core/pack_executor.py could
    launch anything (Phase 3 predates Phase 4) — now that both exist, a
    manifest pointing at a missing file must fail loudly, not sit unnoticed."""
    packs = discover_packs([BUNDLED_PACKS_DIR])
    rc = next(p for p in packs if p.manifest.pack_id == "realityscan")

    assert (rc.pack_dir / rc.manifest.entry_point).is_file()


def test_realityscan_pack_commands_source_matches_config():
    """pack.json's commands_source (relative — read generically by
    core/pack_catalog.py via pack_dir/commands_source) and
    packs/realityscan/config.py's COMMAND_DB_JSON (absolute — read
    directly by command_database.py) are two representations of the same
    file. They must resolve to the same path, or a future executor reading
    one while the catalog builder writes the other would silently miss
    every command."""
    from packs.realityscan.config import COMMAND_DB_JSON

    packs = discover_packs([BUNDLED_PACKS_DIR])
    rc = next(p for p in packs if p.manifest.pack_id == "realityscan")

    assert (rc.pack_dir / rc.manifest.commands_source).resolve() == Path(COMMAND_DB_JSON).resolve()
