"""Copies (books / batches): every copy with its first number, size and what is left."""
from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox

from .. import actions
from ..context import AppContext
from ..dialogs.copy_dialogs import CopyContentsDialog, EditCopyDialog
from ..table_model import Col
from ..widgets import PageHeader, TablePanel, button, dash, thousands
from .base import BasePage


def _price(copy: dict) -> str:
    low, high = copy["min_denomination"], copy["max_denomination"]
    if low is None:
        return ""
    return f"{low:,}" if low == high else f"{low:,} - {high:,}"


class CopiesPage(BasePage):
    COLUMNS = [
        Col("name", "Copy (book)", 170),
        Col("first_number", "1st bond number", 130, fmt=dash),
        Col("size", "Positions", 90, "right", numeric=True, export_raw=True,
            fmt=lambda v, r: thousands(v)),
        Col("active", "Waiting", 80, "right", numeric=True, export_raw=True),
        Col("won", "Won", 70, "right", numeric=True, export_raw=True),
        Col("price", "Price (Rs)", 110, "right"),
        Col("purchase_date", "Purchased", 110, fmt=dash),
        Col("note", "Note", 220, fmt=lambda v, r: v or ""),
    ]

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, parent)
        header = PageHeader(
            "Copies (books)",
            "A copy is one book or batch of bonds. Each bond keeps its position in the copy, so a "
            "win can tell you exactly where to look. Copies can differ in size and in numbers.")
        self.add_button = header.add_action(button("Add copies...", "primary"))
        self.view_button = header.add_action(button("View bonds"))
        self.rename_button = header.add_action(button("Rename"))
        self.delete_button = header.add_action(button("Delete", "danger"))
        self.add_button.clicked.connect(lambda: actions.add_bonds(self.ctx, self, 0))
        self.view_button.clicked.connect(self._view)
        self.rename_button.clicked.connect(self._rename)
        self.delete_button.clicked.connect(self._delete)
        self.root.addWidget(header)

        self.panel = TablePanel(self.COLUMNS, export_name="copies", sheet_name="Copies",
                                placeholder="Search copies ...",
                                empty_text="No copies yet.\nClick 'Add copies...' to create a book "
                                           "or batch of bonds.")
        self.panel.selection_changed.connect(self._update_buttons)
        self.panel.row_activated.connect(lambda row: self._view())
        self.root.addWidget(self.panel, 1)

    def refresh(self) -> None:
        rows = self.db.list_copies()
        for row in rows:
            row["price"] = _price(row)
        self.panel.set_rows(rows)
        self._update_buttons()

    def _selected(self) -> dict | None:
        rows = self.panel.selected_rows()
        return rows[0] if len(rows) == 1 else None

    def _update_buttons(self) -> None:
        one = self._selected() is not None
        for widget in (self.view_button, self.rename_button):
            widget.setEnabled(one)
        self.delete_button.setEnabled(bool(self.panel.selected_rows()))

    def _view(self) -> None:
        copy = self._selected()
        if copy:
            CopyContentsDialog(self.ctx, copy["id"], self).exec()

    def _rename(self) -> None:
        copy = self._selected()
        if copy and EditCopyDialog(self.ctx, copy["id"], self).exec():
            self.ctx.changed()

    def _delete(self) -> None:
        rows = self.panel.selected_rows()
        if not rows:
            return
        names = ", ".join(r["name"] for r in rows[:3]) + (" ..." if len(rows) > 3 else "")
        bonds = sum(r["bonds"] for r in rows)
        box = QMessageBox(QMessageBox.Icon.Warning, "Delete copies",
                          f"Delete {len(rows)} copy/copies ({names})?",
                          QMessageBox.StandardButton.NoButton, self)
        box.setInformativeText(f"They hold {bonds:,} bond(s). You can delete the bonds too, or keep "
                               "them as loose bonds without a copy or position.")
        delete_all = box.addButton("Delete copies and bonds", QMessageBox.ButtonRole.DestructiveRole)
        keep = box.addButton("Delete copies, keep bonds", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        chosen = box.clickedButton()
        if chosen not in (delete_all, keep):
            return
        for row in rows:
            self.db.delete_copy(row["id"], delete_bonds=chosen is delete_all)
        self.ctx.changed()
        self.ctx.status.emit(f"{len(rows)} copy/copies deleted.")
