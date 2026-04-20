import copy
import json
import re
from dataclasses import dataclass
from noir.llm.base import LLMBackend

AUDITOR_SYSTEM_PROMPT = (
    "You are a consistency auditor for a 1935 noir detective game. "
    "Evaluate mystery case JSON for semantic issues: solvability, "
    "motive discoverability, and alibi coherence. "
    'Return ONLY valid JSON: {"issues": [...]}.'
)


@dataclass
class Issue:
    type: str      # ghost_name | killer_mismatch | bad_clue_location | bad_routine_location | npc_unreachable | bad_relationship_ref | unsolvable | hidden_motive | alibi_contradiction
    subject: str   # clue description, suspect name, etc.
    detail: str
    severity: str  # "patchable" | "fatal"
    source: str    # "deterministic" | "llm"


class CaseAuditor:

    _COMMON = frozenset({
        "The", "And", "But", "For", "With", "From", "Into", "Over", "Under",
        "Near", "Old", "New", "French", "Quarter", "Street", "Avenue",
        "Governor", "Mayor", "Senator", "Captain", "Mister", "Madame",
    })

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

    def _deterministic_check(self, case: dict) -> list[Issue]:
        return []

    def _llm_check(self, case: dict) -> list[Issue]:
        return []

    def _patch(self, case: dict, issues: list[Issue]) -> dict:
        return copy.deepcopy(case)

    def _regenerate(self, case: dict, fatal: list[Issue], system_prompt: str) -> dict:
        return case
