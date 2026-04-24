import sqlite3
from noir.llm.base import LLMBackend
from noir.persistence.repository import (
    update_npc_guilt, update_npc_pressure, decay_npc_pressure,
    get_npc_revelation_stage, increment_npc_revelation_stage,
    get_npc_relationship_flags, set_npc_secret_revealed, get_npc,
)

_CLASSIFY_SYSTEM = (
    "You are classifying what happened in a detective interrogation exchange. "
    "Return ONLY valid JSON with five boolean fields. "
    "Definitions: "
    "pressure_applied = detective used persistent questioning, confrontation, or emotional pressure to push the NPC. "
    "threat_made = detective explicitly threatened consequences (arrest, exposure, violence, harm to the NPC or someone they care about) — NOT merely firm questioning. "
    "kindness_shown = detective showed empathy, offered help, or built rapport. "
    "guilt_trigger = the exchange touched on something the NPC feels guilty about. "
    "evidence_confronted = detective presented a specific piece of evidence directly to the NPC. "
    "Be conservative on threat_made — only mark true for explicit threats, not strong questions."
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


def _pressure_delta(events: dict, pressure_tolerance: int) -> int:
    resist = 11 - pressure_tolerance
    delta = 0
    if events.get("pressure_applied"):
        delta += resist * 5
    if events.get("threat_made"):
        delta += resist * 10
    if events.get("evidence_confronted"):
        delta += resist * 8
    return delta  # 0 means no pressure events


def _guilt_delta(events: dict, empathy: int) -> int:
    delta = 0
    if events.get("kindness_shown"):
        delta += empathy * 2
    if events.get("guilt_trigger"):
        delta += empathy * 4
    return delta


def _combined_score(state: dict, psychology: dict, affection: int = 0) -> int:
    kw = psychology.get("kindness_weight", 5)
    return (
        state.get("pressure_score", 0)
        + state.get("guilt", 0)
        + int(affection * kw / 10)
    )


def _next_threshold(current_stage: int, psychology: dict) -> int | None:
    style = psychology.get("revelation_style", "staged")
    stages = psychology.get("revelation_stages", 3)
    thresholds = _revelation_thresholds(style, stages)
    if current_stage >= len(thresholds):
        return None
    return thresholds[current_stage]


def _build_revelation_prompt(stage: int, total_stages: int,
                              events: dict, style: str,
                              player_input: str = "") -> str:
    fired = [k for k, v in events.items() if v]
    events_desc = ", ".join(fired) if fired else "accumulated pressure and guilt"
    topic_hint = (f" The detective was pressing you about: \"{player_input[:120]}\". "
                  "If your secret touches that thread, let it surface through that angle."
                  ) if player_input.strip() else ""
    if style == "sudden":
        return (
            "[You have reached your breaking point. Tell the detective your secret — all of it. "
            f"What broke you: {events_desc}.{topic_hint} "
            "Stay fully in character. No speeches. Speak the way this person actually speaks.]"
        )
    return (
        f"[You are about to reveal something you have been hiding. "
        f"This is stage {stage} of {total_stages} — reveal approximately "
        f"1/{total_stages} of your secret. Do not reveal more than this stage calls for. "
        f"What broke you open just now: {events_desc}.{topic_hint} "
        "Stay fully in character. Do not announce that you are confessing. "
        "Speak naturally, as the moment demands.]"
    )


def update_npc_state(conn: sqlite3.Connection, npc_id: int,
                     events: dict, psychology: dict) -> None:
    pressure_delta = _pressure_delta(events, psychology.get("pressure_tolerance", 5))
    guilt_delta = _guilt_delta(events, psychology.get("empathy", 5))

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
                     events: dict, psychology: dict,
                     player_input: str = "") -> str | None:
    flags = get_npc_relationship_flags(conn, npc_id)

    style = psychology.get("revelation_style", "staged")
    stages = psychology.get("revelation_stages", 3)
    thresholds = _revelation_thresholds(style, stages)
    current_stage = get_npc_revelation_stage(conn, npc_id)

    if flags and flags.get("secret_revealed"):
        if current_stage > len(thresholds):
            return None  # restatement already used
        pressure = psychology.get("pressure_score", 0)
        guilt = psychology.get("guilt", 0)
        affection = psychology.get("affection", 0)
        kw = psychology.get("kindness_weight", 5)
        combined = pressure + guilt + (affection * kw / 10)
        if combined < 50:
            return None
        from noir.persistence.repository import get_history as _get_history
        history = _get_history(conn, character_id=f"npc_{npc_id}", case_id=case_id)
        excerpt = ""
        if history:
            assistant_msgs = [m["content"] for m in history if m["role"] == "assistant"]
            if assistant_msgs:
                excerpt = assistant_msgs[-1][:300]
        increment_npc_revelation_stage(conn, npc_id=npc_id)
        if excerpt:
            return (
                f"[You have already admitted your secret. Your most recent words were: \"{excerpt}\". "
                f"The detective is pressing you to say it plainly — no metaphor, no deflection. "
                f"Restate what you already admitted, directly, in your own voice.]"
            )
        return (
            "[You have already admitted your secret. The detective is pressing you to say it plainly. "
            "State it directly, in your own voice, without evasion.]"
        )

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

    override_note = " (guilt override — couldn't live with it)" if guilt_override else ""
    effective_style = "sudden" if (style == "sudden" or is_final) else style
    prompt = _build_revelation_prompt(
        stage=new_stage,
        total_stages=len(thresholds),
        events=events,
        style=effective_style,
        player_input=player_input,
    )
    if override_note:
        prompt = prompt.replace("[You have reached your breaking point.",
                                f"[You have reached your breaking point{override_note}.")
        prompt = prompt.replace("[You are about to reveal something you have been hiding.",
                                f"[You are about to reveal something you have been hiding{override_note}.")

    return prompt  # caller injects this into the next npc.speak() call
