"""Editor for adding several copies (books / batches), each with its own numbers."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from PyQt6.QtCore import QRegularExpression, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QRegularExpressionValidator
from PyQt6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout,
                             QHBoxLayout, QLineEdit, QPlainTextEdit, QSpinBox, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from ...db import Database
from ...processing.numbers import PatternResult, format_number, parse_pattern
from .. import theme
from ..widgets import button, label

_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


@dataclass
class CopyRow:
    name: str
    pattern: str = ""
    result: PatternResult = field(default_factory=PatternResult)
    problem: str = ""        # blocks adding
    note: str = ""           # information only (numbers shared with other copies)


def _item(text: str = "", editable: bool = False, right: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
    if editable:
        flags |= Qt.ItemFlag.ItemIsEditable
    item.setFlags(flags)
    if right:
        item.setTextAlignment(_RIGHT)
    return item


class CopiesEditor(QWidget):
    """A table of copies plus a text box for the numbers of the selected copy."""

    changed = pyqtSignal()
    HEADERS = ["Copy name", "Bonds", "First number", "Last number", "Check"]

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self.rows: list[CopyRow] = []
        self._loading = False

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((170, 70, 110, 110)):
            self.table.setColumnWidth(column, width)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.currentCellChanged.connect(lambda *_: self._sync_editor())

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("Numbers of the selected copy, in book order. For example:\n"
                                       "100001-100100\n250010, 250011, 250020-250030")
        self.editor.setEnabled(False)
        self.editor.textChanged.connect(self._on_pattern_changed)
        self.summary = label("", "muted")

        add = button("+ Add copy")
        add.clicked.connect(lambda: self.add_row())
        remove = button("Remove copy", "danger")
        remove.clicked.connect(self.remove_current)
        generate = button("Generate copies...", tooltip="Create several copies of a regular size at once")
        generate.clicked.connect(self._generate)
        tools = QHBoxLayout()
        for widget in (add, remove, generate):
            tools.addWidget(widget)
        tools.addStretch(1)
        tools.addWidget(self.summary)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.addWidget(label(
            "Each copy is one book or batch. Type its numbers in the order they sit in the book - "
            "ranges (100001-100100), single numbers or a mix. Copies do not have to share a range, "
            "a size or a sequence, and the same number may appear in several copies (when it is "
            "drawn, every bond holding it wins).", "muted", wrap=True))
        layout.addWidget(self.table, 3)
        layout.addLayout(tools)
        layout.addWidget(label("Numbers in the selected copy (the order you type is the position "
                               "in the book)", "section"))
        layout.addWidget(self.editor, 2)
        self.add_row()

    # -- rows -----------------------------------------------------------------
    def _next_name(self) -> str:
        used = {r.name.strip().casefold() for r in self.rows}
        for candidate in self.db.suggest_copy_names(len(self.rows) + 50):
            if candidate.casefold() not in used:
                return candidate
        return f"Copy {len(self.rows) + 1}"

    def add_row(self, name: str | None = None, pattern: str = "") -> None:
        row = CopyRow(name or self._next_name(), pattern, parse_pattern(pattern))
        self.rows.append(row)
        self._loading = True
        index = self.table.rowCount()
        self.table.insertRow(index)
        self.table.setItem(index, 0, _item(row.name, editable=True))
        for column in (1, 2, 3):
            self.table.setItem(index, column, _item(right=column == 1))
        self.table.setItem(index, 4, _item())
        self._loading = False
        self.table.setCurrentCell(index, 0)
        self.revalidate()
        self.editor.setFocus()

    def remove_current(self) -> None:
        index = self.table.currentRow()
        if index < 0:
            return
        self.table.removeRow(index)
        del self.rows[index]
        if self.rows:
            self.table.setCurrentCell(min(index, len(self.rows) - 1), 0)
        self._sync_editor()
        self.revalidate()

    def add_generated(self, patterns: list[str]) -> None:
        if len(self.rows) == 1 and not self.rows[0].pattern.strip():
            self.table.removeRow(0)
            self.rows.clear()
        for pattern in patterns:
            self.add_row(pattern=pattern)

    def _generate(self) -> None:
        dialog = GenerateCopiesDialog(self)
        if dialog.exec():
            self.add_generated(dialog.patterns())

    # -- editing ------------------------------------------------------------------
    def _sync_editor(self) -> None:
        index = self.table.currentRow()
        self._loading = True
        self.editor.setEnabled(index >= 0)
        self.editor.setPlainText(self.rows[index].pattern if 0 <= index < len(self.rows) else "")
        self._loading = False

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() != 0 or item.row() >= len(self.rows):
            return
        self.rows[item.row()].name = item.text()
        self.revalidate()

    def _on_pattern_changed(self) -> None:
        index = self.table.currentRow()
        if self._loading or not 0 <= index < len(self.rows):
            return
        row = self.rows[index]
        row.pattern = self.editor.toPlainText()
        row.result = parse_pattern(row.pattern)
        self.revalidate()

    # -- validation ---------------------------------------------------------------
    def _shared_note(self, index: int, holders: dict[int, list[int]]) -> str:
        """Which numbers of this copy also sit in another copy of the dialog (not an error)."""
        shared = [k for _, k in self.rows[index].result.numbers if len(holders[k]) > 1]
        if not shared:
            return ""
        others = sorted({i for k in shared for i in holders[k] if i != index})
        first = self.rows[others[0]].name.strip() or "another copy"
        more = f" and {len(others) - 1} more" if len(others) > 1 else ""
        return f"{len(shared):,} number(s) also in '{first}'{more}"

    def revalidate(self) -> None:
        holders: dict[int, list[int]] = {}
        for index, row in enumerate(self.rows):
            for _, key in row.result.numbers:
                holders.setdefault(key, []).append(index)
        name_counts = Counter(r.name.strip().casefold() for r in self.rows)
        self._loading = True
        for index, row in enumerate(self.rows):
            problems: list[str] = []
            name = row.name.strip()
            if not name:
                problems.append("name is empty")
            elif name_counts[name.casefold()] > 1:
                problems.append("name used twice")
            elif self.db.copy_name_taken(name):
                problems.append("name already exists")
            if not row.result.numbers and not row.result.errors:
                problems.append("enter the bond numbers")
            if not row.result.ok:
                problems.append(row.result.problems(2))
            row.problem = "; ".join(problems)
            row.note = self._shared_note(index, holders)

            result = row.result
            self.table.item(index, 1).setText(f"{result.count:,}")
            self.table.item(index, 2).setText(result.first)
            self.table.item(index, 3).setText(result.last)
            check = self.table.item(index, 4)
            if row.problem:
                check.setText(row.problem)
                colour = theme.DANGER
            elif row.note:
                check.setText(f"OK - {row.note}")
                colour = theme.WARNING_TEXT
            else:
                check.setText("OK")
                colour = theme.SUCCESS_TEXT
            check.setToolTip("" if not row.note else
                             "The same number may sit in several copies. If it is drawn, every "
                             "bond holding it wins.")
            check.setForeground(QBrush(QColor(colour)))
        self._loading = False
        bad = sum(1 for r in self.rows if r.problem)
        total = sum(r.result.count for r in self.rows)
        shared = sum(1 for r in self.rows if r.note)
        if bad:
            self.summary.setText(f"{bad} copy/copies need attention")
            self.summary.setProperty("role", "problem")
        else:
            extra = f", {shared} with shared numbers" if shared else ""
            self.summary.setText(f"{len(self.rows)} copy/copies, {total:,} bond(s){extra}")
            self.summary.setProperty("role", "ok")
        self.summary.style().unpolish(self.summary)
        self.summary.style().polish(self.summary)
        self.changed.emit()

    # -- results ------------------------------------------------------------------
    def is_valid(self) -> bool:
        return bool(self.rows) and all(not r.problem for r in self.rows)

    def collect(self) -> list[tuple[str, list[tuple[str, int]]]]:
        return [(r.name.strip(), r.result.numbers) for r in self.rows]


class GenerateCopiesDialog(QDialog):
    """Fill the copies table with several regular copies (each can be edited afterwards)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generate copies")
        self.setMinimumWidth(460)
        self.count = QSpinBox()
        self.count.setRange(1, 500)
        self.count.setValue(5)
        self.size = QSpinBox()
        self.size.setRange(1, 100000)
        self.size.setValue(100)
        self.first = QLineEdit("100001")
        self.first.setValidator(QRegularExpressionValidator(QRegularExpression(r"[0-9]{1,12}")))
        self.gap = QSpinBox()
        self.gap.setRange(0, 10_000_000)
        self.preview = label("", "muted", wrap=True)

        form = QFormLayout()
        form.addRow("Number of copies", self.count)
        form.addRow("Bonds in each copy", self.size)
        form.addRow("First number of the first copy", self.first)
        form.addRow("Numbers skipped between copies", self.gap)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(label("Creates equal-sized copies that follow on from each other. "
                               "Afterwards you can still change any copy on its own.", "muted",
                               wrap=True))
        layout.addLayout(form)
        layout.addWidget(self.preview)
        layout.addWidget(buttons)
        for spin in (self.count, self.size, self.gap):
            spin.valueChanged.connect(self._update)
        self.first.textChanged.connect(self._update)
        self._update()

    def patterns(self) -> list[str]:
        if not self.first.text().strip():
            return []
        start, size, step = int(self.first.text()), self.size.value(), self.size.value() + self.gap.value()
        return [f"{format_number(start + i * step)}-{format_number(start + i * step + size - 1)}"
                for i in range(self.count.value())]

    def _update(self) -> None:
        patterns = self.patterns()
        self.ok_button.setEnabled(bool(patterns))
        if not patterns:
            self.preview.setText("Enter the first number.")
            return
        shown = ",   ".join(patterns[:3]) + (",   ..." if len(patterns) > 3 else "")
        self.preview.setText(f"{len(patterns)} copies, {len(patterns) * self.size.value():,} "
                             f"bonds:   {shown}")
