from noir.mystery.generator import REQUIRED_SUSPECT_FIELDS, _validate_case

_VALID_SUSPECT = {
    "name": "Rex Fontaine",
    "role": "suspect",
    "alibi": "was home",
    "secret": "he did it",
    "archetype_id": "nervous_informant",
    "race": "white",
    "political_connections": "none",
    "routine": [{"time_start": "09:00", "time_end": "17:00", "location": "The Diner"}],
    "alignment": "Chaotic Neutral",
    "age": 38,
    "pressure_tolerance": 4,
    "kindness_weight": 6,
    "empathy": 5,
    "starting_guilt": 3,
    "revelation_style": "staged",
    "revelation_stages": 3,
}

_VALID_CASE = {
    "title": "Death at the Docks",
    "victim": {"name": "Gerald Mink", "cause_of_death": "trombone", "found_at": "The Docks"},
    "killer_name": "Rex Fontaine",
    "motive": "jealousy",
    "suspects": [
        _VALID_SUSPECT,
        {**_VALID_SUSPECT, "name": "Vera Laine", "role": "witness"},
    ],
    "clues": [{"description": "a bloodied fedora", "is_red_herring": False, "location": "The Docks"}],
    "locations": [{"name": "The Docks"}],
}


def test_required_suspect_fields_includes_psychology():
    assert "pressure_tolerance" in REQUIRED_SUSPECT_FIELDS
    assert "kindness_weight" in REQUIRED_SUSPECT_FIELDS
    assert "empathy" in REQUIRED_SUSPECT_FIELDS
    assert "starting_guilt" in REQUIRED_SUSPECT_FIELDS
    assert "revelation_style" in REQUIRED_SUSPECT_FIELDS
    assert "revelation_stages" in REQUIRED_SUSPECT_FIELDS
    assert "archetype_id" in REQUIRED_SUSPECT_FIELDS


def test_validate_case_passes_with_psychology_fields():
    assert _validate_case(_VALID_CASE) is True


def test_validate_case_fails_missing_psychology_field():
    bad_suspect = {k: v for k, v in _VALID_SUSPECT.items() if k != "pressure_tolerance"}
    bad_case = {**_VALID_CASE, "suspects": [bad_suspect, bad_suspect]}
    assert _validate_case(bad_case) is False
