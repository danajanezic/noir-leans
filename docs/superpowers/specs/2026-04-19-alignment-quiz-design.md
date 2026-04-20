# Alignment Quiz — Design Spec
**Date:** 2026-04-19

## Overview

Replace the existing 8-question onboarding quiz with a new set of 8 questions designed to place the player on the D&D two-axis alignment spectrum (Lawful/Neutral/Chaotic × Good/Neutral/Evil). Alignment is determined by explicit answer weights, stored as two integers in the `player` table, and drifts slowly based on significant in-game choices. NPCs receive generated alignments that affect how they interact with the player. The partner's alignment is chosen to complement the player's — opening doors that the player's profile might close.

---

## Section 1: Quiz Questions & Scoring

### Scoring Model

Each question has 4 options, each tagged with `law` and `good` deltas:
- `law`: –2 (chaotic) to +2 (lawful)
- `good`: –2 (evil) to +2 (good)

After 8 questions, totals are summed across both axes (range: –16 to +16 each) and bucketed:

| Score | Axis Result |
|-------|------------|
| ≤ –4 | Chaotic / Evil |
| –3 to +3 | Neutral |
| ≥ +4 | Lawful / Good |

This yields one of nine alignments: Lawful Good, Neutral Good, Chaotic Good, Lawful Neutral, True Neutral, Chaotic Neutral, Lawful Evil, Neutral Evil, Chaotic Evil.

### Questions

**Q1.** A man drops his wallet. You pick it up. Inside: $40 cash, a photo of his kids, and a folded note that says "Payment received. The judge will rule by Friday." You:
- A. Return it, cash and all. Not your business. *(law +2, good –1)*
- B. Return the wallet, keep the cash. Consider it a fine. *(law –1, good 0)*
- C. Keep everything and follow up on the note. *(law –1, good +1)*
- D. Drop it in the nearest sewer. Let him wonder. *(law –2, good 0)*

**Q2.** The judge in a case you're working is dirty. You know it. You can't prove it. You:
- A. Keep digging until you can prove it. Justice takes time. *(law +2, good +2)*
- B. Work around him. Get the result through other channels. *(law –1, good +1)*
- C. Blackmail him into ruling your way just this once. *(law –2, good 0)*
- D. Accept it. Every system has rot. You're just one detective. *(law 0, good –1)*

**Q3.** Noirleans has a law you think is unjust. You:
- A. Follow it. Laws exist for reasons, even bad ones. *(law +2, good –1)*
- B. Break it quietly when necessary, without making it a statement. *(law –1, good +1)*
- C. Break it loudly. Bad laws deserve public contempt. *(law –2, good +1)*
- D. Use it when convenient, ignore it when not. *(law –1, good –1)*

**Q4.** A client is lying to you. You know it. You:
- A. Confront them directly. You won't work a case blind. *(law +1, good +1)*
- B. Keep working and figure out the real truth yourself. *(law 0, good +1)*
- C. Bill them double and let them discover you know. *(law 0, good –1)*
- D. Drop the case. Life's too short for people who waste your time. *(law +1, good 0)*

**Q5.** You get evidence that would solve the case — but you got it illegally. You:
- A. Use it. Results matter more than procedure. *(law –2, good +1)*
- B. Find a way to get it legally obtained. It takes longer but it's right. *(law +2, good +2)*
- C. Use it if the guilty party deserves it. Don't use it if they don't. *(law –1, good 0)*
- D. Sell it to the DA and let them figure out the paperwork. *(law –1, good –1)*

**Q6.** Someone confesses to a crime you're not working. It's bad. You:
- A. Turn them in. That's the only correct answer. *(law +2, good +1)*
- B. Hear them out first. Context matters before consequences. *(law 0, good +1)*
- C. Tell them to leave town and not come back. *(law –2, good 0)*
- D. File it away. Information is currency. *(law –1, good –2)*

**Q7.** The killer you just caught will walk on a technicality. You:
- A. Let it happen. The process has to mean something. *(law +2, good 0)*
- B. Plant corroborating evidence. They're guilty. *(law –2, good –1)*
- C. Leak it to someone who'll handle it outside the courts. *(law –1, good 0)*
- D. Beat yourself up about it and drink heavily. *(law 0, good 0)*

**Q8.** Someone asks you to keep a secret that would hurt an innocent person if you keep it. You:
- A. Tell the truth. Secrets like that fester. *(law 0, good +2)*
- B. Keep it. You made a promise. *(law +2, good –1)*
- C. Use the information to quietly fix the situation without disclosure. *(law –1, good +1)*
- D. Tell the person being hurt, not anyone else. *(law 0, good +1)*

### Scoring Function

A pure Python function `score_alignment(answers: list[str]) -> tuple[int, int]` maps answer letters to deltas and returns `(law_total, good_total)`. A second function `resolve_alignment(law: int, good: int) -> str` buckets the totals into one of the nine named alignments.

Both functions are deterministic and fully testable without an LLM.

---

## Section 2: Storage & Drift

### Schema

Two new columns on the `player` table:

```sql
ALTER TABLE player ADD COLUMN law_chaos INTEGER DEFAULT 0;
ALTER TABLE player ADD COLUMN good_evil INTEGER DEFAULT 0;
```

- `law_chaos`: –16 (chaotic) to +16 (lawful)
- `good_evil`: –16 (evil) to +16 (good)

Set at quiz time by the scoring function. Readable by `get_player()` (no new query needed).

### New Repository Functions

```python
def update_player_alignment(conn, *, law_delta: int = 0, good_delta: int = 0) -> None:
    """Clamps both axes to [–16, +16]."""

def get_alignment(player: sqlite3.Row) -> str:
    """Maps player.law_chaos and player.good_evil to a named alignment string."""
```

### Drift

Significant in-game choices call `update_player_alignment` with small deltas (±1 or ±2). Examples:
- Planting evidence → `law_delta=-2`
- Protecting a witness at personal cost → `good_delta=+1`
- Accepting a bribe → `law_delta=-1, good_delta=-1`

**Drift trigger placement is out of scope for this spec.** This spec delivers the schema, scoring functions, and the quiz replacement. Drift triggers are wired in a follow-up.

---

## Section 3: NPC Alignments & Soft Mechanical Impact

### NPC Alignment Generation

`alignment` is added to `REQUIRED_SUSPECT_FIELDS` in `generator.py`. The LLM assigns one of the nine named alignments based on the NPC's role, backstory, and personality. Stored in the `npcs` table as a new `alignment TEXT` column.

```sql
ALTER TABLE npcs ADD COLUMN alignment TEXT DEFAULT 'True Neutral';
```

### Alignment Compatibility

A helper `alignment_disposition(player_alignment: str, npc_alignment: str) -> str` returns one of three values:

| Result | Condition |
|--------|-----------|
| `"aligned"` | Both axes within 1 step of each other (e.g., Lawful Good / Neutral Good, or Lawful Good / Lawful Neutral) |
| `"opposed"` | Both axes differ by 2 steps — diagonally opposite (e.g., Lawful Good vs. Chaotic Evil, Lawful Neutral vs. Chaotic Neutral does NOT qualify) |
| `"neutral"` | Everything else |

### Context Injection

Injected as a prefix addition to every NPC conversation turn (same mechanism as the romance system's relationship stage injection):

```
[Player alignment: {player_alignment}. Your disposition: {disposition_note}.
Partner alignment: {partner_alignment}. {partner_note}]
```

Disposition notes:
- `aligned` → "Your values broadly align. You are somewhat more open with them."
- `opposed` → "Your values conflict fundamentally. You are guarded."
- `neutral` → (omitted — no note injected for neutral)

Partner notes (only injected if partner alignment differs from player alignment):
- If partner is `aligned` to NPC but player is not → "You find their partner more trustworthy. Their presence helps."
- Otherwise → omitted

### Partner Alignment

The `QUIZ_SYSTEM_PROMPT` is updated to include the player's resolved alignment and instruct the LLM to generate a partner whose alignment opens doors the player might find closed:

```
Player alignment: {alignment}. Generate a partner whose alignment complements this — 
someone who can reach people and institutions the player cannot. A Chaotic Good player 
needs a partner who can vouch for them with lawful institutions. A Lawful Evil player 
needs a partner who can reach people who distrust authority. Return the partner's 
alignment as a field in the JSON response.
```

Partner alignment is stored in the `partner` table:

```sql
ALTER TABLE partner ADD COLUMN alignment TEXT DEFAULT 'True Neutral';
```

---

## Files to Modify

| File | Change |
|------|--------|
| `noir/onboarding/quiz.py` | Replace `QUIZ_QUESTIONS` with new questions + weights; add `score_alignment()` and `resolve_alignment()`; update `Quiz.run()` to score answers and pass alignment to LLM; update `QUIZ_SYSTEM_PROMPT` to include player alignment and request partner alignment |
| `noir/persistence/db.py` | Add `law_chaos`, `good_evil` to `player` schema; add `alignment` to `partner` schema; add `alignment` to `npcs` schema |
| `noir/persistence/repository.py` | Add `update_player_alignment()` and `get_alignment()`; update `save_partner()` to accept and store `alignment` |
| `noir/mystery/generator.py` | Add `alignment` to `REQUIRED_SUSPECT_FIELDS`; update case generation prompt to require alignment per suspect |
| `noir/characters/npc.py` | Inject alignment disposition prefix into NPC context |
| `tests/test_onboarding.py` | Tests for `score_alignment()` and `resolve_alignment()` |
| `tests/test_persistence.py` | Tests for `update_player_alignment()` and `get_alignment()` |

---

## Out of Scope

- Drift trigger placement (wired in follow-up spec)
- Player-facing alignment display (no UI for showing the player their alignment)
- Alignment-gated dialogue options (soft disposition only, no hard gates)
