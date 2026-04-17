import sqlite3
from noir.llm.base import LLMBackend
from noir.persistence.repository import append_history, get_history


class Agent:

    def __init__(self, *, character_id: str, system_prompt: str,
                 llm: LLMBackend, conn: sqlite3.Connection,
                 case_id: int | None = None):
        self.character_id = character_id
        self.system_prompt = system_prompt
        self.llm = llm
        self.conn = conn
        self.case_id = case_id

    def speak(self, player_input: str) -> str:
        history = get_history(self.conn, self.character_id, case_id=self.case_id)
        response = self.llm.query(self.system_prompt, history, player_input)
        append_history(self.conn, character_id=self.character_id,
                       role="user", content=player_input, case_id=self.case_id)
        append_history(self.conn, character_id=self.character_id,
                       role="assistant", content=response, case_id=self.case_id)
        return response
