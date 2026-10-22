"""Command line entry point for the shop fixture."""

import sys

from shop.api import checkout
from shop.models import Book, Customer


def main(argv: list[str]) -> int:
    customer = Customer(name="Ada Example", email="ada@example.com")
    books = [Book(title=title, price_cents=1500) for title in argv[1:]]
    receipt = checkout(customer, books, code="WELCOME10")
    print(receipt)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
