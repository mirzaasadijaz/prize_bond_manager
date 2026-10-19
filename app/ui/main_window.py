"""Main window: sidebar navigation, stacked pages, menus and status bar."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QMainWindow, QMessageBox,
                             QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from .. import __version__
from ..config import APP_NAME
from . import actions
from .context import AppContext
from .dialogs.online_dialog import OnlineDrawsDialog
from .online_auto import check_online
from .pages.bonds_page import BondsPage
from .pages.copies_page import CopiesPage
from .pages.dashboard import DashboardPage
from .pages.draws_page import DrawsPage
from .pages.history_page import HistoryPage
from .pages.pending_page import PendingPage
from .pages.sales_page import SalesPage
from .pages.wins_page import WinsPage
from .widgets import label


class MainWindow(QMainWindow):
    PAGES = [
        ("dashboard", "Dashboard", DashboardPage),
        ("bonds", "My Bonds", BondsPage),
        ("copies", "Copies (Books)", CopiesPage),
        ("draws", "Draw Results", DrawsPage),
        ("pending", "Pending Wins", PendingPage),
        ("wins", "Win List", WinsPage),
        ("sales", "Sales", SalesPage),
        ("history", "History", HistoryPage),
    ]

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(APP_NAME)
        self.resize(1360, 840)
        self.setMinimumSize(1060, 660)

        self.stack = QStackedWidget()
        self.pages: dict[str, QWidget] = {}
        self.nav: dict[str, QPushButton] = {}
        self.titles = {key: title for key, title, _ in self.PAGES}
        group = QButtonGroup(self)
        group.setExclusive(True)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(226)
        column = QVBoxLayout(sidebar)
        column.setContentsMargins(14, 22, 14, 14)
        column.setSpacing(4)
        column.addWidget(label(APP_NAME, "brand"))
        column.addWidget(label("Track bonds. Check draws. Approve wins.", "muted", wrap=True))
        column.addSpacing(16)
        for key, title, page_class in self.PAGES:
            page = page_class(ctx)
            self.pages[key] = page
            self.stack.addWidget(page)
            button = QPushButton(title)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked, k=key: self.show_page(k))
            group.addButton(button)
            self.nav[key] = button
            column.addWidget(button)
        column.addStretch(1)
        db_name = Path(ctx.db.path).name if ctx.db.path != ":memory:" else "(in memory)"
        data_label = label(f"Data file: {db_name}", "muted")
        data_label.setToolTip(str(ctx.db.path))              # the full location
        column.addWidget(data_label)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(sidebar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self._build_menus()
        self.statusBar().showMessage("Ready")
        self._dirty: set[str] = set(self.pages)
        ctx.data_changed.connect(self._on_data_changed)
        ctx.navigate.connect(self.show_page)
        ctx.status.connect(lambda text: self.statusBar().showMessage(text, 10000))
        self.show_page("dashboard")
        self._update_badge()

    # -- navigation ---------------------------------------------------------------
    def current_key(self) -> str:
        return next(k for k, p in self.pages.items() if p is self.stack.currentWidget())

    def show_page(self, key: str) -> None:
        self.stack.setCurrentWidget(self.pages[key])
        self.nav[key].setChecked(True)
        self._refresh_current()

    def _refresh_current(self) -> None:
        key = self.current_key()
        if key in self._dirty:
            self._dirty.discard(key)
            self.pages[key].refresh()

    def _on_data_changed(self) -> None:
        self._dirty = set(self.pages)
        self._refresh_current()
        self._update_badge()

    def _update_badge(self) -> None:
        pending = self.ctx.db.pending_count()
        self.nav["pending"].setText(self.titles["pending"] + (f"   ({pending:,})" if pending else ""))

    # -- menus ---------------------------------------------------------------------
    def _action(self, menu, text: str, handler, shortcut: str | None = None) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(lambda _checked=False: handler())
        menu.addAction(action)
        return action

    def _build_menus(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
        self._action(file_menu, "Add bonds...", lambda: actions.add_bonds(self.ctx, self), "Ctrl+N")
        self._action(file_menu, "Import from file...", lambda: actions.import_file(self.ctx, self),
                     "Ctrl+I")
        file_menu.addSeparator()
        self._action(file_menu, "Export everything to Excel...",
                     lambda: actions.export_everything(self.ctx, self), "Ctrl+E")
        self._action(file_menu, "Export everything to CSV files...",
                     lambda: actions.export_everything(self.ctx, self, csv_folder=True))
        self._action(file_menu, "Back up database...",
                     lambda: actions.backup_database(self.ctx, self))
        file_menu.addSeparator()
        self._action(file_menu, "Quit", self.close, "Ctrl+Q")

        agent_menu = bar.addMenu("&Agent")
        self._action(agent_menu, "Run win-checking agent now", self._run_agent, "Ctrl+R")
        self._action(agent_menu, "Go to Pending Wins", lambda: self.show_page("pending"))
        agent_menu.addSeparator()
        self._action(agent_menu, "Get draw results from the web...", self.open_online, "Ctrl+G")
        self._action(agent_menu, "Look for new draws online now",
                     lambda: check_online(self.ctx, self, forced=True))
        self._action(agent_menu, "Check a list of numbers...", self.open_checker)

        view_menu = bar.addMenu("&View")
        for number, (key, title, _) in enumerate(self.PAGES, start=1):
            self._action(view_menu, title, lambda k=key: self.show_page(k), f"Ctrl+{number}")

        help_menu = bar.addMenu("&Help")
        self._action(help_menu, "About", self._about)

    def open_online(self) -> None:
        OnlineDrawsDialog(self.ctx, self).exec()

    def open_checker(self) -> None:
        from .dialogs.check_numbers import CheckNumbersDialog
        CheckNumbersDialog(self.ctx, self).exec()

    def start_online_check(self) -> bool:
        """The quiet start-up check (does nothing unless it was switched on)."""
        return check_online(self.ctx, self)

    def _run_agent(self) -> None:
        self.ctx.offer_review(self, self.ctx.run_agent("manual", force=True))

    def _about(self) -> None:
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<b>{APP_NAME}</b> {__version__}<br><br>Keeps track of your prize bonds, checks them "
            "against draw results and moves winners to a win list after you approve them."
            f"<br><br>Data file:<br>{self.ctx.db.path}")
