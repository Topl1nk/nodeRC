"""
diagnostics.py — Structured Exception Interception
Every failure surfaces a human-readable cause, not a raw code.
"""
from __future__ import annotations
import logging
import sys
import traceback

_logger = logging.getLogger("nodeRC")
_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.setFormatter(
    logging.Formatter("[%(levelname)s] %(name)s — %(message)s")
)
_logger.addHandler(_stream_handler)
_logger.setLevel(logging.DEBUG)


def install_global_exception_hook() -> None:
    """
    Wire Python's unhandled exception channel to the structured logger.
    Why: the default traceback dump gives no context; this routes everything
    through a single auditable channel from the very first import.
    """
    def _report_unhandled(exc_type, exc_value, exc_tb):
        _logger.critical(
            "Unhandled exception: %s\n%s",
            exc_value,
            "".join(traceback.format_tb(exc_tb)),
        )
    sys.excepthook = _report_unhandled


def log_and_explain(context: str, exc: Exception) -> str:
    """
    Log exc under context label and return a human-readable diagnosis string.
    Why: callers need one call site that both logs and produces UI-ready text,
    eliminating the risk of silent swallowing or duplicate logging.
    """
    diagnosis = f"{context}\n\nCause: {type(exc).__name__} — {exc}"
    _logger.error(diagnosis)
    return diagnosis
