"""Draw Results: record winning numbers, then let the agent check your bonds."""
from __future__ import annotations

import re

from PyQt6.QtCore import QItemSelectionModel, QStringListModel, Qt
from PyQt6.QtWidgets import (QComboBox, QCompleter, QFormLayout, QGroupBox, QHBoxLayout,
                             QLineEdit, QPlainTextEdit, QSplitter, QVBoxLayout, QWidget)

from ...config import DEFAULT_PRIZE_TIERS
from ...db import WinningNumberError
from ...db.core import KEEP
from ...online.parse import read_result_file
from ...processing.importer import load_records
from ...processing.numbers import normalize_number, parse_pattern
from ...processing.parsers import ParseError
from ..context import AppContext
from ..dialogs.common import DateField, DenominationBox
from ..dialogs.edit_numbers import EditNumbersDialog
from ..dialogs.online_dialog import OnlineDrawsDialog
from ..dialogs.tier_dialog import PrizeTiersDialog
from ..table_model import Col
from ..widgets import (PageHeader, TablePanel, button, confirm, dash, info, label, money,
                       pick_open_file, warn)
from .base import BasePage


RESULT_FILTER = ("Results and lists (*.txt *.pdf *.html *.htm *.csv *.tsv *.xlsx *.xlsm *.docx);;"
                 "All files (*)")


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
        Col("label", "Draw", 130, fmt=dash),
        Col("location", "Location", 100, fmt=dash),
        Col("source_text", "Entered", 130),
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
        header = PageHeader(
            "Draw Results",
            "Enter the winning numbers of a draw and where it was held - by hand, from a file, or "
            "let the program fetch them from the official site. The win-checking agent then "
            "compares them with all your bonds and lists matches for your approval.")
        self.web_button = header.add_action(button(
            "Get results from the web...", "primary",
            tooltip="Read the published results from savings.gov.pk (or prizebond.net) and "
                    "save the draws you pick"))
        self.web_button.clicked.connect(self._from_web)
        self.root.addWidget(header)

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
        self.staged_panel.row_activated.connect(lambda row: self._edit_staged(False))
        self.edit_staged_button = button("Edit selected...")
        self.edit_staged_button.clicked.connect(lambda: self._edit_staged(False))
        self.edit_staged_all_button = button("Edit all...")
        self.edit_staged_all_button.clicked.connect(lambda: self._edit_staged(True))
        self.tiers_staged_button = button("Prizes by tier...", tooltip="1st prize = this number, "
                                          "2nd prize = these numbers, all the rest = 3rd prize")
        self.tiers_staged_button.clicked.connect(self._tiers_staged)
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
        row.addWidget(self.edit_staged_button)
        row.addWidget(self.edit_staged_all_button)
        row.addWidget(self.tiers_staged_button)
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
        self.numbers.selection_changed.connect(self._update_number_buttons)
        self.numbers.row_activated.connect(lambda row: self._edit_numbers(False))
        self.edit_numbers_button = button("Edit selected...", tooltip="Change the number, prize "
                                          "and prize amount (select several to change their "
                                          "prize together)")
        self.edit_numbers_button.clicked.connect(lambda: self._edit_numbers(False))
        self.edit_all_button = button("Edit all...", tooltip="Change the prize of every number "
                                      "shown below (use the search box to narrow them down)")
        self.edit_all_button.clicked.connect(lambda: self._edit_numbers(True))
        self.tiers_button = button("Prizes by tier...", tooltip="1st prize = this number, 2nd "
                                   "prize = these numbers, all the rest = 3rd prize")
        self.tiers_button.clicked.connect(self._tiers_numbers)
        self.numbers.add_tool(self.edit_numbers_button)
        self.numbers.add_tool(self.edit_all_button)
        self.numbers.add_tool(self.tiers_button)
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
            draw["source_text"] = ("Typed in" if draw["source"] == "Manual"
                                   else f"Fetched: {draw['source']}")
        kept = {r["id"] for r in self.draws.selected_rows()}     # stay on the draw being edited
        self.draws.set_rows(draws)
        self._reselect(kept)
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

    def _reselect(self, draw_ids: set[int]) -> None:
        view = self.draws.view
        for row in range(self.draws.proxy.rowCount()):
            index = self.draws.proxy.index(row, 0)
            source = self.draws.model.row_at(self.draws.proxy.mapToSource(index).row())
            if source["id"] in draw_ids:
                view.selectionModel().select(
                    index, QItemSelectionModel.SelectionFlag.Select
                    | QItemSelectionModel.SelectionFlag.Rows)

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
        self._update_number_buttons()

    def _update_number_buttons(self) -> None:
        self.edit_numbers_button.setEnabled(bool(self.numbers.selected_rows()))
        self.edit_all_button.setEnabled(bool(self.numbers.visible_rows()))
        self.tiers_button.setEnabled(len(self.draws.selected_rows()) == 1)

    # -- editing the numbers of a recorded draw ----------------------------------------
    def _edit_numbers(self, everything: bool) -> None:
        rows = self.numbers.visible_rows() if everything else self.numbers.selected_rows()
        draws = self.draws.selected_rows()
        if not rows or len(draws) != 1:
            return
        if not self.ctx.guard(self, "edit the winning numbers"):
            return
        scope = " shown" if everything and self.numbers.search.text().strip() else ""
        dialog = EditNumbersDialog(rows, ("number", "prize_label", "prize_amount"), scope, self)
        if not dialog.exec():
            return
        try:
            if len(rows) == 1:
                moved = self.db.update_winning_number(rows[0]["id"], dialog.number, dialog.prize,
                                                      dialog.amount)
            else:
                moved = False
                self.db.update_prizes([r["id"] for r in rows], dialog.prize, dialog.amount)
        except WinningNumberError as exc:
            warn(self, "Cannot save", str(exc))
            return
        scan = self.ctx.run_agent("draw", draws[0]["id"]) if moved else None
        self.ctx.changed()
        self.ctx.status.emit(f"{len(rows):,} winning number(s) changed.")
        self.ctx.offer_review(self, scan, "Draw changed")

    def _tiers_numbers(self) -> None:
        draws = self.draws.selected_rows()
        if len(draws) != 1:
            return
        if not self.ctx.guard(self, "change the prizes of this draw"):
            return
        dialog = PrizeTiersDialog(self)
        if not dialog.exec():
            return
        changed, added = self.db.set_prize_tiers(draws[0]["id"], dialog.tiers, dialog.rest)
        scan = self.ctx.run_agent("draw", draws[0]["id"]) if added else None
        self.ctx.changed()
        self.ctx.status.emit(f"Prizes set: {changed:,} number(s) changed, {added:,} added.")
        self.ctx.offer_review(self, scan, "Draw changed")

    # -- editing the numbers that are not saved yet ----------------------------------------
    def _edit_staged(self, everything: bool) -> None:
        rows = list(self.staged) if everything else self.staged_panel.selected_rows()
        if not rows:
            return
        dialog = EditNumbersDialog(rows, ("number", "tier", "amount"), "", self)
        if not dialog.exec():
            return
        if len(rows) == 1:
            display, key = normalize_number(dialog.number)
            if any(r is not rows[0] and r["num"] == key for r in self.staged):
                warn(self, "Cannot save", f"The list already has the number {display}.")
                return
            rows[0].update(number=display, num=key)
        for row in rows:
            if dialog.prize is not KEEP:
                row["tier"] = dialog.prize
            if dialog.amount is not KEEP:
                row["amount"] = dialog.amount
        self._update_staged()

    def _tiers_staged(self) -> None:
        dialog = PrizeTiersDialog(self)
        if not dialog.exec():
            return
        if dialog.rest is not None:
            for row in self.staged:
                row["tier"], row["amount"] = dialog.rest
        by_key = {r["num"]: r for r in self.staged}
        for name, amount, numbers in dialog.tiers:
            for display, key in numbers:
                row = by_key.get(key)
                if row is None:
                    row = by_key[key] = {"number": display, "num": key}
                    self.staged.append(row)
                row["tier"], row["amount"] = name, amount
        self._update_staged()

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

    def _from_web(self) -> None:
        OnlineDrawsDialog(self.ctx, self).exec()
        self.ctx.changed()

    def _import_numbers(self) -> None:
        chosen = self._tier_and_amount()
        path = pick_open_file(self, "Choose a file with the winning numbers", RESULT_FILTER) \
            if chosen else None
        if not path:
            return
        official = read_result_file(path)
        if official is not None and official.number_count:
            self._stage_result(official)
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

    def _stage_result(self, draw) -> None:
        """A whole published result (official .txt / .pdf, saved prizebond.net page): every
        prize tier with its amount, and the draw's price, name and place filled in."""
        added = repeated = 0
        for prize in draw.prizes:
            numbers = [normalize_number(n) for n in prize.numbers]
            more, again = self._stage(numbers, prize.label, prize.amount)
            added, repeated = added + more, repeated + again
        if draw.denomination and self.target.currentData() is None:
            self.price.set_value(draw.denomination)
        if draw.draw_date and self.target.currentData() is None:
            self.date.set_value(draw.draw_date)
        if draw.label and not self.label_edit.text().strip():
            self.label_edit.setText(draw.label)
        if draw.location and not self.location_edit.text().strip():
            self.location_edit.setText(draw.location)
        note = "\n\n".join(draw.warnings)
        info(self, "Results read from the file",
             f"{added:,} winning number(s) added with their prize tiers"
             + (f"; {repeated:,} repeated number(s) ignored" if repeated else "") + "."
             + ("" if draw.draw_date else "\n\nThe file does not give the draw date - check "
                "the date above.") + (f"\n\nNote:\n{note}" if note else ""))

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
        self.edit_staged_button.setEnabled(bool(self.staged_panel.selected_rows()))
        self.edit_staged_all_button.setEnabled(bool(self.staged))
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
        if not self.ctx.guard(self, "delete draws"):
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
