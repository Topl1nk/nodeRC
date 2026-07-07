"""execute_chain()'s QThread wiring — proves the worker actually runs off
the caller's thread (execute_chain() returns before the executor result is
ready) and that the launch button flips back to "Launch" once it's done.
The chain-length gate and real graph resolution are covered elsewhere;
build_exec_chain is stubbed here so this test is only about the threading
plumbing.
"""
import time

from PyQt5.QtWidgets import QApplication

import ui.editor_window as editor_window_module
from localization import t
from ui.command_nodes import StartNode


def _pump_until(predicate, timeout_s=5.0):
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
    assert predicate(), "timed out waiting for the execution thread to finish"


class _FakeGraphExecutor:
    def __init__(self, runs, delay=0.05):
        self._runs = runs
        self._delay = delay
        self.received_cancel_check = None

    def execute(self, graph, *, cancel_check=None):
        self.received_cancel_check = cancel_check
        time.sleep(self._delay)
        return self._runs


def test_execute_chain_does_not_block_and_reenables_launch_button(window, monkeypatch):
    monkeypatch.setattr(editor_window_module, "build_exec_chain", lambda graph: ["start", "cmd"])
    fake_executor = _FakeGraphExecutor(runs=[])
    monkeypatch.setattr(window, "_graph_executor", fake_executor)
    start_node = next(i for i in window.scene.items() if isinstance(i, StartNode))
    assert start_node._launch_btn.text() == t("btn_launch")

    before = time.monotonic()
    window.execute_chain()
    elapsed = time.monotonic() - before

    assert elapsed < 0.05, "execute_chain() blocked the caller instead of handing off to a worker thread"
    assert start_node._launch_btn.text() == t("btn_cancel")
    assert start_node._launch_btn.isEnabled() is True  # stays clickable — that click is now Cancel

    _pump_until(lambda: window._execution_thread is None)

    assert start_node._launch_btn.text() == t("btn_launch")
    assert fake_executor.received_cancel_check is not None


def test_execute_chain_ignores_a_second_call_while_one_is_running(window, monkeypatch):
    monkeypatch.setattr(editor_window_module, "build_exec_chain", lambda graph: ["start", "cmd"])
    fake_executor = _FakeGraphExecutor(runs=[], delay=0.2)
    monkeypatch.setattr(window, "_graph_executor", fake_executor)

    window.execute_chain()
    first_thread = window._execution_thread
    window.execute_chain()  # should no-op — a worker slot is already in use

    assert window._execution_thread is first_thread
    _pump_until(lambda: window._execution_thread is None)


def test_clicking_the_launch_button_while_running_cancels_instead_of_relaunching(window, monkeypatch):
    """The exact scenario that motivated the toggle: a pack process that
    never exits on its own (RC not actually terminating when its own
    window closes, say) must not leave the chain permanently stuck — the
    same button the user already knows has to be able to get them out."""
    monkeypatch.setattr(editor_window_module, "build_exec_chain", lambda graph: ["start", "cmd"])
    fake_executor = _FakeGraphExecutor(runs=[], delay=0.2)
    monkeypatch.setattr(window, "_graph_executor", fake_executor)
    start_node = next(i for i in window.scene.items() if isinstance(i, StartNode))

    start_node._launch_btn.click()
    worker = window._execution_worker
    assert worker is not None

    start_node._launch_btn.click()  # same button, now showing "Cancel"

    assert worker.cancel_event.is_set()
    _pump_until(lambda: window._execution_thread is None)
    assert start_node._launch_btn.text() == t("btn_launch")


def test_cancel_chain_execution_sets_the_worker_cancel_event(window, monkeypatch):
    monkeypatch.setattr(editor_window_module, "build_exec_chain", lambda graph: ["start", "cmd"])
    fake_executor = _FakeGraphExecutor(runs=[], delay=0.2)
    monkeypatch.setattr(window, "_graph_executor", fake_executor)

    window.execute_chain()
    worker = window._execution_worker
    window.cancel_chain_execution()

    assert worker.cancel_event.is_set()
    _pump_until(lambda: window._execution_thread is None)
