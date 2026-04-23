from noir.llm.base import LLMBackend

INCIDENT_SYSTEM_PROMPT = """You are generating the opening amnesia incident for a noir detective game set in Noirleans, 1935.

The text will complete this exact sentence: "last night you ___"
Start with a past-tense verb. One incident, one clause. No lists. No "and you woke up" continuations.

The incident must be:
- Grounded in the world of 1930s Noirleans: speakeasies, jazz joints, card games, bookies, bootleg liquor, hustlers, gamblers, crooked cops, debt collectors, showgirls, dockworkers, back-room deals, political machines, church socials gone wrong
- Plausible for this city and this era — not necessarily funny, but specific and telling
- The kind of thing that reveals something about who this detective is and what city they live in
- One sentence. Short. Punchy.

Good: "lost the deed to a tugboat in a poker game with a man who insisted he was his own twin brother"
Good: "took a job delivering an envelope to the wrong address and spent four hours in an alderman's office explaining yourself to a man who already knew everything"
Good: "were the only witness to something you have no memory of, which three separate people confirmed this morning without being asked"
Good: "sat with a dying longshoreman until two in the morning because he asked you to and you didn't have anywhere better to be"

Bad: "agreed to protect a flamingo in a trench coat from government agents" (surreal, makes no sense)
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
            "Generate a unique incident from last night that caused the detective's amnesia."
        )
        import re
        incident = result.get("incident", "Something happened at the bar. Something memorable. It's gone now.")
        incident = re.sub(r'^you\s+', '', incident, flags=re.IGNORECASE)
        incident = re.sub(r'^(and|but|so|then)\s+', '', incident, flags=re.IGNORECASE)
        if incident:
            incident = incident[0].lower() + incident[1:]
        return incident
