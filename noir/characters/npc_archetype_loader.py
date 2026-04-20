import json
from pathlib import Path
from functools import lru_cache

_PATH = Path(__file__).parent / "npc_archetypes.json"


@lru_cache(maxsize=None)
def load_npc_archetypes() -> tuple[dict, ...]:
    return tuple(json.loads(_PATH.read_text()))


def get_npc_archetype(archetype_id: str) -> dict | None:
    for a in load_npc_archetypes():
        if a["id"] == archetype_id:
            return a
    return None


def archetype_ids() -> list[str]:
    return [a["id"] for a in load_npc_archetypes()]
