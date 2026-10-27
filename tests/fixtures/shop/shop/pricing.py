"""Tax and discount rules."""

from .models import Book

TAX_RATE = 0.08875
DISCOUNT_CODES = {"WELCOME10": 0.10, "STUDENT": 0.15}


def compute_tax(subtotal_cents: int) -> int:
    """Sales tax on a subtotal, rounded to the nearest cent."""
    return round(subtotal_cents * TAX_RATE)


def discount_for(code: str | None) -> float:
    """The fraction taken off for a discount code. Unknown codes give no discount."""
    if not code:
        return 0.0
    return DISCOUNT_CODES.get(code.strip().upper(), 0.0)


def is_free_shipping(books: list[Book]) -> bool:
    return sum(book.price_cents for book in books) >= 5000
