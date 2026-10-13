"""Win report window: copy, 1st bond number of the copy and position for every win."""
from __future__ import annotations

from datetime import date

from PyQt6.QtWidgets import QApplication, QDialog, QHBoxLayout, QTextBrowser, QVBoxLayout

from ...processing import exporter, reports
from ..widgets import button, info, label, pick_save_file, warn

SAVE_FILTER = ("HTML page (*.html);;Text file (*.txt);;"
               "Excel workbook (*.xlsx);;CSV file (*.csv)")


def save_report(parent, wins: list[dict]) -> None:
    """Save wins as a report file; the format follows the chosen extension."""
    target = pick_save_file(parent, "Save win report", f"win_report_{date.today().isoformat()}.html",
                            SAVE_FILTER)
    if target is None:
        return
    try:
        extension = target.suffix.lower()
        if extension == ".html":
            target.write_text(reports.win_report_html(wins), encoding="utf-8")
        elif extension == ".txt":
            target.write_text(reports.win_report_text(wins), encoding="utf-8")
        else:
            headers, rows = reports.win_table(wins)
            exporter.write_table(target, headers, rows, "Win report")
    except (OSError, ValueError) as exc:
        warn(parent, "Could not save the report", str(exc))
        return
    info(parent, "Report saved", f"Saved to:\n{target}")


class WinReportDialog(QDialog):
    """Read-only report for one or more wins, with copy / save buttons."""

    def __init__(self, wins: list[dict], title: str = "Win report", intro: str = "", parent=None):
        super().__init__(parent)
        self.wins = wins
        self.setWindowTitle(title)
        self.resize(640, 640)
        self.browser = QTextBrowser()
        self.browser.setHtml(reports.win_report_html(wins, title))

        copy = button("Copy as text")
        copy.clicked.connect(self._copy)
        save = button("Save report...")
        save.clicked.connect(lambda: save_report(self, self.wins))
        close = button("Close", "primary")
        close.clicked.connect(self.accept)
        footer = QHBoxLayout()
        footer.addWidget(copy)
        footer.addWidget(save)
        footer.addStretch(1)
        footer.addWidget(close)

        layout = QVBoxLayout(self)
        if intro:
            layout.addWidget(label(intro, "muted", wrap=True))
        layout.addWidget(self.browser, 1)
        layout.addLayout(footer)

    def _copy(self) -> None:
        QApplication.clipboard().setText(reports.win_report_text(self.wins))
