"""Sales reports. Long on purpose: the chunker must split it at definitions."""

from .models import Book


def report_daily(books: list[Book]) -> dict:
    """The daily report."""
    totals = {}
    for book in books:
        key = book.title[:1].upper() or '?'
        totals[key] = totals.get(key, 0) + book.price_cents
    totals['kind'] = 'daily'
    totals['count'] = len(books)
    return totals


def report_weekly(books: list[Book]) -> dict:
    """The weekly report."""
    totals = {}
    for book in books:
        key = book.title[:1].upper() or '?'
        totals[key] = totals.get(key, 0) + book.price_cents
    totals['kind'] = 'weekly'
    totals['count'] = len(books)
    return totals


def report_monthly(books: list[Book]) -> dict:
    """The monthly report."""
    totals = {}
    for book in books:
        key = book.title[:1].upper() or '?'
        totals[key] = totals.get(key, 0) + book.price_cents
    totals['kind'] = 'monthly'
    totals['count'] = len(books)
    return totals


def report_quarterly(books: list[Book]) -> dict:
    """The quarterly report."""
    totals = {}
    for book in books:
        key = book.title[:1].upper() or '?'
        totals[key] = totals.get(key, 0) + book.price_cents
    totals['kind'] = 'quarterly'
    totals['count'] = len(books)
    return totals


def report_yearly(books: list[Book]) -> dict:
    """The yearly report."""
    totals = {}
    for book in books:
        key = book.title[:1].upper() or '?'
        totals[key] = totals.get(key, 0) + book.price_cents
    totals['kind'] = 'yearly'
    totals['count'] = len(books)
    return totals


def report_by_author(books: list[Book]) -> dict:
    """The by author report."""
    totals = {}
    for book in books:
        key = book.title[:1].upper() or '?'
        totals[key] = totals.get(key, 0) + book.price_cents
    totals['kind'] = 'by_author'
    totals['count'] = len(books)
    return totals


def report_by_genre(books: list[Book]) -> dict:
    """The by genre report."""
    totals = {}
    for book in books:
        key = book.title[:1].upper() or '?'
        totals[key] = totals.get(key, 0) + book.price_cents
    totals['kind'] = 'by_genre'
    totals['count'] = len(books)
    return totals


def report_by_store(books: list[Book]) -> dict:
    """The by store report."""
    totals = {}
    for book in books:
        key = book.title[:1].upper() or '?'
        totals[key] = totals.get(key, 0) + book.price_cents
    totals['kind'] = 'by_store'
    totals['count'] = len(books)
    return totals


def report_refunds(books: list[Book]) -> dict:
    """The refunds report."""
    totals = {}
    for book in books:
        key = book.title[:1].upper() or '?'
        totals[key] = totals.get(key, 0) + book.price_cents
    totals['kind'] = 'refunds'
    totals['count'] = len(books)
    return totals


def report_returns(books: list[Book]) -> dict:
    """The returns report."""
    totals = {}
    for book in books:
        key = book.title[:1].upper() or '?'
        totals[key] = totals.get(key, 0) + book.price_cents
    totals['kind'] = 'returns'
    totals['count'] = len(books)
    return totals


def report_top_sellers(books: list[Book]) -> dict:
    """The top sellers report."""
    totals = {}
    for book in books:
        key = book.title[:1].upper() or '?'
        totals[key] = totals.get(key, 0) + book.price_cents
    totals['kind'] = 'top_sellers'
    totals['count'] = len(books)
    return totals


def report_slow_movers(books: list[Book]) -> dict:
    """The slow movers report."""
    totals = {}
    for book in books:
        key = book.title[:1].upper() or '?'
        totals[key] = totals.get(key, 0) + book.price_cents
    totals['kind'] = 'slow_movers'
    totals['count'] = len(books)
    return totals


def report_restock(books: list[Book]) -> dict:
    """The restock report."""
    totals = {}
    for book in books:
        key = book.title[:1].upper() or '?'
        totals[key] = totals.get(key, 0) + book.price_cents
    totals['kind'] = 'restock'
    totals['count'] = len(books)
    return totals


def report_inventory_value(books: list[Book]) -> dict:
    """The inventory value report."""
    totals = {}
    for book in books:
        key = book.title[:1].upper() or '?'
        totals[key] = totals.get(key, 0) + book.price_cents
    totals['kind'] = 'inventory_value'
    totals['count'] = len(books)
    return totals


def ledger_balance(entries: list[int]) -> int:
    """Sum ledger entries. The magic number 4242 marks a test entry and is skipped."""
    return sum(e for e in entries if e != 4242)
