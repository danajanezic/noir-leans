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
            "alibi": "Claims she was playing cards at Fournier's Jazz Club all evening",
            "secret": "She was present at the murder scene but did not commit it",
            "archetype_id": "charming_liar",
            "race": "White",
            "political_connections": "none",
            "age": 34,
            "alignment": "Chaotic Neutral",
            "pressure_tolerance": 7, "kindness_weight": 3, "empathy": 2,
            "starting_guilt": 2, "revelation_style": "sudden", "revelation_stages": 1,
            "routine": [
                {"time_start": "18:00", "time_end": "02:00", "location": "Fournier's Jazz Club"}
            ],
            "relationships": [
                {
                    "name": "Victor Voss",
                    "relationship": "former employer",
                    "shared_facts": ["worked together for 3 years"],
                }
            ],
        },
        {
            "name": "René LeBlanc",
            "role": "witness",
            "alibi": "Was playing trumpet on stage all night",
            "secret": "Saw Dolores leaving the back office",
            "archetype_id": "nervous_witness",
            "race": "Creole",
            "political_connections": "None",
            "age": 28,
            "alignment": "True Neutral",
            "pressure_tolerance": 3, "kindness_weight": 6, "empathy": 7,
            "starting_guilt": 1, "revelation_style": "staged", "revelation_stages": 3,
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
        {"name": "Fournier's Jazz Club"},
        {"name": "City Hall"},
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


def test_name_words_extracts_all_character_name_parts(auditor, clean_case):
    words = auditor._name_words(clean_case)
    assert "Dolores" in words
    assert "Mink" in words
    assert "René" in words
    assert "LeBlanc" in words
    assert "Victor" in words
    assert "Voss" in words


def test_location_names_includes_home(auditor, clean_case):
    locs = auditor._location_names(clean_case)
    assert "Fournier's Jazz Club" in locs
    assert "City Hall" in locs
    assert "home" in locs


def test_extract_name_candidates_finds_multiword_names(auditor):
    text = "A witness saw Reginald Smoot leaving the building"
    candidates = auditor._extract_name_candidates(text)
    assert "Reginald Smoot" in candidates


def test_extract_name_candidates_ignores_single_words(auditor):
    text = "Something happened at midnight"
    candidates = auditor._extract_name_candidates(text)
    assert candidates == []


def test_killer_mismatch_detected(auditor, clean_case):
    clean_case["killer_name"] = "Nobody McFakerson"
    issues = auditor._deterministic_check(clean_case)
    types = [i.type for i in issues]
    assert "killer_mismatch" in types
    fatal = [i for i in issues if i.type == "killer_mismatch"]
    assert fatal[0].severity == "fatal"


def test_ghost_name_in_clue_detected(auditor, clean_case):
    clean_case["clues"].append({
        "description": "A witness saw Reginald Smoot leaving the club",
        "is_red_herring": False,
        "location": "Fournier's Jazz Club",
    })
    issues = auditor._deterministic_check(clean_case)
    types = [i.type for i in issues]
    assert "ghost_name" in types
    ghost = [i for i in issues if i.type == "ghost_name"]
    assert "Reginald Smoot" in ghost[0].detail


def test_known_name_in_clue_not_flagged(auditor, clean_case):
    # Dolores Mink is a known suspect — should not be flagged
    issues = auditor._deterministic_check(clean_case)
    types = [i.type for i in issues]
    assert "ghost_name" not in types


def test_bad_clue_location_detected(auditor, clean_case):
    clean_case["clues"][0]["location"] = "The Moon"
    issues = auditor._deterministic_check(clean_case)
    types = [i.type for i in issues]
    assert "bad_clue_location" in types
    bad = [i for i in issues if i.type == "bad_clue_location"]
    assert bad[0].severity == "patchable"


def test_bad_routine_location_detected(auditor, clean_case):
    clean_case["suspects"][0]["routine"][0]["location"] = "Atlantis"
    issues = auditor._deterministic_check(clean_case)
    types = [i.type for i in issues]
    assert "bad_routine_location" in types


def test_npc_unreachable_detected(auditor, clean_case):
    clean_case["suspects"][1]["routine"] = []
    issues = auditor._deterministic_check(clean_case)
    types = [i.type for i in issues]
    assert "npc_unreachable" in types
    unreachable = [i for i in issues if i.type == "npc_unreachable"]
    assert unreachable[0].subject == "René LeBlanc"


def test_npc_unreachable_detected_when_routine_not_a_list(auditor, clean_case):
    clean_case["suspects"][1]["routine"] = "goes to the club sometimes"
    issues = auditor._deterministic_check(clean_case)
    types = [i.type for i in issues]
    assert "npc_unreachable" in types


def test_bad_relationship_ref_detected(auditor, clean_case):
    clean_case["suspects"][0]["relationships"][0]["name"] = "Ghost Person"
    issues = auditor._deterministic_check(clean_case)
    types = [i.type for i in issues]
    assert "bad_relationship_ref" in types


def test_clean_case_has_no_deterministic_issues(auditor, clean_case):
    issues = auditor._deterministic_check(clean_case)
    assert issues == []


def test_llm_check_returns_empty_when_no_issues(auditor, clean_case, mock_llm):
    mock_llm._responses = cycle(['{"issues": []}'])
    issues = auditor._llm_check(clean_case)
    assert issues == []


def test_llm_check_parses_unsolvable_issue(auditor, clean_case, mock_llm):
    response = json.dumps({"issues": [
        {
            "type": "unsolvable",
            "subject": "all clues",
            "detail": "No clue points toward the killer",
            "severity": "fatal",
        }
    ]})
    mock_llm._responses = cycle([response])
    issues = auditor._llm_check(clean_case)
    assert len(issues) == 1
    assert issues[0].type == "unsolvable"
    assert issues[0].severity == "fatal"
    assert issues[0].source == "llm"


def test_llm_check_parses_alibi_contradiction(auditor, clean_case, mock_llm):
    response = json.dumps({"issues": [
        {
            "type": "alibi_contradiction",
            "subject": "Dolores Mink",
            "detail": "Alibi says back office but routine places her on stage",
            "severity": "patchable",
        }
    ]})
    mock_llm._responses = cycle([response])
    issues = auditor._llm_check(clean_case)
    assert issues[0].type == "alibi_contradiction"
    assert issues[0].severity == "patchable"


def test_llm_check_sends_full_case_json_in_prompt(auditor, clean_case, mock_llm):
    mock_llm._responses = cycle(['{"issues": []}'])
    auditor._llm_check(clean_case)
    prompt = mock_llm.calls[-1]["user_input"]
    assert "Dolores Mink" in prompt
    assert "solvability" in prompt.lower() or "unsolvable" in prompt.lower()


def test_patch_ghost_name_replaces_with_witness(auditor, clean_case):
    clean_case["clues"].append({
        "description": "A witness saw Reginald Smoot leaving the club",
        "is_red_herring": False,
        "location": "Fournier's Jazz Club",
    })
    issue = Issue(
        type="ghost_name",
        subject="A witness saw Reginald Smoot leaving the club",
        detail="clue references 'Reginald Smoot' who is not a known character",
        severity="patchable",
        source="deterministic",
    )
    patched = auditor._patch(clean_case, [issue])
    desc = patched["clues"][-1]["description"]
    assert "Reginald Smoot" not in desc
    assert "witness" in desc


def test_patch_bad_clue_location_uses_found_at(auditor, clean_case):
    clean_case["clues"][0]["location"] = "The Moon"
    issue = Issue(
        type="bad_clue_location",
        subject=clean_case["clues"][0]["description"],
        detail="clue location 'The Moon' not in locations list",
        severity="patchable",
        source="deterministic",
    )
    patched = auditor._patch(clean_case, [issue])
    assert patched["clues"][0]["location"] == "Fournier's Jazz Club"


def test_patch_bad_routine_location_uses_first_location(auditor, clean_case):
    clean_case["suspects"][0]["routine"][0]["location"] = "Atlantis"
    issue = Issue(
        type="bad_routine_location",
        subject="Dolores Mink",
        detail="routine entry location 'Atlantis' not in locations list",
        severity="patchable",
        source="deterministic",
    )
    patched = auditor._patch(clean_case, [issue])
    assert patched["suspects"][0]["routine"][0]["location"] == "Fournier's Jazz Club"


def test_patch_npc_unreachable_adds_default_routine(auditor, clean_case):
    clean_case["suspects"][1]["routine"] = []
    issue = Issue(
        type="npc_unreachable",
        subject="René LeBlanc",
        detail="René LeBlanc has no routine entries and cannot be reached",
        severity="patchable",
        source="deterministic",
    )
    patched = auditor._patch(clean_case, [issue])
    routine = patched["suspects"][1]["routine"]
    assert len(routine) == 1
    assert routine[0]["location"] == "Fournier's Jazz Club"
    assert routine[0]["time_start"] == "09:00"
    assert routine[0]["time_end"] == "17:00"


def test_patch_alibi_contradiction_blanks_alibi(auditor, clean_case):
    issue = Issue(
        type="alibi_contradiction",
        subject="Dolores Mink",
        detail="alibi contradicts routine",
        severity="patchable",
        source="llm",
    )
    patched = auditor._patch(clean_case, [issue])
    dolores = next(s for s in patched["suspects"] if s["name"] == "Dolores Mink")
    assert dolores["alibi"] == ""


def test_patch_bad_relationship_ref_removes_entry(auditor, clean_case):
    clean_case["suspects"][0]["relationships"][0]["name"] = "Ghost Person"
    issue = Issue(
        type="bad_relationship_ref",
        subject="Dolores Mink",
        detail="relationship references 'Ghost Person' not in the case",
        severity="patchable",
        source="deterministic",
    )
    patched = auditor._patch(clean_case, [issue])
    dolores = next(s for s in patched["suspects"] if s["name"] == "Dolores Mink")
    names = [r["name"] for r in dolores["relationships"]]
    assert "Ghost Person" not in names


def test_patch_does_not_mutate_original(auditor, clean_case):
    clean_case["clues"].append({
        "description": "A witness saw Reginald Smoot leaving",
        "is_red_herring": False,
        "location": "Fournier's Jazz Club",
    })
    issue = Issue(
        type="ghost_name",
        subject="A witness saw Reginald Smoot leaving",
        detail="clue references 'Reginald Smoot' who is not a known character",
        severity="patchable",
        source="deterministic",
    )
    patched = auditor._patch(clean_case, [issue])
    # patched copy has the replacement
    assert "Reginald Smoot" not in patched["clues"][-1]["description"]
    assert "witness" in patched["clues"][-1]["description"]
    # original is untouched
    assert clean_case["clues"][-1]["description"] == "A witness saw Reginald Smoot leaving"


def test_regenerate_calls_llm_with_issue_preamble(auditor, clean_case, mock_llm):
    fixed_case = copy.deepcopy(clean_case)
    fixed_case["killer_name"] = "Dolores Mink"  # valid
    mock_llm._responses = cycle([json.dumps(fixed_case)])
    fatal = [Issue(
        type="killer_mismatch",
        subject="Nobody",
        detail="killer_name 'Nobody' does not match any suspect name",
        severity="fatal",
        source="deterministic",
    )]
    result = auditor._regenerate(clean_case, fatal, "system prompt")
    prompt = mock_llm.calls[-1]["user_input"]
    assert "killer_name" in prompt  # vector key for killer_mismatch
    assert "correction vector" in prompt.lower()
    assert "Dolores Mink" in prompt  # valid_values contains suspect names


def test_audit_and_fix_triggers_regenerate_for_killer_mismatch(auditor, clean_case, mock_llm):
    broken = copy.deepcopy(clean_case)
    broken["killer_name"] = "Ghost Person"

    fixed = copy.deepcopy(clean_case)  # valid case returned by regeneration
    # LLM calls: 1 for _llm_check (no issues), 1 for _regenerate
    mock_llm._responses = cycle(['{"issues": []}', json.dumps(fixed)])

    result = auditor.audit_and_fix(broken, "system prompt")
    assert result["killer_name"] == "Dolores Mink"
    assert len(mock_llm.calls) == 2


def test_audit_and_fix_no_llm_calls_for_clean_case(auditor, clean_case, mock_llm):
    mock_llm._responses = cycle(['{"issues": []}'])
    auditor.audit_and_fix(clean_case, "system prompt")
    # Only the _llm_check call — no regeneration
    assert len(mock_llm.calls) == 1
