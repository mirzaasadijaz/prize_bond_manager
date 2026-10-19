"""Win List: approved wins with copy, 1st bond number, position, location, status and feedback."""
from __future__ import annotations

from ...config import FINAL_WIN_STATUS, STATUS_PROBLEM, STATUS_SUBMITTED
from ...processing import reports
from .. import actions, theme
from ..context import AppContext
from ..dialogs.win_details import EditWinDetailsDialog
from ..dialogs.win_report import save_report
from ..table_model import Col, same_number_col
from ..widgets import Note, PageHeader, TablePanel, button, confirm, dash
from .base import BasePage


def _status_style(row):
    status = row.get("claim_status")
    if status == FINAL_WIN_STATUS:
        return theme.SUCCESS_TEXT, theme.SUCCESS_BG
    if status == STATUS_SUBMITTED:
        return theme.WARNING_TEXT, theme.WARNING_BG
    if status == STATUS_PROBLEM:
        return theme.DANGER, "#FEE2E2"
    return None


def _one_line(value, row) -> str:
    return " ".join((value or "").split()) or "-"


class WinsPage(BasePage):
    COLUMNS = [
        Col("draw_date", "Draw date", 92),
        Col("location", "Location", 100, fmt=dash),
        Col("bond_number", "Bond number", 104),
        Col("denomination", "Price (Rs)", 76, "right", numeric=True, export_raw=True,
            fmt=lambda v, r: f"{v:,}"),
        Col("prize", "Prize", 165),
        Col("copy", "Copy (book)", 104),
        Col("copy_first_number", "1st bond of copy", 118, fmt=dash),
        Col("where", "Position in copy", 114),
        Col("bond_location", "Bond kept at", 110, fmt=dash),
        Col("sold_date", "Bond sold", 150, fmt=lambda v, r: reports.sold_text(r) or "-"),
        same_number_col(),
        Col("win_no", "Win no.", 72, "right", numeric=True,
            fmt=lambda v, r: reports.win_no_text(r)),
        Col("claim_status", "Status", 120),
        Col("feedback", "Feedback", 240, fmt=_one_line),
        Col("draw_label", "Draw", 100, fmt=dash),
        Col("approved_at", "Approved", 130),
    ]

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, parent)
        header = PageHeader("Win List", "Approved wins. Each one shows the draw and its location, "
                            "the copy, that copy's 1st bond number and the position - plus the "
                            "status of your claim and a feedback note. Double-click a row for the "
                            "full report.")
        self.report_button = header.add_action(button("Show report", "primary"))
        self.save_button = header.add_action(button("Save report..."))
        self.details_button = header.add_action(button(
            "Status / location...", tooltip="Set where the prize is claimed, how the claim stands "
                                            "and add a feedback note to the selected wins"))
        self.revert_button = header.add_action(button(
            "Undo approval", "danger", tooltip="Remove a win that was approved by mistake"))
        self.report_button.clicked.connect(self._show)
        self.save_button.clicked.connect(self._save)
        self.details_button.clicked.connect(self._details)
        self.revert_button.clicked.connect(self._revert)
        self.root.addWidget(header)
        self.panel = TablePanel(self.COLUMNS, export_name="win_list", sheet_name="Win list",
                                row_style=_status_style, placeholder="Search wins ...",
                                empty_text="No wins yet.\nApproved matches from the Pending Wins "
                                           "page are listed here.")
        self.panel.selection_changed.connect(self._update_buttons)
        self.panel.row_activated.connect(lambda r: actions.show_win_report(
            self, reports.with_same_number([r], self.panel.all_rows()), "Win report"))
        self.root.addWidget(self.panel, 1)
        self.root.addWidget(Note(
            "A bond keeps taking part in every draw after it wins, so the same bond can be listed "
            "more than once - another draw, another place, another date. 'Win no.' says which win "
            "a row is. A number held in several copies wins in every copy, one row per bond; "
            "each row has its own status and feedback."))
        self.total = self.panel.count_label

    def refresh(self) -> None:
        rows = self.db.list_wins()
        for r in rows:
            r["prize"] = reports.prize_text(r)
            r["copy"] = reports.copy_text(r) if r["copy_name"] else "-"
            r["where"] = reports.position_text(r) or "-"
        self.panel.set_rows(rows)
        self._update_buttons()

    def _targets(self) -> list[dict]:
        """Selected wins (or everything shown when nothing is selected) for a report.

        A winning number's report always covers every bond that won with it.
        """
        chosen = self.panel.selected_rows()
        if not chosen:
            return self.panel.visible_rows()
        return reports.with_same_number(chosen, self.panel.all_rows())

    def _update_buttons(self) -> None:
        has_rows = bool(self.panel.visible_rows())
        selected = bool(self.panel.selected_rows())
        self.report_button.setEnabled(has_rows)
        self.save_button.setEnabled(has_rows)
        self.details_button.setEnabled(selected)
        self.revert_button.setEnabled(selected)

    def _show(self) -> None:
        actions.show_win_report(self, self._targets(), "Win report")

    def _save(self) -> None:
        wins = self._targets()
        if wins:
            save_report(self, wins)

    def _details(self) -> None:
        rows = self.panel.selected_rows()
        if rows and not self.ctx.guard(self, "edit the win details"):
            return
        if rows and EditWinDetailsDialog(self.ctx, rows, self).exec():
            self.ctx.changed()

    def _revert(self) -> None:
        rows = self.panel.selected_rows()
        if not rows:
            return
        if not self.ctx.guard(self, "undo the approval"):
            return
        others = sum(1 for r in rows if (r.get("same_number_count") or 1) > 1)
        note = ("\n\nOnly the selected bond(s) are affected; other bonds holding the same number "
                "keep their wins unless you select them too." if others else "")
        if not confirm(self, "Undo approval",
                       f"Remove {len(rows):,} win(s) from the Win List?\n\nUse this if a win was "
                       "approved by mistake. The bonds stay in your list. The matches go to the "
                       "'Rejected' view of Pending Wins, where you can restore them if you change "
                       f"your mind.{note}",
                       yes="Undo approval", danger=True):
            return
        self.db.revert_wins([r["id"] for r in rows])
        self.ctx.changed()
