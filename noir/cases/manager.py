import json
import sqlite3
from noir.llm.base import LLMBackend
from noir.persistence.repository import (
    add_evidence, get_evidence_for_case, get_clues_for_case, create_arrest,
    update_arrest_verdict, update_player_reputation, update_player_stats, get_case, get_npc
)

_VALIDATE_SYSTEM = (
    "You are matching a player's collect command against a case's actual clue list. "
    "Return ONLY valid JSON: "
    '{"matched": true|false, "clue_description": "exact clue text if matched, else null", '
    '"reason": "one sentence"}'
)


class CaseManager:

    def __init__(self, *, conn: sqlite3.Connection, case_id: int, llm: LLMBackend | None = None):
        self.conn = conn
        self.case_id = case_id
        self.llm = llm

    def collect_evidence(self, *, clue_id: int, location_id: int,
                         source_npc_id: int | None) -> int:
        return add_evidence(self.conn, case_id=self.case_id, clue_id=clue_id,
                            source_npc_id=source_npc_id, location_id=location_id)

    def validate_and_collect(self, *, description: str, location_id: int,
                             source_npc_id: int | None) -> dict:
        """Validate description against case clues, dedup by clue_id, then collect."""
        clues = get_clues_for_case(self.conn, self.case_id)

        if not clues:
            return {"ok": False, "message": "No clues defined for this case."}

        clue_list = "\n".join(
            f"- {c['description']} (location: {c['location'] or '?'})"
            for c in clues
        )
        existing = get_evidence_for_case(self.conn, self.case_id)
        already_collected_ids = {e["clue_id"] for e in existing}

        if self.llm:
            prompt = (
                f"Player wants to collect: \"{description}\"\n\n"
                f"Case clues:\n{clue_list}\n\n"
                "Does the player's description match any clue? "
                "Be generous with wording variations — 'the card', 'business card', 'monogrammed card' "
                "all match 'A monogrammed business card found near the body'. "
                "Only reject if it clearly matches nothing in the list."
            )
            result = self.llm.query_structured(_VALIDATE_SYSTEM, [], prompt)
            canonical = result.get("clue_description") if result.get("matched") else None
        else:
            desc_lower = description.lower()
            matched = next(
                (c for c in clues if any(
                    word in c["description"].lower()
                    for word in desc_lower.split()
                    if len(word) > 3
                )),
                None
            )
            result = {"matched": matched is not None, "reason": "matched" if matched else "no matching clue found"}
            canonical = matched["description"] if matched else None

        if not result.get("matched") or canonical is None:
            return {
                "ok": False,
                "message": f"That doesn't appear to be case evidence. {result.get('reason', '')}",
            }

        matched_clue = next((c for c in clues if c["description"] == canonical), None)
        if matched_clue is None:
            return {"ok": False, "message": "Matched clue not found in case file."}

        if matched_clue["id"] in already_collected_ids:
            return {"ok": False, "message": f"Already collected: {canonical}"}

        add_evidence(self.conn, case_id=self.case_id, clue_id=matched_clue["id"],
                     source_npc_id=source_npc_id, location_id=location_id)
        return {"ok": True, "description": canonical}

    def arrest(self, *, npc_id: int, evidence_summary: str) -> int:
        case = get_case(self.conn, self.case_id)
        case_data = json.loads(case["case_data"])
        killer_name = case_data.get("killer_name", "")
        npc = get_npc(self.conn, npc_id)
        is_correct = npc["name"] == killer_name

        arrest_id = create_arrest(self.conn, case_id=self.case_id, npc_id=npc_id,
                                  evidence_summary=evidence_summary)
        update_arrest_verdict(self.conn, arrest_id=arrest_id, was_correct=is_correct)
        return arrest_id

    def get_arrest(self) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM arrests WHERE case_id=? ORDER BY id DESC LIMIT 1",
            (self.case_id,)
        ).fetchone()

    def get_evidence_summary(self) -> str:
        evidence = get_evidence_for_case(self.conn, self.case_id)
        if not evidence:
            return "No evidence collected."
        lines = [f"- {e['description']}" for e in evidence]
        return "\n".join(lines)
