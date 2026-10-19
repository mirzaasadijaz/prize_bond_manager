"""Headless tests for the 'Get results from the web' screens (a fake connection serves saved
copies of the real pages; nothing touches the network)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PyQt6")

from datetime import date  # noqa: E402

from app.online.fetcher import ResultFetcher  # noqa: E402
from app.online.store import SETTING_AUTO, SETTING_LAST  # noqa: E402
from app.ui.dialogs.check_numbers import CheckNumbersDialog  # noqa: E402
from app.ui.dialogs.online_dialog import OnlineDrawsDialog  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.online_auto import check_online  # noqa: E402
from tests.conftest import numbers  # noqa: E402
from tests.test_gui_smoke import box, ctx, qapp  # noqa: E402,F401  (fixtures)
from tests.test_online import (FakeWeb, OFFICIAL_LIST, TXT_0515, read,  # noqa: E402
                               web)


def factory(**extra):
    fake = web(**extra)
    return fake, (lambda mode: ResultFetcher(fake.client(), mode))


def dialog(ctx, fake_factory, **kwargs):
    return OnlineDrawsDialog(ctx, None, fetcher_factory=fake_factory, threaded=False, **kwargs)


def tick_only(dlg, price):
    for p, box_ in dlg.price_boxes.items():
        box_.setChecked(p == price)


def select(dlg, rows):
    dlg._select(rows)
    dlg._selection_changed()


# ------------------------------------------------------------------ the dialog
def test_look_read_and_save_a_draw_then_the_agent_queues_the_winner(ctx, qapp, box):
    db = ctx.db
    db.add_copy("Fresh", numbers("024130-024135"), 1500, "2026-01-01")     # holds the 1st prize 024132
    fake, make = factory()
    dlg = dialog(ctx, make)
    tick_only(dlg, 1500)
    dlg.mode.setCurrentIndex(dlg.mode.findData("official"))
    dlg._look()
    dates = sorted(r["draw_date"] for r in dlg.rows)
    assert dates == ["2025-08-15", "2025-11-17", "2026-02-16", "2026-05-15", "2026-08-17"]
    assert all(r["state"] == "New" for r in dlg.rows)
    assert "Official" in dlg.log.toPlainText() or "savings.gov.pk" in dlg.log.toPlainText()
    may = next(r for r in dlg.rows if r["draw_date"] == "2026-05-15")
    select(dlg, [may])
    assert dlg.read_button.isEnabled() and not dlg.save_button.isEnabled()
    dlg._read()
    assert may["draw"].number_count == 50 and "Read: 50 numbers" in may["state"]
    assert "1st Prize" in dlg.details.toPlainText()
    select(dlg, [may])
    assert dlg.save_button.isEnabled()
    dlg._save()
    assert [d["source"] for d in db.list_draws() if d["denomination"] == 1500] == ["savings.gov.pk"]
    (pending,) = [p for p in db.list_pending() if p["denomination"] == 1500]
    assert pending["bond_number"] == "024132" and pending["prize_amount"] == 3_000_000
    assert dlg.saved and ("Review now" in box.asked[-1][1])                 # the review offer


def test_a_second_look_marks_recorded_draws_and_does_not_preselect_them(ctx, qapp, box):
    db = ctx.db
    db.add_copy("Fresh", numbers("024130-024135"), 1500, "2026-01-01")
    fake, make = factory()
    dlg = dialog(ctx, make)
    tick_only(dlg, 1500)
    dlg.mode.setCurrentIndex(dlg.mode.findData("official"))
    dlg._look()
    first = next(r for r in dlg.rows if r["draw_date"] == "2026-05-15")
    select(dlg, [first])
    dlg._read()
    select(dlg, [first])
    dlg._save()
    dlg2 = dialog(ctx, make)
    tick_only(dlg2, 1500)
    dlg2.mode.setCurrentIndex(dlg2.mode.findData("official"))
    dlg2._look()
    recorded = [r for r in dlg2.rows if r["recorded"]]
    assert [r["draw_date"] for r in recorded] == ["2026-05-15"]
    assert "Already recorded (50 numbers)" in recorded[0]["state"]
    chosen = {r["draw_date"] for r in dlg2.listing.selected_rows()}
    assert "2026-05-15" not in chosen
    assert chosen == {"2025-08-15", "2025-11-17", "2026-02-16", "2026-08-17"}


def test_a_draw_that_cannot_be_read_is_reported_and_not_saved(ctx, qapp):
    ctx.db.add_copy("Fresh", numbers("024130-024135"), 1500, "2026-01-01")
    fake, make = factory()
    dlg = dialog(ctx, make)
    tick_only(dlg, 1500)
    dlg.mode.setCurrentIndex(dlg.mode.findData("official"))
    dlg._look()
    august = next(r for r in dlg.rows if r["draw_date"] == "2026-08-17")     # a PDF that is not served
    select(dlg, [august])
    dlg._read()
    assert august["draw"] is None and august["state"].startswith("Could not be read")
    select(dlg, [august])
    assert not dlg.save_button.isEnabled()
    assert [d for d in ctx.db.list_draws() if d["denomination"] == 1500] == []


def test_nothing_found_points_to_the_log_the_link_and_hand_entry(ctx, qapp):
    ctx.db.add_loose_bonds(numbers("100001"), 1500)
    dlg = OnlineDrawsDialog(ctx, None, fetcher_factory=lambda mode: ResultFetcher(
        FakeWeb({}).client(), mode), threaded=False)
    tick_only(dlg, 1500)
    dlg._look()
    assert dlg.rows == [] and "No draws were found" in dlg.progress.text()
    assert dlg.tabs.currentWidget() is dlg.log and "FAIL" in dlg.log.toPlainText()


def test_a_pasted_link_is_read_and_the_missing_date_comes_from_the_box(ctx, qapp, box):
    ctx.db.add_copy("Fresh", numbers("024130-024135"), 1500, "2026-01-01")
    fake, make = factory()
    dlg = dialog(ctx, make)
    dlg.link_date.set_value("2026-05-15")
    dlg.link_edit.setText(TXT_0515)
    dlg._read_link()
    (row,) = dlg.rows
    assert row["draw"].draw_date == "2026-05-15" and row["denomination"] == 1500
    assert any("gives no date" in w for w in row["draw"].warnings)
    select(dlg, [row])
    box.choice = "Save anyway"                       # the date warning asks first
    dlg._save()
    assert [d["draw_date"] for d in ctx.db.list_draws() if d["denomination"] == 1500] == [
        "2026-05-15"]
    assert len([p for p in ctx.db.list_pending() if p["denomination"] == 1500]) == 1


def test_a_bad_link_is_explained(ctx, qapp):
    fake, make = factory()
    dlg = dialog(ctx, make)
    dlg.link_edit.setText("not a link")
    dlg._read_link()
    assert dlg.rows == [] and "https://" in dlg.progress.text()


def test_settings_are_remembered(ctx, qapp):
    fake, make = factory()
    dlg = dialog(ctx, make)
    dlg.auto.setChecked(True)
    dlg.verify.setChecked(True)
    dlg.mode.setCurrentIndex(dlg.mode.findData("prizebond.net"))
    again = dialog(ctx, make)
    assert again.auto.isChecked() and again.verify.isChecked()
    assert again.mode.currentData() == "prizebond.net"


# ----------------------------------------------------------------- the start-up check
def test_startup_check_only_runs_when_switched_on_and_once_a_day(ctx, qapp):
    db = ctx.db
    fake, make = factory()
    assert not check_online(ctx, None, fetcher_factory=make, threaded=False)    # off by default
    db.set_setting(SETTING_AUTO, "1")
    db.add_copy("Fresh", numbers("024130-024135"), 1500, "2026-01-01")
    db.set_setting(SETTING_LAST, date.today().isoformat())
    assert not check_online(ctx, None, fetcher_factory=make, threaded=False)    # already today
    assert fake.asked == []


def test_startup_check_saves_new_complete_draws_and_leaves_a_review_note(ctx, qapp, box):
    db = ctx.db
    fake, make = factory()
    db.set_setting(SETTING_AUTO, "1")
    db.add_copy("Fresh", numbers("024130-024135"), 1500, "2026-01-01")
    messages = []
    ctx.status.connect(messages.append)
    before = db.pending_count()                         # the demo already has some
    assert check_online(ctx, None, fetcher_factory=make, threaded=False)
    assert sorted(d["draw_date"] for d in db.list_draws() if d["denomination"] == 1500) == [
        "2026-02-16", "2026-05-15"]
    assert db.get_setting(SETTING_LAST) == date.today().isoformat()
    assert any("2 new draw(s) fetched" in m and "need your review" in m for m in messages)
    assert ctx.online_busy is False
    assert db.pending_count() == before + 2             # the 1st prize 024132 of both draws
    assert box.asked and "Review now" in box.asked[0][1]


def test_the_menu_check_runs_even_when_not_switched_on(ctx, qapp, box):
    db = ctx.db
    fake, make = factory()
    db.add_copy("Fresh", numbers("999990-999995"), 1500, "2026-01-01")      # nothing of it wins
    messages = []
    ctx.status.connect(messages.append)
    before = db.pending_count()
    assert check_online(ctx, None, forced=True, fetcher_factory=make, threaded=False)
    assert len([d for d in db.list_draws() if d["denomination"] == 1500]) == 2
    assert db.pending_count() == before                  # nothing of the new draws wins
    assert any("2 new draw(s) fetched" in m for m in messages)


def test_startup_check_without_internet_is_quiet(ctx, qapp, box):
    db = ctx.db
    db.set_setting(SETTING_AUTO, "1")
    db.add_loose_bonds(numbers("100001"), 1500)
    messages = []
    ctx.status.connect(messages.append)
    off = lambda mode: ResultFetcher(FakeWeb({}).client(), mode)  # noqa: E731
    assert check_online(ctx, None, fetcher_factory=off, threaded=False)
    assert any("could not be reached" in m for m in messages)
    assert db.get_setting(SETTING_LAST) is None          # tries again next time
    assert not box.asked and len(db.list_draws()) == 1       # only the demo draw


# --------------------------------------------------------------- the draws page and menus
def test_draws_page_shows_the_source_and_reads_an_official_file(ctx, qapp, tmp_path, monkeypatch):
    from app.ui.pages import draws_page

    path = tmp_path / "result.txt"
    path.write_text(read("official_rs1500_106.txt"), encoding="utf-8")
    monkeypatch.setattr(draws_page, "pick_open_file", lambda *a, **k: str(path))
    monkeypatch.setattr(draws_page, "info", lambda *a, **k: None)
    window = MainWindow(ctx)
    page = window.pages["draws"]
    page._import_numbers()
    tiers = {}
    for row in page.staged:
        tiers.setdefault(row["tier"], []).append(row)
    assert {t: len(rows) for t, rows in tiers.items()} == {"1st Prize": 1, "2nd Prize": 3,
                                                           "3rd Prize": 46}
    assert tiers["2nd Prize"][0]["amount"] == 1_000_000
    assert page.price.value() == 1500
    page.date.set_value("2026-05-15")
    page._save()
    saved = ctx.db.find_draw("2026-05-15", 1500)
    assert saved and ctx.db.get_draw(saved["id"])["source"] == "Manual"      # typed in / from a file
    window.show_page("draws")
    sources = {r["draw_date"]: r["source_text"] for r in page.draws.all_rows()}
    assert sources["2026-05-15"] == "Typed in"


def test_menu_has_the_new_actions(ctx, qapp):
    window = MainWindow(ctx)
    texts = [a.text() for m in window.menuBar().actions() for a in m.menu().actions()]
    for wanted in ("Get draw results from the web...", "Look for new draws online now",
                   "Check a list of numbers..."):
        assert wanted in texts


# --------------------------------------------------------------- check a list of numbers
def test_check_a_pasted_list_and_all_my_bonds(ctx, qapp):
    dlg = CheckNumbersDialog(ctx)               # the demo: 100056, 777777 (750), 900007 (750)
    dlg.numbers.setPlainText("100056, 777777\n123456 abc 500000-500009")
    dlg.price.set_value(750)
    dlg.check_text()
    assert dlg.summary.checked == 13 and dlg.summary.winners == 2      # 'abc' is skipped
    assert {r["number"] for r in dlg.table.all_rows()} == {"100056", "777777"}
    assert "2 won" in dlg.message.text()
    dlg.price.set_value(1500)
    dlg.check_text()
    assert dlg.summary.winners == 0 and "none of them won" in dlg.message.text()
    dlg.check_mine()
    assert dlg.summary.winners >= 3                         # 100056 twice (two copies) and the others
    refs = {r["ref"] for r in dlg.table.all_rows()}
    assert "Copy 1 #56" in refs and "Copy 5 #7" in refs


def test_check_dialog_says_when_no_draws_are_recorded(qapp):
    from app.db import Database
    from app.ui.context import AppContext
    empty = AppContext(Database(":memory:"))
    dlg = CheckNumbersDialog(empty)
    dlg.numbers.setPlainText("100001")
    dlg.check_text()
    assert "No draws are recorded" in dlg.message.text()
    dlg.numbers.setPlainText("")
    dlg.check_text()
    assert "at least one" in dlg.message.text()


def test_check_dialog_handles_ten_thousand_numbers_instantly(ctx, qapp):
    dlg = CheckNumbersDialog(ctx)
    dlg.numbers.setPlainText("200000-209999")
    dlg.check_text()
    assert dlg.summary.checked == 10_000 and dlg.summary.elapsed_ms < 500


# ------------------------------------------------------------------ the real worker thread
def _wait_for(qapp, condition, seconds=5.0):
    from PyQt6.QtTest import QTest
    waited = 0
    while not condition() and waited < seconds * 1000:
        QTest.qWait(20)
        waited += 20
    assert condition(), "the background job did not finish"


def test_a_job_runs_off_the_window_thread_and_the_answer_comes_back_on_it(qapp):
    import threading

    from app.ui.background import run_in_background
    seen = {}
    answers, errors = [], []

    def job():
        seen["job"] = threading.get_ident()
        return 42

    def answer(value):
        seen["answer"] = threading.get_ident()
        answers.append(value)

    run_in_background(job, answer, errors.append)
    _wait_for(qapp, lambda: answers)
    assert answers == [42] and seen["job"] != threading.get_ident()
    assert seen["answer"] == threading.get_ident()          # back in the main thread
    run_in_background(lambda: 1 / 0, answers.append, errors.append)
    _wait_for(qapp, lambda: errors)
    assert "division by zero" in errors[0]


def test_the_dialog_looks_things_up_in_a_thread_and_stays_usable(ctx, qapp):
    import threading

    class SpyWeb(FakeWeb):
        threads: set = set()

        def __call__(self, url, timeout):
            self.threads.add(threading.get_ident())
            return super().__call__(url, timeout)

    fake = SpyWeb(web().pages)
    make = lambda mode: ResultFetcher(fake.client(), mode)  # noqa: E731
    ctx.db.add_copy("Fresh", numbers("024130-024135"), 1500, "2026-01-01")
    dlg = OnlineDrawsDialog(ctx, None, fetcher_factory=make, threaded=True)
    tick_only(dlg, 1500)
    dlg.mode.setCurrentIndex(dlg.mode.findData("official"))
    dlg._look()
    assert dlg._busy and not dlg.look_button.isEnabled()      # the window is told to wait ...
    _wait_for(qapp, lambda: not dlg._busy)                    # ... and the answer arrives later
    assert len(dlg.rows) == 5 and dlg.look_button.isEnabled()
    assert fake.threads and threading.get_ident() not in fake.threads
