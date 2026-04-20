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

    def _patch(self, case: dict, issues: list[Issue]) -> dict:
        case = copy.deepcopy(case)
        loc_names = self._location_names(case)
        first_loc = case["locations"][0]["name"] if case.get("locations") else "home"
        victim_found_at = case.get("victim", {}).get("found_at", first_loc)
        fallback_loc = victim_found_at if victim_found_at in loc_names else first_loc

        for issue in issues:
            if issue.severity != "patchable":
                continue

            # ghost_name is processed first; if the same clue also has bad_clue_location,
            # the location fix won't match after description rewrite (rare edge case)
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
