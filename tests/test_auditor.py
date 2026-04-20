import copy
import json
import pytest
from itertools import cycle
from noir.mystery.auditor import CaseAuditor, Issue
from noir.llm.mock import MockLLMBackend

BASE_CASE = {
    "title": "The Muted Maestro",
    "victim": {
        "name": "Victor Voss",
        "cause_of_death": "strangled by a trombone slide",
        "found_at": "Fournier's Jazz Club",
    },
    "killer_name": "Dolores Mink",
    "motive": "Victor discovered Dolores was skimming from the till",
    "suspects": [
        {
            "name": "Dolores Mink",
            "role": "suspect",
            "alibi": "Claims she was counting receipts in the back office",
            "secret": "Has been skimming from the till for months",
            "personality": "Charming and ruthless",
            "speech_style": "All business, no small talk",
            "race": "White",
            "political_connections": "None",
            "backstory": "Ran speakeasies during Prohibition. Now runs Fournier's.",
            "alignment": "Neutral Evil",
            "routine": [
                {"time_start": "18:00", "time_end": "02:00", "location": "Fournier's Jazz Club"}
            ],
            "relationships": [
                {
                    "name": "Victor Voss",
                    "relationship": "employer",
                    "shared_facts": ["Victor hired her three years ago"],
                }
            ],
        },
        {
            "name": "René LeBlanc",
            "role": "witness",
            "alibi": "Was playing trumpet on stage all night",
            "secret": "Saw Dolores leaving the back office",
            "personality": "Nervous, avoids eye contact",
            "speech_style": "Speaks in short bursts",
            "race": "Creole",
            "political_connections": "None",
            "backstory": "Jazz musician who knows more than he lets on.",
            "alignment": "True Neutral",
            "routine": [
                {"time_start": "20:00", "time_end": "02:00", "location": "Fournier's Jazz Club"}
            ],
            "relationships": [],
        },
    ],
    "clues": [
        {
            "description": "Dolores Mink's fingerprints were found on the trombone slide",
            "is_red_herring": False,
            "location": "Fournier's Jazz Club",
        },
        {
            "description": "A ledger showing payments that don't add up",
            "is_red_herring": False,
            "location": "Fournier's Jazz Club",
        },
    ],
    "locations": [
        {"name": "Fournier's Jazz Club", "description": "Smoky and crowded"},
        {"name": "City Hall", "description": "Marble floors, suspicious eyes"},
    ],
}


@pytest.fixture
def auditor(mock_llm):
    return CaseAuditor(llm=mock_llm)


@pytest.fixture
def clean_case():
    return copy.deepcopy(BASE_CASE)


def test_auditor_returns_case_unchanged_when_clean(auditor, clean_case, mock_llm):
    mock_llm._responses = cycle(['{"issues": []}'])
    result = auditor.audit_and_fix(clean_case, "system prompt")
    assert result["title"] == "The Muted Maestro"
    assert result["killer_name"] == "Dolores Mink"
