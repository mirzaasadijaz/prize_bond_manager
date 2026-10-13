"""History: a log of everything that was added, drawn, approved or removed."""
from __future__ import annotations

from ..context import AppContext
from ..table_model import Col
from ..widgets import PageHeader, TablePanel
from .base import BasePage


class HistoryPage(BasePage):
    COLUMNS = [
        Col("ts", "When", 150),
        Col("action", "What happened", 200),
        Col("details", "Details", 600, fmt=lambda v, r: v or ""),
    ]

    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(ctx, parent)
        self.root.addWidget(PageHeader(
            "History", "A log of bonds added, imported and removed, draws recorded, and wins "
            "found, approved or rejected."))
        self.panel = TablePanel(self.COLUMNS, export_name="activity_log", sheet_name="Activity log",
                                placeholder="Search the history ...",
                                empty_text="Nothing has happened yet.")
        self.root.addWidget(self.panel, 1)

    def refresh(self) -> None:
        self.panel.set_rows(self.db.list_activity())
