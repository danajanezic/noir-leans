# NPC Ages — Design Spec
**Date:** 2026-04-19

## Overview

NPCs are assigned an age appropriate to their role and relationships. Age determines which historical lore events they personally remember — those they were at least 12 years old for. Lore injection is split into two tiers: investigation-relevant events (always in the system prompt) and background events (injected per-turn only when the player asks about history).

The game is always set in 1935. Birth year is computed as `1935 - age`.

---

## Section 1: Age Assignment & Storage

### Schema

One new migration on the `npcs` table:

```sql
ALTER TABLE npcs ADD COLUMN age INTEGER DEFAULT 35;
```

### Generation

`age` is added to `REQUIRED_SUSPECT_FIELDS` in `generator.py`. The case generation prompt includes these guidelines in the suspect schema:

```
"age": integer — the character's age in 1935.
  Guidelines: law enforcement / legal professionals: 28–65;
  working adults (merchants, laborers, clerks): 20–60;
  young adults (students, apprentices): 18–30.
  CRITICAL: respect relationship logic — a father must be at least 18 years
  older than his child, an employer typically older than an apprentice, a
  mentor older than their protégé. All ages are as of 1935.
```

The same age field and guidelines are added to the `generate_from_dark_past()` prompt.

### Seeding

`create_npc()` in `repository.py` gains `age: int = 35`. In `game.py`, the `create_npc()` call passes `age=suspect.get("age", 35)`.

---

## Section 2: Lore Memory Filtering

### Module

A new module `noir/lore.py` contains all lore utilities. It reads `world_lore.json` from `noir/data/`.

### Memory threshold

An NPC remembers an event if their age during that event was **≥ 12**:

```
age_during_event = event["start"]["year"] - (1935 - npc_age)
```

If `age_during_event >= 12`, the event is included.

### Function

```python
def lore_memories_for_age(age: int) -> tuple[list[str], list[str]]:
    """Return (case_hook_memories, background_memories).

    case_hook_memories: events marked case_hook=true that the NPC remembers.
    background_memories: all other events the NPC remembers.
    Both lists contain formatted strings: "{year} — {summary}"
    """
```

Each memory string is formatted as:
```
"1929 — The stock market crashed. Noirleans had been rich. Then it wasn't. ..."
```

Returns two empty lists if the NPC is too young for any event.

### Examples (1935)

| NPC Age | Born | Remembers (≥12) |
|---------|------|-----------------|
| 60 | 1875 | All 7 events |
| 35 | 1900 | red_light_closure (age 17), the_crash (age 29), short_rise (age 28), longshoremen_strike (age 32), prohibition_end (age 33), short_assassination (age 35) |
| 25 | 1910 | the_crash (age 19), short_rise (age 18), longshoremen_strike (age 22), prohibition_end (age 23), short_assassination (age 25) |
| 15 | 1920 | longshoremen_strike (age 12), prohibition_end (age 13), short_assassination (age 15) |
| 10 | 1925 | short_assassination (age 10) — **excluded** (below threshold) |

### Keyword detection

```python
_HISTORY_KEYWORDS = {
    "remember", "recall", "back then", "before", "used to", "grew up",
    "young", "history", "past", "what happened", "when did", "were you",
    "1917", "1919", "1928", "1929", "1932", "1933",
    "prohibition", "crash", "depression", "strike", "howie", "short",
    "red light", "war", "district"
}

def is_history_query(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in _HISTORY_KEYWORDS)
```

---

## Section 3: Injection Points

### Tier 1 — Case-hook events (always injected)

Events marked `case_hook: true` in `world_lore.json`:
- `short_assassination` (1935)
- `longshoremen_strike` (1932)
- `red_light_closure` (1917)

If the NPC was ≥12 during any of these, they are appended to `NPC._locked_system_prompt`. The block appears after the alignment prefix and before the base system prompt:

```
[Historical events you personally remember:
 1935 — Governor Howie Short shot in the Capitol six weeks ago...
 1932 — Dock workers walked out for four months...]
```

If the NPC was too young for all case-hook events, nothing is injected here.

### Tier 2 — Background events (keyword-triggered)

Events marked `case_hook: false`:
- `the_crash` (1929)
- `short_rise` (1928)
- `prohibition_end` (1933)
- `great_migration_acceleration` (1929)

These are stored on the NPC instance but not in the system prompt. `NPC._query_with_retry()` is overridden: if `is_history_query(prompt)` returns `True`, the background memories are prepended to the prompt for that LLM call only. The recorded conversation history receives the original, unmodified player input.

```
[Historical background you remember, relevant to this question:
 1929 — The stock market crashed...
 1933 — Prohibition repealed...]

{original player input}
```

---

## Section 4: NPC Class Changes

`NPC.load()` calls `lore_memories_for_age(row["age"] or 35)` and stores both lists (the `or 35` guards against legacy rows where the column may be null despite the migration default):
- `self._case_memories: list[str]` — tier 1
- `self._background_memories: list[str]` — tier 2

`NPC._locked_system_prompt` is already overridden for the alignment prefix. It is updated to also append tier 1 memories if non-empty.

`NPC._query_with_retry()` override:

```python
def _query_with_retry(self, prompt: str, history: list[dict]) -> str:
    if self._background_memories and is_history_query(prompt):
        mem_block = "[Historical background you remember, relevant to this question: " \
                    + " / ".join(self._background_memories) + "]"
        prompt = mem_block + "\n\n" + prompt
    return super()._query_with_retry(prompt, history)
```

---

## Files to Modify

| File | Change |
|------|--------|
| `noir/lore.py` | New — `lore_memories_for_age()`, `is_history_query()` |
| `noir/persistence/db.py` | Migration: `age INTEGER DEFAULT 35` on `npcs` |
| `noir/persistence/repository.py` | `create_npc()` accepts `age: int = 35` |
| `noir/mystery/generator.py` | Add `age` to `REQUIRED_SUSPECT_FIELDS`; add age guidelines to both prompt methods |
| `noir/game.py` | Pass `age=suspect.get("age", 35)` to `create_npc()` |
| `noir/characters/npc.py` | Load tier 1/2 memories; update `_locked_system_prompt`; override `_query_with_retry` |
| `tests/test_lore.py` | New — unit tests for `lore_memories_for_age` and `is_history_query` |
| `tests/test_mystery.py` | Add `age` to VALID_CASE suspects; test `REQUIRED_SUSPECT_FIELDS` includes `age` |
| `tests/test_agent.py` | NPC lore injection tests |

---

## Out of Scope

- Player-facing display of NPC age
- Age validation against relationships post-generation (LLM is instructed to handle this)
- Age for fixed NPCs (Lou the bartender uses the default of 35; can be updated manually later)
- Drift or change of age over time
