# Case Audit Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `CaseAuditor` class that runs after `MysteryGenerator` produces a case dict, catches structural inconsistencies and semantic solvability gaps, patches what it can in-place, and triggers targeted LLM regeneration for issues it can't patch.

**Architecture:** A new `CaseAuditor` class in `noir/mystery/auditor.py` is instantiated inside `MysteryGenerator.generate()` and `generate_from_dark_past()` after the LLM returns a valid case dict. It runs a deterministic pass (pure Python set-membership checks), then an LLM semantic pass, then patches patchable issues and regenerates if any fatal issues remain. `game.py` is untouched.

**Tech Stack:** Python 3.12 stdlib (`re`, `copy`, `json`, `dataclasses`), existing `LLMBackend` interface, `MockLLMBackend` for tests, `pytest`.

---

## File Map

| File | Change | Responsibility |
|---|---|---|
| `noir/mystery/auditor.py` | **Create** | `Issue` dataclass, `CaseAuditor` class with all audit/patch/regenerate logic |
| `noir/mystery/generator.py` | **Modify** (lines 209–222 and 278–298) | Call `CaseAuditor.audit_and_fix()` after structural validation passes |
| `tests/test_auditor.py` | **Create** | Unit tests for all auditor behaviour using fixture case dicts and `MockLLMBackend` |

---

## Shared Test Fixture

All auditor tests share this base case. Individual tests modify copies. Put this at the top of `tests/test_auditor.py` — it will be referenced by every task below.

```python
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
```

---

### Task 1: Create `auditor.py` skeleton

**Files:**
- Create: `noir/mystery/auditor.py`
- Test: `tests/test_auditor.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_auditor.py` after the fixtures:

```python
def test_auditor_returns_case_unchanged_when_clean(auditor, clean_case, mock_llm):
    mock_llm._responses = cycle(['{"issues": []}'])
    result = auditor.audit_and_fix(clean_case, "system prompt")
    assert result["title"] == "The Muted Maestro"
    assert result["killer_name"] == "Dolores Mink"
```

- [ ] **Step 2: Run to verify it fails**

```
pytest tests/test_auditor.py::test_auditor_returns_case_unchanged_when_clean -v
```
Expected: `ModuleNotFoundError` — `noir.mystery.auditor` doesn't exist yet.

- [ ] **Step 3: Create `noir/mystery/auditor.py`**

```python
import copy
import json
import re
from dataclasses import dataclass
from noir.llm.base import LLMBackend

AUDITOR_SYSTEM_PROMPT = (
    "You are a consistency auditor for a 1935 noir detective game. "
    "Evaluate mystery case JSON for semantic issues: solvability, "
    "motive discoverability, and alibi coherence. "
    "Return ONLY valid JSON: {\"issues\": [...]}."
)


@dataclass
class Issue:
    type: str      # ghost_name | killer_mismatch | bad_clue_location | bad_routine_location | npc_unreachable | bad_relationship_ref | unsolvable | hidden_motive | alibi_contradiction
    subject: str   # clue description, suspect name, etc.
    detail: str
    severity: str  # "patchable" | "fatal"
    source: str    # "deterministic" | "llm"


class CaseAuditor:

    def __init__(self, *, llm: LLMBackend):
        self.llm = llm

    def audit_and_fix(self, case: dict, system_prompt: str) -> dict:
        issues = self._deterministic_check(case) + self._llm_check(case)
        if not issues:
            return case
        case = self._patch(case, issues)
        fatal = [i for i in issues if i.severity == "fatal"]
        if fatal:
            case = self._regenerate(case, fatal, system_prompt)
        return case

    def _deterministic_check(self, case: dict) -> list[Issue]:
        return []

    def _llm_check(self, case: dict) -> list[Issue]:
        return []

    def _patch(self, case: dict, issues: list[Issue]) -> dict:
        return copy.deepcopy(case)

    def _regenerate(self, case: dict, fatal: list[Issue], system_prompt: str) -> dict:
        return case
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_auditor.py::test_auditor_returns_case_unchanged_when_clean -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add noir/mystery/auditor.py tests/test_auditor.py
git commit -m "feat: add CaseAuditor skeleton with Issue dataclass"
```

---

### Task 2: Deterministic checks — helpers

**Files:**
- Modify: `noir/mystery/auditor.py`
- Test: `tests/test_auditor.py`

The helpers `_name_words`, `_location_names`, `_location_words`, and `_extract_name_candidates` are used by all deterministic checks. Build and test them first.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_auditor.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

```
pytest tests/test_auditor.py -k "name_words or location_names or extract_name" -v
```
Expected: `AttributeError` — methods don't exist yet.

- [ ] **Step 3: Add helper methods to `CaseAuditor`**

Add these methods inside `CaseAuditor` in `noir/mystery/auditor.py`, before `_deterministic_check`:

```python
    _COMMON = frozenset({
        "The", "And", "But", "For", "With", "From", "Into", "Over", "Under",
        "Near", "Old", "New", "French", "Quarter", "Street", "Avenue",
        "Governor", "Mayor", "Senator", "Captain", "Mister", "Madame",
    })

    def _name_words(self, case: dict) -> set[str]:
        words: set[str] = set()
        for s in case.get("suspects", []):
            words.update(s.get("name", "").split())
        victim_name = case.get("victim", {}).get("name", "")
        if victim_name:
            words.update(victim_name.split())
        return words

    def _location_names(self, case: dict) -> set[str]:
        locs = {loc["name"] for loc in case.get("locations", [])}
        locs.add("home")
        return locs

    def _location_words(self, case: dict) -> set[str]:
        words: set[str] = set()
        for loc in case.get("locations", []):
            words.update(loc["name"].split())
        return words

    def _extract_name_candidates(self, text: str) -> list[str]:
        return re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b', text)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_auditor.py -k "name_words or location_names or extract_name" -v
```
Expected: all 4 PASS

- [ ] **Step 5: Commit**

```bash
git add noir/mystery/auditor.py tests/test_auditor.py
git commit -m "feat: add CaseAuditor helper methods for name/location extraction"
```

---

### Task 3: Deterministic checks — implementation

**Files:**
- Modify: `noir/mystery/auditor.py`
- Test: `tests/test_auditor.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_auditor.py`:

```python
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


def test_bad_relationship_ref_detected(auditor, clean_case):
    clean_case["suspects"][0]["relationships"][0]["name"] = "Ghost Person"
    issues = auditor._deterministic_check(clean_case)
    types = [i.type for i in issues]
    assert "bad_relationship_ref" in types


def test_clean_case_has_no_deterministic_issues(auditor, clean_case):
    issues = auditor._deterministic_check(clean_case)
    assert issues == []
```

- [ ] **Step 2: Run to verify they fail**

```
pytest tests/test_auditor.py -k "killer_mismatch or ghost_name or bad_clue or bad_routine or npc_unreachable or bad_relationship or clean_case_has_no" -v
```
Expected: all FAIL (stubs return `[]`).

- [ ] **Step 3: Implement `_deterministic_check`**

Replace the stub `_deterministic_check` in `noir/mystery/auditor.py`:

```python
    def _deterministic_check(self, case: dict) -> list[Issue]:
        issues: list[Issue] = []
        name_words = self._name_words(case)
        loc_names = self._location_names(case)
        loc_words = self._location_words(case)
        suspect_names = {s["name"] for s in case.get("suspects", [])}
        victim_name = case.get("victim", {}).get("name", "")
        all_char_names = suspect_names | ({victim_name} if victim_name else set())

        killer = case.get("killer_name", "")
        if killer not in suspect_names:
            issues.append(Issue(
                type="killer_mismatch",
                subject=killer,
                detail=f"killer_name '{killer}' does not match any suspect name",
                severity="fatal",
                source="deterministic",
            ))

        for clue in case.get("clues", []):
            desc = clue.get("description", "")
            for candidate in self._extract_name_candidates(desc):
                parts = candidate.split()
                if (
                    not any(p in name_words for p in parts)
                    and not any(p in loc_words for p in parts)
                    and not any(p in self._COMMON for p in parts)
                ):
                    issues.append(Issue(
                        type="ghost_name",
                        subject=desc,
                        detail=f"clue references '{candidate}' who is not a known character",
                        severity="patchable",
                        source="deterministic",
                    ))

        for clue in case.get("clues", []):
            loc = clue.get("location", "")
            if loc and loc not in loc_names:
                issues.append(Issue(
                    type="bad_clue_location",
                    subject=clue.get("description", ""),
                    detail=f"clue location '{loc}' not in locations list",
                    severity="patchable",
                    source="deterministic",
                ))

        for suspect in case.get("suspects", []):
            routine = suspect.get("routine", [])
            if not isinstance(routine, list):
                continue
            for entry in routine:
                loc = entry.get("location", "")
                if loc and loc not in loc_names:
                    issues.append(Issue(
                        type="bad_routine_location",
                        subject=suspect["name"],
                        detail=f"routine entry location '{loc}' not in locations list",
                        severity="patchable",
                        source="deterministic",
                    ))

        for suspect in case.get("suspects", []):
            routine = suspect.get("routine", [])
            if not isinstance(routine, list) or len(routine) == 0:
                issues.append(Issue(
                    type="npc_unreachable",
                    subject=suspect["name"],
                    detail=f"{suspect['name']} has no routine entries and cannot be reached",
                    severity="patchable",
                    source="deterministic",
                ))

        for suspect in case.get("suspects", []):
            for rel in suspect.get("relationships", []):
                rel_name = rel.get("name", "")
                if rel_name and rel_name not in all_char_names:
                    issues.append(Issue(
                        type="bad_relationship_ref",
                        subject=suspect["name"],
                        detail=f"relationship references '{rel_name}' not in the case",
                        severity="patchable",
                        source="deterministic",
                    ))

        return issues
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_auditor.py -k "killer_mismatch or ghost_name or bad_clue or bad_routine or npc_unreachable or bad_relationship or clean_case_has_no" -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add noir/mystery/auditor.py tests/test_auditor.py
git commit -m "feat: implement CaseAuditor deterministic checks"
```

---

### Task 4: LLM semantic check

**Files:**
- Modify: `noir/mystery/auditor.py`
- Test: `tests/test_auditor.py`

`query_structured` returns a `dict`, so ask the LLM for `{"issues": [...]}` rather than a bare list.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_auditor.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

```
pytest tests/test_auditor.py -k "llm_check" -v
```
Expected: all FAIL (stub returns `[]`).

- [ ] **Step 3: Implement `_llm_check`**

Replace the stub `_llm_check` in `noir/mystery/auditor.py`:

```python
    def _llm_check(self, case: dict) -> list[Issue]:
        prompt = (
            "Evaluate this mystery case for three types of semantic issues:\n\n"
            "1. unsolvable (fatal): Is there at least one non-red-herring clue whose "
            "description meaningfully points toward the killer by name, role, location, "
            "or motive? If not, report this.\n"
            "2. hidden_motive (fatal): Is the motive something a player could discover "
            "through NPC dialogue or clue descriptions, or does it exist only in the "
            "internal 'motive' field with no in-world trail? If hidden, report this.\n"
            "3. alibi_contradiction (patchable): Does any suspect's alibi directly "
            "contradict their own routine entries (e.g. claims to be elsewhere during "
            "a time their routine places them at the crime scene)? If so, report this.\n\n"
            f"Case JSON:\n{json.dumps(case, indent=2)}\n\n"
            'Return ONLY: {"issues": [{"type": "unsolvable"|"hidden_motive"|"alibi_contradiction", '
            '"subject": "suspect or clue name", "detail": "string", '
            '"severity": "patchable"|"fatal"}]} '
            'If no issues, return {"issues": []}.'
        )
        result = self.llm.query_structured(AUDITOR_SYSTEM_PROMPT, [], prompt)
        return [
            Issue(
                type=i.get("type", "unknown"),
                subject=i.get("subject", ""),
                detail=i.get("detail", ""),
                severity=i.get("severity", "patchable"),
                source="llm",
            )
            for i in result.get("issues", [])
            if isinstance(i, dict)
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_auditor.py -k "llm_check" -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add noir/mystery/auditor.py tests/test_auditor.py
git commit -m "feat: implement CaseAuditor LLM semantic check"
```

---

### Task 5: Patch phase

**Files:**
- Modify: `noir/mystery/auditor.py`
- Test: `tests/test_auditor.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_auditor.py`:

```python
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


def test_patch_does_not_mutate_original(auditor, clean_case):
    original_desc = clean_case["clues"][0]["description"]
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
    auditor._patch(clean_case, [issue])
    # original unchanged
    assert clean_case["clues"][-1]["description"] == "A witness saw Reginald Smoot leaving"
```

- [ ] **Step 2: Run to verify they fail**

```
pytest tests/test_auditor.py -k "patch" -v
```
Expected: all FAIL (stub returns a deepcopy but doesn't modify anything).

- [ ] **Step 3: Implement `_patch`**

Replace the stub `_patch` in `noir/mystery/auditor.py`:

```python
    def _patch(self, case: dict, issues: list[Issue]) -> dict:
        case = copy.deepcopy(case)
        loc_names = self._location_names(case)
        first_loc = case["locations"][0]["name"] if case.get("locations") else "home"
        victim_found_at = case.get("victim", {}).get("found_at", first_loc)
        fallback_loc = victim_found_at if victim_found_at in loc_names else first_loc

        for issue in issues:
            if issue.severity != "patchable":
                continue

            if issue.type == "ghost_name":
                m = re.search(r"references '([^']+)'", issue.detail)
                ghost = m.group(1) if m else None
                if ghost:
                    for clue in case["clues"]:
                        if clue.get("description") == issue.subject:
                            clue["description"] = clue["description"].replace(ghost, "a witness")
                            break

            elif issue.type == "bad_clue_location":
                for clue in case["clues"]:
                    if clue.get("description") == issue.subject:
                        clue["location"] = fallback_loc
                        break

            elif issue.type == "bad_routine_location":
                for suspect in case["suspects"]:
                    if suspect["name"] == issue.subject:
                        for entry in suspect.get("routine", []):
                            if entry.get("location") not in loc_names:
                                entry["location"] = first_loc
                        break

            elif issue.type == "npc_unreachable":
                for suspect in case["suspects"]:
                    if suspect["name"] == issue.subject:
                        if not isinstance(suspect.get("routine"), list):
                            suspect["routine"] = []
                        suspect["routine"].append({
                            "time_start": "09:00",
                            "time_end": "17:00",
                            "location": first_loc,
                        })
                        break

            elif issue.type == "alibi_contradiction":
                for suspect in case["suspects"]:
                    if suspect["name"] == issue.subject:
                        suspect["alibi"] = ""
                        break

            elif issue.type == "bad_relationship_ref":
                m = re.search(r"references '([^']+)'", issue.detail)
                bad_name = m.group(1) if m else None
                if bad_name:
                    for suspect in case["suspects"]:
                        if suspect["name"] == issue.subject:
                            suspect["relationships"] = [
                                r for r in suspect.get("relationships", [])
                                if r.get("name") != bad_name
                            ]
                            break

        return case
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_auditor.py -k "patch" -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add noir/mystery/auditor.py tests/test_auditor.py
git commit -m "feat: implement CaseAuditor patch phase"
```

---

### Task 6: Regenerate phase

**Files:**
- Modify: `noir/mystery/auditor.py`
- Test: `tests/test_auditor.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_auditor.py`:

```python
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
    assert "killer_mismatch" in prompt
    assert "must be corrected" in prompt.lower() or "issues" in prompt.lower()


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
```

- [ ] **Step 2: Run to verify they fail**

```
pytest tests/test_auditor.py -k "regenerate or audit_and_fix" -v
```
Expected: FAIL — `_regenerate` stub doesn't call LLM.

- [ ] **Step 3: Implement `_regenerate`**

Replace the stub `_regenerate` in `noir/mystery/auditor.py`:

```python
    def _regenerate(self, case: dict, fatal: list[Issue], system_prompt: str) -> dict:
        issue_lines = "\n".join(
            f"- [{i.type}] {i.subject}: {i.detail}" for i in fatal
        )
        preamble = (
            "The previous case had the following issues that MUST be corrected:\n"
            f"{issue_lines}\n\n"
            "Regenerate the case fixing all listed issues. "
            "Return the same JSON schema.\n\n"
            f"Previous case for reference:\n{json.dumps(case, indent=2)}"
        )
        return self.llm.query_structured(system_prompt, [], preamble)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_auditor.py -k "regenerate or audit_and_fix" -v
```
Expected: all PASS

- [ ] **Step 5: Run full auditor test suite**

```
pytest tests/test_auditor.py -v
```
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add noir/mystery/auditor.py tests/test_auditor.py
git commit -m "feat: implement CaseAuditor regenerate phase and audit_and_fix orchestration"
```

---

### Task 7: Integrate into `generator.py`

**Files:**
- Modify: `noir/mystery/generator.py`
- Test: `tests/test_mystery.py`

The auditor is called after the structural `_validate_case` check passes. If the auditor's `_regenerate` returns an invalid case, fall through to `_fatal()`.

- [ ] **Step 1: Write failing integration test**

Add to `tests/test_mystery.py`:

```python
from noir.mystery.auditor import CaseAuditor

def test_generate_calls_auditor_and_patches_ghost_name(db, mock_llm):
    from itertools import cycle as _cycle
    create_player(db)

    # Case with a ghost name in a clue
    case_with_ghost = {
        **VALID_CASE,
        "clues": [
            {"description": "A witness saw Reginald Smoot leaving the club", "is_red_herring": False, "location": "The Music Room"},
            {"description": "A receipt from the flamingo sanctuary", "is_red_herring": False, "location": "The Victim's Desk"},
        ]
    }
    # First call: generator; second: auditor _llm_check (no semantic issues)
    mock_llm._responses = _cycle([json.dumps(case_with_ghost), '{"issues": []}'])
    gen = MysteryGenerator(llm=mock_llm, conn=db)
    result = gen.generate(archetype_name="Agatha Christie")

    clue_texts = [c["description"] for c in result["clues"]]
    assert not any("Reginald Smoot" in t for t in clue_texts)


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
```

- [ ] **Step 2: Run to verify they fail**

```
pytest tests/test_mystery.py::test_generate_calls_auditor_and_patches_ghost_name tests/test_mystery.py::test_generate_regenerates_on_killer_mismatch -v
```
Expected: FAIL — auditor not called yet.

- [ ] **Step 3: Integrate auditor into `generate()`**

In `noir/mystery/generator.py`, add the import at the top of the file (after the existing imports):

```python
from noir.mystery.auditor import CaseAuditor
```

Then in `MysteryGenerator.generate()`, replace:

```python
        if not _validate_case(case):
            error_msg = (
                f"The generated case is missing required fields or has invalid structure.\n"
                f"Required top-level fields: {REQUIRED_FIELDS}\n"
                f"Generated case keys: {set(case.keys())}\n"
                "Please regenerate with the complete schema."
            )
            case = self.llm.query_structured(GENERATOR_SYSTEM_PROMPT, [], error_msg)
            if not _validate_case(case):
                self.llm._fatal()

        return case
```

with:

```python
        if not _validate_case(case):
            error_msg = (
                f"The generated case is missing required fields or has invalid structure.\n"
                f"Required top-level fields: {REQUIRED_FIELDS}\n"
                f"Generated case keys: {set(case.keys())}\n"
                "Please regenerate with the complete schema."
            )
            case = self.llm.query_structured(GENERATOR_SYSTEM_PROMPT, [], error_msg)
            if not _validate_case(case):
                self.llm._fatal()

        auditor = CaseAuditor(llm=self.llm)
        case = auditor.audit_and_fix(case, GENERATOR_SYSTEM_PROMPT)
        if not _validate_case(case):
            self.llm._fatal()

        return case
```

- [ ] **Step 4: Integrate auditor into `generate_from_dark_past()`**

In `generate_from_dark_past()`, find the block that ends with (around line 298):

```python
        if not _validate_case(case) or case.get("killer_name", "").lower() == partner_name.lower():
            self.llm._fatal()

        return case, archetype_name
```

Replace with:

```python
        if not _validate_case(case) or case.get("killer_name", "").lower() == partner_name.lower():
            self.llm._fatal()

        auditor = CaseAuditor(llm=self.llm)
        case = auditor.audit_and_fix(case, DARK_PAST_CASE_SYSTEM_PROMPT)
        if not _validate_case(case):
            self.llm._fatal()

        return case, archetype_name
```

- [ ] **Step 5: Run integration tests**

```
pytest tests/test_mystery.py::test_generate_calls_auditor_and_patches_ghost_name tests/test_mystery.py::test_generate_regenerates_on_killer_mismatch -v
```
Expected: both PASS

- [ ] **Step 6: Run full test suite**

```
pytest tests/ -v
```
Expected: all PASS (no regressions)

- [ ] **Step 7: Commit**

```bash
git add noir/mystery/generator.py tests/test_mystery.py
git commit -m "feat: integrate CaseAuditor into MysteryGenerator.generate and generate_from_dark_past"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered by |
|---|---|
| Ghost name detection (Reginald class of bugs) | Task 3 + Task 5 |
| `killer_name` match check | Task 3 |
| Location refs in clues | Task 3 |
| Location refs in routines | Task 3 |
| NPC reachability | Task 3 |
| Relationship refs | Task 3 |
| LLM solvability check | Task 4 |
| LLM motive discoverability check | Task 4 |
| LLM alibi coherence check | Task 4 |
| Patch: ghost name → "a witness" | Task 5 |
| Patch: bad clue location → found_at | Task 5 |
| Patch: bad routine location → first_loc | Task 5 |
| Patch: npc_unreachable → default routine | Task 5 |
| Patch: alibi_contradiction → blank alibi | Task 5 |
| Patch runs before regeneration decision | Task 6 (`audit_and_fix` order) |
| Regenerate with issue preamble | Task 6 |
| Regenerate triggers on killer_mismatch, unsolvable, hidden_motive | Task 6 |
| One regeneration max, then `_fatal()` | Task 7 (re-validates after `audit_and_fix`) |
| `generate()` integration | Task 7 |
| `generate_from_dark_past()` integration | Task 7 |
| `game.py` untouched | ✓ (never referenced) |

**Type consistency:** `Issue` dataclass defined in Task 1, used identically in Tasks 3–6. `audit_and_fix(case, system_prompt)` signature consistent across all tasks. `_patch` and `_regenerate` use the same `Issue` type throughout.

**No placeholders found.**
