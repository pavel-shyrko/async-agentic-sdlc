import unittest
import src.utils.math_helpers
from decimal import Decimal
from fractions import Fraction

class TestIsPrime(unittest.TestCase):

    def test_prime_numbers(self):
        # Test known prime numbers
        self.assertTrue(src.utils.math_helpers.is_prime(2))
        self.assertTrue(src.utils.math_helpers.is_prime(3))
        self.assertTrue(src.utils.math_helpers.is_prime(5))
        self.assertTrue(src.utils.math_helpers.is_prime(7))
        self.assertTrue(src.utils.math_helpers.is_prime(11))
        self.assertTrue(src.utils.math_helpers.is_prime(13))
        self.assertTrue(src.utils.math_helpers.is_prime(17))
        self.assertTrue(src.utils.math_helpers.is_prime(19))
        self.assertTrue(src.utils.math_helpers.is_prime(23))
        self.assertTrue(src.utils.math_helpers.is_prime(29))
        self.assertTrue(src.utils.math_helpers.is_prime(31))
        self.assertTrue(src.utils.math_helpers.is_prime(37))
        self.assertTrue(src.utils.math_helpers.is_prime(41))
        self.assertTrue(src.utils.math_helpers.is_prime(43))
        self.assertTrue(src.utils.math_helpers.is_prime(47))
        self.assertTrue(src.utils.math_helpers.is_prime(53))
        self.assertTrue(src.utils.math_helpers.is_prime(97))
        self.assertTrue(src.utils.math_helpers.is_prime(101))
        self.assertTrue(src.utils.math_helpers.is_prime(1009))
        self.assertTrue(src.utils.math_helpers.is_prime(7919)) # Larger prime

    def test_composite_numbers(self):
        # Test known composite numbers
        self.assertFalse(src.utils.math_helpers.is_prime(4))
        self.assertFalse(src.utils.math_helpers.is_prime(6))
        self.assertFalse(src.utils.math_helpers.is_prime(8))
        self.assertFalse(src.utils.math_helpers.is_prime(9))
        self.assertFalse(src.utils.math_helpers.is_prime(10))
        self.assertFalse(src.utils.math_helpers.is_prime(12))
        self.assertFalse(src.utils.math_helpers.is_prime(15))
        self.assertFalse(src.utils.math_helpers.is_prime(25))
        self.assertFalse(src.utils.math_helpers.is_prime(49))
        self.assertFalse(src.utils.math_helpers.is_prime(100))
        self.assertFalse(src.utils.math_helpers.is_prime(121)) # 11*11
        self.assertFalse(src.utils.math_helpers.is_prime(999)) # 9*111

    def test_numbers_less_than_two(self):
        # Test numbers less than 2, which are explicitly not prime
        self.assertFalse(src.utils.math_helpers.is_prime(0))
        self.assertFalse(src.utils.math_helpers.is_prime(1))
        self.assertFalse(src.utils.math_helpers.is_prime(-1))
        self.assertFalse(src.utils.math_helpers.is_prime(-2))
        self.assertFalse(src.utils.math_helpers.is_prime(-100))

    def test_invalid_input_types(self):
        # Test for TypeError with non-integer inputs
        self.assertRaises(TypeError, src.utils.math_helpers.is_prime, 5.0) # Float
        self.assertRaises(TypeError, src.utils.math_helpers.is_prime, 3.14) # Float
        self.assertRaises(TypeError, src.utils.math_helpers.is_prime, True) # Boolean
        self.assertRaises(TypeError, src.utils.math_helpers.is_prime, False) # Boolean
        self.assertRaises(TypeError, src.utils.math_helpers.is_prime, "5") # String
        self.assertRaises(TypeError, src.utils.math_helpers.is_prime, "abc") # String
        self.assertRaises(TypeError, src.utils.math_helpers.is_prime, None) # NoneType
        self.assertRaises(TypeError, src.utils.math_helpers.is_prime, [5]) # List
        self.assertRaises(TypeError, src.utils.math_helpers.is_prime, (5,)) # Tuple
        self.assertRaises(TypeError, src.utils.math_helpers.is_prime, {'num': 5}) # Dictionary
        self.assertRaises(TypeError, src.utils.math_helpers.is_prime, Decimal('5')) # Decimal
        self.assertRaises(TypeError, src.utils.math_helpers.is_prime, Fraction(5, 1)) # Fraction

if __name__ == '__main__':
    unittest.main()