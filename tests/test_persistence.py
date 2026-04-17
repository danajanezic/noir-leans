import sqlite3
from noir.persistence.db import create_schema
from noir.persistence.repository import (
    create_player, get_player, update_player_reputation,
    save_partner, get_partner,
    append_history, get_history,
    create_location, get_location,
    create_case, get_case, update_case_status,
    create_npc, get_npc, get_npcs_for_case,
    set_character_location, get_character_location,
    add_evidence, get_evidence_for_case,
    create_arrest,
    save_archetype, get_archetype, list_archetypes,
)


def test_create_schema_creates_all_tables():
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    tables = {
        row[0] for row in
        conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    expected = {
        "player", "partner", "conversation_history", "cases",
        "locations", "npcs", "evidence", "arrests",
        "character_locations", "mystery_archetypes",
    }
    assert expected.issubset(tables)
    conn.close()


def test_create_schema_is_idempotent():
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    create_schema(conn)  # must not raise
    conn.close()


def test_player_create_and_get(db):
    create_player(db)
    player = get_player(db)
    assert player["reputation"] == 100
    assert player["cases_solved"] == 0


def test_player_reputation_update(db):
    create_player(db)
    update_player_reputation(db, delta=-10)
    assert get_player(db)["reputation"] == 90


def test_partner_save_and_get(db):
    create_player(db)
    save_partner(db, name="Vera", sex="female", personality_archetype="world-weary cynic",
                 speech_style="terse and hard-boiled", relationship_stance="exasperated",
                 system_prompt="You are Vera.")
    partner = get_partner(db)
    assert partner["name"] == "Vera"
    assert partner["sex"] == "female"


def test_conversation_history_append_and_get(db):
    append_history(db, character_id="partner", role="user", content="Hello Vera", case_id=None)
    append_history(db, character_id="partner", role="assistant", content="What now.", case_id=None)
    history = get_history(db, character_id="partner")
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["content"] == "What now."


def test_location_create_and_get(db):
    loc_id = create_location(db, name="The Rusty Anchor", description="A bar of ill repute.", is_fixed=True)
    loc = get_location(db, loc_id)
    assert loc["name"] == "The Rusty Anchor"
    assert loc["is_fixed"] == 1


def test_case_create_and_get(db):
    case_data = {"victim": "Gerald Fitch", "killer_npc_id": 1}
    case_id = create_case(db, archetype="Agatha Christie", title="The Fitch Affair", case_data=case_data)
    case = get_case(db, case_id)
    assert case["title"] == "The Fitch Affair"
    assert case["status"] == "active"


def test_case_status_update(db):
    case_id = create_case(db, archetype="Chinatown", title="Test", case_data={})
    update_case_status(db, case_id=case_id, status="submitted")
    assert get_case(db, case_id)["status"] == "submitted"


def test_npc_create_and_get(db):
    case_id = create_case(db, archetype="Hammett", title="Test", case_data={})
    loc_id = create_location(db, name="Diner", description="Greasy.", is_fixed=True)
    npc_id = create_npc(db, case_id=case_id, name="Dolores", role="suspect",
                        system_prompt="You are Dolores.", current_location_id=loc_id)
    npc = get_npc(db, npc_id)
    assert npc["name"] == "Dolores"
    npcs = get_npcs_for_case(db, case_id)
    assert len(npcs) == 1


def test_character_location(db):
    loc_id = create_location(db, name="Alley", description="Dark.", is_fixed=True)
    set_character_location(db, character_id="npc_1", location_id=loc_id)
    result = get_character_location(db, "npc_1")
    assert result == loc_id


def test_evidence_add_and_get(db):
    case_id = create_case(db, archetype="Blanc", title="Test", case_data={})
    loc_id = create_location(db, name="Study", description="Books.", is_fixed=False, case_id=case_id)
    add_evidence(db, case_id=case_id, description="A monogrammed glove",
                 source_npc_id=None, location_id=loc_id)
    evidence = get_evidence_for_case(db, case_id)
    assert len(evidence) == 1
    assert evidence[0]["description"] == "A monogrammed glove"


def test_arrest_create(db):
    case_id = create_case(db, archetype="Chinatown", title="Test", case_data={})
    loc_id = create_location(db, name="Office", description="Dusty.", is_fixed=True)
    npc_id = create_npc(db, case_id=case_id, name="Rex", role="suspect",
                        system_prompt="You are Rex.", current_location_id=loc_id)
    create_arrest(db, case_id=case_id, npc_id=npc_id, evidence_summary="A glove and a grudge")
    arrests = db.execute("SELECT * FROM arrests WHERE case_id=?", (case_id,)).fetchall()
    assert len(arrests) == 1


def test_archetype_save_and_list(db):
    save_archetype(db, name="Agatha Christie",
                   description="Closed-room social intrigue",
                   seed_prompt="You are generating an Agatha Christie style mystery...")
    archetypes = list_archetypes(db)
    assert len(archetypes) == 1
    assert get_archetype(db, "Agatha Christie")["description"] == "Closed-room social intrigue"
