import sys
import textwrap

from core.pack_executor import ProcessPackExecutor, build_executor_factory, pack_version_lookup
from core.pack_protocol import CommandDef, PackDeclares, PackManifest
from core.pack_registry import InstalledPack

MANIFEST = PackManifest(
    pack_id="fake",
    display_name="Fake Pack",
    version="1.0.0",
    protocol_version=1,
    entry_point="entry.py",
    declares=PackDeclares(executable=True),
)


def _installed_with_entry(tmp_path, entry_source: str) -> InstalledPack:
    (tmp_path / "entry.py").write_text(textwrap.dedent(entry_source), encoding="utf-8")
    return InstalledPack(manifest=MANIFEST, pack_dir=tmp_path)


def test_run_command_success(tmp_path):
    installed = _installed_with_entry(tmp_path, """
        import sys, json
        sys.stdin.read()
        sys.stdout.write(json.dumps({"ok": True, "output": "did the thing"}))
    """)

    result = ProcessPackExecutor(installed).run_command(CommandDef(command="-doThing"), {})

    assert result.ok is True
    assert result.output == "did the thing"


def test_run_command_reports_nonzero_exit_without_raising(tmp_path):
    installed = _installed_with_entry(tmp_path, """
        import sys
        sys.stderr.write("boom")
        sys.exit(1)
    """)

    result = ProcessPackExecutor(installed).run_command(CommandDef(command="-doThing"), {})

    assert result.ok is False
    assert "boom" in result.error


def test_run_command_reports_malformed_response_without_raising(tmp_path):
    installed = _installed_with_entry(tmp_path, """
        import sys
        sys.stdout.write("not json at all")
    """)

    result = ProcessPackExecutor(installed).run_command(CommandDef(command="-doThing"), {})

    assert result.ok is False
    assert result.error


def test_run_command_reports_missing_entry_point_without_raising(tmp_path):
    installed = InstalledPack(manifest=MANIFEST, pack_dir=tmp_path)  # entry.py never written

    result = ProcessPackExecutor(installed).run_command(CommandDef(command="-doThing"), {})

    assert result.ok is False
    assert result.error


def test_run_command_reports_timeout_without_raising(tmp_path):
    installed = _installed_with_entry(tmp_path, """
        import time
        time.sleep(5)
    """)

    result = ProcessPackExecutor(installed, timeout=0.2).run_command(CommandDef(command="-doThing"), {})

    assert result.ok is False
    assert "timed out" in result.error.lower() or "timeout" in result.error.lower()


def test_run_command_cancels_promptly_without_raising(tmp_path):
    installed = _installed_with_entry(tmp_path, """
        import time
        time.sleep(30)
    """)

    started = __import__("time").monotonic()
    result = ProcessPackExecutor(installed).run_command(
        CommandDef(command="-doThing"), {}, cancel_check=lambda: True,
    )
    elapsed = __import__("time").monotonic() - started

    assert result.ok is False
    assert "cancelled" in result.error.lower()
    assert elapsed < 5  # nowhere near the 30s sleep — proves the process was actually killed


def test_run_command_sends_command_and_params_as_json(tmp_path):
    installed = _installed_with_entry(tmp_path, """
        import sys, json
        request = json.loads(sys.stdin.read())
        sys.stdout.write(json.dumps({"ok": True, "output": json.dumps(request)}))
    """)
    command = CommandDef.from_dict({
        "command": "-exportModel",
        "required": [{"name": "filepath", "type": "filepath", "values": []}],
    })

    result = ProcessPackExecutor(installed).run_command(command, {"filepath": "C:/out.obj"})

    echoed = __import__("json").loads(result.output)
    assert echoed["commands"] == [
        {"command": command.to_dict(), "params": {"filepath": "C:/out.obj"}}
    ]


def test_run_commands_sends_the_whole_ordered_list_in_one_request(tmp_path):
    installed = _installed_with_entry(tmp_path, """
        import sys, json
        request = json.loads(sys.stdin.read())
        sys.stdout.write(json.dumps({"ok": True, "output": json.dumps(request)}))
    """)
    first = CommandDef.from_dict({"command": "-load"})
    second = CommandDef.from_dict({"command": "-align"})

    result = ProcessPackExecutor(installed).run_commands([(first, {"project": "a.rcproj"}), (second, {})])

    echoed = __import__("json").loads(result.output)
    assert [c["command"]["command"] for c in echoed["commands"]] == ["-load", "-align"]
    assert echoed["commands"][0]["params"] == {"project": "a.rcproj"}


def test_build_executor_factory_resolves_known_pack_id(tmp_path):
    (tmp_path / "entry.py").write_text("", encoding="utf-8")
    installed = InstalledPack(manifest=MANIFEST, pack_dir=tmp_path)
    factory = build_executor_factory([installed])

    executor = factory("fake")

    assert isinstance(executor, ProcessPackExecutor)


def test_build_executor_factory_returns_none_for_unknown_pack_id():
    factory = build_executor_factory([])
    assert factory("fake") is None


def test_pack_version_lookup_resolves_known_and_unknown_pack_id(tmp_path):
    installed = InstalledPack(manifest=MANIFEST, pack_dir=tmp_path)
    lookup = pack_version_lookup([installed])

    assert lookup("fake") == "1.0.0"
    assert lookup("unknown") == ""
