"""Saving fetched draws in the data file, and the optional automatic check."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from ..processing.numbers import normalize_number
from .fetcher import ResultFetcher
from .http import FetchError
from .model import Listed, OnlineDraw, Trace

SETTING_AUTO = "online_auto"            # '1': look for new results when the app starts
SETTING_MODE = "online_mode"
SETTING_LAST = "online_last_check"
SETTING_VERIFY = "online_verify"
LOOK_BACK_DAYS = 400                    # how far back an automatic check looks for new draws
AUTO_MAX_DRAWS = 6                      # most draws one automatic check will save


@dataclass
class SaveOutcome:
    draw_id: int
    created: bool                       # False: the draw was already recorded; numbers were added
    added: int
    skipped: int                        # numbers that were already in the draw


def save_draw(db, draw: OnlineDraw) -> SaveOutcome:
    """Record a fetched draw and its winning numbers (an already-recorded draw is topped up).

    Marks the draw's ``source`` with the site it came from, so the Draw Results list shows
    which draws were typed in and which were fetched.
    """
    if not draw.draw_date:
        raise ValueError("The draw date is missing.")
    items = [(*normalize_number(number), prize.label, prize.amount)
             for prize in draw.prizes for number in prize.numbers]
    with db.tx():
        existing = db.find_draw(draw.draw_date, draw.denomination)
        if existing:
            draw_id, created = existing["id"], False
        else:
            draw_id, created = db.add_draw(
                draw.draw_date, draw.denomination, draw.label, draw.location,
                source=draw.source, source_url=draw.url, draw_no=draw.draw_no), True
        added, skipped = db.add_winning_numbers(draw_id, items)
    return SaveOutcome(draw_id, created, added, skipped)


# ---------------------------------------------------------------- automatic check
@dataclass
class AutoResult:
    saved: list[tuple[Listed, OnlineDraw, SaveOutcome]] = field(default_factory=list)
    needs_review: list[tuple[Listed, str]] = field(default_factory=list)
    older_available: int = 0
    trace: Trace = field(default_factory=Trace)
    error: str = ""

    @property
    def draw_ids(self) -> list[int]:
        return [outcome.draw_id for _, _, outcome in self.saved]

    def summary(self) -> str:
        if self.error:
            return self.error
        parts = []
        if self.saved:
            parts.append(f"{len(self.saved)} new draw(s) fetched")
        if self.needs_review:
            parts.append(f"{len(self.needs_review)} need your review (Draw Results > Get from "
                         "the web)")
        if self.older_available:
            parts.append(f"{self.older_available} older draw(s) are also available")
        return ", ".join(parts) or "No new draws online."


def _earliest_purchase(db) -> str | None:
    row = db.conn.execute(
        "SELECT MIN(purchase_date) AS d FROM bonds WHERE sale_id IS NULL "
        "AND purchase_date IS NOT NULL AND purchase_date <> ''").fetchone()
    missing = db.conn.execute(
        "SELECT COUNT(*) FROM bonds WHERE sale_id IS NULL AND "
        "(purchase_date IS NULL OR purchase_date = '')").fetchone()[0]
    return None if missing else row["d"]


# An automatic check is split in three so that the slow middle part (the network) can run in a
# background thread while the data file is only ever touched by the thread that owns it:
#     plan = plan_auto(db)            # reads the data file
#     fetched = fetch_auto(plan, f)   # network only - safe in a worker thread
#     result = apply_auto(db, fetched)  # writes the data file
@dataclass
class AutoPlan:
    prices: list[int]
    since: str
    today: str
    known: set[tuple[str, int | None]]          # (draw date, price) already recorded
    max_draws: int = AUTO_MAX_DRAWS
    error: str = ""


@dataclass
class AutoFetched:
    """What the network part found: new draws that were read, and draws that could not be."""

    plan: AutoPlan
    # newest first: (the listing, the draw read or None, why it could not be read)
    results: list[tuple[Listed, OnlineDraw | None, str]] = field(default_factory=list)
    older_available: int = 0
    trace: Trace = field(default_factory=Trace)
    error: str = ""


def plan_auto(db, today: date | None = None, max_draws: int = AUTO_MAX_DRAWS) -> AutoPlan:
    today = today or date.today()
    prices = [r["denomination"] for r in db.conn.execute(
        "SELECT DISTINCT denomination FROM bonds WHERE sale_id IS NULL ORDER BY denomination")]
    floor = (today - timedelta(days=LOOK_BACK_DAYS)).isoformat()
    bought = _earliest_purchase(db)
    known = {(r["draw_date"], r["denomination"]) for r in db.conn.execute(
        "SELECT draw_date, denomination FROM draws")}
    return AutoPlan(prices, max(floor, bought) if bought else floor, today.isoformat(), known,
                    max_draws, "" if prices else "No bonds yet, so there is nothing to check.")


def fetch_auto(plan: AutoPlan, fetcher: ResultFetcher) -> AutoFetched:
    """The network part of an automatic check (does not touch the data file)."""
    out = AutoFetched(plan, error=plan.error)
    if plan.error:
        return out
    try:
        listed = fetcher.list_draws(plan.prices, out.trace)
    except FetchError as exc:
        out.error = str(exc)
        return out
    if not listed:
        out.error = "The web sites could not be reached or gave no draws."
    fresh = [e for e in listed if e.draw_date and plan.since <= e.draw_date <= plan.today
             and (e.draw_date, e.denomination) not in plan.known]
    out.older_available = max(0, len(fresh) - plan.max_draws)
    for entry in fresh[:plan.max_draws]:
        try:
            out.results.append((entry, fetcher.fetch(entry, out.trace), ""))
        except FetchError as exc:
            out.results.append((entry, None, str(exc)))
    return out


def apply_auto(db, fetched: AutoFetched) -> AutoResult:
    """Save the draws that look complete; the rest is left for the person to review."""
    result = AutoResult(trace=fetched.trace, error=fetched.error,
                        older_available=fetched.older_available)
    for entry, draw, why in fetched.results:
        if draw is None:
            result.needs_review.append((entry, why))
        elif draw.looks_complete():
            result.saved.append((entry, draw, save_draw(db, draw)))
        else:
            result.needs_review.append((entry, "; ".join(draw.warnings) or "incomplete result"))
    return result


def auto_check(db, fetcher: ResultFetcher, today: date | None = None,
               max_draws: int = AUTO_MAX_DRAWS) -> AutoResult:
    """Fetch the newest draws you do not have yet for the prices you hold.

    Only results that look complete are saved on their own (a date, one first prize, no
    warnings); anything odd is left for you to review.  Draws from before you owned any bond are
    ignored.  Nothing is approved - the win-checking agent still only queues possible wins.
    """
    return apply_auto(db, fetch_auto(plan_auto(db, today, max_draws), fetcher))
