"""The HTTP API.  Start it with ``python main.py --serve`` (needs ``pip install fastapi uvicorn``).

    POST /check             bonds in the body  ->  which of them won
    POST /check/my-bonds    check every bond in the data file (no body needed)
    GET  /draws             the recorded draws
    GET  /health            is it running, how many draws / winning numbers it knows

The server only reads the data file (it never writes, and it does not take the app's lock), so it
can run while the app is open.  Interactive documentation: http://127.0.0.1:8765/docs
"""
from __future__ import annotations

import ipaddress
import secrets
import threading
from pathlib import Path

from .checker import WinningIndex, check_bonds, held_bonds, held_limits, open_readonly
from .schemas import (MAX_BONDS, CheckRequest, CheckResponse, DrawOut, Health, InvalidBond,
                      WinOut)

DEFAULT_HOST, DEFAULT_PORT = "127.0.0.1", 8765


def _is_local(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class _Store:
    """The read-only connection and the winning-number index, reloaded when the file changes."""

    def __init__(self, path: Path):
        self.path = path
        self.conn = open_readonly(path)
        self.lock = threading.Lock()
        self._version: int | None = None
        self._index: WinningIndex | None = None

    def index(self, draw_ids=None, since=None) -> WinningIndex:
        with self.lock:
            version = self.conn.execute("PRAGMA data_version").fetchone()[0]
            if draw_ids or since:                         # a filtered view is not cached
                return WinningIndex.from_connection(self.conn, draw_ids, since)
            if self._index is None or version != self._version:
                self._index = WinningIndex.from_connection(self.conn)
                self._version = version
            return self._index

    def query(self, sql: str, params=()):
        with self.lock:
            return self.conn.execute(sql, params).fetchall()


def _response(summary) -> CheckResponse:
    return CheckResponse(
        checked=summary.checked, winners=summary.winners, hits=len(summary.hits),
        draws_searched=summary.draws_searched,
        winning_numbers_searched=summary.numbers_searched,
        elapsed_ms=round(summary.elapsed_ms, 3),
        wins=[WinOut(number=h.number, denomination=h.denomination or h.row.denomination,
                     ref=h.ref, draw_id=h.row.draw_id, draw_date=h.row.draw_date,
                     draw_label=h.row.draw_label, location=h.row.location,
                     prize_label=h.row.prize_label, prize_amount=h.row.prize_amount)
              for h in summary.hits],
        invalid=[InvalidBond(index=i, number=text, reason=why)
                 for i, text, why in summary.invalid])


def create_app(db_path: str | Path, token: str | None = None):
    """Build the FastAPI application for one data file (``token``: require 'Bearer <token>')."""
    from fastapi import Depends, FastAPI, Header, HTTPException

    store = _Store(Path(db_path))

    def authorize(authorization: str | None = Header(None)) -> None:
        if token and not secrets.compare_digest(authorization or "", f"Bearer {token}"):
            raise HTTPException(401, "Send the header 'Authorization: Bearer <token>'.")

    api = FastAPI(title="Prize Bond Checker", version="1.0",
                  description=f"Check up to {MAX_BONDS:,} bonds per request against the draws "
                              "recorded in your data file.")

    @api.get("/health", response_model=Health)
    def health():
        draws = store.query("SELECT COUNT(*) FROM draws")[0][0]
        numbers = store.query("SELECT COUNT(*) FROM winning_numbers")[0][0]
        return Health(status="ok", draws=draws, winning_numbers=numbers)

    @api.get("/draws", response_model=list[DrawOut], dependencies=[Depends(authorize)])
    def draws():
        rows = store.query(
            "SELECT d.id, d.draw_date, d.denomination, d.label, d.location, d.source, "
            "(SELECT COUNT(*) FROM winning_numbers w WHERE w.draw_id = d.id) AS n "
            "FROM draws d ORDER BY d.draw_date DESC, d.id DESC")
        return [DrawOut(id=r["id"], draw_date=r["draw_date"], denomination=r["denomination"],
                        label=r["label"], location=r["location"], source=r["source"],
                        winning_numbers=r["n"]) for r in rows]

    @api.post("/check", response_model=CheckResponse, dependencies=[Depends(authorize)])
    def check(request: CheckRequest):
        index = store.index(request.draw_ids, request.since)
        summary = check_bonds(
            index, ((b.number, b.denomination, b.ref) for b in request.bonds),
            request.denomination)
        return _response(summary)

    @api.post("/check/my-bonds", response_model=CheckResponse, dependencies=[Depends(authorize)])
    def check_my_bonds(draw_ids: list[int] | None = None):
        """Every bond in the data file against the recorded draws (what the agent does)."""
        with store.lock:
            bonds = held_bonds(store.conn)
            limits = held_limits(store.conn)
        index = store.index(draw_ids)
        summary = check_bonds(index, ((n, d, r) for n, d, r, _ in bonds),
                              owned_at={i: s for i, (_, _, _, s) in enumerate(bonds) if s},
                              limits=limits)
        return _response(summary)

    return api


def run(db_path: str | Path, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
        token: str | None = None) -> None:
    """Serve until Ctrl+C.  Anything but this computer needs a token."""
    if not _is_local(host) and not token:
        raise SystemExit("Refusing to serve on a network address without --token: the API shows "
                         "your bonds.  Add --token <secret>, or use --host 127.0.0.1.")
    try:
        import uvicorn

        app = create_app(db_path, token)
    except ImportError as exc:
        raise SystemExit("The API needs extra packages:  pip install fastapi uvicorn") from exc
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Prize Bond Checker API on http://{host}:{port}  (documentation at /docs)")
    uvicorn.run(app, host=host, port=port, log_level="info")
