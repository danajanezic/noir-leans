import sqlite3
from noir.llm.base import LLMBackend
from noir.persistence.repository import get_npc, update_npc_location, set_character_location
from .agent import Agent


class NPC(Agent):

    def __init__(self, *, npc_id: int, name: str, role: str,
                 current_location_id: int, **kwargs):
        super().__init__(**kwargs)
        self.npc_id = npc_id
        self.name = name
        self.role = role
        self.current_location_id = current_location_id

    @classmethod
    def load(cls, *, conn: sqlite3.Connection, llm: LLMBackend,
             npc_id: int, case_id: int) -> "NPC":
        row = get_npc(conn, npc_id)
        if row is None:
            raise ValueError(f"NPC {npc_id} not found")
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
        )

    def move_to(self, location_id: int) -> None:
        self.current_location_id = location_id
        update_npc_location(self.conn, npc_id=self.npc_id, location_id=location_id)
        set_character_location(self.conn, character_id=self.character_id, location_id=location_id)
