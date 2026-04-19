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
When action is GO, target MUST be the exact location name from the "Known locations" list in your context — never a paraphrase, direction, or invented name.
Set moved_npc only when action is GO and your dialogue explicitly moves an NPC with you (e.g. "Let's take Fredrick to Solomon's"). Otherwise null.

Dialogue clarity rules:
- Make one point at a time.
- Describe what you observe or feel; do not state logical conclusions as fact. Wonder aloud, don't deduce.
- Complete every sentence. Never trail off mid-thought."""


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

    def interpret(self, player_input: str) -> dict:
        """Respond in character AND return a game action to dispatch."""
        interpret_system = self._locked_system_prompt + _INTERPRET_SUFFIX
        history = get_history(self.conn, character_id=self.character_id, case_id=self.case_id)
        result = self.llm.query_structured(interpret_system, history, player_input)
        dialogue = result.get("dialogue", "")
        append_history(self.conn, character_id=self.character_id,
                       role="user", content=player_input, case_id=self.case_id)
        append_history(self.conn, character_id=self.character_id,
                       role="assistant", content=dialogue, case_id=self.case_id)
        return result

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
