"""My Bonds: every bond grouped by price, with filters, edit and delete."""
from __future__ import annotations

import re
from datetime import datetime

from PyQt6.QtWidgets import QCheckBox, QComboBox, QFrame, QHBoxLayout, QLineEdit, QTabWidget

from .. import actions
from ..context import AppContext
from ..dialogs.edit_bond import EditBondDialog
from ..highlight import bond_row_style, highlight_button
from ..table_model import Col, same_number_col
from ..widgets import (PageHeader, TablePanel, button, confirm, dash, label, repolish,
                       thousands)
from .base import BasePage

# A bond stays in play after it wins (it can win again), so "won" is a history, not a state.
WON_CHOICES = [("All bonds", None), ("Bonds that have won", True), ("Bonds that never won", False)]


# Bonds you sold stay in the table (greyed out) if you ask for them: they are no longer yours.
HELD_CHOICES = [("Bonds I hold", False), ("Bonds I sold", True), ("Held and sold", None)]


def _status_text(value, row) -> str:
    if row["sale_id"] is not None:
        return f"Sold {row['sold_date']}" + (f" to {row['sold_to']}" if row["sold_to"] else "")
    return "Active - win pending" if row["pending_count"] else "Active"


class BondsPage(BasePage):
    COLUMNS = [
        Col("number", "Bond number", 120, sort_key="num"),
        Col("denomination", "Price (Rs)", 100, "right", numeric=True, export_raw=True,
            fmt=lambda v, r: f"{v:,}"),
        Col("purchase_date", "Purchased", 110, fmt=dash),
        Col("last_prize_date", "Last prize taken", 120, fmt=dash),
        Col("status", "Status", 240, fmt=_status_text),
        Col("location", "Location", 130, fmt=dash),
        Col("times_won", "Times won", 90, "right", numeric=True, export_raw=True,
            fmt=lambda v, r: str(v) if v else "-"),
        same_number_col("same_count", single="-"),
        Col("copy_name", "Copy (book)", 140, fmt=dash),
        Col("position", "Position", 80, "right", numeric=True, export_raw=True,
            fmt=lambda v, r: thousands(v) or "-"),
        Col("copy_first_number", "1st bond of copy", 130, fmt=dash),
    ]

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, parent)
        self.panels: dict[int | None, TablePanel] = {}
        self._keys: list[int | None] = []

        header = PageHeader("My Bonds", "Your bonds grouped by price. Click a column heading to "
                            "sort; use the search box or the filters to narrow the list. Green rows "
                            "have already won; 'Highlight' gives rows a colour of your own. The same "
                            "number can sit in several copies - the 'Same number' "
                            "column shows it, and they all win together. Bonds stay in every "
                            "draw after a win; 'Times won' counts their wins.")
        self.add_button = header.add_action(button("Add bonds...", "primary"))
        self.import_button = header.add_action(button("Import file..."))
        self.sell_button = header.add_action(button("Sell selected...",
                                                    tooltip="Record that the selected bonds were "
                                                            "sold to somebody"))
        self.highlight_button = header.add_action(highlight_button(self, self._highlight))
        self.edit_button = header.add_action(button("Edit"))
        self.delete_button = header.add_action(button("Delete", "danger"))
        self.add_button.clicked.connect(lambda: actions.add_bonds(self.ctx, self))
        self.import_button.clicked.connect(lambda: actions.import_file(self.ctx, self))
        self.sell_button.clicked.connect(self._sell)
        self.edit_button.clicked.connect(self._edit)
        self.delete_button.clicked.connect(self._delete)
        self.root.addWidget(header)

        self.held = QComboBox()
        for text, value in HELD_CHOICES:
            self.held.addItem(text, value)
        self.held.setToolTip("Sold bonds are not yours any more: they take no part in draws held "
                             "on or after the day they were sold")
        self.won = QComboBox()
        for text, value in WON_CHOICES:
            self.won.addItem(text, value)
        self.number_from, self.number_to = QLineEdit(), QLineEdit()
        self.date_from, self.date_to = QLineEdit(), QLineEdit()
        for edit, hint in ((self.number_from, "from"), (self.number_to, "to"),
                           (self.date_from, "YYYY-MM-DD"), (self.date_to, "YYYY-MM-DD")):
            edit.setPlaceholderText(hint)
            edit.setMaximumWidth(112)
            edit.returnPressed.connect(self.refresh)
        self.shared_only = QCheckBox("Shared numbers only")
        self.shared_only.setToolTip("Show just the bonds whose number sits in more than one "
                                    "copy (they win together)")
        self.shared_only.toggled.connect(self.refresh)
        apply = button("Apply")
        apply.clicked.connect(self.refresh)
        clear = button("Clear filters")
        clear.clicked.connect(self._clear_filters)
        self.won.currentIndexChanged.connect(self.refresh)
        self.held.currentIndexChanged.connect(self.refresh)

        bar = QFrame()
        bar.setObjectName("Card")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 10, 14, 10)
        for widget in (label("Show", "muted"), self.held, self.won, label("Number", "muted"),
                       self.number_from, label("-", "muted"), self.number_to,
                       label("Purchased", "muted"), self.date_from, label("-", "muted"),
                       self.date_to, self.shared_only, apply, clear):
            row.addWidget(widget)
        row.addStretch(1)
        self.root.addWidget(bar)

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(lambda *_: self._update_buttons())
        self.root.addWidget(self.tabs, 1)

    # -- tabs ------------------------------------------------------------------
    def _make_panel(self, key: int | None) -> TablePanel:
        name = "all_bonds" if key is None else f"bonds_rs_{key}"
        panel = TablePanel(self.COLUMNS, export_name=name, sheet_name="Bonds" if key is None
                           else f"Rs {key}", row_style=bond_row_style,
                           placeholder="Search bond number, copy, date ...",
                           empty_text="No bonds to show here.\nUse 'Add bonds...' or "
                                      "'Import file...' to get started.")
        panel.selection_changed.connect(self._update_buttons)
        panel.row_activated.connect(lambda row: self._edit())
        return panel

    def _current_panel(self) -> TablePanel | None:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, TablePanel) else None

    def _ensure_tabs(self, keys: list[int | None]) -> None:
        if keys == self._keys:
            return
        current = next((k for k, p in self.panels.items() if p is self.tabs.currentWidget()), None)
        self.tabs.blockSignals(True)
        self.tabs.clear()
        for key in [k for k in self.panels if k not in keys]:
            self.panels.pop(key).deleteLater()
        for key in keys:
            if key not in self.panels:
                self.panels[key] = self._make_panel(key)
            self.tabs.addTab(self.panels[key], "")
        self._keys = list(keys)
        self.tabs.blockSignals(False)
        if current in keys:
            self.tabs.setCurrentIndex(keys.index(current))

    # -- filters -----------------------------------------------------------------
    @staticmethod
    def _number(edit: QLineEdit) -> int | None:
        digits = re.sub(r"\D", "", edit.text())
        return int(digits) if digits else None

    def _date(self, edit: QLineEdit) -> str | None | bool:
        text = edit.text().strip()
        bad = False
        if text:
            try:
                datetime.strptime(text, "%Y-%m-%d")
            except ValueError:
                bad = True
        edit.setProperty("invalid", bad)
        repolish(edit)
        return False if bad else (text or None)

    def _filters(self) -> dict | None:
        date_from, date_to = self._date(self.date_from), self._date(self.date_to)
        if date_from is False or date_to is False:
            return None
        return {"sold": self.held.currentData(), "won": self.won.currentData(),
                "number_from": self._number(self.number_from),
                "number_to": self._number(self.number_to), "date_from": date_from,
                "date_to": date_to}

    def _clear_filters(self) -> None:
        for edit in (self.number_from, self.number_to, self.date_from, self.date_to):
            edit.clear()
        self.won.setCurrentIndex(0)
        self.held.setCurrentIndex(0)
        self.shared_only.setChecked(False)
        self.refresh()

    # -- refresh -------------------------------------------------------------------
    def refresh(self) -> None:
        filters = self._filters()
        if filters is None:
            return
        bonds = self.db.list_bonds(**filters)
        if self.shared_only.isChecked():
            bonds = [b for b in bonds if (b["same_count"] or 0) > 1]
        by_price: dict[int, list[dict]] = {}
        for bond in bonds:
            by_price.setdefault(bond["denomination"], []).append(bond)
        keys: list[int | None] = [None] + self.db.denominations()
        self._ensure_tabs(keys)
        for key in keys:
            rows = bonds if key is None else by_price.get(key, [])
            panel = self.panels[key]
            panel.set_rows(rows)
            title = "All prices" if key is None else f"Rs {key:,}"
            self.tabs.setTabText(self.tabs.indexOf(panel), f"{title}  ({len(rows):,})")
        self._update_buttons()

    def _update_buttons(self) -> None:
        panel = self._current_panel()
        rows = panel.selected_rows() if panel else []
        self.edit_button.setEnabled(len(rows) == 1)
        self.highlight_button.setEnabled(bool(rows))
        self.delete_button.setEnabled(bool(rows))
        self.sell_button.setEnabled(bool(rows) and all(r["sale_id"] is None for r in rows))

    # -- actions ---------------------------------------------------------------------
    def _edit(self) -> None:
        panel = self._current_panel()
        rows = panel.selected_rows() if panel else []
        if len(rows) != 1:
            return
        if not self.ctx.guard(self, "edit this bond"):
            return
        if EditBondDialog(self.ctx, rows[0]["id"], self).exec():
            self.ctx.changed()
            self.ctx.offer_review(self, self.ctx.run_agent("bonds"))

    def _highlight(self, colour) -> None:
        panel = self._current_panel()
        rows = panel.selected_rows() if panel else []
        if rows and self.ctx.guard(self, "change the colour"):
            self.db.set_highlight("bonds", [r["id"] for r in rows], colour)
            self.ctx.changed()

    def _sell(self) -> None:
        panel = self._current_panel()
        rows = [r for r in (panel.selected_rows() if panel else []) if r["sale_id"] is None]
        if rows:
            actions.sell_bonds(self.ctx, self, rows)

    def _delete(self) -> None:
        panel = self._current_panel()
        rows = panel.selected_rows() if panel else []
        if not rows:
            return
        if not self.ctx.guard(self, "delete bonds"):
            return
        won = sum(1 for r in rows if r["times_won"])
        text = f"Delete {len(rows):,} bond(s)? This cannot be undone."
        if won:
            text += (f"\n\n{won:,} of them have won before; their win records stay in the Win "
                     "List.")
        sold = sum(1 for r in rows if r["sale_id"] is not None)
        if sold:
            text += f"\n\n{sold:,} of them were sold; the sale records keep their details."
        if not confirm(self, "Delete bonds", text, yes="Delete", danger=True):
            return
        removed = self.db.delete_bonds([r["id"] for r in rows])
        self.ctx.changed()
        self.ctx.status.emit(f"{removed:,} bond(s) deleted.")
