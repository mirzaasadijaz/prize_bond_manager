"""Skipping draws before the purchase / last-prize date, row colours and the PIN."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from app.api.checker import WinningIndex, check_bonds, held_bonds, held_limits  # noqa: E402
from app.db import Database, PinError  # noqa: E402
from app.processing.numbers import parse_pattern  # noqa: E402


def nums(pattern):
    return parse_pattern(pattern).numbers


def add_draw(db, numbers, date, denomination=750):
    draw = db.add_draw(date, denomination, f"Draw {date}")
    db.add_winning_numbers(draw, [(*n, "1st Prize", None) for n in nums(numbers)])
    return draw


@pytest.fixture
def db():
    d = Database(":memory:")
    yield d
    d.close()


def bond(db, number):
    return next(b for b in db.list_bonds() if b["number"] == number)


# ---------------------------------------------------- 1. bought after the draw: skipped
def test_a_bond_bought_after_the_draw_is_not_checked_for_it(db):
    db.add_copy("A", nums("100001-100003"), 750, "2026-06-01")
    db.add_loose_bonds(nums("100009"), 750)                           # no purchase date at all
    early = add_draw(db, "100001, 100009", "2026-05-01")             # before the purchase
    same_day = add_draw(db, "100002", "2026-06-01")                   # on the day of purchase
    later = add_draw(db, "100003", "2026-07-01")
    scan = db.scan_for_matches()
    found = {(p["bond_number"], p["draw_id"]) for p in db.list_pending()}
    assert found == {("100009", early), ("100002", same_day), ("100003", later)}
    assert scan.new_pending == 3


# ------------------------------------------- 2. last prize taken: only newer draws count
def test_only_draws_after_the_last_prize_date_are_checked(db):
    db.add_copy("A", nums("100001-100003"), 750, "2025-01-01")
    for i, number in enumerate(("100001", "100002", "100003")):
        db.update_bond(bond(db, number)["id"], number, 750, "2025-01-01",
                       bond(db, number)["copy_id"], None,
                       last_prize_date=("2026-05-01" if i == 0 else "2026-04-30" if i == 1 else None))
    add_draw(db, "100001, 100002, 100003", "2026-05-01")
    db.scan_for_matches()
    # 100001: draw is on the last-prize day -> skipped.  100002: draw is newer -> checked.
    assert sorted(p["bond_number"] for p in db.list_pending()) == ["100002", "100003"]
    assert bond(db, "100001")["last_prize_date"] == "2026-05-01"


def test_editing_the_dates_drops_waiting_matches_that_no_longer_apply(db):
    db.add_copy("A", nums("100001-100002"), 750, "2025-01-01")
    add_draw(db, "100001", "2026-05-01")
    db.scan_for_matches()
    assert len(db.list_pending()) == 1
    b = bond(db, "100001")
    db.update_bond(b["id"], "100001", 750, "2026-06-01", b["copy_id"], b["position"])  # bought later
    assert db.list_pending() == []
    db.update_bond(b["id"], "100001", 750, "2025-01-01", b["copy_id"], b["position"])
    assert db.scan_for_matches().new_pending == 1
    db.update_bond(b["id"], "100001", 750, "2025-01-01", b["copy_id"], b["position"],
                   last_prize_date="2026-05-01")
    assert db.list_pending() == []
    db.update_bond(b["id"], "100001", 750, "2025-01-01", b["copy_id"], b["position"],
                   last_prize_date=None)                              # cleared again
    assert bond(db, "100001")["last_prize_date"] is None


def test_old_pending_rows_are_refused_when_approved(db):
    db.add_copy("A", nums("100001-100002"), 750, "2025-01-01")
    draw = add_draw(db, "100001", "2026-05-01")
    db.scan_for_matches()
    pid = db.list_pending()[0]["pending_id"]
    b = bond(db, "100001")
    db.conn.execute("UPDATE bonds SET purchase_date = '2027-01-01' WHERE id = ?", (b["id"],))
    result = db.approve_pending([pid])
    assert result.win_ids == [] and "bought after" in result.rejected[0][1]
    assert draw


def test_the_api_applies_the_same_two_rules(db):
    db.add_copy("A", nums("100001-100003"), 750, "2026-06-01")
    b = bond(db, "100002")
    db.update_bond(b["id"], "100002", 750, "2025-01-01", b["copy_id"], b["position"],
                   last_prize_date="2026-07-01")
    add_draw(db, "100001, 100002, 100003", "2026-07-01")
    add_draw(db, "100001", "2026-05-01")
    db.conn.commit() if db.conn.in_transaction else None
    index = WinningIndex.from_connection(db.conn)
    bonds = held_bonds(db.conn)
    summary = check_bonds(index, ((n, d, r) for n, d, r, _ in bonds),
                          limits=held_limits(db.conn))
    assert sorted((h.number, h.row.draw_date) for h in summary.hits) == [
        ("100001", "2026-07-01"), ("100003", "2026-07-01")]   # 100001's 2026-05 draw: bought later


# ------------------------------------------------------------------ 4. colours (database)
def test_highlight_bonds_and_copies(db):
    db.add_copy("A", nums("100001-100002"), 750)
    copy_id = db.list_copies()[0]["id"]
    ids = [b["id"] for b in db.list_bonds()]
    assert db.set_highlight("bonds", ids[:1], "#FDE68A") == 1
    assert db.set_highlight("copies", [copy_id], "#BFDBFE") == 1
    assert bond(db, "100001")["highlight"] == "#FDE68A"
    assert bond(db, "100002")["copy_highlight"] == "#BFDBFE"
    assert db.list_copies()[0]["highlight"] == "#BFDBFE"
    db.set_highlight("bonds", ids, None)
    assert bond(db, "100001")["highlight"] is None
    with pytest.raises(ValueError):
        db.set_highlight("bonds", ids, "red")


def test_row_styles_have_the_right_priority():
    from app.ui import theme
    from app.ui.highlight import bond_row_style, copy_row_style

    base = {"sale_id": None, "pending_count": 0, "times_won": 0, "highlight": None,
            "copy_highlight": None}
    assert bond_row_style(base) is None
    assert bond_row_style({**base, "times_won": 2})[1] == theme.WON_ROW_BG
    assert bond_row_style({**base, "times_won": 2, "pending_count": 1})[1] == theme.WARNING_BG
    assert bond_row_style({**base, "times_won": 2, "highlight": "#FDE68A"})[1] == "#FDE68A"
    assert bond_row_style({**base, "copy_highlight": "#BFDBFE"})[1] == "#BFDBFE"
    assert bond_row_style({**base, "highlight": "#FDE68A", "sale_id": 3})[1] is None   # sold: grey
    assert copy_row_style({"won": 0, "highlight": None}) is None
    assert copy_row_style({"won": 3, "highlight": None})[1] == theme.WON_ROW_BG
    assert copy_row_style({"won": 3, "highlight": "#DDD6FE"})[1] == "#DDD6FE"
    assert theme.readable_on("#FDE68A") == "#0F172A" and theme.readable_on("#1E3A8A") == "#FFFFFF"


# ------------------------------------------------------------------------- 5. the PIN
def test_pin_is_stored_hashed_and_checked(db):
    assert not db.pin_is_set() and db.check_pin("anything")           # nothing set: always fine
    db.set_pin("1234")
    assert db.pin_is_set() and db.check_pin("1234") and not db.check_pin("12345")
    assert "1234" not in str(db.query("SELECT * FROM settings"))
    with pytest.raises(PinError):
        db.set_pin("5678", current_pin="nope")
    with pytest.raises(PinError):
        db.set_pin("12")                                              # asks for the old one first
    db.set_pin("abcd9", current_pin="1234")
    assert db.check_pin("abcd9") and not db.check_pin("1234")
    with pytest.raises(PinError):
        db.remove_pin("wrong")
    db.remove_pin("abcd9")
    assert not db.pin_is_set()
    db.set_pin("1111")
    db.clear_pin()                                                    # forgotten PIN
    assert not db.pin_is_set()


pytest.importorskip("PyQt6")
from tests.test_gui_smoke import box, ctx, qapp  # noqa: E402,F401
from app.ui import security  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402


def _type_pin(monkeypatch, *answers):
    """Make the PIN prompt 'type' these answers one after the other (None = Cancel)."""
    queue = list(answers)
    asked = []

    def fake(parent, title, text, mode=None, *a, **k):
        asked.append(text)
        value = queue.pop(0)
        return ("", False) if value is None else (value, True)
    monkeypatch.setattr(security.QInputDialog, "getText", staticmethod(fake))
    return asked


def test_no_pin_means_no_question(ctx, qapp, monkeypatch):
    asked = _type_pin(monkeypatch)
    assert ctx.guard(None, "delete bonds") is True and asked == []


def test_guard_asks_and_checks_the_pin(ctx, qapp, monkeypatch):
    ctx.db.set_pin("1234")
    asked = _type_pin(monkeypatch, "1234", "bad", None)
    assert ctx.guard(None, "delete bonds") is True
    assert ctx.guard(None, "delete bonds") is False       # wrong
    assert ctx.guard(None, "delete bonds") is False       # cancelled
    assert "delete bonds" in asked[0] and len(asked) == 3


def test_three_wrong_pins_lock_the_prompt_for_a_while(ctx, qapp, monkeypatch):
    ctx.db.set_pin("1234")
    asked = _type_pin(monkeypatch, "x", "y", "z", "1234")
    assert [ctx.guard(None, "edit") for _ in range(3)] == [False, False, False]
    assert ctx.guard(None, "edit") is False and len(asked) == 3       # locked: not even asked
    ctx.pin_locked_until = 0
    assert ctx.guard(None, "edit") is True


def test_deleting_and_editing_need_the_pin(ctx, qapp, monkeypatch, box):
    db = ctx.db
    window = MainWindow(ctx)
    window.show_page("bonds")
    page = window.pages["bonds"]
    page.panels[None].view.selectRow(0)
    before = len(db.list_bonds())
    box.choice = "Delete"
    db.set_pin("1234")
    _type_pin(monkeypatch, "wrong")
    page._delete()
    assert len(db.list_bonds()) == before                             # wrong PIN: nothing happens
    _type_pin(monkeypatch, "1234")
    page._delete()
    assert len(db.list_bonds()) < before                              # right PIN: deleted

    copies = window.pages["copies"]
    window.show_page("copies")
    copies.panel.view.selectRow(0)
    name = copies._selected()["name"]
    _type_pin(monkeypatch, None, None)
    copies._rename()                                                  # cancelled: no dialog opens
    copies._delete()
    assert any(c["name"] == name for c in db.list_copies())


def test_pin_dialog_sets_changes_and_removes(ctx, qapp):
    dlg = security.PinDialog(ctx)
    dlg.new.setText("1234")
    dlg.again.setText("9999")
    dlg._save()
    assert not ctx.db.pin_is_set()                                    # typed differently
    dlg.again.setText("1234")
    dlg._save()
    assert ctx.db.pin_is_set()
    dlg = security.PinDialog(ctx)
    dlg.current.setText("1234")
    dlg._remove()
    assert not ctx.db.pin_is_set()


# ---------------------------------------------------------- screens: colours and the new column
def test_lists_show_the_new_column_and_colour_the_rows(ctx, qapp):
    from app.ui import theme

    window = MainWindow(ctx)
    window.show_page("bonds")
    page = window.pages["bonds"]
    assert "Last prize taken" in [c.title for c in page.COLUMNS]
    rows = page.panels[None].all_rows()
    plain = next(r for r in rows if not r["times_won"] and not r["pending_count"])
    assert page.panels[None].model.row_style(plain) is None
    won = dict(plain, times_won=1)                                    # a bond that has won
    assert page.panels[None].model.row_style(won)[1] == theme.WON_ROW_BG
    page.panels[None].view.selectRow(0)
    chosen = page.panels[None].selected_rows()[0]
    page._highlight("#FDE68A")
    assert next(b for b in ctx.db.list_bonds() if b["id"] == chosen["id"])["highlight"] == "#FDE68A"
    window.show_page("copies")
    copies = window.pages["copies"]
    copies.panel.view.selectRow(0)
    copies._highlight("#BFDBFE")
    assert copies.panel.all_rows()[0]["highlight"] == "#BFDBFE" or any(
        r["highlight"] == "#BFDBFE" for r in copies.panel.all_rows())


def test_edit_dialog_saves_the_last_prize_date(ctx, qapp):
    from app.ui.dialogs.edit_bond import EditBondDialog

    b = ctx.db.list_bonds()[0]
    dlg = EditBondDialog(ctx, b["id"])
    assert dlg.last_prize.unknown.isChecked()
    dlg.last_prize.set_value("2026-05-01")
    dlg._save()
    assert next(x for x in ctx.db.list_bonds() if x["id"] == b["id"])["last_prize_date"] == "2026-05-01"
    dlg = EditBondDialog(ctx, b["id"])
    dlg.last_prize.set_value(None)
    dlg._save()
    assert next(x for x in ctx.db.list_bonds() if x["id"] == b["id"])["last_prize_date"] is None


def test_adding_importing_approving_and_colouring_need_the_pin_too(ctx, qapp, monkeypatch, box):
    from app.ui import actions
    from app.ui.dialogs import add_bonds as add_module

    db = ctx.db
    db.set_pin("1234")
    opened = []
    monkeypatch.setattr(actions, "AddBondsDialog", lambda *a, **k: opened.append("add"))
    monkeypatch.setattr(actions, "ImportDialog", lambda *a, **k: opened.append("import"))
    _type_pin(monkeypatch, "no", "no")
    actions.add_bonds(ctx, None)
    actions.import_file(ctx, None)
    assert opened == []                                               # wrong PIN: nothing opens
    _type_pin(monkeypatch, "1234", "1234")
    with pytest.raises(AttributeError):                               # the fake dialog has no exec()
        actions.add_bonds(ctx, None)
    assert opened == ["add"] and add_module                           # right PIN: it opened

    window = MainWindow(ctx)
    ctx.run_agent("x", force=True)
    window.show_page("pending")
    page = window.pages["pending"]
    page.panel.view.selectRow(0)
    waiting = db.pending_count()
    box.choice = "Reject"
    _type_pin(monkeypatch, "no")
    page._reject()
    assert db.pending_count() == waiting
    _type_pin(monkeypatch, "1234")
    page._reject()
    assert db.pending_count() == waiting - 1
    _type_pin(monkeypatch, "no")
    page._approve(page.panel.all_rows())
    assert db.list_wins() == []

    window.show_page("bonds")
    bonds = window.pages["bonds"]
    bonds.panels[None].view.selectRow(0)
    chosen = bonds.panels[None].selected_rows()[0]["id"]
    _type_pin(monkeypatch, "no")
    bonds._highlight("#FDE68A")
    assert db.get_bond(chosen)["highlight"] is None
    _type_pin(monkeypatch, "1234")
    bonds._highlight("#FDE68A")
    assert db.get_bond(chosen)["highlight"] == "#FDE68A"
