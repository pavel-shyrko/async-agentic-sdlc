def fibonacci(n: int) -> int:
    if isinstance(n, bool):
        raise TypeError(f"n must be an int, not bool: {n!r}")
    if not isinstance(n, int):
        raise TypeError(f"n must be an int, not {type(n).__name__}: {n!r}")
    if n < 0:
        raise ValueError(f"n must be non-negative: {n!r}")

    previous, current = 0, 1
    for _ in range(n):
        previous, current = current, previous + current
    return previous
