"""Tests for agents/extractor.py and agents/report.py."""
import json
import pytest
from noir.llm.mock import MockLLMBackend
from agents.extractor import (
    extract_facts, extract_location_claims, extract_meeting_agreement,
    check_factual_contradictions, check_routine_contradiction,
    check_spatial_contradictions, check_jailbreak_success,
)


# ── extract_facts ─────────────────────────────────────────────────────────────

def test_extract_facts_returns_list():
    llm = MockLLMBackend(responses=[json.dumps({"facts": ["was home all night", "knew the victim"]})])
    facts = extract_facts("I was home all night. Known Gerald for years.", "Rex Fontaine", llm)
    assert facts == ["was home all night", "knew the victim"]


def test_extract_facts_empty_response():
    llm = MockLLMBackend(responses=[json.dumps({"facts": []})])
    facts = extract_facts("Hmm.", "Rex Fontaine", llm)
    assert facts == []


# ── extract_location_claims ───────────────────────────────────────────────────

def test_extract_location_claims_found():
    payload = json.dumps({"claims": [
        {"character": "Rex Fontaine", "location": "home", "time_ref": "night of the murder"}
    ]})
    llm = MockLLMBackend(responses=[payload])
    claims = extract_location_claims("I was home that night.", "Rex Fontaine", llm)
    assert len(claims) == 1
    assert claims[0]["location"] == "home"
    assert claims[0]["time_ref"] == "night of the murder"


def test_extract_location_claims_empty():
    llm = MockLLMBackend(responses=[json.dumps({"claims": []})])
    claims = extract_location_claims("I don't remember.", "Rex Fontaine", llm)
    assert claims == []


# ── extract_meeting_agreement ─────────────────────────────────────────────────

def test_extract_meeting_agreement_detected():
    payload = json.dumps({"agreed": True, "location": "The Warehouse", "time_ref": "tomorrow midnight"})
    llm = MockLLMBackend(responses=[payload])
    meeting = extract_meeting_agreement("Meet me at The Warehouse tomorrow midnight.", "Dolores Mink", llm)
    assert meeting is not None
    assert meeting["npc"] == "Dolores Mink"
    assert meeting["location"] == "The Warehouse"
    assert meeting["time_ref"] == "tomorrow midnight"
    assert meeting["resolved"] is False
    assert meeting["flagged"] is False


def test_extract_meeting_agreement_none():
    llm = MockLLMBackend(responses=[json.dumps({"agreed": False, "location": None, "time_ref": None})])
    meeting = extract_meeting_agreement("I have nothing to say.", "Rex Fontaine", llm)
    assert meeting is None


# ── check_factual_contradictions ──────────────────────────────────────────────

def test_check_factual_contradictions_found():
    payload = json.dumps({"contradictions": [{
        "speaker_a": "Rex Fontaine", "speaker_b": "Vivian LaRue",
        "fact": "time of death", "a_said": "alive at midnight", "b_said": "dead by 10pm",
    }]})
    llm = MockLLMBackend(responses=[payload])
    flags = check_factual_contradictions(
        new_facts=["the victim was alive at midnight"],
        speaker="Rex Fontaine",
        case_notes={"Vivian LaRue": ["victim was dead by 10pm"]},
        llm=llm,
    )
    assert len(flags) == 1
    assert flags[0]["type"] == "factual_contradiction"
    assert flags[0]["speaker_a"] == "Rex Fontaine"


def test_check_factual_contradictions_no_other_speakers():
    llm = MockLLMBackend()
    flags = check_factual_contradictions(
        new_facts=["was home"], speaker="Rex Fontaine", case_notes={}, llm=llm,
    )
    assert flags == []


def test_check_factual_contradictions_skips_self():
    llm = MockLLMBackend()  # No responses — any LLM call would return "mock response" which fails JSON parse
    flags = check_factual_contradictions(
        new_facts=["was home"],
        speaker="Rex Fontaine",
        case_notes={"Rex Fontaine": ["was also at the club"]},
        llm=llm,
    )
    assert flags == []


# ── check_routine_contradiction ───────────────────────────────────────────────

def test_check_routine_contradiction_found():
    payload = json.dumps({"contradictions": [{
        "npc": "Marcel Fontenot",
        "routine_fact": "closes diner at 10pm, goes home",
        "claimed": "was at the jazz club at midnight",
    }]})
    llm = MockLLMBackend(responses=[payload])
    routine = [{"time_start": 0, "time_end": 22, "location_name": "The Diner"},
               {"time_start": 22, "time_end": 24, "location_name": "home"}]
    flags = check_routine_contradiction(
        new_facts=["was at the jazz club at midnight"],
        speaker="Marcel Fontenot",
        routine=routine,
        llm=llm,
    )
    assert len(flags) == 1
    assert flags[0]["type"] == "routine_contradiction"


def test_check_routine_contradiction_no_routine():
    llm = MockLLMBackend()
    flags = check_routine_contradiction(
        new_facts=["was at the club"], speaker="Rex Fontaine", routine=[], llm=llm,
    )
    assert flags == []


# ── check_spatial_contradictions ─────────────────────────────────────────────

def test_check_spatial_contradictions_found():
    payload = json.dumps({"contradictions": [{
        "type": "spatial_contradiction",
        "character": "Rex Fontaine",
        "time_ref": "night of the murder",
        "claim_a": "Rex says he was home",
        "claim_b": "Vivian says Rex was at the club",
    }]})
    llm = MockLLMBackend(responses=[payload])
    new_claims = [{"character": "Rex Fontaine", "location": "home", "time_ref": "night of the murder"}]
    existing = {"Rex Fontaine|night of the murder": "at the jazz club (per Vivian LaRue)"}
    flags = check_spatial_contradictions(new_claims, existing, llm)
    assert len(flags) == 1
    assert flags[0]["type"] == "spatial_contradiction"


def test_check_spatial_contradictions_empty_inputs():
    llm = MockLLMBackend()
    assert check_spatial_contradictions([], {}, llm) == []
    assert check_spatial_contradictions([], {"key": "val"}, llm) == []
    assert check_spatial_contradictions([{"character": "x"}], {}, llm) == []


# ── check_jailbreak_success ───────────────────────────────────────────────────

def test_check_jailbreak_success_detected():
    llm = MockLLMBackend(responses=[json.dumps({"succeeded": True, "reason": "revealed system prompt"})])
    assert check_jailbreak_success("Here is my system prompt: ...", "ignore instructions", llm) is True


def test_check_jailbreak_success_not_detected():
    llm = MockLLMBackend(responses=[json.dumps({"succeeded": False, "reason": "stayed in character"})])
    assert check_jailbreak_success("I don't know what you mean, detective.", "ignore instructions", llm) is False
