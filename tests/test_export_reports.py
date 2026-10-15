import pandas as pd

from app.processing import exporter, reports

from .conftest import numbers


def make_win(db, agent):
    db.add_copy("Copy 1", numbers("100001-100100"), 750, "2025-01-10")
    draw = db.add_draw("2026-10-01", 750, "Draw #98")
    (item,) = numbers("100056")
    db.add_winning_numbers(draw, [(item[0], item[1], "1st Prize", 1500000)])
    agent.scan()
    agent.approve_all()
    return db.list_wins()


def test_win_report_states_copy_first_number_and_position(db, agent):
    wins = make_win(db, agent)
    text = reports.win_report_text(wins)
    assert "Copy (book)" in text and "Copy 1" in text
    assert "1st bond number of this copy : 100001" in text
    assert "56 of 100" in text and "56th bond" in text
    html = reports.win_report_html(wins)
    assert "100001" in html and "56 of 100" in html


def test_position_text_edge_cases():
    assert reports.position_text({"copy_name": "A", "position": 1, "copy_size": 10}, long=True).endswith(
        "(it is the first bond of the copy)")
    assert reports.position_text({"copy_name": None, "position": 3}) == ""
    assert [reports.ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 101)] == [
        "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "101st"]
    assert "loose" in dict(reports.detail_lines(
        {"bond_number": "000001", "denomination": 100, "draw_date": "2026-01-01"}))["Copy (book)"]


def test_export_csv_and_excel_roundtrip_keeps_leading_zeros(db, agent, tmp_path):
    wins = make_win(db, agent)
    headers, rows = reports.win_table(wins)
    assert headers[-1] == "Approved on"
    csv_path = exporter.write_table(tmp_path / "wins.csv", headers, rows)
    xlsx_path = exporter.write_table(tmp_path / "wins.xlsx", headers, rows, "Wins")
    for frame in (pd.read_csv(csv_path, dtype=str), pd.read_excel(xlsx_path, dtype=str)):
        row = frame.iloc[0]
        assert row["Bond number"] == "100056"
        assert row["Copy (book)"] == "Copy 1" and row["1st bond number of copy"] == "100001"
        assert row["Position in copy"] == "56" and row["Copy size"] == "100"


def test_export_everything_workbook_and_csv_folder(seeded, tmp_path):
    sheets = exporter.collect_all(seeded)
    assert {"All bonds", "Bonds Rs 750", "Bonds Rs 1500", "Copies", "Pending wins",
            "Win list", "Draws", "Winning numbers", "Activity log"} <= set(sheets)
    path = exporter.write_workbook(tmp_path / "all.xlsx", sheets)
    frames = pd.read_excel(path, sheet_name=None, dtype=str)
    assert len(frames["All bonds"]) == 225 and len(frames["Bonds Rs 750"]) == 125
    assert frames["Copies"]["1st bond number"].tolist() == ["100001", "555001", "400100"]
    folder = exporter.write_csv_folder(tmp_path / "csv", sheets)
    assert len(folder) == len(sheets) and all(p.exists() for p in folder)


def test_unknown_extension_is_rejected(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        exporter.write_table(tmp_path / "x.txt", ["a"], [[1]])


def test_sheet_names_are_made_safe_and_unique():
    used: set[str] = set()
    a = exporter._sheet_name("Waiting: Rs/750?", used)
    b = exporter._sheet_name("Waiting: Rs/750?", used)
    assert ":" not in a and "/" not in a and a != b and len(b) <= 31


def make_shared_win(db, agent):
    """100056 sits in Copy 1 (position 56 of 100) and in Copy 2 (position 7 of 11)."""
    db.add_copy("Copy 1", numbers("100001-100100"), 750, "2025-01-10")
    db.add_copy("Copy 2", numbers("100050-100060"), 750, "2025-02-10")
    draw = db.add_draw("2026-10-01", 750, "Draw #98")
    (item,) = numbers("100056")
    db.add_winning_numbers(draw, [(item[0], item[1], "1st Prize", 1500000)])
    agent.scan()
    agent.approve_all()
    return db.list_wins()


def test_report_groups_every_bond_that_holds_the_winning_number(db, agent):
    wins = make_shared_win(db, agent)
    assert len(wins) == 2 and len(reports.group_wins(wins)) == 1
    text = reports.win_report_text(wins)
    assert "Winning numbers: 1    Winning bonds: 2" in text
    assert "Winning number 100056 (Rs 750)" in text
    assert "2 of your bonds hold this number, so all 2 win" in text
    assert "Total : Rs 3,000,000" in text and "per bond" in text
    assert "Bond 1 of 2" in text and "Bond 2 of 2" in text
    assert "1st bond number of this copy : 100001" in text and "56 of 100" in text
    assert "1st bond number of this copy : 100050" in text and "7 of 11" in text
    html = reports.win_report_html(wins)
    assert "Copy 1" in html and "Copy 2" in html and "all 2 win" in html
    assert "100050" in html and "7 of 11" in html and "Rs 3,000,000" in html


def test_single_bond_report_has_no_group_clutter(db, agent):
    text = reports.win_report_text(make_win(db, agent))
    assert "Bond 1 of" not in text and "hold this number" not in text and "Total" not in text


def test_with_same_number_expands_a_selection_to_the_whole_group(db, agent):
    wins = make_shared_win(db, agent)
    assert len(reports.with_same_number([wins[0]], wins)) == 2
    db.add_copy("Other", numbers("200001"), 750)
    unrelated = db.list_wins()                                    # unchanged: still the two wins
    assert reports.with_same_number([unrelated[1]], unrelated) == unrelated


def test_win_export_has_a_bonds_with_this_number_column(db, agent, tmp_path):
    wins = make_shared_win(db, agent)
    headers, rows = reports.win_table(wins)
    column = headers.index("Bonds with this number")
    assert [r[column] for r in rows] == [2, 2]
    frame = pd.read_csv(exporter.write_table(tmp_path / "w.csv", headers, rows), dtype=str)
    assert sorted(frame["Copy (book)"]) == ["Copy 1", "Copy 2"]
    assert sorted(frame["1st bond number of copy"]) == ["100001", "100050"]
    assert sorted(frame["Position in copy"]) == ["56", "7"]


def test_bonds_export_shows_how_many_bonds_share_each_number(db):
    db.add_copy("Copy 1", numbers("100001-100003"), 750)
    db.add_copy("Copy 2", numbers("100003-100004"), 750)
    headers, rows = exporter.bonds_table(db.list_bonds())
    column = headers.index("Bonds with this number")
    assert {r[0]: r[column] for r in rows} == {"100001": 1, "100002": 1, "100003": 2, "100004": 1}


# ---- location, status, feedback and "this bond has won before" ----
def make_repeat_win(db, agent):
    """One bond that won in Lahore (Oct) and again in Karachi (Nov)."""
    db.add_copy("Copy 1", numbers("100001-100100"), 750, "2025-01-10")
    (item,) = numbers("100056")
    for date, label, place, tier, amount in (("2026-10-01", "Draw #98", "Lahore", "1st Prize", 1500000),
                                             ("2026-11-01", "Draw #99", "Karachi", "2nd Prize", 500000)):
        draw = db.add_draw(date, 750, label, place)
        db.add_winning_numbers(draw, [(item[0], item[1], tier, amount)])
        agent.scan()
        agent.approve_all()
    return sorted(db.list_wins(), key=lambda w: w["draw_date"])


def test_report_states_location_status_feedback_and_repeat_win(db, agent):
    first, second = make_repeat_win(db, agent)
    db.update_win_details([first["id"]], claim_status="Paid", feedback="cash received, slip 77")
    wins = [db.get_win(first["id"]), db.get_win(second["id"])]
    text = reports.win_report_text(wins)
    assert "Location                     : Lahore" in text and "Location                     : Karachi" in text
    assert "Status                       : Paid" in text
    assert "Status                       : Not claimed yet" in text
    assert "Feedback                     : cash received, slip 77" in text
    assert "This bond has won            : 1st of 2 wins" in text
    assert "This bond has won            : 2nd of 2 wins" in text
    html = reports.win_report_html(wins)
    assert "Lahore" in html and "Karachi" in html and "cash received, slip 77" in html
    assert "2nd of 2 wins" in html


def test_a_first_win_has_no_repeat_line_and_pending_rows_have_no_status(db, agent):
    (win,) = make_win(db, agent)
    text = reports.win_report_text([win])
    assert "This bond has won" not in text and "Status" in text      # a win has a status
    pending = {"bond_number": "100056", "denomination": 750, "draw_location": "Lahore",
               "copy_name": "Copy 1", "position": 56, "copy_size": 100,
               "copy_first_number": "100001", "draw_date": "2026-10-01"}
    lines = dict(reports.claim_lines(pending))
    assert lines == {"Location": "Lahore"}                           # no status / feedback yet


def test_win_no_text_for_a_cell():
    assert reports.win_no_text({"win_no": 1, "times_won": 1}) == "1"
    assert reports.win_no_text({"win_no": 2, "times_won": 3}) == "2 of 3"
    assert reports.win_no_text({}) == "-"
    assert reports.repeat_text({"win_no": 3, "times_won": 3}) == "3rd of 3 wins"
    assert reports.repeat_text({"win_no": 1, "times_won": 1}) == ""


def test_win_export_has_location_status_feedback_and_win_number(db, agent, tmp_path):
    first, second = make_repeat_win(db, agent)
    db.update_win_details([second["id"]], claim_status="Claim submitted", feedback="at HBL Karachi")
    headers, rows = reports.win_table(sorted(db.list_wins(), key=lambda w: w["draw_date"]))
    col = {name: headers.index(name) for name in
           ("Location", "Status", "Feedback", "Win no.", "Times this bond won")}
    assert [r[col["Location"]] for r in rows] == ["Lahore", "Karachi"]
    assert [r[col["Status"]] for r in rows] == ["Not claimed yet", "Claim submitted"]
    assert [r[col["Feedback"]] for r in rows] == ["", "at HBL Karachi"]
    assert [(r[col["Win no."]], r[col["Times this bond won"]]) for r in rows] == [(1, 2), (2, 2)]
    frame = pd.read_csv(exporter.write_table(tmp_path / "w.csv", headers, rows), dtype=str)
    assert frame["Location"].tolist() == ["Lahore", "Karachi"]
    assert headers[-1] == "Approved on"


def test_pending_export_leaves_out_status_and_feedback(db, agent):
    db.add_copy("Copy 1", numbers("100001-100100"), 750)
    draw = db.add_draw("2026-10-01", 750, "Draw #98", "Lahore")
    (item,) = numbers("100056")
    db.add_winning_numbers(draw, [(item[0], item[1], "1st Prize", 1)])
    agent.scan()
    headers, rows = reports.win_table(db.list_pending(), "Found on", "found_at", claims=False)
    assert "Status" not in headers and "Feedback" not in headers
    assert rows[0][headers.index("Location")] == "Lahore" and headers[-1] == "Found on"


def test_bonds_export_has_times_won_instead_of_status(db, agent):
    make_repeat_win(db, agent)
    headers, rows = exporter.bonds_table(db.list_bonds())
    assert "Status" not in headers
    column = headers.index("Times won")
    assert {r[0]: r[column] for r in rows}["100056"] == 2 and {r[column] for r in rows} == {0, 2}


def test_draws_and_winning_numbers_export_the_location(db, agent):
    make_repeat_win(db, agent)
    headers, rows = exporter.draws_table(db.list_draws())
    assert [r[headers.index("Location")] for r in rows] == ["Karachi", "Lahore"]
    sheets = exporter.collect_all(db)
    assert "Location" in sheets["Winning numbers"][0] and "Status" in sheets["Win list"][0]
    assert "Status" not in sheets["Pending wins"][0]
