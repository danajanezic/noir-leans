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
    create_clue, add_evidence, get_evidence_for_case, link_evidence_to_suspect,
    create_arrest,
    save_archetype, get_archetype, list_archetypes,
    get_npc_affection, set_npc_affection, increment_npc_affection,
    get_npc_relationship_flags, set_npc_clue_volunteered, set_npc_secret_revealed,
    get_partner_affection, increment_partner_affection,
    get_partner_dark_past_state, set_partner_dark_past_state, set_partner_dark_past,
    get_partner_dark_past,
)
from noir.persistence.repository import (
    update_player_alignment, get_alignment
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
        "character_locations", "mystery_archetypes", "npc_relationships",
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
    clue_id = create_clue(db, case_id=case_id, description="A monogrammed glove", location="Study")
    add_evidence(db, case_id=case_id, clue_id=clue_id, source_npc_id=None, location_id=loc_id)
    evidence = get_evidence_for_case(db, case_id)
    assert len(evidence) == 1
    assert evidence[0]["description"] == "A monogrammed glove"


def test_link_evidence_to_suspect(db):
    case_id = create_case(db, archetype="Blanc", title="Test", case_data={})
    loc_id = create_location(db, name="Study", description="Books.", is_fixed=False, case_id=case_id)
    npc_id = create_npc(db, case_id=case_id, name="Marcel", role="suspect",
                        system_prompt="You are Marcel.", current_location_id=loc_id)
    clue_id = create_clue(db, case_id=case_id, description="A bloody cufflink", location="Study")
    ev_id = add_evidence(db, case_id=case_id, clue_id=clue_id, source_npc_id=None, location_id=loc_id)
    link_evidence_to_suspect(db, evidence_id=ev_id, npc_id=npc_id)
    evidence = get_evidence_for_case(db, case_id)
    assert evidence[0]["accused_npc_id"] == npc_id
    assert evidence[0]["accused_npc_name"] == "Marcel"


def test_link_evidence_accused_npc_name_is_none_when_unlinked(db):
    case_id = create_case(db, archetype="Blanc", title="Test", case_data={})
    loc_id = create_location(db, name="Study", description="Books.", is_fixed=False, case_id=case_id)
    clue_id = create_clue(db, case_id=case_id, description="A monogrammed glove", location="Study")
    add_evidence(db, case_id=case_id, clue_id=clue_id, source_npc_id=None, location_id=loc_id)
    evidence = get_evidence_for_case(db, case_id)
    assert evidence[0]["accused_npc_id"] is None
    assert evidence[0]["accused_npc_name"] is None


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


def test_npc_relationships_has_correct_columns():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    cols = {row[1]: row for row in conn.execute("PRAGMA table_info(npc_relationships)").fetchall()}
    assert "npc_id" in cols
    assert "affection" in cols
    assert "clue_volunteered" in cols
    assert "secret_revealed" in cols
    assert cols["affection"]["dflt_value"] == "0"
    assert cols["clue_volunteered"]["dflt_value"] == "0"
    assert cols["secret_revealed"]["dflt_value"] == "0"
    conn.close()


def test_partner_has_romance_columns():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    cols = {row[1]: row for row in conn.execute("PRAGMA table_info(partner)").fetchall()}
    assert "affection" in cols
    assert "dark_past_state" in cols
    assert "dark_past" in cols
    assert cols["affection"]["dflt_value"] == "0"
    assert cols["dark_past_state"]["dflt_value"] == "'none'"
    conn.close()


def test_cases_has_case_type_column():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    cols = {row[1]: row for row in conn.execute("PRAGMA table_info(cases)").fetchall()}
    assert "case_type" in cols
    assert cols["case_type"]["dflt_value"] == "'standard'"
    conn.close()


def test_npc_affection_defaults_to_zero(db):
    case_id = create_case(db, archetype="Test", title="T", case_data={"x": 1})
    loc_id = create_location(db, name="Loc", description="A loc", is_fixed=False, case_id=case_id)
    npc_id = create_npc(db, case_id=case_id, name="Rex", role="suspect",
                        system_prompt="you are Rex", current_location_id=loc_id)
    assert get_npc_affection(db, npc_id) == 0


def test_increment_npc_affection(db):
    case_id = create_case(db, archetype="Test", title="T", case_data={"x": 1})
    loc_id = create_location(db, name="Loc", description="A loc", is_fixed=False, case_id=case_id)
    npc_id = create_npc(db, case_id=case_id, name="Rex", role="suspect",
                        system_prompt="you are Rex", current_location_id=loc_id)
    increment_npc_affection(db, npc_id, delta=8)
    assert get_npc_affection(db, npc_id) == 8
    increment_npc_affection(db, npc_id, delta=8)
    assert get_npc_affection(db, npc_id) == 16


def test_npc_affection_capped_at_100(db):
    case_id = create_case(db, archetype="Test", title="T", case_data={"x": 1})
    loc_id = create_location(db, name="Loc", description="A loc", is_fixed=False, case_id=case_id)
    npc_id = create_npc(db, case_id=case_id, name="Rex", role="suspect",
                        system_prompt="you are Rex", current_location_id=loc_id)
    increment_npc_affection(db, npc_id, delta=200)
    assert get_npc_affection(db, npc_id) == 100


def test_partner_affection(db):
    save_partner(db, name="Vera", sex="female", personality_archetype="cynic",
                 speech_style="terse", relationship_stance="exasperated", system_prompt="you are Vera")
    assert get_partner_affection(db) == 0
    increment_partner_affection(db, delta=15)
    assert get_partner_affection(db) == 15


def test_partner_dark_past_state(db):
    save_partner(db, name="Vera", sex="female", personality_archetype="cynic",
                 speech_style="terse", relationship_stance="exasperated", system_prompt="you are Vera")
    assert get_partner_dark_past_state(db) == "none"
    set_partner_dark_past_state(db, "flagged")
    assert get_partner_dark_past_state(db) == "flagged"


def test_npc_affection_floor(db):
    case_id = create_case(db, archetype="Test", title="T", case_data={"x": 1})
    loc_id = create_location(db, name="Loc", description="A loc", is_fixed=False, case_id=case_id)
    npc_id = create_npc(db, case_id=case_id, name="Rex", role="suspect",
                        system_prompt="you are Rex", current_location_id=loc_id)
    increment_npc_affection(db, npc_id, delta=-50)
    assert get_npc_affection(db, npc_id) == 0


def test_set_npc_affection_cap(db):
    case_id = create_case(db, archetype="Test", title="T", case_data={"x": 1})
    loc_id = create_location(db, name="Loc", description="A loc", is_fixed=False, case_id=case_id)
    npc_id = create_npc(db, case_id=case_id, name="Rex", role="suspect",
                        system_prompt="you are Rex", current_location_id=loc_id)
    set_npc_affection(db, npc_id, 150)
    assert get_npc_affection(db, npc_id) == 100


def test_npc_relationship_flags(db):
    case_id = create_case(db, archetype="Test", title="T", case_data={"x": 1})
    loc_id = create_location(db, name="Loc", description="A loc", is_fixed=False, case_id=case_id)
    npc_id = create_npc(db, case_id=case_id, name="Rex", role="suspect",
                        system_prompt="you are Rex", current_location_id=loc_id)
    flags = get_npc_relationship_flags(db, npc_id)
    assert flags == {"clue_volunteered": 0, "secret_revealed": 0}
    set_npc_clue_volunteered(db, npc_id)
    flags = get_npc_relationship_flags(db, npc_id)
    assert flags["clue_volunteered"] == 1
    assert flags["secret_revealed"] == 0
    set_npc_secret_revealed(db, npc_id)
    flags = get_npc_relationship_flags(db, npc_id)
    assert flags["secret_revealed"] == 1


def test_partner_dark_past_content(db):
    save_partner(db, name="Vera", sex="female", personality_archetype="cynic",
                 speech_style="terse", relationship_stance="exasperated", system_prompt="you are Vera")
    assert get_partner_dark_past(db) is None
    set_partner_dark_past(db, "I did a terrible thing in 1928.")
    assert get_partner_dark_past(db) == "I did a terrible thing in 1928."


def test_get_world_context_returns_nonempty_string():
    from noir.persistence.repository import get_world_context
    result = get_world_context()
    assert isinstance(result, str)
    assert len(result) > 50


def test_get_world_context_contains_noirleans():
    from noir.persistence.repository import get_world_context
    result = get_world_context()
    assert "NOIRLEANS" in result


def test_get_world_context_contains_howie_short():
    from noir.persistence.repository import get_world_context
    result = get_world_context()
    assert "Howie Short" in result


def test_player_has_alignment_columns(db):
    create_player(db)
    player = get_player(db)
    assert player["law_chaos"] == 0
    assert player["good_evil"] == 0

def test_partner_has_alignment_column(db):
    save_partner(db, name="Vera", sex="female", personality_archetype="cynic",
                 speech_style="terse", relationship_stance="exasperated",
                 system_prompt="You are Vera.", alignment="True Neutral")
    partner = get_partner(db)
    assert partner["alignment"] == "True Neutral"

def test_npc_has_alignment_column(db):
    case_id = create_case(db, archetype="test", title="T", case_data={})
    loc_id = create_location(db, name="Bar", description="A bar.", is_fixed=True)
    npc_id = create_npc(db, case_id=case_id, name="Rex", role="suspect",
                        system_prompt="You are Rex.", current_location_id=loc_id,
                        alignment="Chaotic Evil")
    npc = get_npc(db, npc_id)
    assert npc["alignment"] == "Chaotic Evil"


def test_update_player_alignment_sets_scores(db):
    create_player(db)
    update_player_alignment(db, law_delta=6, good_delta=-3)
    player = get_player(db)
    assert player["law_chaos"] == 6
    assert player["good_evil"] == -3

def test_update_player_alignment_accumulates(db):
    create_player(db)
    update_player_alignment(db, law_delta=3, good_delta=2)
    update_player_alignment(db, law_delta=2, good_delta=-1)
    player = get_player(db)
    assert player["law_chaos"] == 5
    assert player["good_evil"] == 1

def test_update_player_alignment_clamps_to_bounds(db):
    create_player(db)
    update_player_alignment(db, law_delta=20, good_delta=-20)
    player = get_player(db)
    assert player["law_chaos"] == 20
    assert player["good_evil"] == -20

def test_get_alignment_lawful_good(db):
    create_player(db)
    update_player_alignment(db, law_delta=5, good_delta=5)
    player = get_player(db)
    assert get_alignment(player) == "Lawful Good"

def test_get_alignment_true_neutral(db):
    create_player(db)
    player = get_player(db)
    assert get_alignment(player) == "True Neutral"

def test_get_alignment_chaotic_evil(db):
    create_player(db)
    update_player_alignment(db, law_delta=-6, good_delta=-6)
    player = get_player(db)
    assert get_alignment(player) == "Chaotic Evil"


def test_create_npc_stores_age(db):
    case_id = create_case(db, archetype="test", title="T", case_data={})
    loc_id = create_location(db, name="Bar", description="A bar.", is_fixed=True)
    npc_id = create_npc(db, case_id=case_id, name="Jake", role="suspect",
                        system_prompt="You are Jake.", current_location_id=loc_id, age=45)
    row = get_npc(db, npc_id)
    assert row["age"] == 45


def test_create_npc_age_defaults_to_35(db):
    case_id = create_case(db, archetype="test", title="T", case_data={})
    loc_id = create_location(db, name="Bar", description="A bar.", is_fixed=True)
    npc_id = create_npc(db, case_id=case_id, name="Jake", role="suspect",
                        system_prompt="You are Jake.", current_location_id=loc_id)
    row = get_npc(db, npc_id)
    assert row["age"] == 35


def test_new_tables_exist(db):
    tables = {
        row[0] for row in
        db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert "player_skills" in tables
    assert "player_specializations" in tables
    assert "skill_events" in tables


def test_alignment_is_unbounded(db):
    create_player(db)
    # Apply large deltas — should not clamp
    for _ in range(20):
        update_player_alignment(db, law_delta=2, good_delta=2)
    player = get_player(db)
    assert player["law_chaos"] == 40
    assert player["good_evil"] == 40
