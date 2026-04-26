import logging
import sqlite3

_log = logging.getLogger(__name__)

_no_embeddings: bool = False
_model = None       # SentenceTransformer instance
_worker = None      # EmbeddingQueueWorker instance

MODEL_NAME = "all-MiniLM-L6-v2"


def init(db_path: str, *, no_embeddings: bool = False) -> None:
    global _no_embeddings, _model, _worker
    if _model is not None or _no_embeddings:
        return
    if no_embeddings:
        _no_embeddings = True
        return
    try:
        from sentence_transformers import SentenceTransformer
        from noir.memory.worker import EmbeddingQueueWorker
        _model = SentenceTransformer(MODEL_NAME)
        _worker = EmbeddingQueueWorker(db_path=db_path, embed_fn=_encode)
        _schedule_backfill(db_path)
    except Exception as e:
        _log.warning("memory init failed, running without embeddings: %s", e)
        _no_embeddings = True


def shutdown() -> None:
    global _worker, _model, _no_embeddings
    if _worker is not None:
        _worker.shutdown()
        _worker = None
    _model = None
    _no_embeddings = False


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
    return not _no_embeddings and _model is not None and _worker is not None


def _encode(text: str):
    return _model.encode(text, convert_to_numpy=True)


def _schedule_backfill(db_path: str) -> None:
    import threading

    def _run():
        try:
            from noir.memory.backfill import run_backfill
            import sqlite3 as _sqlite3
            conn = _sqlite3.connect(db_path)
            conn.row_factory = _sqlite3.Row
            try:
                run_backfill(conn)
            finally:
                conn.close()
        except Exception as e:
            _log.warning("backfill failed: %s", e)

    t = threading.Thread(target=_run, daemon=True, name="embedding-backfill")
    t.start()
