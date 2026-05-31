from abc import ABC, abstractmethod


def validate_positive_number(value: float, name: str) -> None:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be a number, not a bool")
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number, not {type(value).__name__}")
    if value <= 0:
        raise ValueError(f"{name} must be a positive number")


class Shape(ABC):
    @abstractmethod
    def area(self) -> float:
        pass
