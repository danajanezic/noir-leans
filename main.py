import sys
import atexit
try:
    import readline
    from pathlib import Path
    _HIST = Path.home() / ".noir_detective" / "history"
    _HIST.parent.mkdir(parents=True, exist_ok=True)
    if _HIST.exists():
        readline.read_history_file(str(_HIST))
    readline.set_history_length(500)
    atexit.register(readline.write_history_file, str(_HIST))
except ImportError:
    pass
from noir.log import setup_logging
from noir.persistence.db import get_connection
from noir.llm.config import load_config
from noir.llm.base import LLMBackend
from noir.game import Game


def _maybe_enable_hot_reload() -> None:
    if "--dev" not in sys.argv:
        return
    try:
        import jurigged
        jurigged.watch("noir/", logger=lambda *_, **__: None)
        print("[dev] Hot-reload active — save any file in noir/ to patch it live.")
    except ImportError:
        print("[dev] Install jurigged for hot-reload: pip install jurigged")
        sys.exit(1)


def create_backend(config: dict) -> LLMBackend:
    backend = config.get("backend", "claude_cli")
    if backend == "claude_cli":
        from noir.llm.claude_cli import ClaudeCLIBackend
        return ClaudeCLIBackend(
            dialogue_model=config.get("dialogue_model", "sonnet"),
            structured_model=config.get("structured_model", "haiku"),
        )
    if backend == "ollama":
        from noir.llm.ollama import OllamaBackend
        return OllamaBackend(
            model=config.get("model", "qwen2.5:14b"),
            host=config.get("host", "http://localhost:11434"),
        )
    raise ValueError(
        f"Unknown backend '{backend}'. "
        f"Edit ~/.noir_detective/config.json to set a valid backend."
    )


def _maybe_wipe_db() -> None:
    if "--reset" not in sys.argv:
        return
    from noir.persistence.db import DB_PATH
    confirm = input("Wipe the database and start over? This cannot be undone. (yes/no): ").strip().lower()
    if confirm == "yes":
        if DB_PATH.exists():
            DB_PATH.unlink()
        print("Database wiped.")
    else:
        print("Cancelled.")
        sys.exit(0)


def main():
    _maybe_wipe_db()
    _maybe_enable_hot_reload()
    setup_logging()
    config = load_config()
    conn = get_connection()
    llm = create_backend(config)

    import noir.audio as audio
    audio.init(no_audio="--no-audio" in sys.argv)

    game = Game(conn=conn, llm=llm)
    try:
        game.loop()
    finally:
        audio.shutdown()


if __name__ == "__main__":
    main()
