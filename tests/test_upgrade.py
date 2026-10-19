"""A data file made by the previous version (v1) is upgraded in place, and nothing is lost."""
import sqlite3

import pytest

from app import config
from app.db import Database
from app.db.core import SCHEMA, SCHEMA_VERSION

# The v1 layout exactly as the previous release created it: no location on draws, and no
# location / claim_status / feedback / updated_at on wins.
V1_SCHEMA = """
CREATE TABLE copies (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    first_number TEXT, size INTEGER NOT NULL DEFAULT 0, note TEXT, created_at TEXT NOT NULL);
CREATE TABLE bonds (
    id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT NOT NULL, num INTEGER NOT NULL,
    denomination INTEGER NOT NULL CHECK (denomination > 0), purchase_date TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'won')),
    copy_id INTEGER REFERENCES copies(id) ON DELETE SET NULL,
    position INTEGER CHECK (position IS NULL OR position > 0), created_at TEXT NOT NULL);
CREATE UNIQUE INDEX ux_bonds_copy_position ON bonds(copy_id, position) WHERE copy_id IS NOT NULL;
CREATE UNIQUE INDEX ux_bonds_copy_num ON bonds(copy_id, denomination, num) WHERE copy_id IS NOT NULL;
CREATE TABLE draws (
    id INTEGER PRIMARY KEY AUTOINCREMENT, draw_date TEXT NOT NULL, denomination INTEGER,
    label TEXT, created_at TEXT NOT NULL);
CREATE TABLE winning_numbers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draw_id INTEGER NOT NULL REFERENCES draws(id) ON DELETE CASCADE,
    number TEXT NOT NULL, num INTEGER NOT NULL, prize_label TEXT NOT NULL DEFAULT 'Winner',
    prize_amount INTEGER, UNIQUE (draw_id, num));
CREATE TABLE pending_wins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bond_id INTEGER NOT NULL REFERENCES bonds(id) ON DELETE CASCADE,
    winning_number_id INTEGER NOT NULL REFERENCES winning_numbers(id) ON DELETE CASCADE,
    draw_id INTEGER NOT NULL REFERENCES draws(id) ON DELETE CASCADE,
    found_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    resolved_at TEXT, note TEXT, UNIQUE (bond_id, winning_number_id));
CREATE TABLE wins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bond_id INTEGER REFERENCES bonds(id) ON DELETE SET NULL,
    draw_id INTEGER REFERENCES draws(id) ON DELETE SET NULL,
    bond_number TEXT NOT NULL, num INTEGER NOT NULL, denomination INTEGER NOT NULL,
    draw_date TEXT NOT NULL, draw_label TEXT, prize_label TEXT, prize_amount INTEGER,
    copy_id INTEGER REFERENCES copies(id) ON DELETE SET NULL, copy_name TEXT,
    copy_first_number TEXT, position INTEGER, copy_size INTEGER, approved_at TEXT NOT NULL,
    UNIQUE (bond_id, draw_id));
CREATE TABLE activity_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
    action TEXT NOT NULL, details TEXT);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
PRAGMA user_version = 1;
"""


@pytest.fixture
def old_file(tmp_path):
    """A v1 data file with a copy, one bond that already won (status 'won'), and its win."""
    path = tmp_path / "my.db"
    con = sqlite3.connect(path)
    con.executescript(V1_SCHEMA)
    con.executescript("""
        INSERT INTO copies VALUES (1, 'Copy 1', '100001', 3, NULL, '2026-01-01 10:00:00');
        INSERT INTO bonds VALUES (1, '100001', 100001, 750, '2025-01-10', 'active', 1, 1, '2026-01-01');
        INSERT INTO bonds VALUES (2, '100002', 100002, 750, '2025-01-10', 'won',    1, 2, '2026-01-01');
        INSERT INTO bonds VALUES (3, '100003', 100003, 750, '2025-01-10', 'active', 1, 3, '2026-01-01');
        INSERT INTO draws VALUES (1, '2026-09-01', 750, 'Draw #97', '2026-09-02');
        INSERT INTO winning_numbers VALUES (1, 1, '100002', 100002, '1st Prize', 1500000);
        INSERT INTO pending_wins VALUES (1, 2, 1, 1, '2026-09-02', 'approved', '2026-09-02', NULL);
        INSERT INTO wins VALUES (1, 2, 1, '100002', 100002, 750, '2026-09-01', 'Draw #97',
            '1st Prize', 1500000, 1, 'Copy 1', '100001', 2, 3, '2026-09-02 09:00:00');
    """)
    con.commit()
    con.close()
    return path


def test_old_file_is_upgraded_and_keeps_its_data(old_file):
    db = Database(old_file)
    assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert [b["number"] for b in db.list_bonds()] == ["100001", "100002", "100003"]
    (win,) = db.list_wins()
    assert (win["bond_number"], win["copy_name"], win["position"], win["prize_amount"]) == (
        "100002", "Copy 1", 2, 1500000)
    assert (win["location"], win["claim_status"], win["feedback"]) == (None, "Not claimed yet", None)
    assert db.list_draws()[0]["location"] is None
    assert [e["action"] for e in db.list_activity()][0] == "Data file upgraded"
    db.close()


def test_the_bond_that_already_won_is_back_in_play_and_can_win_again(old_file):
    db = Database(old_file)
    assert {b["status"] for b in db.list_bonds()} == {"active"}
    assert next(b for b in db.list_bonds() if b["number"] == "100002")["times_won"] == 1
    draw = db.add_draw("2026-10-01", 750, "Draw #98", "Karachi")
    db.add_winning_numbers(draw, [("100002", 100002, "2nd Prize", 500000)])
    assert db.scan_for_matches(draw).new_pending == 1            # the earlier winner is checked
    db.approve_pending([db.list_pending()[0]["pending_id"]])
    wins = sorted(db.list_wins(), key=lambda w: w["draw_date"])
    assert [(w["draw_date"], w["win_no"], w["times_won"]) for w in wins] == [
        ("2026-09-01", 1, 2), ("2026-10-01", 2, 2)]
    assert wins[1]["location"] == "Karachi"
    db.close()


def test_rescanning_an_old_draw_does_not_requeue_a_win_you_already_approved(old_file):
    db = Database(old_file)
    assert db.scan_for_matches().new_pending == 0
    db.close()


def test_a_backup_of_the_old_file_is_kept_once(old_file):
    Database(old_file).close()
    backup = old_file.with_name("my.db.before-upgrade.bak")
    assert backup.exists()
    con = sqlite3.connect(backup)
    assert con.execute("PRAGMA user_version").fetchone()[0] == 1
    assert con.execute("SELECT status FROM bonds WHERE id = 2").fetchone()[0] == "won"
    con.close()
    # later starts do not touch it again
    before = backup.read_bytes()
    Database(old_file).close()
    assert backup.read_bytes() == before


def test_a_failed_upgrade_changes_nothing(old_file, monkeypatch):
    def broken(self):
        self.conn.execute("ALTER TABLE draws ADD COLUMN location TEXT")
        raise RuntimeError("disk full")
    monkeypatch.setattr(Database, "_upgrade_to_2", broken)
    with pytest.raises(RuntimeError, match="disk full"):
        Database(old_file)
    con = sqlite3.connect(old_file)
    assert con.execute("PRAGMA user_version").fetchone()[0] == 1
    assert "location" not in [r[1] for r in con.execute("PRAGMA table_info(draws)")]
    con.close()


def test_a_new_file_has_the_new_columns_from_the_start(tmp_path):
    db = Database(tmp_path / "fresh.db")
    assert "location" in [r["name"] for r in db.query("PRAGMA table_info(draws)")]
    wins = {r["name"]: r for r in db.query("PRAGMA table_info(wins)")}
    assert {"location", "claim_status", "feedback", "updated_at"} <= set(wins)
    assert wins["claim_status"]["dflt_value"] == f"'{config.DEFAULT_WIN_STATUS}'"
    assert not (tmp_path / "fresh.db.before-upgrade.bak").exists()      # nothing to back up
    db.close()


def test_upgraded_and_new_files_have_the_same_win_columns(old_file, tmp_path):
    upgraded = Database(old_file)
    fresh = Database(":memory:")
    names = lambda d: sorted(r["name"] for r in d.query("PRAGMA table_info(wins)"))  # noqa: E731
    assert names(upgraded) == names(fresh)
    assert "claim_status" in SCHEMA
    upgraded.close()
    fresh.close()


# ------------------------------------------------------------------ version 2 -> 3
@pytest.fixture
def v2_file(tmp_path):
    """A data file as the previous release (v2) left it: wins have claim columns, but there is no
    location on bonds / copies, no sales and no source on draws."""
    path = tmp_path / "v2.db"
    con = sqlite3.connect(path)
    con.executescript(V1_SCHEMA)
    for sql in ("ALTER TABLE draws ADD COLUMN location TEXT",
                "ALTER TABLE wins ADD COLUMN location TEXT",
                "ALTER TABLE wins ADD COLUMN claim_status TEXT NOT NULL DEFAULT 'Not claimed yet'",
                "ALTER TABLE wins ADD COLUMN feedback TEXT",
                "ALTER TABLE wins ADD COLUMN updated_at TEXT"):
        con.execute(sql)
    con.executescript("""
        INSERT INTO copies VALUES (1, 'Copy 1', '100001', 2, NULL, '2026-01-01 10:00:00');
        INSERT INTO bonds VALUES (1, '100001', 100001, 750, '2025-01-10', 'active', 1, 1, '2026-01-01');
        INSERT INTO bonds VALUES (2, '100002', 100002, 750, '2025-01-10', 'active', 1, 2, '2026-01-01');
        INSERT INTO draws (id, draw_date, denomination, label, created_at, location)
            VALUES (1, '2026-09-01', 750, 'Draw #97', '2026-09-02', 'Lahore');
        PRAGMA user_version = 2;
    """)
    con.commit()
    con.close()
    return path


def test_a_version_2_file_gets_locations_sales_and_draw_sources(v2_file):
    db = Database(v2_file)
    assert db.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert [b["location"] for b in db.list_bonds()] == [None, None]
    assert db.list_copies()[0]["location"] is None and db.list_copies()[0]["sold"] == 0
    assert db.list_draws()[0]["source"] == "Manual"              # what was typed in earlier
    assert db.list_sales() == []
    sale_id = db.record_sale([db.list_bonds()[0]["id"]], "2026-10-14", "Ali")      # sales work
    assert db.get_sale(sale_id)["bonds"] == 1
    assert any(a["action"] == "Data file upgraded" for a in db.list_activity())
    assert v2_file.with_name("v2.db.before-upgrade.bak").exists()
    db.close()


def _columns(db):
    return {t: [r["name"] for r in db.conn.execute(f"PRAGMA table_info({t})")]
            for t in ("copies", "bonds", "draws", "wins", "sales", "sale_items")}


def test_upgraded_and_new_files_end_up_with_the_same_columns(v2_file, tmp_path):
    upgraded, fresh = Database(v2_file), Database(tmp_path / "new.db")
    for table, columns in _columns(fresh).items():
        assert set(_columns(upgraded)[table]) == set(columns), table
    upgraded.close()
    fresh.close()


def test_a_version_1_file_goes_all_the_way_to_version_3(old_file):
    db = Database(old_file)
    assert db.conn.execute("PRAGMA user_version").fetchone()[0] == 3
    assert db.list_sales() == [] and db.list_draws()[0]["source"] == "Manual"
    db.close()
