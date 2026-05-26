import unittest
from math_lib import factorial

class TestFactorial(unittest.TestCase):

    # Test cases for valid non-negative integer inputs
    def test_factorial_zero(self):
        self.assertEqual(factorial(0), 1)

    def test_factorial_one(self):
        self.assertEqual(factorial(1), 1)

    def test_factorial_positive_small(self):
        self.assertEqual(factorial(2), 2)
        self.assertEqual(factorial(3), 6)
        self.assertEqual(factorial(5), 120)

    def test_factorial_positive_medium(self):
        self.assertEqual(factorial(7), 5040)
        self.assertEqual(factorial(10), 3628800)

    def test_factorial_positive_large(self):
        # Test with a reasonably large number to ensure correctness
        # Python handles large integers automatically, so no explicit overflow test needed.
        self.assertEqual(factorial(15), 1307674368000)

    # Test cases for invalid negative integer inputs (ValueError)
    def test_factorial_negative_one_raises_value_error(self):
        with self.assertRaises(ValueError):
            factorial(-1)

    def test_factorial_negative_large_raises_value_error(self):
        with self.assertRaises(ValueError):
            factorial(-10)

    # Test cases for invalid non-integer types (TypeError)
    def test_factorial_float_raises_type_error(self):
        with self.assertRaises(TypeError):
            factorial(5.0)
        with self.assertRaises(TypeError):
            factorial(0.0)
        with self.assertRaises(TypeError):
            factorial(-5.0)

    def test_factorial_string_raises_type_error(self):
        with self.assertRaises(TypeError):
            factorial("5")
        with self.assertRaises(TypeError):
            factorial("hello")

    def test_factorial_boolean_true_raises_type_error(self):
        # bool is a subclass of int, but the requirement is 'exact instance of int'
        with self.assertRaises(TypeError):
            factorial(True)

    def test_factorial_boolean_false_raises_type_error(self):
        # bool is a subclass of int, but the requirement is 'exact instance of int'
        with self.assertRaises(TypeError):
            factorial(False)

    def test_factorial_none_raises_type_error(self):
        with self.assertRaises(TypeError):
            factorial(None)

    def test_factorial_list_raises_type_error(self):
        with self.assertRaises(TypeError):
            factorial([5])

    def test_factorial_tuple_raises_type_error(self):
        with self.assertRaises(TypeError):
            factorial((5,))

    def test_factorial_dict_raises_type_error(self):
        with self.assertRaises(TypeError):
            factorial({'key': 5})

    def test_factorial_complex_raises_type_error(self):
        with self.assertRaises(TypeError):
            factorial(5 + 2j)

    def test_factorial_bytearray_raises_type_error(self):
        with self.assertRaises(TypeError):
            factorial(bytearray(b'\x01'))

    # Test case with object that is convertible to int but not an int itself
    def test_factorial_custom_object_raises_type_error(self):
        class MyInt:
            def __index__(self):
                return 5
            def __int__(self):
                return 5
        with self.assertRaises(TypeError):
            factorial(MyInt())

if __name__ == '__main__':
    unittest.main()