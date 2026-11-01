from dataclasses import dataclass


@dataclass(frozen=True)
class AttributeStat:
    name: str
    frequency: int
    relevance: float


@dataclass(frozen=True)
class MaveCategory:
    name: str
    attributes: tuple[AttributeStat, ...]
