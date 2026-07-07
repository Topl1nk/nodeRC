import sys
import pytest

def pytest_sessionfinish(session, exitstatus):
    """
    Ensure that when only core tests are run, no Qt or UI modules are ever imported.
    If the suite mixes core and ui tests, Qt will be in sys.modules from the UI tests,
    so we only enforce this strictly when running the core test directory directly.
    """
    # Check if the user specifically asked to run tests/core (or a subset within it)
    running_only_core = all("core" in str(arg) for arg in session.config.args)
    if running_only_core:
        bad_modules = [
            m for m in sys.modules 
            if m.startswith('PyQt') or m.startswith('ui.')
        ]
        if bad_modules:
            print(f"\nFATAL: tests/core pulled in UI/Qt modules: {bad_modules}", file=sys.stderr)
            session.exitstatus = 1
