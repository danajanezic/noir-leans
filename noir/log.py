import logging
from pathlib import Path

_log_dir = Path.home() / ".noir_detective"
_feedback_logger = logging.getLogger("noir.feedback")


def setup_logging() -> None:
    _log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(_log_dir / "game.log")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    # Suppress all third-party noise (markdown_it, rich, etc.) — only our loggers
    logging.getLogger().setLevel(logging.WARNING)
    noir_log = logging.getLogger("noir")
    noir_log.setLevel(logging.DEBUG)
    noir_log.addHandler(handler)
    noir_log.propagate = False


def save_feedback(text: str) -> None:
    _feedback_logger.info("PLAYER FEEDBACK: %s", text)
