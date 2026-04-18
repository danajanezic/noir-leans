import sqlite3
from noir.llm.base import LLMBackend
from noir.persistence.repository import get_partner
from .agent import Agent


DARK_PAST_SYSTEM_PROMPT = """You are generating a partner's dark past confession for an absurdist noir detective game set in Noirleans, 1935. The confession is written in the partner's voice — first person, in their speech style. It describes something terrible they did or were part of: a crime committed, a death they caused or enabled, an injustice they participated in. It should be morally complex, not cartoonishly evil. It should feel like something a real person would carry for years. It must connect to the provided theme. 2-3 paragraphs. Return ONLY valid JSON: {"backstory": "string (the confession in the partner's voice)", "crime_summary": "string (one sentence describing what they did, third person)"}"""


class Companion(Agent):

    def __init__(self, *, name: str, sex: str, personality_archetype: str,
                 speech_style: str, relationship_stance: str, **kwargs):
        super().__init__(**kwargs)
        self.name = name
        self.sex = sex
        self.personality_archetype = personality_archetype
        self.speech_style = speech_style
        self.relationship_stance = relationship_stance

    def generate_dark_past(self, theme: str) -> dict:
        prompt = (
            f"Partner name: {self.name}. "
            f"Personality: {self.personality_archetype}. "
            f"Speech style: {self.speech_style}. "
            f"Theme to weave in: {theme}. "
            "Generate the dark past confession."
        )
        return self.llm.query_structured(DARK_PAST_SYSTEM_PROMPT, [], prompt)

    @classmethod
    def load(cls, *, conn: sqlite3.Connection, llm: LLMBackend) -> "Companion":
        row = get_partner(conn)
        if row is None:
            raise ValueError("No partner found in database. Run onboarding first.")
        return cls(
            character_id="partner",
            system_prompt=row["system_prompt"],
            llm=llm,
            conn=conn,
            case_id=None,
            name=row["name"],
            sex=row["sex"],
            personality_archetype=row["personality_archetype"],
            speech_style=row["speech_style"],
            relationship_stance=row["relationship_stance"],
        )
