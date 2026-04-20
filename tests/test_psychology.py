import pytest
import json
from itertools import cycle
from noir.llm.mock import MockLLMBackend
from noir.characters.psychology import (
    classify_events, update_npc_state, check_revelation,
    _revelation_thresholds,
)
from noir.characters.psychology import (
    _pressure_delta, _guilt_delta, _combined_score, _next_threshold,
    _build_revelation_prompt,
)

_NO_EVENTS = {
    "pressure_applied": False, "threat_made": False,
    "kindness_shown": False, "guilt_trigger": False, "evidence_confronted": False,
}

def test_pressure_delta_zero_when_no_pressure():
    assert _pressure_delta(_NO_EVENTS, pressure_tolerance=5) == 0

def test_pressure_delta_higher_for_low_tolerance():
    events = {**_NO_EVENTS, "pressure_applied": True}
    low = _pressure_delta(events, pressure_tolerance=1)
    high = _pressure_delta(events, pressure_tolerance=9)
    assert low > high

def test_pressure_delta_threat_larger_than_push():
    push = _pressure_delta({**_NO_EVENTS, "pressure_applied": True}, pressure_tolerance=5)
    threat = _pressure_delta({**_NO_EVENTS, "threat_made": True}, pressure_tolerance=5)
    assert threat > push

def test_guilt_delta_zero_with_no_emotional_events():
    assert _guilt_delta(_NO_EVENTS, empathy=10) == 0

def test_guilt_delta_scales_with_empathy():
    events = {**_NO_EVENTS, "guilt_trigger": True}
    low = _guilt_delta(events, empathy=1)
    high = _guilt_delta(events, empathy=10)
    assert high > low

def test_combined_score():
    state = {"pressure_score": 30, "guilt": 20}
    psychology = {"kindness_weight": 10}
    # 30 + 20 + (50 * 10 // 10) = 100
    assert _combined_score(state, psychology, affection=50) == 100

def test_next_threshold_sudden_unrevealed():
    assert _next_threshold(0, {"revelation_style": "sudden", "revelation_stages": 1}) == 100

def test_next_threshold_sudden_already_revealed():
    assert _next_threshold(1, {"revelation_style": "sudden", "revelation_stages": 1}) is None

def test_next_threshold_staged_2():
    p = {"revelation_style": "staged", "revelation_stages": 2}
    assert _next_threshold(0, p) == 60
    assert _next_threshold(1, p) == 100
    assert _next_threshold(2, p) is None

def test_build_revelation_prompt_sudden():
    events = {**_NO_EVENTS, "pressure_applied": True}
    prompt = _build_revelation_prompt(stage=1, total_stages=1, events=events, style="sudden")
    assert "breaking point" in prompt
    assert "pressure_applied" in prompt

def test_build_revelation_prompt_staged():
    events = {**_NO_EVENTS, "guilt_trigger": True}
    prompt = _build_revelation_prompt(stage=2, total_stages=4, events=events, style="staged")
    assert "stage 2 of 4" in prompt
    assert "1/4" in prompt
    assert "guilt_trigger" in prompt


# --- threshold logic (pure Python, no LLM) ---

def test_staged_2_thresholds():
    assert _revelation_thresholds("staged", 2) == [60, 100]

def test_staged_3_thresholds():
    assert _revelation_thresholds("staged", 3) == [50, 75, 100]

def test_staged_4_thresholds():
    assert _revelation_thresholds("staged", 4) == [40, 60, 80, 100]

def test_staged_5_thresholds():
    assert _revelation_thresholds("staged", 5) == [35, 55, 70, 85, 100]

def test_sudden_threshold():
    assert _revelation_thresholds("sudden", 1) == [100]


# --- classify_events ---

def test_classify_events_returns_five_booleans():
    llm = MockLLMBackend(responses=[json.dumps({
        "pressure_applied": True,
        "threat_made": False,
        "kindness_shown": False,
        "guilt_trigger": False,
        "evidence_confronted": True,
    })])
    result = classify_events(llm, "I know you were there.", "I told you, I was home.")
    assert result["pressure_applied"] is True
    assert result["evidence_confronted"] is True
    assert result["kindness_shown"] is False

def test_classify_events_missing_keys_default_false():
    llm = MockLLMBackend(responses=[json.dumps({"pressure_applied": True})])
    result = classify_events(llm, "msg", "resp")
    assert result["pressure_applied"] is True
    assert result.get("kindness_shown") is False
    assert result.get("threat_made") is False


# --- update_npc_state ---

def test_update_npc_state_pressure_applied(db):
    from noir.persistence.repository import create_npc, get_npc_psychology, create_location
    from noir.characters.psychology import update_npc_state
    db.execute("INSERT INTO cases (archetype, title, case_data) VALUES ('t','t','{}')")
    db.commit()
    case_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    loc_id = create_location(db, name="S", description=".", is_fixed=False)
    npc_id = create_npc(db, case_id=case_id, name="X", role="suspect",
                        system_prompt=".", current_location_id=loc_id,
                        pressure_tolerance=5, kindness_weight=5, empathy=5,
                        starting_guilt=0, revelation_style="staged", revelation_stages=3)
    events = {"pressure_applied": True, "threat_made": False,
              "kindness_shown": False, "guilt_trigger": False, "evidence_confronted": False}
    psychology = get_npc_psychology(db, npc_id)
    update_npc_state(db, npc_id, events, psychology)
    psych = get_npc_psychology(db, npc_id)
    # pressure_applied: (11 - 5) * 5 = 30
    assert psych["pressure_score"] == 30

def test_update_npc_state_no_pressure_decays(db):
    from noir.persistence.repository import (
        create_npc, get_npc_psychology, update_npc_pressure, create_location
    )
    from noir.characters.psychology import update_npc_state
    db.execute("INSERT INTO cases (archetype, title, case_data) VALUES ('t','t','{}')")
    db.commit()
    case_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    loc_id = create_location(db, name="S2", description=".", is_fixed=False)
    npc_id = create_npc(db, case_id=case_id, name="Y", role="suspect",
                        system_prompt=".", current_location_id=loc_id,
                        pressure_tolerance=5, kindness_weight=5, empathy=5,
                        starting_guilt=0, revelation_style="staged", revelation_stages=3)
    update_npc_pressure(db, npc_id=npc_id, delta=20)
    events = {"pressure_applied": False, "threat_made": False,
              "kindness_shown": False, "guilt_trigger": False, "evidence_confronted": False}
    psychology = get_npc_psychology(db, npc_id)
    update_npc_state(db, npc_id, events, psychology)
    psych = get_npc_psychology(db, npc_id)
    assert psych["pressure_score"] == 15  # 20 - 5 decay


# --- check_revelation ---

def test_check_revelation_returns_none_below_threshold(db):
    from noir.persistence.repository import create_npc, get_npc_psychology, create_location
    from noir.characters.psychology import check_revelation
    db.execute("INSERT INTO cases (archetype, title, case_data) VALUES ('t','t','{}')")
    db.commit()
    case_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    loc_id = create_location(db, name="S3", description=".", is_fixed=False)
    npc_id = create_npc(db, case_id=case_id, name="Z", role="suspect",
                        system_prompt=".", current_location_id=loc_id,
                        pressure_tolerance=10, kindness_weight=1, empathy=1,
                        starting_guilt=0, revelation_style="staged", revelation_stages=3)
    llm = MockLLMBackend()
    psychology = get_npc_psychology(db, npc_id)
    events = {"pressure_applied": False, "threat_made": False,
              "kindness_shown": False, "guilt_trigger": False, "evidence_confronted": False}
    result = check_revelation(db, llm, npc_id, case_id, "Z", events, psychology)
    assert result is None

def test_check_revelation_fires_when_threshold_crossed(db):
    from noir.persistence.repository import (
        create_npc, get_npc_psychology, update_npc_pressure, update_npc_guilt,
        get_npc_revelation_stage, create_location
    )
    from noir.characters.psychology import check_revelation
    db.execute("INSERT INTO cases (archetype, title, case_data) VALUES ('t','t','{}')")
    db.commit()
    case_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    loc_id = create_location(db, name="S4", description=".", is_fixed=False)
    npc_id = create_npc(db, case_id=case_id, name="W", role="suspect",
                        system_prompt="NPC is W.", current_location_id=loc_id,
                        pressure_tolerance=5, kindness_weight=5, empathy=5,
                        starting_guilt=0, revelation_style="staged", revelation_stages=2)
    # push pressure + guilt to combined >= 60 (first threshold for staged 2)
    update_npc_pressure(db, npc_id=npc_id, delta=40)
    update_npc_guilt(db, npc_id=npc_id, delta=25)
    llm = MockLLMBackend(responses=["I... I was there. I saw what happened."])
    psychology = get_npc_psychology(db, npc_id)
    events = {"pressure_applied": False, "threat_made": False,
              "kindness_shown": False, "guilt_trigger": False, "evidence_confronted": False}
    result = check_revelation(db, llm, npc_id, case_id, "W", events, psychology)
    assert result is not None
    assert isinstance(result, str)
    assert get_npc_revelation_stage(db, npc_id) == 1
