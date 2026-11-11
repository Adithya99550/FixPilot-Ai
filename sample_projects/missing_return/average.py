"""Missing-return sample project for FixPilot AI.

A function that forgets to return its result, so the test sees None.
"""


def average(numbers):
    """Return the arithmetic mean of a list of numbers.

    Args:
        numbers: A non-empty list of numbers.

    Returns:
        The arithmetic mean of the numbers.
    """
    total = 0
    for number in numbers:
        total += number
    # Bug: the result is computed but never returned.
