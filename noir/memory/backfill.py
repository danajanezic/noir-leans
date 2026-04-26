import logging
import sqlite3

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
