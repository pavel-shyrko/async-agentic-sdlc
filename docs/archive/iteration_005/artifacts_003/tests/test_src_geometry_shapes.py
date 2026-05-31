import unittest
import math
from src.geometry.shapes import Circle, Rectangle

class TestShapes(unittest.TestCase):

    # --- Circle Tests ---

    def test_circle_init_valid_float_radius(self):
        circle = Circle(5.5)
        self.assertEqual(circle.radius, 5.5)

    def test_circle_init_valid_int_radius(self):
        circle = Circle(7)
        self.assertEqual(circle.radius, 7.0) # Should be cast to float internally

    def test_circle_init_zero_radius_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "radius must be a positive number"):
            Circle(0)

    def test_circle_init_negative_radius_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "radius must be a positive number"):
            Circle(-5.0)

    def test_circle_init_string_radius_raises_type_error(self):
        with self.assertRaisesRegex(TypeError, "radius must be a number"):
            Circle("invalid")

    def test_circle_init_none_radius_raises_type_error(self):
        with self.assertRaisesRegex(TypeError, "radius must be a number"):
            Circle(None)

    def test_circle_init_boolean_radius_raises_type_error(self):
        with self.assertRaisesRegex(TypeError, "radius must be a number, not a bool"):
            Circle(True)

    def test_circle_area_calculation_positive_float(self):
        circle = Circle(5.0)
        expected_area = math.pi * (5.0 ** 2)
        self.assertAlmostEqual(circle.area(), expected_area)

    def test_circle_area_calculation_positive_int(self):
        circle = Circle(3)
        expected_area = math.pi * (3 ** 2)
        self.assertAlmostEqual(circle.area(), expected_area)

    def test_circle_area_with_large_radius(self):
        circle = Circle(1000)
        expected_area = math.pi * (1000 ** 2)
        self.assertAlmostEqual(circle.area(), expected_area)

    def test_circle_area_with_small_radius(self):
        circle = Circle(0.1)
        expected_area = math.pi * (0.1 ** 2)
        self.assertAlmostEqual(circle.area(), expected_area)

    # --- Rectangle Tests ---

    def test_rectangle_init_valid_float_dimensions(self):
        rect = Rectangle(10.5, 5.5)
        self.assertEqual(rect.width, 10.5)
        self.assertEqual(rect.height, 5.5)

    def test_rectangle_init_valid_int_dimensions(self):
        rect = Rectangle(8, 4)
        self.assertEqual(rect.width, 8.0) # Should be cast to float internally
        self.assertEqual(rect.height, 4.0)

    def test_rectangle_init_zero_width_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "width must be a positive number"):
            Rectangle(0, 5)

    def test_rectangle_init_negative_height_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "height must be a positive number"):
            Rectangle(10, -2.0)

    def test_rectangle_init_string_width_raises_type_error(self):
        with self.assertRaisesRegex(TypeError, "width must be a number"):
            Rectangle("invalid", 5)

    def test_rectangle_init_none_height_raises_type_error(self):
        with self.assertRaisesRegex(TypeError, "height must be a number"):
            Rectangle(10, None)

    def test_rectangle_init_boolean_width_raises_type_error(self):
        with self.assertRaisesRegex(TypeError, "width must be a number, not a bool"):
            Rectangle(False, 5)

    def test_rectangle_init_boolean_height_raises_type_error(self):
        with self.assertRaisesRegex(TypeError, "height must be a number, not a bool"):
            Rectangle(10, True)

    def test_rectangle_area_calculation_positive_float(self):
        rect = Rectangle(10.0, 5.0)
        expected_area = 10.0 * 5.0
        self.assertAlmostEqual(rect.area(), expected_area)

    def test_rectangle_area_calculation_positive_int(self):
        rect = Rectangle(8, 4)
        expected_area = 8 * 4
        self.assertAlmostEqual(rect.area(), expected_area)

    def test_rectangle_area_with_large_dimensions(self):
        rect = Rectangle(1000, 2000)
        expected_area = 1000 * 2000
        self.assertAlmostEqual(rect.area(), expected_area)

    def test_rectangle_area_with_small_dimensions(self):
        rect = Rectangle(0.5, 0.25)
        expected_area = 0.5 * 0.25
        self.assertAlmostEqual(rect.area(), expected_area)

if __name__ == '__main__':
    unittest.main()