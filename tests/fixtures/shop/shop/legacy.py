"""Old refund rules, kept for one more release."""


def refund_policy() -> str:
    return "Refunds within 30 days with a receipt."


def legacy_checkout(customer, books):
    from .api import checkout  # imported late: api imports this module

    return checkout(customer, books)
