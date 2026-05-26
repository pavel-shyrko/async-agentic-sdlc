def factorial(n: int) -> int:
    if not isinstance(n, int) or isinstance(n, bool):
        raise TypeError(f"factorial() requires an integer argument, got {type(n).__name__}")
    if n < 0:
        raise ValueError(f"factorial() is not defined for negative integers, got {n}")
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result
