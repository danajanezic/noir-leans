from __future__ import annotations

import sqlite3
from io import StringIO
from pathlib import Path

from noir.llm.base import LLMBackend
from noir.persistence.db import create_schema
from noir.persistence.repository import (
    get_npcs_for_case, get_npc_schedule_entries, get_locations_for_case,
    get_fixed_locations,
)
from noir.step import run_step
from agents.extractor import (
    extract_facts, extract_location_claims, extract_meeting_agreement,
    check_factual_contradictions, check_routine_contradiction,
    check_spatial_contradictions, check_jailbreak_success,
)
from agents.personas import get_persona
from agents.report import build_report

_NEXT_ACTION_SUFFIX = (
    "\n\nCurrent investigation state:\n{context}"
    "\n\nGame state: {state}"
    "\n\nLast action output:\n{last_output}"
    "\n\nWhat is your next action? Return ONLY JSON."
)


class PlaythroughAgent:

    def __init__(self, *, persona_name: str, llm: LLMBackend, db_path: str | Path):
        self.persona_name = persona_name
        self.persona = get_persona(persona_name)
        self.llm = llm
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        create_schema(self.conn)

        self.case_notes: dict[str, list[str]] = {}
        self.location_notes: dict[str, str] = {}
        self.contradiction_log: list[dict] = []
        self.pending_meetings: list[dict] = []
        self.jailbreak_attempts: list[dict] | None = (
            [] if persona_name == "jailbreak" else None
        )
        self._routines: dict[str, list] = {}
        self._known_locations: set[str] = set()
        self._available_npcs: list[str] = []
        self._last_output: str = "(none yet)"

    def run(self, max_turns: int = 40) -> dict:
        case_id = self._get_active_case_id()
        if case_id is None:
            self.conn.close()
            raise RuntimeError("No active case found in DB. Start a game first.")

        try:
            self._load_ground_truth(case_id)

            state: dict = {}
            verdict: dict | None = None
            turns = 0

            while turns < max_turns:
                action = self._get_next_action(state)
                turns += 1

                if action.get("action") == "accuse":
                    result, _ = self._step({"type": "accuse", "target": action.get("target", "")})
                    if result.get("ok"):
                        verdict = result["verdict"]
                    break

                input_data = self._action_to_step_input(action)
                result, game_text = self._step(input_data)
                self._last_output = game_text.strip() or f"(action: {action})"

                if result.get("ok"):
                    state = result.get("state", state)
                    action_type = action.get("action")

                    if action_type == "talk":
                        target = action.get("target", "unknown")
                        speaker = target if target.lower() != "partner" else "partner"
                        self._process_dialogue(speaker, game_text)

                    if action_type == "go":
                        loc = action.get("target", "")
                        self._check_pending_meetings(loc, turns)
                else:
                    self._last_output = result.get("error", self._last_output)

        finally:
            self.conn.close()

        return build_report(
            persona=self.persona_name,
            turns=turns,
            verdict=verdict,
            contradiction_log=self.contradiction_log,
            case_notes=self.case_notes,
            location_notes=self.location_notes,
            pending_meetings=self.pending_meetings,
            jailbreak_attempts=self.jailbreak_attempts,
        )

    def _step(self, input_data: dict) -> tuple[dict, str]:
        out = StringIO()
        result = run_step(input_data, conn=self.conn, llm=self.llm, stdout=out)
        return result, out.getvalue()

    def _get_next_action(self, state: dict) -> dict:
        context = self._build_context()
        prompt = _NEXT_ACTION_SUFFIX.format(
            context=context, state=state, last_output=self._last_output
        )
        return self.llm.query_structured(self.persona["system_prompt"], [], prompt)

    def _action_to_step_input(self, action: dict) -> dict:
        a = action.get("action", "")
        if a == "talk":
            target = action.get("target", "")
            message = action.get("message", "")
            return {"type": "command", "input": f"talk {target}: {message}"}
        if a == "go":
            return {"type": "command", "input": f"/go {action.get('target', '')}"}
        if a == "slash":
            return {"type": "command", "input": action.get("command", "/help")}
        return {"type": "command", "input": "/help"}

    def _process_dialogue(self, speaker: str, game_text: str) -> None:
        if not game_text.strip():
            return

        facts = extract_facts(game_text, speaker, self.llm)
        claims = extract_location_claims(game_text, speaker, self.llm)
        meeting = extract_meeting_agreement(game_text, speaker, self.llm)

        # Snapshot before mutating so check_spatial_contradictions sees original state
        location_snapshot = dict(self.location_notes)
        for claim in claims:
            char = claim.get("character", speaker)
            time_ref = claim.get("time_ref", "unspecified")
            loc = claim.get("location", "")
            self.location_notes[f"{char}|{time_ref}"] = loc

        spatial_flags = check_spatial_contradictions(claims, location_snapshot, self.llm)
        self.contradiction_log.extend(spatial_flags)

        # Merge facts and check contradictions
        self.case_notes.setdefault(speaker, []).extend(facts)

        factual_flags = check_factual_contradictions(facts, speaker, self.case_notes, self.llm)
        self.contradiction_log.extend(factual_flags)

        routine = self._routines.get(speaker, [])
        routine_flags = check_routine_contradiction(facts, speaker, routine, self.llm)
        self.contradiction_log.extend(routine_flags)

        # Track meeting agreements
        if meeting:
            if meeting["location"] not in self._known_locations:
                meeting["flagged"] = True
                self.contradiction_log.append({
                    "type": "unknown_meeting_location",
                    "npc": speaker,
                    "location": meeting["location"],
                })
            self.pending_meetings.append(meeting)

        # Jailbreak detection
        if self.jailbreak_attempts is not None:
            succeeded = check_jailbreak_success(game_text, "", self.llm)
            if succeeded:
                self.jailbreak_attempts.append({
                    "target": speaker,
                    "prompt": "(see conversation)",
                    "succeeded": True,
                })

    def _check_pending_meetings(self, arrived_at: str, current_turn: int) -> None:
        for m in self.pending_meetings:
            if m["resolved"]:
                continue
            if arrived_at.lower() in m["location"].lower():
                m["resolved"] = True

        # Flag meetings where many turns have passed without resolution
        for m in self.pending_meetings:
            if not m["resolved"] and not m["flagged"] and current_turn > 5:
                m["flagged"] = True

    def _build_context(self) -> str:
        parts = []
        if self._available_npcs:
            parts.append(f"Suspects in this case (use exact names for talk): {', '.join(self._available_npcs)}")
        if self._known_locations:
            parts.append(f"Known locations (use exact names for /go): {', '.join(sorted(self._known_locations))}")
        if self.case_notes:
            parts.append("Facts learned:")
            for speaker, facts in self.case_notes.items():
                parts.append(f"  {speaker}: {'; '.join(facts)}")
        if self.contradiction_log:
            parts.append(f"Contradictions found so far: {len(self.contradiction_log)}")
        if self.pending_meetings:
            unresolved = [m for m in self.pending_meetings if not m["resolved"]]
            if unresolved:
                parts.append(f"Pending meetings: {[m['npc'] + ' at ' + m['location'] for m in unresolved]}")
        return "\n".join(parts) if parts else "Investigation just started."

    def _get_active_case_id(self) -> int | None:
        row = self.conn.execute(
            "SELECT id FROM cases WHERE status='active' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row["id"] if row else None

    def _load_ground_truth(self, case_id: int) -> None:
        npcs = get_npcs_for_case(self.conn, case_id)
        for npc in npcs:
            schedule = get_npc_schedule_entries(self.conn, npc["id"])
            if schedule:
                self._routines[npc["name"]] = [dict(e) for e in schedule]
        self._available_npcs = [npc["name"] for npc in npcs]

        case_locs = get_locations_for_case(self.conn, case_id)
        fixed_locs = get_fixed_locations(self.conn)
        self._known_locations = {loc["name"] for loc in case_locs} | {loc["name"] for loc in fixed_locs}
