from noir.llm.base import LLMBackend

INCIDENT_SYSTEM_PROMPT = """You are generating the opening amnesia incident for a noir detective game set in Noirleans, 1935.

The text will complete this exact sentence: "last night you ___"
Start with a past-tense verb. One incident, one clause. No lists. No "and you woke up" continuations.

The incident must be:
- Grounded in the world of 1930s Noirleans: speakeasies, jazz joints, card games, bookies, bootleg liquor, hustlers, gamblers, crooked cops, debt collectors, showgirls, back-room deals
- Strange but internally logical — the kind of thing that could actually happen to a hard-drinking detective in a corrupt city
- Funny in a dry, noir way — not surreal, not random, not absurdist for its own sake
- One sentence. Short. Punchy.

Good: "lost the deed to a tugboat in a poker game with a man who insisted he was his own twin brother"
Good: "were named temporary mayor of a floating speakeasy by a unanimous vote of four people, one of whom was a parrot"
Good: "accepted a commission to find a missing accordion and got as far as the waterfront before the accordion found you first"

Bad: "agreed to protect a flamingo in a trench coat from government agents" (surreal, anachronistic, makes no sense)
Bad: "woke up with a mysterious key" (not an incident, just a thing)
Bad: "tried to solve a crime" (too generic)

Return ONLY valid JSON: {"incident": "string"}"""


class ColdOpen:

    def __init__(self, *, llm: LLMBackend):
        self.llm = llm

    def generate_bar_incident(self) -> str:
        result = self.llm.query_structured(
            INCIDENT_SYSTEM_PROMPT,
            [],
            "Generate a unique, absurd bar incident that caused the detective's amnesia."
        )
        import re
        incident = result.get("incident", "Something happened at the bar. Something memorable. It's gone now.")
        incident = re.sub(r'^you\s+', '', incident, flags=re.IGNORECASE)
        incident = re.sub(r'^(and|but|so|then)\s+', '', incident, flags=re.IGNORECASE)
        if incident:
            incident = incident[0].lower() + incident[1:]
        return incident
