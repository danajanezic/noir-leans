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

    contents = [{"id": r["id"], "role": r["role"], "content": r["content"]} for r in rows]
    matrix = np.stack([
        np.frombuffer(r["embedding"], dtype=np.float32) for r in rows
    ])

    query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-10)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10
    scores = matrix / norms @ query_norm

    top_k_indices = set(np.argsort(scores)[-k:].tolist())
    recency_indices = set(range(max(0, len(rows) - recency), len(rows)))

    selected = sorted(top_k_indices | recency_indices)
    return [{"role": contents[i]["role"], "content": contents[i]["content"]} for i in selected]
