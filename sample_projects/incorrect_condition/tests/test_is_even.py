"""Tests for the is_even function."""

from is_even import is_even


def test_even_numbers():
    """Even numbers are detected."""
    assert is_even(4) is True
    assert is_even(0) is True


def test_odd_numbers():
    """Odd numbers are detected."""
    assert is_even(7) is False
