"""Actions that more than one page or menu can start (add, import, export, backup)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from PyQt6.QtWidgets import QFileDialog

from ..processing import exporter
from .context import AppContext
from .dialogs.add_bonds import AddBondsDialog
from .dialogs.import_dialog import ImportDialog
from .dialogs.sale_dialog import SaleDialog
from .dialogs.win_report import WinReportDialog
from .widgets import info, last_dir, pick_save_file, remember_dir, warn


def add_bonds(ctx: AppContext, parent, start_tab: int = 0) -> None:
    if not ctx.guard(parent, "add bonds"):
        return
    dialog = AddBondsDialog(ctx, parent, start_tab)
    if dialog.exec() and dialog.result:
        ctx.after_bonds_added(parent, dialog.result, "Bonds added")


def import_file(ctx: AppContext, parent, path: str | None = None) -> None:
    if not ctx.guard(parent, "import bonds"):
        return
    dialog = ImportDialog(ctx, parent, path)
    if dialog.exec() and dialog.result:
        ctx.after_bonds_added(parent, dialog.result, "Import finished")


def sell_bonds(ctx: AppContext, parent, bonds: list[dict] | None = None) -> int | None:
    """Open the sale dialog (optionally with bonds already chosen); returns the new sale's id."""
    dialog = SaleDialog(ctx, parent, bonds)
    if not dialog.exec() or dialog.sale_id is None:
        return None
    sale = ctx.db.get_sale(dialog.sale_id)
    ctx.changed()
    ctx.status.emit(f"Sale recorded: {sale['bonds']:,} bond(s) for Rs {sale['total_amount']:,}. "
                    "They are now shown as sold.")
    return dialog.sale_id


def show_win_report(parent, wins: list[dict], title: str = "Win report", intro: str = "") -> None:
    if wins:
        WinReportDialog(wins, title, intro, parent).exec()


def export_everything(ctx: AppContext, parent, csv_folder: bool = False) -> None:
    """Every list in the app: one Excel workbook, or one CSV file per list in a folder."""
    stamp = date.today().isoformat()
    try:
        sheets = exporter.collect_all(ctx.db)
        if csv_folder:
            folder = QFileDialog.getExistingDirectory(parent, "Choose a folder for the CSV files",
                                                      last_dir())
            if not folder:
                return
            remember_dir(Path(folder))
            written = exporter.write_csv_folder(
                Path(folder) / f"prize_bonds_{stamp}", sheets)
            info(parent, "Export complete", f"{len(written)} CSV files saved in:\n"
                 f"{written[0].parent}")
        else:
            target = pick_save_file(parent, "Export everything to Excel",
                                    f"prize_bonds_{stamp}.xlsx", "Excel workbook (*.xlsx)")
            if target is None:
                return
            exporter.write_workbook(target, sheets)
            info(parent, "Export complete",
                 f"{len(sheets)} sheets (bonds by price, copies, pending wins, win list, draws, "
                 f"activity) saved to:\n{target}")
    except PermissionError:
        warn(parent, "Export failed", "A file could not be written. Is it open in another program?")
    except Exception as exc:  # noqa: BLE001
        warn(parent, "Export failed", str(exc))


def backup_database(ctx: AppContext, parent) -> None:
    target = pick_save_file(parent, "Back up the database",
                            f"prize_bonds_backup_{date.today().isoformat()}.db",
                            "SQLite database (*.db)")
    if target is None:
        return
    try:
        ctx.db.backup_to(target)
    except Exception as exc:  # noqa: BLE001
        warn(parent, "Backup failed", str(exc))
        return
    info(parent, "Backup complete", f"A complete copy of your data was saved to:\n{target}")
