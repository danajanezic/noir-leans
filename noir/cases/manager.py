import json
import sqlite3
from noir.persistence.repository import (
    add_evidence, get_evidence_for_case, create_arrest,
    update_arrest_verdict, update_player_reputation, update_player_stats, get_case, get_npc
)


class CaseManager:

    def __init__(self, *, conn: sqlite3.Connection, case_id: int):
        self.conn = conn
        self.case_id = case_id

    def collect_evidence(self, *, description: str, location_id: int,
                         source_npc_id: int | None) -> int:
        return add_evidence(self.conn, case_id=self.case_id, description=description,
                            source_npc_id=source_npc_id, location_id=location_id)

    def arrest(self, *, npc_id: int, evidence_summary: str) -> int:
        case = get_case(self.conn, self.case_id)
        case_data = json.loads(case["case_data"])
        killer_name = case_data.get("killer_name", "")
        npc = get_npc(self.conn, npc_id)
        is_correct = npc["name"] == killer_name

        arrest_id = create_arrest(self.conn, case_id=self.case_id, npc_id=npc_id,
                                  evidence_summary=evidence_summary)
        update_arrest_verdict(self.conn, arrest_id=arrest_id, was_correct=is_correct)

        if is_correct:
            update_player_stats(self.conn, cases_solved_delta=1)
        else:
            update_player_reputation(self.conn, delta=-15)
            update_player_stats(self.conn, wrong_arrests_delta=1)

        return arrest_id

    def get_evidence_summary(self) -> str:
        evidence = get_evidence_for_case(self.conn, self.case_id)
        if not evidence:
            return "No evidence collected."
        lines = [f"- {e['description']}" for e in evidence]
        return "\n".join(lines)
