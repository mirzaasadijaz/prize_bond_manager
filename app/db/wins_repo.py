"""Pending wins (the agent's output), the approval workflow, the win list and stats."""
from __future__ import annotations

from typing import Sequence

from ..config import FINAL_WIN_STATUS, WIN_STATUSES
from ..models import ApprovalResult, ScanResult
from .core import KEEP, chunks, now_iso  # noqa: F401  (KEEP is re-used by callers)

# A bond matches when it carries a winning number and has the draw's denomination
# (a draw with no denomination matches all).  Every bond that holds the number
# matches - the same number may sit in several copies, and when it is drawn they
# all win.  A bond that has already won still takes part in every later draw.
# A bond you sold takes part only in the draws held *before* the sale date: from the sale
# date on it belongs to the buyer.
MATCH_FROM = """
FROM winning_numbers w
JOIN draws d ON d.id = w.draw_id
JOIN bonds b ON b.num = w.num
             AND (d.denomination IS NULL OR b.denomination = d.denomination)
             AND (b.sale_id IS NULL OR d.draw_date < b.sold_date)
WHERE (:draw_id IS NULL OR w.draw_id = :draw_id)
"""

PENDING_SELECT = """
SELECT p.id AS pending_id, p.status AS pending_status, p.found_at, p.resolved_at, p.note,
       b.id AS bond_id, b.number AS bond_number, b.num AS bond_num, b.denomination,
       b.purchase_date, b.position, b.status AS bond_status, b.location AS bond_location,
       b.sale_id, b.sold_date, sl.buyer AS sold_to,
       c.id AS copy_id, c.name AS copy_name, c.first_number AS copy_first_number,
       c.size AS copy_size,
       d.id AS draw_id, d.draw_date, d.label AS draw_label, d.location AS draw_location,
       d.denomination AS draw_denomination,
       (SELECT COUNT(*) FROM wins x WHERE x.bond_id = b.id) AS times_won,
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
LEFT JOIN sales sl ON sl.id = b.sale_id
"""

# Wins sharing a draw, a denomination and a number are the same winning number
# held in several copies.  ``times_won`` / ``win_no``: the same bond can win in
# several draws; ``win_no`` says which one of them this row is (oldest first).
WIN_SELECT = """
SELECT w.*,
       (SELECT COUNT(*) FROM wins x
         WHERE x.num = w.num AND x.denomination = w.denomination
           AND x.draw_date = w.draw_date AND x.draw_id IS w.draw_id) AS same_number_count,
       CASE WHEN w.bond_id IS NULL THEN 1 ELSE
            (SELECT COUNT(*) FROM wins y WHERE y.bond_id = w.bond_id) END AS times_won,
       CASE WHEN w.bond_id IS NULL THEN 1 ELSE
            (SELECT COUNT(*) FROM wins y WHERE y.bond_id = w.bond_id
               AND (y.draw_date < w.draw_date
                    OR (y.draw_date = w.draw_date AND y.id <= w.id))) END AS win_no,
       bd.sold_date AS sold_date, sl.buyer AS sold_to
FROM wins w
LEFT JOIN bonds bd ON bd.id = w.bond_id
LEFT JOIN sales sl ON sl.id = bd.sale_id
"""


class WinsMixin:
    # ------------------------------------------------------------- agent scan
    def scan_for_matches(self, draw_id: int | None = None) -> ScanResult:
        """Compare every bond with the winning numbers; queue new matches as pending.

        Safe to run repeatedly: a (bond, winning number) pair is queued once, and
        pairs you already rejected are not queued again.
        """
        result = ScanResult(draw_id=draw_id, ran_at=now_iso())
        params = {"draw_id": draw_id}
        result.bonds_checked = self.conn.execute(
            "SELECT COUNT(*) FROM bonds WHERE sale_id IS NULL").fetchone()[0]
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
        """Turn approved pending matches into Win List records.

        When a number wins, every bond holding it wins: approving one pending
        match also approves the other *pending* bonds with the same winning
        number (``include_siblings``; ones you rejected stay rejected).

        Each approval writes a win row with a snapshot of the copy details
        (copy name, first bond number, position) and the draw's location.  The
        bond itself stays in your list and in every later draw - it can win
        again, and then gets another win row.  A pending row that no longer
        makes sense (bond edited, wrong denomination) is rejected with an
        explanation instead.
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
                elif row["sale_id"] is not None and row["sold_date"] <= row["draw_date"]:
                    reason = "The bond was sold on or before the draw date."
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
                        "copy_first_number, position, copy_size, approved_at, location, "
                        "bond_location) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (row["bond_id"], row["draw_id"], row["bond_number"], row["bond_num"],
                         row["denomination"], row["draw_date"], row["draw_label"],
                         row["prize_label"], row["prize_amount"], row["copy_id"],
                         row["copy_name"], row["copy_first_number"], row["position"],
                         row["copy_size"], stamp, row["draw_location"], row["bond_location"]),
                    ).lastrowid
                self.conn.execute(
                    "UPDATE pending_wins SET status = 'approved', resolved_at = ?, note = NULL "
                    "WHERE id = ?", (stamp, pid))
                result.win_ids.append(win_id)
                result.with_siblings += pid in extra
            if result.win_ids:
                shared = (f" ({result.with_siblings} of them because they hold the same number as "
                          "another winning bond)") if result.with_siblings else ""
                self.log("Wins approved",
                         f"{len(result.win_ids)} win(s) added to the Win List{shared}")
            if result.rejected:
                self.log("Pending wins dropped", f"{len(result.rejected)} could not be approved")
        return result

    def reject_pending(self, pending_ids: Sequence[int], note: str | None = None) -> int:
        """Dismiss pending wins; the bonds are not affected."""
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

    def update_win_details(self, win_ids: Sequence[int], *, location=KEEP, claim_status=KEEP,
                           feedback=KEEP) -> int:
        """Set the location, claim status and/or feedback note of wins.

        Only the fields you pass are changed (``KEEP`` leaves one alone); an empty
        text clears a location or a feedback note.
        """
        sets: list[str] = []
        values: list = []
        said: list[str] = []
        if claim_status is not KEEP:
            if claim_status not in WIN_STATUSES:
                raise ValueError(f"'{claim_status}' is not a win status "
                                 f"(use one of: {', '.join(WIN_STATUSES)}).")
            sets.append("claim_status = ?")
            values.append(claim_status)
            said.append(f"status {claim_status}")
        if location is not KEEP:
            sets.append("location = ?")
            values.append((location or "").strip() or None)
            said.append("location changed")
        if feedback is not KEEP:
            sets.append("feedback = ?")
            values.append((feedback or "").strip() or None)
            said.append("feedback changed")
        if not sets:
            return 0
        sets.append("updated_at = ?")
        values.append(now_iso())
        changed = 0
        with self.tx():
            for part in chunks(list(win_ids), 500):
                marks = ",".join("?" * len(part))
                changed += self.conn.execute(
                    f"UPDATE wins SET {', '.join(sets)} WHERE id IN ({marks})",
                    (*values, *part)).rowcount
            if changed:
                self.log("Win details updated", f"{changed} win(s): {', '.join(said)}")
        return changed

    def known_locations(self) -> list[str]:
        """Every location used so far (draws, wins, bonds, copies, sales), for suggestions
        while typing."""
        rows = self.conn.execute(
            " UNION ".join(f"SELECT location FROM {table} "
                           "WHERE location IS NOT NULL AND location <> ''"
                           for table in ("draws", "wins", "bonds", "copies", "sales"))
            + " ORDER BY 1 COLLATE NOCASE")
        return [r["location"] for r in rows]

    def revert_wins(self, win_ids: Sequence[int]) -> int:
        """Undo approvals: the win record is removed (the bond itself was never touched).

        The match goes to the 'Rejected' view of the pending list (note 'Win reverted'),
        so the agent does not queue it again; restore it from there to review it again.
        """
        reverted = 0
        stamp = now_iso()
        with self.tx():
            for wid in win_ids:
                win = self.conn.execute("SELECT * FROM wins WHERE id = ?", (wid,)).fetchone()
                if win is None:
                    continue
                if win["bond_id"] is not None:
                    self.conn.execute(
                        "UPDATE pending_wins SET status = 'rejected', resolved_at = ?, "
                        "note = 'Win reverted' WHERE bond_id = ? AND draw_id = ? "
                        "AND status = 'approved'", (stamp, win["bond_id"], win["draw_id"]))
                self.conn.execute("DELETE FROM wins WHERE id = ?", (wid,))
                reverted += 1
            if reverted:
                self.log("Wins reverted", f"{reverted} win(s) removed from the Win List")
        return reverted

    # ------------------------------------------------------------- dashboard
    def dashboard_stats(self) -> dict:
        one = lambda sql: self.conn.execute(sql).fetchone()  # noqa: E731
        bonds = one("SELECT COUNT(*) AS c, COALESCE(SUM(denomination), 0) AS v FROM bonds "
                    "WHERE sale_id IS NULL")
        sold = one("SELECT COUNT(*) AS c, COALESCE(SUM(denomination), 0) AS v FROM bonds "
                   "WHERE sale_id IS NOT NULL")
        sales = one("SELECT COUNT(*) AS c, COALESCE(SUM(total_amount), 0) AS t FROM sales")
        wins = one("SELECT COUNT(*) AS c, COALESCE(SUM(prize_amount), 0) AS s FROM wins")
        open_wins = self.conn.execute(
            "SELECT COUNT(*) AS c, COALESCE(SUM(prize_amount), 0) AS s FROM wins "
            "WHERE claim_status <> ?", (FINAL_WIN_STATUS,)).fetchone()
        repeat = one("SELECT COUNT(*) AS c FROM (SELECT 1 FROM wins WHERE bond_id IS NOT NULL "
                     "GROUP BY bond_id HAVING COUNT(*) > 1)")
        copies = one("SELECT COUNT(*) AS c FROM copies")
        # Numbers held in more than one bond (several copies): they win together.
        shared = one("SELECT COUNT(*) AS c FROM (SELECT 1 FROM bonds WHERE sale_id IS NULL "
                     "GROUP BY denomination, num HAVING COUNT(*) > 1)")
        by_denomination = self.query(
            "SELECT b.denomination, COALESCE(SUM(b.sale_id IS NULL), 0) AS bonds, "
            "COALESCE(SUM(b.sale_id IS NOT NULL), 0) AS sold, "
            "COALESCE(SUM(b.sale_id IS NULL AND "
            "EXISTS (SELECT 1 FROM wins x WHERE x.bond_id = b.id)), 0) AS won, "
            "COALESCE(SUM(CASE WHEN b.sale_id IS NULL THEN b.denomination END), 0) AS value "
            "FROM bonds b GROUP BY b.denomination ORDER BY b.denomination")
        return {
            "bond_count": bonds["c"], "bond_value": bonds["v"],
            "sold_count": sold["c"], "sold_value": sold["v"],
            "sale_count": sales["c"], "sale_total": sales["t"],
            "win_count": wins["c"], "prize_total": wins["s"],
            "unpaid_count": open_wins["c"], "unpaid_total": open_wins["s"],
            "repeat_winners": repeat["c"],
            "pending_count": self.pending_count(), "copy_count": copies["c"],
            "shared_numbers": shared["c"],
            "by_denomination": by_denomination,
        }
