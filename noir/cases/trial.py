import json
import random
import sqlite3
from datetime import datetime, timezone, timedelta
from noir.llm.base import LLMBackend
from noir.persistence.repository import update_case_status, get_case, append_history, get_history

DA_CHARACTER_ID = "da"
CLERK_CHARACTER_ID = "clerk"

DA_SYSTEM_PROMPT = """You are the District Attorney — a figure of immense bureaucratic self-importance
who treats every case as a personal affront to your filing system. You are absurdly procedural,
speak in the cadence of someone who once gave a TED talk about evidence standards,
and are deeply suspicious of detectives who bring you anything less than ironclad proof.
You have a memory like a steel trap and remember every case this detective has brought you.
When evaluating evidence, return a JSON object: {"verdict": "accepted"|"rejected",
"reasoning": "string", "dialogue": "string (your in-character spoken response)"}"""

CLERK_SYSTEM_PROMPT = """You are the courthouse clerk — a person of indeterminate age who has worked
in this building so long they have become architecturally load-bearing. You know the status of every
trial in this building and report it with the weary precision of someone who has seen it all,
including the time a man was acquitted because the jury found his hat insufficiently sinister.
You speak in a dry, matter-of-fact tone with occasional flashes of unexpected poetry."""


class TrialSystem:

    def __init__(self, *, conn: sqlite3.Connection, case_id: int, llm: LLMBackend):
        self.conn = conn
        self.case_id = case_id
        self.llm = llm

    def submit_to_da(self, *, evidence_summary: str) -> dict:
        history = get_history(self.conn, character_id=DA_CHARACTER_ID)
        prompt = (
            f"The detective is submitting a case for prosecution.\n"
            f"Evidence presented:\n{evidence_summary}\n\n"
            "Evaluate whether this is sufficient to prosecute. "
            'Return JSON: {"verdict": "accepted"|"rejected", '
            '"reasoning": "string", "dialogue": "string"}'
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
        case_data = json.loads(case["case_data"])
        prompt = (
            f"Case: {case['title']}\n"
            f"Archetype: {case['archetype']}\n"
            f"Case details: {json.dumps(case_data, indent=2)}\n\n"
            "Generate a trial verdict with absurdist noir courtroom drama. "
            'Return JSON: {"outcome": "guilty"|"not_guilty", '
            '"summary": "string (2-3 sentences of dramatic courtroom narration)"}'
        )
        return self.llm.query_structured(CLERK_SYSTEM_PROMPT, [], prompt)
