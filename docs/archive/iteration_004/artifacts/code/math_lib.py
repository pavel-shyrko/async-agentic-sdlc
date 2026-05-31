"""Math utilities for the Antigravity SDLC project."""


def factorial(n: int) -> int:
    """Compute the factorial of a non-negative integer.

    Args:
        n: A non-negative integer.

    Returns:
        The factorial of ``n``.

    Raises:
        TypeError: If ``n`` is not an integer (booleans and floats rejected).
        ValueError: If ``n`` is a negative integer.
    """
    if type(n) is not int:
        raise TypeError(f"n must be an int, got {type(n).__name__}")
    if n < 0:
        raise ValueError("n must be a non-negative integer")

    result = 1
    for i in range(2, n + 1):
        result *= i
    return result
