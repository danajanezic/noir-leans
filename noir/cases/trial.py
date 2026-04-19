import json
import random
import sqlite3
from datetime import datetime, timezone, timedelta
from noir.llm.base import LLMBackend
from noir.persistence.repository import (
    update_case_status, get_case, append_history, get_history,
    update_player_reputation, update_player_stats, get_player
)

DA_CHARACTER_ID = "da"
CLERK_CHARACTER_ID = "clerk"

DA_SYSTEM_PROMPT = """You are the District Attorney of Noirleans, 1935.

You are a political creature first, a lawyer second. You decide which cases to prosecute based on
what is good for your career — not what is just. You operate within the corrupt machinery of
Depression-era Louisiana and you know exactly how it works.

Your calculus when evaluating an arrest:
- A detective with a strong reputation brings you winners. A detective with a weak reputation
  brings you embarrassments. Adjust your willingness accordingly.
- Wealthy suspects and politically connected suspects have lawyers, friends in high places, and
  the ability to make your life difficult. You need ironclad evidence before touching them.
- Suspects with no money, no connections, and especially Black suspects in 1935 Noirleans —
  you will prosecute these cases on almost any charge the detective names, because juries
  convict them and nobody important complains. This is the system you work in.
- The charges themselves matter less than whether you think you can win.

You are not evil — you are practical. You have convinced yourself this is how the world works
and you are simply being realistic. You speak with bureaucratic confidence and occasional
flashes of self-justifying philosophy.

Return ONLY valid JSON: {"verdict": "accepted"|"rejected", "reasoning": "string", "dialogue": "string (your in-character spoken response)"}"""

CLERK_SYSTEM_PROMPT = """You are the courthouse clerk — a person of indeterminate age who has worked
in this building so long they have become architecturally load-bearing. You know the status of every
trial in this building and report it with the weary precision of someone who has seen it all,
including the time a man was acquitted because the jury found his hat insufficiently sinister.
You speak in a dry, matter-of-fact tone with occasional flashes of unexpected poetry."""


def _suspect_profile(conn: sqlite3.Connection, case_id: int) -> dict:
    """Pull the arrested suspect's details from case_data for the DA's consideration."""
    arrest = conn.execute(
        "SELECT npc_id FROM arrests WHERE case_id=? ORDER BY id DESC LIMIT 1", (case_id,)
    ).fetchone()
    if not arrest:
        return {}
    npc = conn.execute("SELECT * FROM npcs WHERE id=?", (arrest["npc_id"],)).fetchone()
    if not npc:
        return {}
    case = get_case(conn, case_id)
    case_data = json.loads(case["case_data"])
    for suspect in case_data.get("suspects", []):
        if suspect["name"].lower() == npc["name"].lower():
            return {
                "name": suspect["name"],
                "role": suspect.get("role", ""),
                "race": suspect.get("race", "unknown"),
                "political_connections": suspect.get("political_connections", "none"),
                "relationships": suspect.get("relationships", []),
            }
    return {"name": npc["name"], "role": npc["role"]}


class TrialSystem:

    def __init__(self, *, conn: sqlite3.Connection, case_id: int, llm: LLMBackend):
        self.conn = conn
        self.case_id = case_id
        self.llm = llm

    def submit_to_da(self, *, evidence_summary: str) -> dict:
        arrest = self.conn.execute(
            "SELECT id FROM arrests WHERE case_id=? LIMIT 1", (self.case_id,)
        ).fetchone()
        if not arrest:
            return {
                "verdict": "rejected",
                "reasoning": "No arrest on record.",
                "dialogue": (
                    "You walk in here with evidence and no body in cuffs? "
                    "I prosecute suspects, detective, not abstractions. "
                    "Arrest someone first. Then come talk to me."
                ),
            }

        player = get_player(self.conn)
        reputation = player["reputation"] if player else 100
        suspect = _suspect_profile(self.conn, self.case_id)

        connections = ", ".join(
            f"{r['name']} ({r['relationship']})"
            for r in suspect.get("relationships", [])
            if r.get("relationship")
        ) or "none known"

        history = get_history(self.conn, character_id=DA_CHARACTER_ID)
        political = suspect.get("political_connections", "none")
        detective_race = player["race"] if player and player["race"] != "unspecified" else "unknown"
        detective_gender = player["gender"] if player and player["gender"] != "unspecified" else "unknown"
        prompt = (
            f"Detective reputation: {reputation}/100. Race: {detective_race}. Gender: {detective_gender}.\n"
            f"Arrested suspect: {suspect.get('name', 'unknown')}, {suspect.get('role', '')}.\n"
            f"Suspect race: {suspect.get('race', 'unknown')}.\n"
            f"Suspect political connections: {political}.\n"
            f"Suspect personal connections: {connections}.\n\n"
            f"Charges and evidence:\n{evidence_summary}\n\n"
            "Decide whether to prosecute. Apply your real calculus — reputation, race, connections, "
            "political risk. Be honest with yourself about why you're deciding what you're deciding, "
            "even if your dialogue softens it. "
            'Return JSON: {"verdict": "accepted"|"rejected", "reasoning": "string", "dialogue": "string"}'
        )
        result = self.llm.query_structured(DA_SYSTEM_PROMPT, history, prompt)

        append_history(self.conn, character_id=DA_CHARACTER_ID, role="user",
                       content=prompt, case_id=None)
        append_history(self.conn, character_id=DA_CHARACTER_ID, role="assistant",
                       content=result.get("dialogue", ""), case_id=None)

        if result.get("verdict") == "accepted":
            hours = random.randint(24, 72)
            end_time = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
            update_case_status(self.conn, case_id=self.case_id, status="in_trial",
                               trial_end_time=end_time)

        return result

    def check_courthouse(self) -> dict:
        case = get_case(self.conn, self.case_id)
        now = datetime.now(timezone.utc)

        if case["status"] == "in_trial" and case["trial_end_time"]:
            end_time = datetime.fromisoformat(case["trial_end_time"])
            if now >= end_time:
                verdict = self._generate_verdict(case)
                update_case_status(self.conn, case_id=self.case_id, status="closed",
                                   trial_outcome=json.dumps(verdict))
                return {"status": "closed", "verdict": verdict}
            remaining = end_time - now
            minutes = int(remaining.total_seconds() / 60)
            return {"status": "in_trial", "minutes_remaining": minutes}

        if case["status"] == "closed":
            return {"status": "closed",
                    "verdict": json.loads(case["trial_outcome"]) if case["trial_outcome"] else {}}

        return {"status": case["status"]}

    def _generate_verdict(self, case: sqlite3.Row) -> dict:
        arrest = self.conn.execute(
            "SELECT was_correct FROM arrests WHERE case_id=? ORDER BY id DESC LIMIT 1",
            (self.case_id,)
        ).fetchone()
        was_correct = bool(arrest and arrest["was_correct"])

        if was_correct:
            update_player_stats(self.conn, cases_solved_delta=1)
            update_player_reputation(self.conn, delta=10)
        else:
            update_player_reputation(self.conn, delta=-15)
            update_player_stats(self.conn, wrong_arrests_delta=1)

        case_data = json.loads(case["case_data"])
        prompt = (
            f"Case: {case['title']}\n"
            f"Case details: {json.dumps(case_data, indent=2)}\n\n"
            f"The arrested person was {'the actual killer' if was_correct else 'innocent'}. "
            "Generate a trial verdict with absurdist noir courtroom drama. "
            'Return JSON: {"outcome": "guilty"|"not_guilty", '
            '"summary": "string (2-3 sentences of dramatic courtroom narration)"}'
        )
        return self.llm.query_structured(CLERK_SYSTEM_PROMPT, [], prompt)
