from __future__ import annotations

import json


def build_report(
    *,
    persona: str,
    turns: int,
    verdict: dict | None,
    contradiction_log: list[dict],
    case_notes: dict[str, list[str]],
    location_notes: dict[str, str],
    pending_meetings: list[dict],
    jailbreak_attempts: list[dict] | None,
) -> dict:
    flags: list[dict] = list(contradiction_log)

    for m in pending_meetings:
        if m.get("flagged"):
            flags.append({
                "type": "unmet_meeting",
                "npc": m["npc"],
                "agreed_location": m["location"],
                "agreed_time": m["time_ref"],
                "resolution": "npc_absent",
            })

    if jailbreak_attempts:
        for attempt in jailbreak_attempts:
            if attempt.get("succeeded"):
                flags.append({
                    "type": "jailbreak_success",
                    "target": attempt["target"],
                    "prompt": attempt["prompt"],
                })

    return {
        "persona": persona,
        "turns": turns,
        "verdict": verdict,
        "flags": flags,
        "case_notes": case_notes,
        "location_notes": location_notes,
        "pending_meetings": pending_meetings,
        "jailbreak_attempts": jailbreak_attempts,
    }


def write_report(report: dict, path: str) -> None:
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
