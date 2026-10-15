"""Dialogs for a single copy: rename it, or look at its bonds position by position."""
from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLineEdit, QVBoxLayout

from ...db import CopyNameError
from .. import theme
from ..context import AppContext
from ..table_model import Col, same_number_col
from ..widgets import TablePanel, button, label, thousands, warn


class EditCopyDialog(QDialog):
    def __init__(self, ctx: AppContext, copy_id: int, parent=None):
        super().__init__(parent)
        self.db, self.copy_id = ctx.db, copy_id
        copy = self.db.get_copy(copy_id)
        self.setWindowTitle("Rename copy")
        self.setMinimumWidth(420)
        self.name = QLineEdit(copy["name"])
        self.note = QLineEdit(copy["note"] or "")
        self.note.setPlaceholderText("optional, e.g. where it was bought")
        form = QFormLayout()
        form.addRow("Copy name", self.name)
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
        layout.addLayout(footer)

    def _save(self) -> None:
        try:
            self.db.rename_copy(self.copy_id, self.name.text(), self.note.text().strip())
        except CopyNameError as exc:
            warn(self, "Cannot save", str(exc))
            return
        self.accept()


def _status(value, row) -> str:
    if row["pending_count"]:
        return "Win pending"
    return f"Won {row['times_won']}x" if row["times_won"] else "-"


def _style(row):
    if row["pending_count"]:
        return theme.WARNING_TEXT, theme.WARNING_BG
    return None


class CopyContentsDialog(QDialog):
    """Every bond of a copy in book order (position 1, 2, 3 ...)."""

    COLUMNS = [
        Col("position", "Position", 80, "right", numeric=True, fmt=lambda v, r: thousands(v)),
        Col("number", "Bond number", 130, sort_key="num"),
        Col("denomination", "Price (Rs)", 100, "right", numeric=True, fmt=lambda v, r: f"{v:,}"),
        Col("purchase_date", "Purchased", 110, fmt=lambda v, r: v or "-"),
        same_number_col("same_count", single="-"),
        Col("status", "Status", 160, fmt=_status),
    ]

    def __init__(self, ctx: AppContext, copy_id: int, parent=None):
        super().__init__(parent)
        db = ctx.db
        copy = db.get_copy(copy_id)
        bonds = db.copy_bonds(copy_id)
        won = sum(1 for b in bonds if b["times_won"])
        self.setWindowTitle(f"Copy: {copy['name']}")
        self.resize(640, 560)
        layout = QVBoxLayout(self)
        layout.addWidget(label(copy["name"], "section"))
        layout.addWidget(label(
            f"1st bond number: {copy['first_number'] or '-'}   |   {copy['size']} position(s)   |   "
            f"{len(bonds)} bond(s) on file, {won} have won"
            + (f"   |   {copy['note']}" if copy["note"] else ""), "muted", wrap=True))
        self.panel = TablePanel(self.COLUMNS, export_name=f"copy_{copy['name']}",
                                sheet_name=copy["name"], row_style=_style,
                                empty_text="This copy has no bonds on file.")
        self.panel.set_rows(bonds)
        layout.addWidget(self.panel, 1)
        close = button("Close")
        close.clicked.connect(self.accept)
        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(close)
        layout.addLayout(footer)
