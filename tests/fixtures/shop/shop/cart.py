"""The shopping cart."""

from .models import Book
from .pricing import compute_tax, discount_for


class Cart:
    def __init__(self) -> None:
        self.items: list[Book] = []
        self.discount = 0.0

    def add_item(self, book: Book) -> None:
        self.items.append(book)

    def remove_item(self, title: str) -> None:
        self.items = [book for book in self.items if book.title != title]

    def subtotal(self) -> int:
        return sum(book.price_cents for book in self.items)

    def apply_discount(self, code: str | None) -> float:
        """Apply a discount code. A second code replaces the first one."""
        rate = discount_for(code)
        if rate > 0.5:
            raise ValueError("discounts above 50 percent need a manager")
        self.discount = rate
        return rate

    def total(self) -> int:
        discounted = round(self.subtotal() * (1 - self.discount))
        return discounted + compute_tax(discounted)
