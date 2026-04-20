import pytest
import json
from itertools import cycle
from noir.mystery.archetype_loader import load_archetypes, seed_archetypes_to_db
from noir.mystery.generator import MysteryGenerator
from noir.persistence.repository import create_player


def test_load_archetypes_returns_all():
    archetypes = load_archetypes()
    names = {a["name"] for a in archetypes}
    assert {"Agatha Christie", "Dashiell Hammett", "Benoit Blanc", "Chinatown"}.issubset(names)


def test_each_archetype_has_required_fields():
    archetypes = load_archetypes()
    for a in archetypes:
        assert "name" in a
        assert "description" in a
        assert "seed_prompt" in a
        assert len(a["seed_prompt"]) > 50


def test_seed_archetypes_to_db(db):
    seed_archetypes_to_db(db)
    from noir.persistence.repository import list_archetypes
    rows = list_archetypes(db)
    assert len(rows) >= 4


VALID_CASE = {
    "title": "The Fitch Affair",
    "victim": {"name": "Gerald Fitch", "cause_of_death": "spontaneous accordion implosion", "found_at": "The Parlour"},
    "killer_name": "Dolores Mink",
    "motive": "Gerald knew about her collection of illegal flamingos",
    "suspects": [
        {
            "name": "Dolores Mink",
            "role": "suspect",
            "alibi": "Claims she was at the flamingo sanctuary",
            "secret": "She owns the flamingos",
            "archetype_id": "femme_fatale",
            "race": "White",
            "political_connections": "None",
            "age": 34,
            "routine": [{"time_start": "09:00", "time_end": "17:00", "location": "The Parlour"}],
            "alignment": "Chaotic Evil",
            "pressure_tolerance": 7,
            "kindness_weight": 3,
            "empathy": 2,
            "starting_guilt": 1,
            "revelation_style": "sudden",
            "revelation_stages": 1,
        },
        {
            "name": "Reginald Smoot",
            "role": "suspect",
            "alibi": "Was definitely not at the scene",
            "secret": "Owes Gerald money",
            "archetype_id": "desperate_debtor",
            "race": "White",
            "political_connections": "None",
            "age": 45,
            "routine": [{"time_start": "09:00", "time_end": "17:00", "location": "The Parlour"}],
            "alignment": "Lawful Neutral",
            "pressure_tolerance": 2,
            "kindness_weight": 5,
            "empathy": 6,
            "starting_guilt": 3,
            "revelation_style": "staged",
            "revelation_stages": 3,
        }
    ],
    "clues": [
        {"description": "A flamingo feather on the accordion", "is_red_herring": False, "location": "The Music Room"},
        {"description": "A receipt from the flamingo sanctuary", "is_red_herring": False, "location": "The Victim's Desk"},
        {"description": "Reginald's IOU note", "is_red_herring": True, "location": "The Parlour"}
    ],
    "locations": [
        {"name": "The Music Room"},
        {"name": "The Victim's Desk"},
        {"name": "The Parlour"}
    ]
}


def test_generate_returns_validated_case_structure(db, mock_llm):
    create_player(db)
    mock_llm._responses = cycle([json.dumps(VALID_CASE), '{"issues": []}'])
    gen = MysteryGenerator(llm=mock_llm, conn=db)
    case = gen.generate(archetype_name="Agatha Christie")
    assert "title" in case
    assert "victim" in case
    assert "suspects" in case
    assert "clues" in case
    assert "locations" in case
    assert len(case["suspects"]) >= 2
    assert len(case["clues"]) >= 1
    assert len(case["locations"]) >= 1


def test_generate_includes_difficulty_calibration_in_prompt(db, mock_llm):
    create_player(db)
    mock_llm._responses = cycle([json.dumps(VALID_CASE), '{"issues": []}'])
    gen = MysteryGenerator(llm=mock_llm, conn=db)
    gen.generate(archetype_name="Agatha Christie")
    # The first call is the generator prompt; subsequent calls are the auditor
    assert any(
        "difficulty" in call["user_input"].lower() or "player" in call["user_input"].lower()
        for call in mock_llm.calls
    )


def test_generate_includes_archetype_seed_in_prompt(db, mock_llm):
    seed_archetypes_to_db(db)
    create_player(db)
    mock_llm._responses = cycle([json.dumps(VALID_CASE), '{"issues": []}'])
    gen = MysteryGenerator(llm=mock_llm, conn=db)
    gen.generate(archetype_name="Agatha Christie")
    # The first call is the generator prompt; subsequent calls are the auditor
    assert any("Agatha Christie" in call["user_input"] for call in mock_llm.calls)


def test_generate_raises_on_missing_required_fields(db, mock_llm):
    create_player(db)
    bad_case = {"title": "incomplete"}
    mock_llm._responses = cycle([json.dumps(bad_case), json.dumps(bad_case)])
    gen = MysteryGenerator(llm=mock_llm, conn=db)
    with pytest.raises(SystemExit):
        gen.generate(archetype_name="Agatha Christie")


def test_generator_system_prompt_contains_world_context():
    from noir.mystery.generator import GENERATOR_SYSTEM_PROMPT
    assert "NOIRLEANS" in GENERATOR_SYSTEM_PROMPT
    assert "Howie Short" in GENERATOR_SYSTEM_PROMPT


def test_generator_system_prompt_does_not_have_hardcoded_fever_dream():
    from noir.mystery.generator import GENERATOR_SYSTEM_PROMPT
    # The old hardcoded description used this phrase — it should be gone
    assert "fever dream" not in GENERATOR_SYSTEM_PROMPT


from noir.mystery.generator import REQUIRED_SUSPECT_FIELDS

def test_required_suspect_fields_includes_alignment():
    assert "alignment" in REQUIRED_SUSPECT_FIELDS


def test_required_suspect_fields_includes_age():
    assert "age" in REQUIRED_SUSPECT_FIELDS


def test_generate_raises_if_age_is_string(db, mock_llm):
    from itertools import cycle as _cycle
    create_player(db)
    bad_case = {
        **VALID_CASE,
        "suspects": [
            {**VALID_CASE["suspects"][0], "age": "38"},  # string, not int
            {**VALID_CASE["suspects"][1]},
        ]
    }
    mock_llm._responses = _cycle([json.dumps(bad_case), json.dumps(bad_case)])
    gen = MysteryGenerator(llm=mock_llm, conn=db)
    with pytest.raises(SystemExit):
        gen.generate(archetype_name="Agatha Christie")


def test_generate_calls_auditor_and_patches_ghost_name(db, mock_llm):
    from itertools import cycle as _cycle
    create_player(db)

    # Case with a ghost name in a clue — Ferdinand Crowe is not a suspect in VALID_CASE
    case_with_ghost = {
        **VALID_CASE,
        "clues": [
            {"description": "A witness saw Ferdinand Crowe leaving the club", "is_red_herring": False, "location": "The Music Room"},
            {"description": "A receipt from the flamingo sanctuary", "is_red_herring": False, "location": "The Victim's Desk"},
        ]
    }
    # First call: generator; second: auditor _llm_check (no semantic issues)
    mock_llm._responses = _cycle([json.dumps(case_with_ghost), '{"issues": []}'])
    gen = MysteryGenerator(llm=mock_llm, conn=db)
    result = gen.generate(archetype_name="Agatha Christie")

    clue_texts = [c["description"] for c in result["clues"]]
    assert not any("Ferdinand Crowe" in t for t in clue_texts)


def test_generate_regenerates_on_killer_mismatch(db, mock_llm):
    from itertools import cycle as _cycle
    create_player(db)

    broken = {**VALID_CASE, "killer_name": "Ghost Person"}
    fixed = VALID_CASE  # killer_name = "Dolores Mink", which IS in suspects
    # calls: generate, llm_check, regenerate
    mock_llm._responses = _cycle([
        json.dumps(broken),
        '{"issues": []}',
        json.dumps(fixed),
    ])
    gen = MysteryGenerator(llm=mock_llm, conn=db)
    result = gen.generate(archetype_name="Agatha Christie")
    assert result["killer_name"] == "Dolores Mink"


from noir.persistence.repository import seed_locations_to_db, get_seeded_location_names, get_seeded_location_description

def test_seed_locations_to_db_and_retrieve(db):
    locations = [
        {"name": "Fournier's Jazz Club", "description": "Low ceiling, high noise.", "type": "club"},
        {"name": "The Rusty Anchor", "description": "Smells of brine and broken promises.", "type": "bar"},
    ]
    seed_locations_to_db(db, locations)
    names = get_seeded_location_names(db)
    assert "Fournier's Jazz Club" in names
    assert "The Rusty Anchor" in names

def test_get_seeded_location_description(db):
    locations = [{"name": "Pilot House", "description": "River views, sticky tables.", "type": "bar"}]
    seed_locations_to_db(db, locations)
    desc = get_seeded_location_description(db, "Pilot House")
    assert desc == "River views, sticky tables."

def test_get_seeded_location_description_unknown_returns_none(db):
    assert get_seeded_location_description(db, "Nonexistent Place") is None

def test_seed_locations_to_db_is_idempotent(db):
    locations = [{"name": "The Blue Room", "description": "Smoky, low-lit.", "type": "club"}]
    seed_locations_to_db(db, locations)
    seed_locations_to_db(db, locations)  # second call must not error or duplicate
    names = get_seeded_location_names(db)
    assert names.count("The Blue Room") == 1

def test_npcs_table_has_psychology_columns(db):
    row = db.execute("PRAGMA table_info(npcs)").fetchall()
    col_names = {r["name"] for r in row}
    assert "pressure_tolerance" in col_names
    assert "kindness_weight" in col_names
    assert "empathy" in col_names
    assert "starting_guilt" in col_names
    assert "revelation_style" in col_names
    assert "revelation_stages" in col_names

def test_npc_relationships_has_psychology_columns(db):
    row = db.execute("PRAGMA table_info(npc_relationships)").fetchall()
    col_names = {r["name"] for r in row}
    assert "guilt" in col_names
    assert "pressure_score" in col_names
    assert "revelation_stage" in col_names

def test_suspects_has_archetype_id_column(db):
    row = db.execute("PRAGMA table_info(suspects)").fetchall()
    col_names = {r["name"] for r in row}
    assert "archetype_id" in col_names
