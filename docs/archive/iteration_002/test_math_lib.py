import unittest
from math_lib import factorial

class TestFactorial(unittest.TestCase):
    def test_factorial_zero(self):
        """Test that factorial of 0 is 1."""
        self.assertEqual(factorial(0), 1)

    def test_factorial_one(self):
        """Test that factorial of 1 is 1."""
        self.assertEqual(factorial(1), 1)

    def test_factorial_positive_integers(self):
        """Test typical positive integers."""
        self.assertEqual(factorial(2), 2)
        self.assertEqual(factorial(3), 6)
        self.assertEqual(factorial(4), 24)
        self.assertEqual(factorial(5), 120)
        self.assertEqual(factorial(10), 3628800)

    def test_factorial_large_integer(self):
        """Test a larger integer to ensure no overflow issues and performance is acceptable."""
        # 20! = 2432902008176640000
        self.assertEqual(factorial(20), 2432902008176640000)

    def test_factorial_negative_raises_value_error(self):
        """Test that negative integers raise a ValueError."""
        with self.assertRaises(ValueError):
            factorial(-1)
        with self.assertRaises(ValueError):
            factorial(-100)

    def test_factorial_invalid_types_raise_type_error(self):
        """Test that non-integer types raise a TypeError."""
        invalid_inputs = [
            5.5, 
            "5", 
            [5], 
            {"n": 5}, 
            None, 
            True,  # Booleans are technically subclasses of int in Python, but usually disallowed for factorial
            False
        ]
        for val in invalid_inputs:
            with self.subTest(val=val):
                with self.assertRaises(TypeError):
                    factorial(val)

if __name__ == '__main__':
    unittest.main()