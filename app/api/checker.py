"""Check thousands of bond numbers against the winning numbers in a data file.

The winning numbers are loaded once into a dictionary keyed by ``(price, number)``.  Checking a
bond is then one dictionary lookup, so 10,000 bonds take a few milliseconds (a loop of 10,000
database queries would take seconds).  Nothing here writes to the data file.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from ..processing.numbers import NumberError, normalize_number


@dataclass(frozen=True)
class WinningRow:
    """One winning number of one draw."""

    draw_id: int
    draw_date: str
    draw_label: str
    location: str
    denomination: int | None          # the draw's price; None = the draw applies to every price
    number: str
    prize_label: str
    prize_amount: int | None


@dataclass
class Hit:
    """A bond that matched a winning number."""

    number: str
    num: int
    denomination: int | None
    ref: str | None
    row: WinningRow


@dataclass
class CheckSummary:
    checked: int = 0
    winners: int = 0                  # bonds with at least one hit
    hits: list[Hit] = field(default_factory=list)
    invalid: list[tuple[int, str, str]] = field(default_factory=list)   # (index, text, reason)
    draws_searched: int = 0
    numbers_searched: int = 0
    elapsed_ms: float = 0.0


SELECT_WINNING = """
SELECT w.number, w.num, w.prize_label, w.prize_amount, d.id AS draw_id, d.draw_date,
       d.label, d.location, d.denomination
FROM winning_numbers w JOIN draws d ON d.id = w.draw_id
"""


class WinningIndex:
    """Winning numbers ready for lookups: ``(price, number) -> rows`` plus draws for any price."""

    def __init__(self, rows: Iterable[WinningRow], keys: Iterable[int] | None = None):
        self._exact: dict[tuple[int, int], list[WinningRow]] = {}
        self._any_price: dict[int, list[WinningRow]] = {}
        self._by_num: dict[int, list[WinningRow]] = {}
        self.draws: set[int] = set()
        self.count = 0
        rows = list(rows)
        keys = list(keys) if keys is not None else [int(r.number) for r in rows]
        for row, key in zip(rows, keys):
            self.draws.add(row.draw_id)
            self.count += 1
            self._by_num.setdefault(key, []).append(row)
            if row.denomination is None:
                self._any_price.setdefault(key, []).append(row)
            else:
                self._exact.setdefault((row.denomination, key), []).append(row)

    @classmethod
    def from_connection(cls, conn: sqlite3.Connection, draw_ids: Sequence[int] | None = None,
                        since: str | None = None) -> "WinningIndex":
        where, params = [], []
        if draw_ids:
            where.append(f"d.id IN ({','.join('?' * len(draw_ids))})")
            params += list(draw_ids)
        if since:
            where.append("d.draw_date >= ?")
            params.append(since)
        sql = SELECT_WINNING + (" WHERE " + " AND ".join(where) if where else "")
        rows, keys = [], []
        for r in conn.execute(sql, params):
            rows.append(WinningRow(r[4], r[5], r[6] or "", r[7] or "", r[8], r[0], r[2], r[3]))
            keys.append(r[1])
        return cls(rows, keys)

    def lookup(self, key: int, denomination: int | None) -> list[WinningRow]:
        """Rows a bond matches.  Without a price the number is matched in every draw."""
        if denomination is None:
            return self._by_num.get(key, [])
        return self._exact.get((denomination, key), []) + self._any_price.get(key, [])


def check_bonds(index: WinningIndex,
                bonds: Iterable[tuple[object, int | None, str | None]],
                default_denomination: int | None = None,
                owned_at: dict[int, str] | None = None) -> CheckSummary:
    """Check ``(number, price, ref)`` tuples.  ``price`` / ``ref`` may be None.

    Numbers that cannot be read are listed in ``invalid`` and the rest is still checked.
    A bond that wins in several draws (or whose number is drawn for several prizes) gives one
    ``Hit`` per draw.
    """
    started = time.perf_counter()
    summary = CheckSummary(draws_searched=len(index.draws), numbers_searched=index.count)
    for position, (raw, price, ref) in enumerate(bonds):
        try:
            display, key = normalize_number(raw)
        except NumberError as exc:
            summary.invalid.append((position, str(raw), str(exc)))
            continue
        summary.checked += 1
        price = price or default_denomination
        rows = index.lookup(key, price)
        if owned_at is not None:                      # sold bonds: only draws before the sale
            sold = owned_at.get(position)
            if sold:
                rows = [r for r in rows if r.draw_date < sold]
        if rows:
            summary.winners += 1
            summary.hits += [Hit(display, key, price, ref, row) for row in rows]
    summary.elapsed_ms = (time.perf_counter() - started) * 1000
    return summary


def open_readonly(path: str | Path) -> sqlite3.Connection:
    """Open a data file for reading only (never writes, takes no lock, so it can run beside the
    app).  Raises ``FileNotFoundError`` when there is no such file."""
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"No data file at {path}")
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=5,
                           check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def held_bonds(conn: sqlite3.Connection) -> list[tuple[str, int, str, str | None]]:
    """The bonds you hold: ``(number, price, ref, sold_date)`` (sold bonds carry the sale date;
    they still count for draws held before it)."""
    rows = conn.execute(
        "SELECT b.number, b.denomination, b.sold_date, c.name AS copy, b.position "
        "FROM bonds b LEFT JOIN copies c ON c.id = b.copy_id "
        "ORDER BY b.denomination, b.num").fetchall()
    return [(r["number"], r["denomination"],
             (f"{r['copy']} #{r['position']}" if r["copy"] and r["position"] else r["copy"] or ""),
             r["sold_date"]) for r in rows]
