import json
import pytest
from noir.cases.manager import CaseManager
from noir.persistence.repository import (
    create_player, create_case, create_location,
    create_npc, get_player, get_evidence_for_case
)


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
