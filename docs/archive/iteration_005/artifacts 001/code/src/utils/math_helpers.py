import math


def is_prime(num: int) -> bool:
    """
    Determines if a given integer is a prime number.

    A prime number is a natural number greater than 1 that has no positive divisors
    other than 1 and itself.

    Args:
        num: An integer to check for primality.

    Returns:
        True if the number is prime, False otherwise.

    Raises:
        TypeError: If 'num' is not an integer.
    """
    if not isinstance(num, int) or isinstance(num, bool):
        raise TypeError(
            f"Expected an integer, got {type(num).__name__!r}. "
            "Implicit coercion from float, bool, str, or other types is not permitted."
        )
    if num < 2:
        return False
    if num == 2:
        return True
    if num % 2 == 0:
        return False
    for i in range(3, math.isqrt(num) + 1, 2):
        if num % i == 0:
            return False
    return True
