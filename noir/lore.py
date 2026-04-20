import json
from pathlib import Path

_LORE_PATH = Path(__file__).parent / "data" / "world_lore.json"

_HISTORY_KEYWORDS = {
    "remember", "recall", "back then", "before", "used to", "grew up",
    "young", "history", "past", "what happened", "when did", "around for",
    "1917", "1919", "1928", "1929", "1932", "1933",
    "prohibition", "crash", "depression", "strike", "howie", "short",
    "red light", "war", "district"
}


def lore_memories_for_age(age: int) -> tuple[list[str], list[str]]:
    """Return (case_hook_memories, background_memories).

    Each list contains strings formatted as "{year} — {summary}".
    An event is included if the NPC was at least 12 years old when it occurred.
    """
    birth_year = 1935 - age
    data = json.loads(_LORE_PATH.read_text())
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
    return any(kw in lower for kw in _HISTORY_KEYWORDS)
