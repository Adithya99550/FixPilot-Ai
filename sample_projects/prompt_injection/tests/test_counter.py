"""Tests for the counter module."""

from counter import count_words


def test_count_words():
    """A three word sentence has three words."""
    assert count_words("one two three") == 3


def test_count_single_word():
    """A single word counts as one."""
    assert count_words("hello") == 1
