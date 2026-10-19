"""Get draw results from the web: official site first, then other sites, then a pasted link."""
from __future__ import annotations

from PyQt6.QtCore import QItemSelectionModel
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QLineEdit,
                             QPlainTextEdit, QTabWidget, QVBoxLayout, QDialog)

from ...config import DEFAULT_DENOMINATIONS
from ...online.fetcher import MODES, ResultFetcher
from ...online.http import HttpClient
from ...online.model import Listed, OnlineDraw, Trace
from ...online.store import (SETTING_AUTO, SETTING_MODE, SETTING_VERIFY, plan_auto,
                             save_draw)
from .. import theme
from ..background import run_in_background
from ..context import AppContext
from ..table_model import Col
from ..widgets import TablePanel, button, confirm, dash, info, label, money, warn
from .common import DateField, DenominationBox

MAX_PRESELECTED = 6          # newest draws ticked for you after a search


def default_fetcher(mode: str) -> ResultFetcher:
    return ResultFetcher(HttpClient(), mode)


def _style(row: dict):
    if row.get("error"):
        return theme.DANGER, None
    if row.get("draw") is not None and row["draw"].warnings:
        return theme.WARNING_TEXT, theme.WARNING_BG
    if row.get("recorded") and row.get("draw") is None:
        return theme.MUTED, None
    return None


class OnlineDrawsDialog(QDialog):
    """Search the sites for draws, read the ones you pick, save them and check your bonds.

    The numbers are never saved before you press the save button, and nothing is approved: the
    win-checking agent only lists possible wins for you to review.
    """

    COLUMNS = [
        Col("draw_date", "Draw date", 100, fmt=dash),
        Col("price", "Price", 90, "right", sort_key="denomination"),
        Col("draw_no", "Draw", 60, "right", numeric=True, fmt=dash),
        Col("location", "Held in", 110, fmt=dash),
        Col("sources", "Found on", 150),
        Col("state", "Status", 330),
    ]

    def __init__(self, ctx: AppContext, parent=None, fetcher_factory=None, threaded: bool = True):
        super().__init__(parent)
        self.ctx, self.db = ctx, ctx.db
        self.factory = fetcher_factory or default_fetcher
        self.threaded = threaded
        self.rows: list[dict] = []
        self.saved: list[int] = []                      # ids of the draws saved by this dialog
        self.trace = Trace()
        self._busy = False
        self.setWindowTitle("Get draw results from the web")
        self.resize(1020, 780)

        # -- where and which prices ------------------------------------------------------
        self.mode = QComboBox()
        for key, text in MODES.items():
            self.mode.addItem(text, key)
        saved_mode = self.db.get_setting(SETTING_MODE, "auto")
        self.mode.setCurrentIndex(max(0, self.mode.findData(saved_mode)))
        self.verify = QCheckBox("Check the numbers against a second site as well (slower)")
        self.verify.setChecked(self.db.get_setting(SETTING_VERIFY) == "1")
        self.verify.setToolTip("Each draw is read from two sites and the numbers are compared; "
                               "a difference is shown as a warning.")
        held = plan_auto(self.db).prices
        self.price_boxes: dict[int, QCheckBox] = {}
        prices = QHBoxLayout()
        for price in sorted(set(DEFAULT_DENOMINATIONS) | set(held)):
            box = QCheckBox(f"Rs {price:,}")
            box.setChecked(price in held if held else price in (200, 750, 1500))
            self.price_boxes[price] = box
            prices.addWidget(box)
        prices.addStretch(1)
        self.look_button = button("Look for draws", "primary")
        self.look_button.clicked.connect(self._look)
        source_box = QGroupBox("1. Where to look")
        form = QVBoxLayout(source_box)
        row = QHBoxLayout()
        row.addWidget(label("Source", "muted"))
        row.addWidget(self.mode, 1)
        row.addWidget(self.look_button)
        form.addLayout(row)
        form.addWidget(label("Bond prices to look for", "muted"))
        form.addLayout(prices)
        form.addWidget(self.verify)

        # -- the draws found ---------------------------------------------------------------
        self.listing = TablePanel(self.COLUMNS, toolbar=False, row_style=_style,
                                  empty_text="Press 'Look for draws' to see which draws the "
                                             "sites list.")
        self.listing.selection_changed.connect(self._selection_changed)
        self.read_button = button("Read selected draws")
        self.read_button.clicked.connect(self._read)
        self.save_button = button("Save selected draws and check my bonds", "primary")
        self.save_button.clicked.connect(self._save)
        self.progress = label("", "muted", wrap=True)
        found_box = QGroupBox("2. Pick the draws")
        column = QVBoxLayout(found_box)
        column.addWidget(self.listing, 1)
        row = QHBoxLayout()
        row.addWidget(self.progress, 1)
        row.addWidget(self.read_button)
        row.addWidget(self.save_button)
        column.addLayout(row)

        # -- a pasted link ----------------------------------------------------------------------
        self.link_edit = QLineEdit()
        self.link_edit.setPlaceholderText("https://... a result .txt / .pdf from savings.gov.pk, "
                                          "or a prizebond.net result page")
        self.link_date = DateField(allow_unknown=False)
        self.link_price = DenominationBox(allow_blank=True)
        self.link_price.setMaximumWidth(100)
        self.link_button = button("Read link")
        self.link_button.clicked.connect(self._read_link)
        link_box = QGroupBox("Or paste a link to a result")
        row = QHBoxLayout(link_box)
        row.addWidget(self.link_edit, 1)
        row.addWidget(label("if it gives no date / price:", "muted"))
        row.addWidget(self.link_date)
        row.addWidget(self.link_price)
        row.addWidget(self.link_button)

        # -- details and log -----------------------------------------------------------------------
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.details, "Selected draw")
        self.tabs.addTab(self.log, "What was tried")
        self.tabs.setMaximumHeight(190)

        self.auto = QCheckBox("Look for new draws by myself when the program starts "
                              "(at most once a day, only for prices I hold)")
        self.auto.setChecked(self.db.get_setting(SETTING_AUTO) == "1")
        self.auto.toggled.connect(lambda on: self.db.set_setting(SETTING_AUTO, "1" if on else "0"))
        self.mode.currentIndexChanged.connect(
            lambda *_: self.db.set_setting(SETTING_MODE, self.mode.currentData()))
        self.verify.toggled.connect(lambda on: self.db.set_setting(SETTING_VERIFY,
                                                                   "1" if on else "0"))
        close = button("Close")
        close.clicked.connect(self.reject)
        footer = QHBoxLayout()
        footer.addWidget(self.auto, 1)
        footer.addWidget(close)

        layout = QVBoxLayout(self)
        layout.addWidget(label(
            "The program reads the published winning numbers from the official National Savings "
            "site and, if that does not work, from prizebond.net. You choose which draws to keep; "
            "then your bonds are checked and possible wins wait for your approval. You can always "
            "type the numbers in by hand on the Draw Results page instead.", "muted", wrap=True))
        layout.addWidget(source_box)
        layout.addWidget(found_box, 1)
        layout.addWidget(link_box)
        layout.addWidget(self.tabs)
        layout.addLayout(footer)
        self._selection_changed()

    # -- helpers ----------------------------------------------------------------------------------
    def _fetcher(self) -> ResultFetcher:
        return self.factory(self.mode.currentData())

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self._busy = busy
        self.progress.setText(text)
        self.look_button.setEnabled(not busy)
        self.link_button.setEnabled(not busy)
        self._selection_changed()

    def _failed(self, text: str) -> None:
        self._set_busy(False, f"Something went wrong: {text}")

    def _show_trace(self) -> None:
        self.log.setPlainText(self.trace.text() or "Nothing was tried yet.")

    def _refill(self, keep: list[dict] | None = None) -> None:
        self.listing.set_rows(self.rows)
        if keep:
            self._select(keep)
        self._selection_changed()

    def _select(self, rows: list[dict]) -> None:
        wanted = {id(r) for r in rows}
        view, proxy = self.listing.view, self.listing.proxy
        shown = self.listing.visible_rows()
        flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        view.selectionModel().clearSelection()
        for position, row in enumerate(shown):
            if id(row) in wanted:
                view.selectionModel().select(proxy.index(position, 0), flags)

    def _row_for(self, listed: Listed, **extra) -> dict:
        row = {"listed": listed, "draw_date": listed.draw_date, "denomination": listed.denomination,
               "price": money(listed.denomination), "draw_no": listed.draw_no,
               "location": listed.location, "sources": ", ".join(listed.sources) or "-",
               "draw": None, "error": "", "state": "", "recorded": False}
        known = self.db.find_draw(listed.draw_date, listed.denomination) if listed.draw_date \
            else None
        if known:
            count = len(self.db.draw_numbers(known["id"]))
            row["recorded"] = True
            row["state"] = f"Already recorded ({count:,} numbers)"
        else:
            row["state"] = "New"
        row.update(extra)
        return row

    # -- 1. look -----------------------------------------------------------------------------------
    def _look(self) -> None:
        prices = [p for p, box in self.price_boxes.items() if box.isChecked()]
        if not prices:
            warn(self, "Choose a price", "Tick at least one bond price to look for.")
            return
        fetcher, trace = self._fetcher(), Trace()
        self._set_busy(True, "Looking for draws ...")
        run_in_background(lambda: (fetcher.list_draws(prices, trace), trace), self._looked,
                          self._failed, self.threaded)

    def _looked(self, answer) -> None:
        listed, self.trace = answer
        self.rows = [self._row_for(entry) for entry in listed]
        self._refill()
        fresh = [r for r in self.rows if not r["recorded"]][:MAX_PRESELECTED]
        self._select(fresh)
        self._show_trace()
        if self.rows:
            text = (f"{len(self.rows)} draw(s) found, {sum(not r['recorded'] for r in self.rows)} "
                    "of them new. Pick the ones you want, then press 'Read selected draws'.")
        else:
            text = ("No draws were found. 'What was tried' says why. You can paste a link below "
                    "or type the numbers in by hand.")
            self.tabs.setCurrentWidget(self.log)
        self._set_busy(False, text)

    # -- 2. read -------------------------------------------------------------------------------------
    def _selected(self) -> list[dict]:
        return self.listing.selected_rows()

    def _selection_changed(self) -> None:
        rows = self._selected()
        self.read_button.setEnabled(not self._busy and bool(rows))
        self.save_button.setEnabled(not self._busy and any(r["draw"] is not None for r in rows))
        if len(rows) == 1:
            self._describe(rows[0])

    def _read(self) -> None:
        rows = [r for r in self._selected() if r["listed"].refs]
        if not rows:
            return
        fetcher, trace, verify = self._fetcher(), Trace(), self.verify.isChecked()

        def job():
            out = []
            for row in rows:
                try:
                    out.append((row, fetcher.fetch(row["listed"], trace, verify), ""))
                except Exception as exc:  # noqa: BLE001 - FetchError or a reader problem
                    out.append((row, None, str(exc)))
            return out, trace

        self._set_busy(True, f"Reading {len(rows)} draw(s) ...")
        run_in_background(job, self._was_read, self._failed, self.threaded)

    def _was_read(self, answer) -> None:
        results, self.trace = answer
        for row, draw, error in results:
            row["draw"], row["error"] = draw, error
            if draw is None:
                row["state"] = f"Could not be read: {error}"
            else:
                row["draw_date"] = draw.draw_date or row["draw_date"]
                row["draw_no"] = draw.draw_no or row["draw_no"]
                row["location"] = draw.location or row["location"]
                row["state"] = self._read_text(draw)
        chosen = [row for row, _, _ in results]
        self._refill(chosen)
        self._show_trace()
        good = sum(1 for _, draw, _ in results if draw is not None)
        self._set_busy(False, f"{good} of {len(results)} draw(s) read. Check the details below, "
                              "then save.")

    @staticmethod
    def _read_text(draw: OnlineDraw) -> str:
        text = f"Read: {draw.number_count:,} numbers from {draw.source}"
        if draw.verified_by:
            text += f", confirmed by {draw.verified_by}"
        if draw.warnings:
            text += f"  -  {len(draw.warnings)} warning(s)"
        return text

    def _describe(self, row: dict) -> None:
        draw = row["draw"]
        listed = row["listed"]
        lines = [f"{row['price']} draw of {row['draw_date'] or '(date unknown)'}"
                 + (f", draw no. {row['draw_no']}" if row["draw_no"] else "")
                 + (f", held in {row['location']}" if row["location"] else "")]
        lines.append("Listed by: " + (", ".join(listed.sources) or "(pasted link)"))
        if row["recorded"]:
            lines.append("This draw is already recorded; saving adds any numbers it does not "
                         "have yet.")
        if row["error"]:
            lines += ["", f"Could not be read: {row['error']}"]
        if draw is not None:
            lines += ["", f"Read from {draw.source}: {draw.url}"]
            for prize in draw.prizes:
                extra = f" (the page says {prize.declared:,})" if prize.declared and \
                    prize.declared != len(prize.numbers) else ""
                amount = f" - {money(prize.amount)} each" if prize.amount else ""
                sample = ", ".join(prize.numbers[:6]) + (" ..." if len(prize.numbers) > 6 else "")
                lines.append(f"  {prize.label}{amount}: {len(prize.numbers):,} number(s){extra}  "
                             f"{sample}")
            if draw.verified_by:
                lines.append(f"The numbers agree with {draw.verified_by}.")
            lines += [f"WARNING: {w}" for w in draw.warnings]
        self.details.setPlainText("\n".join(lines))
        self.tabs.setCurrentWidget(self.details)

    # -- link -------------------------------------------------------------------------------------------
    def _read_link(self) -> None:
        url = self.link_edit.text().strip()
        if not url:
            return
        fetcher, trace = self._fetcher(), Trace()
        self._set_busy(True, "Reading the link ...")
        run_in_background(lambda: (fetcher.fetch_link(url, trace), trace), self._link_read,
                          self._link_failed, self.threaded)

    def _link_failed(self, text: str) -> None:
        self.trace.add("link", "link", False, text)
        self._show_trace()
        self.tabs.setCurrentWidget(self.log)
        self._set_busy(False, f"The link could not be read: {text}")

    def _link_read(self, answer) -> None:
        draw, self.trace = answer
        if not draw.draw_date:
            draw.draw_date = self.link_date.value()
            draw.warnings.append(f"the file gives no date - {draw.draw_date} (from the date box) "
                                 "is used")
        if not draw.denomination:
            draw.denomination = self.link_price.value()
        if not draw.denomination:
            self._set_busy(False, "The link gave no bond price - choose the price next to the "
                                  "date box and read it again.")
            return
        listed = Listed(draw.denomination, draw.draw_date, draw.draw_no, draw.location, [])
        row = self._row_for(listed, draw=draw, sources=draw.source)
        row["state"] = self._read_text(draw)
        self.rows = [r for r in self.rows if not (r["listed"].refs == [] and
                                                  r["draw_date"] == row["draw_date"] and
                                                  r["denomination"] == row["denomination"])]
        self.rows.insert(0, row)
        self._refill([row])
        self._show_trace()
        self._set_busy(False, "Read from the link. Check the details, then save.")

    # -- 3. save --------------------------------------------------------------------------------------
    def _save(self) -> None:
        rows = [r for r in self._selected() if r["draw"] is not None]
        if not rows:
            return
        flagged = [r for r in rows if r["draw"].warnings]
        if flagged:
            text = "\n".join(f"- {r['price']} {r['draw_date']}: {r['draw'].warnings[0]}"
                             for r in flagged[:6])
            if not confirm(self, "Save draws with warnings?",
                           f"{len(flagged)} of these draw(s) have warnings:\n\n{text}\n\nSave "
                           "them anyway? (You can delete a draw later on the Draw Results page.)",
                           yes="Save anyway"):
                return
        total_added = 0
        try:
            for row in rows:
                outcome = save_draw(self.db, row["draw"])
                self.saved.append(outcome.draw_id)
                total_added += outcome.added
        except ValueError as exc:
            warn(self, "Cannot save", str(exc))
            return
        self.ctx.changed()
        scan = self.ctx.run_agent("draw")
        lead = f"{len(rows)} draw(s) saved with {total_added:,} new winning number(s)."
        if scan is None:
            info(self, "Draws saved", lead + "\n\nThe win-checking agent is switched off - open "
                 "Pending Wins and press 'Run agent now' to check your bonds.")
        elif scan.new_pending:
            self.ctx.offer_review(self, scan, "Draws saved", lead)
        else:
            info(self, "Draws saved", lead + "\n\nNone of your bonds match these numbers.")
        self.accept()
