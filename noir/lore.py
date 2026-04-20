import functools
import json
import re
from pathlib import Path

_LORE_PATH = Path(__file__).parent / "data" / "world_lore.json"

_HISTORY_KEYWORDS = {
    "remember", "recall", "back then", "used to", "grew up",
    "young", "history", "when did", "around for",
    "1917", "1919", "1928", "1929", "1932", "1933",
    "prohibition", "crash", "depression", "strike", "howie",
    "red light", "war"
}


@functools.lru_cache(maxsize=None)
def _load_lore() -> dict:
    return json.loads(_LORE_PATH.read_text())


def lore_memories_for_age(age: int) -> tuple[list[str], list[str]]:
    """Return (case_hook_memories, background_memories).

    Each list contains strings formatted as "{year} — {summary}".
    An event is included if the NPC was at least 12 years old when it occurred.
    """
    birth_year = 1935 - age
    data = _load_lore()
    case_hooks: list[str] = []
    background: list[str] = []
    for event in data.get("events", []):
        event_year = event["start"]["year"]
        if event_year - birth_year < 12:
            continue
        memory = f"{event_year} — {event['summary']}"
        if event.get("case_hook"):
            case_hooks.append(memory)
        else:
            background.append(memory)
    return case_hooks, background


def is_history_query(text: str) -> bool:
    lower = text.lower()
    return any(re.search(r'\b' + re.escape(kw) + r'\b', lower) for kw in _HISTORY_KEYWORDS)
