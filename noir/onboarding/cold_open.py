from noir.llm.base import LLMBackend

INCIDENT_SYSTEM_PROMPT = """You are generating the opening incident for an absurdist noir detective game set in Noirleans, 1935. The Great Depression is in full swing — everyone's broke, everyone's desperate, and the city smells like rain and bad decisions.
The player's detective woke up with amnesia after combining alcohol with a bizarre incident at a bar.

The incident text will be inserted into this exact sentence: "last night you ___"
So write it to complete that sentence naturally — starting with a past-tense verb, self-contained,
no dangling comparisons, no "and you" or "but you" continuations.

Example good outputs: "bet a flamingo on a card game and lost both"
Example bad outputs: "you tried to arm-wrestle someone" (starts with 'you') or "and then things got worse" (starts with 'and')

2-3 sentences max. Absurd but coherent. Memorable.

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
