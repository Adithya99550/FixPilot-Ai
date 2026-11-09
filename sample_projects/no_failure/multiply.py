"""No-failure sample project for FixPilot AI.

This project contains tests that all pass, so FixPilot should report
"No failing tests detected" and not invent a repair.
"""


def multiply(a, b):
    """Multiply two numbers together."""
    return a * b


def is_positive(n):
    """Check if a number is positive."""
    return n > 0


# Test file
"""Tests for the multiply and is_positive functions."""
import pytest


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