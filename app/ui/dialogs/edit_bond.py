"""Edit one bond: number, price, date of purchase, location, copy and position."""
from __future__ import annotations

from PyQt6.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout, QLineEdit, QSpinBox,
                             QVBoxLayout)

from ...db import DuplicateBondError, PositionTakenError
from ...processing.numbers import NumberError
from ..context import AppContext
from ..widgets import button, label, warn
from .common import DateField, DenominationBox, LocationField


class EditBondDialog(QDialog):
    def __init__(self, ctx: AppContext, bond_id: int, parent=None):
        super().__init__(parent)
        self.ctx, self.db, self.bond_id = ctx, ctx.db, bond_id
        self.bond = self.db.get_bond(bond_id)
        if self.bond is None:
            raise ValueError("That bond no longer exists.")
        self.setWindowTitle(f"Edit bond {self.bond['number']}")
        self.setMinimumWidth(460)
        bond = self.bond
        self.sold = bond["sale_id"] is not None

        self.number = QLineEdit(bond["number"])
        self.price = DenominationBox(extra=self.db.denominations())
        self.price.set_value(bond["denomination"])
        self.date = DateField()
        self.date.set_value(bond["purchase_date"])
        self.location = LocationField(self.db)
        self.location.set_value(bond["location"])
        status = "Active (takes part in every draw)"
        if self.sold:
            status = (f"Sold on {bond['sold_date']}" + (f" to {bond['sold_to']}" if bond["sold_to"]
                                                        else ""))
        if bond["times_won"]:
            status += f" - has won {bond['times_won']} time(s)"
        if bond["pending_count"]:
            status += " - a possible win is waiting for approval"
        self.copy_combo = QComboBox()
        self.copy_combo.addItem("None (loose bond)", None)
        for copy in self.db.list_copies():
            self.copy_combo.addItem(f"{copy['name']}  ({copy['size']} positions)", copy["id"])
            if copy["id"] == bond["copy_id"]:
                self.copy_combo.setCurrentIndex(self.copy_combo.count() - 1)
        self.position = QSpinBox()
        self.position.setRange(0, 10_000_000)
        self.position.setSpecialValueText("Next free position")
        self.position.setValue(bond["position"] or 0)
        self.copy_combo.currentIndexChanged.connect(self._copy_changed)
        self._copy_changed()

        form = QFormLayout()
        form.addRow("Bond number", self.number)
        form.addRow("Price (Rs)", self.price)
        form.addRow("Date of purchase", self.date)
        form.addRow("Location (optional)", self.location)
        self.status_label = label(status, wrap=True)
        form.addRow("Status", self.status_label)
        form.addRow("Copy (book)", self.copy_combo)
        form.addRow("Position in copy", self.position)

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
        if self.sold:
            layout.addWidget(label("This bond has been sold, so it cannot be changed here. To change "
                                   "it, undo the sale (or take the bond back) on the Sales page "
                                   "first.", "problem", wrap=True))
            for widget in (self.number, self.price, self.date, self.location, self.copy_combo,
                           self.position):
                widget.setEnabled(False)
            save.setEnabled(False)
        if bond["times_won"]:
            layout.addWidget(label("This bond has won before. Changing it here does not change the "
                                   "saved win records.", "muted", wrap=True))
        layout.addLayout(footer)

    def _copy_changed(self) -> None:
        self.position.setEnabled(self.copy_combo.currentData() is not None)

    def _save(self) -> None:
        price = self.price.value()
        if price is None:
            warn(self, "Price needed", "Enter the price of the bond, for example 750.")
            return
        try:
            self.db.update_bond(self.bond_id, self.number.text(), price, self.date.value(),
                                self.copy_combo.currentData(), self.position.value() or None,
                                location=self.location.value())
        except (NumberError, DuplicateBondError, PositionTakenError, ValueError) as exc:
            warn(self, "Cannot save", str(exc))
            return
        self.accept()
