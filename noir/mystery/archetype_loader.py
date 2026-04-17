import json
import sqlite3
from pathlib import Path
from noir.persistence.repository import save_archetype

_ARCHETYPES_PATH = Path(__file__).parent / "archetypes.json"


def load_archetypes() -> list[dict]:
    return json.loads(_ARCHETYPES_PATH.read_text())


def seed_archetypes_to_db(conn: sqlite3.Connection) -> None:
    for archetype in load_archetypes():
        save_archetype(conn, name=archetype["name"],
                       description=archetype["description"],
                       seed_prompt=archetype["seed_prompt"])
