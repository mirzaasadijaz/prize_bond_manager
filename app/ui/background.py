"""Run a slow job (a web request) in a worker thread and hand the answer back to the window.

Only pure work belongs in the job - it must not touch the data file, because the SQLite
connection belongs to the main thread.  The answer arrives in the main thread, where the
window may use the database again.

``threaded=False`` runs the job on the spot (tests, and anything that cannot use threads).
"""
from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QThread, pyqtSignal

_running: set["_Worker"] = set()          # keeps a running thread alive even if its window closes


class _Worker(QThread):
    answer = pyqtSignal(object)
    failure = pyqtSignal(str)

    def __init__(self, job: Callable[[], object]):
        super().__init__()
        self.job = job

    def run(self) -> None:
        try:
            value = self.job()
        except Exception as exc:  # noqa: BLE001 - whatever went wrong is shown to the user
            self.failure.emit(f"{exc}" or type(exc).__name__)
        else:
            self.answer.emit(value)


def run_in_background(job: Callable[[], object], on_answer: Callable[[object], None],
                      on_error: Callable[[str], None] | None = None,
                      threaded: bool = True) -> _Worker | None:
    """Call ``job()`` away from the window; then ``on_answer(result)`` (or ``on_error(text)``)."""
    def failed(text: str) -> None:
        if on_error:
            on_error(text)

    if not threaded:
        try:
            value = job()
        except Exception as exc:  # noqa: BLE001
            failed(str(exc) or type(exc).__name__)
        else:
            on_answer(value)
        return None
    worker = _Worker(job)
    _running.add(worker)
    worker.answer.connect(on_answer)
    worker.failure.connect(failed)
    worker.finished.connect(lambda: (_running.discard(worker), worker.deleteLater()))
    worker.start()
    return worker
