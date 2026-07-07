import json

from core.pack_catalog import flatten_commands, load_pack_catalog, merge_catalogs
from core.pack_protocol import PackDeclares, PackManifest
from core.pack_registry import InstalledPack

MANIFEST = PackManifest(
    pack_id="fake",
    display_name="Fake Pack",
    version="1.0.0",
    protocol_version=1,
    entry_point="entry.py",
    declares=PackDeclares(),
    commands_source="commands.json",
)

TREE_A = {"Section": {"Sub": [{"command": "-a"}]}}
TREE_B = {"Section": {"Sub": [{"command": "-b"}], "Other": [{"command": "-c"}]}}


def test_load_pack_catalog_reads_the_declared_file(tmp_path):
    (tmp_path / "commands.json").write_text(json.dumps(TREE_A), encoding="utf-8")
    installed = InstalledPack(manifest=MANIFEST, pack_dir=tmp_path)

    assert load_pack_catalog(installed) == TREE_A


def test_load_pack_catalog_returns_empty_when_file_missing(tmp_path):
    installed = InstalledPack(manifest=MANIFEST, pack_dir=tmp_path)
    assert load_pack_catalog(installed) == {}


def test_load_pack_catalog_returns_empty_when_no_commands_source(tmp_path):
    manifest = PackManifest(
        pack_id="fake", display_name="Fake", version="1.0.0", protocol_version=1,
        entry_point="entry.py", declares=PackDeclares(), commands_source=None,
    )
    installed = InstalledPack(manifest=manifest, pack_dir=tmp_path)
    assert load_pack_catalog(installed) == {}


def test_load_pack_catalog_returns_empty_on_malformed_json(tmp_path):
    (tmp_path / "commands.json").write_text("not json", encoding="utf-8")
    installed = InstalledPack(manifest=MANIFEST, pack_dir=tmp_path)
    assert load_pack_catalog(installed) == {}


def test_merge_catalogs_combines_subsections_under_a_shared_section():
    merged = merge_catalogs(TREE_A, TREE_B)

    assert merged == {
        "Section": {"Sub": [{"command": "-a"}, {"command": "-b"}], "Other": [{"command": "-c"}]}
    }


def test_merge_catalogs_with_no_trees_is_empty():
    assert merge_catalogs() == {}


def test_flatten_commands_lists_every_command_across_sections():
    commands = flatten_commands(TREE_B)
    assert commands == [{"command": "-b"}, {"command": "-c"}]
