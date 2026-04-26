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


def test_embedding_worker_processes_task(tmp_path):
    """Worker calls embed_fn with the text and writes result back."""
    import sqlite3
    from noir.memory.worker import EmbeddingQueueWorker

    conn = sqlite3.connect(str(tmp_path / "test.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE conversation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id TEXT,
            role TEXT,
            content TEXT,
            case_id INTEGER,
            embedding BLOB
        )
    """)
    conn.execute("INSERT INTO conversation_history (character_id, role, content) VALUES ('p', 'user', 'hello')")
    conn.commit()
    row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    import numpy as np
    results = []

    def fake_embed(text: str):
        vec = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        results.append(text)
        return vec

    worker = EmbeddingQueueWorker(conn=conn, embed_fn=fake_embed)
    worker.enqueue(row_id=row_id, text="hello")
    worker.shutdown()

    row = conn.execute("SELECT embedding FROM conversation_history WHERE id=?", (row_id,)).fetchone()
    assert row["embedding"] is not None
    stored = np.frombuffer(row["embedding"], dtype=np.float32)
    assert list(stored) == [1.0, 2.0, 3.0]
    assert results == ["hello"]


def test_embedding_worker_shutdown_drains_queue(tmp_path):
    """Worker processes all enqueued tasks before shutting down."""
    import sqlite3
    from noir.memory.worker import EmbeddingQueueWorker
    import numpy as np

    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE conversation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id TEXT, role TEXT, content TEXT, case_id INTEGER, embedding BLOB
        )
    """)
    for i in range(5):
        conn.execute("INSERT INTO conversation_history (character_id, role, content) VALUES ('p', 'user', ?)", (f"msg{i}",))
    conn.commit()

    processed = []
    def fake_embed(text):
        processed.append(text)
        return np.zeros(3, dtype=np.float32)

    worker = EmbeddingQueueWorker(conn=conn, embed_fn=fake_embed)
    for i in range(1, 6):
        worker.enqueue(row_id=i, text=f"msg{i-1}")
    worker.shutdown()

    assert len(processed) == 5
