import sqlite3
from noir.llm.base import LLMBackend
from noir.persistence.repository import (
    update_npc_guilt, update_npc_pressure, decay_npc_pressure,
    get_npc_revelation_stage, increment_npc_revelation_stage,
    get_npc_relationship_flags, set_npc_secret_revealed,
)

_CLASSIFY_SYSTEM = (
    "You are classifying what happened in a detective interrogation exchange. "
    "Return ONLY valid JSON with five boolean fields."
)


def _revelation_thresholds(style: str, stages: int) -> list[int]:
    if style == "sudden":
        return [100]
    thresholds = {
        2: [60, 100],
        3: [50, 75, 100],
        4: [40, 60, 80, 100],
        5: [35, 55, 70, 85, 100],
    }
    return thresholds.get(stages, [50, 75, 100])


def classify_events(llm: LLMBackend, player_msg: str, npc_response: str) -> dict:
    prompt = (
        f'Detective said: "{player_msg}"\n'
        f'NPC replied: "{npc_response}"\n\n'
        "Classify what just happened. Return JSON:\n"
        '{"pressure_applied": bool, "threat_made": bool, '
        '"kindness_shown": bool, "guilt_trigger": bool, "evidence_confronted": bool}'
    )
    try:
        result = llm.query_structured(_CLASSIFY_SYSTEM, [], prompt)
    except SystemExit:
        result = {}
    defaults = {
        "pressure_applied": False, "threat_made": False,
        "kindness_shown": False, "guilt_trigger": False, "evidence_confronted": False,
    }
    defaults.update({k: bool(v) for k, v in result.items() if k in defaults})
    return defaults


def update_npc_state(conn: sqlite3.Connection, npc_id: int,
                     events: dict, psychology: dict) -> None:
    pt = psychology.get("pressure_tolerance", 5)
    emp = psychology.get("empathy", 5)

    pressure_delta = 0
    if events.get("pressure_applied"):
        pressure_delta += (11 - pt) * 5
    if events.get("threat_made"):
        pressure_delta += (11 - pt) * 10
    if events.get("evidence_confronted"):
        pressure_delta += (11 - pt) * 8

    guilt_delta = 0
    if events.get("kindness_shown"):
        guilt_delta += emp * 2
    if events.get("guilt_trigger"):
        guilt_delta += emp * 4

    any_pressure = (events.get("pressure_applied") or
                    events.get("threat_made") or
                    events.get("evidence_confronted"))

    if pressure_delta:
        update_npc_pressure(conn, npc_id=npc_id, delta=pressure_delta)
    elif not any_pressure:
        decay_npc_pressure(conn, npc_id)

    if guilt_delta:
        update_npc_guilt(conn, npc_id=npc_id, delta=guilt_delta)


def check_revelation(conn: sqlite3.Connection, llm: LLMBackend,
                     npc_id: int, case_id: int, npc_name: str,
                     events: dict, psychology: dict) -> str | None:
    flags = get_npc_relationship_flags(conn, npc_id)
    if flags and flags.get("secret_revealed"):
        return None

    style = psychology.get("revelation_style", "staged")
    stages = psychology.get("revelation_stages", 3)
    thresholds = _revelation_thresholds(style, stages)
    current_stage = get_npc_revelation_stage(conn, npc_id)

    if current_stage >= len(thresholds):
        return None

    pressure = psychology.get("pressure_score", 0)
    guilt = psychology.get("guilt", 0)
    affection = psychology.get("affection", 0)
    kw = psychology.get("kindness_weight", 5)
    combined = pressure + guilt + (affection * kw / 10)

    next_threshold = thresholds[current_stage]
    guilt_override = guilt >= 90

    if combined < next_threshold and not guilt_override:
        return None

    new_stage = increment_npc_revelation_stage(conn, npc_id=npc_id)
    is_final = new_stage >= len(thresholds)

    if is_final:
        set_npc_secret_revealed(conn, npc_id)

    fired = [k for k, v in events.items() if v]
    fired_str = ", ".join(fired) if fired else "sustained pressure"
    override_note = " (guilt override — couldn't live with it)" if guilt_override else ""

    if style == "sudden" or is_final:
        prompt = (
            f"[You have reached your breaking point{override_note}. "
            f"Tell the detective your secret — all of it. "
            f"What broke you: {fired_str}. "
            "Stay fully in character. No speeches. Speak the way this person actually speaks.]"
        )
    else:
        prompt = (
            f"[You are about to reveal something you have been hiding{override_note}. "
            f"This is stage {new_stage} of {len(thresholds)} — reveal approximately "
            f"1/{len(thresholds)} of your secret. Do not reveal more than this stage calls for. "
            f"What broke you open just now: {fired_str}. "
            "Stay fully in character. Do not announce that you are confessing. "
            "Speak naturally, as the moment demands.]"
        )

    from noir.persistence.repository import get_npc
    npc_row = get_npc(conn, npc_id)
    if npc_row is None:
        return None

    response = llm.query(npc_row["system_prompt"], [], prompt)
    return response
