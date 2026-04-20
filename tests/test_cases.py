import json
import pytest
from noir.cases.manager import CaseManager
from noir.persistence.repository import (
    create_player, create_case, create_location,
    create_npc, get_player, get_evidence_for_case, get_clues_for_case, get_history, get_case,
    update_case_status, create_arrest, link_evidence_to_suspect,
)
from noir.cases.trial import TrialSystem, DA_CHARACTER_ID, CLERK_CHARACTER_ID
from noir.llm.mock import MockLLMBackend


CASE_DATA_WITH_CLUES = {
    "killer_name": "Dolores Mink",
    "clues": [
        {"description": "A monogrammed flamingo feather", "is_red_herring": False, "location": "The Study"},
        {"description": "A torn receipt from Café Lune", "is_red_herring": False, "location": "The Study"},
        {"description": "A red herring matchbook", "is_red_herring": True, "location": "The Alley"},
    ],
    "suspects": [],
    "locations": [],
    "victim": {"name": "Gerald Fitch", "cause_of_death": "trombone", "found_at": "The Study"},
}


@pytest.fixture
def case_setup(db):
    create_player(db)
    case_id = create_case(db, archetype="Christie", title="The Fitch Affair",
                          case_data=CASE_DATA_WITH_CLUES)
    loc_id = create_location(db, name="The Study", description="Books.", is_fixed=False, case_id=case_id)
    npc_id = create_npc(db, case_id=case_id, name="Dolores Mink", role="suspect",
                        system_prompt="You are Dolores.", current_location_id=loc_id)
    return db, case_id, loc_id, npc_id


def test_collect_evidence_saves_to_db(case_setup):
    db, case_id, loc_id, _ = case_setup
    clue_id = get_clues_for_case(db, case_id)[0]["id"]
    mgr = CaseManager(conn=db, case_id=case_id)
    mgr.collect_evidence(clue_id=clue_id, location_id=loc_id, source_npc_id=None)
    evidence = get_evidence_for_case(db, case_id)
    assert len(evidence) == 1
    assert evidence[0]["clue_id"] == clue_id


# --- validate_and_collect ---

def test_validate_and_collect_accepts_matching_clue(case_setup):
    db, case_id, loc_id, _ = case_setup
    llm = MockLLMBackend(responses=['{"matched": true, "clue_description": "A monogrammed flamingo feather", "reason": "matches"}'])
    mgr = CaseManager(conn=db, case_id=case_id, llm=llm)
    result = mgr.validate_and_collect(description="the flamingo feather", location_id=loc_id, source_npc_id=None)
    assert result["ok"] is True
    assert result["description"] == "A monogrammed flamingo feather"
    evidence = get_evidence_for_case(db, case_id)
    assert len(evidence) == 1
    assert evidence[0]["description"] == "A monogrammed flamingo feather"


def test_validate_and_collect_rejects_invalid_item(case_setup):
    db, case_id, loc_id, _ = case_setup
    llm = MockLLMBackend(responses=['{"matched": false, "clue_description": null, "reason": "no matching clue"}'])
    mgr = CaseManager(conn=db, case_id=case_id, llm=llm)
    result = mgr.validate_and_collect(description="my left shoe", location_id=loc_id, source_npc_id=None)
    assert result["ok"] is False
    assert len(get_evidence_for_case(db, case_id)) == 0


def test_validate_and_collect_rejects_duplicate(case_setup):
    db, case_id, loc_id, _ = case_setup
    llm = MockLLMBackend(responses=[
        '{"matched": true, "clue_description": "A monogrammed flamingo feather", "reason": "matches"}',
        '{"matched": true, "clue_description": "A monogrammed flamingo feather", "reason": "matches"}',
    ])
    mgr = CaseManager(conn=db, case_id=case_id, llm=llm)
    mgr.validate_and_collect(description="the feather", location_id=loc_id, source_npc_id=None)
    result = mgr.validate_and_collect(description="flamingo feather", location_id=loc_id, source_npc_id=None)
    assert result["ok"] is False
    assert "Already collected" in result["message"]
    assert len(get_evidence_for_case(db, case_id)) == 1


def test_validate_and_collect_uses_canonical_description(case_setup):
    db, case_id, loc_id, _ = case_setup
    llm = MockLLMBackend(responses=['{"matched": true, "clue_description": "A torn receipt from Café Lune", "reason": "matches"}'])
    mgr = CaseManager(conn=db, case_id=case_id, llm=llm)
    result = mgr.validate_and_collect(description="receipt", location_id=loc_id, source_npc_id=None)
    assert result["ok"] is True
    assert result["description"] == "A torn receipt from Café Lune"


def test_validate_and_collect_fallback_without_llm(case_setup):
    db, case_id, loc_id, _ = case_setup
    mgr = CaseManager(conn=db, case_id=case_id, llm=None)
    result = mgr.validate_and_collect(description="flamingo feather", location_id=loc_id, source_npc_id=None)
    assert result["ok"] is True  # "flamingo" matches "A monogrammed flamingo feather"


def _run_verdict(db, case_id, npc_id, verdict_response):
    from datetime import datetime, timezone, timedelta
    CaseManager(conn=db, case_id=case_id).arrest(npc_id=npc_id, evidence_summary="evidence")
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    update_case_status(db, case_id=case_id, status="in_trial", trial_end_time=past)
    llm = MockLLMBackend(responses=[verdict_response])
    ts = TrialSystem(conn=db, case_id=case_id, llm=llm)
    return ts.check_courthouse()


def test_verdict_wrong_suspect_reduces_reputation(case_setup):
    db, case_id, loc_id, npc_id = case_setup
    wrong_npc_id = create_npc(db, case_id=case_id, name="Reginald Smoot", role="suspect",
                               system_prompt="You are Reginald.", current_location_id=loc_id)
    _run_verdict(db, case_id, wrong_npc_id, CLERK_VERDICT_RESPONSE)
    assert get_player(db)["reputation"] < 100


def test_verdict_correct_suspect_keeps_reputation(case_setup):
    db, case_id, loc_id, npc_id = case_setup
    _run_verdict(db, case_id, npc_id, CLERK_VERDICT_RESPONSE)
    assert get_player(db)["reputation"] == 110  # +10 from correct verdict


def test_verdict_correct_suspect_increments_cases_solved(case_setup):
    db, case_id, loc_id, npc_id = case_setup
    _run_verdict(db, case_id, npc_id, CLERK_VERDICT_RESPONSE)
    assert get_player(db)["cases_solved"] == 1


def test_verdict_wrong_suspect_increments_wrong_arrests(case_setup):
    db, case_id, loc_id, npc_id = case_setup
    wrong_npc_id = create_npc(db, case_id=case_id, name="Reginald Smoot", role="suspect",
                               system_prompt="You are Reginald.", current_location_id=loc_id)
    _run_verdict(db, case_id, wrong_npc_id, CLERK_VERDICT_RESPONSE)
    assert get_player(db)["wrong_arrests"] == 1


def test_get_evidence_summary_for_da(case_setup):
    db, case_id, loc_id, npc_id = case_setup
    clues = get_clues_for_case(db, case_id)
    mgr = CaseManager(conn=db, case_id=case_id)
    mgr.collect_evidence(clue_id=clues[0]["id"], location_id=loc_id, source_npc_id=None)
    mgr.collect_evidence(clue_id=clues[1]["id"], location_id=loc_id, source_npc_id=npc_id)
    summary = mgr.get_evidence_summary()
    assert clues[0]["description"] in summary
    assert clues[1]["description"] in summary


def test_get_evidence_summary_groups_by_accused(case_setup):
    db, case_id, loc_id, npc_id = case_setup
    clues = get_clues_for_case(db, case_id)
    mgr = CaseManager(conn=db, case_id=case_id)
    ev_id = mgr.collect_evidence(clue_id=clues[0]["id"], location_id=loc_id, source_npc_id=None)
    mgr.collect_evidence(clue_id=clues[1]["id"], location_id=loc_id, source_npc_id=None)
    link_evidence_to_suspect(db, evidence_id=ev_id, npc_id=npc_id)
    summary = mgr.get_evidence_summary()
    assert "Against Dolores Mink" in summary
    assert "Unlinked evidence" in summary
    assert clues[0]["description"] in summary
    assert clues[1]["description"] in summary


DA_ACCEPT_RESPONSE = json.dumps({
    "verdict": "accepted",
    "reasoning": "The flamingo feather is damning. I've seen worse cases. Barely.",
    "dialogue": "The People will take this case, detective. Don't embarrass us."
})

DA_REJECT_RESPONSE = json.dumps({
    "verdict": "rejected",
    "reasoning": "A hunch is not evidence. Neither is optimism.",
    "dialogue": "Come back when you have something I can actually use in court."
})

CLERK_VERDICT_RESPONSE = json.dumps({
    "outcome": "guilty",
    "summary": "The jury deliberated for eleven minutes, including a water break."
})


def test_da_rejects_without_arrest(case_setup):
    db, case_id, _, _ = case_setup
    llm = MockLLMBackend(responses=[])
    ts = TrialSystem(conn=db, case_id=case_id, llm=llm)
    result = ts.submit_to_da(evidence_summary="A flamingo feather")
    assert result["verdict"] == "rejected"
    assert get_case(db, case_id)["status"] == "active"


def test_da_accepts_strong_evidence(case_setup):
    db, case_id, loc_id, npc_id = case_setup
    create_arrest(db, case_id=case_id, npc_id=npc_id, evidence_summary="A flamingo feather")
    llm = MockLLMBackend(responses=[DA_ACCEPT_RESPONSE])
    ts = TrialSystem(conn=db, case_id=case_id, llm=llm)
    result = ts.submit_to_da(evidence_summary="A flamingo feather, a receipt, and a clear motive")
    assert result["verdict"] == "accepted"


def test_da_rejects_weak_evidence(case_setup):
    db, case_id, loc_id, npc_id = case_setup
    create_arrest(db, case_id=case_id, npc_id=npc_id, evidence_summary="A hunch")
    llm = MockLLMBackend(responses=[DA_REJECT_RESPONSE])
    ts = TrialSystem(conn=db, case_id=case_id, llm=llm)
    result = ts.submit_to_da(evidence_summary="A hunch")
    assert result["verdict"] == "rejected"


def test_accepted_case_starts_trial(case_setup):
    db, case_id, loc_id, npc_id = case_setup
    create_arrest(db, case_id=case_id, npc_id=npc_id, evidence_summary="Strong evidence")
    llm = MockLLMBackend(responses=[DA_ACCEPT_RESPONSE])
    ts = TrialSystem(conn=db, case_id=case_id, llm=llm)
    ts.submit_to_da(evidence_summary="Strong evidence")
    case = get_case(db, case_id)
    assert case["status"] == "in_trial"
    assert case["trial_end_time"] is not None


def test_courthouse_reports_trial_in_progress(case_setup):
    db, case_id, loc_id, npc_id = case_setup
    create_arrest(db, case_id=case_id, npc_id=npc_id, evidence_summary="Strong evidence")
    llm = MockLLMBackend(responses=[DA_ACCEPT_RESPONSE])
    ts = TrialSystem(conn=db, case_id=case_id, llm=llm)
    ts.submit_to_da(evidence_summary="Strong evidence")
    status = ts.check_courthouse()
    assert status["status"] == "in_trial"


def test_da_history_persists_across_calls(case_setup):
    db, case_id, loc_id, npc_id = case_setup
    create_arrest(db, case_id=case_id, npc_id=npc_id, evidence_summary="First evidence")
    llm = MockLLMBackend(responses=[DA_ACCEPT_RESPONSE, DA_REJECT_RESPONSE])
    ts = TrialSystem(conn=db, case_id=case_id, llm=llm)
    ts.submit_to_da(evidence_summary="First evidence")
    history = get_history(db, character_id=DA_CHARACTER_ID)
    assert len(history) >= 2


def test_courthouse_elapsed_trial_generates_verdict(case_setup):
    from datetime import datetime, timezone, timedelta
    db, case_id, _, _ = case_setup
    past_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    update_case_status(db, case_id=case_id, status="in_trial", trial_end_time=past_time)
    llm = MockLLMBackend(responses=[CLERK_VERDICT_RESPONSE])
    ts = TrialSystem(conn=db, case_id=case_id, llm=llm)
    result = ts.check_courthouse()
    assert result["status"] == "closed"
    assert result["verdict"]["outcome"] == "guilty"
    assert get_case(db, case_id)["status"] == "closed"
