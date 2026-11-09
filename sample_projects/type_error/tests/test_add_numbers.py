"""Tests for the add_numbers function."""

import pytest

from add_numbers import add_numbers


def test_add_numbers_basic():
    """Basic addition test."""
    result = add_numbers(2, 3)
    assert result == 5


def test_add_numbers_type_error():
    """Type error test: string argument should raise TypeError."""
    with pytest.raises(TypeError):
        add_numbers("2", 3)