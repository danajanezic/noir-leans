import re
from dataclasses import dataclass
from enum import Enum, auto


class Intent(Enum):
    GO = auto()
    GO_DA = auto()
    GO_COURTHOUSE = auto()
    TALK = auto()
    TALK_PARTNER = auto()
    ARREST = auto()
    COLLECT = auto()
    EXAMINE = auto()
    LOOK = auto()
    MAP = auto()
    HELP = auto()
    SHOOT_PARTNER = auto()
    UNKNOWN = auto()


@dataclass
class Command:
    intent: Intent
    target: str = ""
    raw: str = ""


_LETS = r"(?:let(?:'s| us) )?"
_GO_WORDS = rf"(?:{_LETS}(?:go to|head to|head over to|visit|walk to|travel to|start at|start with|make our way to)|go)"
_TALK_WORDS = r"(?:talk to|speak (?:to|with)|ask|chat with|question|interrogate)"
_COLLECT_WORDS = r"(?:pick up|take|grab|collect|pocket)"
_EXAMINE_WORDS = r"(?:examine|look at|inspect|check|study|scrutinize)"
_LOOK_WORDS = r"(?:look around|where am i|what do i see|look|survey)"
_ARREST_WORDS = r"(?:arrest|collar|nab|apprehend|bust)"

_PARTNER_WORDS = r"(?:my partner|partner|the partner)"

_DA_WORDS = r"(?:the da|district attorney|da's office|da)"
_COURTHOUSE_WORDS = r"(?:the courthouse|courthouse|the court|court)"

_RULES: list[tuple[str, Intent, int]] = [
    (rf"^{_GO_WORDS}\s+{_DA_WORDS}\b", Intent.GO_DA, 0),
    (rf"^{_GO_WORDS}\s+{_COURTHOUSE_WORDS}\b", Intent.GO_COURTHOUSE, 0),
    (rf"^{_TALK_WORDS}\s+{_PARTNER_WORDS}\b", Intent.TALK_PARTNER, 0),
    (r"^ask\s+(\w+(?:\s+\w+)?)\s+about\b", Intent.TALK, 1),
    (rf"^{_TALK_WORDS}\s+(.+)$", Intent.TALK, 1),
    (rf"^{_ARREST_WORDS}\s+(.+)$", Intent.ARREST, 1),
    (rf"^{_COLLECT_WORDS}\s+(.+)$", Intent.COLLECT, 1),
    (rf"^{_EXAMINE_WORDS}\s+(.+)$", Intent.EXAMINE, 1),
    (rf"^{_GO_WORDS}\s+(.+)$", Intent.GO, 1),
    (rf"^{_LOOK_WORDS}$", Intent.LOOK, 0),
    (r"^/map$", Intent.MAP, 0),
    (r"^(?:shoot|kill|murder|shoot|gun down|put a bullet in|fire at)\s+(?:my partner|partner|riley|the partner|\w+)$", Intent.SHOOT_PARTNER, 0),
    (r"^help\b", Intent.HELP, 0),
]


def parse_command(raw: str) -> Command:
    text = raw.strip()
    text_lower = text.lower()
    for pattern, intent, group in _RULES:
        m = re.match(pattern, text_lower, re.IGNORECASE)
        if m:
            # Extract target from the original text (not lowercased) if group is specified
            target = ""
            if group:
                # Re-match on original text to get proper casing
                m_orig = re.match(pattern, text, re.IGNORECASE)
                if m_orig:
                    target = m_orig.group(group)
            return Command(intent=intent, target=target.strip(), raw=raw)
    return Command(intent=Intent.UNKNOWN, raw=raw)
