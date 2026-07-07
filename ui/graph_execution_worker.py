"""graph_execution_worker.py — Running GraphExecutor Off the UI Thread

core/graph_executor.py's execute() blocks until every pack process it drives
exits — for RC that can be hours. GraphExecutionWorker runs it on a QThread
so the editor stays responsive, and signals the result back to whichever
slot the window connects. cancel_event is the one thing the UI thread is
allowed to touch on this object while the worker thread is running (setting
an Event is thread-safe by design) — everything else about the run stays on
the worker thread.
"""
from __future__ import annotations

import threading
from typing import List

from PyQt5.QtCore import QObject, pyqtSignal

from core.graph_executor import GraphExecutor, SegmentRun
from core.graph_model import GraphModel


class GraphExecutionWorker(QObject):
    finished = pyqtSignal(list)      # List[SegmentRun]
    failed = pyqtSignal(Exception)

    def __init__(self, graph_executor: GraphExecutor, graph: GraphModel):
        super().__init__()
        self._graph_executor = graph_executor
        self._graph = graph
        self.cancel_event = threading.Event()

    def run(self) -> None:
        try:
            runs: List[SegmentRun] = self._graph_executor.execute(
                self._graph, cancel_check=self.cancel_event.is_set,
            )
        except Exception as exc:  # noqa: BLE001 — the whole point is to never propagate into the QThread
            self.failed.emit(exc)
            return
        self.finished.emit(runs)
