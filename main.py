from noir.log import setup_logging
from noir.persistence.db import get_connection
from noir.llm.config import load_config
from noir.llm.base import LLMBackend
from noir.game import Game


def create_backend(config: dict) -> LLMBackend:
    backend = config.get("backend", "claude_cli")
    if backend == "claude_cli":
        from noir.llm.claude_cli import ClaudeCLIBackend
        return ClaudeCLIBackend(
            dialogue_model=config.get("dialogue_model", "sonnet"),
            structured_model=config.get("structured_model", "haiku"),
        )
    raise ValueError(
        f"Unknown backend '{backend}'. "
        f"Edit ~/.noir_detective/config.json to set a valid backend."
    )


def main():
    setup_logging()
    config = load_config()
    conn = get_connection()
    llm = create_backend(config)
    game = Game(conn=conn, llm=llm)
    game.loop()


if __name__ == "__main__":
    main()
