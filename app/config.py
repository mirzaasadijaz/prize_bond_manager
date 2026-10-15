"""Application-wide constants and path helpers."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Prize Bond Manager"

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# The folder the program lives in: next to main.py, or next to the .exe when the app has been
# packaged (PyInstaller).  Data files are kept here, not in whatever folder the app was started from.
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else PROJECT_ROOT

# Standard Pakistani prize-bond denominations (Rs).  The UI lets you type any
# other value too, so this list only seeds the drop-downs.
DEFAULT_DENOMINATIONS = [100, 200, 750, 1500, 7500, 15000, 25000, 40000]

# Bond numbers are displayed zero-padded to this many digits (Pakistani prize
# bonds have 6-digit numbers).  Matching never depends on padding: "123" and
# "000123" are treated as the same bond.
BOND_DIGITS = 6

# Safety limits that protect against typos such as "100001-1000100".
MAX_DIGITS = 15
MAX_RANGE_SIZE = 100_000

# Where a win stands once you have claimed (or tried to claim) the prize.  The first one is what
# every new win starts with; "Paid" is the only one that counts as finished.
WIN_STATUSES = ["Not claimed yet", "Claim submitted", "Paid", "Problem"]
DEFAULT_WIN_STATUS = WIN_STATUSES[0]
STATUS_SUBMITTED = WIN_STATUSES[1]
FINAL_WIN_STATUS = WIN_STATUSES[2]            # "Paid"
STATUS_PROBLEM = WIN_STATUSES[3]

# Default prize tiers offered in the Draw Results form.
DEFAULT_PRIZE_TIERS = ["1st Prize", "2nd Prize", "3rd Prize", "Winner"]


DEFAULT_DB_NAME = "prize_bonds.db"


def resolve_db_path(name: str | os.PathLike | None = None) -> Path:
    """Turn what the user asked for into the data file to open.

    * a full path (``D:\\bonds\\my.db``) is used as it is;
    * a bare or relative name (``my.db``) is looked for **next to the program** (``APP_DIR``),
      not in the folder the program happened to be started from;
    * nothing given: the ``PRIZE_BOND_DB`` environment variable, else ``prize_bonds.db`` next to
      the program (or the older ``data/prize_bonds.db`` if that is where your data already is).
    """
    name = name or os.environ.get("PRIZE_BOND_DB")
    if name:
        path = Path(name).expanduser()
        return path if path.is_absolute() else APP_DIR / path
    legacy = PROJECT_ROOT / "data" / DEFAULT_DB_NAME
    here = APP_DIR / DEFAULT_DB_NAME
    return legacy if legacy.exists() and not here.exists() else here


def default_db_path() -> Path:
    """The data file used when none is chosen (see ``resolve_db_path``)."""
    return resolve_db_path(None)
