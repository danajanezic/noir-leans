import json
import sqlite3
from noir.llm.base import LLMBackend
from noir.persistence.repository import (
    add_evidence, get_evidence_for_case, get_clues_for_case, create_arrest,
    update_arrest_verdict, update_player_reputation, update_player_stats, get_case, get_npc,
    get_suspect_by_npc, get_history, create_clue, get_npcs_for_case, get_all_dossier,
    get_location,
)

_ADMISSIBILITY_SYSTEM = (
    "You are an evidence admissibility evaluator for a 1935 noir detective game. "
    "The detective wants to record something as evidence. "
    "Your job: could the detective plausibly know this based on what they have actually learned? "
    "Accept if the claim is supported by or reasonably inferable from dossier facts or case context. "
    "Accept implicit confirmations — if the detective accused someone and the NPC responded without denying it, that is admissible. "
    "Reject pure speculation with no basis in what was actually learned. "
    "Be generous with wording but honest about whether there is a real foundation. "
    "Return ONLY valid JSON: "
    '{"admissible": true|false, '
    '"evidence_text": "canonical one-sentence version of the evidence as it would appear in the file, or null", '
    '"reason": "one short in-character sentence a detective\'s partner might say — terse, noir voice"}'
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
        """Evaluate admissibility using dossier + case context, then collect."""
        clues = get_clues_for_case(self.conn, self.case_id)
        existing = get_evidence_for_case(self.conn, self.case_id)
        already_collected_ids = {e["clue_id"] for e in existing}
        already_collected_descs = {e["description"] for e in existing}

        # Fast path: exact/fuzzy match against pre-generated clues
        if clues:
            desc_lower = description.lower()
            matched_clue = None
            if self.llm:
                clue_list = "\n".join(f"- id={c['id']}: {c['description']}" for c in clues)
                fp_result = self.llm.query_structured(
                    "Match a player's collect command against a case clue list. "
                    "Be generous with wording variations. "
                    "Return ONLY valid JSON: "
                    '{"matched": true|false, "clue_id": integer|null}',
                    [],
                    f"Player wants to collect: \"{description}\"\n\nClues:\n{clue_list}"
                )
                if fp_result.get("matched") and fp_result.get("clue_id"):
                    matched_clue = next(
                        (c for c in clues if c["id"] == fp_result["clue_id"]), None
                    )
            else:
                matched_clue = next(
                    (c for c in clues if any(
                        word in c["description"].lower()
                        for word in desc_lower.split() if len(word) > 3
                    )), None
                )
            if matched_clue:
                if matched_clue["id"] in already_collected_ids:
                    return {"ok": False, "message": f"Already collected: {matched_clue['description']}"}
                if matched_clue["location"] and location_id and not source_npc_id:
                    current_loc = get_location(self.conn, location_id)
                    if current_loc and current_loc["name"].lower() != matched_clue["location"].lower():
                        return {
                            "ok": False,
                            "message": "Nothing here matches that.",
                            "reason": "not at location",
                        }
                add_evidence(self.conn, case_id=self.case_id, clue_id=matched_clue["id"],
                             source_npc_id=source_npc_id, location_id=location_id)
                return {"ok": True, "description": matched_clue["description"]}

        if not self.llm:
            return {"ok": False, "message": "No matching evidence found.", "reason": ""}

        # Admissibility evaluation: build dossier + case context
        case = get_case(self.conn, self.case_id)
        case_data = json.loads(case["case_data"]) if case else {}
        victim = case_data.get("victim", {})
        suspects = case_data.get("suspects", [])
        case_summary = (
            f"Case: {case['title'] if case else '?'}\n"
            f"Victim: {victim.get('name', '?')}, cause of death: {victim.get('cause_of_death', '?')}\n"
            f"Suspects: {', '.join(s['name'] for s in suspects)}"
        )

        dossier_dict = get_all_dossier(self.conn, case_id=self.case_id)
        dossier_lines = []
        for npc_name, facts in dossier_dict.items():
            for fact in facts:
                dossier_lines.append(f"- {npc_name}: {fact}")
        dossier_text = "\n".join(dossier_lines) or "None yet."

        existing_ev = "\n".join(f"- {e['description']}" for e in existing) or "None yet."

        # Also include NPC conversation excerpt if source_npc_id is known or can be inferred
        npc_excerpt = ""
        if not source_npc_id:
            desc_lower = description.lower()
            npcs = get_npcs_for_case(self.conn, self.case_id)
            desc_words = [w.strip("'s.,") for w in desc_lower.split() if len(w) > 2]
            matched_npc = next(
                (n for n in npcs if
                 n["name"].lower() in desc_lower or
                 any(n["name"].lower().startswith(w) for w in desc_words) or
                 any(w in n["name"].lower() for w in desc_words)),
                None
            )
            if matched_npc:
                source_npc_id = matched_npc["id"]
        if source_npc_id:
            npc = get_npc(self.conn, source_npc_id)
            npc_name = npc["name"] if npc else "NPC"
            history = get_history(self.conn, character_id=f"npc_{source_npc_id}",
                                  case_id=self.case_id)
            if history:
                npc_excerpt = "\nRecent conversation with " + npc_name + ":\n" + "\n".join(
                    f"{'Detective' if m['role'] == 'user' else npc_name}: {m['content']}"
                    for m in history[-10:]
                )

        prompt = (
            f"Detective wants to record as evidence: \"{description}\"\n\n"
            f"{case_summary}\n\n"
            f"What the detective has learned (dossier):\n{dossier_text}\n\n"
            f"Already collected evidence:\n{existing_ev}"
            f"{npc_excerpt}\n\n"
            "Is this admissible? Could the detective plausibly know this based on what they have learned?"
        )
        result = self.llm.query_structured(_ADMISSIBILITY_SYSTEM, [], prompt)

        if not result.get("admissible"):
            reason = result.get("reason", "")
            return {
                "ok": False,
                "message": reason or "That doesn't hold up as evidence.",
                "reason": reason,
            }

        evidence_text = result.get("evidence_text") or description
        if evidence_text in already_collected_descs:
            return {"ok": False, "message": f"Already collected: {evidence_text}"}

        clue_id = create_clue(self.conn, case_id=self.case_id,
                              description=evidence_text,
                              location=None, is_red_herring=False)
        add_evidence(self.conn, case_id=self.case_id, clue_id=clue_id,
                     source_npc_id=source_npc_id, location_id=location_id)
        return {"ok": True, "description": evidence_text}


    def arrest(self, *, npc_id: int, evidence_summary: str) -> int:
        suspect_row = get_suspect_by_npc(self.conn, npc_id)
        if suspect_row is not None:
            is_correct = bool(suspect_row["is_killer"])
        else:
            # fallback for old cases without suspects table rows
            case = get_case(self.conn, self.case_id)
            case_data = json.loads(case["case_data"])
            npc = get_npc(self.conn, npc_id)
            is_correct = npc["name"] == case_data.get("killer_name", "")

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
        linked: dict[str, list[str]] = {}
        unlinked: list[str] = []
        for e in evidence:
            if e["accused_npc_name"]:
                linked.setdefault(e["accused_npc_name"], []).append(e["description"])
            else:
                unlinked.append(e["description"])
        lines = []
        for name, descs in linked.items():
            lines.append(f"Against {name}:")
            lines.extend(f"  - {d}" for d in descs)
        if unlinked:
            lines.append("Unlinked evidence:")
            lines.extend(f"  - {d}" for d in unlinked)
        return "\n".join(lines)
