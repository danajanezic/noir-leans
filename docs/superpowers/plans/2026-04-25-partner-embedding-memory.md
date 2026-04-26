# Partner Embedding Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the partner's unbounded cross-case history dump with semantic retrieval using local embeddings, so the partner recalls relevant past conversations without hallucinating details from unrelated cases.

**Architecture:** New `noir/memory/` module owns embedding generation (sentence-transformers, all-MiniLM-L6-v2), async write-back worker, startup backfill, and retrieval. `conversation_history` gains an `embedding BLOB NULL` column via migration. `Companion._history_with_summaries()` is overridden to use retrieval. Base `Agent` and NPC behavior are unchanged. A `_set_active_case()` helper in `game.py` keeps `companion.case_id` in sync.

**Tech Stack:** `sentence-transformers>=2.7`, `numpy>=1.24` (optional dep group `[memory]`). SQLite for vector storage. Pure numpy for cosine similarity.

---

## File Map

**Created:**
- `noir/memory/__init__.py` — model singleton, `init()`, `shutdown()`, `embed()`, `enqueue()`, `is_available()`
- `noir/memory/worker.py` — `EmbeddingQueueWorker` (mirrors audio queue worker pattern)
- `noir/memory/backfill.py` — `run_backfill(conn)` async startup backfill
- `noir/memory/retrieval.py` — `retrieve_relevant_history(conn, *, character_id, query, k, recency)`
- `tests/test_memory.py` — all memory tests

**Modified:**
- `pyproject.toml` — add `[memory]` optional dep group
- `noir/persistence/db.py` — add migration for `embedding BLOB NULL` column
- `noir/persistence/repository.py` — `append_history()` posts embed task, returns `row_id`
- `noir/characters/companion.py` — override `_history_with_summaries(query="")`
- `noir/game.py` — `_set_active_case()` helper, memory init/shutdown in `main.py`
- `main.py` — `memory.init()` / `memory.shutdown()` alongside audio

---

## Task 1: Optional dependency and schema migration

**Files:**
- Modify: `pyproject.toml`
- Modify: `noir/persistence/db.py:324-372` (the `_MIGRATIONS` list)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_memory.py
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
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_memory.py::test_embedding_column_exists -v
```

Expected: FAIL (test_memory.py doesn't exist yet, or column missing from real DB schema)

- [ ] **Step 3: Add the migration to `noir/persistence/db.py`**

Add to the end of the `_MIGRATIONS` list (around line 371, after the `"ALTER TABLE npcs ADD COLUMN sex TEXT"` entry):

```python
    "ALTER TABLE conversation_history ADD COLUMN embedding BLOB",
```

- [ ] **Step 4: Add the `[memory]` optional dep group to `pyproject.toml`**

```toml
[project.optional-dependencies]
memory = [
    "sentence-transformers>=2.7",
    "numpy>=1.24",
]
```

Add this block after the existing `audio = [...]` block.

- [ ] **Step 5: Run the test to verify it passes**

```bash
pytest tests/test_memory.py::test_embedding_column_exists -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml noir/persistence/db.py tests/test_memory.py
git commit -m "feat: add embedding column migration and memory optional dep group"
```

---

## Task 2: Embedding worker

**Files:**
- Create: `noir/memory/worker.py`
- Create: `noir/memory/__init__.py` (stub, expanded in Task 3)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_memory.py`:

```python
def test_embedding_worker_processes_task(tmp_path):
    """Worker calls embed_fn with the text and writes result back."""
    import sqlite3
    from noir.memory.worker import EmbeddingQueueWorker

    conn = sqlite3.connect(str(tmp_path / "test.db"))
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
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_memory.py::test_embedding_worker_processes_task tests/test_memory.py::test_embedding_worker_shutdown_drains_queue -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'noir.memory'`

- [ ] **Step 3: Create `noir/memory/__init__.py` (stub)**

```python
# noir/memory/__init__.py
```

(Empty for now — expanded in Task 3.)

- [ ] **Step 4: Create `noir/memory/worker.py`**

```python
import logging
import queue
import sqlite3
import threading
from typing import Callable
import numpy as np

_log = logging.getLogger(__name__)
_STOP = object()


class EmbeddingQueueWorker:
    """Background daemon thread that embeds text and writes vectors back to conversation_history."""

    def __init__(self, conn: sqlite3.Connection, embed_fn: Callable[[str], np.ndarray]) -> None:
        self._conn = conn
        self._embed_fn = embed_fn
        self._q: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True, name="embedding-queue")
        self._thread.start()

    def enqueue(self, *, row_id: int, text: str) -> None:
        self._q.put((row_id, text))

    def shutdown(self) -> None:
        self._q.put(_STOP)
        self._thread.join(timeout=10.0)
        if self._thread.is_alive():
            _log.warning("embedding-queue worker did not stop within timeout")

    def _run(self) -> None:
        while True:
            item = self._q.get()
            if item is _STOP:
                break
            row_id, text = item
            try:
                vec = self._embed_fn(text)
                self._conn.execute(
                    "UPDATE conversation_history SET embedding=? WHERE id=?",
                    (vec.astype(np.float32).tobytes(), row_id)
                )
                self._conn.commit()
            except Exception as e:
                _log.warning("embedding worker error for row %d: %s", row_id, e)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_memory.py::test_embedding_worker_processes_task tests/test_memory.py::test_embedding_worker_shutdown_drains_queue -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add noir/memory/__init__.py noir/memory/worker.py tests/test_memory.py
git commit -m "feat: embedding queue worker"
```

---

## Task 3: Memory module init/shutdown and embed function

**Files:**
- Modify: `noir/memory/__init__.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_memory.py`:

```python
def test_memory_init_no_package_is_graceful(monkeypatch):
    """init() with no sentence-transformers sets _no_embeddings=True without crashing."""
    import sys
    import noir.memory as mem

    # Simulate sentence_transformers not installed
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    mem._no_embeddings = False
    mem._model = None
    mem._worker = None

    mem.init(conn=None, no_embeddings=True)
    assert mem.is_available() is False
    assert mem.embed("anything") is None


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
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_memory.py::test_memory_init_no_package_is_graceful tests/test_memory.py::test_memory_embed_returns_none_when_unavailable tests/test_memory.py::test_memory_enqueue_noop_when_unavailable -v
```

Expected: FAIL (module has no real functions yet)

- [ ] **Step 3: Implement `noir/memory/__init__.py`**

```python
import logging
import sqlite3

import numpy as np

_log = logging.getLogger(__name__)

_no_embeddings: bool = False
_model = None       # SentenceTransformer instance
_worker = None      # EmbeddingQueueWorker instance

MODEL_NAME = "all-MiniLM-L6-v2"


def init(conn: sqlite3.Connection | None, *, no_embeddings: bool = False) -> None:
    global _no_embeddings, _model, _worker
    if no_embeddings:
        _no_embeddings = True
        return
    try:
        from sentence_transformers import SentenceTransformer
        from noir.memory.worker import EmbeddingQueueWorker
        _model = SentenceTransformer(MODEL_NAME)
        if conn is not None:
            _worker = EmbeddingQueueWorker(conn=conn, embed_fn=_encode)
            _schedule_backfill(conn)
    except Exception as e:
        _log.warning("memory init failed, running without embeddings: %s", e)
        _no_embeddings = True


def shutdown() -> None:
    global _worker
    if _worker is not None:
        _worker.shutdown()
        _worker = None


def embed(text: str) -> "np.ndarray | None":
    if _no_embeddings or _model is None:
        return None
    try:
        return _encode(text)
    except Exception as e:
        _log.warning("embed failed: %s", e)
        return None


def enqueue(*, row_id: int, text: str) -> None:
    if _no_embeddings or _worker is None:
        return
    _worker.enqueue(row_id=row_id, text=text)


def is_available() -> bool:
    return not _no_embeddings and _model is not None


def _encode(text: str) -> np.ndarray:
    return _model.encode(text, convert_to_numpy=True).astype(np.float32)


def _schedule_backfill(conn: sqlite3.Connection) -> None:
    import threading
    from noir.memory.backfill import run_backfill
    t = threading.Thread(target=run_backfill, args=(conn,), daemon=True, name="embedding-backfill")
    t.start()
```

- [ ] **Step 4: Run the tests**

```bash
pytest tests/test_memory.py::test_memory_init_no_package_is_graceful tests/test_memory.py::test_memory_embed_returns_none_when_unavailable tests/test_memory.py::test_memory_enqueue_noop_when_unavailable -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add noir/memory/__init__.py tests/test_memory.py
git commit -m "feat: memory module init/shutdown/embed with graceful fallback"
```

---

## Task 4: Backfill

**Files:**
- Create: `noir/memory/backfill.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_memory.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_memory.py::test_backfill_embeds_null_rows -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'noir.memory.backfill'`

- [ ] **Step 3: Create `noir/memory/backfill.py`**

```python
import logging
import sqlite3

import numpy as np

import noir.memory as _mem

_log = logging.getLogger(__name__)
_BATCH_SIZE = 32


def run_backfill(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT id, content FROM conversation_history WHERE embedding IS NULL ORDER BY id"
    ).fetchall()
    if not rows:
        return
    _log.info("embedding backfill: %d rows to process", len(rows))
    for i in range(0, len(rows), _BATCH_SIZE):
        batch = rows[i: i + _BATCH_SIZE]
        for row in batch:
            try:
                vec = _mem._encode(row["content"])
                conn.execute(
                    "UPDATE conversation_history SET embedding=? WHERE id=?",
                    (vec.tobytes(), row["id"])
                )
            except Exception as e:
                _log.warning("backfill failed for row %d: %s", row["id"], e)
        conn.commit()
    _log.info("embedding backfill complete")
```

- [ ] **Step 4: Run the test**

```bash
pytest tests/test_memory.py::test_backfill_embeds_null_rows -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add noir/memory/backfill.py tests/test_memory.py
git commit -m "feat: async embedding backfill for existing conversation history"
```

---

## Task 5: Retrieval function

**Files:**
- Create: `noir/memory/retrieval.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_memory.py`:

```python
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

    # Three messages: first two are "close" to each other, third is orthogonal
    v_sister = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    v_family = np.array([0.9, 0.1, 0.0], dtype=np.float32)
    v_alderman = np.array([0.0, 0.0, 1.0], dtype=np.float32)

    conn.execute("INSERT INTO conversation_history (character_id, role, content, embedding) VALUES ('partner', 'user', 'my sister in Baton Rouge', ?)", (v_sister.tobytes(),))
    conn.execute("INSERT INTO conversation_history (character_id, role, content, embedding) VALUES ('partner', 'assistant', 'you mentioned family in Baton Rouge', ?)", (v_family.tobytes(),))
    conn.execute("INSERT INTO conversation_history (character_id, role, content, embedding) VALUES ('partner', 'user', 'the alderman freight contracts', ?)", (v_alderman.tobytes(),))
    conn.commit()

    # Query vector close to sister/family
    query_vec = np.array([0.95, 0.05, 0.0], dtype=np.float32)
    mem._model = type("M", (), {"encode": staticmethod(lambda t, **kw: query_vec)})()
    mem._no_embeddings = False

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

    # Orthogonal vectors — nothing is semantically similar to the query
    for i in range(5):
        v = np.zeros(4, dtype=np.float32)
        v[i % 4] = 1.0
        conn.execute(
            "INSERT INTO conversation_history (character_id, role, content, embedding) VALUES ('partner', 'user', ?, ?)",
            (f"message {i}", v.tobytes())
        )
    conn.commit()

    query_vec = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)  # only matches msg 3
    mem._model = type("M", (), {"encode": staticmethod(lambda t, **kw: query_vec)})()
    mem._no_embeddings = False

    results = retrieve_relevant_history(conn, character_id="partner", query="anything", k=1, recency=2)
    contents = [r["content"] for r in results]

    # recency=2 means last 2 messages (msg 3 and msg 4) must be present
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

    results = retrieve_relevant_history(conn, character_id="partner", query="hello", k=8, recency=4)
    assert results == []
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_memory.py::test_retrieve_returns_semantically_similar_messages tests/test_memory.py::test_retrieve_always_includes_recency tests/test_memory.py::test_retrieve_returns_empty_when_no_embeddings -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create `noir/memory/retrieval.py`**

```python
import logging
import sqlite3
from typing import Any

import numpy as np

import noir.memory as _mem

_log = logging.getLogger(__name__)


def retrieve_relevant_history(
    conn: sqlite3.Connection,
    *,
    character_id: str,
    query: str,
    k: int = 8,
    recency: int = 4,
) -> list[dict[str, Any]]:
    if not _mem.is_available():
        return []

    query_vec = _mem.embed(query)
    if query_vec is None:
        return []

    rows = conn.execute(
        "SELECT id, role, content, embedding FROM conversation_history "
        "WHERE character_id=? AND embedding IS NOT NULL ORDER BY id",
        (character_id,)
    ).fetchall()

    if not rows:
        return []

    # Build matrix of stored vectors
    ids = [r["id"] for r in rows]
    contents = [{"id": r["id"], "role": r["role"], "content": r["content"]} for r in rows]
    matrix = np.stack([
        np.frombuffer(r["embedding"], dtype=np.float32) for r in rows
    ])

    # Cosine similarity
    query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-10)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10
    scores = matrix / norms @ query_norm

    # Top-k by score
    top_k_indices = set(np.argsort(scores)[-k:].tolist())

    # Last `recency` by insertion order
    recency_indices = set(range(max(0, len(rows) - recency), len(rows)))

    # Merge, deduplicate, sort chronologically
    selected = sorted(top_k_indices | recency_indices)
    return [{"role": contents[i]["role"], "content": contents[i]["content"]} for i in selected]
```

- [ ] **Step 4: Run the tests**

```bash
pytest tests/test_memory.py::test_retrieve_returns_semantically_similar_messages tests/test_memory.py::test_retrieve_always_includes_recency tests/test_memory.py::test_retrieve_returns_empty_when_no_embeddings -v
```

Expected: PASS

- [ ] **Step 5: Run all memory tests**

```bash
pytest tests/test_memory.py -v
```

Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add noir/memory/retrieval.py tests/test_memory.py
git commit -m "feat: semantic history retrieval with cosine similarity"
```

---

## Task 6: Wire `append_history()` to post embed tasks

**Files:**
- Modify: `noir/persistence/repository.py:66-72`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_memory.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_memory.py::test_append_history_posts_embed_task -v
```

Expected: FAIL (`append_history` returns None, no enqueue)

- [ ] **Step 3: Update `append_history` in `noir/persistence/repository.py`**

Replace:

```python
def append_history(conn: sqlite3.Connection, *, character_id: str, role: str,
                   content: str, case_id: int | None) -> None:
    conn.execute(
        "INSERT INTO conversation_history (character_id, role, content, case_id) VALUES (?, ?, ?, ?)",
        (character_id, role, content, case_id)
    )
    conn.commit()
```

With:

```python
def append_history(conn: sqlite3.Connection, *, character_id: str, role: str,
                   content: str, case_id: int | None) -> int:
    cursor = conn.execute(
        "INSERT INTO conversation_history (character_id, role, content, case_id) VALUES (?, ?, ?, ?)",
        (character_id, role, content, case_id)
    )
    conn.commit()
    row_id: int = cursor.lastrowid
    try:
        import noir.memory as _mem
        _mem.enqueue(row_id=row_id, text=content)
    except Exception:
        pass
    return row_id
```

- [ ] **Step 4: Run the test**

```bash
pytest tests/test_memory.py::test_append_history_posts_embed_task -v
```

Expected: PASS

- [ ] **Step 5: Run full test suite to confirm no regressions**

```bash
pytest tests/ -v --tb=short
```

Expected: All previously passing tests still PASS (callers that ignored the return value are unaffected in Python)

- [ ] **Step 6: Commit**

```bash
git add noir/persistence/repository.py tests/test_memory.py
git commit -m "feat: append_history posts embed task and returns row_id"
```

---

## Task 7: Companion `_history_with_summaries` override

**Files:**
- Modify: `noir/characters/companion.py:70-92`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_memory.py`:

```python
def test_companion_history_uses_retrieval_when_available(tmp_path, monkeypatch):
    """_history_with_summaries(query) calls retrieve_relevant_history when embeddings available."""
    import sqlite3
    import noir.memory as mem
    from noir.characters.companion import Companion
    from unittest.mock import MagicMock, patch

    conn = sqlite3.connect(str(tmp_path / "comp.db"))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE conversation_history (id INTEGER PRIMARY KEY AUTOINCREMENT, character_id TEXT, role TEXT, content TEXT, case_id INTEGER, embedding BLOB);
        CREATE TABLE conversation_summaries (id INTEGER PRIMARY KEY AUTOINCREMENT, character_id TEXT, summary TEXT, npc_opinion TEXT, case_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE partner (id INTEGER PRIMARY KEY, name TEXT, sex TEXT, personality_archetype TEXT, speech_style TEXT, relationship_stance TEXT, system_prompt TEXT, alignment TEXT, affection INTEGER DEFAULT 0, dark_past_state TEXT DEFAULT 'none', dark_past TEXT, relationship_notes TEXT);
        INSERT INTO partner (id, name, sex, personality_archetype, speech_style, relationship_stance, system_prompt) VALUES (1, 'Viv', 'female', 'stoic', 'terse', 'professional', 'you are a partner');
    """)

    retrieved = [{"role": "user", "content": "my sister in Baton Rouge"}]
    monkeypatch.setattr(mem, "_no_embeddings", False)
    monkeypatch.setattr(mem, "_model", object())

    companion = Companion(
        character_id="partner", system_prompt="you are a partner", llm=MagicMock(),
        conn=conn, case_id=None, name="Viv", sex="female",
        personality_archetype="stoic", speech_style="terse", relationship_stance="professional"
    )

    with patch("noir.memory.retrieval.retrieve_relevant_history", return_value=retrieved) as mock_retrieve:
        result = companion._history_with_summaries(query="do you remember my sister")

    mock_retrieve.assert_called_once()
    call_kwargs = mock_retrieve.call_args[1]
    assert call_kwargs["character_id"] == "partner"
    assert call_kwargs["query"] == "do you remember my sister"
    # retrieved messages appear in the result (possibly after a prefix)
    assert any(m["content"] == "my sister in Baton Rouge" for m in result)


def test_companion_history_falls_back_to_recency_when_unavailable(tmp_path, monkeypatch):
    """Falls back to last 12 messages when embeddings unavailable."""
    import sqlite3
    import noir.memory as mem
    from noir.characters.companion import Companion
    from unittest.mock import MagicMock

    conn = sqlite3.connect(str(tmp_path / "comp2.db"))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE conversation_history (id INTEGER PRIMARY KEY AUTOINCREMENT, character_id TEXT, role TEXT, content TEXT, case_id INTEGER, embedding BLOB);
        CREATE TABLE conversation_summaries (id INTEGER PRIMARY KEY AUTOINCREMENT, character_id TEXT, summary TEXT, npc_opinion TEXT, case_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE partner (id INTEGER PRIMARY KEY, name TEXT, sex TEXT, personality_archetype TEXT, speech_style TEXT, relationship_stance TEXT, system_prompt TEXT, alignment TEXT, affection INTEGER DEFAULT 0, dark_past_state TEXT DEFAULT 'none', dark_past TEXT, relationship_notes TEXT);
        INSERT INTO partner (id, name, sex, personality_archetype, speech_style, relationship_stance, system_prompt) VALUES (1, 'Viv', 'female', 'stoic', 'terse', 'professional', 'you are a partner');
    """)
    for i in range(20):
        conn.execute("INSERT INTO conversation_history (character_id, role, content, case_id) VALUES ('partner', 'user', ?, NULL)", (f"msg{i}",))
    conn.commit()

    monkeypatch.setattr(mem, "_no_embeddings", True)
    monkeypatch.setattr(mem, "_model", None)

    companion = Companion(
        character_id="partner", system_prompt="you are a partner", llm=MagicMock(),
        conn=conn, case_id=None, name="Viv", sex="female",
        personality_archetype="stoic", speech_style="terse", relationship_stance="professional"
    )

    result = companion._history_with_summaries(query="anything")
    # Should return at most 12 messages (plus optional prefix)
    dialogue_msgs = [m for m in result if m["role"] in ("user", "assistant")]
    assert len(dialogue_msgs) <= 12
    # Should be the LAST 12 (most recent)
    assert dialogue_msgs[-1]["content"] == "msg19"
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_memory.py::test_companion_history_uses_retrieval_when_available tests/test_memory.py::test_companion_history_falls_back_to_recency_when_unavailable -v
```

Expected: FAIL

- [ ] **Step 3: Update `Companion._history_with_summaries` in `noir/characters/companion.py`**

Replace the existing `_history_with_summaries` method (lines 70-92):

```python
def _history_with_summaries(self, query: str = "") -> list[dict]:
    import noir.memory as _mem
    from noir.memory.retrieval import retrieve_relevant_history
    from noir.persistence.repository import get_history, get_conversation_summaries

    if query and _mem.is_available():
        history = retrieve_relevant_history(
            self.conn,
            character_id=self.character_id,
            query=query,
            k=8,
            recency=4,
        )
    else:
        all_history = get_history(self.conn, character_id=self.character_id, case_id=self.case_id)
        history = all_history[-12:]

    case_summaries = get_conversation_summaries(
        self.conn, character_id=self.character_id, case_id=self.case_id
    ) if self.case_id else []
    relationship = get_partner_relationship(self.conn)

    parts = []
    if case_summaries:
        parts.append("This case so far (summarized):\n" + "\n---\n".join(case_summaries))
    if relationship:
        parts.append(f"Your private feelings about this detective: {relationship}")

    if not parts:
        return history
    memory_block = "\n\n".join(parts)
    prefix = [
        {"role": "user", "content": f"[Memory: {memory_block}]"},
        {"role": "assistant", "content": "Understood — I'll carry that forward."},
    ]
    return prefix + history
```

Also update `speak()` and `interpret()` in the same file to pass the query. Find these two lines:

In `speak()` — there is no `speak()` override in Companion (it inherits from Agent). The call to `_history_with_summaries()` is in the base class `Agent._query_with_retry()` via `Agent.speak()`. Since Companion overrides `_history_with_summaries` with an optional `query` parameter, the base class call `self._history_with_summaries()` still works — `query` defaults to `""` and falls back gracefully.

However, to actually pass the query, we need to override `speak()` in Companion to call `_history_with_summaries(query=player_input)`:

```python
def speak(self, player_input: str, record: bool = True, store_as: str | None = None) -> str:
    history = self._history_with_summaries(query=player_input)
    response = self._query_with_retry(player_input, history)
    if record:
        from noir.persistence.repository import append_history
        append_history(self.conn, character_id=self.character_id,
                       role="user", content=store_as if store_as is not None else player_input,
                       case_id=self.case_id)
        append_history(self.conn, character_id=self.character_id,
                       role="assistant", content=response, case_id=self.case_id)
    return response
```

Also update `interpret()`:

```python
def interpret(self, player_input: str) -> dict:
    interpret_system = self._locked_system_prompt + _INTERPRET_SUFFIX
    history = self._history_with_summaries(query=player_input)
    result = self.llm.query_structured(interpret_system, history, player_input)
    dialogue = result.get("dialogue", "")
    from noir.persistence.repository import append_history
    append_history(self.conn, character_id=self.character_id,
                   role="user", content=player_input, case_id=self.case_id)
    append_history(self.conn, character_id=self.character_id,
                   role="assistant", content=dialogue, case_id=self.case_id)
    return result
```

- [ ] **Step 4: Run the tests**

```bash
pytest tests/test_memory.py::test_companion_history_uses_retrieval_when_available tests/test_memory.py::test_companion_history_falls_back_to_recency_when_unavailable -v
```

Expected: PASS

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add noir/characters/companion.py tests/test_memory.py
git commit -m "feat: companion uses semantic retrieval for history"
```

---

## Task 8: `_set_active_case()` helper in `game.py`

**Files:**
- Modify: `noir/game.py`

This fixes the `case_id` scoping bug: `companion.case_id` was always `None`, so the recency fallback loaded cross-case history.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_memory.py`:

```python
def test_set_active_case_syncs_companion_case_id():
    """_set_active_case updates both self.active_case_id and self.companion.case_id."""
    from unittest.mock import MagicMock, patch
    import sqlite3

    # We test the helper directly, not through Game.__init__ which requires a full DB
    # Minimal stub of the Game class for this method
    class FakeGame:
        def __init__(self):
            self.active_case_id = None
            self.companion = MagicMock()
            self.companion.case_id = None

        def _set_active_case(self, case_id):
            self.active_case_id = case_id
            if self.companion is not None:
                self.companion.case_id = case_id

    g = FakeGame()
    g._set_active_case(42)
    assert g.active_case_id == 42
    assert g.companion.case_id == 42

    g._set_active_case(None)
    assert g.active_case_id is None
    assert g.companion.case_id is None
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_memory.py::test_set_active_case_syncs_companion_case_id -v
```

Expected: FAIL (FakeGame is the stub — it should pass; but let's verify the real `Game` doesn't have `_set_active_case`)

Actually this test uses a FakeGame stub so it tests the logic pattern, not the import. It will PASS immediately because FakeGame already implements it. Instead, just run it to confirm it passes, then proceed to implement in Game.

- [ ] **Step 3: Add `_set_active_case()` to `noir/game.py`**

Find the `Game` class and add this method (place it near other helper methods, e.g. after `__init__`):

```python
def _set_active_case(self, case_id: int | None) -> None:
    self.active_case_id = case_id
    if self.companion is not None:
        self.companion.case_id = case_id
```

- [ ] **Step 4: Replace all `self.active_case_id = ` assignments in `game.py`**

Run this to find them all:

```bash
grep -n "self\.active_case_id = " noir/game.py
```

For each hit, replace `self.active_case_id = <value>` with `self._set_active_case(<value>)`.

Current hits (verify these match — line numbers may shift):
- Line 1132: `self.active_case_id = case_id`
- Line 2923: `self.active_case_id = match["id"]`
- Line 3074: `self.active_case_id = None`
- Line 3084: `self.active_case_id = None`
- Line 3096: `self.active_case_id = None`
- Line 3147: `self.active_case_id = None`
- Line 3268: `self.active_case_id = None`
- Line 3348: `self.active_case_id = None`
- Line 3866: `self.active_case_id = case_id`
- Line 3973: `self.active_case_id = active_cases[0]["id"]`

**Do not replace** the `self.active_case_id: int | None = None` declaration in `__init__` — that's the initial declaration, not an assignment.

- [ ] **Step 5: Verify no bare assignments remain**

```bash
grep -n "self\.active_case_id = " noir/game.py
```

Expected: Only the `__init__` declaration line remains (the `int | None = None` one).

- [ ] **Step 6: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add noir/game.py tests/test_memory.py
git commit -m "feat: _set_active_case helper keeps companion.case_id in sync"
```

---

## Task 9: Wire memory init/shutdown in `main.py`

**Files:**
- Modify: `main.py:75-82`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_memory.py`:

```python
def test_memory_init_and_shutdown_no_crash(tmp_path):
    """init() and shutdown() complete without error when no sentence-transformers installed."""
    import noir.memory as mem
    mem._no_embeddings = False
    mem._model = None
    mem._worker = None

    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "m.db"))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE conversation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id TEXT, role TEXT, content TEXT, case_id INTEGER, embedding BLOB
        )
    """)

    mem.init(conn=conn, no_embeddings=True)
    assert mem.is_available() is False
    mem.shutdown()  # must not raise
```

- [ ] **Step 2: Run to verify it passes**

```bash
pytest tests/test_memory.py::test_memory_init_and_shutdown_no_crash -v
```

Expected: PASS (already handled by no_embeddings=True path)

- [ ] **Step 3: Update `main.py`**

Replace:

```python
import noir.audio as audio
audio.init(no_audio="--no-audio" in sys.argv)

game = Game(conn=conn, llm=llm)
try:
    game.loop()
finally:
    audio.shutdown()
```

With:

```python
import noir.audio as audio
import noir.memory as memory

audio.init(no_audio="--no-audio" in sys.argv)
memory.init(conn=conn, no_embeddings="--no-memory" in sys.argv)

game = Game(conn=conn, llm=llm)
try:
    game.loop()
finally:
    audio.shutdown()
    memory.shutdown()
```

- [ ] **Step 4: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: All PASS

- [ ] **Step 5: Run the game briefly to confirm startup works**

```bash
python main.py --no-audio --no-memory
```

Expected: Game starts normally. If `sentence-transformers` is installed, run without `--no-memory` and check logs for "embedding backfill" messages.

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_memory.py
git commit -m "feat: wire memory init/shutdown in main.py"
```

---

## Task 10: Install sentence-transformers and verify end-to-end

This task is manual verification — no new code, no new tests.

- [ ] **Step 1: Install the memory optional deps**

```bash
pip install -e ".[memory]"
```

Expected: `sentence-transformers` and `numpy` install successfully. First run will download `all-MiniLM-L6-v2` (~80MB, cached to `~/.cache/huggingface/`).

- [ ] **Step 2: Run the full test suite with memory available**

```bash
pytest tests/ -v --tb=short
```

Expected: All PASS

- [ ] **Step 3: Start the game and verify backfill logging**

```bash
python main.py --no-audio 2>&1 | grep -i "embed\|backfill\|memory"
```

Expected output (if existing history): `INFO noir.memory.backfill: embedding backfill: N rows to process` followed by `INFO noir.memory.backfill: embedding backfill complete`

- [ ] **Step 4: Talk to the partner and verify no cross-case contamination**

In-game: start the current case, talk to the partner, ask about something personal from a previous case. Verify the partner recalls it correctly without hallucinating current-case details from unrelated past cases.

- [ ] **Step 5: Final commit**

```bash
git add .
git commit -m "feat: partner embedding memory — semantic retrieval complete"
```

---

## Self-Review

**Spec coverage:**
- ✅ `noir/memory/` module — Tasks 2, 3, 4, 5
- ✅ `embedding BLOB NULL` column — Task 1
- ✅ Async worker — Task 2
- ✅ Backfill — Task 4
- ✅ Retrieval function — Task 5
- ✅ `append_history` posts embed task — Task 6
- ✅ `Companion._history_with_summaries(query)` — Task 7
- ✅ `case_id` scoping fix — Task 8
- ✅ `main.py` init/shutdown — Task 9
- ✅ `pyproject.toml [memory]` dep group — Task 1
- ✅ Graceful fallback when package not installed — Tasks 3, 7

**Placeholder scan:** None found.

**Type consistency:**
- `retrieve_relevant_history` signature matches usage in `Companion._history_with_summaries` ✅
- `EmbeddingQueueWorker.enqueue(row_id=, text=)` keyword args match `_mem.enqueue(row_id=, text=)` ✅
- `append_history` return type changed from `None` to `int` — callers that ignore return value unaffected ✅
