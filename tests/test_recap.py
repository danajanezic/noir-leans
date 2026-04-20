import json
import pytest
from noir.persistence.db import create_schema
from noir.persistence.repository import (
    create_player, create_case, create_location, create_npc,
    create_clue, add_evidence, link_evidence_to_suspect,
    add_dossier_facts, create_suspect, mark_suspect_met,
    set_character_location,
)
from noir.recap import build_case_recap


CASE_DATA = {
    "killer_name": "Dolores Mink",
    "victim": {"name": "Gerald Fitch", "cause_of_death": "trombone", "found_at": "The Jazz Club"},
    "suspects": [
        {"name": "Dolores Mink", "role": "suspect", "alibi": "I was at home", "secret": "she did it",
         "personality": "cold", "speech_style": "clipped", "race": "white",
         "political_connections": "none", "backstory": "...", "routine": [], "relationships": []},
        {"name": "Marcel Fontenot", "role": "witness", "alibi": "playing cards", "secret": "gambling debts",
         "personality": "nervous", "speech_style": "stammering", "race": "Creole",
         "political_connections": "none", "backstory": "...", "routine": [], "relationships": []},
        {"name": "Vivian LaRue", "role": "suspect", "alibi": "at the club", "secret": "affair",
         "personality": "charming", "speech_style": "smooth", "race": "Black",
         "political_connections": "alderman", "backstory": "...", "routine": [], "relationships": []},
    ],
    "clues": [],
    "locations": [
        {"name": "The Jazz Club", "description": "Smoky."},
        {"name": "The Warehouse", "description": "Dark."},
    ],
}


@pytest.fixture
def recap_db():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    create_player(conn)
    yield conn
    conn.close()


@pytest.fixture
def full_case(recap_db):
    db = recap_db
    case_id = create_case(db, archetype="Christie", title="The Fitch Affair", case_data=CASE_DATA)
    jazz_loc = create_location(db, name="The Jazz Club", description="Smoky.", case_id=case_id)
    warehouse_loc = create_location(db, name="The Warehouse", description="Dark.", case_id=case_id)
    precinct_loc = create_location(db, name="The Precinct", description="Grim.", is_fixed=True)

    dolores_id = create_npc(db, case_id=case_id, name="Dolores Mink", role="suspect",
                            system_prompt="You are Dolores.", current_location_id=jazz_loc)
    marcel_id = create_npc(db, case_id=case_id, name="Marcel Fontenot", role="witness",
                           system_prompt="You are Marcel.", current_location_id=warehouse_loc)
    vivian_id = create_npc(db, case_id=case_id, name="Vivian LaRue", role="suspect",
                           system_prompt="You are Vivian.", current_location_id=warehouse_loc)

    create_suspect(db, case_id=case_id, npc_id=dolores_id, is_killer=True)
    create_suspect(db, case_id=case_id, npc_id=marcel_id, is_killer=False)
    create_suspect(db, case_id=case_id, npc_id=vivian_id, is_killer=False)
    mark_suspect_met(db, npc_id=dolores_id)
    mark_suspect_met(db, npc_id=marcel_id)

    clue1 = create_clue(db, case_id=case_id, description="A monogrammed cufflink", location="The Jazz Club")
    clue2 = create_clue(db, case_id=case_id, description="A torn receipt from Café Lune", location="The Warehouse")
    clue3 = create_clue(db, case_id=case_id, description="A red matchbook", location="The Jazz Club", is_red_herring=True)

    ev1 = add_evidence(db, case_id=case_id, clue_id=clue1, source_npc_id=None, location_id=jazz_loc)
    ev2 = add_evidence(db, case_id=case_id, clue_id=clue2, source_npc_id=None, location_id=warehouse_loc)
    link_evidence_to_suspect(db, evidence_id=ev1, npc_id=dolores_id)

    add_dossier_facts(db, case_id=case_id, npc_name="Dolores Mink",
                      facts=["Lied about being home that night", "Knew the victim for years"])
    add_dossier_facts(db, case_id=case_id, npc_name="Marcel Fontenot",
                      facts=["Owes money to three different people"])

    set_character_location(db, character_id="player", location_id=jazz_loc)

    return db, case_id, {
        "jazz_loc": jazz_loc, "warehouse_loc": warehouse_loc,
        "dolores_id": dolores_id, "marcel_id": marcel_id, "vivian_id": vivian_id,
    }


def test_recap_includes_victim_info(full_case):
    db, case_id, _ = full_case
    recap = build_case_recap(db, case_id)
    assert recap["victim_name"] == "Gerald Fitch"
    assert recap["cause_of_death"] == "trombone"
    assert recap["found_at"] == "The Jazz Club"


def test_recap_includes_evidence(full_case):
    db, case_id, ids = full_case
    recap = build_case_recap(db, case_id)
    assert recap["evidence_count"] == 2
    descs = [e["description"] for e in recap["evidence"]]
    assert "A monogrammed cufflink" in descs
    assert "A torn receipt from Café Lune" in descs


def test_recap_evidence_shows_accused_link(full_case):
    db, case_id, ids = full_case
    recap = build_case_recap(db, case_id)
    cufflink = next(e for e in recap["evidence"] if "cufflink" in e["description"])
    assert cufflink["accused_npc_name"] == "Dolores Mink"


def test_recap_separates_met_and_unmet_suspects(full_case):
    db, case_id, ids = full_case
    recap = build_case_recap(db, case_id)
    met_names = [s["name"] for s in recap["met_suspects"]]
    unmet_names = [s["name"] for s in recap["unmet_suspects"]]
    assert "Dolores Mink" in met_names
    assert "Marcel Fontenot" in met_names
    assert "Vivian LaRue" in unmet_names


def test_recap_includes_dossier_facts(full_case):
    db, case_id, _ = full_case
    recap = build_case_recap(db, case_id)
    assert "Dolores Mink" in recap["dossier"]
    assert any("Lied" in f for f in recap["dossier"]["Dolores Mink"])
    assert "Marcel Fontenot" in recap["dossier"]


def test_recap_separates_visited_and_unvisited_locations(full_case):
    db, case_id, ids = full_case
    recap = build_case_recap(db, case_id)
    visited = [l["name"] for l in recap["locations_visited"]]
    unvisited = [l["name"] for l in recap["locations_unvisited"]]
    assert "The Jazz Club" in visited
    assert "The Warehouse" in unvisited


def test_recap_no_evidence_case():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    create_player(conn)
    empty_data = {
        "killer_name": "Nobody",
        "victim": {"name": "Vic", "cause_of_death": "unknown", "found_at": "Alley"},
        "suspects": [], "clues": [], "locations": [],
    }
    case_id = create_case(conn, archetype="Test", title="Empty Case", case_data=empty_data)
    recap = build_case_recap(conn, case_id)
    assert recap["evidence_count"] == 0
    assert recap["met_suspects"] == []
    conn.close()
