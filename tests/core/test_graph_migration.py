import json
from pathlib import Path
from core.graph_model import GraphModel

def test_v1_migration_and_frozen_nodes():
    fixture_path = Path(__file__).parent.parent / "fixtures" / "graph_format" / "v1_sample.json"
    with open(fixture_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    # test migration mechanism which is called inside from_dict
    graph = GraphModel.from_dict(payload)
    
    assert graph.version == 1
    assert len(graph.nodes) == 2
    
    start_node = graph.node_by_uid("n1")
    assert start_node.node_type == "StartNode"
    assert start_node.is_frozen is False
    
    unknown_node = graph.node_by_uid("n2")
    assert unknown_node.node_type == "NonexistentCommand"
    assert unknown_node.is_frozen is True
    assert unknown_node.cmd_def == {"command": "-unknown"}
    
    # ensure it roundtrips back without losing is_frozen or cmd_def
    out_payload = graph.to_dict()
    out_unknown = next(n for n in out_payload["nodes"] if n["id"] == "n2")
    assert out_unknown["is_frozen"] is True
    assert out_unknown["cmd_def"] == {"command": "-unknown"}
