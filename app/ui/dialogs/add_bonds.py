"""Add bonds by hand: copies (books/batches), or a single bond / range / list."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QFormLayout, QGroupBox,
                             QHBoxLayout, QLineEdit, QMessageBox, QPlainTextEdit, QRadioButton,
                             QTabWidget, QVBoxLayout, QWidget)

from ...db import Database
from ...models import AddResult
from ...processing.numbers import parse_pattern
from ..context import AppContext
from ..widgets import button, label, set_role, warn
from .common import DateField, DenominationBox, LocationField
from .copies_editor import CopiesEditor


class QuickAdd(QWidget):
    """One pattern (single number, range or list) -> loose bonds, a new copy or an existing copy."""

    changed = pyqtSignal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.pattern = QPlainTextEdit()
        self.pattern.setPlaceholderText("123456\n100001-100050\n100001, 100002, 250010-250020")
        self.pattern.setMaximumHeight(130)
        self.info = label("", "muted", wrap=True)

        self.loose = QRadioButton("No copy (loose bonds)")
        self.new = QRadioButton("A new copy named:")
        self.existing = QRadioButton("An existing copy (added after its last position):")
        self.loose.setChecked(True)
        self.new_name = QLineEdit()
        self.new_name.setPlaceholderText("e.g. Copy 7")
        self.copy_combo = QComboBox()
        for copy in db.list_copies():
            self.copy_combo.addItem(f"{copy['name']}  ({copy['size']} positions)", copy["id"])
        if not self.copy_combo.count():
            self.existing.setEnabled(False)
        self.copy_combo.setEnabled(False)
        self.new_name.setEnabled(False)
        group = QButtonGroup(self)
        for radio in (self.loose, self.new, self.existing):
            group.addButton(radio)
        group.buttonToggled.connect(self._on_target)

        box = QGroupBox("Put these bonds in")
        grid = QVBoxLayout(box)
        grid.addWidget(self.loose)
        row = QHBoxLayout()
        row.addWidget(self.new)
        row.addWidget(self.new_name, 1)
        grid.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(self.existing)
        row.addWidget(self.copy_combo, 1)
        grid.addLayout(row)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.addWidget(label("Type one bond number, a range like 100001-100050 (add :2 to take "
                               "every 2nd number), or any list separated by commas, spaces or "
                               "new lines.", "muted", wrap=True))
        layout.addWidget(self.pattern)
        layout.addWidget(self.info)
        layout.addWidget(box)
        layout.addStretch(1)
        self.pattern.textChanged.connect(self._update)
        self.new_name.textChanged.connect(self._update)
        self.copy_combo.currentIndexChanged.connect(self._update)
        self._update()

    def _on_target(self) -> None:
        self.new_name.setEnabled(self.new.isChecked())
        self.copy_combo.setEnabled(self.existing.isChecked())
        self._update()

    def parsed(self):
        return parse_pattern(self.pattern.toPlainText())

    def target(self) -> tuple[str, object]:
        if self.new.isChecked():
            return "new", self.new_name.text().strip()
        if self.existing.isChecked():
            return "existing", self.copy_combo.currentData()
        return "loose", None

    def _problem(self) -> str:
        result = self.parsed()
        if result.errors or result.duplicates:
            return result.problems()
        if not result.count:
            return "Enter at least one bond number."
        kind, value = self.target()
        if kind == "new":
            if not value:
                return "Give the new copy a name."
            if self.db.copy_name_taken(value):
                return f"A copy named '{value}' already exists."
        return ""

    def is_valid(self) -> bool:
        return not self._problem()

    def _update(self) -> None:
        result, problem = self.parsed(), self._problem()
        if problem and (result.errors or result.duplicates or result.count):
            self.info.setText(problem)
            set_role(self.info, "problem")
        elif problem:
            self.info.setText("")
        else:
            self.info.setText(f"{result.count:,} bond(s): first {result.first}, last {result.last}")
            set_role(self.info, "ok")
        self.changed.emit()


class AddBondsDialog(QDialog):
    """Price and purchase date apply to everything added in this dialog."""

    def __init__(self, ctx: AppContext, parent=None, start_tab: int = 0):
        super().__init__(parent)
        self.ctx, self.db = ctx, ctx.db
        self.result: AddResult | None = None
        self.setWindowTitle("Add bonds")
        self.resize(900, 720)

        self.price = DenominationBox(extra=self.db.denominations())
        self.price.set_value(DenominationBox.remembered())
        self.price.setMaximumWidth(160)
        self.date = DateField()
        common = QGroupBox("Applies to every bond added here")
        form = QFormLayout(common)
        form.addRow("Price (Rs)", self.price)
        form.addRow("Date of purchase", self.date)
        self.location = LocationField(self.db)
        self.location.setToolTip("Where these bonds are kept. Leave empty if it does not matter; "
                                 "in the copies table each copy can also have its own place, "
                                 "which wins over this one.")
        form.addRow("Location (optional)", self.location)

        self.copies = CopiesEditor(self.db)
        self.quick = QuickAdd(self.db)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.copies, "Copies (books / batches)")
        self.tabs.addTab(self.quick, "Single bond / range / list")
        self.tabs.setCurrentIndex(start_tab)

        self.add_button = button("Add bonds", "primary")
        self.add_button.clicked.connect(self._add)
        cancel = button("Cancel")
        cancel.clicked.connect(self.reject)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(cancel)
        footer.addWidget(self.add_button)

        layout = QVBoxLayout(self)
        layout.addWidget(common)
        layout.addWidget(self.tabs, 1)
        layout.addLayout(footer)

        for signal in (self.copies.changed, self.quick.changed, self.tabs.currentChanged,
                       self.price.editTextChanged):
            signal.connect(self._update_button)
        self._update_button()

    def _update_button(self, *_) -> None:
        editor = self.copies if self.tabs.currentIndex() == 0 else self.quick
        self.add_button.setEnabled(editor.is_valid() and self.price.value() is not None)

    # -- saving ------------------------------------------------------------------
    def _ask_about_held(self, count: int, denomination: int, in_copy: int = 0) -> str | None:
        """Some numbers are already in the list: add them again ('all'), 'skip' them, or cancel."""
        box = QMessageBox(QMessageBox.Icon.Question, "Numbers you already have", "",
                          QMessageBox.StandardButton.NoButton, self)
        box.setText(f"{count:,} of these numbers are already in your list (Rs {denomination}).")
        extra = (f"\n\n{in_copy:,} more are already in the copy you chose; a copy cannot hold the "
                 "same number twice, so those are always left out." if in_copy else "")
        box.setInformativeText(
            "The same number can sit in several copies: if it is drawn, every bond holding it "
            "wins.\n\nAdd them anyway as extra bonds, or leave out the numbers you already have? "
            "(Left-out numbers keep their position in the copy.)" + extra)
        add_all = box.addButton("Add all", QMessageBox.ButtonRole.AcceptRole)
        skip = box.addButton("Skip numbers I already have", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(add_all)
        box.exec()
        if box.clickedButton() is add_all:
            return "all"
        return "skip" if box.clickedButton() is skip else None

    def _add(self) -> None:
        denomination = self.price.value()
        if denomination is None:
            warn(self, "Price needed", "Enter the price of these bonds, for example 750.")
            return
        purchase_date = self.date.value()
        common_location = self.location.value()
        copies_tab = self.tabs.currentIndex() == 0
        if copies_tab:
            groups = self.copies.collect()
            keys = [k for _, numbers in groups for _, k in numbers]
        else:
            groups, keys = None, [k for _, k in self.quick.parsed().numbers]
        # Numbers held before this dialog adds anything.  Copies added together may still
        # share numbers, so "skip" only ever refers to this snapshot.
        held = self.db.held_keys(denomination, keys)
        kind, value = (None, None) if copies_tab else self.quick.target()
        in_copy = self.db.held_keys(denomination, keys, value) if kind == "existing" else set()
        skip_keys: set[int] = set()
        if held - in_copy:
            choice = self._ask_about_held(len(held - in_copy), denomination, len(in_copy))
            if choice is None:
                return
            if choice == "skip":
                skip_keys = held
        try:
            result = AddResult()
            with self.db.tx():
                if copies_tab:
                    for (name, numbers), own in zip(groups, self.copies.collect_locations()):
                        result.merge(self.db.add_copy(name, numbers, denomination, purchase_date,
                                                      skip_keys=skip_keys,
                                                      location=own or common_location))
                else:
                    numbers = self.quick.parsed().numbers
                    if kind == "new":
                        result.merge(self.db.add_copy(value, numbers, denomination, purchase_date,
                                                      skip_keys=skip_keys,
                                                      location=common_location))
                    elif kind == "existing":
                        result.merge(self.db.append_to_copy(value, numbers, denomination,
                                                            purchase_date, skip_keys=skip_keys,
                                                            location=common_location))
                    else:
                        result.merge(self.db.add_loose_bonds(numbers, denomination, purchase_date,
                                                             skip_keys=skip_keys,
                                                             location=common_location))
        except Exception as exc:  # noqa: BLE001 - nothing was written (rolled back)
            warn(self, "Could not add bonds", str(exc))
            return
        self.price.remember()
        self.result = result
        self.accept()
