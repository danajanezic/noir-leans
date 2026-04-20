"""Tests for single-turn (step) execution mode."""
import json
import sqlite3
import pytest
from io import StringIO

from noir.persistence.db import create_schema
from noir.persistence.repository import (
    create_player, save_partner, create_case, create_location,
    create_npc, create_clue, create_suspect, mark_suspect_met,
    get_evidence_for_case, get_character_location, get_partner,
)
from noir.llm.mock import MockLLMBackend
from noir.step import run_step


MINIMAL_CASE = {
    "killer_name": "Rex Fontaine",
    "victim": {"name": "Gerald Fitch", "cause_of_death": "trombone", "found_at": "The Jazz Club"},
    "suspects": [
        {"name": "Rex Fontaine", "role": "suspect", "alibi": "I was home", "secret": "did it",
         "personality": "cold", "speech_style": "clipped", "race": "white",
         "political_connections": "none", "backstory": "Bad guy.", "routine": [], "relationships": []},
    ],
    "clues": [
        {"description": "A monogrammed cufflink", "is_red_herring": False, "location": "The Jazz Club"},
    ],
    "locations": [{"name": "The Jazz Club", "description": "Smoky and loud."}],
}

PARTNER_RESPONSE = json.dumps({
    "name": "Sam Wolfe", "sex": "male",
    "personality_archetype": "world-weary cynic",
    "speech_style": "terse", "relationship_stance": "exasperated",
    "system_prompt": "You are Sam Wolfe, a world-weary detective partner.",
})

CASE_RESPONSE = json.dumps(MINIMAL_CASE)


@pytest.fixture
def fresh_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    create_player(conn)
    yield conn
    conn.close()


@pytest.fixture
def db_with_partner(fresh_db):
    save_partner(fresh_db, name="Riley Mack", sex="female",
                 personality_archetype="world-weary cynic",
                 speech_style="terse", relationship_stance="exasperated",
                 system_prompt="You are Riley Mack.")
    return fresh_db


@pytest.fixture
def db_with_case(db_with_partner):
    db = db_with_partner
    case_id = create_case(db, archetype="Christie", title="The Fitch Affair",
                          case_data=MINIMAL_CASE)
    loc_id = create_location(db, name="The Jazz Club", description="Smoky.",
                             is_fixed=False, case_id=case_id)
    create_location(db, name="The Precinct", description="Grim.", is_fixed=True)
    npc_id = create_npc(db, case_id=case_id, name="Rex Fontaine", role="suspect",
                        system_prompt="You are Rex.", current_location_id=loc_id)
    create_suspect(db, case_id=case_id, npc_id=npc_id, is_killer=True)
    return db, case_id, loc_id, npc_id


# --- onboard ---

def test_onboard_creates_partner(fresh_db):
    llm = MockLLMBackend(responses=[
        json.dumps({"incident": "lost your hat in a poker game"}),
        PARTNER_RESPONSE,
        "Good to meet you, detective.",  # partner intro narration
    ])
    out = StringIO()
    result = run_step(
        {"type": "onboard", "race": "Black", "gender": "man",
         "answers": ["A", "B", "C", "A", "B", "D", "A", "A"]},
        conn=fresh_db, llm=llm, stdout=out,
    )
    assert result["ok"] is True
    partner = get_partner(fresh_db)
    assert partner is not None
    assert partner["name"] == "Sam Wolfe"


def test_onboard_saves_player_identity(fresh_db):
    llm = MockLLMBackend(responses=[
        json.dumps({"incident": "lost a bet on a mule race"}),
        PARTNER_RESPONSE,
        "Right then.",
    ])
    run_step(
        {"type": "onboard", "race": "Creole", "gender": "woman",
         "answers": ["A", "A", "A", "A", "A", "A", "A", "A"]},
        conn=fresh_db, llm=llm, stdout=StringIO(),
    )
    player = fresh_db.execute("SELECT race, gender FROM player WHERE id=1").fetchone()
    assert player["race"] == "Creole"
    assert player["gender"] == "woman"


def test_onboard_error_if_partner_exists(db_with_partner):
    llm = MockLLMBackend()
    result = run_step(
        {"type": "onboard", "race": "white", "gender": "man",
         "answers": ["A"] * 8},
        conn=db_with_partner, llm=llm, stdout=StringIO(),
    )
    assert result["ok"] is False
    assert "already" in result["error"].lower()


# --- command: slash ---

def test_command_locations(db_with_case):
    db, case_id, loc_id, _ = db_with_case
    out = StringIO()
    result = run_step({"type": "command", "input": "/locations"}, conn=db, llm=MockLLMBackend(), stdout=out)
    assert result["ok"] is True
    assert "Jazz Club" in out.getvalue()


def test_command_evidence_empty(db_with_case):
    db, case_id, loc_id, _ = db_with_case
    out = StringIO()
    result = run_step({"type": "command", "input": "/evidence"}, conn=db, llm=MockLLMBackend(), stdout=out)
    assert result["ok"] is True
    assert out.getvalue()


def test_command_go_moves_player(db_with_case):
    db, case_id, loc_id, _ = db_with_case
    llm = MockLLMBackend(responses=["The Jazz Club. Cigarettes and regret."])
    run_step({"type": "command", "input": "/go The Jazz Club"}, conn=db, llm=llm, stdout=StringIO())
    assert get_character_location(db, "player") == loc_id


# --- command: talk npc ---

def test_command_talk_npc_single_exchange(db_with_case):
    db, case_id, loc_id, npc_id = db_with_case
    mark_suspect_met(db, npc_id=npc_id)
    llm = MockLLMBackend(responses=[
        "I was home all night. Ask anybody.",
        '{"facts": []}',
        '{"pressure_applied": false, "threat_made": false, "kindness_shown": false, "guilt_trigger": false, "evidence_confronted": false}',
    ])
    out = StringIO()
    result = run_step(
        {"type": "command", "input": "talk Rex Fontaine: Where were you?"},
        conn=db, llm=llm, stdout=out,
    )
    assert result["ok"] is True
    assert "Rex Fontaine" in out.getvalue()
    assert "home all night" in out.getvalue()


def test_command_talk_npc_not_found(db_with_case):
    db, case_id, loc_id, _ = db_with_case
    result = run_step(
        {"type": "command", "input": "talk Nobody McFake: Hello?"},
        conn=db, llm=MockLLMBackend(), stdout=StringIO(),
    )
    assert result["ok"] is False


# --- command: talk partner ---

def test_command_talk_partner_single_exchange(db_with_case):
    db, case_id, loc_id, _ = db_with_case
    llm = MockLLMBackend(responses=[json.dumps({
        "dialogue": "We should check the Jazz Club.", "action": None, "target": None, "moved_npc": None,
    })])
    out = StringIO()
    result = run_step(
        {"type": "command", "input": "talk partner: What next?"},
        conn=db, llm=llm, stdout=out,
    )
    assert result["ok"] is True
    assert "Riley Mack" in out.getvalue()


# --- command: natural language falls through to partner ---

def test_command_natural_language_routes_to_partner(db_with_case):
    db, case_id, loc_id, _ = db_with_case
    llm = MockLLMBackend(responses=[json.dumps({
        "dialogue": "Let's head to the crime scene.", "action": None, "target": None, "moved_npc": None,
    })])
    out = StringIO()
    result = run_step(
        {"type": "command", "input": "I want to look around"},
        conn=db, llm=llm, stdout=out,
    )
    assert result["ok"] is True
    assert "Riley Mack" in out.getvalue()


# --- no active case ---

def test_command_without_case_returns_error(db_with_partner):
    result = run_step(
        {"type": "command", "input": "/locations"},
        conn=db_with_partner, llm=MockLLMBackend(), stdout=StringIO(),
    )
    assert result["ok"] is False
    assert "case" in result["error"].lower()


# --- accuse ---

def test_accuse_correct_suspect(db_with_case):
    db, case_id, loc_id, npc_id = db_with_case
    result = run_step(
        {"type": "accuse", "target": "Rex Fontaine"},
        conn=db, llm=MockLLMBackend(), stdout=StringIO(),
    )
    assert result["ok"] is True
    assert result["verdict"]["accused"] == "Rex Fontaine"
    assert result["verdict"]["correct"] is True


def test_accuse_wrong_suspect(db_with_case):
    db, case_id, loc_id, npc_id = db_with_case
    from noir.persistence.repository import create_npc, create_suspect
    innocent_id = create_npc(db, case_id=case_id, name="Vera Mills", role="witness",
                             system_prompt="You are Vera.", current_location_id=loc_id)
    create_suspect(db, case_id=case_id, npc_id=innocent_id, is_killer=False)
    result = run_step(
        {"type": "accuse", "target": "Vera Mills"},
        conn=db, llm=MockLLMBackend(), stdout=StringIO(),
    )
    assert result["ok"] is True
    assert result["verdict"]["correct"] is False


def test_accuse_unknown_target(db_with_case):
    db, case_id, loc_id, _ = db_with_case
    result = run_step(
        {"type": "accuse", "target": "Nobody McFake"},
        conn=db, llm=MockLLMBackend(), stdout=StringIO(),
    )
    assert result["ok"] is False
    assert "find" in result["error"].lower()


def test_accuse_no_active_case(db_with_partner):
    result = run_step(
        {"type": "accuse", "target": "Rex Fontaine"},
        conn=db_with_partner, llm=MockLLMBackend(), stdout=StringIO(),
    )
    assert result["ok"] is False
    assert "case" in result["error"].lower()


# --- state in result ---

def test_result_includes_game_state(db_with_case):
    db, case_id, loc_id, _ = db_with_case
    result = run_step({"type": "command", "input": "/evidence"}, conn=db, llm=MockLLMBackend(), stdout=StringIO())
    assert "state" in result
    state = result["state"]
    assert state["active_case"] == "The Fitch Affair"
    assert "evidence_count" in state
    assert "reputation" in state
