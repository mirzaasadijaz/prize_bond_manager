import pytest

from app.db import Database
from app.processing.agent import WinAgent
from app.processing.numbers import parse_pattern


def numbers(pattern: str):
    """Parse a pattern and fail loudly if it is invalid."""
    result = parse_pattern(pattern)
    assert result.ok, result.problems()
    return result.numbers


@pytest.fixture
def db():
    database = Database(":memory:")
    yield database
    database.close()


@pytest.fixture
def agent(db):
    return WinAgent(db)


@pytest.fixture
def seeded(db):
    """Three copies that differ in size, range and sequence."""
    db.add_copy("Copy 1", numbers("100001-100100"), 750, "2025-01-10")           # 100 bonds
    db.add_copy("Copy 2", numbers("555001-555020, 777777, 900001-900010:3"), 750, "2025-02-01")
    db.add_copy("Copy 3", numbers("400100-400001"), 1500, "2026-05-01")           # descending
    return db
