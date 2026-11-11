"""Tests for the clamp function."""

from clamp import clamp


def test_clamp_below_low():
    """Values below the lower bound are raised to it."""
    assert clamp(-5, 0, 10) == 0


def test_clamp_above_high():
    """Values above the upper bound are lowered to it."""
    assert clamp(50, 0, 10) == 10
