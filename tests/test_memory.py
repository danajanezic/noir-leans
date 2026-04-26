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

    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
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

    worker = EmbeddingQueueWorker(db_path=db_path, embed_fn=fake_embed)
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

    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
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

    worker = EmbeddingQueueWorker(db_path=db_path, embed_fn=fake_embed)
    for i in range(1, 6):
        worker.enqueue(row_id=i, text=f"msg{i-1}")
    worker.shutdown()

    assert len(processed) == 5

    # Verify embeddings were actually written to DB
    rows = conn.execute("SELECT id, embedding FROM conversation_history ORDER BY id").fetchall()
    for row in rows:
        assert row["embedding"] is not None, f"Row {row['id']} embedding not stored"
        stored = np.frombuffer(row["embedding"], dtype=np.float32)
        assert np.allclose(stored, np.zeros(3, dtype=np.float32))


def test_memory_init_no_package_is_graceful(monkeypatch):
    """init() with no_embeddings=True sets _no_embeddings=True without crashing."""
    import sys
    import noir.memory as mem

    # Reset state
    mem._no_embeddings = False
    mem._model = None
    mem._worker = None

    mem.init(db_path="/tmp/test.db", no_embeddings=True)
    assert mem.is_available() is False
    assert mem.embed("anything") is None
    mem.shutdown()  # must not raise


def test_memory_embed_returns_none_when_unavailable():
    import noir.memory as mem
    mem._no_embeddings = True
    mem._model = None
    assert mem.embed("test") is None


def test_memory_enqueue_noop_when_unavailable():
    import noir.memory as mem
    mem._no_embeddings = True
    mem._worker = None
    mem.enqueue(row_id=1, text="test")  # must not raise


def test_backfill_embeds_null_rows(tmp_path):
    """run_backfill embeds all rows with embedding IS NULL."""
    import sqlite3
    import numpy as np
    import noir.memory as mem
    from noir.memory.backfill import run_backfill

    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE conversation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id TEXT, role TEXT, content TEXT, case_id INTEGER, embedding BLOB
        )
    """)
    conn.execute("INSERT INTO conversation_history (character_id, role, content) VALUES ('p', 'user', 'hello world')")
    conn.execute("INSERT INTO conversation_history (character_id, role, content) VALUES ('p', 'assistant', 'already embedded')")
    already = np.zeros(3, dtype=np.float32).tobytes()
    conn.execute("UPDATE conversation_history SET embedding=? WHERE id=2", (already,))
    conn.commit()

    # Patch the model to use a fake encoder
    mem._no_embeddings = False
    mem._model = type("M", (), {"encode": staticmethod(lambda t, **kw: np.ones(3, dtype=np.float32))})()

    run_backfill(conn)

    rows = conn.execute("SELECT id, embedding FROM conversation_history ORDER BY id").fetchall()
    assert rows[0]["embedding"] is not None  # was NULL, now filled
    assert rows[1]["embedding"] == already   # pre-existing, unchanged


def test_retrieve_returns_semantically_similar_messages(tmp_path):
    """Retrieval returns messages whose embeddings are closest to the query."""
    import sqlite3
    import numpy as np
    import noir.memory as mem
    from noir.memory.retrieval import retrieve_relevant_history

    conn = sqlite3.connect(str(tmp_path / "ret.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE conversation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id TEXT, role TEXT, content TEXT, case_id INTEGER, embedding BLOB
        )
    """)

    v_sister = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    v_family = np.array([0.9, 0.1, 0.0], dtype=np.float32)
    v_alderman = np.array([0.0, 0.0, 1.0], dtype=np.float32)

    conn.execute("INSERT INTO conversation_history (character_id, role, content, embedding) VALUES ('partner', 'user', 'my sister in Baton Rouge', ?)", (v_sister.tobytes(),))
    conn.execute("INSERT INTO conversation_history (character_id, role, content, embedding) VALUES ('partner', 'assistant', 'you mentioned family in Baton Rouge', ?)", (v_family.tobytes(),))
    conn.execute("INSERT INTO conversation_history (character_id, role, content, embedding) VALUES ('partner', 'user', 'the alderman freight contracts', ?)", (v_alderman.tobytes(),))
    conn.commit()

    query_vec = np.array([0.95, 0.05, 0.0], dtype=np.float32)
    mem._model = type("M", (), {"encode": staticmethod(lambda t, **kw: query_vec)})()
    mem._no_embeddings = False
    mem._worker = object()  # non-None so is_available() returns True

    results = retrieve_relevant_history(conn, character_id="partner", query="do you remember my sister", k=2, recency=0)
    contents = [r["content"] for r in results]

    assert "my sister in Baton Rouge" in contents
    assert "you mentioned family in Baton Rouge" in contents
    assert "the alderman freight contracts" not in contents


def test_retrieve_always_includes_recency(tmp_path):
    """Last `recency` messages are always included regardless of similarity score."""
    import sqlite3
    import numpy as np
    import noir.memory as mem
    from noir.memory.retrieval import retrieve_relevant_history

    conn = sqlite3.connect(str(tmp_path / "rec.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE conversation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id TEXT, role TEXT, content TEXT, case_id INTEGER, embedding BLOB
        )
    """)

    for i in range(5):
        v = np.zeros(4, dtype=np.float32)
        v[i % 4] = 1.0
        conn.execute(
            "INSERT INTO conversation_history (character_id, role, content, embedding) VALUES ('partner', 'user', ?, ?)",
            (f"message {i}", v.tobytes())
        )
    conn.commit()

    query_vec = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
    mem._model = type("M", (), {"encode": staticmethod(lambda t, **kw: query_vec)})()
    mem._no_embeddings = False
    mem._worker = object()  # non-None so is_available() returns True

    results = retrieve_relevant_history(conn, character_id="partner", query="anything", k=1, recency=2)
    contents = [r["content"] for r in results]

    assert "message 3" in contents
    assert "message 4" in contents


def test_retrieve_returns_empty_when_no_embeddings(tmp_path):
    """Returns empty list gracefully when embeddings are unavailable."""
    import sqlite3
    import noir.memory as mem
    from noir.memory.retrieval import retrieve_relevant_history

    conn = sqlite3.connect(str(tmp_path / "empty.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE conversation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id TEXT, role TEXT, content TEXT, case_id INTEGER, embedding BLOB
        )
    """)
    conn.execute("INSERT INTO conversation_history (character_id, role, content) VALUES ('partner', 'user', 'hello')")
    conn.commit()

    mem._no_embeddings = True
    mem._model = None
    mem._worker = None

    results = retrieve_relevant_history(conn, character_id="partner", query="hello", k=8, recency=4)
    assert results == []


def test_append_history_posts_embed_task(tmp_path, monkeypatch):
    """append_history enqueues an embed task and returns the row_id."""
    import sqlite3
    import noir.memory as mem
    from noir.persistence.repository import append_history

    conn = sqlite3.connect(str(tmp_path / "ah.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE conversation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id TEXT, role TEXT, content TEXT, case_id INTEGER, embedding BLOB
        )
    """)

    enqueued = []
    monkeypatch.setattr(mem, "_no_embeddings", False)
    monkeypatch.setattr(mem, "_worker", type("W", (), {"enqueue": staticmethod(lambda **kw: enqueued.append(kw))})())

    row_id = append_history(conn, character_id="partner", role="user", content="hello", case_id=None)

    assert isinstance(row_id, int)
    assert row_id > 0
    assert enqueued == [{"row_id": row_id, "text": "hello"}]
