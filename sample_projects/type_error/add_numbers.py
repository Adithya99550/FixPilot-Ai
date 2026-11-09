"""Type error sample project for FixPilot AI.

This project contains a function that receives a string where a numeric
value is expected, causing a test to fail with a TypeError.
"""

def add_numbers(a, b):
    """Add two numbers together.

    Args:
        a: First number (should be int or float)
        b: Second number (should be int or float)

    Returns:
        The sum of a and b

    Raises:
        TypeError: If either argument is not a number
    """
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise TypeError(
            f"Expected numeric types, got {type(a).__name__} and {type(b).__name__}"
        )
    return a + b


# Test file
"""Tests for the add_numbers function."""
import pytest

def test_add_numbers_basic():
    """Basic addition test."""
    result = add_numbers(2, 3)
    assert result == 5

def test_add_numbers_type_error():
    """Type error test: string argument should raise TypeError."""
    with pytest.raises(TypeError):
        add_numbers("2", 3)