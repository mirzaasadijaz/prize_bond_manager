"""Pending wins (the agent's output), the approval workflow, the win list and stats."""
from __future__ import annotations

from typing import Sequence

from ..models import ApprovalResult, ScanResult
from ..processing.numbers import normalize_number, NumberError
from .core import chunks, now_iso

# A bond matches when it is still waiting (status 'active'), carries a winning
# number and has the draw's denomination (a draw with no denomination matches all).
# Every bond that holds the number matches - the same number may sit in several
# copies, and when it is drawn they all win.
MATCH_FROM = """
FROM winning_numbers w
JOIN draws d ON d.id = w.draw_id
JOIN bonds b ON b.num = w.num AND b.status = 'active'
             AND (d.denomination IS NULL OR b.denomination = d.denomination)
WHERE (:draw_id IS NULL OR w.draw_id = :draw_id)
"""

PENDING_SELECT = """
SELECT p.id AS pending_id, p.status AS pending_status, p.found_at, p.resolved_at, p.note,
       b.id AS bond_id, b.number AS bond_number, b.num AS bond_num, b.denomination,
       b.purchase_date, b.position, b.status AS bond_status,
       c.id AS copy_id, c.name AS copy_name, c.first_number AS copy_first_number,
       c.size AS copy_size,
       d.id AS draw_id, d.draw_date, d.label AS draw_label, d.denomination AS draw_denomination,
       w.id AS winning_number_id, w.number AS winning_number, w.num AS win_num,
       w.prize_label, w.prize_amount,
       (SELECT COUNT(*) FROM pending_wins q
         WHERE q.winning_number_id = p.winning_number_id) AS same_number_count,
       CASE WHEN b.purchase_date IS NOT NULL AND b.purchase_date <> ''
                 AND b.purchase_date > d.draw_date
            THEN 'Bond bought after the draw date' ELSE '' END AS warning
FROM pending_wins p
JOIN bonds b ON b.id = p.bond_id
JOIN draws d ON d.id = p.draw_id
JOIN winning_numbers w ON w.id = p.winning_number_id
LEFT JOIN copies c ON c.id = b.copy_id
"""

# Wins sharing a draw, a denomination and a number are the same winning number
# held in several copies.
WIN_SELECT = """
SELECT w.*,
       (SELECT COUNT(*) FROM wins x
         WHERE x.num = w.num AND x.denomination = w.denomination
           AND x.draw_date = w.draw_date AND x.draw_id IS w.draw_id) AS same_number_count
FROM wins w
"""


class WinsMixin:
    # ------------------------------------------------------------- agent scan
    def scan_for_matches(self, draw_id: int | None = None) -> ScanResult:
        """Compare the waiting list with winning numbers; queue new matches as pending.

        Safe to run repeatedly: a (bond, winning number) pair is queued once, and
        pairs you already rejected are not queued again.
        """
        result = ScanResult(draw_id=draw_id, ran_at=now_iso())
        params = {"draw_id": draw_id}
        result.bonds_checked = self.conn.execute(
            "SELECT COUNT(*) FROM bonds WHERE status = 'active'").fetchone()[0]
        result.draws_checked = 1 if draw_id is not None else self.conn.execute(
            "SELECT COUNT(*) FROM draws").fetchone()[0]
        with self.tx():
            result.total_matches = self.conn.execute(
                "SELECT COUNT(*) " + MATCH_FROM, params).fetchone()[0]
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO pending_wins (bond_id, winning_number_id, draw_id, found_at) "
                "SELECT b.id, w.id, w.draw_id, :now " + MATCH_FROM,
                {**params, "now": result.ran_at})
            result.new_pending = max(cur.rowcount, 0)
        return result

    # ----------------------------------------------------------- pending list
    def list_pending(self, status: str = "pending") -> list[dict]:
        # Bonds holding the same winning number end up next to each other.
        return self.query(
            PENDING_SELECT + " WHERE p.status = ? "
            "ORDER BY d.draw_date DESC, d.id DESC, w.prize_label, w.num, c.name, b.position",
            (status,))

    def pending_count(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM pending_wins WHERE status = 'pending'").fetchone()[0]

    def pending_siblings(self, pending_ids: Sequence[int]) -> list[int]:
        """Ids of the *pending* matches that share a winning number with ``pending_ids``.

        These are the other bonds holding the same number (in other copies); the
        given ids themselves are included.  Matches you rejected are left alone.
        """
        found: list[int] = []
        for part in chunks(list(pending_ids), 500):
            marks = ",".join("?" * len(part))
            rows = self.conn.execute(
                "SELECT DISTINCT q.id FROM pending_wins p "
                "JOIN pending_wins q ON q.winning_number_id = p.winning_number_id "
                f"AND q.status = 'pending' WHERE p.status = 'pending' AND p.id IN ({marks}) "
                "ORDER BY q.id", tuple(part))
            found += [r["id"] for r in rows]
        return found

    def approve_pending(self, pending_ids: Sequence[int],
                        include_siblings: bool = True) -> ApprovalResult:
        """Move approved pending wins from the waiting list to the win list.

        When a number wins, every bond holding it wins: approving one pending
        match also approves the other *pending* bonds with the same winning
        number (``include_siblings``; ones you rejected stay rejected).

        Each approval writes a win row with a snapshot of the copy details
        (copy name, first bond number, position) and marks the bond as won.
        A pending row that no longer makes sense (bond edited, wrong
        denomination) is rejected with an explanation instead.
        """
        result = ApprovalResult()
        stamp = now_iso()
        ids = list(dict.fromkeys(pending_ids))
        extra: set[int] = set()
        if include_siblings:
            extra = {pid for pid in self.pending_siblings(ids)} - set(ids)
            ids += sorted(extra)
        with self.tx():
            for pid in ids:
                row = self.conn.execute(
                    PENDING_SELECT + " WHERE p.id = ? AND p.status = 'pending'", (pid,)).fetchone()
                if row is None:
                    result.rejected.append((pid, "It is no longer pending."))
                    continue
                reason = None
                if row["bond_num"] != row["win_num"]:
                    reason = "The bond number was edited after the match was found."
                elif (row["draw_denomination"] is not None
                      and row["draw_denomination"] != row["denomination"]):
                    reason = "The bond's denomination no longer matches the draw."
                if reason:
                    self.conn.execute(
                        "UPDATE pending_wins SET status = 'rejected', resolved_at = ?, note = ? "
                        "WHERE id = ?", (stamp, reason, pid))
                    result.rejected.append((pid, reason))
                    continue
                existing = self.conn.execute(
                    "SELECT id FROM wins WHERE bond_id = ? AND draw_id = ?",
                    (row["bond_id"], row["draw_id"])).fetchone()
                if existing:
                    win_id = existing["id"]
                else:
                    win_id = self.conn.execute(
                        "INSERT INTO wins (bond_id, draw_id, bond_number, num, denomination, "
                        "draw_date, draw_label, prize_label, prize_amount, copy_id, copy_name, "
                        "copy_first_number, position, copy_size, approved_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (row["bond_id"], row["draw_id"], row["bond_number"], row["bond_num"],
                         row["denomination"], row["draw_date"], row["draw_label"],
                         row["prize_label"], row["prize_amount"], row["copy_id"],
                         row["copy_name"], row["copy_first_number"], row["position"],
                         row["copy_size"], stamp),
                    ).lastrowid
                self.conn.execute("UPDATE bonds SET status = 'won' WHERE id = ?", (row["bond_id"],))
                self.conn.execute(
                    "UPDATE pending_wins SET status = 'approved', resolved_at = ?, note = NULL "
                    "WHERE id = ?", (stamp, pid))
                result.win_ids.append(win_id)
                result.with_siblings += pid in extra
            if result.win_ids:
                shared = (f" ({result.with_siblings} of them because they hold the same number as "
                          "another winning bond)") if result.with_siblings else ""
                self.log("Wins approved",
                         f"{len(result.win_ids)} bond(s) moved from the waiting list to the "
                         f"win list{shared}")
            if result.rejected:
                self.log("Pending wins dropped", f"{len(result.rejected)} could not be approved")
        return result

    def reject_pending(self, pending_ids: Sequence[int], note: str | None = None) -> int:
        """Dismiss pending wins; the bonds simply stay in the waiting list."""
        changed = 0
        stamp = now_iso()
        with self.tx():
            for pid in pending_ids:
                changed += self.conn.execute(
                    "UPDATE pending_wins SET status = 'rejected', resolved_at = ?, note = ? "
                    "WHERE id = ? AND status = 'pending'", (stamp, note, pid)).rowcount
            if changed:
                self.log("Pending wins rejected", f"{changed} match(es) dismissed")
        return changed

    def restore_pending(self, pending_ids: Sequence[int]) -> int:
        """Bring rejected matches back into the pending list."""
        changed = 0
        with self.tx():
            for pid in pending_ids:
                changed += self.conn.execute(
                    "UPDATE pending_wins SET status = 'pending', resolved_at = NULL, note = NULL "
                    "WHERE id = ? AND status = 'rejected'", (pid,)).rowcount
            if changed:
                self.log("Pending wins restored", f"{changed} match(es) back in the pending list")
        return changed

    # --------------------------------------------------------------- win list
    def list_wins(self) -> list[dict]:
        # Wins of one number (held in several copies) stay together, copy by copy.
        return self.query(WIN_SELECT + " ORDER BY w.draw_date DESC, w.draw_id DESC, w.prize_label, "
                          "w.num, w.copy_name, w.position, w.id")

    def get_win(self, win_id: int) -> dict | None:
        rows = self.query(WIN_SELECT + " WHERE w.id = ?", (win_id,))
        return rows[0] if rows else None

    def recent_wins(self, limit: int = 8) -> list[dict]:
        return self.query(WIN_SELECT + " ORDER BY w.approved_at DESC, w.id DESC LIMIT ?", (limit,))

    def revert_wins(self, win_ids: Sequence[int]) -> int:
        """Undo approvals: the bond returns to the waiting list, the win is removed."""
        reverted = 0
        stamp = now_iso()
        with self.tx():
            for wid in win_ids:
                win = self.conn.execute("SELECT * FROM wins WHERE id = ?", (wid,)).fetchone()
                if win is None:
                    continue
                if win["bond_id"] is not None:
                    others = self.conn.execute(
                        "SELECT COUNT(*) FROM wins WHERE bond_id = ? AND id <> ?",
                        (win["bond_id"], wid)).fetchone()[0]
                    if others == 0:
                        self.conn.execute("UPDATE bonds SET status = 'active' WHERE id = ?",
                                          (win["bond_id"],))
                    self.conn.execute(
                        "UPDATE pending_wins SET status = 'rejected', resolved_at = ?, "
                        "note = 'Win reverted' WHERE bond_id = ? AND draw_id = ? "
                        "AND status = 'approved'", (stamp, win["bond_id"], win["draw_id"]))
                else:
                    self._recreate_bond_from_win(win)
                self.conn.execute("DELETE FROM wins WHERE id = ?", (wid,))
                reverted += 1
            if reverted:
                self.log("Wins reverted", f"{reverted} bond(s) moved back to the waiting list")
        return reverted

    def _recreate_bond_from_win(self, win) -> None:
        """The bond row was deleted after the win; rebuild it from the snapshot."""
        try:
            display, key = normalize_number(win["bond_number"])
        except NumberError:
            return
        copy_id, position = win["copy_id"], win["position"]
        if copy_id is not None and position is not None:
            # Back into its old slot if the copy still exists and the slot / number is free;
            # otherwise it returns as a loose bond (other bonds may hold the same number).
            taken = self.conn.execute(
                "SELECT 1 FROM bonds WHERE copy_id = ? "
                "AND (position = ? OR (denomination = ? AND num = ?))",
                (copy_id, position, win["denomination"], key)).fetchone()
            if taken or self.get_copy(copy_id) is None:
                copy_id, position = None, None
        else:
            copy_id, position = None, None
        self._insert_bonds([(display, key, position, None)], win["denomination"], copy_id)

    # ------------------------------------------------------------- dashboard
    def dashboard_stats(self) -> dict:
        one = lambda sql: self.conn.execute(sql).fetchone()  # noqa: E731
        active = one("SELECT COUNT(*) AS c, COALESCE(SUM(denomination), 0) AS v "
                     "FROM bonds WHERE status = 'active'")
        total = one("SELECT COUNT(*) AS c, COALESCE(SUM(denomination), 0) AS v FROM bonds")
        wins = one("SELECT COUNT(*) AS c, COALESCE(SUM(prize_amount), 0) AS s FROM wins")
        copies = one("SELECT COUNT(*) AS c FROM copies")
        # Numbers waiting in more than one bond (several copies): they win together.
        shared = one("SELECT COUNT(*) AS c FROM (SELECT 1 FROM bonds WHERE status = 'active' "
                     "GROUP BY denomination, num HAVING COUNT(*) > 1)")
        by_denomination = self.query(
            "SELECT denomination, COALESCE(SUM(status = 'active'), 0) AS active, "
            "COALESCE(SUM(status = 'won'), 0) AS won, "
            "COALESCE(SUM(CASE WHEN status = 'active' THEN denomination ELSE 0 END), 0) AS value "
            "FROM bonds GROUP BY denomination ORDER BY denomination")
        return {
            "active_count": active["c"], "active_value": active["v"],
            "total_count": total["c"], "total_value": total["v"],
            "win_count": wins["c"], "prize_total": wins["s"],
            "pending_count": self.pending_count(), "copy_count": copies["c"],
            "shared_numbers": shared["c"],
            "by_denomination": by_denomination,
        }
