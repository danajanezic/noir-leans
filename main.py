from noir.persistence.db import get_connection
from noir.llm.claude_cli import ClaudeCLIBackend
from noir.game import Game


def main():
    conn = get_connection()
    llm = ClaudeCLIBackend()
    game = Game(conn=conn, llm=llm)
    game.loop()


if __name__ == "__main__":
    main()
