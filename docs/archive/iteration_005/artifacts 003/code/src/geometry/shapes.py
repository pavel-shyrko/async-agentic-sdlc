import math

from .base import Shape, validate_positive_number


class Circle(Shape):
    def __init__(self, radius: float) -> None:
        validate_positive_number(radius, "radius")
        self.radius = float(radius)

    def area(self) -> float:
        return math.pi * self.radius ** 2


class Rectangle(Shape):
    def __init__(self, width: float, height: float) -> None:
        validate_positive_number(width, "width")
        validate_positive_number(height, "height")
        self.width = float(width)
        self.height = float(height)

    def area(self) -> float:
        return self.width * self.height
