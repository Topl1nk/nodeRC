from packs.realitycapture.config import RC_EXECUTABLE
from packs.realitycapture.rc_pack import build_command_tokens, run_request

COMMAND_PAYLOAD = {
    "command": "-exportModel",
    "required": [{"name": "filepath", "type": "filepath", "values": []}],
    "optional": [{"name": "offset", "type": "float3", "values": []}],
}


def test_build_command_tokens_skips_empty_params():
    tokens = build_command_tokens(COMMAND_PAYLOAD, {"filepath": "C:/out.obj"})
    assert tokens == ["-exportModel", "C:/out.obj"]


def test_build_command_tokens_splits_vector_values():
    tokens = build_command_tokens(
        COMMAND_PAYLOAD, {"filepath": "C:/out.obj", "offset": "1.0 2.0 3.0"}
    )
    assert tokens == ["-exportModel", "C:/out.obj", "1.0", "2.0", "3.0"]


def test_build_command_tokens_with_no_params_is_just_the_flag():
    assert build_command_tokens({"command": "-quit"}, {}) == ["-quit"]


def test_run_request_reports_success(monkeypatch):
    class FakeCompletedProcess:
        returncode = 0
        stdout = "RC finished"
        stderr = ""

    monkeypatch.setattr(
        "packs.realitycapture.rc_pack.subprocess.run",
        lambda *a, **k: FakeCompletedProcess(),
    )

    response = run_request({"commands": [{"command": {"command": "-quit"}, "params": {}}]})

    assert response == {"ok": True, "output": "RC finished", "error": ""}


def test_run_request_reports_nonzero_exit(monkeypatch):
    class FakeCompletedProcess:
        returncode = 1
        stdout = ""
        stderr = "RC could not find the input file"

    monkeypatch.setattr(
        "packs.realitycapture.rc_pack.subprocess.run",
        lambda *a, **k: FakeCompletedProcess(),
    )

    response = run_request({"commands": [{"command": {"command": "-quit"}, "params": {}}]})

    assert response["ok"] is False
    assert "could not find" in response["error"]


def test_run_request_reports_launch_failure(monkeypatch):
    def _raise(*a, **k):
        raise OSError("RealityCapture.exe not found")

    monkeypatch.setattr("packs.realitycapture.rc_pack.subprocess.run", _raise)

    response = run_request({"commands": [{"command": {"command": "-quit"}, "params": {}}]})

    assert response["ok"] is False
    assert "not found" in response["error"]


def test_run_request_launches_rc_once_with_every_command_concatenated(monkeypatch):
    """The whole point of the segment protocol: RC keeps a project loaded in
    memory across commands, so a segment of -load/-align/-exportModel must
    reach RC as one process invocation, not three."""
    captured_tokens = []

    class FakeCompletedProcess:
        returncode = 0
        stdout = "done"
        stderr = ""

    def _fake_run(tokens, **kwargs):
        captured_tokens.extend(tokens)
        return FakeCompletedProcess()

    monkeypatch.setattr("packs.realitycapture.rc_pack.subprocess.run", _fake_run)

    run_request({
        "commands": [
            {"command": {"command": "-load", "required": [{"name": "project", "type": "filepath"}]},
             "params": {"project": "a.rcproj"}},
            {"command": {"command": "-align"}, "params": {}},
            {"command": {"command": "-exportModel", "required": [{"name": "filepath", "type": "filepath"}]},
             "params": {"filepath": "out.obj"}},
        ]
    })

    assert captured_tokens == [
        RC_EXECUTABLE, "-load", "a.rcproj", "-align", "-exportModel", "out.obj",
    ]
