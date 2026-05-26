import pytest
from math_lib import factorial


def test_factorial_zero():
    assert factorial(0) == 1


def test_factorial_one():
    assert factorial(1) == 1


def test_factorial_positive():
    assert factorial(5) == 120
    assert factorial(10) == 3628800


def test_factorial_negative_raises():
    with pytest.raises(ValueError):
        factorial(-1)


def test_factorial_large():
    assert factorial(20) == 2432902008176640000


def test_factorial_type_error_on_float():
    with pytest.raises(TypeError):
        factorial(3.0)


def test_factorial_type_error_on_string():
    with pytest.raises(TypeError):
        factorial("5")
