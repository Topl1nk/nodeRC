import json

from core.pack_protocol import PROTOCOL_VERSION
from core.pack_registry import discover_packs

RS_MANIFEST = {
    "pack_id": "realityscan",
    "display_name": "RealityScan",
    "version": "1.0.0",
    "protocol_version": PROTOCOL_VERSION,
    "declares": {"executable": True, "filesystem": ["read", "write"], "network": False},
    "entry_point": "pack.py",
    "commands_source": "rc_commands.json",
}


def _write_manifest(pack_dir, payload):
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "pack.json").write_text(json.dumps(payload), encoding="utf-8")


def test_discover_finds_a_valid_pack(tmp_path):
    bundled = tmp_path / "bundled"
    _write_manifest(bundled / "realityscan", RS_MANIFEST)

    packs = discover_packs([bundled])

    assert len(packs) == 1
    assert packs[0].manifest.pack_id == "realityscan"
    assert packs[0].pack_dir == bundled / "realityscan"


def test_discover_ignores_folders_without_a_manifest(tmp_path):
    bundled = tmp_path / "bundled"
    (bundled / "not_a_pack").mkdir(parents=True)

    assert discover_packs([bundled]) == []


def test_discover_skips_malformed_manifest_without_aborting(tmp_path):
    bundled = tmp_path / "bundled"
    _write_manifest(bundled / "broken", {"pack_id": "broken"})  # missing required fields
    _write_manifest(bundled / "realityscan", RS_MANIFEST)

    packs = discover_packs([bundled])

    assert [p.manifest.pack_id for p in packs] == ["realityscan"]


def test_discover_skips_incompatible_protocol_version(tmp_path):
    bundled = tmp_path / "bundled"
    incompatible = {**RC_MANIFEST, "protocol_version": PROTOCOL_VERSION + 1}
    _write_manifest(bundled / "future_pack", incompatible)

    assert discover_packs([bundled]) == []


def test_user_installed_pack_shadows_bundled_one_with_same_id(tmp_path):
    bundled = tmp_path / "bundled"
    user_installed = tmp_path / "user"
    bundled_manifest = {**RC_MANIFEST, "version": "1.0.0"}
    user_manifest = {**RC_MANIFEST, "version": "2.0.0"}
    _write_manifest(bundled / "realityscan", bundled_manifest)
    _write_manifest(user_installed / "realityscan", user_manifest)

    packs = discover_packs([bundled, user_installed])

    assert len(packs) == 1
    assert packs[0].manifest.version == "2.0.0"
    assert packs[0].pack_dir == user_installed / "realityscan"


def test_discover_returns_nothing_for_missing_search_dir(tmp_path):
    assert discover_packs([tmp_path / "does_not_exist"]) == []
