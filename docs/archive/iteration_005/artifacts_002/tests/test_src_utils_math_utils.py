import unittest
from src.utils import math_utils

class TestFibonacci(unittest.TestCase):

    # Test cases for valid inputs
    def test_fibonacci_zero(self):
        self.assertEqual(math_utils.fibonacci(0), 0)

    def test_fibonacci_one(self):
        self.assertEqual(math_utils.fibonacci(1), 1)

    def test_fibonacci_two(self):
        self.assertEqual(math_utils.fibonacci(2), 1)

    def test_fibonacci_three(self):
        self.assertEqual(math_utils.fibonacci(3), 2)

    def test_fibonacci_five(self):
        self.assertEqual(math_utils.fibonacci(5), 5)

    def test_fibonacci_ten(self):
        self.assertEqual(math_utils.fibonacci(10), 55)

    def test_fibonacci_twenty(self):
        self.assertEqual(math_utils.fibonacci(20), 6765)

    # Test cases for invalid types (TypeError)
    def test_fibonacci_bool_true_type_error(self):
        self.assertRaises(TypeError, math_utils.fibonacci, True)

    def test_fibonacci_bool_false_type_error(self):
        self.assertRaises(TypeError, math_utils.fibonacci, False)

    def test_fibonacci_float_type_error(self):
        self.assertRaises(TypeError, math_utils.fibonacci, 3.14)

    def test_fibonacci_string_type_error(self):
        self.assertRaises(TypeError, math_utils.fibonacci, "5")

    def test_fibonacci_none_type_error(self):
        self.assertRaises(TypeError, math_utils.fibonacci, None)

    def test_fibonacci_list_type_error(self):
        self.assertRaises(TypeError, math_utils.fibonacci, [5])

    def test_fibonacci_dict_type_error(self):
        self.assertRaises(TypeError, math_utils.fibonacci, {'n': 5})

    # Test cases for invalid values (ValueError)
    def test_fibonacci_negative_one_value_error(self):
        self.assertRaises(ValueError, math_utils.fibonacci, -1)

    def test_fibonacci_negative_five_value_error(self):
        self.assertRaises(ValueError, math_utils.fibonacci, -5)

if __name__ == '__main__':
    unittest.main()