"""Draws and their winning numbers."""
from __future__ import annotations

from typing import Sequence

from .core import now_iso


class DrawsMixin:
    def add_draw(self, draw_date: str, denomination: int | None, label: str = "",
                 location: str = "") -> int:
        """Create a draw.  ``denomination=None`` means it applies to every denomination.

        ``location`` is where the draw was held; wins found in this draw start with it.
        """
        with self.tx():
            cur = self.conn.execute(
                "INSERT INTO draws (draw_date, denomination, label, location, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (draw_date, denomination, (label or "").strip() or None,
                 (location or "").strip() or None, now_iso()))
            scope = f"Rs {denomination}" if denomination else "all denominations"
            place = (location or "").strip()
            self.log("Draw recorded", ", ".join(
                x for x in (draw_date, scope, (label or "").strip(), place) if x))
        return cur.lastrowid

    def get_draw(self, draw_id: int) -> dict | None:
        rows = self.query("SELECT * FROM draws WHERE id = ?", (draw_id,))
        return rows[0] if rows else None

    def list_draws(self) -> list[dict]:
        return self.query(
            """
            SELECT d.id, d.draw_date, d.denomination, d.label, d.location, d.created_at,
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
