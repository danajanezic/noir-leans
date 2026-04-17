import sqlite3
from noir.persistence.db import create_schema


def test_create_schema_creates_all_tables():
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    tables = {
        row[0] for row in
        conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    expected = {
        "player", "partner", "conversation_history", "cases",
        "locations", "npcs", "evidence", "arrests",
        "character_locations", "mystery_archetypes",
    }
    assert expected.issubset(tables)
    conn.close()


def test_create_schema_is_idempotent():
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    create_schema(conn)  # must not raise
    conn.close()
