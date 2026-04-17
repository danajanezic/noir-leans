from noir.llm.base import LLMBackend

INCIDENT_SYSTEM_PROMPT = """You are generating the opening incident for an absurdist noir detective game.
The player's detective woke up with amnesia after combining alcohol with a bizarre incident at a bar.
Generate a short, hilarious description of what happened — 2-3 sentences, completely absurd,
vaguely plausible within a noir setting, and memorable enough that the partner can reference it
throughout the game.

Return ONLY valid JSON: {"incident": "string (the incident description)"}"""


class ColdOpen:

    def __init__(self, *, llm: LLMBackend):
        self.llm = llm

    def generate_bar_incident(self) -> str:
        result = self.llm.query_structured(
            INCIDENT_SYSTEM_PROMPT,
            [],
            "Generate a unique, absurd bar incident that caused the detective's amnesia."
        )
        return result.get("incident", "Something happened at the bar. Something memorable. It's gone now.")
