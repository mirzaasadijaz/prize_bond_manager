"""Bond and copy (book) operations."""
from __future__ import annotations

import re
from typing import Collection, Sequence

from ..models import AddResult
from ..processing.numbers import normalize_number
from .core import KEEP, chunks, now_iso


class DuplicateBondError(ValueError):
    """The copy already holds a bond with that number (other copies may)."""


class PositionTakenError(ValueError):
    """Another bond already occupies that position in the copy."""


class CopyNameError(ValueError):
    """A copy with that name already exists."""


# ``same_count`` = how many bonds you hold with this number (this denomination), including
# the bond itself.  Above 1 means the number sits in several copies: when it is
# drawn, every one of those bonds wins.  A sold bond has no "same number" partners (0).
# ``times_won`` = how often this very bond has won (a bond stays in play after a win, so it
# can win again).  ``sale_id`` / ``sold_date`` / ``sold_to`` are set once the bond is sold.
BOND_SELECT = """
SELECT b.id, b.number, b.num, b.denomination, b.purchase_date, b.status,
       b.copy_id, b.position, b.created_at, b.location,
       b.sale_id, b.sold_date, sl.buyer AS sold_to,
       b.last_prize_date, b.highlight, c.highlight AS copy_highlight,
       c.name AS copy_name, c.first_number AS copy_first_number, c.size AS copy_size,
       c.location AS copy_location,
       COALESCE(pw.cnt, 0) AS pending_count,
       CASE WHEN b.sale_id IS NOT NULL THEN 0 ELSE
            (SELECT COUNT(*) FROM bonds o
              WHERE o.num = b.num AND o.denomination = b.denomination
                AND o.sale_id IS NULL) END AS same_count,
       (SELECT COUNT(*) FROM wins x WHERE x.bond_id = b.id) AS times_won
FROM bonds b
LEFT JOIN copies c ON c.id = b.copy_id
LEFT JOIN sales sl ON sl.id = b.sale_id
LEFT JOIN (SELECT bond_id, COUNT(*) AS cnt FROM pending_wins
           WHERE status = 'pending' GROUP BY bond_id) pw ON pw.bond_id = b.id
"""


class BondsMixin:
    # ------------------------------------------------------------ queries
    def list_bonds(self, won: bool | None = None, denomination: int | None = None,
                   number_from: int | None = None, number_to: int | None = None,
                   date_from: str | None = None, date_to: str | None = None,
                   copy_id: int | None = None, sold: bool | None = None) -> list[dict]:
        """Bonds, optionally filtered.  ``sold``: None = all, False = the ones you still
        hold, True = the ones you sold."""
        where: list[str] = []
        params: list = []
        if sold is not None:
            where.append("b.sale_id IS " + ("NOT NULL" if sold else "NULL"))
        if won is not None:                  # True: has won before, False: never won
            where.append(("" if won else "NOT ") +
                         "EXISTS (SELECT 1 FROM wins x WHERE x.bond_id = b.id)")
        if denomination is not None:
            where.append("b.denomination = ?")
            params.append(denomination)
        if number_from is not None:
            where.append("b.num >= ?")
            params.append(number_from)
        if number_to is not None:
            where.append("b.num <= ?")
            params.append(number_to)
        if date_from:
            where.append("b.purchase_date >= ?")
            params.append(date_from)
        if date_to:
            where.append("b.purchase_date <= ?")
            params.append(date_to)
        if copy_id is not None:
            where.append("b.copy_id = ?")
            params.append(copy_id)
        sql = BOND_SELECT + (" WHERE " + " AND ".join(where) if where else "")
        return self.query(sql + " ORDER BY b.denomination, b.num", params)

    def get_bond(self, bond_id: int) -> dict | None:
        rows = self.query(BOND_SELECT + " WHERE b.id = ?", (bond_id,))
        return rows[0] if rows else None

    def denominations(self) -> list[int]:
        return [r["denomination"] for r in self.conn.execute(
            "SELECT DISTINCT denomination FROM bonds ORDER BY denomination")]

    def held_keys(self, denomination: int, keys: Sequence[int],
                  copy_id: int | None = None) -> set[int]:
        """Which of ``keys`` are already held as bonds of this denomination.

        Every bond you still hold counts (in any copy or none; sold bonds do not).  With
        ``copy_id`` only that one copy is checked - and there sold bonds count too, because
        they still sit in the copy and a copy never holds a number twice.
        """
        found: set[int] = set()
        for part in chunks(list(keys), 500):
            marks = ",".join("?" * len(part))
            sql = f"SELECT num FROM bonds WHERE denomination = ? AND num IN ({marks})"
            params: list = [denomination, *part]
            if copy_id is not None:
                sql += " AND copy_id = ?"
                params.append(copy_id)
            else:
                sql += " AND sale_id IS NULL"
            found.update(r["num"] for r in self.conn.execute(sql, params))
        return found

    def _screen(self, numbers: Sequence[tuple[str, int]], denomination: int,
                skip_existing: bool = False, skip_keys: Collection[int] | None = None,
                copy_id: int | None = None) -> tuple[list[int], list[str], int]:
        """Decide which of ``numbers`` get inserted.

        Several bonds may hold the same number (in different copies), so a number
        is only left out when
          * it repeats inside ``numbers`` itself (kept once),
          * ``copy_id`` is given and that copy already holds it (a copy never holds
            a number twice),
          * ``skip_existing`` is on and any bond already holds it, or
          * it is in ``skip_keys`` - a snapshot of the numbers held *before* a multi
            copy add/import started, so copies added together may still share numbers.
        Returns ``(indexes to insert, display text of the numbers left out, how many
        of the inserted ones share their number with bonds that already exist)``.
        """
        keys = [k for _, k in numbers]
        held = self.held_keys(denomination, keys)
        in_copy = self.held_keys(denomination, keys, copy_id) if copy_id is not None else set()
        skip = set(skip_keys or ())
        if skip_existing:
            skip |= held
        keep: list[int] = []
        skipped: list[str] = []
        seen: set[int] = set()
        shared = 0
        for i, (display, key) in enumerate(numbers):
            if key in seen or key in in_copy or key in skip:
                skipped.append(display)
                continue
            seen.add(key)
            keep.append(i)
            shared += key in held
        return keep, skipped, shared

    # ------------------------------------------------------------ adding
    def _insert_bonds(self, items: list[tuple[str, int, int | None, str | None, str | None]],
                      denomination: int, copy_id: int | None = None) -> None:
        """Insert ``(display, key, position, purchase_date, location)`` rows as active bonds."""
        now = now_iso()
        self.conn.executemany(
            "INSERT INTO bonds (number, num, denomination, purchase_date, status, "
            "copy_id, position, created_at, location) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?)",
            [(d, k, denomination, date or None, copy_id, pos, now, (where or "").strip() or None)
             for d, k, pos, date, where in items])

    @staticmethod
    def _locations(count: int, location: str | None,
                   locations: Sequence[str | None] | None) -> list[str | None]:
        """One optional location per bond: its own (``locations``) or the common one."""
        common = (location or "").strip() or None
        if not locations:
            return [common] * count
        return [((loc or "").strip() or common) for loc in locations]

    def add_loose_bonds(self, numbers: list[tuple[str, int]], denomination: int,
                        purchase_date: str | None = None,
                        dates: Sequence[str | None] | None = None,
                        skip_existing: bool = False,
                        skip_keys: Collection[int] | None = None,
                        location: str | None = None,
                        locations: Sequence[str | None] | None = None) -> AddResult:
        """Add bonds that do not belong to any copy.

        ``dates`` optionally gives one purchase date per number (overrides
        ``purchase_date``); ``location`` is the optional place all of them are kept
        (``locations`` gives one per number).  A number that is already held is added again unless
        ``skip_existing`` is set (or it is in ``skip_keys``); if it is drawn, all
        bonds holding it win.
        """
        result = AddResult()
        keep, result.skipped_duplicates, result.shared = self._screen(
            numbers, denomination, skip_existing, skip_keys)
        where = self._locations(len(numbers), location, locations)
        fresh = [(numbers[i][0], numbers[i][1], None, dates[i] if dates else purchase_date,
                  where[i]) for i in keep]
        if fresh:
            with self.tx():
                self._insert_bonds(fresh, denomination)
                self.log("Bonds added", f"{len(fresh)} bond(s) of Rs {denomination} (no copy)")
        result.added = len(fresh)
        return result

    def add_copy(self, name: str, numbers: list[tuple[str, int]], denomination: int,
                 purchase_date: str | None = None, note: str | None = None,
                 dates: Sequence[str | None] | None = None,
                 positions: Sequence[int] | None = None,
                 skip_existing: bool = False,
                 skip_keys: Collection[int] | None = None,
                 location: str | None = None,
                 locations: Sequence[str | None] | None = None) -> AddResult:
        """Create a copy whose bonds are ``numbers`` in physical order.

        Positions follow the order given (or ``positions`` when supplied, e.g.
        from a file), whatever the numbers are, so copies need not share a range
        or a sequence.  The same number may appear in other copies (they all win
        together); with ``skip_existing`` (or ``skip_keys``) numbers held elsewhere
        are left out.  Numbers that are left out still occupy their position in the
        copy.  ``location`` (optional) is where the copy is kept: it is stored on the copy and
        on each of its bonds (``locations`` gives a place per bond; the copy then shows the
        place all of its bonds share, if there is one).
        """
        result = AddResult()
        if not numbers:
            return result
        count = len(numbers)
        slots = list(positions) if positions else list(range(1, count + 1))
        keep, result.skipped_duplicates, result.shared = self._screen(
            numbers, denomination, skip_existing, skip_keys)
        where = self._locations(count, location, locations)
        fresh = [(numbers[i][0], numbers[i][1], slots[i], dates[i] if dates else purchase_date,
                  where[i]) for i in keep]
        if not fresh:
            return result
        kept_places = {fresh_item[4] for fresh_item in fresh}
        copy_location = next(iter(kept_places)) if len(kept_places) == 1 else None
        first_number = numbers[min(range(count), key=lambda i: slots[i])][0]
        with self.tx():
            wanted = (name or "").strip() or "Copy"
            final = self.unique_copy_name(wanted)
            if final != wanted:
                result.renamed_copies.append((wanted, final))
            cur = self.conn.execute(
                "INSERT INTO copies (name, first_number, size, note, created_at, location) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (final, first_number, max(slots), note or None, now_iso(), copy_location))
            copy_id = cur.lastrowid
            self._insert_bonds(fresh, denomination, copy_id)
            self.log("Copy added",
                     f"{final}: {len(fresh)} bond(s) of Rs {denomination}, "
                     f"{max(slots)} positions, first bond {first_number}")
        result.added = len(fresh)
        result.copy_ids.append(copy_id)
        result.copy_names.append(final)
        return result

    def _next_position(self, copy_id: int) -> int:
        row = self.conn.execute(
            "SELECT MAX(position) AS m FROM bonds WHERE copy_id = ?", (copy_id,)).fetchone()
        copy = self.get_copy(copy_id)
        return max(row["m"] or 0, copy["size"] if copy else 0) + 1

    def append_to_copy(self, copy_id: int, numbers: list[tuple[str, int]], denomination: int,
                       purchase_date: str | None = None,
                       dates: Sequence[str | None] | None = None,
                       skip_existing: bool = False,
                       skip_keys: Collection[int] | None = None,
                       location: str | None = None,
                       locations: Sequence[str | None] | None = None) -> AddResult:
        """Add more bonds at the end of an existing copy.

        Numbers the copy already holds are always left out (a copy never holds a
        number twice); numbers held by other copies are added unless
        ``skip_existing`` is set (or they are in ``skip_keys``).
        """
        copy = self.get_copy(copy_id)
        if copy is None:
            raise ValueError("That copy no longer exists.")
        result = AddResult()
        keep, result.skipped_duplicates, result.shared = self._screen(
            numbers, denomination, skip_existing, skip_keys, copy_id)
        start = self._next_position(copy_id)
        where = self._locations(len(numbers), location, locations)
        fresh = [(numbers[i][0], numbers[i][1], start + i, dates[i] if dates else purchase_date,
                  where[i]) for i in keep]
        if fresh:
            with self.tx():
                self._insert_bonds(fresh, denomination, copy_id)
                self.conn.execute("UPDATE copies SET size = ? WHERE id = ?",
                                  (start + len(numbers) - 1, copy_id))
                self.log("Bonds added to copy",
                         f"{copy['name']}: {len(fresh)} bond(s) of Rs {denomination}")
            result.copy_ids.append(copy_id)
        result.added = len(fresh)
        return result

    # ------------------------------------------------- edit / delete bonds
    def update_bond(self, bond_id: int, number, denomination: int,
                    purchase_date: str | None, copy_id: int | None,
                    position: int | None, location=KEEP, last_prize_date=KEEP) -> None:
        bond = self.get_bond(bond_id)
        if bond is None:
            raise ValueError("That bond no longer exists.")
        if bond["sale_id"] is not None:
            raise ValueError(f"Bond {bond['number']} was sold on {bond['sold_date']}. Undo the "
                             "sale on the Sales page before changing it.")
        display, key = normalize_number(number)
        if copy_id is not None:
            # Other copies may hold the same number; the same copy may not.
            dup = self.conn.execute(
                "SELECT id FROM bonds WHERE copy_id = ? AND denomination = ? AND num = ? "
                "AND id <> ?", (copy_id, denomination, key, bond_id)).fetchone()
            if dup:
                raise DuplicateBondError(
                    f"That copy already holds bond {display} (Rs {denomination}). "
                    "Different copies may hold the same number, one copy may not.")
        if copy_id is None:
            position = None
        else:
            if position is None:
                same_copy = bond["copy_id"] == copy_id and bond["position"]
                position = bond["position"] if same_copy else self._next_position(copy_id)
            taken = self.conn.execute(
                "SELECT number FROM bonds WHERE copy_id = ? AND position = ? AND id <> ?",
                (copy_id, position, bond_id)).fetchone()
            if taken:
                raise PositionTakenError(
                    f"Position {position} of that copy is already used by bond {taken['number']}.")
        with self.tx():
            self.conn.execute(
                "UPDATE bonds SET number = ?, num = ?, denomination = ?, purchase_date = ?, "
                "copy_id = ?, position = ? WHERE id = ?",
                (display, key, denomination, purchase_date or None, copy_id, position, bond_id))
            if location is not KEEP:
                self.conn.execute("UPDATE bonds SET location = ? WHERE id = ?",
                                  ((location or "").strip() or None, bond_id))
            if last_prize_date is not KEEP:
                self.conn.execute("UPDATE bonds SET last_prize_date = ? WHERE id = ?",
                                  (last_prize_date or None, bond_id))
            self._drop_skipped_pending(bond_id)
            if copy_id is not None:
                self.conn.execute("UPDATE copies SET size = MAX(size, ?) WHERE id = ?",
                                  (position, copy_id))
                if position == 1:
                    self.conn.execute("UPDATE copies SET first_number = ? WHERE id = ?",
                                      (display, copy_id))
            self.log("Bond edited", f"{display} (Rs {denomination})")

    def _drop_skipped_pending(self, bond_id: int) -> None:
        """Waiting matches of a draw the bond no longer takes part in (it was bought after the
        draw, or the draw is not newer than the date its last prize was taken) are removed."""
        self.conn.execute(
            "DELETE FROM pending_wins WHERE status = 'pending' AND bond_id = ? AND draw_id IN ("
            "SELECT d.id FROM draws d JOIN bonds b ON b.id = ? WHERE "
            "(b.purchase_date IS NOT NULL AND b.purchase_date <> '' "
            " AND b.purchase_date > d.draw_date) "
            "OR (b.last_prize_date IS NOT NULL AND b.last_prize_date <> '' "
            " AND d.draw_date <= b.last_prize_date))", (bond_id, bond_id))

    def set_highlight(self, kind: str, ids: Sequence[int], colour: str | None) -> int:
        """Give bonds (``kind='bonds'``) or copies (``kind='copies'``) a colour, ``#RRGGBB``;
        ``None`` takes the colour away again."""
        if kind not in ("bonds", "copies"):
            raise ValueError("kind must be 'bonds' or 'copies'")
        if colour is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", colour):
            raise ValueError("The colour must look like #FDE68A.")
        changed = 0
        with self.tx():
            for part in chunks(list(ids), 500):
                marks = ",".join("?" * len(part))
                changed += self.conn.execute(
                    f"UPDATE {kind} SET highlight = ? WHERE id IN ({marks})",
                    (colour, *part)).rowcount
        return changed

    def delete_bonds(self, ids: Sequence[int]) -> int:
        removed = 0
        with self.tx():
            for part in chunks(list(ids), 500):
                marks = ",".join("?" * len(part))
                removed += self.conn.execute(
                    f"DELETE FROM bonds WHERE id IN ({marks})", tuple(part)).rowcount
            if removed:
                self.log("Bonds deleted", f"{removed} bond(s) removed")
        return removed

    # ------------------------------------------------------------- copies
    def list_copies(self) -> list[dict]:
        return self.query(
            """
            SELECT c.id, c.name, c.first_number, c.size, c.note, c.location, c.created_at,
                   c.highlight,
                   COALESCE(SUM(b.sale_id IS NULL), 0) AS bonds,
                   COALESCE(SUM(b.sale_id IS NOT NULL), 0) AS sold,
                   COALESCE(SUM(EXISTS (SELECT 1 FROM wins x WHERE x.bond_id = b.id)), 0) AS won,
                   MIN(b.denomination) AS min_denomination,
                   MAX(b.denomination) AS max_denomination,
                   MIN(b.purchase_date) AS purchase_date
            FROM copies c LEFT JOIN bonds b ON b.copy_id = c.id
            GROUP BY c.id ORDER BY c.id
            """)

    def get_copy(self, copy_id: int) -> dict | None:
        rows = self.query("SELECT * FROM copies WHERE id = ?", (copy_id,))
        return rows[0] if rows else None

    def copy_bonds(self, copy_id: int) -> list[dict]:
        return self.query(BOND_SELECT + " WHERE b.copy_id = ? ORDER BY b.position, b.num",
                          (copy_id,))

    def copy_name_taken(self, name: str, exclude_id: int | None = None) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM copies WHERE name = ? COLLATE NOCASE AND id <> ?",
            (name.strip(), -1 if exclude_id is None else exclude_id)).fetchone()
        return row is not None

    def unique_copy_name(self, base: str, exclude_id: int | None = None) -> str:
        base = (base or "").strip() or "Copy"
        name, n = base, 1
        while self.copy_name_taken(name, exclude_id):
            n += 1
            name = f"{base} ({n})"
        return name

    def suggest_copy_names(self, count: int, prefix: str = "Copy") -> list[str]:
        """Next free names 'Copy N', 'Copy N+1', ... (one per requested copy)."""
        pattern = re.compile(rf"^{re.escape(prefix)} (\d+)$", re.IGNORECASE)
        highest = 0
        for row in self.conn.execute("SELECT name FROM copies"):
            match = pattern.match(row["name"])
            if match:
                highest = max(highest, int(match.group(1)))
        return [f"{prefix} {highest + i}" for i in range(1, count + 1)]

    def rename_copy(self, copy_id: int, name: str, note: str | None = None,
                    location=KEEP, apply_to_bonds: bool = False) -> None:
        """Change a copy's name and note, and (``location`` given) where it is kept.

        With ``apply_to_bonds`` the same location is also set on every bond of the copy that you
        still hold (bonds already sold keep the place they were sold from).
        """
        name = (name or "").strip()
        if not name:
            raise CopyNameError("The copy needs a name.")
        if self.copy_name_taken(name, copy_id):
            raise CopyNameError(f"A copy named '{name}' already exists.")
        with self.tx():
            self.conn.execute("UPDATE copies SET name = ?, note = ? WHERE id = ?",
                              (name, note or None, copy_id))
            if location is not KEEP:
                place = (location or "").strip() or None
                self.conn.execute("UPDATE copies SET location = ? WHERE id = ?", (place, copy_id))
                if apply_to_bonds:
                    self.conn.execute("UPDATE bonds SET location = ? WHERE copy_id = ? "
                                      "AND sale_id IS NULL", (place, copy_id))
            self.log("Copy edited", name)

    def delete_copy(self, copy_id: int, delete_bonds: bool = False) -> int:
        """Delete a copy.  Its bonds are either deleted or kept as loose bonds."""
        copy = self.get_copy(copy_id)
        if copy is None:
            return 0
        with self.tx():
            if delete_bonds:
                count = self.conn.execute(
                    "DELETE FROM bonds WHERE copy_id = ?", (copy_id,)).rowcount
            else:
                count = self.conn.execute(
                    "UPDATE bonds SET copy_id = NULL, position = NULL WHERE copy_id = ?",
                    (copy_id,)).rowcount
            self.conn.execute("DELETE FROM copies WHERE id = ?", (copy_id,))
            verb = "deleted" if delete_bonds else "kept as loose bonds"
            self.log("Copy deleted", f"{copy['name']} ({count} bond(s) {verb})")
        return count
