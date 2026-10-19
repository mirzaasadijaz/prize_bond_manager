"""Database layer: one ``Database`` object composed from small mixins."""
from .bonds_repo import (BondsMixin, CopyNameError, DuplicateBondError,  # noqa: F401
                         PositionTakenError)
from .core import DatabaseCore, chunks, now_iso, today_iso  # noqa: F401
from .draws_repo import DrawsMixin, WinningNumberError  # noqa: F401
from .lock import DatabaseInUseError  # noqa: F401
from .security_repo import PinError, SecurityMixin  # noqa: F401
from .sales_repo import SaleError, SalesMixin  # noqa: F401
from .wins_repo import WinsMixin


class Database(BondsMixin, DrawsMixin, WinsMixin, SalesMixin, SecurityMixin, DatabaseCore):
    """Everything the app stores, backed by a single SQLite file."""
