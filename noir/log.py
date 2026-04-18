import logging
from pathlib import Path

_log_dir = Path.home() / ".noir_detective"
_feedback_logger = logging.getLogger("noir.feedback")


def setup_logging() -> None:
    _log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=_log_dir / "game.log",
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def save_feedback(text: str) -> None:
    _feedback_logger.info("PLAYER FEEDBACK: %s", text)
