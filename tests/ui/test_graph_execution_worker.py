from ui.graph_execution_worker import GraphExecutionWorker


class FakeGraphExecutor:
    def __init__(self, runs=None, error: Exception = None):
        self._runs = runs or []
        self._error = error
        self.received_cancel_check = None

    def execute(self, graph, *, cancel_check=None):
        self.received_cancel_check = cancel_check
        if self._error:
            raise self._error
        return self._runs


def test_run_emits_finished_with_the_executor_result():
    fake = FakeGraphExecutor(runs=["a run"])
    worker = GraphExecutionWorker(fake, graph=object())
    received = []
    worker.finished.connect(received.append)

    worker.run()

    assert received == [["a run"]]


def test_run_emits_failed_instead_of_raising_when_executor_errors():
    fake = FakeGraphExecutor(error=RuntimeError("boom"))
    worker = GraphExecutionWorker(fake, graph=object())
    received = []
    worker.failed.connect(received.append)

    worker.run()  # must not raise

    assert len(received) == 1
    assert str(received[0]) == "boom"


def test_run_passes_cancel_event_is_set_as_cancel_check():
    fake = FakeGraphExecutor()
    worker = GraphExecutionWorker(fake, graph=object())

    worker.run()

    assert fake.received_cancel_check == worker.cancel_event.is_set
    assert fake.received_cancel_check() is False
    worker.cancel_event.set()
    assert fake.received_cancel_check() is True
