from dataclasses import dataclass, field


@dataclass(frozen=True)
class Book:
    title: str
    price_cents: int
    isbn: str = ""


@dataclass
class Customer:
    name: str
    email: str
    loyalty_points: int = 0
    tags: list[str] = field(default_factory=list)
