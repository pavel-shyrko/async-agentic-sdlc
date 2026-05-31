from .base import validate_positive_number
from .shapes import Circle, Rectangle


class Cylinder:
    def __init__(self, radius: float, height: float) -> None:
        validate_positive_number(height, "height")
        self.base = Circle(radius)
        self.height = float(height)

    @property
    def radius(self) -> float:
        return self.base.radius

    def volume(self) -> float:
        return self.base.area() * self.height


class Cuboid:
    def __init__(self, width: float, height: float, depth: float) -> None:
        validate_positive_number(depth, "depth")
        self.base = Rectangle(width, height)
        self.depth = float(depth)

    @property
    def width(self) -> float:
        return self.base.width

    @property
    def height(self) -> float:
        return self.base.height

    def volume(self) -> float:
        return self.base.area() * self.depth
