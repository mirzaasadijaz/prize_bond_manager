"""One recorded sale: what was sold, to whom, for how much - and taking bonds back."""
from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLineEdit, QVBoxLayout

from ...db import SaleError
from .. import theme
from ..context import AppContext
from ..table_model import Col
from ..widgets import TablePanel, button, confirm, dash, label, money, warn
from .common import DateField, LocationField
from .sale_dialog import buyer_field


class EditSaleDialog(QDialog):
    """Change who / when / where of a sale (the bonds and prices stay as they are)."""

    def __init__(self, ctx: AppContext, sale_id: int, parent=None):
        super().__init__(parent)
        self.db, self.sale_id = ctx.db, sale_id
        sale = self.db.get_sale(sale_id)
        if sale is None:
            raise ValueError("That sale no longer exists.")
        self.setWindowTitle("Edit sale")
        self.setMinimumWidth(460)
        self.date = DateField(allow_unknown=False)
        self.date.set_value(sale["sale_date"])
        self.buyer = buyer_field(self.db)
        self.buyer.setText(sale["buyer"] or "")
        self.contact = QLineEdit(sale["contact"] or "")
        self.location = LocationField(self.db, "where the sale took place (optional)")
        self.location.set_value(sale["location"])
        self.note = QLineEdit(sale["note"] or "")
        form = QFormLayout()
        form.addRow("Date of sale", self.date)
        form.addRow("Sold to", self.buyer)
        form.addRow("Contact", self.contact)
        form.addRow("Location", self.location)
        form.addRow("Note", self.note)
        save = button("Save", "primary")
        save.clicked.connect(self._save)
        cancel = button("Cancel")
        cancel.clicked.connect(self.reject)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(cancel)
        footer.addWidget(save)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(label("Moving the date also moves the date from which the bonds belong "
                               "to the buyer: a possible win from a draw on or after the new date "
                               "is taken off the waiting list.", "muted", wrap=True))
        layout.addLayout(footer)

    def _save(self) -> None:
        try:
            self.db.update_sale(self.sale_id, sale_date=self.date.value(), buyer=self.buyer.text(),
                                contact=self.contact.text(), location=self.location.text(),
                                note=self.note.text())
        except SaleError as exc:
            warn(self, "Cannot save", str(exc))
            return
        self.accept()


def _in_list(value, row) -> str:
    return "Sold" if row["bond_exists"] else "Bond deleted"


class SaleDetailsDialog(QDialog):
    """Shows a sale.  ``changed`` becomes True when anything was edited, taken back or undone."""

    COLUMNS = [
        Col("bond_number", "Bond number", 120, sort_key="num"),
        Col("price", "Sold for (Rs)", 110, "right", numeric=True, fmt=lambda v, r: f"{v:,}"),
        Col("denomination", "Face value (Rs)", 110, "right", numeric=True,
            fmt=lambda v, r: f"{v:,}"),
        Col("copy_name", "Copy (book)", 140, fmt=dash),
        Col("copy_first_number", "1st bond of copy", 120, fmt=dash),
        Col("position", "Position", 80, "right", numeric=True, fmt=dash),
        Col("bond_location", "Kept at", 130, fmt=dash),
        Col("bond_exists", "Bond", 100, fmt=_in_list),
    ]

    def __init__(self, ctx: AppContext, sale_id: int, parent=None):
        super().__init__(parent)
        self.ctx, self.db, self.sale_id = ctx, ctx.db, sale_id
        self.changed = False
        self.setWindowTitle("Sale details")
        self.resize(900, 620)

        self.heading = label("", "section")
        self.facts = label("", wrap=True)
        self.note = label("", "muted", wrap=True)
        self.table = TablePanel(self.COLUMNS, export_name="sale", sheet_name="Sale",
                                row_style=lambda r: None if r["bond_exists"] else (theme.MUTED, None),
                                empty_text="This sale has no bonds.")
        self.table.selection_changed.connect(self._update_buttons)
        self.edit_button = button("Edit sale...")
        self.back_button = button("Take back selected bonds",
                                  tooltip="The buyer returned them, or they were put in by mistake")
        self.undo_button = button("Undo whole sale", "danger")
        close = button("Close")
        self.edit_button.clicked.connect(self._edit)
        self.back_button.clicked.connect(self._take_back)
        self.undo_button.clicked.connect(self._undo)
        close.clicked.connect(self.accept)
        footer = QHBoxLayout()
        for widget in (self.edit_button, self.back_button, self.undo_button):
            footer.addWidget(widget)
        footer.addStretch(1)
        footer.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addWidget(self.heading)
        layout.addWidget(self.facts)
        layout.addWidget(self.note)
        layout.addWidget(self.table, 1)
        layout.addLayout(footer)
        self._load()

    def _load(self) -> bool:
        sale = self.db.get_sale(self.sale_id)
        if sale is None:
            return False
        items = self.db.sale_items(self.sale_id)
        buyer = sale["buyer"] or "(buyer not recorded)"
        self.heading.setText(f"Sold to {buyer} on {sale['sale_date']}")
        diff = sale["difference"]
        sign = "+" if diff > 0 else "-" if diff < 0 else ""
        parts = [f"{sale['bonds']:,} bond(s)", f"face value {money(sale['face_value'])}",
                 f"received {money(sale['total_amount'])}"
                 + (f" ({sign}{money(abs(diff))} against face value)" if diff else "")]
        if sale["contact"]:
            parts.append(f"contact: {sale['contact']}")
        if sale["location"]:
            parts.append(f"at {sale['location']}")
        self.facts.setText("   |   ".join(parts))
        self.note.setText(sale["note"] or "")
        self.note.setVisible(bool(sale["note"]))
        self.table.set_rows(items)
        self._update_buttons()
        return True

    def _update_buttons(self) -> None:
        self.back_button.setEnabled(bool(self.table.selected_rows()))

    def _after_change(self, text: str) -> None:
        """Something changed: let the rest of the program catch up (including the agent, since
        bonds that are yours again take part in the earlier draws once more)."""
        self.changed = True
        self.ctx.changed()
        result = self.ctx.run_agent("bonds")
        self.ctx.status.emit(text)
        if not self._load():                      # the sale is gone
            self.accept()
        self.ctx.offer_review(self.parentWidget() or self, result)

    def _edit(self) -> None:
        if not self.ctx.guard(self, "edit this sale"):
            return
        if EditSaleDialog(self.ctx, self.sale_id, self).exec():
            self.changed = True
            self.ctx.changed()
            self._load()

    def _take_back(self) -> None:
        rows = self.table.selected_rows()
        if not rows:
            return
        if not self.ctx.guard(self, "take these bonds back"):
            return
        everything = len(rows) == len(self.table.all_rows())
        text = (f"Take back {len(rows):,} bond(s)? They become yours again and take part in every "
                "draw, including the ones held while they were sold.")
        if everything:
            text += "\n\nThis is the whole sale, so the sale record is removed too."
        if not confirm(self, "Take bonds back", text, yes="Take back"):
            return
        back = self.db.return_sale_items([r["id"] for r in rows])
        self._after_change(f"{back:,} bond(s) taken back.")

    def _undo(self) -> None:
        if not self.ctx.guard(self, "undo the sale"):
            return
        if not confirm(self, "Undo sale",
                       "Undo this whole sale? All of its bonds become yours again and the sale "
                       "record is removed.", yes="Undo sale", danger=True):
            return
        back = self.db.undo_sale(self.sale_id)
        self._after_change(f"Sale undone: {back:,} bond(s) are yours again.")
