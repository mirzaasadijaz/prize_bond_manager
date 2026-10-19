"""Edit winning numbers: one number (its code, prize and amount) or many at the same time."""
from __future__ import annotations

import re

from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLineEdit,
                             QVBoxLayout)

from ...config import DEFAULT_PRIZE_TIERS
from ...db.core import KEEP
from ...processing.numbers import NumberError, normalize_number
from ..widgets import button, label, warn


def parse_amount(text: str):
    """'1,500,000' / 'Rs 1500000' -> int; '' -> None (no amount); anything else -> False."""
    text = (text or "").strip()
    if not text:
        return None
    digits = re.sub(r"[,\s]", "", text.lower().replace("rs.", "").replace("rs", ""))
    return int(digits) if digits.isdigit() else False


class EditNumbersDialog(QDialog):
    """One row: change the number, the prize name and the prize amount.
    Several rows: change the prize name and / or the prize amount of all of them together
    (tick what to change; the numbers themselves stay as they are).

    After ``exec()`` accepted: ``number`` (text, only when one row was edited), ``prize``
    (new name or ``KEEP``) and ``amount`` (int, ``None`` for "no amount", or ``KEEP``).
    """

    def __init__(self, rows: list[dict], keys: tuple[str, str, str], scope: str = "", parent=None):
        """``rows``: dicts; ``keys``: the names of the number, prize and amount fields."""
        super().__init__(parent)
        self.single = len(rows) == 1
        self.number, self.prize, self.amount = None, KEEP, KEEP
        number_key, prize_key, amount_key = keys
        first = rows[0]
        self.setWindowTitle("Edit winning number" if self.single
                            else f"Edit {len(rows):,} winning numbers")
        self.setMinimumWidth(440)

        self.number_edit = QLineEdit(str(first[number_key]) if self.single else "")
        self.prize_box = QComboBox()
        self.prize_box.setEditable(True)
        self.prize_box.addItems(DEFAULT_PRIZE_TIERS)
        self.amount_edit = QLineEdit()
        self.amount_edit.setPlaceholderText("leave empty for no amount, e.g. 1500000")
        self.change_prize = QCheckBox("Change the prize to")
        self.change_amount = QCheckBox("Change the prize amount (Rs) to")
        if self.single:
            self.prize_box.setCurrentText(str(first[prize_key] or ""))
            self.amount_edit.setText("" if first[amount_key] is None else str(first[amount_key]))

        form = QFormLayout()
        if self.single:
            form.addRow("Winning number", self.number_edit)
            form.addRow("Prize", self.prize_box)
            form.addRow("Prize amount (Rs)", self.amount_edit)
        else:
            form.addRow(self.change_prize, self.prize_box)
            form.addRow(self.change_amount, self.amount_edit)
            self.prize_box.setEnabled(False)
            self.amount_edit.setEnabled(False)
            self.change_prize.toggled.connect(self.prize_box.setEnabled)
            self.change_amount.toggled.connect(self.amount_edit.setEnabled)

        save = button("Save", "primary")
        save.clicked.connect(self._save)
        cancel = button("Cancel")
        cancel.clicked.connect(self.reject)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(cancel)
        footer.addWidget(save)
        layout = QVBoxLayout(self)
        if not self.single:
            layout.addWidget(label(f"{len(rows):,} winning number(s){scope} will be changed "
                                   "together. Tick what you want to change.", "muted", wrap=True))
        layout.addLayout(form)
        layout.addLayout(footer)

    def _save(self) -> None:
        amount = parse_amount(self.amount_edit.text())
        if amount is False and (self.single or self.change_amount.isChecked()):
            warn(self, "Prize amount", "The prize amount must be a number, for example 1500000.")
            return
        if self.single:
            try:
                self.number = normalize_number(self.number_edit.text())[0]
            except NumberError as exc:
                warn(self, "Winning number", f"That is not a valid bond number ({exc}).")
                return
            self.prize = self.prize_box.currentText().strip() or "Winner"
            self.amount = amount
        else:
            if not (self.change_prize.isChecked() or self.change_amount.isChecked()):
                warn(self, "Nothing to change", "Tick the prize and / or the prize amount.")
                return
            if self.change_prize.isChecked():
                self.prize = self.prize_box.currentText().strip() or "Winner"
            if self.change_amount.isChecked():
                self.amount = amount
        self.accept()
