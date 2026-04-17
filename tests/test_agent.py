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
