import pytest
from core.graph_model import GraphModel, NodeModel, ConnectionModel, GroupModel

def test_graph_model_round_trip():
    # Create synthetic graph
    original = GraphModel(
        version=1,
        nodes=[
            NodeModel(
                uid="n1", 
                node_type="StartNode", 
                x=10.5, 
                y=20.5,
                color="#FF0000",
                selected=True
            ),
            NodeModel(
                uid="n2",
                node_type="CommandNode",
                x=100.0,
                y=100.0,
                cmd_def={"name": "test_cmd"},
                expanded_vectors={"x", "y"}
            ),
            NodeModel(
                uid="n3",
                node_type="StringParamNode",
                x=200.0,
                y=200.0,
                creation_data={"param_type": "string", "display": "Test"},
                current_value="Hello",
                is_project_input=True
            )
        ],
        connections=[
            ConnectionModel(
                src_node_uid="n1",
                src_socket="exec_out",
                dst_node_uid="n2",
                dst_socket="exec_in",
                selected=False
            )
        ],
        groups=[
            GroupModel(
                title="Test Group",
                x=0.0,
                y=0.0,
                width=500.0,
                height=500.0,
                color="#00FF00",
                selected=True
            )
        ]
    )

    # Serialize
    payload = original.to_dict(include_selection=True)

    # Deserialize
    restored = GraphModel.from_dict(payload)

    assert restored.version == 1
    assert len(restored.nodes) == 3
    
    n1, n2, n3 = restored.nodes
    assert n1.uid == "n1"
    assert n1.node_type == "StartNode"
    assert n1.x == 10.5
    assert n1.y == 20.5
    assert n1.color == "#FF0000"
    assert n1.selected is True

    assert n2.uid == "n2"
    assert n2.node_type == "CommandNode"
    assert n2.cmd_def == {"name": "test_cmd"}
    assert n2.expanded_vectors == {"x", "y"}

    assert n3.uid == "n3"
    assert n3.node_type == "StringParamNode"
    assert n3.creation_data == {"param_type": "string", "display": "Test"}
    assert n3.current_value == "Hello"
    assert n3.is_project_input is True
    assert n1.is_project_input is False

    assert len(restored.connections) == 1
    c1 = restored.connections[0]
    assert c1.src_node_uid == "n1"
    assert c1.src_socket == "exec_out"
    assert c1.dst_node_uid == "n2"
    assert c1.dst_socket == "exec_in"

    assert len(restored.groups) == 1
    g1 = restored.groups[0]
    assert g1.title == "Test Group"
    assert g1.width == 500.0
    assert g1.color == "#00FF00"
    assert g1.selected is True

def test_graph_model_indices():
    # Test __post_init__ index building
    graph = GraphModel(
        version=1,
        nodes=[
            NodeModel(uid="n1", node_type="A", x=0, y=0),
            NodeModel(uid="n2", node_type="B", x=0, y=0)
        ],
        connections=[
            ConnectionModel(src_node_uid="n1", src_socket="out", dst_node_uid="n2", dst_socket="in")
        ],
        groups=[]
    )

    assert graph.node_by_uid("n1").node_type == "A"
    assert graph.node_by_uid("n2").node_type == "B"
    assert graph.node_by_uid("nx") is None

    out_conns = graph.connections_from("n1", "out")
    assert len(out_conns) == 1
    assert out_conns[0].dst_node_uid == "n2"

    in_conns = graph.connections_to("n2", "in")
    assert len(in_conns) == 1
    assert in_conns[0].src_node_uid == "n1"

def test_project_input_nodes_query():
    graph = GraphModel(
        nodes=[
            NodeModel(uid="n1", node_type="StringParamNode", x=0, y=0, is_project_input=True),
            NodeModel(uid="n2", node_type="IntParamNode", x=0, y=0),
            NodeModel(uid="n3", node_type="StringParamNode", x=0, y=0, is_project_input=True),
        ]
    )
    assert [n.uid for n in graph.project_input_nodes()] == ["n1", "n3"]

def test_node_model_from_dict_defaults_project_input_false():
    # A payload saved before this field existed must still load cleanly
    # (Доктрина II.1 — old graph files always open).
    node = NodeModel.from_dict({"id": "n1", "type": "StringParamNode", "x": 0, "y": 0})
    assert node.is_project_input is False
