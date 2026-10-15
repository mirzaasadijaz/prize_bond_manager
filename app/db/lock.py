"""A lock on the data file, so it cannot be opened by two copies of the app at once.

Two windows writing to one SQLite file can overwrite each other's view of the data (one window
shows stale lists and its agent can approve a win the other already moved).  The lock is an
operating-system file lock on ``<data file>.lock`` next to the data file.  The system releases it
by itself when the app closes or crashes, so it can never be left "stuck": if the app died, just
start it again.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class DatabaseInUseError(RuntimeError):
    """The data file is already open in another Prize Bond Manager window."""


class FileLock:
    """Exclusive, non-blocking lock held for as long as the object is open."""

    def __init__(self, data_file: str | Path):
        self.path = Path(str(data_file) + ".lock")
        self.data_file = Path(data_file)
        self._handle = None
        self._acquire()

    def _acquire(self) -> None:
        handle = open(self.path, "a+b")
        try:
            if sys.platform == "win32":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise DatabaseInUseError(
                f"'{self.data_file.name}' is already open in another Prize Bond Manager window "
                f"(or another program is using it).\n\nClose the other window first - two windows "
                f"on one data file would show out-of-date lists and can mix up wins.") from None
        self._handle = handle
        self._write_owner()

    def _write_owner(self) -> None:
        """Informational only: who holds the lock (the lock itself is the OS lock)."""
        try:
            self._handle.seek(1)                      # byte 0 is the locked byte on Windows
            self._handle.truncate(1)
            self._handle.write(f"pid {os.getpid()}\n".encode())
            self._handle.flush()
        except OSError:
            pass

    @property
    def held(self) -> bool:
        return self._handle is not None

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if sys.platform == "win32":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            handle.close()
