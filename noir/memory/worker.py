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

    def __init__(self, db_path: str, embed_fn: Callable[[str], np.ndarray]) -> None:
        self._db_path = db_path
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
        conn = sqlite3.connect(self._db_path)
        try:
            while True:
                item = self._q.get()
                if item is _STOP:
                    break
                row_id, text = item
                try:
                    vec = self._embed_fn(text)
                    conn.execute(
                        "UPDATE conversation_history SET embedding=? WHERE id=?",
                        (vec.astype(np.float32).tobytes(), row_id)
                    )
                    conn.commit()
                except Exception as e:
                    _log.warning("embedding worker error for row %d: %s", row_id, e)
        finally:
            conn.close()
