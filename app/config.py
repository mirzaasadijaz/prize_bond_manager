"""Application-wide constants and path helpers."""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Prize Bond Manager"

PROJECT_ROOT = Path(__file__).resolve().parent.parent

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

# Default prize tiers offered in the Draw Results form.
DEFAULT_PRIZE_TIERS = ["1st Prize", "2nd Prize", "3rd Prize", "Winner"]


def default_db_path() -> Path:
    """Where the SQLite file lives.

    Override with the PRIZE_BOND_DB environment variable or ``--db`` on the
    command line.  By default the database sits in ``data/`` next to the code,
    which makes it easy to find and back up.
    """
    env = os.environ.get("PRIZE_BOND_DB")
    if env:
        return Path(env).expanduser()
    return PROJECT_ROOT / "data" / "prize_bonds.db"
