"""Headless tests for the Location fields and the Sales screens."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PyQt6")

from tests.test_gui_smoke import box, ctx, qapp  # noqa: E402,F401  (fixtures)
from app.ui import actions  # noqa: E402
from app.ui.dialogs.add_bonds import AddBondsDialog  # noqa: E402
from app.ui.dialogs.copy_dialogs import CopyContentsDialog, EditCopyDialog  # noqa: E402
from app.ui.dialogs.edit_bond import EditBondDialog  # noqa: E402
from app.ui.dialogs.import_dialog import ImportDialog  # noqa: E402
from app.ui.dialogs.sale_dialog import SaleDialog  # noqa: E402
from app.ui.dialogs.sale_details import EditSaleDialog, SaleDetailsDialog  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402


def bond(db, number, copy=None):
    rows = [b for b in db.list_bonds() if b["number"] == number
            and (copy is None or b["copy_name"] == copy)]
    assert len(rows) == 1, rows
    return rows[0]


# ------------------------------------------------------------------ location
def test_add_dialog_saves_the_location_of_loose_bonds_and_copies(ctx, qapp, box):
    dlg = AddBondsDialog(ctx, None, start_tab=1)
    dlg.price.set_value(750)
    dlg.location.setText("  Bank locker ")
    dlg.quick.pattern.setPlainText("700001-700003")
    dlg.quick.loose.setChecked(True)
    dlg._add()
    assert {b["location"] for b in ctx.db.list_bonds(number_from=700001, number_to=700003)} == {
        "Bank locker"}

    dlg = AddBondsDialog(ctx, None, start_tab=0)          # a copy of its own and one with the shared place
    dlg.price.set_value(750)
    dlg.location.setText("Home safe")
    editor = dlg.copies
    editor.table.item(0, 0).setText("Alpha")
    editor.editor.setPlainText("710001-710005")
    editor.add_row("Beta", "720001-720005")
    editor.table.item(1, editor.LOCATION).setText("Office drawer")      # its own place wins
    assert editor.collect_locations() == [None, "Office drawer"]
    dlg._add()
    db = ctx.db
    assert {b["location"] for b in db.copy_bonds(_copy(db, "Alpha"))} == {"Home safe"}
    assert {b["location"] for b in db.copy_bonds(_copy(db, "Beta"))} == {"Office drawer"}
    assert db.get_copy(_copy(db, "Beta"))["location"] == "Office drawer"


def _copy(db, name):
    return next(c["id"] for c in db.list_copies() if c["name"] == name)


def test_a_location_is_optional(ctx, qapp, box):
    dlg = AddBondsDialog(ctx, None, start_tab=1)
    dlg.price.set_value(750)
    dlg.quick.pattern.setPlainText("700001")
    dlg.quick.loose.setChecked(True)
    dlg._add()
    assert bond(ctx.db, "700001")["location"] is None


def test_generate_copies_can_give_every_copy_a_place(ctx, qapp):
    dlg = AddBondsDialog(ctx, None, start_tab=0)
    dlg.copies.add_generated(["800001-800010", "800011-800020"], "Shop")
    assert [r.location for r in dlg.copies.rows][-2:] == ["Shop", "Shop"]
    assert dlg.copies.table.item(1, dlg.copies.LOCATION).text() == "Shop"


def test_edit_bond_dialog_changes_the_location(ctx, qapp):
    target = bond(ctx.db, "123456")
    dlg = EditBondDialog(ctx, target["id"])
    dlg.location.setText("Mother's house")
    dlg._save()
    assert bond(ctx.db, "123456")["location"] == "Mother's house"
    dlg = EditBondDialog(ctx, target["id"])
    dlg.location.clear()
    dlg._save()
    assert bond(ctx.db, "123456")["location"] is None


def test_edit_copy_dialog_can_move_the_whole_copy(ctx, qapp):
    db = ctx.db
    copy_id = _copy(db, "Copy 4")
    dlg = EditCopyDialog(ctx, copy_id)
    dlg.location.setText("Bank")
    dlg._save()                                              # only the copy's own place
    assert db.get_copy(copy_id)["location"] == "Bank"
    assert {b["location"] for b in db.copy_bonds(copy_id)} == {None}
    dlg = EditCopyDialog(ctx, copy_id)
    dlg.apply.setChecked(True)
    dlg._save()
    assert {b["location"] for b in db.copy_bonds(copy_id)} == {"Bank"}


def test_import_reads_a_location_column_and_a_default(ctx, qapp, tmp_path):
    path = tmp_path / "bonds.csv"
    path.write_text("Bond number,Price,Location\n910001,750,Safe A\n910002,750,\n910003,750,Safe B\n")
    dlg = ImportDialog(ctx, None, str(path))
    assert dlg.parsed.has_location_column
    dlg.location.setText("Everywhere else")
    shown = {r["number"]: r["location"] for r in dlg.preview.all_rows()}
    assert shown == {"910001": "Safe A", "910002": "Everywhere else", "910003": "Safe B"}
    dlg._import()
    assert {n: bond(ctx.db, n)["location"] for n in shown} == shown


# -------------------------------------------------------------------- sales
def test_sell_dialog_picks_bonds_by_number_and_reports_ambiguity(ctx, qapp):
    dlg = SaleDialog(ctx)
    dlg.pattern.setText("100056")                      # held in Copy 1 and in Copy 5
    dlg._add()
    assert not dlg._bonds and "Held more than once" in dlg.message.text()
    assert "Copy 1" in dlg.message.text() and "Copy 5" in dlg.message.text()
    dlg.copy_combo.setCurrentIndex(dlg.copy_combo.findText("Copy 5", flags=_starts()))
    dlg._add()
    assert [(b["number"], b["copy_name"]) for b in dlg._bonds] == [("100056", "Copy 5")]
    dlg.copy_combo.setCurrentIndex(0)
    dlg.pattern.setText("100001-100003, 999999")
    dlg._add()
    assert len(dlg._bonds) == 4 and "999999" in dlg.message.text()      # not among your bonds


def _starts():
    from PyQt6.QtCore import Qt
    return Qt.MatchFlag.MatchStartsWith


def test_sell_dialog_adds_a_whole_copy_and_prices_the_sale(ctx, qapp):
    dlg = SaleDialog(ctx)
    dlg.copy_combo.setCurrentIndex(dlg.copy_combo.findText("Copy 4", flags=_starts()))
    dlg._add()
    assert len(dlg._bonds) == 50 and dlg.prices() == [200] * 50
    assert "Rs 10,000" in dlg.total_label.text()
    dlg.mode_total.setChecked(True)
    assert dlg.prices() is None and not dlg.save_button.isEnabled()      # amount missing
    dlg.amount.setText("Rs 9,500")
    assert sum(dlg.prices()) == 9_500 and dlg.save_button.isEnabled()
    assert "-Rs 500 against face value" in dlg.total_label.text()
    dlg.mode_each.setChecked(True)
    dlg.amount.setText("210")
    assert dlg.prices() == [210] * 50
    dlg._remove()                                                         # nothing selected: no-op
    assert len(dlg._bonds) == 50


def test_sell_dialog_warns_about_wins_that_would_go_to_the_buyer(ctx, qapp):
    db = ctx.db                                      # the demo draw (2026-10-01) has pending matches
    dlg = SaleDialog(ctx, None, [bond(db, "777777")])
    dlg.date.set_value("2026-09-01")                 # sold before the draw: the buyer's win
    dlg._refresh()
    assert "removed from the waiting list" in dlg.warnings.text()
    assert "stay yours" not in dlg.warnings.text()
    dlg.date.set_value("2026-10-05")                 # sold after the draw: the win stays yours
    dlg._refresh()
    assert "stay yours" in dlg.warnings.text()
    assert "removed from the waiting list" not in dlg.warnings.text()
    dlg.date.set_value("2026-10-01")                 # on the draw day: already the buyer's
    dlg._refresh()
    assert "removed from the waiting list" in dlg.warnings.text()


def test_recording_a_sale_updates_every_table(ctx, qapp, box):
    db = ctx.db
    window = MainWindow(ctx)
    before = db.dashboard_stats()
    copy_id = _copy(db, "Copy 4")
    dlg = SaleDialog(ctx, None, db.list_bonds(copy_id=copy_id))
    dlg.date.set_value("2026-10-10")
    dlg.buyer.setText("Ahmed")
    dlg.contact.setText("0300-1234567")
    dlg.location.setText("Lahore")
    dlg.mode_total.setChecked(True)
    dlg.amount.setText("10300")
    dlg._save()
    assert dlg.sale_id
    ctx.changed()

    window.show_page("copies")
    copies = {r["name"]: r for r in window.pages["copies"].panel.all_rows()}
    assert (copies["Copy 4"]["bonds"], copies["Copy 4"]["sold"]) == (0, 50)
    window.show_page("bonds")
    page = window.pages["bonds"]
    assert not [r for r in page.panels[None].all_rows() if r["copy_name"] == "Copy 4"]     # hidden by default
    page.held.setCurrentIndex(1)                                                            # "Bonds I sold"
    sold = page.panels[None].all_rows()
    assert len(sold) == 50 and {r["sold_to"] for r in sold} == {"Ahmed"}
    window.show_page("dashboard")
    stats = db.dashboard_stats()
    assert stats["bond_count"] == before["bond_count"] - 50
    assert (stats["sold_count"], stats["sale_total"]) == (50, 10_300)
    assert window.pages["dashboard"].card_sold.value.text() == "50"
    window.show_page("sales")
    (row,) = window.pages["sales"].panel.all_rows()
    assert (row["buyer"], row["bonds"], row["total_amount"], row["difference"]) == (
        "Ahmed", 50, 10_300, 300)
    assert row["copy_names"] == ["Copy 4"]


def test_a_sold_bond_cannot_be_edited_and_the_sale_can_be_taken_back(ctx, qapp, box):
    db = ctx.db
    target = bond(db, "123456")
    sale_id = db.record_sale([target["id"]], "2026-10-10", "Bilal", location="Karachi")
    dlg = EditBondDialog(ctx, target["id"])
    assert not dlg.number.isEnabled() and not dlg.location.isEnabled()
    assert "Sold on 2026-10-10 to Bilal" in dlg.status_label.text()

    details = SaleDetailsDialog(ctx, sale_id)
    assert "Bilal" in details.heading.text() and len(details.table.all_rows()) == 1
    details.table.view.selectAll()
    box.choice = "Take back"
    details._take_back()
    assert details.changed and db.get_sale(sale_id) is None          # the empty sale is removed
    assert bond(db, "123456")["sale_id"] is None


def test_edit_sale_and_undo_from_the_sales_page(ctx, qapp, box):
    db = ctx.db
    first = bond(db, "123456")
    second = bond(db, "234567")
    sale_id = db.record_sale([first["id"], second["id"]], "2026-10-10", "Bilal")
    window = MainWindow(ctx)
    window.show_page("sales")
    page = window.pages["sales"]
    page.panel.view.selectRow(0)
    dlg = EditSaleDialog(ctx, sale_id)
    dlg.buyer.setText("Bilal Khan")
    dlg.location.setText("Multan")
    dlg._save()
    assert db.get_sale(sale_id)["buyer"] == "Bilal Khan" and db.get_sale(sale_id)["location"] == "Multan"
    ctx.changed()
    page.panel.view.selectRow(0)
    box.choice = "Undo"
    page._undo()
    assert db.list_sales() == []
    assert bond(db, "123456")["sale_id"] is None and bond(db, "234567")["sale_id"] is None


def test_copy_contents_shows_location_and_sold_state(ctx, qapp):
    db = ctx.db
    copy_id = _copy(db, "Copy 4")
    bonds = db.copy_bonds(copy_id)
    db.record_sale([bonds[0]["id"]], "2026-10-10", "Zed")
    dialog = CopyContentsDialog(ctx, copy_id)
    rows = dialog.panel.all_rows()
    assert len(rows) == 50
    assert [r for r in rows if r["sale_id"]][0]["sold_to"] == "Zed"
    assert "49 bond(s) held, 1 sold" in dialog.facts.text()


def test_sell_action_returns_the_new_sale(ctx, qapp, monkeypatch):
    target = bond(ctx.db, "234567")
    def fake_exec(self):
        self.date.set_value("2026-10-12")
        self._save()
        return 1
    monkeypatch.setattr(SaleDialog, "exec", fake_exec)
    sale_id = actions.sell_bonds(ctx, None, [target])
    assert ctx.db.get_sale(sale_id)["bonds"] == 1


def test_the_demo_can_include_a_sale(qapp):
    from app import demo
    from app.db import Database
    db = Database(":memory:")
    demo.seed(db, with_sale=True)
    (sale,) = db.list_sales()
    assert (sale["buyer"], sale["bonds"], sale["copy_names"]) == ("Neighbour (demo)", 5, ["Copy 1"])
    assert db.pending_count() == 4                       # the sold bonds are not winners
    assert {c["name"]: c["location"] for c in db.list_copies()}["Copy 4"] is None
    assert {c["name"]: c["sold"] for c in db.list_copies()}["Copy 1"] == 5
    db.close()
