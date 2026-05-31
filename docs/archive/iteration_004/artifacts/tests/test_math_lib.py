import unittest
import math_lib

class TestFactorial(unittest.TestCase):

    def test_factorial_zero(self):
        self.assertEqual(math_lib.factorial(0), 1)

    def test_factorial_one(self):
        self.assertEqual(math_lib.factorial(1), 1)

    def test_factorial_positive_small(self):
        self.assertEqual(math_lib.factorial(5), 120)

    def test_factorial_positive_medium(self):
        self.assertEqual(math_lib.factorial(10), 3628800)

    def test_factorial_positive_large(self):
        self.assertEqual(math_lib.factorial(15), 1307674368000)

    def test_factorial_negative_one_raises_value_error(self):
        with self.assertRaises(ValueError):
            math_lib.factorial(-1)

    def test_factorial_negative_large_raises_value_error(self):
        with self.assertRaises(ValueError):
            math_lib.factorial(-100)

    def test_factorial_none_raises_type_error(self):
        with self.assertRaises(TypeError):
            math_lib.factorial(None)

    def test_factorial_string_raises_type_error(self):
        with self.assertRaises(TypeError):
            math_lib.factorial("abc")

    def test_factorial_list_raises_type_error(self):
        with self.assertRaises(TypeError):
            math_lib.factorial([1, 2, 3])

    def test_factorial_tuple_raises_type_error(self):
        with self.assertRaises(TypeError):
            math_lib.factorial((1, 2, 3))

    def test_factorial_dict_raises_type_error(self):
        with self.assertRaises(TypeError):
            math_lib.factorial({'a': 1})

    def test_factorial_float_zero_raises_type_error(self):
        with self.assertRaises(TypeError):
            math_lib.factorial(0.0)

    def test_factorial_float_whole_number_raises_type_error(self):
        with self.assertRaises(TypeError):
            math_lib.factorial(5.0)

    def test_factorial_float_decimal_raises_type_error(self):
        with self.assertRaises(TypeError):
            math_lib.factorial(3.14)

    def test_factorial_true_raises_type_error(self):
        with self.assertRaises(TypeError):
            math_lib.factorial(True)

    def test_factorial_false_raises_type_error(self):
        with self.assertRaises(TypeError):
            math_lib.factorial(False)