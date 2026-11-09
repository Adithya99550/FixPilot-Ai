"""Tests for the sum_range function."""

import pytest

from sum_range import sum_range


def test_sum_range_basic():
    """Basic sum test: 1+2+3 = 6"""
    result = sum_range(3)
    assert result == 6


def test_sum_range_up_to_5():
    """Sum 1 to 5 should be 15."""
    result = sum_range(5)
    assert result == 15


def test_sum_range_up_to_10():
    """Sum 1 to 10 should be 55."""
    result = sum_range(10)
    assert result == 55