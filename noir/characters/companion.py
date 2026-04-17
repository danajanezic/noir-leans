import sqlite3
from noir.llm.base import LLMBackend
from noir.persistence.repository import get_partner
from .agent import Agent


class Companion(Agent):

    def __init__(self, *, name: str, sex: str, personality_archetype: str,
                 speech_style: str, relationship_stance: str, **kwargs):
        super().__init__(**kwargs)
        self.name = name
        self.sex = sex
        self.personality_archetype = personality_archetype
        self.speech_style = speech_style
        self.relationship_stance = relationship_stance

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
