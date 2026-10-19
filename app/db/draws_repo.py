"""Draws and their winning numbers."""
from __future__ import annotations

from typing import Sequence

from ..processing.numbers import NumberError, normalize_number
from .core import KEEP, chunks, now_iso


class WinningNumberError(ValueError):
    """The edit cannot be saved (the draw already has that number, or it is not a number)."""


class DrawsMixin:
    def add_draw(self, draw_date: str, denomination: int | None, label: str = "",
                 location: str = "", source: str = "Manual", source_url: str | None = None,
                 draw_no: int | None = None) -> int:
        """Create a draw.  ``denomination=None`` means it applies to every denomination.

        ``location`` is where the draw was held; wins found in this draw start with it.
        ``source`` says how the numbers got here: 'Manual' (typed or imported by you) or the
        name of the web site they were fetched from (``source_url`` is the page or file).
        """
        with self.tx():
            cur = self.conn.execute(
                "INSERT INTO draws (draw_date, denomination, label, location, created_at, "
                "source, source_url, draw_no) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (draw_date, denomination, (label or "").strip() or None,
                 (location or "").strip() or None, now_iso(),
                 (source or "").strip() or "Manual", source_url or None, draw_no))
            scope = f"Rs {denomination}" if denomination else "all denominations"
            place = (location or "").strip()
            how = "" if (source or "Manual") == "Manual" else f"fetched from {source}"
            self.log("Draw recorded", ", ".join(
                x for x in (draw_date, scope, (label or "").strip(), place, how) if x))
        return cur.lastrowid

    def find_draw(self, draw_date: str, denomination: int | None) -> dict | None:
        """The draw already recorded for this date and denomination, if there is one."""
        rows = self.query(
            "SELECT * FROM draws WHERE draw_date = ? AND denomination IS ? ORDER BY id LIMIT 1",
            (draw_date, denomination))
        return rows[0] if rows else None

    def get_draw(self, draw_id: int) -> dict | None:
        rows = self.query("SELECT * FROM draws WHERE id = ?", (draw_id,))
        return rows[0] if rows else None

    def list_draws(self) -> list[dict]:
        return self.query(
            """
            SELECT d.id, d.draw_date, d.denomination, d.label, d.location, d.created_at,
                   COALESCE(d.source, 'Manual') AS source, d.source_url, d.draw_no,
                   (SELECT COUNT(*) FROM winning_numbers w WHERE w.draw_id = d.id) AS numbers,
                   (SELECT COUNT(*) FROM pending_wins p
                     WHERE p.draw_id = d.id AND p.status = 'pending') AS pending,
                   (SELECT COUNT(*) FROM wins x WHERE x.draw_id = d.id) AS wins
            FROM draws d ORDER BY d.draw_date DESC, d.id DESC
            """)

    def draw_numbers(self, draw_id: int) -> list[dict]:
        return self.query(
            "SELECT id, number, num, prize_label, prize_amount FROM winning_numbers "
            "WHERE draw_id = ? ORDER BY prize_label, num", (draw_id,))

    def add_winning_numbers(
            self, draw_id: int,
            items: Sequence[tuple[str, int, str, int | None]]) -> tuple[int, int]:
        """Add ``(display, key, prize_label, prize_amount)`` rows to a draw.

        Returns ``(added, skipped)``; numbers already in the draw are skipped.
        """
        seen = {r["num"] for r in self.conn.execute(
            "SELECT num FROM winning_numbers WHERE draw_id = ?", (draw_id,))}
        fresh = []
        for display, key, label, amount in items:
            if key in seen:
                continue
            seen.add(key)
            fresh.append((draw_id, display, key, (label or "").strip() or "Winner", amount))
        if fresh:
            with self.tx():
                self.conn.executemany(
                    "INSERT INTO winning_numbers (draw_id, number, num, prize_label, "
                    "prize_amount) VALUES (?, ?, ?, ?, ?)", fresh)
                self.log("Winning numbers added", f"{len(fresh)} number(s) to draw #{draw_id}")
        return len(fresh), len(items) - len(fresh)

    def update_winning_number(self, number_id: int, number, prize_label=KEEP,
                              prize_amount=KEEP) -> bool:
        """Change one winning number: the number itself, its prize and its prize amount.

        Returns True when the number itself changed.  Then the waiting matches made with the old
        number are dropped (run the agent for the draw again to find the new ones); wins you
        already approved keep their own saved copy of the prize.
        """
        row = self.conn.execute(
            "SELECT draw_id, number, num FROM winning_numbers WHERE id = ?", (number_id,)).fetchone()
        if row is None:
            raise WinningNumberError("That winning number no longer exists.")
        try:
            display, key = normalize_number(number)
        except NumberError as exc:
            raise WinningNumberError(f"'{number}' is not a valid bond number ({exc}).") from exc
        changed = key != row["num"]
        if changed and self.conn.execute(
                "SELECT 1 FROM winning_numbers WHERE draw_id = ? AND num = ? AND id <> ?",
                (row["draw_id"], key, number_id)).fetchone():
            raise WinningNumberError(f"This draw already has the winning number {display}.")
        with self.tx():
            self.conn.execute("UPDATE winning_numbers SET number = ?, num = ? WHERE id = ?",
                              (display, key, number_id))
            if prize_label is not KEEP:
                self.conn.execute("UPDATE winning_numbers SET prize_label = ? WHERE id = ?",
                                  ((prize_label or "").strip() or "Winner", number_id))
            if prize_amount is not KEEP:
                self.conn.execute("UPDATE winning_numbers SET prize_amount = ? WHERE id = ?",
                                  (prize_amount, number_id))
            if changed:
                self.conn.execute("DELETE FROM pending_wins WHERE winning_number_id = ? "
                                  "AND status <> 'approved'", (number_id,))
            self.log("Winning number edited", f"{row['number']} -> {display} in draw #{row['draw_id']}"
                     if changed else f"{display} in draw #{row['draw_id']}")
        return changed

    def update_prizes(self, number_ids: Sequence[int], prize_label=KEEP, prize_amount=KEEP) -> int:
        """Set the prize name and/or the prize amount of many winning numbers at once
        (``KEEP`` leaves that field as it is; an amount of ``None`` clears it)."""
        if prize_label is KEEP and prize_amount is KEEP:
            return 0
        changed = 0
        with self.tx():
            for part in chunks(list(number_ids), 500):
                marks = ",".join("?" * len(part))
                if prize_label is not KEEP:
                    changed = max(changed, self.conn.execute(
                        f"UPDATE winning_numbers SET prize_label = ? WHERE id IN ({marks})",
                        ((prize_label or "").strip() or "Winner", *part)).rowcount)
                if prize_amount is not KEEP:
                    changed = max(changed, self.conn.execute(
                        f"UPDATE winning_numbers SET prize_amount = ? WHERE id IN ({marks})",
                        (prize_amount, *part)).rowcount)
            self.log("Winning numbers edited", f"prize of {len(number_ids)} number(s) changed")
        return len(number_ids)

    def set_prize_tiers(self, draw_id: int,
                        tiers: Sequence[tuple[str, int | None, Sequence[tuple[str, int]]]],
                        rest: tuple[str, int | None] | None = None) -> tuple[int, int]:
        """Give the numbers of a draw their prizes by tier.

        ``tiers``: ``(prize name, amount, [(display, key), ...])`` - those numbers get that prize
        and amount (a number the draw does not have yet is added).  ``rest``: ``(name, amount)``
        for every number that is not listed (None leaves them as they are).
        Returns ``(numbers changed, numbers added)``.
        """
        def clean(name) -> str:
            return (name or "").strip() or "Winner"

        with self.tx():
            known = {r["num"]: r["id"] for r in self.conn.execute(
                "SELECT id, num FROM winning_numbers WHERE draw_id = ?", (draw_id,))}
            touched: set[int] = set()
            if rest is not None:
                self.conn.execute(
                    "UPDATE winning_numbers SET prize_label = ?, prize_amount = ? "
                    "WHERE draw_id = ?", (clean(rest[0]), rest[1], draw_id))
                touched.update(known.values())
            added = 0
            for name, amount, numbers in tiers:
                for display, key in numbers:
                    if key in known:
                        self.conn.execute(
                            "UPDATE winning_numbers SET prize_label = ?, prize_amount = ? "
                            "WHERE id = ?", (clean(name), amount, known[key]))
                        touched.add(known[key])
                    else:
                        known[key] = self.conn.execute(
                            "INSERT INTO winning_numbers (draw_id, number, num, prize_label, "
                            "prize_amount) VALUES (?, ?, ?, ?, ?)",
                            (draw_id, display, key, clean(name), amount)).lastrowid
                        added += 1
            self.log("Prizes set by tier", f"draw #{draw_id}: {len(touched)} number(s) changed, "
                     f"{added} added")
        return len(touched), added

    def delete_draw(self, draw_id: int) -> None:
        """Delete a draw with its numbers and any still-pending matches.

        Wins that were already approved stay in the win list (they keep their
        own snapshot of the draw date and prize).
        """
        draw = self.get_draw(draw_id)
        if draw is None:
            return
        with self.tx():
            self.conn.execute("DELETE FROM draws WHERE id = ?", (draw_id,))
            self.log("Draw deleted", f"{draw['draw_date']} {draw['label'] or ''}".strip())
