"""Tests for the average function."""

from average import average


def test_average_of_two_numbers():
    """The mean of 1 and 3 is 2."""
    assert average([1, 3]) == 2


def test_average_of_single_number():
    """The mean of a single number is the number itself."""
    assert average([5]) == 5
