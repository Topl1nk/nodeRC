import pytest

from core.pack_protocol import (
    CommandDef,
    ExecutionResult,
    PackDeclares,
    PackExecutor,
    PackManifest,
    PackManifestError,
    ParamDef,
    PROTOCOL_VERSION,
)

RC_MANIFEST_PAYLOAD = {
    "pack_id": "realitycapture",
    "display_name": "RealityCapture",
    "version": "1.0.0",
    "protocol_version": PROTOCOL_VERSION,
    "declares": {"executable": True, "filesystem": ["read", "write"], "network": False},
    "entry_point": "pack.py",
    "commands_source": "rc_commands.json",
    "cacheable": False,
}

RC_COMMAND_PAYLOAD = {
    "command": "-calculateQualityTexture",
    "display": "Calculate Quality Texture",
    "action": "calculate",
    "required": [{"name": "params.xml", "type": "filepath", "values": []}],
    "optional": [{"name": "true|false", "type": "bool", "values": ["true", "false"]}],
    "section": "Reconstruction",
    "subsection": None,
}


def test_pack_manifest_round_trip():
    manifest = PackManifest.from_dict(RC_MANIFEST_PAYLOAD)
    assert manifest.pack_id == "realitycapture"
    assert manifest.declares == PackDeclares(executable=True, filesystem=["read", "write"], network=False)
    assert manifest.to_dict() == RC_MANIFEST_PAYLOAD


def test_pack_manifest_missing_field_raises_explained_error():
    payload = {k: v for k, v in RC_MANIFEST_PAYLOAD.items() if k != "entry_point"}
    with pytest.raises(PackManifestError, match="entry_point"):
        PackManifest.from_dict(payload)


def test_pack_manifest_declares_defaults_when_absent():
    payload = {k: v for k, v in RC_MANIFEST_PAYLOAD.items() if k != "declares"}
    manifest = PackManifest.from_dict(payload)
    assert manifest.declares == PackDeclares()


def test_pack_manifest_cacheable_defaults_to_false_when_absent():
    """A pack must opt in to caching, the same way it must opt in to
    filesystem/network access — an absent field is not implicitly safe."""
    payload = {k: v for k, v in RC_MANIFEST_PAYLOAD.items() if k != "cacheable"}
    manifest = PackManifest.from_dict(payload)
    assert manifest.cacheable is False


def test_check_protocol_compatible_accepts_matching_version():
    manifest = PackManifest.from_dict(RC_MANIFEST_PAYLOAD)
    manifest.check_protocol_compatible()  # must not raise


def test_check_protocol_compatible_rejects_mismatched_version():
    payload = {**RC_MANIFEST_PAYLOAD, "protocol_version": PROTOCOL_VERSION + 1}
    manifest = PackManifest.from_dict(payload)
    with pytest.raises(PackManifestError, match="protocol_version"):
        manifest.check_protocol_compatible()


def test_command_def_round_trip_matches_rc_documentation_extractor_shape():
    command = CommandDef.from_dict(RC_COMMAND_PAYLOAD)
    assert command.command == "-calculateQualityTexture"
    assert command.required == [ParamDef(name="params.xml", type="filepath", values=[])]
    assert command.optional == [ParamDef(name="true|false", type="bool", values=["true", "false"])]
    assert command.section == "Reconstruction"
    assert command.subsection is None

    out = command.to_dict()
    assert out["command"] == RC_COMMAND_PAYLOAD["command"]
    assert out["required"] == RC_COMMAND_PAYLOAD["required"]
    assert out["optional"] == RC_COMMAND_PAYLOAD["optional"]
    assert out["section"] == RC_COMMAND_PAYLOAD["section"]
    assert "subsection" not in out  # None is omitted, not written as null


def test_command_def_defaults_for_minimal_payload():
    command = CommandDef.from_dict({"command": "-quit"})
    assert command.required == []
    assert command.optional == []
    assert command.section is None


def test_pack_executor_is_an_abstract_contract():
    executor = PackExecutor()
    with pytest.raises(NotImplementedError):
        executor.run_command(CommandDef.from_dict({"command": "-quit"}), {})


def test_execution_result_is_a_plain_value():
    result = ExecutionResult(ok=True, output="done")
    assert result.ok is True
    assert result.error == ""
