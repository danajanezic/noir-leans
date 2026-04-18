import sqlite3
from noir.llm.base import LLMBackend
from noir.persistence.repository import get_partner, get_history, append_history
from .agent import Agent

_INTERPRET_SUFFIX = """

You must respond ONLY with valid JSON in this exact format — no prose, no markdown:
{
  "dialogue": "your in-character response (1-3 sentences, stay in character)",
  "action": "GO" | "EXAMINE" | "COLLECT" | "TALK" | null,
  "target": "exact name of location / thing / NPC" | null,
  "moved_npc": "exact NPC name if your dialogue narratively brings them to the new location" | null
}

Set action+target when the player is clearly trying to go somewhere, examine something, pick something up, or talk to someone. Otherwise both must be null.
Set moved_npc only when action is GO and your dialogue explicitly moves an NPC with you (e.g. "Let's take Fredrick to Solomon's"). Otherwise null.

Dialogue clarity rules:
- Make one point at a time. Do not chain multiple deductions in a single response.
- Name the observable evidence before stating the conclusion. ("The scratches are methodical, not frenzied — that's patience, not rage.")
- Complete every sentence. Never trail off mid-thought."""


class Companion(Agent):

    def __init__(self, *, name: str, sex: str, personality_archetype: str,
                 speech_style: str, relationship_stance: str, **kwargs):
        super().__init__(**kwargs)
        self.name = name
        self.sex = sex
        self.personality_archetype = personality_archetype
        self.speech_style = speech_style
        self.relationship_stance = relationship_stance

    def interpret(self, player_input: str) -> dict:
        """Respond in character AND return a game action to dispatch."""
        interpret_system = self.system_prompt + _INTERPRET_SUFFIX
        history = get_history(self.conn, character_id=self.character_id, case_id=self.case_id)
        result = self.llm.query_structured(interpret_system, history, player_input)
        dialogue = result.get("dialogue", "")
        append_history(self.conn, character_id=self.character_id,
                       role="user", content=player_input, case_id=self.case_id)
        append_history(self.conn, character_id=self.character_id,
                       role="assistant", content=dialogue, case_id=self.case_id)
        return result

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
