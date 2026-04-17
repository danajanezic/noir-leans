import pytest
import json
from itertools import cycle
from noir.characters.agent import Agent
from noir.llm.mock import MockLLMBackend
from noir.persistence.repository import get_history


def test_agent_speak_returns_response(db, mock_llm):
    mock_llm._responses = cycle(["Good evening, detective."])
    agent = Agent(
        character_id="partner",
        system_prompt="You are a cynical detective's partner.",
        llm=mock_llm,
        conn=db,
    )
    response = agent.speak("Hello")
    assert response == "Good evening, detective."


def test_agent_speak_persists_history(db, mock_llm):
    mock_llm._responses = cycle(["Sure thing."])
    agent = Agent(
        character_id="npc_1",
        system_prompt="You are a suspect.",
        llm=mock_llm,
        conn=db,
    )
    agent.speak("Where were you last Tuesday?")
    history = get_history(db, character_id="npc_1")
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Where were you last Tuesday?"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "Sure thing."


def test_agent_speak_passes_history_to_llm(db, mock_llm):
    mock_llm._responses = cycle(["response"])
    agent = Agent(
        character_id="partner",
        system_prompt="You are Vera.",
        llm=mock_llm,
        conn=db,
    )
    agent.speak("First message")
    agent.speak("Second message")
    assert len(mock_llm.last_history) == 2


def test_agent_uses_case_scoped_history(db, mock_llm):
    mock_llm._responses = cycle(["ok"])
    agent = Agent(
        character_id="npc_2",
        system_prompt="You are a witness.",
        llm=mock_llm,
        conn=db,
        case_id=42,
    )
    agent.speak("Did you see anything?")
    history = get_history(db, character_id="npc_2", case_id=42)
    assert len(history) == 2


# Companion tests
from noir.characters.companion import Companion
from noir.persistence.repository import save_partner, get_partner


def test_companion_loads_from_db(db, mock_llm):
    save_partner(db, name="Vera", sex="female",
                 personality_archetype="world-weary cynic",
                 speech_style="terse and hard-boiled",
                 relationship_stance="exasperated",
                 system_prompt="You are Vera, a world-weary detective's partner.")
    companion = Companion.load(conn=db, llm=mock_llm)
    assert companion.name == "Vera"
    assert companion.sex == "female"


def test_companion_speak_persists_without_case_id(db, mock_llm):
    mock_llm._responses = cycle(["Charming."])
    save_partner(db, name="Vera", sex="female",
                 personality_archetype="world-weary cynic",
                 speech_style="terse and hard-boiled",
                 relationship_stance="exasperated",
                 system_prompt="You are Vera.")
    companion = Companion.load(conn=db, llm=mock_llm)
    companion.speak("Morning, Vera.")
    history = get_history(db, character_id="partner")
    assert len(history) == 2


def test_companion_raises_if_no_partner_in_db(db, mock_llm):
    with pytest.raises(ValueError, match="No partner"):
        Companion.load(conn=db, llm=mock_llm)


# NPC tests
from noir.characters.npc import NPC
from noir.persistence.repository import (
    create_case, create_location, create_npc, get_character_location
)


def _make_npc(db, mock_llm):
    case_id = create_case(db, archetype="Christie", title="Test Case", case_data={})
    loc_id = create_location(db, name="The Diner", description="Greasy spoons.", is_fixed=True)
    npc_id = create_npc(db, case_id=case_id, name="Dolores",
                        role="suspect", system_prompt="You are Dolores.",
                        current_location_id=loc_id)
    return NPC.load(conn=db, llm=mock_llm, npc_id=npc_id, case_id=case_id), loc_id, case_id


def test_npc_loads_from_db(db, mock_llm):
    npc, _, _ = _make_npc(db, mock_llm)
    assert npc.name == "Dolores"
    assert npc.role == "suspect"


def test_npc_speak_uses_case_scoped_history(db, mock_llm):
    mock_llm._responses = cycle(["I was at the haberdasher's."])
    npc, _, case_id = _make_npc(db, mock_llm)
    npc.speak("Where were you?")
    history = get_history(db, character_id=f"npc_{npc.npc_id}", case_id=case_id)
    assert len(history) == 2


def test_npc_move_updates_location(db, mock_llm):
    npc, _, _ = _make_npc(db, mock_llm)
    new_loc_id = create_location(db, name="The Pier", description="Foggy.", is_fixed=True)
    npc.move_to(new_loc_id)
    assert get_character_location(db, f"npc_{npc.npc_id}") == new_loc_id


def test_npc_current_location(db, mock_llm):
    npc, loc_id, _ = _make_npc(db, mock_llm)
    assert npc.current_location_id == loc_id
