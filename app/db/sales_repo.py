"""Sales: bonds sold to somebody.

Selling does three things, all in one transaction:
  * a ``sales`` record (date, buyer, contact, place, note, what you received),
  * one ``sale_items`` row per bond - a snapshot of its number, price, copy, 1st bond number
    and position, so the sale stays readable even if the bond or copy is edited or deleted,
  * the bonds themselves are marked as sold (``sale_id`` / ``sold_date``).

A sold bond stays in its copy at its position, but every list of "my bonds", the copy counts,
the dashboard and the win-checking agent treat it as no longer yours.  The one exception is
time: draws held *before* the sale date still count, so a win you earned while you owned the
bond stays yours.  Undoing a sale (or taking some bonds back) puts the bonds straight back.
"""
from __future__ import annotations

from datetime import datetime
from typing import Sequence

from .bonds_repo import BOND_SELECT
from .core import KEEP, chunks, now_iso


class SaleError(ValueError):
    """A sale could not be recorded or changed; the message is safe to show to the user."""


def _valid_date(text: str) -> str:
    try:
        return datetime.strptime((text or "").strip(), "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise SaleError("The sale date must look like 2026-10-14.") from exc


def _clean(text) -> str | None:
    return (text or "").strip() or None


class SalesMixin:
    # ------------------------------------------------------------- recording
    def record_sale(self, bond_ids: Sequence[int], sale_date: str, buyer: str = "",
                    contact: str = "", location: str = "", note: str = "",
                    prices: Sequence[int] | None = None) -> int:
        """Sell the given bonds.  ``prices`` (whole rupees, one per bond, same order) defaults
        to each bond's face value.  Returns the new sale's id."""
        ids = list(dict.fromkeys(bond_ids))
        if not ids:
            raise SaleError("Choose at least one bond to sell.")
        when = _valid_date(sale_date)
        if prices is None:
            by_id = None
        else:
            if len(prices) != len(bond_ids):
                raise SaleError("There must be one price per bond.")
            if any(int(p) < 0 for p in prices):
                raise SaleError("A price cannot be negative.")
            by_id = {}
            for bond_id, price in zip(bond_ids, prices):
                by_id.setdefault(bond_id, int(price))
        bonds: dict[int, dict] = {}
        for part in chunks(ids, 500):
            marks = ",".join("?" * len(part))
            for row in self.query(BOND_SELECT + f" WHERE b.id IN ({marks})", tuple(part)):
                bonds[row["id"]] = row
        if len(bonds) != len(ids):
            raise SaleError("Some of the chosen bonds no longer exist. Refresh the list and try "
                            "again.")
        already = [b["number"] for b in bonds.values() if b["sale_id"] is not None]
        if already:
            shown = ", ".join(already[:5]) + (" ..." if len(already) > 5 else "")
            raise SaleError(f"Already sold: {shown}. A bond can only be sold once - undo the "
                            "earlier sale first.")
        rows = [bonds[i] for i in ids]
        price_of = {r["id"]: (by_id[r["id"]] if by_id else r["denomination"]) for r in rows}
        total = sum(price_of.values())
        stamp = now_iso()
        with self.tx():
            sale_id = self.conn.execute(
                "INSERT INTO sales (sale_date, buyer, contact, location, total_amount, note, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (when, _clean(buyer), _clean(contact), _clean(location), total, _clean(note),
                 stamp)).lastrowid
            self.conn.executemany(
                "INSERT INTO sale_items (sale_id, bond_id, bond_number, num, denomination, price, "
                "copy_id, copy_name, copy_first_number, position, copy_size, bond_location) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(sale_id, r["id"], r["number"], r["num"], r["denomination"], price_of[r["id"]],
                  r["copy_id"], r["copy_name"], r["copy_first_number"], r["position"],
                  r["copy_size"], r["location"]) for r in rows])
            for part in chunks(ids, 500):
                marks = ",".join("?" * len(part))
                self.conn.execute(
                    f"UPDATE bonds SET sale_id = ?, sold_date = ? WHERE id IN ({marks})",
                    (sale_id, when, *part))
            dropped = self._drop_pending_after(ids, when)
            to = f" to {_clean(buyer)}" if _clean(buyer) else ""
            self.log("Bonds sold", f"{len(ids)} bond(s){to} on {when} for Rs {total:,}"
                     + (f"; {dropped} possible win(s) from draws on or after that date removed "
                        "from the waiting list" if dropped else ""))
        return sale_id

    def _drop_pending_after(self, bond_ids: Sequence[int], sold_date: str) -> int:
        """Pending matches from draws on/after the sale date are the buyer's, not yours."""
        removed = 0
        for part in chunks(list(bond_ids), 500):
            marks = ",".join("?" * len(part))
            removed += self.conn.execute(
                f"DELETE FROM pending_wins WHERE status = 'pending' AND bond_id IN ({marks}) "
                "AND draw_id IN (SELECT id FROM draws WHERE draw_date >= ?)",
                (*part, sold_date)).rowcount
        return removed

    # --------------------------------------------------------------- reading
    def list_sales(self) -> list[dict]:
        sales = self.query(
            """
            SELECT s.id, s.sale_date, s.buyer, s.contact, s.location, s.note, s.total_amount,
                   s.created_at, COUNT(i.id) AS bonds,
                   COALESCE(SUM(i.denomination), 0) AS face_value
            FROM sales s LEFT JOIN sale_items i ON i.sale_id = s.id
            GROUP BY s.id ORDER BY s.sale_date DESC, s.id DESC
            """)
        copies: dict[int, list[str]] = {}
        for row in self.conn.execute(
                "SELECT DISTINCT sale_id, copy_name FROM sale_items "
                "WHERE copy_name IS NOT NULL ORDER BY sale_id, copy_name"):
            copies.setdefault(row["sale_id"], []).append(row["copy_name"])
        for sale in sales:
            sale["copy_names"] = copies.get(sale["id"], [])
            sale["difference"] = sale["total_amount"] - sale["face_value"]
        return sales

    def get_sale(self, sale_id: int) -> dict | None:
        return next((s for s in self.list_sales() if s["id"] == sale_id), None)

    def sale_items(self, sale_id: int) -> list[dict]:
        """The bonds of one sale, in copy order.  ``bond_exists`` is False if the bond itself
        has been deleted since."""
        return self.query(
            "SELECT i.*, (i.bond_id IS NOT NULL) AS bond_exists FROM sale_items i "
            "WHERE i.sale_id = ? ORDER BY i.copy_name IS NULL, i.copy_name, i.position, "
            "i.num, i.id", (sale_id,))

    def sales_summary(self) -> dict:
        row = self.conn.execute(
            "SELECT COUNT(*) AS sales, COALESCE(SUM(total_amount), 0) AS received FROM sales"
        ).fetchone()
        bonds = self.conn.execute(
            "SELECT COUNT(*) AS bonds, COALESCE(SUM(denomination), 0) AS face FROM sale_items"
        ).fetchone()
        return {"sales": row["sales"], "received": row["received"], "bonds": bonds["bonds"],
                "face_value": bonds["face"]}

    def known_buyers(self) -> list[str]:
        return [r["buyer"] for r in self.conn.execute(
            "SELECT DISTINCT buyer FROM sales WHERE buyer IS NOT NULL AND buyer <> '' "
            "ORDER BY buyer COLLATE NOCASE")]

    # --------------------------------------------------------------- changing
    def update_sale(self, sale_id: int, *, sale_date=KEEP, buyer=KEEP, contact=KEEP,
                    location=KEEP, note=KEEP) -> None:
        """Change the details of a sale.  A new date moves the sale date of all its bonds."""
        sale = self.conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
        if sale is None:
            raise SaleError("That sale no longer exists.")
        sets, values = [], []
        new_date = None
        if sale_date is not KEEP:
            new_date = _valid_date(sale_date)
            sets.append("sale_date = ?")
            values.append(new_date)
        for column, value in (("buyer", buyer), ("contact", contact), ("location", location),
                              ("note", note)):
            if value is not KEEP:
                sets.append(f"{column} = ?")
                values.append(_clean(value))
        if not sets:
            return
        sets.append("updated_at = ?")
        values.append(now_iso())
        with self.tx():
            self.conn.execute(f"UPDATE sales SET {', '.join(sets)} WHERE id = ?",
                              (*values, sale_id))
            if new_date and new_date != sale["sale_date"]:
                self.conn.execute("UPDATE bonds SET sold_date = ? WHERE sale_id = ?",
                                  (new_date, sale_id))
                ids = [r["id"] for r in self.conn.execute(
                    "SELECT id FROM bonds WHERE sale_id = ?", (sale_id,))]
                self._drop_pending_after(ids, new_date)
            self.log("Sale edited", f"sale #{sale_id}")

    def return_sale_items(self, item_ids: Sequence[int]) -> int:
        """Take bonds back (the buyer returned them, or the sale was a mistake).

        The bonds become yours again and take part in every draw.  A sale left with no bonds
        is removed.  Returns how many bonds are yours again.
        """
        back = 0
        touched: set[int] = set()
        with self.tx():
            for part in chunks(list(dict.fromkeys(item_ids)), 500):
                marks = ",".join("?" * len(part))
                items = self.conn.execute(
                    f"SELECT id, sale_id, bond_id FROM sale_items WHERE id IN ({marks})",
                    tuple(part)).fetchall()
                for item in items:
                    touched.add(item["sale_id"])
                    if item["bond_id"] is not None:
                        back += self.conn.execute(
                            "UPDATE bonds SET sale_id = NULL, sold_date = NULL "
                            "WHERE id = ? AND sale_id = ?",
                            (item["bond_id"], item["sale_id"])).rowcount
                    self.conn.execute("DELETE FROM sale_items WHERE id = ?", (item["id"],))
            for sale_id in touched:
                left = self.conn.execute(
                    "SELECT COUNT(*) AS c, COALESCE(SUM(price), 0) AS t FROM sale_items "
                    "WHERE sale_id = ?", (sale_id,)).fetchone()
                if left["c"]:
                    self.conn.execute(
                        "UPDATE sales SET total_amount = ?, updated_at = ? WHERE id = ?",
                        (left["t"], now_iso(), sale_id))
                else:
                    self.conn.execute("DELETE FROM sales WHERE id = ?", (sale_id,))
            if touched:
                self.log("Sale changed", f"{back} bond(s) taken back and in your list again")
        return back

    def undo_sale(self, sale_id: int) -> int:
        """Cancel a whole sale: every bond is yours again.  Returns how many bonds came back."""
        ids = [r["id"] for r in self.conn.execute(
            "SELECT id FROM sale_items WHERE sale_id = ?", (sale_id,))]
        if not ids:
            with self.tx():
                self.conn.execute("DELETE FROM sales WHERE id = ?", (sale_id,))
            return 0
        return self.return_sale_items(ids)
