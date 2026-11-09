"""Tests for the multiply and is_positive functions."""

import pytest

from multiply import multiply, is_positive


def test_multiply_basic():
    """Basic multiplication test."""
    result = multiply(3, 4)
    assert result == 12


def test_multiply_by_zero():
    """Any number times zero is zero."""
    result = multiply(5, 0)
    assert result == 0


def test_multiply_negative():
    """Negative times negative is positive."""
    result = multiply(-3, -4)
    assert result == 12


def test_is_positive_true():
    """Positive number should return True."""
    assert is_positive(5) is True


def test_is_positive_false():
    """Non-positive number should return False."""
    assert is_positive(0) is False
    assert is_positive(-5) is False