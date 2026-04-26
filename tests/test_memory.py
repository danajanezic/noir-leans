import sqlite3
import pytest


def make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE conversation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            case_id INTEGER,
            embedding BLOB
        )
    """)
    return conn


def test_embedding_column_exists():
    conn = make_conn()
    cols = [row[1] for row in conn.execute("PRAGMA table_info(conversation_history)").fetchall()]
    assert "embedding" in cols
