"""Off-by-one sample project for FixPilot AI.

This project contains a loop with an off-by-one error that causes one
test to fail due to an incorrect boundary condition.
"""


def sum_range(n):
    """Sum all integers from 1 to n (inclusive).

    Args:
        n: The upper bound (should be a positive integer)

    Returns:
        The sum of integers from 1 to n
    """
    total = 0
    for i in range(1, n):  # Bug: should be range(1, n+1) to include n
        total += i
    return total


# Test file
"""Tests for the sum_range function."""
import pytest


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