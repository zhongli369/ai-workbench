"""Tiny price calc used by main.py."""


def total_price(items):
    """Sum price * qty for each (name, price, qty) tuple."""
    return sum(price * qty for _name, price, qty in items)


def discount(total, pct):
    return total * (1 - pct / 100)
