"""Pricing helpers for the Sales section (pure functions, no database).

A sale is priced in one of three ways:
    face value     every bond is sold for the amount printed on it
    each           every bond is sold for the same amount
    total          one amount for the whole sale, shared out between the bonds in proportion
               to their face value (so 4 bonds of Rs 750 sold for Rs 3,100 get 775 each)
All amounts are whole rupees, and the parts always add up to exactly the total you typed.
"""
from __future__ import annotations

import re
from typing import Sequence

PRICE_MODES = ("face", "each", "total")


def parse_amount(text) -> int | None:
    """'Rs 3,100' -> 3100.  None when the text is empty or is not a whole number of rupees."""
    cleaned = re.sub(r"(?i)rs\.?|[,\s]", "", str(text or ""))
    return int(cleaned) if cleaned.isdigit() else None


def split_total(total: int, denominations: Sequence[int]) -> list[int]:
    """Share ``total`` between bonds in proportion to their face value (whole rupees).

    The rounding leftovers go to the first bonds, so ``sum(result) == total`` always.
    """
    if not denominations:
        return []
    face = sum(denominations)
    shares = [total * d // face for d in denominations]
    for i in range(total - sum(shares)):
        shares[i % len(shares)] += 1
    return shares


def prices_for(mode: str, denominations: Sequence[int], amount: int | None = None) -> list[int]:
    """The price of each bond for a pricing ``mode`` ('face', 'each' or 'total')."""
    if mode == "face":
        return list(denominations)
    if amount is None:
        raise ValueError("Enter the amount.")
    if mode == "each":
        return [amount] * len(denominations)
    if mode == "total":
        return split_total(amount, denominations)
    raise ValueError(f"Unknown price mode '{mode}'.")
