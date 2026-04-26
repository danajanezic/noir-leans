# Partner Embedding Memory Design

**Goal:** Replace the partner's "load all history" approach with semantic retrieval using local embeddings, so the partner's dialogue is grounded in relevant past conversations rather than the full unbounded cross-case history dump that causes hallucination and contamination.

**Architecture:** A new `noir/memory/` module owns embedding generation, async write-back, backfill, and retrieval. The base `Agent` class is unchanged — only `Companion` adopts retrieval. NPCs continue to load full case-scoped history as before. The `case_id` scoping fix (wiring `companion.case_id` to `active_case_id`) is included in this work.

**Tech Stack:** `sentence-transformers>=2.7` with `all-MiniLM-L6-v2` (384-dimension vectors, ~80MB, CPU-friendly). `numpy` for cosine similarity. Both are optional deps — the game degrades gracefully to recency-only history if the package isn't installed.

---

## Data Layer

### `conversation_history` schema change

Add one column:

```sql
ALTER TABLE conversation_history ADD COLUMN embedding BLOB NULL;
```

Applied as a migration at DB init time (safe to run multiple times — check column existence first). `NULL` means not yet embedded. No other schema changes.

### Vector format

Stored as raw `float32` bytes: 384 floats × 4 bytes = 1,536 bytes per row. Serialized with `numpy.ndarray.tobytes()`, deserialized with `numpy.frombuffer(..., dtype=numpy.float32)`.

---

## `noir/memory/` Module

### `noir/memory/__init__.py`

Module-level singleton. Tries to import `sentence_transformers` at load time. If unavailable, sets `_no_embeddings = True` and all public functions become no-ops or return empty lists — the game never crashes.

```python
_no_embeddings: bool = False
_model = None  # SentenceTransformer instance
_worker = None  # EmbeddingQueueWorker instance

def init() -> None: ...          # load model, start worker, schedule backfill
def shutdown() -> None: ...      # drain worker, clean up
def embed(text: str) -> np.ndarray | None: ...  # synchronous, used at retrieval time
def enqueue(row_id: int, text: str) -> None: ... # async write-back
def is_available() -> bool: ...  # True when model loaded and worker running
```

Model is loaded once at `init()`. Loading `all-MiniLM-L6-v2` takes ~1-2 seconds on first call (downloads ~80MB on first run, cached thereafter). This happens at game startup, not mid-turn.

### `noir/memory/worker.py`

`EmbeddingQueueWorker` — mirrors `SpeechQueueWorker` pattern from `noir/audio/queue_worker.py`.

- Background daemon thread
- Consumes `(row_id: int, text: str)` tasks from a queue
- For each task: calls `_model.encode(text)`, writes embedding BLOB back to `conversation_history` by `row_id`
- Batch size: 1 (tasks arrive one at a time; no need to batch since volume is low)
- On shutdown: drains queue before exiting

### `noir/memory/backfill.py`

Run once at startup (in a background thread, after `init()`).

```python
def run_backfill(conn: sqlite3.Connection) -> None: ...
```

- Queries all `conversation_history` rows where `embedding IS NULL`
- Embeds each text in batches of 32 (more efficient than one-at-a-time for the model)
- Writes embeddings back
- Logs progress at INFO level
- Safe to interrupt — partial backfill continues on next startup

### `noir/memory/retrieval.py`

```python
def retrieve_relevant_history(
    conn: sqlite3.Connection,
    *,
    character_id: str,
    query: str,
    k: int = 8,
    recency: int = 4,
) -> list[dict]:
```

**Algorithm:**

1. Embed `query` synchronously via `noir.memory.embed()` (~10ms)
2. Load all `conversation_history` rows for `character_id` where `embedding IS NOT NULL`, ordered by `id` — returns `(id, role, content, embedding)`
3. Deserialize each embedding BLOB to `numpy.float32` array
4. Compute cosine similarity between query vector and each stored vector:
   ```python
   similarity = np.dot(query_vec, stored_vec) / (np.linalg.norm(query_vec) * np.linalg.norm(stored_vec))
   ```
5. Select top-`k` rows by similarity score
6. Select last-`recency` rows by insertion order (regardless of score)
7. Merge and deduplicate by `id`
8. Sort merged set by original `id` (chronological order) so the LLM sees history in sequence
9. Return as `[{"role": str, "content": str}]`

**If `noir.memory.is_available()` is False:** return last `recency` rows only (recency-only fallback, no retrieval).

**If query embedding fails** (model error): same fallback.

No `case_id` filtering — partner retrieval is intentionally cross-case to support personal conversation threads (e.g. "do you remember what I said about my sister?" should find that exchange regardless of which case it happened in). The `_companion_context()` block already injects all current-case facts as ground truth, so case contamination via retrieved history is not a risk — the LLM has authoritative current-case context and retrieved chunks only provide relationship/personal thread continuity.

---

## `Companion` Integration

### `Companion._history_with_summaries(query: str = "")` override

Replace the current implementation:

```python
def _history_with_summaries(self, query: str = "") -> list[dict]:
    from noir.memory.retrieval import retrieve_relevant_history
    import noir.memory as _mem

    if query and _mem.is_available():
        history = retrieve_relevant_history(
            self.conn,
            character_id=self.character_id,
            query=query,
            k=8,
            recency=4,
        )
    else:
        # Fallback: last 12 messages from current case (or all if case_id is None)
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

### `Companion.speak()` passes query

```python
history = self._history_with_summaries(query=player_input)
```

### `Companion.interpret()` passes query

```python
history = self._history_with_summaries(query=player_input)
```

### `Companion.summarize_and_save()` unchanged

Uses the session history passed in directly — no retrieval needed here.

---

## `case_id` Scoping Fix

### Problem

`Companion.load()` hardcodes `case_id=None`. When embeddings aren't available and the fallback loads recent messages, it loads cross-case history, which is where the Levasseur contamination came from.

### Fix

In `game.py`, add a helper method:

```python
def _set_active_case(self, case_id: int | None) -> None:
    self.active_case_id = case_id
    if self.companion is not None:
        self.companion.case_id = case_id
```

Replace all `self.active_case_id = <value>` assignments with `self._set_active_case(<value>)` throughout `game.py`.

This ensures the fallback (recency-only, no embeddings) is also case-scoped, not cross-case.

---

## `append_history()` Integration

In `noir/persistence/repository.py`, `append_history()` posts an embed task after INSERT:

```python
def append_history(conn, *, character_id, role, content, case_id=None) -> int:
    cursor = conn.execute(
        "INSERT INTO conversation_history (character_id, role, content, case_id) VALUES (?, ?, ?, ?)",
        (character_id, role, content, case_id)
    )
    conn.commit()
    row_id = cursor.lastrowid
    try:
        import noir.memory as _mem
        _mem.enqueue(row_id, content)
    except Exception:
        pass  # never block on embedding failure
    return row_id
```

`append_history()` currently returns `None` — this changes it to return the `row_id`. Callers that ignore the return value are unaffected.

---

## Startup Sequence

In `game.py` startup (alongside `audio.init()`):

```python
import noir.memory as _memory
_memory.init()
```

Backfill is triggered inside `_memory.init()` as a daemon thread — it runs in the background and the game starts immediately regardless.

At shutdown (alongside `audio.shutdown()`):

```python
_memory.shutdown()
```

---

## `pyproject.toml`

```toml
[project.optional-dependencies]
memory = [
    "sentence-transformers>=2.7",
    "numpy>=1.24",
]
```

Install with: `pip install -e ".[memory]"`

---

## Fallback Behavior Summary

| Condition | Partner history behavior |
|---|---|
| `sentence-transformers` installed, model loaded | Semantic retrieval (top-8) + recency (last-4) |
| `sentence-transformers` not installed | Last 12 messages, case-scoped |
| Model loaded, query embedding fails | Last 12 messages, case-scoped |
| No active case | Last 12 messages, no case filter |

---

## Files Created

- `noir/memory/__init__.py`
- `noir/memory/worker.py`
- `noir/memory/backfill.py`
- `noir/memory/retrieval.py`

## Files Modified

- `noir/persistence/repository.py` — schema migration, `append_history()` posts embed task
- `noir/characters/companion.py` — `_history_with_summaries(query)` override
- `noir/game.py` — `_set_active_case()` helper, startup/shutdown hooks
- `pyproject.toml` — `[memory]` optional dep group
