"""Timeout-case sample project for FixPilot AI.

The test deliberately sleeps for longer than the configured timeout so the
sandbox executor has to terminate it and report a timeout rather than a
test failure.
"""

import time


def test_sleeps_too_long():
    """This test exceeds the configured execution timeout."""
    time.sleep(30)
    assert True
