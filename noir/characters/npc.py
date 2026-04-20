import sqlite3
from noir.llm.base import LLMBackend
from noir.persistence.repository import get_npc, get_player, get_partner, update_npc_location, set_character_location
from noir.onboarding.quiz import alignment_disposition, resolve_alignment
from noir.lore import lore_memories_for_age, is_history_query
from .agent import Agent


def _build_alignment_prefix(player_alignment: str, npc_alignment: str,
                              partner_alignment: str) -> str:
    disposition = alignment_disposition(player_alignment, npc_alignment)
    partner_disposition = alignment_disposition(partner_alignment, npc_alignment)

    if disposition == "aligned":
        disposition_note = "Your values broadly align. You are somewhat more open with them."
    elif disposition == "opposed":
        disposition_note = "Your values conflict fundamentally. You are guarded."
    else:
        return ""

    prefix = f"[Player alignment: {player_alignment}. {disposition_note}"

    if partner_alignment != player_alignment and partner_disposition == "aligned":
        prefix += f" Their partner's alignment: {partner_alignment}. You find the partner more trustworthy. Their presence helps."

    prefix += "]"
    return prefix


class NPC(Agent):

    def __init__(self, *, npc_id: int, name: str, role: str,
                 current_location_id: int, alignment_prefix: str = "",
                 case_memories: list[str] | None = None,
                 background_memories: list[str] | None = None,
                 **kwargs):
        super().__init__(**kwargs)
        self.npc_id = npc_id
        self.name = name
        self.role = role
        self.current_location_id = current_location_id
        self._alignment_prefix = alignment_prefix
        self._case_memories: list[str] = case_memories or []
        self._background_memories: list[str] = background_memories or []

    @property
    def _locked_system_prompt(self) -> str:
        base = super()._locked_system_prompt
        parts = []
        if self._alignment_prefix:
            parts.append(self._alignment_prefix)
        if self._case_memories:
            mem_block = (
                "[Historical events you personally remember:\n "
                + "\n ".join(self._case_memories)
                + "]"
            )
            parts.append(mem_block)
        parts.append(base)
        return "\n\n".join(parts)

    def _query_with_retry(self, prompt: str, history: list[dict]) -> str:
        if self._background_memories and is_history_query(prompt):
            mem_block = (
                "[Historical background you remember, relevant to this question: "
                + " / ".join(self._background_memories)
                + "]"
            )
            prompt = mem_block + "\n\n" + prompt
        return super()._query_with_retry(prompt, history)

    @classmethod
    def load(cls, *, conn: sqlite3.Connection, llm: LLMBackend,
             npc_id: int, case_id: int) -> "NPC":
        row = get_npc(conn, npc_id)
        if row is None:
            raise ValueError(f"NPC {npc_id} not found")

        alignment_prefix = ""
        player = get_player(conn)
        partner = get_partner(conn)
        if player and row["alignment"]:
            player_alignment = resolve_alignment(player["law_chaos"], player["good_evil"])
            partner_alignment = partner["alignment"] if partner and partner["alignment"] else "True Neutral"
            alignment_prefix = _build_alignment_prefix(
                player_alignment, row["alignment"], partner_alignment
            )

        case_memories, background_memories = lore_memories_for_age(row["age"] or 35)

        return cls(
            character_id=f"npc_{npc_id}",
            system_prompt=row["system_prompt"],
            llm=llm,
            conn=conn,
            case_id=case_id,
            npc_id=npc_id,
            name=row["name"],
            role=row["role"],
            current_location_id=row["current_location_id"],
            alignment_prefix=alignment_prefix,
            case_memories=case_memories,
            background_memories=background_memories,
        )

    def move_to(self, location_id: int) -> None:
        self.current_location_id = location_id
        update_npc_location(self.conn, npc_id=self.npc_id, location_id=location_id)
        set_character_location(self.conn, character_id=self.character_id, location_id=location_id)
