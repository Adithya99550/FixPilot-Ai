"""Regression-case sample project for FixPilot AI.

One failing test can be "fixed" by a naive repair that breaks another test.
The second test must fail once the first one is made to pass incorrectly,
so FixPilot has to detect the regression instead of claiming success.
"""


def clamp(value, low, high):
    """Clamp a value into the inclusive range [low, high].

    Args:
        value: The value to clamp.
        low: Lower bound.
        high: Upper bound.

    Returns:
        The clamped value.
    """
    # Bug: only the lower bound is handled, so values above `high` are
    # returned unchanged.
    if value < low:
        return low
    return value
