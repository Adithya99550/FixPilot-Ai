"""Incorrect-condition sample project for FixPilot AI.

A boundary condition written with the wrong comparison operator.
"""


def is_even(number):
    """Return True when the number is even.

    Args:
        number: Any integer.

    Returns:
        True when the number is divisible by two.
    """
    # Bug: uses > instead of >=, so zero is reported as odd.
    return number % 2 > 0
