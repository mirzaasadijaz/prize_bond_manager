"""Draw Results: record winning numbers, then let the agent check your bonds."""
from __future__ import annotations

import re

from PyQt6.QtCore import QStringListModel, Qt
from PyQt6.QtWidgets import (QComboBox, QCompleter, QFormLayout, QGroupBox, QHBoxLayout,
                             QLineEdit, QPlainTextEdit, QSplitter, QVBoxLayout, QWidget)

from ...config import DEFAULT_PRIZE_TIERS
from ...processing.importer import load_records
from ...processing.numbers import parse_pattern
from ...processing.parsers import FILE_DIALOG_FILTER, ParseError
from ..context import AppContext
from ..dialogs.common import DateField, DenominationBox
from ..table_model import Col
from ..widgets import (PageHeader, TablePanel, button, confirm, dash, info, label, money,
                       pick_open_file, warn)
from .base import BasePage


def _amount(value, row) -> str:
    return money(value) or "-"


class DrawsPage(BasePage):
    STAGED = [
        Col("number", "Winning number", 130, sort_key="num"),
        Col("tier", "Prize", 110),
        Col("amount", "Prize amount", 110, "right", fmt=_amount, numeric=True, export_raw=True),
    ]
    DRAWS = [
        Col("draw_date", "Draw date", 100),
        Col("price", "Price", 110),
        Col("label", "Draw", 150, fmt=dash),
        Col("location", "Location", 100, fmt=dash),
        Col("numbers", "Numbers", 80, "right", numeric=True, export_raw=True),
        Col("pending", "Pending", 75, "right", numeric=True, export_raw=True),
        Col("wins", "Wins", 70, "right", numeric=True, export_raw=True),
    ]
    NUMBERS = [
        Col("number", "Winning number", 130, sort_key="num"),
        Col("prize_label", "Prize", 120),
        Col("prize_amount", "Prize amount", 120, "right", fmt=_amount, numeric=True,
            export_raw=True),
    ]

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, parent)
        self.staged: list[dict] = []
        self._loading = False
        self.root.addWidget(PageHeader(
            "Draw Results",
            "Enter the winning numbers of a draw and where it was held. The win-checking agent "
            "then compares them with all your bonds and lists matches for your approval."))

        # -- left: the entry form -------------------------------------------------
        self.target = QComboBox()
        self.target.currentIndexChanged.connect(self._target_changed)
        self.date = DateField(allow_unknown=False)
        self.price = DenominationBox(allow_any=True)
        self.price.set_value(DenominationBox.remembered())
        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("optional, e.g. Draw #98")
        self.location_edit = QLineEdit()
        self.location_edit.setPlaceholderText("where the draw was held, e.g. Lahore")
        self.location_model = QStringListModel(self)
        completer = QCompleter(self.location_model, self.location_edit)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.location_edit.setCompleter(completer)
        details = QGroupBox("1. Which draw?")
        form = QFormLayout(details)
        form.addRow("Draw", self.target)
        form.addRow("Draw date", self.date)
        form.addRow("Bond price (Rs)", self.price)
        form.addRow("Draw name", self.label_edit)
        form.addRow("Location", self.location_edit)

        self.tier = QComboBox()
        self.tier.setEditable(True)
        self.tier.addItems(DEFAULT_PRIZE_TIERS)
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("optional, e.g. 1500000")
        self.entry = QPlainTextEdit()
        self.entry.setPlaceholderText("Paste or type winning numbers - separated by spaces, commas "
                                      "or new lines")
        self.entry.setMaximumHeight(84)
        add = button("Add to list")
        add.clicked.connect(self._add_numbers)
        from_file = button("Import from file...")
        from_file.clicked.connect(self._import_numbers)
        self.staged_panel = TablePanel(self.STAGED, toolbar=False,
                                       empty_text="Numbers you add appear here.")
        self.staged_panel.selection_changed.connect(self._update_buttons)
        self.remove_button = button("Remove selected")
        self.remove_button.clicked.connect(self._remove_staged)
        self.clear_button = button("Clear list")
        self.clear_button.clicked.connect(self._clear_staged)
        self.staged_count = label("", "muted")
        self.save_button = button("Save draw and check my bonds", "primary")
        self.save_button.clicked.connect(self._save)

        entry_box = QGroupBox("2. Winning numbers")
        box = QVBoxLayout(entry_box)
        tier_form = QFormLayout()
        tier_form.addRow("Prize", self.tier)
        tier_form.addRow("Prize amount (Rs)", self.amount)
        box.addLayout(tier_form)
        box.addWidget(self.entry)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(from_file)
        row.addStretch(1)
        box.addLayout(row)
        box.addWidget(self.staged_panel, 1)
        row = QHBoxLayout()
        row.addWidget(self.remove_button)
        row.addWidget(self.clear_button)
        row.addStretch(1)
        row.addWidget(self.staged_count)
        box.addLayout(row)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.addWidget(details)
        left_layout.addWidget(entry_box, 1)
        left_layout.addWidget(self.save_button)

        # -- right: recorded draws --------------------------------------------------
        self.draws = TablePanel(self.DRAWS, export_name="draws", sheet_name="Draws",
                                placeholder="Search draws ...",
                                empty_text="No draws recorded yet.")
        self.draws.selection_changed.connect(self._draw_selected)
        self.delete_button = button("Delete draw", "danger")
        self.delete_button.clicked.connect(self._delete_draw)
        self.numbers = TablePanel(self.NUMBERS, export_name="winning_numbers",
                                  sheet_name="Winning numbers", placeholder="Search numbers ...",
                                  empty_text="Select a draw to see its winning numbers.")
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        top = QHBoxLayout()
        top.addWidget(label("Recorded draws", "section"))
        top.addStretch(1)
        top.addWidget(self.delete_button)
        right_layout.addLayout(top)
        right_layout.addWidget(self.draws, 1)
        right_layout.addWidget(label("Winning numbers of the selected draw", "section"))
        right_layout.addWidget(self.numbers, 1)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 6)
        splitter.setChildrenCollapsible(False)
        self.root.addWidget(splitter, 1)
        self._update_buttons()

    # -- list of draws -----------------------------------------------------------------
    @staticmethod
    def _price_text(draw: dict) -> str:
        return money(draw["denomination"]) if draw["denomination"] else "Any price"

    def refresh(self) -> None:
        self.location_model.setStringList(self.db.known_locations())
        draws = self.db.list_draws()
        for draw in draws:
            draw["price"] = self._price_text(draw)
        self.draws.set_rows(draws)
        keep = self.target.currentData()
        self._loading = True
        self.target.clear()
        self.target.addItem("New draw", None)
        for draw in draws:
            name = (f"{draw['draw_date']} - {draw['price']}"
                    + (f" - {draw['label']}" if draw["label"] else "")
                    + (f" - {draw['location']}" if draw["location"] else ""))
            self.target.addItem(f"Add to: {name} ({draw['numbers']:,} numbers)", draw["id"])
            if draw["id"] == keep:
                self.target.setCurrentIndex(self.target.count() - 1)
        self._loading = False
        self._target_changed()
        self._draw_selected()

    def _target_changed(self, *_) -> None:
        if self._loading:
            return
        draw = self.db.get_draw(self.target.currentData()) if self.target.currentData() else None
        for widget in (self.date, self.price, self.label_edit, self.location_edit):
            widget.setEnabled(draw is None)
        if draw:
            self.date.set_value(draw["draw_date"])
            self.price.set_value(draw["denomination"])
            self.label_edit.setText(draw["label"] or "")
            self.location_edit.setText(draw["location"] or "")
        self.save_button.setText("Add numbers to this draw and check my bonds" if draw
                                 else "Save draw and check my bonds")

    def _draw_selected(self) -> None:
        rows = self.draws.selected_rows()
        self.delete_button.setEnabled(bool(rows))
        self.numbers.set_rows(self.db.draw_numbers(rows[0]["id"]) if len(rows) == 1 else [])

    # -- staging winning numbers ------------------------------------------------------------
    @staticmethod
    def _parse_amount(text: str) -> int | None | bool:
        text = text.strip()
        if not text:
            return None
        digits = re.sub(r"[,\s]", "", text.lower().replace("rs.", "").replace("rs", ""))
        return int(digits) if digits.isdigit() else False

    def _stage(self, numbers: list[tuple[str, int]], tier: str, amount: int | None) -> tuple[int, int]:
        known = {r["num"] for r in self.staged}
        added = 0
        for display, key in numbers:
            if key in known:
                continue
            known.add(key)
            self.staged.append({"number": display, "num": key, "tier": tier, "amount": amount})
            added += 1
        self._update_staged()
        return added, len(numbers) - added

    def _tier_and_amount(self) -> tuple[str, int | None] | None:
        amount = self._parse_amount(self.amount.text())
        if amount is False:
            warn(self, "Prize amount", "The prize amount must be a number, for example 1500000.")
            return None
        return (self.tier.currentText().strip() or "Winner"), amount

    def _add_numbers(self) -> None:
        text = self.entry.toPlainText()
        if not text.strip():
            return
        chosen = self._tier_and_amount()
        if chosen is None:
            return
        result = parse_pattern(text)
        if result.errors and not confirm(
                self, "Some entries were not understood",
                f"{len(result.errors)} entry/entries are not valid bond numbers, for example:\n\n"
                + "\n".join(result.errors[:6]) + "\n\nAdd the valid numbers anyway?",
                yes="Add the valid ones"):
            return
        added, repeated = self._stage(result.numbers, *chosen)
        repeated += len(result.duplicates)
        self.entry.clear()
        if repeated:
            self.ctx.status.emit(f"{added:,} number(s) added; {repeated:,} repeated number(s) ignored.")

    def _import_numbers(self) -> None:
        chosen = self._tier_and_amount()
        path = pick_open_file(self, "Choose a file with the winning numbers", FILE_DIALOG_FILTER) \
            if chosen else None
        if not path:
            return
        try:
            parsed = load_records(path)
        except ParseError as exc:
            warn(self, "Could not read the file", str(exc))
            return
        if not parsed.records:
            warn(self, "No numbers found", "No bond numbers were found in that file.")
            return
        added, repeated = self._stage([(r.display, r.key) for r in parsed.records], *chosen)
        info(self, "Numbers added", f"{added:,} winning number(s) added from the file"
             + (f"; {repeated:,} repeated number(s) ignored." if repeated else "."))

    def _remove_staged(self) -> None:
        chosen = {id(r) for r in self.staged_panel.selected_rows()}
        self.staged = [r for r in self.staged if id(r) not in chosen]
        self._update_staged()

    def _clear_staged(self) -> None:
        self.staged = []
        self._update_staged()

    def _update_staged(self) -> None:
        self.staged_panel.set_rows(list(self.staged))
        self.staged_count.setText(f"{len(self.staged):,} number(s) ready to save")
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.remove_button.setEnabled(bool(self.staged_panel.selected_rows()))
        self.clear_button.setEnabled(bool(self.staged))
        self.save_button.setEnabled(bool(self.staged))

    # -- saving ------------------------------------------------------------------------------
    def _save(self) -> None:
        if not self.staged:
            return
        draw_id = self.target.currentData()
        if draw_id is None:
            price = self.price.value()
            if price is None and not self.price.is_any:
                warn(self, "Bond price needed", "Enter the price of the bonds this draw is for "
                     "(for example 750), or choose 'Any denomination'.")
                return
            draw_id = self.db.add_draw(self.date.value(), price, self.label_edit.text(),
                                       self.location_edit.text())
            self.price.remember()
        items = [(r["number"], r["num"], r["tier"], r["amount"]) for r in self.staged]
        added, skipped = self.db.add_winning_numbers(draw_id, items)
        self.staged = []
        self._update_staged()
        self.entry.clear()
        scan = self.ctx.run_agent("draw", draw_id)          # also refreshes every page
        self.ctx.changed()
        lead = f"Draw saved with {added:,} winning number(s)" + (
            f" ({skipped:,} were already recorded)." if skipped else ".")
        if scan is None:
            info(self, "Draw saved", lead + "\n\nThe win-checking agent is switched off - open "
                 "Pending Wins and press 'Run agent now' to check your bonds.")
        elif scan.new_pending:
            self.ctx.offer_review(self, scan, "Draw saved", lead)
        else:
            info(self, "Draw saved", lead + "\n\nNone of your bonds match these numbers.")

    def _delete_draw(self) -> None:
        rows = self.draws.selected_rows()
        if not rows:
            return
        pending = sum(r["pending"] for r in rows)
        wins = sum(r["wins"] for r in rows)
        text = f"Delete {len(rows)} draw(s) with {sum(r['numbers'] for r in rows):,} winning number(s)?"
        if pending:
            text += f"\n\n{pending:,} pending match(es) from them will be removed."
        if wins:
            text += f"\n\n{wins:,} approved win(s) stay in the Win List."
        if not confirm(self, "Delete draws", text, yes="Delete", danger=True):
            return
        for row in rows:
            self.db.delete_draw(row["id"])
        self.ctx.changed()
