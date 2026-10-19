"""Sales: the bonds you sold to other people, and what you received for them."""
from __future__ import annotations

from ...db import SaleError
from .. import actions
from ..context import AppContext
from ..dialogs.sale_details import EditSaleDialog, SaleDetailsDialog
from ..table_model import Col
from ..widgets import PageHeader, TablePanel, button, confirm, dash, label, money
from .base import BasePage


def _difference(value, row) -> str:
    if not value:
        return "-"
    return f"{'+' if value > 0 else '-'}{abs(value):,}"


def _copies(value, row) -> str:
    names = row["copy_names"]
    if not names:
        return "-"
    return ", ".join(names[:3]) + (f" (+{len(names) - 3})" if len(names) > 3 else "")


class SalesPage(BasePage):
    COLUMNS = [
        Col("sale_date", "Date", 100),
        Col("buyer", "Sold to", 160, fmt=dash),
        Col("contact", "Contact", 130, fmt=dash),
        Col("location", "Location", 130, fmt=dash),
        Col("bonds", "Bonds", 70, "right", numeric=True, export_raw=True),
        Col("face_value", "Face value (Rs)", 120, "right", numeric=True, export_raw=True,
            fmt=lambda v, r: f"{v:,}"),
        Col("total_amount", "Received (Rs)", 120, "right", numeric=True, export_raw=True,
            fmt=lambda v, r: f"{v:,}"),
        Col("difference", "Against face value", 130, "right", numeric=True, export_raw=True,
            fmt=_difference),
        Col("copy_names", "Copies", 180, fmt=_copies, export_raw=False),
        Col("note", "Note", 220, fmt=lambda v, r: v or ""),
    ]

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, parent)
        header = PageHeader(
            "Sales",
            "Bonds you sold to other people. A sold bond stays in its copy at its position but is "
            "shown as sold, no longer counts as yours and is not checked against draws held on "
            "or after the sale date (wins from before the sale stay yours). Undo a sale, or take "
            "some bonds back, and they are yours again.")
        self.sell_button = header.add_action(button("Record a sale...", "primary"))
        self.details_button = header.add_action(button("Details"))
        self.edit_button = header.add_action(button("Edit"))
        self.undo_button = header.add_action(button("Undo sale", "danger"))
        self.sell_button.clicked.connect(lambda: actions.sell_bonds(self.ctx, self))
        self.details_button.clicked.connect(self._details)
        self.edit_button.clicked.connect(self._edit)
        self.undo_button.clicked.connect(self._undo)
        self.root.addWidget(header)

        self.totals = label("", "muted", wrap=True)
        self.root.addWidget(self.totals)
        self.panel = TablePanel(
            self.COLUMNS, export_name="sales", sheet_name="Sales",
            placeholder="Search buyer, copy, location, note ...",
            empty_text="No sales recorded.\nUse 'Record a sale...' - or select bonds on My Bonds / "
                       "a copy on Copies and press Sell.")
        self.panel.selection_changed.connect(self._update_buttons)
        self.panel.row_activated.connect(lambda row: self._details())
        self.root.addWidget(self.panel, 1)

    def refresh(self) -> None:
        self.panel.set_rows(self.db.list_sales())
        total = self.db.sales_summary()
        self.totals.setText(
            f"{total['sales']:,} sale(s) - {total['bonds']:,} bond(s) sold, face value "
            f"{money(total['face_value'])}, received {money(total['received'])}."
            if total["sales"] else "Nothing sold yet.")
        self._update_buttons()

    def _selected(self) -> dict | None:
        rows = self.panel.selected_rows()
        return rows[0] if len(rows) == 1 else None

    def _update_buttons(self) -> None:
        one = self._selected() is not None
        for widget in (self.details_button, self.edit_button):
            widget.setEnabled(one)
        self.undo_button.setEnabled(bool(self.panel.selected_rows()))

    def _details(self) -> None:
        sale = self._selected()
        if sale is None:
            return
        dialog = SaleDetailsDialog(self.ctx, sale["id"], self)
        dialog.exec()
        if dialog.changed:
            self.ctx.changed()

    def _edit(self) -> None:
        sale = self._selected()
        if sale and EditSaleDialog(self.ctx, sale["id"], self).exec():
            self.ctx.changed()

    def _undo(self) -> None:
        rows = self.panel.selected_rows()
        if not rows:
            return
        bonds = sum(r["bonds"] for r in rows)
        if not confirm(self, "Undo sale",
                       f"Undo {len(rows)} sale(s)? {bonds:,} bond(s) become yours again and the "
                       "sale record(s) are removed.", yes="Undo", danger=True):
            return
        try:
            for row in rows:
                self.db.undo_sale(row["id"])
        except SaleError as exc:
            self.ctx.status.emit(str(exc))
        self.ctx.changed()
        self.ctx.offer_review(self, self.ctx.run_agent("bonds"))
        self.ctx.status.emit(f"{bonds:,} bond(s) are yours again.")
