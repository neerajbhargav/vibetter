"""Checkout API used by the CLI and the web front end."""

from . import pricing
from .cart import Cart
from .legacy import refund_policy
from .models import Book, Customer


def checkout(customer: Customer, books: list[Book], code: str | None = None) -> dict:
    cart = Cart()
    for book in books:
        cart.add_item(book)
    cart.apply_discount(code)
    return {
        "customer": customer.email,
        "total_cents": cart.total(),
        "free_shipping": pricing.is_free_shipping(books),
        "refunds": refund_policy(),
    }
