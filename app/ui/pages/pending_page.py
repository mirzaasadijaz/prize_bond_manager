"""Pending Wins: the agent's temporary list. Nothing moves until you approve it."""
from __future__ import annotations

from PyQt6.QtWidgets import QCheckBox, QComboBox, QFrame, QHBoxLayout

from ...processing import reports
from .. import actions, theme
from ..context import AppContext
from ..table_model import Col, same_number_col
from ..widgets import Note, PageHeader, TablePanel, button, confirm, dash, label, warn
from .base import BasePage


def _style(row):
    if row["pending_status"] == "rejected":
        return theme.WON_TEXT, "#F1F5F9"
    if row["warning"]:
        return theme.WARNING_TEXT, theme.WARNING_BG
    return None


class PendingPage(BasePage):
    COLUMNS = [
        Col("draw_date", "Draw date", 92),
        Col("draw_label", "Draw", 90, fmt=dash),
        Col("draw_location", "Location", 90, fmt=dash),
        Col("bond_number", "Bond number", 104, sort_key="bond_num"),
        Col("denomination", "Price (Rs)", 86, "right", numeric=True, export_raw=True,
            fmt=lambda v, r: f"{v:,}"),
        Col("prize", "Prize", 175),
        same_number_col(),
        Col("copy", "Copy (book)", 104),
        Col("copy_first_number", "1st bond of copy", 126, fmt=dash),
        Col("where", "Position in copy", 124),
        Col("times_won", "Won before", 88, "right", numeric=True, export_raw=True,
            fmt=lambda v, r: f"{v}x" if v else "-"),
        Col("check", "Check", 150),
        Col("found_at", "Found", 130),
    ]

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, parent)
        self.agent = ctx.agent
        header = PageHeader("Pending Wins", "Bonds the win-checking agent matched with winning "
                            "numbers. Approve them to add them to the Win List - or reject any "
                            "that look wrong. A number held in several copies wins in every copy, "
                            "and a bond that won before can win again.")
        self.approve_button = header.add_action(button("Approve selected", "primary"))
        self.approve_all_button = header.add_action(button("Approve all"))
        self.reject_button = header.add_action(button("Reject selected", "danger"))
        self.restore_button = header.add_action(button("Restore selected"))
        self.approve_button.clicked.connect(lambda: self._approve(self.panel.selected_rows()))
        self.approve_all_button.clicked.connect(lambda: self._approve(self.panel.visible_rows()))
        self.reject_button.clicked.connect(self._reject)
        self.restore_button.clicked.connect(self._restore)
        self.root.addWidget(header)

        card = QFrame()
        card.setObjectName("Card")
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 10, 16, 10)
        self.status_text = label("", wrap=True)
        run = button("Run agent now", tooltip="Check every waiting bond against every recorded draw")
        run.clicked.connect(self._run_agent)
        self.auto = QCheckBox("Run automatically")
        self.auto.setToolTip("Check at start-up, after bonds are added or imported, and after a "
                             "draw is saved")
        self.auto.toggled.connect(self._toggle_auto)
        row.addWidget(label("Win-checking agent", "section"))
        row.addWidget(self.status_text, 1)
        row.addWidget(self.auto)
        row.addWidget(run)
        self.root.addWidget(card)

        self.view = QComboBox()
        self.view.addItem("Waiting for approval", "pending")
        self.view.addItem("Rejected", "rejected")
        self.view.currentIndexChanged.connect(self.refresh)
        self.panel = TablePanel(self.COLUMNS, export_name="pending_wins", sheet_name="Pending wins",
                                row_style=_style, placeholder="Search pending wins ...",
                                empty_text="Nothing to review.\nWhen winning numbers match one of "
                                           "one of your bonds it will appear here.")
        self.panel.add_tool(self.view)
        self.panel.selection_changed.connect(self._update_buttons)
        self.panel.row_activated.connect(self._show_report)
        self.root.addWidget(self.panel, 1)
        self.root.addWidget(Note("Rows in amber are flagged: the bond's purchase date is later than "
                                 "the draw date. Check them before approving. When the same number "
                                 "sits in several copies, every one of those bonds wins: approving "
                                 "one of them approves them all (reject a bond first to keep it "
                                 "out)."))

    # -- data -----------------------------------------------------------------------
    def refresh(self) -> None:
        status = self.view.currentData()
        rows = self.db.list_pending(status)
        for r in rows:
            r["prize"] = reports.prize_text(r)
            r["copy"] = reports.copy_text(r) if r["copy_name"] else "-"
            r["where"] = reports.position_text(r) or "-"
            r["check"] = (r["note"] or "Rejected") if status == "rejected" else (r["warning"] or "OK")
        self.panel.set_rows(rows)
        self.status_text.setText(self.agent.last_run_text())
        self.auto.blockSignals(True)
        self.auto.setChecked(self.agent.auto_enabled)
        self.auto.blockSignals(False)
        self._update_buttons()

    def _update_buttons(self) -> None:
        pending_view = self.view.currentData() == "pending"
        selected = bool(self.panel.selected_rows())
        self.approve_button.setEnabled(pending_view and selected)
        self.approve_all_button.setEnabled(pending_view and bool(self.panel.visible_rows()))
        self.reject_button.setEnabled(pending_view and selected)
        self.restore_button.setEnabled(not pending_view and selected)

    # -- agent ----------------------------------------------------------------------------
    def _run_agent(self) -> None:
        result = self.ctx.run_agent("manual", force=True)
        if result and not result.new_pending:
            self.status_text.setText(self.agent.last_run_text())
            warn_text = result.summary()
            self.ctx.status.emit(warn_text)
        else:
            self.ctx.offer_review(self, result)

    def _toggle_auto(self, enabled: bool) -> None:
        self.agent.auto_enabled = enabled
        self.ctx.status.emit("The agent will run automatically." if enabled
                             else "Automatic runs are off - use 'Run agent now'.")

    # -- decisions ---------------------------------------------------------------------------
    def _show_report(self, row: dict) -> None:
        """Report on a match - together with every other bond holding the same number."""
        rows = reports.with_same_number([row], self.panel.all_rows())
        actions.show_win_report(self, rows, "Possible win",
                                "This win is still waiting for your approval.")

    def _approve(self, rows: list[dict]) -> None:
        if not rows:
            return
        chosen = [r["pending_id"] for r in rows]
        # Bonds in other copies holding the same winning number win too.
        extra = len(set(self.db.pending_siblings(chosen)) - set(chosen))
        flagged = sum(1 for r in rows if r["warning"])
        text = f"Approve {len(rows):,} win(s)?\n\nThey will be added to the Win List."
        if extra:
            text += (f"\n\n{extra:,} more bond(s) hold the same winning number(s) in other copies, "
                     f"so they win too: {len(rows) + extra:,} bond(s) in total will be moved.")
        if flagged:
            text += (f"\n\n{flagged:,} of them are flagged (bond bought after the draw date). "
                     "Make sure they are right.")
        if not confirm(self, "Approve wins", text, yes="Approve"):
            return
        result = self.agent.approve(chosen)
        self.ctx.changed()
        if result.rejected:
            warn(self, "Some matches were not approved",
                 "\n".join(f"- {reason}" for _, reason in result.rejected[:8]))
        wins = [self.db.get_win(win_id) for win_id in result.win_ids]
        n = result.with_siblings
        shared = (f" {n:,} of them {'holds' if n == 1 else 'hold'} the same number as another "
                  "winning bond." if n else "")
        actions.show_win_report(
            self, [w for w in wins if w], "Approved wins",
            f"{result.approved:,} win(s) added to the Win List.{shared} For each win: the copy it "
            "belongs to, that copy's 1st bond number, its position and where it was drawn. Set the "
            "claim status and your feedback in the Win List.")

    def _reject(self) -> None:
        rows = self.panel.selected_rows()
        if rows and confirm(
                self, "Reject matches",
                f"Reject {len(rows):,} match(es)?\n\nThe bonds stay in your list and will "
                "not be flagged again for this draw. You can restore them from the 'Rejected' view."
                "\n\nOther bonds holding the same number are not affected - reject those too if "
                "the number should not count.",
                yes="Reject", danger=True):
            self.agent.reject([r["pending_id"] for r in rows])
            self.ctx.changed()

    def _restore(self) -> None:
        rows = self.panel.selected_rows()
        if rows:
            self.agent.restore([r["pending_id"] for r in rows])
            self.ctx.changed()
