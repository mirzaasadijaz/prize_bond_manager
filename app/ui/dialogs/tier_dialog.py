"""Give the prizes by tier: 1st prize = this number and amount, 2nd prize = these numbers and
amount, and every other number = 3rd prize with its amount."""
from __future__ import annotations

from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout,
                             QLineEdit, QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget)

from ...config import DEFAULT_PRIZE_TIERS
from ...processing.numbers import parse_pattern
from ..widgets import button, label, warn
from .edit_numbers import parse_amount


class _Tier(QGroupBox):
    """One prize: its name, its amount and the numbers that win it."""

    def __init__(self, title: str, prize: str, hint: str, parent=None):
        super().__init__(title, parent)
        self.prize = QComboBox()
        self.prize.setEditable(True)
        self.prize.addItems(DEFAULT_PRIZE_TIERS)
        self.prize.setCurrentText(prize)
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("e.g. 1500000 (empty = no amount)")
        self.numbers = QPlainTextEdit()
        self.numbers.setPlaceholderText(hint)
        self.numbers.setMaximumHeight(70)
        form = QFormLayout(self)
        form.addRow("Prize", self.prize)
        form.addRow("Prize amount (Rs)", self.amount)
        form.addRow("Numbers", self.numbers)


class PrizeTiersDialog(QDialog):
    """After ``exec()`` accepted: ``tiers`` = ``[(prize name, amount, [(display, key), ...])]``
    and ``rest`` = ``(prize name, amount)`` for every number that is not listed, or ``None``."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tiers: list[tuple[str, int | None, list[tuple[str, int]]]] = []
        self.rest: tuple[str, int | None] | None = None
        self.setWindowTitle("Set the prizes by tier")
        self.resize(520, 640)
        self.boxes: list[_Tier] = []

        intro = label("Type the numbers of each prize. Numbers can be separated by spaces, commas "
                      "or new lines (a range like 100001-100010 works too). A number that is not "
                      "in the table yet is added. Whatever you leave empty is not touched.",
                      "muted", wrap=True)
        self.inner = QVBoxLayout()
        holder = QWidget()
        holder.setLayout(self.inner)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        self._add_tier("1st Prize", "the 1st prize number, e.g. 123456")
        self._add_tier("2nd Prize", "the 2nd prize numbers, e.g. 111111 222222 333333")
        self.inner.addStretch(1)

        self.rest_box = QGroupBox("Every other number")
        self.rest_on = QCheckBox("All the numbers that are not listed above get this prize")
        self.rest_on.setChecked(True)
        self.rest_prize = QComboBox()
        self.rest_prize.setEditable(True)
        self.rest_prize.addItems(DEFAULT_PRIZE_TIERS)
        self.rest_prize.setCurrentText("3rd Prize")
        self.rest_amount = QLineEdit()
        self.rest_amount.setPlaceholderText("e.g. 1250 (empty = no amount)")
        rest_form = QFormLayout(self.rest_box)
        rest_form.addRow(self.rest_on)
        rest_form.addRow("Prize", self.rest_prize)
        rest_form.addRow("Prize amount (Rs)", self.rest_amount)
        self.rest_on.toggled.connect(self.rest_prize.setEnabled)
        self.rest_on.toggled.connect(self.rest_amount.setEnabled)

        more = button("Add another prize")
        more.clicked.connect(self._more)
        save = button("Apply", "primary")
        save.clicked.connect(self._apply)
        cancel = button("Cancel")
        cancel.clicked.connect(self.reject)
        footer = QHBoxLayout()
        footer.addWidget(more)
        footer.addStretch(1)
        footer.addWidget(cancel)
        footer.addWidget(save)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(scroll, 1)
        layout.addWidget(self.rest_box)
        layout.addLayout(footer)

    def _add_tier(self, prize: str, hint: str, before_stretch: bool = False) -> None:
        box = _Tier(f"Prize {len(self.boxes) + 1}", prize, hint)
        self.boxes.append(box)
        if before_stretch:
            self.inner.insertWidget(self.inner.count() - 1, box)
        else:
            self.inner.addWidget(box)

    def _more(self) -> None:
        self._add_tier("Winner", "the numbers of this prize", before_stretch=True)

    def _apply(self) -> None:
        tiers: list[tuple[str, int | None, list[tuple[str, int]]]] = []
        seen: dict[int, str] = {}
        for box in self.boxes:
            text = box.numbers.toPlainText()
            if not text.strip():
                continue
            name = box.prize.currentText().strip() or "Winner"
            amount = parse_amount(box.amount.text())
            if amount is False:
                warn(self, "Prize amount", f"The amount of {name} must be a number, for example "
                     "1500000.")
                return
            parsed = parse_pattern(text)
            if parsed.errors:
                warn(self, "Numbers not understood", f"These entries of {name} are not valid bond "
                     "numbers:\n\n" + "\n".join(parsed.errors[:8]))
                return
            for display, key in parsed.numbers:
                if key in seen:
                    warn(self, "Number listed twice", f"{display} is in both {seen[key]} and "
                         f"{name}. A number can only win one prize.")
                    return
                seen[key] = name
            tiers.append((name, amount, parsed.numbers))
        rest = None
        if self.rest_on.isChecked():
            amount = parse_amount(self.rest_amount.text())
            if amount is False:
                warn(self, "Prize amount", "The amount of the other numbers must be a number, "
                     "for example 1250.")
                return
            rest = (self.rest_prize.currentText().strip() or "Winner", amount)
        if not tiers and rest is None:
            warn(self, "Nothing to change", "Type some numbers, or tick the box for the other "
                 "numbers.")
            return
        self.tiers, self.rest = tiers, rest
        self.accept()