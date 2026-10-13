"""Headless smoke tests for the PyQt6 interface (run with the offscreen platform).

They open every page and dialog, drive the main workflows and check the same-number-in-several-
copies behaviour on screen.  Skipped automatically when PyQt6 is not installed.
"""
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app import demo  # noqa: E402
from app.db import Database  # noqa: E402
from app.ui import actions  # noqa: E402
from app.ui.context import AppContext  # noqa: E402
from app.ui.dialogs.add_bonds import AddBondsDialog  # noqa: E402
from app.ui.dialogs.import_dialog import ImportDialog  # noqa: E402
from app.ui.dialogs.win_report import WinReportDialog  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.pages import draws_page, pending_page  # noqa: E402
from app.ui.theme import STYLESHEET  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    return app


@pytest.fixture
def ctx(qapp):
    db = Database(":memory:")
    demo.seed(db)                      # 100056 sits in Copy 1 and in Copy 5
    yield AppContext(db)
    db.close()


@pytest.fixture
def box(monkeypatch):
    """Answer every QMessageBox without blocking: click the button named in ``box.choice``."""
    class Answers:
        choice = None
        asked: list = []

    answers = Answers()
    answers.asked = []

    def fake_exec(self):
        answers.asked.append((self.text(), [b.text().replace("&", "") for b in self.buttons()]))
        for button in self.buttons():
            if button.text().replace("&", "") == answers.choice:
                button.click()
                return 0
        self.buttons()[-1].click()      # default: the last button (Cancel / Close)
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    return answers


@pytest.fixture
def reports_shown(monkeypatch):
    shown = []
    monkeypatch.setattr(actions, "show_win_report",
                        lambda parent, wins, title="", intro="": shown.append((title, wins, intro)))
    monkeypatch.setattr(pending_page, "confirm", lambda *a, **k: True)
    return shown


def test_every_page_opens_and_refreshes(ctx, qapp):
    window = MainWindow(ctx)
    window.show()
    for key in window.pages:
        window.show_page(key)
        qapp.processEvents()
        assert window.stack.currentWidget() is window.pages[key]
    assert "(4)" in window.nav["pending"].text()               # the badge counts pending matches


def test_pending_list_shows_both_bonds_holding_the_winning_number(ctx, qapp):
    window = MainWindow(ctx)
    window.show_page("pending")
    rows = window.pages["pending"].panel.all_rows()
    held = [r for r in rows if r["bond_number"] == "100056"]
    assert sorted((r["copy_name"], r["copy_first_number"], r["where"]) for r in held) == [
        ("Copy 1", "100001", "56 of 100"), ("Copy 5", "100050", "7 of 11")]
    assert {r["same_number_count"] for r in held} == {2}


def test_approving_one_row_approves_the_other_bond_with_the_same_number(ctx, qapp, reports_shown):
    window = MainWindow(ctx)
    window.show_page("pending")
    page = window.pages["pending"]
    page._approve([r for r in page.panel.all_rows() if r["copy_name"] == "Copy 5"])
    title, wins, intro = reports_shown[-1]
    assert title == "Approved wins" and len(wins) == 2 and "same number" in intro
    assert {w["copy_name"] for w in wins} == {"Copy 1", "Copy 5"}
    window.show_page("wins")
    win_rows = window.pages["wins"].panel.all_rows()
    assert [r["same_number_count"] for r in win_rows] == [2, 2]
    assert ctx.db.pending_count() == 2                          # the other two numbers wait


def test_wins_page_report_covers_every_bond_of_the_number(ctx, qapp, reports_shown):
    ctx.agent.approve_all()
    window = MainWindow(ctx)
    window.show_page("wins")
    page = window.pages["wins"]
    page.panel.view.selectRow(0)
    qapp.processEvents()
    chosen = page.panel.selected_rows()
    assert len(chosen) == 1
    targets = page._targets()
    same = [t for t in targets if t["bond_number"] == chosen[0]["bond_number"]]
    assert len(same) == chosen[0]["same_number_count"]


def test_add_dialog_asks_before_repeating_a_number_you_hold(ctx, qapp, box):
    def dialog(pattern, new_copy):
        dlg = AddBondsDialog(ctx, None, start_tab=1)
        dlg.price.set_value(750)
        dlg.quick.pattern.setPlainText(pattern)
        dlg.quick.new.setChecked(True)
        dlg.quick.new_name.setText(new_copy)
        return dlg

    box.choice = "Cancel"
    cancelled = dialog("100050-100052, 888801", "Copy 9")
    cancelled._add()
    assert cancelled.result is None and ctx.db.list_bonds(number_from=888801, number_to=888801) == []

    box.choice = "Skip numbers I already have"
    skipped = dialog("100050-100052, 888801", "Copy 9")
    skipped._add()
    assert skipped.result.added == 1 and len(skipped.result.skipped_duplicates) == 3

    box.choice = "Add all"
    everything = dialog("100050-100052, 888802", "Copy 10")
    everything._add()
    assert everything.result.added == 4 and everything.result.shared == 3
    assert "3 of these numbers are already in your list" in box.asked[-1][0]
    assert {b["same_count"] for b in ctx.db.list_bonds(number_from=100050, number_to=100052)} == {3}


def test_add_dialog_does_not_ask_when_nothing_is_held(ctx, qapp, box):
    dlg = AddBondsDialog(ctx, None, start_tab=1)
    dlg.price.set_value(750)
    dlg.quick.pattern.setPlainText("700001-700003")
    dlg.quick.loose.setChecked(True)
    dlg._add()
    assert not box.asked and dlg.result.added == 3


def test_copies_editor_accepts_numbers_shared_between_copies(ctx, qapp, box):
    dlg = AddBondsDialog(ctx, None, start_tab=0)
    editor = dlg.copies
    editor.table.item(0, 0).setText("Alpha")
    editor.editor.setPlainText("200001-200010")
    editor.add_row("Beta", "200006-200015")
    assert editor.is_valid()
    alpha, beta = editor.rows
    assert not alpha.problem and "5 number(s) also in 'Beta'" in alpha.note
    assert "5 number(s) also in 'Alpha'" in beta.note
    dlg.price.set_value(750)
    dlg._add()
    assert dlg.result.added == 20 and not box.asked
    assert {b["same_count"] for b in ctx.db.list_bonds(number_from=200006, number_to=200010)} == {2}


def test_copies_editor_still_rejects_a_number_twice_in_one_copy(ctx, qapp):
    dlg = AddBondsDialog(ctx, None, start_tab=0)
    dlg.copies.editor.setPlainText("200001-200003, 200002")
    assert not dlg.copies.is_valid()


def test_import_dialog_explains_numbers_you_already_hold_and_can_skip_them(ctx, qapp, tmp_path):
    path = tmp_path / "more.csv"
    path.write_text("Copy,Bond Number,Denomination\nCopy A,100056,750\nCopy A,100057,750\n"
                    "Copy B,100056,750\nCopy B,999001,750\nCopy B,999001,750\n", encoding="utf-8")
    dlg = ImportDialog(ctx, None, str(path))
    dlg.show()
    qapp.processEvents()
    assert not dlg.held_note.isHidden() and "2 number(s)" in dlg.held_note.text()
    assert "added again" in dlg.held_note.text()
    assert "999001" in dlg.problems.toPlainText()               # repeated inside one copy
    dlg.skip_existing.setChecked(True)
    assert "left out" in dlg.held_note.text()
    dlg.skip_existing.setChecked(False)
    dlg._import()
    assert dlg.result.added == 4 and dlg.result.shared == 3
    assert {b["same_count"] for b in ctx.db.list_bonds(number_from=100056, number_to=100056)} == {4}


def test_report_dialog_lists_each_bond_with_its_copy_first_number_and_position(ctx, qapp):
    ctx.agent.approve_all()
    dlg = WinReportDialog(ctx.db.list_wins(), "Approved wins")
    html = dlg.browser.toPlainText()
    assert "Winning number 100056" in html and "all 2 win" in html
    for fact in ("Copy 1", "Copy 5", "100001", "100050", "56 of 100", "7 of 11"):
        assert fact in html
    assert "Winning number 777777" in html and "Winning number 900007" in html


def test_dashboard_mentions_numbers_held_more_than_once(ctx, qapp):
    window = MainWindow(ctx)
    window.show_page("dashboard")
    assert "11 number(s) held more than once" in window.pages["dashboard"].card_active.sub.text()


SAMPLES = Path(__file__).resolve().parent.parent / "sample_data"


@pytest.mark.skipif(not SAMPLES.exists(), reason="sample_data/ not present")
def test_readme_walkthrough_with_the_sample_files(qapp, box, reports_shown, monkeypatch):
    """The quick start in the README: import three files, record a draw, approve one win."""
    db = Database(":memory:")
    ctx = AppContext(db)
    for name, price in (("bonds_with_copies.csv", None), ("copies_workbook.xlsx", None),
                        ("copies_list.docx", 100)):
        dialog = ImportDialog(ctx, None, str(SAMPLES / name))
        if price:
            dialog.price.set_value(price)
        dialog._import()
        assert dialog.result is not None and dialog.result.added > 0
    assert db.dashboard_stats()["shared_numbers"] == 20

    window = MainWindow(ctx)
    window.show_page("draws")
    page = window.pages["draws"]
    page.price.set_value(None)                                      # "Any denomination"
    assert page.price.is_any
    monkeypatch.setattr(draws_page, "pick_open_file",
                        lambda *a, **k: str(SAMPLES / "winning_numbers.csv"))
    monkeypatch.setattr(draws_page, "info", lambda *a, **k: None)
    page._import_numbers()
    assert len(page.staged) == 4
    page._save()

    window.show_page("pending")
    pending = window.pages["pending"].panel.all_rows()
    assert len(pending) == 7 and window.nav["pending"].text().endswith("(7)")
    one = next(r for r in pending if r["bond_number"] == "400008" and r["copy_name"] == "Copy 2")
    window.pages["pending"]._approve([one])
    title, wins, intro = reports_shown[-1]
    assert title == "Approved wins" and len(wins) == 2
    assert sorted((w["copy_name"], w["copy_first_number"], w["position"]) for w in wins) == [
        ("Copy 1", "400001", 8), ("Copy 2", "400006", 3)]
    assert db.pending_count() == 5
    db.close()
