"""Where the data file lives, and the lock that keeps two windows off one file."""
import subprocess
import sys
import textwrap

import pytest

from app import config
from app.db import Database, DatabaseInUseError


def test_a_bare_file_name_is_kept_next_to_the_program(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.delenv("PRIZE_BOND_DB", raising=False)
    assert config.resolve_db_path("my.db") == tmp_path / "my.db"
    assert config.resolve_db_path("backups/my.db") == tmp_path / "backups" / "my.db"


def test_a_full_path_is_used_as_it_is(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DIR", tmp_path / "program")
    elsewhere = tmp_path / "elsewhere" / "bonds.db"
    assert config.resolve_db_path(str(elsewhere)) == elsewhere


def test_default_file_is_next_to_the_program_and_the_env_variable_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path / "nowhere")
    monkeypatch.delenv("PRIZE_BOND_DB", raising=False)
    assert config.resolve_db_path(None) == tmp_path / config.DEFAULT_DB_NAME
    monkeypatch.setenv("PRIZE_BOND_DB", "from_env.db")
    assert config.default_db_path() == tmp_path / "from_env.db"


def test_data_in_the_old_data_folder_is_still_found(tmp_path, monkeypatch):
    old = tmp_path / "data"
    old.mkdir()
    (old / config.DEFAULT_DB_NAME).write_bytes(b"")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.delenv("PRIZE_BOND_DB", raising=False)
    assert config.resolve_db_path(None) == old / config.DEFAULT_DB_NAME


def test_second_window_cannot_open_a_locked_file(tmp_path):
    path = tmp_path / "my.db"
    first = Database(path, lock=True)
    with pytest.raises(DatabaseInUseError, match="already open"):
        Database(path, lock=True)
    first.close()
    Database(path, lock=True).close()               # free again once the first window closed


def test_unlocked_connections_and_memory_databases_are_not_affected(tmp_path):
    Database(":memory:", lock=True).close()
    first = Database(tmp_path / "plain.db")
    second = Database(tmp_path / "plain.db")        # tests / scripts do not take the lock
    first.close()
    second.close()


def test_lock_is_released_when_the_file_cannot_be_opened(tmp_path):
    path = tmp_path / "new.db"
    db = Database(path)
    db.conn.execute("PRAGMA user_version = 999")
    db.close()
    with pytest.raises(RuntimeError, match="newer version"):
        Database(path, lock=True)
    path.unlink()
    Database(path, lock=True).close()               # the failed attempt did not keep the lock


@pytest.mark.skipif(sys.platform == "win32", reason="uses a helper process; same lock code path")
def test_lock_works_across_processes_and_dies_with_the_process(tmp_path):
    path = tmp_path / "shared.db"
    holder = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(f"""
            import sys, time
            sys.path.insert(0, {str(config.PROJECT_ROOT)!r})
            from app.db import Database
            db = Database({str(path)!r}, lock=True)
            print("locked", flush=True)
            time.sleep(60)
        """)], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "locked"
        with pytest.raises(DatabaseInUseError):
            Database(path, lock=True)
    finally:
        holder.kill()                                # a crash: no clean shutdown, no cleanup
        holder.wait()
    Database(path, lock=True).close()                # the system dropped the lock by itself
