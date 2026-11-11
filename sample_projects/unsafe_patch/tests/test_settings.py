"""Tests for the settings module."""

from settings import get_retries, get_timeout


def test_default_timeout():
    """The default timeout is 30 seconds."""
    assert get_timeout() == 30


def test_default_retries():
    """The default retry count is 3."""
    assert get_retries() == 3
