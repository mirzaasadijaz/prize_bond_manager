"""Prize Bond Manager - start here:  python main.py"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prize Bond Manager")
    parser.add_argument("--db", help="data file to use, e.g. my.db - a name without a folder is "
                                     "kept next to the program (default: prize_bonds.db there)")
    parser.add_argument("--demo", action="store_true",
                        help="open a fresh demo database (demo.db next to the program) filled "
                             "with sample bonds, copies and a draw")
    args = parser.parse_args(argv)

    from PyQt6.QtWidgets import QApplication, QMessageBox

    from app import demo
    from app.config import APP_DIR, APP_NAME, resolve_db_path
    from app.db import Database, DatabaseInUseError
    from app.ui.context import AppContext
    from app.ui.main_window import MainWindow
    from app.ui.theme import STYLESHEET

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("PrizeBondManager")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)

    if args.demo:
        path = APP_DIR / "demo.db"
    else:
        path = resolve_db_path(args.db)
    try:
        db = Database(path, lock=True)
        if args.demo:
            # only a demo file that no other window has open may be replaced
            db.close()
            path.unlink(missing_ok=True)
            db = Database(path, lock=True)
    except DatabaseInUseError as exc:
        QMessageBox.warning(None, APP_NAME, str(exc))
        return 1
    except Exception as exc:  # unreadable file, newer schema, no permission ...
        QMessageBox.critical(None, APP_NAME, f"The data file could not be opened:\n{path}\n\n{exc}")
        return 1
    if args.demo:
        demo.seed(db)

    ctx = AppContext(db)
    window = MainWindow(ctx)
    window.show()
    ctx.run_agent("startup")          # silent unless it finds something; see the sidebar badge
    code = app.exec()
    db.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
