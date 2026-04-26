import pytest
import sqlite3
from noir.persistence.db import create_schema


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    create_schema(c)
    return c


def test_neighborhoods_table_exists(conn):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='neighborhoods'"
    ).fetchone()
    assert row is not None


def test_neighborhood_factions_table_exists(conn):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='neighborhood_factions'"
    ).fetchone()
    assert row is not None


def test_neighborhood_adjacency_table_exists(conn):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='neighborhood_adjacency'"
    ).fetchone()
    assert row is not None


def test_locations_has_neighborhood_id(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info('locations')").fetchall()]
    assert "neighborhood_id" in cols
