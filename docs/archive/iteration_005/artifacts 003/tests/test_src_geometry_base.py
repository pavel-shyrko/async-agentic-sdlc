import unittest
from abc import ABC, abstractmethod

import src.geometry.base

class TestShape(unittest.TestCase):

    def test_shape_is_abstract_base_class(self) -> None:
        self.assertTrue(issubclass(src.geometry.base.Shape, ABC))

    def test_shape_cannot_be_instantiated_directly(self) -> None:
        with self.assertRaisesRegex(TypeError, r"Can't instantiate abstract class Shape with(out an implementation for)? abstract method"):
            src.geometry.base.Shape()

    def test_incomplete_concrete_shape_cannot_be_instantiated(self) -> None:
        class IncompleteConcreteShape(src.geometry.base.Shape):
            # Missing the 'area' method implementation
            pass

        with self.assertRaisesRegex(TypeError, r"Can't instantiate abstract class IncompleteConcreteShape with(out an implementation for)? abstract method"):
            IncompleteConcreteShape()

    def test_shape_has_abstract_area_method(self) -> None:
        self.assertIn('area', src.geometry.base.Shape.__abstractmethods__)