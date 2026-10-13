"""Demo data so you can try the whole workflow in a minute (``python main.py --demo``)."""
from __future__ import annotations

from .db import Database
from .processing.agent import WinAgent
from .processing.numbers import parse_pattern


def _numbers(pattern: str):
    return parse_pattern(pattern).numbers


def seed(db: Database) -> None:
    """Copies that differ in size and sequence, one number held in two copies, and a draw.

    100056 sits in Copy 1 (position 56 of 100) *and* in Copy 5 (position 7 of 11): when it is
    drawn, both bonds win - the agent queues both and approving one approves both.
    """
    db.add_copy("Copy 1", _numbers("100001-100100"), 750, "2025-01-10")
    db.add_copy("Copy 2", _numbers("555001-555020, 777777, 900001-900010:3"), 750, "2025-02-01")
    db.add_copy("Copy 3", _numbers("400100-400001"), 1500, "2026-05-01")
    db.add_copy("Copy 4", _numbers("310001-310050"), 200, "2026-03-15")
    db.add_copy("Copy 5", _numbers("100050-100060"), 750, "2025-06-01")
    db.add_loose_bonds(_numbers("123456, 234567"), 100, "2026-06-01")

    draw = db.add_draw("2026-10-01", 750, "Draw #98 (demo)")
    winners = [("100056", "1st Prize", 1_500_000), ("777777", "2nd Prize", 500_000),
               ("900007", "3rd Prize", 9_300), ("812345", "3rd Prize", 9_300)]
    db.add_winning_numbers(draw, [(*_numbers(n)[0], tier, amount) for n, tier, amount in winners])
    WinAgent(db).scan(draw, trigger="draw")
