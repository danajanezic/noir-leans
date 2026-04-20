# Case Audit Agent Design

**Date:** 2026-04-19
**Status:** Approved

## Problem

The case generator produces a JSON blob that passes structural validation but can contain semantic inconsistencies that make cases unsolvable or broken. The canonical example: a clue references "Reginald" by name, but no NPC named Reginald exists in `suspects[]`, so no NPC record is ever created — the lead is permanently unsolvable. Current `_validate_case()` only checks required keys and list lengths, not cross-references or solvability.

## Goal

Add a second-pass audit step between `gen.generate()` returning and `create_case()` being called. The auditor catches structural inconsistencies and semantic solvability gaps, patches what it can in-place, and triggers a targeted regeneration for issues it can't patch.

---

## Architecture

A new `CaseAuditor` class in `noir/mystery/auditor.py`. Called from `MysteryGenerator.generate()` and `generate_from_dark_past()` after the LLM returns a case dict but before the dict is returned to the caller.

```
gen.generate()
  └─ LLM produces case dict
  └─ CaseAuditor.audit(case) → [Issue, ...]
       ├─ deterministic pass (Python, no LLM)
       └─ LLM semantic pass (one call)
  └─ CaseAuditor.fix(case, issues) → patched case dict
       ├─ patch phase (in-place JSON edits, no LLM)
       └─ regenerate phase (one LLM call if fatal issues remain)
  └─ return patched/regenerated case dict
```

The generator already owns retry/fatal logic, so that pattern is preserved. `game.py` is untouched.

---

## Deterministic Checks

Pure Python set-membership and reference checks. No LLM call.

| Check | What it catches | Severity |
|---|---|---|
| Ghost names in clues | Proper nouns in `clue.description` not in `suspects[].name`, `victim.name`, or partner name | patchable |
| `killer_name` match | `killer_name` must exactly match one `suspects[].name` | fatal |
| Location refs in clues | `clue.location` must be in `locations[].name` | patchable |
| Location refs in routines | `suspect.routine[].location` must be in `locations[].name` or `"home"` | patchable |
| NPC reachability | Every suspect must have ≥1 routine entry with a valid location | patchable |
| Relationship refs | `suspect.relationships[].name` must resolve to another suspect or the victim | patchable |

Ghost name detection: extract capitalized word sequences from clue descriptions, filter against the known name set. Imprecise by design — false positives are acceptable (a patched clue is better than a ghost NPC).

---

## LLM Semantic Pass

A single LLM call after the deterministic pass. Receives the full case JSON. Evaluates:

1. **Solvability** — is there ≥1 non-red-herring clue whose description meaningfully points toward the killer (by name, role, location, or motive)?
2. **Motive discoverability** — is the motive something a player could uncover via NPC dialogue or clues, or does it exist only in the internal `motive` field?
3. **Alibi coherence** — does any suspect's alibi directly contradict their own routine entries?

Returns structured JSON:
```json
[
  {
    "type": "unsolvable" | "hidden_motive" | "alibi_contradiction",
    "subject": "suspect or clue name",
    "detail": "string",
    "severity": "patchable" | "fatal"
  }
]
```

`unsolvable` and `hidden_motive` are always fatal. `alibi_contradiction` is patchable.

---

## Hybrid Fix / Regenerate Logic

Issues from both passes are merged, then handled in two phases.

### Patch Phase (no LLM, in-place edits)

Applied first regardless of whether regeneration will follow.

- **Ghost name in clue** → rewrite description, replacing the ghost name with a generic descriptor ("a witness", "someone at the club")
- **Bad location ref in routine** → replace with the NPC's first valid location, or `"home"`
- **Bad location ref in clue** → replace with the victim's `found_at` location, or the first location in the list
- **Patchable alibi contradiction** → blank the alibi string so the NPC generates it dynamically in conversation
- **Missing routine entry** → add a single default entry: `{"time_start": "09:00", "time_end": "17:00", "location": first valid location}`

### Regenerate Phase (one LLM call)

Triggered when any of the following are present after patching:
- `killer_name` matches nobody in `suspects[]`
- `unsolvable` issue (no clue points at killer)
- `hidden_motive` issue (motive undiscoverable)
- ≥3 fatal issues of any kind

The regeneration reuses the same system prompt as the original call, prepended with a structured preamble:

```
The previous case had the following issues that must be corrected:
- [issue type]: [detail]
...
Regenerate the case fixing all listed issues. Return the same JSON schema.
```

If the regenerated case also fails audit, fall through to `llm._fatal()` — same behavior as today. The auditor never loops more than once.

The patch phase always runs first, even when regeneration will also be triggered. This means the regeneration prompt receives a partially-cleaned case dict and a list of only the remaining fatal issues — reducing the chance the regenerated case re-introduces the same patchable problems.

---

## Data Model

No new DB tables. The auditor operates entirely on the in-memory case dict before persistence.

Issue representation (internal, not persisted):
```python
@dataclass
class Issue:
    type: str        # ghost_name | killer_mismatch | bad_location_ref | ...
    subject: str     # the clue description, suspect name, etc.
    detail: str
    severity: str    # "patchable" | "fatal"
    source: str      # "deterministic" | "llm"
```

---

## Files

| File | Change |
|---|---|
| `noir/mystery/auditor.py` | New — `CaseAuditor` class, `Issue` dataclass |
| `noir/mystery/generator.py` | Call `CaseAuditor.audit_and_fix()` from `generate()` and `generate_from_dark_past()` |
| `tests/test_auditor.py` | New — unit tests using fixture case dicts, no LLM required for deterministic tests |

---

## Testing

- Deterministic checks: unit tests with hand-crafted case dicts containing known issues
- LLM semantic pass: tested with mock LLM (existing `MockLLM` in `noir/llm/mock.py`)
- Patch logic: assert patched case passes `_validate_case()` and deterministic re-audit
- Regenerate trigger: assert that a case with `killer_name` mismatch triggers regeneration (verify LLM call count via mock)
