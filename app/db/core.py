"""SQLite connection, schema, transactions, settings and the activity log."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from .lock import FileLock

SCHEMA_VERSION = 2

SCHEMA = """
-- A copy is one physical book/batch of bonds.  Bonds inside it keep a stable
-- 1-based "position", so a win can say exactly where in the copy it sits.
CREATE TABLE IF NOT EXISTS copies (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL COLLATE NOCASE UNIQUE,
    first_number  TEXT,                       -- number at position 1 (kept even if that bond is later removed)
    size          INTEGER NOT NULL DEFAULT 0, -- number of positions in the copy
    note          TEXT,
    created_at    TEXT NOT NULL
);

-- The same number may be held in several copies (every one of those bonds wins
-- when the number is drawn), but one copy never holds a number twice.
CREATE TABLE IF NOT EXISTS bonds (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    number        TEXT NOT NULL,              -- display text, zero padded
    num           INTEGER NOT NULL,           -- numeric key used for matching
    denomination  INTEGER NOT NULL CHECK (denomination > 0),
    purchase_date TEXT,                       -- ISO yyyy-mm-dd or NULL
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'won')),
    copy_id       INTEGER REFERENCES copies(id) ON DELETE SET NULL,
    position      INTEGER CHECK (position IS NULL OR position > 0),
    created_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_bonds_copy_position
    ON bonds(copy_id, position) WHERE copy_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_bonds_copy_num
    ON bonds(copy_id, denomination, num) WHERE copy_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_bonds_num ON bonds(num, denomination);
CREATE INDEX IF NOT EXISTS ix_bonds_status ON bonds(status, denomination);

CREATE TABLE IF NOT EXISTS draws (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    draw_date     TEXT NOT NULL,
    denomination  INTEGER,                    -- NULL = applies to every denomination
    label         TEXT,
    location      TEXT,                       -- where the draw was held, e.g. Lahore
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS winning_numbers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    draw_id       INTEGER NOT NULL REFERENCES draws(id) ON DELETE CASCADE,
    number        TEXT NOT NULL,
    num           INTEGER NOT NULL,
    prize_label   TEXT NOT NULL DEFAULT 'Winner',
    prize_amount  INTEGER,
    UNIQUE (draw_id, num)
);
CREATE INDEX IF NOT EXISTS ix_winning_num ON winning_numbers(num);

-- Temporary list filled by the win-checking agent; nothing here has left the
-- waiting list until the user approves it.
CREATE TABLE IF NOT EXISTS pending_wins (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    bond_id            INTEGER NOT NULL REFERENCES bonds(id) ON DELETE CASCADE,
    winning_number_id  INTEGER NOT NULL REFERENCES winning_numbers(id) ON DELETE CASCADE,
    draw_id            INTEGER NOT NULL REFERENCES draws(id) ON DELETE CASCADE,
    found_at           TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending', 'approved', 'rejected')),
    resolved_at        TEXT,
    note               TEXT,
    UNIQUE (bond_id, winning_number_id)
);
CREATE INDEX IF NOT EXISTS ix_pending_status ON pending_wins(status);

-- The final win list.  Copy details are stored as a snapshot so the report
-- survives later edits or deletion of the bond, copy or draw.  A bond stays in
-- play after it wins, so one bond can have several rows here (other draws,
-- other places, other dates).
CREATE TABLE IF NOT EXISTS wins (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    bond_id            INTEGER REFERENCES bonds(id) ON DELETE SET NULL,
    draw_id            INTEGER REFERENCES draws(id) ON DELETE SET NULL,
    bond_number        TEXT NOT NULL,
    num                INTEGER NOT NULL,          -- numeric key; bonds sharing it win together
    denomination       INTEGER NOT NULL,
    draw_date          TEXT NOT NULL,
    draw_label         TEXT,
    prize_label        TEXT,
    prize_amount       INTEGER,
    copy_id            INTEGER REFERENCES copies(id) ON DELETE SET NULL,
    copy_name          TEXT,
    copy_first_number  TEXT,
    position           INTEGER,
    copy_size          INTEGER,
    approved_at        TEXT NOT NULL,
    location           TEXT,                      -- starts as the draw's location; editable
    claim_status       TEXT NOT NULL DEFAULT 'Not claimed yet',
    feedback           TEXT,                      -- free note: what the bank said, reference no ...
    updated_at         TEXT,
    UNIQUE (bond_id, draw_id)                     -- a bond can win again in another draw
);
CREATE INDEX IF NOT EXISTS ix_wins_date ON wins(draw_date);

CREATE TABLE IF NOT EXISTS activity_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL,
    action   TEXT NOT NULL,
    details  TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT
);
"""


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_iso() -> str:
    return date.today().isoformat()


def chunks(items: Sequence, size: int = 500) -> Iterator[Sequence]:
    """Split a sequence so IN (...) queries stay below SQLite's variable limit."""
    for i in range(0, len(items), size):
        yield items[i:i + size]


class DatabaseCore:
    """Owns the connection.  Domain methods are added by the mixins."""

    def __init__(self, path: str | Path = ":memory:", lock: bool = False):
        """``lock=True`` keeps a second app window from opening the same file (raises
        ``DatabaseInUseError``); the app uses it, tests and in-memory databases do not need it."""
        self.path = str(path)
        self._lock: FileLock | None = None
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            if lock:
                self._lock = FileLock(self.path)
        try:
            # isolation_level=None -> autocommit; tx() issues BEGIN/COMMIT itself.
            self.conn = sqlite3.connect(self.path, isolation_level=None)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")
            self._depth = 0
            self._migrate()
        except BaseException:
            if self._lock:
                self._lock.release()
            raise

    # -- lifecycle -----------------------------------------------------
    def _migrate(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError("This database was created by a newer version of the app.")
        if version == SCHEMA_VERSION:
            return
        if version < 1:
            self.conn.executescript(SCHEMA)
            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            return
        self._backup_before_upgrade()
        with self.tx():                       # all or nothing
            if version < 2:
                self._upgrade_to_2()
            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _backup_before_upgrade(self) -> None:
        """Keep a copy of a data file as it was before its first upgrade."""
        if self.path == ":memory:":
            return
        target = Path(self.path)
        target = target.with_name(f"{target.name}.before-upgrade.bak")
        if not target.exists():
            self.backup_to(target)

    def _upgrade_to_2(self) -> None:
        """Version 2: location / status / feedback on wins, location on draws, and bonds that
        stay in play after a win (a bond can win again, so none is marked 'won' any more)."""
        for sql in (
                "ALTER TABLE draws ADD COLUMN location TEXT",
                "ALTER TABLE wins ADD COLUMN location TEXT",
                "ALTER TABLE wins ADD COLUMN claim_status TEXT NOT NULL "
                "DEFAULT 'Not claimed yet'",
                "ALTER TABLE wins ADD COLUMN feedback TEXT",
                "ALTER TABLE wins ADD COLUMN updated_at TEXT"):
            self.conn.execute(sql)
        back = self.conn.execute(
            "UPDATE bonds SET status = 'active' WHERE status = 'won'").rowcount
        self.log("Data file upgraded",
                 "Wins now have location, status and feedback; bonds that already won take part "
                 f"in every later draw ({back} bond(s) put back in play)")

    def close(self) -> None:
        self.conn.close()
        if self._lock:
            self._lock.release()
            self._lock = None

    # -- transactions --------------------------------------------------
    @contextmanager
    def tx(self):
        """Atomic block; nested blocks become savepoints."""
        if self._depth == 0:
            self.conn.execute("BEGIN")
            name = None
        else:
            name = f"sp{self._depth}"
            self.conn.execute(f"SAVEPOINT {name}")
        self._depth += 1
        try:
            yield self.conn
        except BaseException:
            self._depth -= 1
            if name is None:
                self.conn.execute("ROLLBACK")
            else:
                self.conn.execute(f"ROLLBACK TO {name}")
                self.conn.execute(f"RELEASE {name}")
            raise
        else:
            self._depth -= 1
            if name is None:
                self.conn.execute("COMMIT")
            else:
                self.conn.execute(f"RELEASE {name}")

    # -- helpers -------------------------------------------------------
    def query(self, sql: str, params: Iterable | dict = ()) -> list[dict]:
        return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value) -> None:
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))

    def log(self, action: str, details: str = "") -> None:
        self.conn.execute(
            "INSERT INTO activity_log (ts, action, details) VALUES (?, ?, ?)",
            (now_iso(), action, details))

    def list_activity(self, limit: int = 5000) -> list[dict]:
        return self.query(
            "SELECT id, ts, action, details FROM activity_log ORDER BY id DESC LIMIT ?", (limit,))

    def backup_to(self, dest: str | Path) -> None:
        """Write a consistent copy of the whole database to ``dest``."""
        target = sqlite3.connect(str(dest))
        try:
            self.conn.backup(target)
        finally:
            target.close()
