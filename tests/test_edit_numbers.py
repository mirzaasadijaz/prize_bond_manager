"""Editing the winning numbers of a draw: one at a time, or many at the same time."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from app.db import Database, WinningNumberError  # noqa: E402
from app.db.core import KEEP  # noqa: E402
from app.processing.numbers import parse_pattern  # noqa: E402


def nums(pattern):
    return parse_pattern(pattern).numbers


@pytest.fixture
def db():
    d = Database(":memory:")
    d.add_copy("A", nums("100001-100010"), 750, "2025-01-01")
    draw = d.add_draw("2026-10-01", 750, "Draw #98")
    d.add_winning_numbers(draw, [(*n, "3rd Prize", 1250) for n in nums("100003, 100004, 555555")])
    d.draw = draw
    yield d
    d.close()


def rows(db):
    return {r["number"]: r for r in db.draw_numbers(db.draw)}


def test_edit_one_number_prize_and_amount(db):
    row = rows(db)["555555"]
    moved = db.update_winning_number(row["id"], "100005", "2nd Prize", 500000)
    assert moved is True
    changed = rows(db)["100005"]
    assert (changed["prize_label"], changed["prize_amount"], changed["num"]) == ("2nd Prize", 500000, 100005)
    assert "555555" not in rows(db)
    assert db.update_winning_number(changed["id"], "100005", prize_amount=None) is False
    assert rows(db)["100005"]["prize_amount"] is None and rows(db)["100005"]["prize_label"] == "2nd Prize"


def test_a_number_the_draw_already_has_is_refused(db):
    row = rows(db)["555555"]
    with pytest.raises(WinningNumberError):
        db.update_winning_number(row["id"], "100003")
    with pytest.raises(WinningNumberError):
        db.update_winning_number(row["id"], "abc")
    assert "555555" in rows(db)


def test_edit_many_at_the_same_time(db):
    ids = [r["id"] for r in db.draw_numbers(db.draw)]
    assert db.update_prizes(ids, prize_label="1st Prize") == 3
    assert {r["prize_label"] for r in db.draw_numbers(db.draw)} == {"1st Prize"}
    assert {r["prize_amount"] for r in db.draw_numbers(db.draw)} == {1250}         # untouched
    db.update_prizes(ids[:2], prize_amount=900)
    db.update_prizes(ids[2:], prize_amount=None)
    assert sorted(r["prize_amount"] or 0 for r in db.draw_numbers(db.draw)) == [0, 900, 900]
    assert db.update_prizes(ids) == 0                                                # KEEP / KEEP


def test_changing_a_number_moves_the_waiting_match(db):
    assert db.scan_for_matches(db.draw).new_pending == 2          # 100003 and 100004 are held
    target = rows(db)["100003"]
    db.update_winning_number(target["id"], "100009")
    assert [p["bond_number"] for p in db.list_pending()] == ["100004"]
    assert db.scan_for_matches(db.draw).new_pending == 1
    assert sorted(p["bond_number"] for p in db.list_pending()) == ["100004", "100009"]


def test_an_approved_win_keeps_its_own_copy_of_the_prize(db):
    db.scan_for_matches(db.draw)
    db.approve_pending([p["pending_id"] for p in db.list_pending()])
    target = rows(db)["100003"]
    db.update_winning_number(target["id"], "100003", "1st Prize", 77)
    assert {w["prize_label"] for w in db.list_wins()} == {"3rd Prize"}


# ------------------------------------------------------------------------------- the screens
pytest.importorskip("PyQt6")
from tests.test_gui_smoke import box, ctx, qapp  # noqa: E402,F401
from app.ui.dialogs.edit_numbers import EditNumbersDialog  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402


def test_dialog_for_one_number_applies_everything(qapp):
    row = {"number": "100003", "prize_label": "3rd Prize", "prize_amount": 1250}
    dlg = EditNumbersDialog([row], ("number", "prize_label", "prize_amount"))
    dlg.number_edit.setText("100005")
    dlg.prize_box.setCurrentText("2nd Prize")
    dlg.amount_edit.setText("Rs 1,000,000")
    dlg._save()
    assert (dlg.number, dlg.prize, dlg.amount) == ("100005", "2nd Prize", 1_000_000)


def test_dialog_for_many_changes_only_what_is_ticked(qapp):
    rows = [{"number": "100003", "prize_label": "x", "prize_amount": 1},
            {"number": "100004", "prize_label": "x", "prize_amount": 1}]
    dlg = EditNumbersDialog(rows, ("number", "prize_label", "prize_amount"))
    dlg.change_prize.setChecked(True)
    dlg.prize_box.setCurrentText("Winner")
    dlg._save()
    assert (dlg.number, dlg.prize, dlg.amount) == (None, "Winner", KEEP)
    dlg = EditNumbersDialog(rows, ("number", "prize_label", "prize_amount"))
    dlg._save()                                           # nothing ticked: refused
    assert dlg.result() == 0
    dlg.change_amount.setChecked(True)
    dlg._save()
    assert (dlg.prize, dlg.amount) == (KEEP, None)       # empty amount clears it


def _answer(monkeypatch, **fields):
    """Make the edit dialog 'click Save' with these field values."""
    def fake_exec(self):
        if "number" in fields:
            self.number_edit.setText(fields["number"])
        if "prize" in fields:
            self.change_prize.setChecked(True)
            self.prize_box.setCurrentText(fields["prize"])
            self.prize_box.setEditText(fields["prize"])
        if "amount" in fields:
            self.change_amount.setChecked(True)
            self.amount_edit.setText(fields["amount"])
        self._save()
        return self.result()
    monkeypatch.setattr(EditNumbersDialog, "exec", fake_exec)


def _open_draw(ctx, window):
    page = window.pages["draws"]
    window.show_page("draws")
    draw_id = ctx.db.find_draw("2026-12-01", 750)["id"]
    row = next(r for r in page.draws.all_rows() if r["id"] == draw_id)
    page.draws.view.selectRow(page.draws.proxy.mapFromSource(
        page.draws.model.index(page.draws.all_rows().index(row), 0)).row())
    return page, draw_id


def test_page_edits_selected_and_all_recorded_numbers(ctx, qapp, monkeypatch, box):
    db = ctx.db
    draw = db.add_draw("2026-12-01", 750, "Draw #98")      # the demo already has an October draw
    db.add_winning_numbers(draw, [(*n, "3rd Prize", 1250) for n in nums("100003, 100004, 555555")])
    window = MainWindow(ctx)
    page, draw_id = _open_draw(ctx, window)
    assert len(page.numbers.all_rows()) == 3
    assert not page.edit_numbers_button.isEnabled() and page.edit_all_button.isEnabled()

    page.numbers.view.selectRow(0)                              # one: change its number
    first = page.numbers.selected_rows()[0]
    assert page.edit_numbers_button.isEnabled()
    _answer(monkeypatch, number="100008", prize="2nd Prize", amount="500000")
    page._edit_numbers(False)
    changed = {r["number"]: r for r in db.draw_numbers(draw_id)}
    assert changed["100008"]["prize_label"] == "2nd Prize" and first["number"] not in changed

    _answer(monkeypatch, prize="Winner")                        # all of them together
    page._edit_numbers(True)
    assert {r["prize_label"] for r in db.draw_numbers(draw_id)} == {"Winner"}
    assert {r["prize_amount"] for r in db.draw_numbers(draw_id)} == {500000, 1250}

    page.numbers.search.setText("100003")                      # "all" means all that are shown
    assert [r["number"] for r in page.numbers.visible_rows()] == ["100003"]
    _answer(monkeypatch, prize="3rd Prize")
    page._edit_numbers(True)
    labels = {r["number"]: r["prize_label"] for r in db.draw_numbers(draw_id)}
    assert labels["100003"] == "3rd Prize" and labels["100004"] == "Winner" and labels["100008"] == "Winner"


def test_page_edits_the_list_before_it_is_saved(ctx, qapp, monkeypatch, box):
    window = MainWindow(ctx)
    page = window.pages["draws"]
    page._stage(nums("200001-200003"), "3rd Prize", 1250)
    page.staged_panel.view.selectRow(0)
    old = page.staged_panel.selected_rows()[0]["number"]
    _answer(monkeypatch, number="200009", prize="1st Prize", amount="1500000")
    page._edit_staged(False)
    got = {r["number"]: (r["tier"], r["amount"]) for r in page.staged}
    assert got["200009"] == ("1st Prize", 1_500_000) and old not in got and len(got) == 3
    _answer(monkeypatch, prize="2nd Prize")
    page._edit_staged(True)
    assert {r["tier"] for r in page.staged} == {"2nd Prize"}
    assert {r["amount"] for r in page.staged} == {1_500_000, 1250}
    others = [r for r in page.staged if r["number"] != "200009"]
    page.staged_panel.view.clearSelection()
    for i, shown in enumerate(page.staged_panel.all_rows()):
        if shown is others[0]:
            page.staged_panel.view.selectRow(page.staged_panel.proxy.mapFromSource(
                page.staged_panel.model.index(i, 0)).row())
    _answer(monkeypatch, number="200009")                       # a number already in the list
    page._edit_staged(False)
    assert len({r["number"] for r in page.staged}) == 3 and others[0]["number"] != "200009"
    assert any("already has" in m[2] for m in __import__("PyQt6.QtWidgets", fromlist=["x"]).QMessageBox.shown)


# ------------------------------------------------------------------- prizes by tier
def test_set_prizes_by_tier(db):
    ids = {r["number"]: r["id"] for r in db.draw_numbers(db.draw)}
    first = [("100003", 100003)]
    second = [("100004", 100004), ("100010", 100010)]            # 100010 is not in the draw yet
    changed, added = db.set_prize_tiers(
        db.draw, [("1st Prize", 1500000, first), ("2nd Prize", 500000, second)],
        rest=("3rd Prize", 1250))
    assert (changed, added) == (3, 1)
    now = rows(db)
    assert (now["100003"]["prize_label"], now["100003"]["prize_amount"]) == ("1st Prize", 1500000)
    assert {n: now[n]["prize_label"] for n in ("100004", "100010")} == {"100004": "2nd Prize",
                                                                       "100010": "2nd Prize"}
    assert (now["555555"]["prize_label"], now["555555"]["prize_amount"]) == ("3rd Prize", 1250)
    assert now["100003"]["id"] == ids["100003"]                    # edited in place, not re-created


def test_tiers_without_a_rest_leave_the_other_numbers_alone(db):
    db.set_prize_tiers(db.draw, [("1st Prize", None, [("555555", 555555)])])
    now = rows(db)
    assert now["555555"]["prize_label"] == "1st Prize" and now["555555"]["prize_amount"] is None
    assert now["100003"]["prize_label"] == "3rd Prize" and now["100003"]["prize_amount"] == 1250


def test_tier_dialog_reads_what_was_typed(qapp):
    from app.ui.dialogs.tier_dialog import PrizeTiersDialog

    dlg = PrizeTiersDialog()
    dlg.boxes[0].numbers.setPlainText("123456")
    dlg.boxes[0].amount.setText("1,500,000")
    dlg.boxes[1].numbers.setPlainText("111111 222222, 333333-333335")
    dlg.boxes[1].amount.setText("500000")
    dlg.rest_amount.setText("1250")
    dlg._apply()
    assert dlg.result() == 1
    assert [(n, a, len(nums)) for n, a, nums in dlg.tiers] == [("1st Prize", 1500000, 1),
                                                               ("2nd Prize", 500000, 5)]
    assert dlg.rest == ("3rd Prize", 1250)
    dlg.more = dlg._more()                                         # a 3rd box keeps its order
    assert len(dlg.boxes) == 3 and dlg.boxes[2].title() == "Prize 3"
    assert dlg.inner.indexOf(dlg.boxes[2]) == 2


def test_tier_dialog_refuses_a_number_in_two_prizes(qapp):
    from PyQt6.QtWidgets import QMessageBox
    from app.ui.dialogs.tier_dialog import PrizeTiersDialog

    dlg = PrizeTiersDialog()
    dlg.boxes[0].numbers.setPlainText("123456")
    dlg.boxes[1].numbers.setPlainText("999999 123456")
    dlg._apply()
    assert dlg.result() == 0
    assert any("only win one prize" in m[2] for m in QMessageBox.shown)


def _tiers_dialog(monkeypatch, first, second, rest_amount="1250"):
    from app.ui.dialogs.tier_dialog import PrizeTiersDialog

    def fake_exec(self):
        self.boxes[0].numbers.setPlainText(first)
        self.boxes[0].amount.setText("1500000")
        self.boxes[1].numbers.setPlainText(second)
        self.boxes[1].amount.setText("500000")
        self.rest_amount.setText(rest_amount)
        self._apply()
        return self.result()
    monkeypatch.setattr(PrizeTiersDialog, "exec", fake_exec)


def test_page_sets_the_prizes_of_a_saved_draw_by_tier(ctx, qapp, monkeypatch, box):
    db = ctx.db
    draw = db.add_draw("2026-12-01", 750, "Draw #98")
    db.add_winning_numbers(draw, [(*n, "Winner", None) for n in nums("100003, 100004, 100005, 555555")])
    window = MainWindow(ctx)
    page, draw_id = _open_draw(ctx, window)
    assert page.tiers_button.isEnabled()
    _tiers_dialog(monkeypatch, "100003", "100004 100005")
    page._tiers_numbers()
    now = {r["number"]: (r["prize_label"], r["prize_amount"]) for r in db.draw_numbers(draw_id)}
    assert now == {"100003": ("1st Prize", 1500000), "100004": ("2nd Prize", 500000),
                   "100005": ("2nd Prize", 500000), "555555": ("3rd Prize", 1250)}


def test_page_sets_the_prizes_of_the_unsaved_list_by_tier(ctx, qapp, monkeypatch, box):
    window = MainWindow(ctx)
    page = window.pages["draws"]
    page._stage(nums("300001-300004"), "Winner", None)
    _tiers_dialog(monkeypatch, "300002", "300003 300009")
    page._tiers_staged()
    now = {r["number"]: (r["tier"], r["amount"]) for r in page.staged}
    assert now == {"300001": ("3rd Prize", 1250), "300002": ("1st Prize", 1500000),
                   "300003": ("2nd Prize", 500000), "300004": ("3rd Prize", 1250),
                   "300009": ("2nd Prize", 500000)}
