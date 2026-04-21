import json
import pytest
from itertools import cycle

from noir.persistence.repository import (
    create_player, get_player,
    create_case, update_case_status,
    create_location, create_npc, create_arrest,
    create_clue, add_evidence,
    get_player_cash, update_player_cash,
    get_npc_corruption, set_npc_corruption,
    record_bribe, get_accepted_bribes_for_case,
    get_player_org_memberships, collect_org_payroll,
    add_organization_member,
)
from noir.game import check_org_eligibility, ORG_ELIGIBILITY
from noir.cases.trial import TrialSystem


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_CASE = {
    "killer_name": "Vic Torino",
    "title": "Test Case",
    "clues": [{"description": "A bloody glove", "is_red_herring": False, "location": "Alley"}],
    "suspects": [],
    "locations": [],
    "victim": {"name": "Dead Guy", "cause_of_death": "stabbing", "found_at": "Alley"},
}


@pytest.fixture
def player(db):
    create_player(db)
    return db


@pytest.fixture
def case_with_arrest(player):
    db = player
    case_id = create_case(db, archetype="test", title="Test Case", case_data=MINIMAL_CASE)
    loc_id = create_location(db, name="Alley", description="Dark.", is_fixed=False, case_id=case_id)
    npc_id = create_npc(db, case_id=case_id, name="Vic Torino", role="suspect",
                        system_prompt="You are Vic.", current_location_id=loc_id)
    clue_id = db.execute(
        "INSERT INTO clues (case_id, description, location) VALUES (?, ?, ?)",
        (case_id, "A bloody glove", "Alley")
    ).lastrowid
    db.commit()
    add_evidence(db, case_id=case_id, clue_id=clue_id, source_npc_id=None, location_id=loc_id)
    create_arrest(db, case_id=case_id, npc_id=npc_id,
                  evidence_summary="glove", was_correct=True)
    return db, case_id, npc_id


# ---------------------------------------------------------------------------
# Cash
# ---------------------------------------------------------------------------

def test_player_cash_default(player):
    p = get_player(player)
    assert p["cash"] == 500


def test_update_player_cash_add(player):
    update_player_cash(player, delta=100)
    assert get_player_cash(player) == 600


def test_update_player_cash_subtract(player):
    update_player_cash(player, delta=-200)
    assert get_player_cash(player) == 300


def test_update_player_cash_cannot_go_negative(player):
    update_player_cash(player, delta=-9999)
    assert get_player_cash(player) == 0


# ---------------------------------------------------------------------------
# NPC corruption
# ---------------------------------------------------------------------------

def test_npc_corruption_default(player):
    loc_id = create_location(player, name="Alley", description="Dark.", is_fixed=False, case_id=None)
    npc_id = create_npc(player, case_id=None, name="Lou", role="bartender",
                        system_prompt="You are Lou.", current_location_id=loc_id)
    assert get_npc_corruption(player, npc_id) == 0


def test_set_npc_corruption(player):
    loc_id = create_location(player, name="Alley", description="Dark.", is_fixed=False, case_id=None)
    npc_id = create_npc(player, case_id=None, name="Bergeron", role="judge",
                        system_prompt="You are the judge.", current_location_id=loc_id)
    set_npc_corruption(player, npc_id, 9)
    assert get_npc_corruption(player, npc_id) == 9


# ---------------------------------------------------------------------------
# Bribe recording
# ---------------------------------------------------------------------------

def test_record_bribe_accepted(case_with_arrest):
    db, case_id, npc_id = case_with_arrest
    record_bribe(db, case_id=case_id, npc_id=npc_id, amount=200,
                 accepted=True, effect="verdict_influence")
    bribes = get_accepted_bribes_for_case(db, case_id)
    assert len(bribes) == 1
    assert bribes[0]["amount"] == 200
    assert bribes[0]["effect"] == "verdict_influence"


def test_record_bribe_rejected_not_returned(case_with_arrest):
    db, case_id, npc_id = case_with_arrest
    record_bribe(db, case_id=case_id, npc_id=npc_id, amount=50,
                 accepted=False, effect=None)
    assert get_accepted_bribes_for_case(db, case_id) == []


def test_get_accepted_bribes_scoped_to_case(case_with_arrest):
    db, case_id, npc_id = case_with_arrest
    other_case_id = create_case(db, archetype="test", title="Other Case", case_data=MINIMAL_CASE)
    record_bribe(db, case_id=other_case_id, npc_id=npc_id, amount=100,
                 accepted=True, effect="general")
    record_bribe(db, case_id=case_id, npc_id=npc_id, amount=200,
                 accepted=True, effect="verdict_influence")
    bribes = get_accepted_bribes_for_case(db, case_id)
    assert len(bribes) == 1
    assert bribes[0]["effect"] == "verdict_influence"


def test_multiple_accepted_bribes(case_with_arrest):
    db, case_id, npc_id = case_with_arrest
    record_bribe(db, case_id=case_id, npc_id=npc_id, amount=100,
                 accepted=True, effect="magistrate_clear")
    record_bribe(db, case_id=case_id, npc_id=npc_id, amount=300,
                 accepted=True, effect="verdict_influence")
    bribes = get_accepted_bribes_for_case(db, case_id)
    assert len(bribes) == 2


# ---------------------------------------------------------------------------
# Payroll
# ---------------------------------------------------------------------------

def _add_player_to_org(db, org_name: str, payroll: int, last_time: int = 0):
    org = db.execute("SELECT id FROM organizations WHERE name=?", (org_name,)).fetchone()
    if not org:
        org_id = db.execute(
            "INSERT INTO organizations (name, type, description, influence) VALUES (?,?,?,?)",
            (org_name, "crime_family", "Test org.", 6)
        ).lastrowid
        db.commit()
    else:
        org_id = org["id"]
    db.execute(
        """INSERT INTO organization_members
           (organization_id, member_type, member_id, role, payroll, last_payroll_time)
           VALUES (?, 'player', 1, 'associate', ?, ?)""",
        (org_id, payroll, last_time)
    )
    db.commit()
    return org_id


def test_payroll_pays_when_due(player):
    _add_player_to_org(player, "Rossi Crime Family", payroll=100, last_time=0)
    payouts = collect_org_payroll(player, current_game_time=1441)
    assert len(payouts) == 1
    assert payouts[0]["amount"] == 100
    assert get_player_cash(player) == 600  # 500 + 100


def test_payroll_does_not_pay_before_threshold(player):
    _add_player_to_org(player, "Rossi Crime Family", payroll=100, last_time=0)
    payouts = collect_org_payroll(player, current_game_time=500)
    assert payouts == []
    assert get_player_cash(player) == 500  # unchanged


def test_payroll_updates_last_time(player):
    _add_player_to_org(player, "Rossi Crime Family", payroll=100, last_time=0)
    collect_org_payroll(player, current_game_time=1500)
    # Second call at same time should not pay again
    payouts = collect_org_payroll(player, current_game_time=1500)
    assert payouts == []


def test_payroll_no_membership_returns_empty(player):
    assert collect_org_payroll(player, current_game_time=9999) == []


def test_payroll_multiple_orgs(player):
    _add_player_to_org(player, "Rossi Crime Family", payroll=100, last_time=0)
    _add_player_to_org(player, "Castellano Crime Family", payroll=80, last_time=0)
    payouts = collect_org_payroll(player, current_game_time=2000)
    assert len(payouts) == 2
    assert get_player_cash(player) == 680  # 500 + 100 + 80


def test_payroll_zero_payroll_not_paid(player):
    _add_player_to_org(player, "Noirleans Bar Association", payroll=0, last_time=0)
    payouts = collect_org_payroll(player, current_game_time=9999)
    assert payouts == []


# ---------------------------------------------------------------------------
# Org eligibility
# ---------------------------------------------------------------------------

def test_no_gates_org_passes(player):
    result = check_org_eligibility(player, "Noirleans Bar Association",
                                   {"race": "white", "gender": "male", "law_chaos": 0, "reputation": 100})
    assert result is None


def test_race_gate_blocks_wrong_race(player):
    result = check_org_eligibility(player, "Treme Social Aid and Pleasure Club",
                                   {"race": "white", "gender": "male", "law_chaos": 0, "reputation": 100})
    assert result is not None


def test_race_gate_passes_correct_race(player):
    result = check_org_eligibility(player, "Treme Social Aid and Pleasure Club",
                                   {"race": "black", "gender": "female", "law_chaos": 0, "reputation": 100})
    assert result is None


def test_race_gate_passes_creole(player):
    result = check_org_eligibility(player, "Treme Social Aid and Pleasure Club",
                                   {"race": "creole", "gender": "male", "law_chaos": 0, "reputation": 100})
    assert result is None


def test_gender_gate_blocks_wrong_gender(player):
    result = check_org_eligibility(player, "Knights of Columbus",
                                   {"race": "white", "gender": "female", "law_chaos": 0, "reputation": 100})
    assert result is not None


def test_gender_gate_passes_correct_gender(player):
    result = check_org_eligibility(player, "Knights of Columbus",
                                   {"race": "white", "gender": "male", "law_chaos": 0, "reputation": 100})
    assert result is None


def test_chaos_gate_blocks_too_lawful(player):
    result = check_org_eligibility(player, "Rossi Crime Family",
                                   {"race": "white", "gender": "male", "law_chaos": 5, "reputation": 100})
    assert result is not None


def test_chaos_gate_passes_sufficient_chaos(player):
    result = check_org_eligibility(player, "Rossi Crime Family",
                                   {"race": "white", "gender": "male", "law_chaos": 15, "reputation": 100})
    assert result is None


def test_castellano_lower_chaos_threshold(player):
    # Castellano requires min_chaos=5; Rossi requires 10
    result = check_org_eligibility(player, "Castellano Crime Family",
                                   {"race": "white", "gender": "male", "law_chaos": 7, "reputation": 100})
    assert result is None


def test_rep_gate_blocks_low_rep(player):
    result = check_org_eligibility(player, "New Orleans Athletic Club",
                                   {"race": "white", "gender": "male", "law_chaos": 0, "reputation": 20})
    assert result is not None


def test_rep_gate_passes_sufficient_rep(player):
    result = check_org_eligibility(player, "New Orleans Athletic Club",
                                   {"race": "white", "gender": "male", "law_chaos": 0, "reputation": 60})
    assert result is None


def test_non_joinable_org_always_rejects(player):
    result = check_org_eligibility(player, "Orleans Parish Judiciary",
                                   {"race": "white", "gender": "male", "law_chaos": 0, "reputation": 100})
    assert result is not None


def test_unknown_org_passes_no_gates(player):
    result = check_org_eligibility(player, "Some Random Club",
                                   {"race": "white", "gender": "male", "law_chaos": 0, "reputation": 100})
    assert result is None


def test_race_and_gender_both_required(player):
    # Athletic Club needs white + male — wrong race should block even with correct gender
    result = check_org_eligibility(player, "New Orleans Athletic Club",
                                   {"race": "black", "gender": "male", "law_chaos": 0, "reputation": 60})
    assert result is not None


# ---------------------------------------------------------------------------
# Trial: magistrate_clear bribe bypasses LLM review
# ---------------------------------------------------------------------------

def test_magistrate_clear_bribe_bypasses_review(case_with_arrest, mock_llm):
    db, case_id, npc_id = case_with_arrest
    update_case_status(db, case_id=case_id, status="pending_magistrate")
    # Record an accepted magistrate_clear bribe
    record_bribe(db, case_id=case_id, npc_id=npc_id, amount=150,
                 accepted=True, effect="magistrate_clear")

    ts = TrialSystem(conn=db, case_id=case_id, llm=mock_llm)
    result = ts.submit_to_magistrate()

    assert result["cleared"] is True
    # LLM should NOT have been called (no structured calls for the magistrate review)
    assert len(mock_llm.calls) == 0


def test_magistrate_no_bribe_calls_llm(case_with_arrest, mock_llm):
    db, case_id, npc_id = case_with_arrest
    update_case_status(db, case_id=case_id, status="pending_magistrate")
    mock_llm._responses = cycle([json.dumps({
        "cleared": True,
        "dialogue": "Case cleared.",
        "reasoning": "Probable cause found.",
        "assigned_judge": None,
    })])

    ts = TrialSystem(conn=db, case_id=case_id, llm=mock_llm)
    result = ts.submit_to_magistrate()

    assert len(mock_llm.calls) > 0


# ---------------------------------------------------------------------------
# Trial: verdict_influence bribe overrides innocence
# ---------------------------------------------------------------------------

def test_verdict_influence_bribe_overrides_wrong_arrest(case_with_arrest, mock_llm):
    db, case_id, npc_id = case_with_arrest
    # Mark arrest as wrong (innocent suspect)
    db.execute("UPDATE arrests SET was_correct=0 WHERE case_id=?", (case_id,))
    db.commit()

    update_case_status(db, case_id=case_id, status="in_trial",
                       trial_end_time="0")  # already expired
    record_bribe(db, case_id=case_id, npc_id=npc_id, amount=500,
                 accepted=True, effect="verdict_influence")

    mock_llm._responses = cycle([json.dumps({
        "outcome": "guilty",
        "summary": "The gavel fell. The defendant was guilty.",
    })])

    ts = TrialSystem(conn=db, case_id=case_id, llm=mock_llm)
    case = db.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    verdict = ts._generate_verdict(case)

    # Bribe should have forced was_correct=True, so no wrong-arrest reputation hit
    player = get_player(db)
    assert player["wrong_arrests"] == 0


def test_no_verdict_bribe_wrong_arrest_penalises(case_with_arrest, mock_llm):
    db, case_id, npc_id = case_with_arrest
    db.execute("UPDATE arrests SET was_correct=0 WHERE case_id=?", (case_id,))
    db.commit()
    update_case_status(db, case_id=case_id, status="in_trial", trial_end_time="0")

    mock_llm._responses = cycle([json.dumps({
        "outcome": "not_guilty",
        "summary": "Insufficient evidence.",
    })])

    ts = TrialSystem(conn=db, case_id=case_id, llm=mock_llm)
    case = db.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    ts._generate_verdict(case)

    player = get_player(db)
    assert player["wrong_arrests"] == 1
