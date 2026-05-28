import unittest
import math
import src.geometry.volume

class TestVolumeModule(unittest.TestCase):

    # --- Cylinder Tests ---

    def test_cylinder_initialization_valid_floats(self):
        cylinder = src.geometry.volume.Cylinder(5.0, 10.0)
        self.assertIsInstance(cylinder.radius, float)
        self.assertEqual(cylinder.radius, 5.0)
        self.assertIsInstance(cylinder.height, float)
        self.assertEqual(cylinder.height, 10.0)

    def test_cylinder_initialization_valid_integers_casted_to_float(self):
        cylinder = src.geometry.volume.Cylinder(5, 10)
        self.assertIsInstance(cylinder.radius, float)
        self.assertEqual(cylinder.radius, 5.0)
        self.assertIsInstance(cylinder.height, float)
        self.assertEqual(cylinder.height, 10.0)

    def test_cylinder_radius_zero_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "radius must be a positive number"):
            src.geometry.volume.Cylinder(0, 10)

    def test_cylinder_radius_negative_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "radius must be a positive number"):
            src.geometry.volume.Cylinder(-5, 10)

    def test_cylinder_height_zero_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "height must be a positive number"):
            src.geometry.volume.Cylinder(5, 0)

    def test_cylinder_height_negative_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "height must be a positive number"):
            src.geometry.volume.Cylinder(5, -10)

    def test_cylinder_radius_string_raises_type_error(self):
        with self.assertRaisesRegex(TypeError, "radius must be a number, not str"):
            src.geometry.volume.Cylinder("5", 10)

    def test_cylinder_height_string_raises_type_error(self):
        with self.assertRaisesRegex(TypeError, "height must be a number, not str"):
            src.geometry.volume.Cylinder(5, "10")

    def test_cylinder_radius_none_raises_type_error(self):
        with self.assertRaisesRegex(TypeError, "radius must be a number, not NoneType"):
            src.geometry.volume.Cylinder(None, 10)

    def test_cylinder_height_none_raises_type_error(self):
        with self.assertRaisesRegex(TypeError, "height must be a number, not NoneType"):
            src.geometry.volume.Cylinder(5, None)

    def test_cylinder_radius_boolean_raises_type_error(self):
        with self.assertRaisesRegex(TypeError, "radius must be a number, not a bool"):
            src.geometry.volume.Cylinder(True, 10)

    def test_cylinder_height_boolean_raises_type_error(self):
        with self.assertRaisesRegex(TypeError, "height must be a number, not a bool"):
            src.geometry.volume.Cylinder(5, False)

    def test_cylinder_volume_calculation(self):
        cylinder = src.geometry.volume.Cylinder(3.0, 5.0)
        expected_volume = math.pi * (3.0 ** 2) * 5.0
        self.assertAlmostEqual(cylinder.volume(), expected_volume)

    def test_cylinder_volume_with_decimal_dimensions(self):
        cylinder = src.geometry.volume.Cylinder(2.5, 4.2)
        expected_volume = math.pi * (2.5 ** 2) * 4.2
        self.assertAlmostEqual(cylinder.volume(), expected_volume)

    def test_cylinder_volume_large_dimensions(self):
        cylinder = src.geometry.volume.Cylinder(100.0, 200.0)
        expected_volume = math.pi * (100.0 ** 2) * 200.0
        self.assertAlmostEqual(cylinder.volume(), expected_volume)

    # --- Cuboid Tests ---

    def test_cuboid_initialization_valid_floats(self):
        cuboid = src.geometry.volume.Cuboid(2.0, 3.0, 4.0)
        self.assertIsInstance(cuboid.width, float)
        self.assertEqual(cuboid.width, 2.0)
        self.assertIsInstance(cuboid.height, float)
        self.assertEqual(cuboid.height, 3.0)
        self.assertIsInstance(cuboid.depth, float)
        self.assertEqual(cuboid.depth, 4.0)

    def test_cuboid_initialization_valid_integers_casted_to_float(self):
        cuboid = src.geometry.volume.Cuboid(2, 3, 4)
        self.assertIsInstance(cuboid.width, float)
        self.assertEqual(cuboid.width, 2.0)
        self.assertIsInstance(cuboid.height, float)
        self.assertEqual(cuboid.height, 3.0)
        self.assertIsInstance(cuboid.depth, float)
        self.assertEqual(cuboid.depth, 4.0)

    def test_cuboid_width_zero_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "width must be a positive number"):
            src.geometry.volume.Cuboid(0, 3, 4)

    def test_cuboid_width_negative_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "width must be a positive number"):
            src.geometry.volume.Cuboid(-2, 3, 4)

    def test_cuboid_height_zero_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "height must be a positive number"):
            src.geometry.volume.Cuboid(2, 0, 4)

    def test_cuboid_height_negative_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "height must be a positive number"):
            src.geometry.volume.Cuboid(2, -3, 4)

    def test_cuboid_depth_zero_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "depth must be a positive number"):
            src.geometry.volume.Cuboid(2, 3, 0)

    def test_cuboid_depth_negative_raises_value_error(self):
        with self.assertRaisesRegex(ValueError, "depth must be a positive number"):
            src.geometry.volume.Cuboid(2, 3, -4)

    def test_cuboid_width_string_raises_type_error(self):
        with self.assertRaisesRegex(TypeError, "width must be a number, not str"):
            src.geometry.volume.Cuboid("2", 3, 4)

    def test_cuboid_height_string_raises_type_error(self):
        with self.assertRaisesRegex(TypeError, "height must be a number, not str"):
            src.geometry.volume.Cuboid(2, "3", 4)

    def test_cuboid_depth_string_raises_type_error(self):
        with self.assertRaisesRegex(TypeError, "depth must be a number, not str"):
            src.geometry.volume.Cuboid(2, 3, "4")

    def test_cuboid_width_none_raises_type_error(self):
        with self.assertRaisesRegex(TypeError, "width must be a number, not NoneType"):
            src.geometry.volume.Cuboid(None, 3, 4)

    def test_cuboid_height_none_raises_type_error(self):
        with self.assertRaisesRegex(TypeError, "height must be a number, not NoneType"):
            src.geometry.volume.Cuboid(2, None, 4)

    def test_cuboid_depth_none_raises_type_error(self):
        with self.assertRaisesRegex(TypeError, "depth must be a number, not NoneType"):
            src.geometry.volume.Cuboid(2, 3, None)

    def test_cuboid_width_boolean_raises_type_error(self):
        with self.assertRaisesRegex(TypeError, "width must be a number, not a bool"):
            src.geometry.volume.Cuboid(True, 3, 4)

    def test_cuboid_height_boolean_raises_type_error(self):
        with self.assertRaisesRegex(TypeError, "height must be a number, not a bool"):
            src.geometry.volume.Cuboid(2, False, 4)

    def test_cuboid_depth_boolean_raises_type_error(self):
        with self.assertRaisesRegex(TypeError, "depth must be a number, not a bool"):
            src.geometry.volume.Cuboid(2, 3, True)

    def test_cuboid_volume_calculation(self):
        cuboid = src.geometry.volume.Cuboid(2.0, 3.0, 4.0)
        expected_volume = 2.0 * 3.0 * 4.0
        self.assertAlmostEqual(cuboid.volume(), expected_volume)

    def test_cuboid_volume_with_decimal_dimensions(self):
        cuboid = src.geometry.volume.Cuboid(2.5, 3.5, 4.5)
        expected_volume = 2.5 * 3.5 * 4.5
        self.assertAlmostEqual(cuboid.volume(), expected_volume)

    def test_cuboid_volume_large_dimensions(self):
        cuboid = src.geometry.volume.Cuboid(100.0, 200.0, 300.0)
        expected_volume = 100.0 * 200.0 * 300.0
        self.assertAlmostEqual(cuboid.volume(), expected_volume)