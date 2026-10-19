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
    parser.add_argument("--serve", action="store_true",
                        help="do not open the window: run the local checking API instead "
                             "(POST /check takes thousands of bonds in one request)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="with --serve: address to listen on (default 127.0.0.1, this "
                             "computer only)")
    parser.add_argument("--port", type=int, default=8765, help="with --serve: port (default 8765)")
    parser.add_argument("--token", default=None,
                        help="with --serve: require 'Authorization: Bearer <token>' "
                             "(needed when --host is not this computer)")
    args = parser.parse_args(argv)

    if args.serve:                    # no window: Qt is not even imported
        from app.api.server import run
        from app.config import resolve_db_path
        run(resolve_db_path(args.db), host=args.host, port=args.port, token=args.token)
        return 0

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
        demo.seed(db, with_sale=True)

    ctx = AppContext(db)
    window = MainWindow(ctx)
    window.show()
    ctx.run_agent("startup")          # silent unless it finds something; see the sidebar badge
    window.start_online_check()       # only if switched on, at most once a day, in the background
    code = app.exec()
    db.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
