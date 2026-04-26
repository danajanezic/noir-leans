import sqlite3
from noir.llm.base import LLMBackend
from noir.persistence.repository import (
    get_partner, get_history, append_history,
    get_conversation_summaries, save_conversation_summary,
    get_latest_npc_opinion, get_partner_relationship, save_partner_relationship,
)
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
- Complete every sentence. Never trail off mid-thought.
- NEVER state where an NPC is or isn't — NPC location facts are context for your awareness only, not your dialogue."""


DARK_PAST_SYSTEM_PROMPT = """You are generating a partner's dark past confession for an absurdist noir detective game set in Noirleans, 1935. The confession is written in the partner's voice — first person, in their speech style. It describes something terrible they did or were part of: a crime committed, a death they caused or enabled, an injustice they participated in. It should be morally complex, not cartoonishly evil. It should feel like something a real person would carry for years. It must connect to the provided theme. 2-3 paragraphs. Return ONLY valid JSON: {"backstory": "string (the confession in the partner's voice)", "crime_summary": "string (one sentence describing what they did, third person)"}"""

_COMPANION_SUMMARY_SYSTEM = (
    "You are processing a conversation between a detective and their partner in a 1935 noir game. "
    "CRITICAL: Only reference characters by name if they appear in the conversation transcript. "
    "Do not invent names for unnamed officials, coroners, doctors, clerks, or any other person. "
    "If a character had no name in the conversation, refer to them by role only ('the coroner', 'the doctor'). "
    "Return ONLY valid JSON with five fields:\n"
    "\"summary\": 2-4 sentences covering investigation facts discussed, leads followed, case progress. Factual and specific.\n"
    "\"npc_opinion\": null\n"
    "\"affection_delta\": an integer from -5 to 10 representing how this conversation moved the relationship. "
    "Positive means warmer. Negative means colder. Most conversations: 0-3. "
    "Significant emotional moments: 8-10. Real damage: negative.\n"
    "\"xp_awards\": an object with keys 'authority', 'streetwise', 'empathy', 'cunning' — "
    "integer XP (0-10) for each root based on what the detective actually did in this conversation.\n"
    "\"relationship_update\": a rewrite of the partner's private feelings about this detective. "
    "You will be given the current relationship notes — update them based on this conversation. "
    "Write in the partner's voice: her private thoughts, what she's noticed, what she feels, "
    "what she trusts or doubts, how her read of this person is changing. "
    "3-6 sentences. This replaces the old record entirely — carry forward what still holds, "
    "revise what has changed, add what is new."
)


class Companion(Agent):

    def __init__(self, *, name: str, sex: str, personality_archetype: str,
                 speech_style: str, relationship_stance: str, **kwargs):
        super().__init__(**kwargs)
        self.name = name
        self.sex = sex
        self.personality_archetype = personality_archetype
        self.speech_style = speech_style
        self.relationship_stance = relationship_stance

    @property
    def _SUMMARY_SYSTEM(self) -> str:
        return _COMPANION_SUMMARY_SYSTEM

    def _history_with_summaries(self, query: str = "") -> list[dict]:
        import noir.memory as _mem
        from noir.memory.retrieval import retrieve_relevant_history

        history = []
        if query and _mem.is_available():
            history = retrieve_relevant_history(
                self.conn,
                character_id=self.character_id,
                query=query,
                k=8,
                recency=4,
            )
        if not history:
            all_history = get_history(self.conn, character_id=self.character_id, case_id=self.case_id)
            history = all_history[-12:]

        case_summaries = get_conversation_summaries(
            self.conn, character_id=self.character_id, case_id=self.case_id
        ) if self.case_id else []
        relationship = get_partner_relationship(self.conn)

        parts = []
        if case_summaries:
            parts.append("This case so far (summarized):\n" + "\n---\n".join(case_summaries))
        if relationship:
            parts.append(f"Your private feelings about this detective: {relationship}")

        if not parts:
            return history
        memory_block = "\n\n".join(parts)
        prefix = [
            {"role": "user", "content": f"[Memory: {memory_block}]"},
            {"role": "assistant", "content": "Understood — I'll carry that forward."},
        ]
        return prefix + history

    def speak(self, player_input: str, record: bool = True, store_as: str | None = None, *, query: str | None = None) -> str:
        history = self._history_with_summaries(query=query if query is not None else player_input)
        response = self._query_with_retry(player_input, history)
        if record:
            append_history(self.conn, character_id=self.character_id,
                           role="user", content=store_as if store_as is not None else player_input,
                           case_id=self.case_id)
            append_history(self.conn, character_id=self.character_id,
                           role="assistant", content=response, case_id=self.case_id)
        return response

    def summarize_and_save(self, history: list[dict], persist: bool = True) -> dict:
        """Summarize conversation, update relationship record. Returns {affection_delta, xp_awards}."""
        if len(history) < 2:
            return {"affection_delta": 0, "xp_awards": {}}

        relationship = get_partner_relationship(self.conn)
        transcript = "\n".join(
            f"{'Detective' if m['role'] == 'user' else 'Partner'}: {m['content']}"
            for m in history
        )
        if relationship:
            transcript = f"[Current relationship notes: {relationship}]\n\n" + transcript

        result = self.llm.query_structured(self._SUMMARY_SYSTEM, [], transcript)
        summary = result.get("summary", "").strip()
        try:
            affection_delta = int(result.get("affection_delta", 0))
            affection_delta = max(-5, min(10, affection_delta))
        except (TypeError, ValueError):
            affection_delta = 0
        xp_awards = {}
        raw_xp = result.get("xp_awards", {})
        if isinstance(raw_xp, dict):
            for root in ("authority", "streetwise", "empathy", "cunning"):
                try:
                    xp_awards[root] = max(0, min(10, int(raw_xp.get(root, 0))))
                except (TypeError, ValueError):
                    xp_awards[root] = 0
        new_relationship = result.get("relationship_update", "").strip()

        if persist:
            if summary:
                save_conversation_summary(
                    self.conn, character_id=self.character_id,
                    summary=summary, npc_opinion=None, case_id=self.case_id
                )
            if new_relationship:
                save_partner_relationship(self.conn, new_relationship)

        return {"affection_delta": affection_delta, "xp_awards": xp_awards}

    def interpret(self, player_input: str) -> dict:
        """Respond in character AND return a game action to dispatch."""
        interpret_system = self._locked_system_prompt + _INTERPRET_SUFFIX
        history = self._history_with_summaries(query=player_input)
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
