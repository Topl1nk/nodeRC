from core.graph_executor import (
    GraphExecutor,
    _resolved_params_for_node,
    build_exec_chain,
    segment_chain_by_pack,
)
from core.graph_model import ConnectionModel, GraphModel, NodeModel
from core.pack_protocol import CommandDef, ExecutionResult, PackExecutor

EXPORT_CMD_DEF = {
    "command": "-exportModel", "display": "Export Model",
    "required": [{"name": "filepath", "type": "filepath", "values": []},
                 {"name": "filepath", "type": "filepath", "values": []}],
    "optional": [],
}


def _exec_conn(src_uid, dst_uid):
    return ConnectionModel(src_node_uid=src_uid, src_socket="exec_out",
                            dst_node_uid=dst_uid, dst_socket="__exec_in__")


class FakeExecutor(PackExecutor):
    def __init__(self, result: ExecutionResult):
        self.result = result
        self.calls = []
        self.received_cancel_checks = []

    def run_commands(self, commands, *, cancel_check=None):
        self.calls.append(commands)
        self.received_cancel_checks.append(cancel_check)
        return self.result


# ── build_exec_chain ────────────────────────────────────────────────────────

def test_build_exec_chain_follows_exec_wires_in_order():
    graph = GraphModel(nodes=[
        NodeModel(uid="start", node_type="StartNode", x=0, y=0),
        NodeModel(uid="a", node_type="CommandNode", x=0, y=0, cmd_def={"command": "-load"}),
        NodeModel(uid="b", node_type="CommandNode", x=0, y=0, cmd_def={"command": "-align"}),
    ], connections=[_exec_conn("start", "a"), _exec_conn("a", "b")])

    chain = build_exec_chain(graph)

    assert [n.uid for n in chain] == ["start", "a", "b"]


def test_build_exec_chain_returns_none_without_a_start_node():
    graph = GraphModel(nodes=[NodeModel(uid="a", node_type="CommandNode", x=0, y=0)])
    assert build_exec_chain(graph) is None


def test_build_exec_chain_stops_at_a_cycle_instead_of_hanging():
    graph = GraphModel(nodes=[
        NodeModel(uid="start", node_type="StartNode", x=0, y=0),
        NodeModel(uid="a", node_type="CommandNode", x=0, y=0, cmd_def={"command": "-load"}),
    ], connections=[_exec_conn("start", "a"), _exec_conn("a", "start")])

    chain = build_exec_chain(graph)

    assert [n.uid for n in chain] == ["start", "a"]


# ── segmentation ─────────────────────────────────────────────────────────────

def test_segment_chain_by_pack_groups_consecutive_command_nodes():
    chain = [
        NodeModel(uid="start", node_type="StartNode", x=0, y=0),
        NodeModel(uid="a", node_type="CommandNode", x=0, y=0, cmd_def={"command": "-load"}),
        NodeModel(uid="b", node_type="CommandNode", x=0, y=0, cmd_def={"command": "-align"}),
    ]

    segments = segment_chain_by_pack(chain)

    assert len(segments) == 1
    assert segments[0].pack_id == "realitycapture"
    assert [n.uid for n in segments[0].nodes] == ["a", "b"]


def test_segment_chain_by_pack_ignores_nodes_without_cmd_def():
    chain = [NodeModel(uid="start", node_type="StartNode", x=0, y=0)]
    assert segment_chain_by_pack(chain) == []


# ── param resolution (moved from tests/ui/test_characterization.py) ────────

def test_resolved_params_for_node_handles_duplicate_named_inputs_independently():
    graph = GraphModel(
        nodes=[
            NodeModel(uid="cmd", node_type="CommandNode", x=100, y=0, cmd_def=EXPORT_CMD_DEF),
            NodeModel(uid="a", node_type="StringParamNode", x=-100, y=0,
                      socket_values={"value_out": "C:/first.obj"}),
            NodeModel(uid="b", node_type="StringParamNode", x=-100, y=100,
                      socket_values={"value_out": "C:/second.obj"}),
        ],
        connections=[
            ConnectionModel(src_node_uid="a", src_socket="value_out",
                             dst_node_uid="cmd", dst_socket="filepath"),
            ConnectionModel(src_node_uid="b", src_socket="value_out",
                             dst_node_uid="cmd", dst_socket="filepath_2"),
        ],
    )
    cmd_node = graph.node_by_uid("cmd")
    command = CommandDef.from_dict(EXPORT_CMD_DEF)

    params = _resolved_params_for_node(graph, cmd_node, command)

    assert params == {"filepath": "C:/first.obj", "filepath_2": "C:/second.obj"}


# ── GraphExecutor ────────────────────────────────────────────────────────────

def _simple_graph(filepath_value="C:/out.obj"):
    return GraphModel(
        nodes=[
            NodeModel(uid="start", node_type="StartNode", x=0, y=0),
            NodeModel(uid="cmd", node_type="CommandNode", x=100, y=0, cmd_def={
                "command": "-exportModel",
                "required": [{"name": "filepath", "type": "filepath", "values": []}],
                "optional": [],
            }),
            NodeModel(uid="a", node_type="StringParamNode", x=-100, y=0,
                      socket_values={"value_out": filepath_value}),
        ],
        connections=[
            _exec_conn("start", "cmd"),
            ConnectionModel(src_node_uid="a", src_socket="value_out",
                             dst_node_uid="cmd", dst_socket="filepath"),
        ],
    )


def _executor_factory(fake):
    return lambda pack_id: fake if pack_id == "realitycapture" else None


def test_execute_runs_one_segment_and_reports_success():
    fake = FakeExecutor(ExecutionResult(ok=True, output="done"))
    executor = GraphExecutor(_executor_factory(fake), pack_version_for=lambda _: "1.0.0")

    runs = executor.execute(_simple_graph())

    assert len(runs) == 1
    assert runs[0].pack_id == "realitycapture"
    assert runs[0].result.ok is True
    assert runs[0].cache_hit is False
    assert len(fake.calls) == 1


def test_execute_never_caches_a_pack_that_did_not_opt_in():
    """The bug this guards against: a pack that launches an interactive
    program (RealityCapture's own window) must run again on every Launch
    click, even with an identical graph — treating "unchanged inputs" as
    "safe to skip" is only true for a pure batch computation. Default
    (no is_pack_cacheable given) must behave the same as an explicit
    cacheable=False manifest."""
    fake = FakeExecutor(ExecutionResult(ok=True, output="done"))
    executor = GraphExecutor(_executor_factory(fake), pack_version_for=lambda _: "1.0.0")
    graph = _simple_graph()

    executor.execute(graph)
    runs = executor.execute(graph)

    assert runs[0].cache_hit is False
    assert len(fake.calls) == 2  # ran again both times, not served from cache


def test_execute_serves_unchanged_segment_from_cache_on_second_run():
    fake = FakeExecutor(ExecutionResult(ok=True, output="done"))
    executor = GraphExecutor(_executor_factory(fake), pack_version_for=lambda _: "1.0.0",
                              is_pack_cacheable=lambda _: True)
    graph = _simple_graph()

    executor.execute(graph)
    runs = executor.execute(graph)

    assert runs[0].cache_hit is True
    assert len(fake.calls) == 1  # not called again


def test_execute_recomputes_when_resolved_input_changes():
    fake = FakeExecutor(ExecutionResult(ok=True, output="done"))
    executor = GraphExecutor(_executor_factory(fake), pack_version_for=lambda _: "1.0.0",
                              is_pack_cacheable=lambda _: True)

    executor.execute(_simple_graph("C:/out1.obj"))
    runs = executor.execute(_simple_graph("C:/out2.obj"))

    assert runs[0].cache_hit is False
    assert len(fake.calls) == 2


def test_execute_recomputes_when_pack_version_changes():
    fake = FakeExecutor(ExecutionResult(ok=True, output="done"))
    versions = {"v": "1.0.0"}
    executor = GraphExecutor(_executor_factory(fake), pack_version_for=lambda _: versions["v"],
                              is_pack_cacheable=lambda _: True)
    graph = _simple_graph()

    executor.execute(graph)
    versions["v"] = "2.0.0"
    runs = executor.execute(graph)

    assert runs[0].cache_hit is False
    assert len(fake.calls) == 2


def test_execute_does_not_cache_a_failed_segment():
    fake = FakeExecutor(ExecutionResult(ok=False, error="boom"))
    executor = GraphExecutor(_executor_factory(fake), pack_version_for=lambda _: "1.0.0",
                              is_pack_cacheable=lambda _: True)
    graph = _simple_graph()

    executor.execute(graph)
    runs = executor.execute(graph)

    assert runs[0].cache_hit is False
    assert len(fake.calls) == 2


def test_execute_reports_missing_pack_without_raising():
    executor = GraphExecutor(lambda pack_id: None, pack_version_for=lambda _: "1.0.0")

    runs = executor.execute(_simple_graph())

    assert runs[0].result.ok is False
    assert "realitycapture" in runs[0].result.error


def test_execute_stops_at_cancel_check_before_running_any_segment():
    fake = FakeExecutor(ExecutionResult(ok=True))
    executor = GraphExecutor(_executor_factory(fake), pack_version_for=lambda _: "1.0.0")

    runs = executor.execute(_simple_graph(), cancel_check=lambda: True)

    assert runs == []
    assert len(fake.calls) == 0


def test_execute_forwards_cancel_check_into_the_running_segment():
    """cancel_check must reach the pack executor itself, not just gate
    between segments — a segment that's a long RC job has to be killable
    mid-run (see core/pack_executor.py's poll loop)."""
    fake = FakeExecutor(ExecutionResult(ok=True))
    executor = GraphExecutor(_executor_factory(fake), pack_version_for=lambda _: "1.0.0")
    cancel_check = lambda: False

    executor.execute(_simple_graph(), cancel_check=cancel_check)

    assert fake.received_cancel_checks == [cancel_check]
