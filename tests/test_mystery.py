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
    "victim": {"name": "Gerald Fitch", "cause_of_death": "spontaneous accordion implosion"},
    "killer_name": "Dolores Mink",
    "motive": "Gerald knew about her collection of illegal flamingos",
    "suspects": [
        {
            "name": "Dolores Mink",
            "role": "suspect",
            "alibi": "Claims she was at the flamingo sanctuary",
            "secret": "She owns the flamingos",
            "personality": "Aggressively cheerful",
            "speech_style": "Speaks exclusively in the third person",
            "race": "White",
            "political_connections": "None",
            "backstory": "Raised flamingos since childhood, turned it into a criminal empire.",
            "routine": "Opens the sanctuary at dawn, counts flamingos at dusk."
        },
        {
            "name": "Reginald Smoot",
            "role": "suspect",
            "alibi": "Was definitely not at the scene",
            "secret": "Owes Gerald money",
            "personality": "Aggressively normal",
            "speech_style": "Uses the wrong word constantly",
            "race": "White",
            "political_connections": "None",
            "backstory": "Failed accordion salesman turned debtor.",
            "routine": "Drinks at the Rusty Anchor every evening."
        }
    ],
    "clues": [
        {"description": "A flamingo feather on the accordion", "is_red_herring": False, "location": "The Music Room"},
        {"description": "A receipt from the flamingo sanctuary", "is_red_herring": False, "location": "The Victim's Desk"},
        {"description": "Reginald's IOU note", "is_red_herring": True, "location": "The Parlour"}
    ],
    "locations": [
        {"name": "The Music Room", "description": "Smells of rosin and regret"},
        {"name": "The Victim's Desk", "description": "Piled with incomprehensible ledgers"},
        {"name": "The Parlour", "description": "A room for sitting and being suspicious in"}
    ]
}


def test_generate_returns_validated_case_structure(db, mock_llm):
    create_player(db)
    mock_llm._responses = cycle([json.dumps(VALID_CASE)])
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
    mock_llm._responses = cycle([json.dumps(VALID_CASE)])
    gen = MysteryGenerator(llm=mock_llm, conn=db)
    gen.generate(archetype_name="Agatha Christie")
    last_call = mock_llm.calls[-1]
    assert "difficulty" in last_call["user_input"].lower() or "player" in last_call["user_input"].lower()


def test_generate_includes_archetype_seed_in_prompt(db, mock_llm):
    seed_archetypes_to_db(db)
    create_player(db)
    mock_llm._responses = cycle([json.dumps(VALID_CASE)])
    gen = MysteryGenerator(llm=mock_llm, conn=db)
    gen.generate(archetype_name="Agatha Christie")
    last_call = mock_llm.calls[-1]
    assert "Agatha Christie" in last_call["user_input"]


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
