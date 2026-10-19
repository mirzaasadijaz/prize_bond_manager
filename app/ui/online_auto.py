"""Look for new draw results by itself: when the program starts, or when asked from the menu."""
from __future__ import annotations

from datetime import date

from ..online.store import SETTING_AUTO, SETTING_LAST, SETTING_MODE, apply_auto, fetch_auto, plan_auto
from .background import run_in_background
from .context import AppContext
from .dialogs.online_dialog import default_fetcher
from .widgets import info


def check_online(ctx: AppContext, parent, forced: bool = False, fetcher_factory=None,
                 threaded: bool = True) -> bool:
    """Start a check for new draws; returns False if none was started.

    Without ``forced`` this is the quiet start-up check: it only runs when the person switched
    it on, at most once a day, and it never opens a window unless a possible win was found.  The
    network part runs in a worker thread; the data file is only used by this (main) thread.
    """
    db = ctx.db
    today = date.today().isoformat()
    if not forced and (db.get_setting(SETTING_AUTO) != "1" or db.get_setting(SETTING_LAST) == today):
        return False
    if getattr(ctx, "online_busy", False):
        return False
    plan = plan_auto(db)
    if plan.error:
        if forced:
            ctx.status.emit(plan.error)
        return False
    fetcher = (fetcher_factory or default_fetcher)(db.get_setting(SETTING_MODE, "auto") or "auto")
    ctx.online_busy = True
    ctx.status.emit("Looking for new draw results online ...")

    def done(fetched) -> None:
        ctx.online_busy = False
        result = apply_auto(db, fetched)
        if not fetched.error:
            db.set_setting(SETTING_LAST, today)
        ctx.changed()
        ctx.status.emit("Online check: " + result.summary())
        scan = ctx.run_agent("draw") if result.saved else None
        if scan is not None and scan.new_pending:
            ctx.offer_review(parent, scan, "New draw results",
                             f"{len(result.saved)} new draw(s) were fetched from the web.")
        elif forced and result.needs_review:
            info(parent, "Some draws need your review",
                 f"{len(result.needs_review)} draw(s) could not be saved by themselves (for "
                 "example the numbers looked incomplete). Open Draw Results > 'Get results from "
                 "the web...' to look at them.")

    def failed(text: str) -> None:
        ctx.online_busy = False
        ctx.status.emit(f"Online check failed: {text}")

    run_in_background(lambda: fetch_auto(plan, fetcher), done, failed, threaded)
    return True
