import json
import pytest
from noir.cases.manager import CaseManager
from noir.persistence.repository import (
    create_player, create_case, create_location,
    create_npc, get_player, get_evidence_for_case, get_history, get_case,
    update_case_status,
)
from noir.cases.trial import TrialSystem, DA_CHARACTER_ID, CLERK_CHARACTER_ID
from noir.llm.mock import MockLLMBackend


@pytest.fixture
def case_setup(db):
    create_player(db)
    case_id = create_case(db, archetype="Christie", title="The Fitch Affair",
                          case_data={"killer_name": "Dolores Mink"})
    loc_id = create_location(db, name="The Study", description="Books.", is_fixed=False, case_id=case_id)
    npc_id = create_npc(db, case_id=case_id, name="Dolores Mink", role="suspect",
                        system_prompt="You are Dolores.", current_location_id=loc_id)
    return db, case_id, loc_id, npc_id


def test_collect_evidence_saves_to_db(case_setup):
    db, case_id, loc_id, _ = case_setup
    mgr = CaseManager(conn=db, case_id=case_id)
    mgr.collect_evidence("A flamingo feather", loc_id, None)
    evidence = get_evidence_for_case(db, case_id)
    assert len(evidence) == 1
    assert evidence[0]["description"] == "A flamingo feather"


def test_arrest_wrong_suspect_reduces_reputation(case_setup):
    db, case_id, loc_id, npc_id = case_setup
    # Killer is Dolores Mink (npc_id), arresting a different npc
    wrong_npc_id = create_npc(db, case_id=case_id, name="Reginald Smoot", role="suspect",
                               system_prompt="You are Reginald.", current_location_id=loc_id)
    mgr = CaseManager(conn=db, case_id=case_id)
    mgr.arrest(npc_id=wrong_npc_id, evidence_summary="A hunch")
    player = get_player(db)
    assert player["reputation"] < 100


def test_arrest_correct_suspect_does_not_reduce_reputation(case_setup):
    db, case_id, loc_id, npc_id = case_setup
    mgr = CaseManager(conn=db, case_id=case_id)
    mgr.arrest(npc_id=npc_id, evidence_summary="A flamingo feather and motive")
    player = get_player(db)
    assert player["reputation"] == 100


def test_get_evidence_summary_for_da(case_setup):
    db, case_id, loc_id, npc_id = case_setup
    mgr = CaseManager(conn=db, case_id=case_id)
    mgr.collect_evidence("A feather", loc_id, None)
    mgr.collect_evidence("A receipt", loc_id, npc_id)
    summary = mgr.get_evidence_summary()
    assert "A feather" in summary
    assert "A receipt" in summary


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


def test_da_accepts_strong_evidence(case_setup):
    db, case_id, loc_id, _ = case_setup
    llm = MockLLMBackend(responses=[DA_ACCEPT_RESPONSE])
    ts = TrialSystem(conn=db, case_id=case_id, llm=llm)
    result = ts.submit_to_da(evidence_summary="A flamingo feather, a receipt, and a clear motive")
    assert result["verdict"] == "accepted"


def test_da_rejects_weak_evidence(case_setup):
    db, case_id, _, _ = case_setup
    llm = MockLLMBackend(responses=[DA_REJECT_RESPONSE])
    ts = TrialSystem(conn=db, case_id=case_id, llm=llm)
    result = ts.submit_to_da(evidence_summary="A hunch")
    assert result["verdict"] == "rejected"


def test_accepted_case_starts_trial(case_setup):
    db, case_id, _, _ = case_setup
    llm = MockLLMBackend(responses=[DA_ACCEPT_RESPONSE])
    ts = TrialSystem(conn=db, case_id=case_id, llm=llm)
    ts.submit_to_da(evidence_summary="Strong evidence")
    case = get_case(db, case_id)
    assert case["status"] == "in_trial"
    assert case["trial_end_time"] is not None


def test_courthouse_reports_trial_in_progress(case_setup):
    db, case_id, _, _ = case_setup
    llm = MockLLMBackend(responses=[DA_ACCEPT_RESPONSE])
    ts = TrialSystem(conn=db, case_id=case_id, llm=llm)
    ts.submit_to_da(evidence_summary="Strong evidence")
    status = ts.check_courthouse()
    assert status["status"] == "in_trial"


def test_da_history_persists_across_calls(case_setup):
    db, case_id, _, _ = case_setup
    llm = MockLLMBackend(responses=[DA_ACCEPT_RESPONSE, DA_REJECT_RESPONSE])
    ts = TrialSystem(conn=db, case_id=case_id, llm=llm)
    ts.submit_to_da(evidence_summary="First evidence")
    history = get_history(db, DA_CHARACTER_ID)
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
