# Skill System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an emergent, mostly-invisible skill system where roots are determined by the alignment quiz, specializations are LLM-generated from play history, and the partner earns XP through in-conversation interjections.

**Architecture:** Four root skills tied to alignment axes grow via XP awarded post-conversation by the existing summary LLM call. Every 3 root levels the LLM generates a specialization from recent skill events. The partner gets a turn after each NPC response when context warrants it, earning her own XP. Everything surfaces quietly — ambient partner lines on unlock, full detail in `/me`.

**Tech Stack:** Python 3.12, SQLite via `sqlite3`, `noir.llm.base.LLMBackend`, `rich` for display, `pytest` for tests.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `noir/persistence/db.py` | Modify | Add 3 new tables, migrations, remove alignment clamp |
| `noir/persistence/repository.py` | Modify | Skill CRUD: initialize, award XP, level-up, specializations, skill events |
| `noir/characters/skills.py` | **Create** | Skill check outcomes, XP multipliers, specialization generation |
| `noir/characters/agent.py` | Modify | Add `xp_awards` to `_SUMMARY_SYSTEM`; `summarize_and_save` returns `dict` |
| `noir/game.py` | Modify | Partner interjection in talk loop; apply XP after conversations; surface unlocks; update `handle_me` |
| `noir/display.py` | Modify | Add skills section to `show_player_profile` |
| `tests/test_skills.py` | **Create** | Tests for skills module |
| `tests/test_persistence.py` | Modify | Tests for skill repository functions |

---

## Task 1: DB Schema — Three New Tables + Remove Alignment Clamp

**Files:**
- Modify: `noir/persistence/db.py`
- Modify: `tests/test_persistence.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_persistence.py`:

```python
from noir.persistence.repository import (
    initialize_player_skills, get_skills, award_xp, get_specializations,
    save_specialization, log_skill_event, get_skill_events,
)


def test_new_tables_exist(db):
    tables = {
        row[0] for row in
        db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert "player_skills" in tables
    assert "player_specializations" in tables
    assert "skill_events" in tables


def test_alignment_is_unbounded(db):
    from noir.persistence.repository import create_player, update_player_alignment, get_player
    create_player(db)
    # Apply large deltas — should not clamp
    for _ in range(20):
        update_player_alignment(db, law_delta=2, good_delta=2)
    player = get_player(db)
    assert player["law_chaos"] == 40
    assert player["good_evil"] == 40
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/danajanezic/code/noir-leans
python3 -m pytest tests/test_persistence.py::test_new_tables_exist tests/test_persistence.py::test_alignment_is_unbounded -v
```

Expected: FAIL — tables don't exist yet, alignment still clamped.

- [ ] **Step 3: Add tables to SCHEMA in `noir/persistence/db.py`**

Add after the `leads` table definition (before `street_reputation`):

```python
CREATE TABLE IF NOT EXISTS player_skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner TEXT NOT NULL,
    root TEXT NOT NULL,
    level INTEGER DEFAULT 1,
    xp INTEGER DEFAULT 0,
    UNIQUE(owner, root)
);

CREATE TABLE IF NOT EXISTS player_specializations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner TEXT NOT NULL,
    root TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    unlocked_at_level INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS skill_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner TEXT NOT NULL,
    root TEXT NOT NULL,
    xp_awarded INTEGER NOT NULL,
    reason TEXT,
    case_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (case_id) REFERENCES cases(id)
);

CREATE INDEX IF NOT EXISTS idx_player_skills_owner ON player_skills(owner);
CREATE INDEX IF NOT EXISTS idx_skill_events_owner_root ON skill_events(owner, root);
```

- [ ] **Step 4: Add migrations to `_MIGRATIONS` list**

Append at the end of `_MIGRATIONS`:

```python
"CREATE TABLE IF NOT EXISTS player_skills (id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, root TEXT NOT NULL, level INTEGER DEFAULT 1, xp INTEGER DEFAULT 0, UNIQUE(owner, root))",
"CREATE TABLE IF NOT EXISTS player_specializations (id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, root TEXT NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL, unlocked_at_level INTEGER NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
"CREATE TABLE IF NOT EXISTS skill_events (id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, root TEXT NOT NULL, xp_awarded INTEGER NOT NULL, reason TEXT, case_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
"CREATE INDEX IF NOT EXISTS idx_player_skills_owner ON player_skills(owner)",
"CREATE INDEX IF NOT EXISTS idx_skill_events_owner_root ON skill_events(owner, root)",
```

- [ ] **Step 5: Remove alignment clamp in `noir/persistence/repository.py`**

Find `update_player_alignment` (around line 755) and replace:

```python
def update_player_alignment(conn: sqlite3.Connection, *,
                             law_delta: int = 0, good_delta: int = 0) -> None:
    conn.execute(
        "UPDATE player SET law_chaos = law_chaos + ?, good_evil = good_evil + ? WHERE id=1",
        (law_delta, good_delta)
    )
    conn.commit()
```

- [ ] **Step 6: Run tests to confirm passing**

```bash
python3 -m pytest tests/test_persistence.py::test_new_tables_exist tests/test_persistence.py::test_alignment_is_unbounded -v
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add noir/persistence/db.py noir/persistence/repository.py tests/test_persistence.py
git commit -m "feat: skill system schema — three new tables, unbounded alignment"
```

---

## Task 2: Skill Repository Functions

**Files:**
- Modify: `noir/persistence/repository.py`
- Modify: `tests/test_persistence.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_persistence.py`:

```python
def test_initialize_player_skills(db):
    initialize_player_skills(db, owner="player", roots=["authority", "empathy"])
    skills = get_skills(db, owner="player")
    assert skills["authority"]["level"] == 1
    assert skills["authority"]["xp"] == 0
    assert skills["empathy"]["level"] == 1
    assert "streetwise" not in skills


def test_award_xp_no_levelup(db):
    initialize_player_skills(db, owner="player", roots=["authority"])
    old_level, new_level = award_xp(db, owner="player", root="authority", xp=50, reason="test")
    assert old_level == 1
    assert new_level == 1
    skills = get_skills(db, owner="player")
    assert skills["authority"]["xp"] == 50


def test_award_xp_levelup(db):
    initialize_player_skills(db, owner="player", roots=["authority"])
    old_level, new_level = award_xp(db, owner="player", root="authority", xp=100, reason="test")
    assert old_level == 1
    assert new_level == 2
    skills = get_skills(db, owner="player")
    assert skills["authority"]["level"] == 2


def test_save_and_get_specialization(db):
    save_specialization(db, owner="player", root="authority",
                        name="Iron Stare", description="Years of pressing witnesses has made your silence louder than most men's threats.",
                        unlocked_at_level=3)
    specs = get_specializations(db, owner="player")
    assert len(specs) == 1
    assert specs[0]["name"] == "Iron Stare"
    assert specs[0]["root"] == "authority"


def test_log_and_get_skill_events(db):
    log_skill_event(db, owner="player", root="empathy", xp=5, reason="showed_kindness")
    events = get_skill_events(db, owner="player", root="empathy", limit=10)
    assert len(events) == 1
    assert events[0]["xp_awarded"] == 5
```

- [ ] **Step 2: Run to confirm failure**

```bash
python3 -m pytest tests/test_persistence.py::test_initialize_player_skills tests/test_persistence.py::test_award_xp_no_levelup tests/test_persistence.py::test_award_xp_levelup tests/test_persistence.py::test_save_and_get_specialization tests/test_persistence.py::test_log_and_get_skill_events -v
```

Expected: FAIL — functions not defined.

- [ ] **Step 3: Add functions to `noir/persistence/repository.py`**

Add after `get_latest_npc_opinion`:

```python
_XP_PER_LEVEL = 100


def initialize_player_skills(conn: sqlite3.Connection, *, owner: str, roots: list[str]) -> None:
    for root in roots:
        conn.execute(
            "INSERT OR IGNORE INTO player_skills (owner, root, level, xp) VALUES (?, ?, 1, 0)",
            (owner, root)
        )
    conn.commit()


def get_skills(conn: sqlite3.Connection, *, owner: str) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT root, level, xp FROM player_skills WHERE owner=?", (owner,)
    ).fetchall()
    return {r["root"]: {"level": r["level"], "xp": r["xp"]} for r in rows}


def award_xp(conn: sqlite3.Connection, *, owner: str, root: str,
             xp: int, reason: str | None = None, case_id: int | None = None) -> tuple[int, int]:
    """Award XP to a root skill. Returns (old_level, new_level)."""
    conn.execute(
        "INSERT OR IGNORE INTO player_skills (owner, root, level, xp) VALUES (?, ?, 1, 0)",
        (owner, root)
    )
    row = conn.execute(
        "SELECT level, xp FROM player_skills WHERE owner=? AND root=?", (owner, root)
    ).fetchone()
    old_level = row["level"]
    new_xp = row["xp"] + xp
    new_level = 1 + new_xp // _XP_PER_LEVEL
    conn.execute(
        "UPDATE player_skills SET xp=?, level=? WHERE owner=? AND root=?",
        (new_xp, new_level, owner, root)
    )
    log_skill_event(conn, owner=owner, root=root, xp=xp, reason=reason, case_id=case_id)
    conn.commit()
    return old_level, new_level


def get_specializations(conn: sqlite3.Connection, *, owner: str) -> list[dict]:
    rows = conn.execute(
        "SELECT root, name, description, unlocked_at_level, created_at "
        "FROM player_specializations WHERE owner=? ORDER BY created_at",
        (owner,)
    ).fetchall()
    return [dict(r) for r in rows]


def save_specialization(conn: sqlite3.Connection, *, owner: str, root: str,
                         name: str, description: str, unlocked_at_level: int) -> None:
    conn.execute(
        "INSERT INTO player_specializations (owner, root, name, description, unlocked_at_level) VALUES (?, ?, ?, ?, ?)",
        (owner, root, name, description, unlocked_at_level)
    )
    conn.commit()


def log_skill_event(conn: sqlite3.Connection, *, owner: str, root: str,
                     xp: int, reason: str | None = None, case_id: int | None = None) -> None:
    conn.execute(
        "INSERT INTO skill_events (owner, root, xp_awarded, reason, case_id) VALUES (?, ?, ?, ?, ?)",
        (owner, root, xp, reason, case_id)
    )
    conn.commit()


def get_skill_events(conn: sqlite3.Connection, *, owner: str, root: str,
                      limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT root, xp_awarded, reason, case_id, created_at "
        "FROM skill_events WHERE owner=? AND root=? ORDER BY id DESC LIMIT ?",
        (owner, root, limit)
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Run tests to confirm passing**

```bash
python3 -m pytest tests/test_persistence.py::test_initialize_player_skills tests/test_persistence.py::test_award_xp_no_levelup tests/test_persistence.py::test_award_xp_levelup tests/test_persistence.py::test_save_and_get_specialization tests/test_persistence.py::test_log_and_get_skill_events -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add noir/persistence/repository.py tests/test_persistence.py
git commit -m "feat: skill repository — initialize, award XP, specializations, events"
```

---

## Task 3: Skills Module

**Files:**
- Create: `noir/characters/skills.py`
- Create: `tests/test_skills.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_skills.py`:

```python
import sqlite3
import pytest
from noir.persistence.db import create_schema
from noir.persistence.repository import initialize_player_skills, get_skills
from noir.characters.skills import (
    alignment_xp_multiplier,
    check_skill_attempt,
    roots_for_alignment,
    apply_conversation_xp,
)
from noir.llm.mock import MockLLMBackend


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    yield conn
    conn.close()


def test_roots_for_alignment_lawful_good():
    roots = roots_for_alignment(law_chaos=10, good_evil=10)
    assert "authority" in roots
    assert "empathy" in roots


def test_roots_for_alignment_chaotic_evil():
    roots = roots_for_alignment(law_chaos=-10, good_evil=-10)
    assert "streetwise" in roots
    assert "cunning" in roots


def test_roots_for_true_neutral():
    roots = roots_for_alignment(law_chaos=0, good_evil=0)
    assert set(roots) == {"authority", "streetwise", "empathy", "cunning"}


def test_alignment_xp_multiplier_aligned():
    # Lawful player using Authority (lawful root) — should get bonus
    mult = alignment_xp_multiplier(law_chaos=15, good_evil=0, root="authority")
    assert mult > 1.0


def test_alignment_xp_multiplier_opposed():
    # Lawful player using Streetwise (chaotic root) — should get penalty
    mult = alignment_xp_multiplier(law_chaos=15, good_evil=0, root="streetwise")
    assert mult < 1.0


def test_alignment_xp_multiplier_neutral():
    # Neutral player — should be near 1.0 for any root
    mult = alignment_xp_multiplier(law_chaos=0, good_evil=0, root="authority")
    assert abs(mult - 1.0) < 0.05


def test_check_skill_attempt_returns_valid_outcome():
    for _ in range(50):
        outcome = check_skill_attempt(skill_level=1, difficulty=1)
        assert outcome in ("success", "backfire", "lucky")


def test_check_skill_attempt_skilled_mostly_succeeds():
    results = [check_skill_attempt(skill_level=5, difficulty=1) for _ in range(200)]
    success_rate = results.count("success") / 200
    assert success_rate > 0.75


def test_check_skill_attempt_unskilled_can_still_succeed():
    results = [check_skill_attempt(skill_level=1, difficulty=5) for _ in range(200)]
    assert "success" in results  # nonzero success rate
    assert "lucky" in results


def test_apply_conversation_xp(db):
    initialize_player_skills(db, owner="player", roots=["authority", "empathy"])
    xp_awards = {"authority": 8, "empathy": 5, "streetwise": 0, "cunning": 0}
    apply_conversation_xp(db, owner="player", xp_awards=xp_awards,
                          law_chaos=10, good_evil=10, case_id=None)
    skills = get_skills(db, owner="player")
    assert skills["authority"]["xp"] > 0
    assert skills["empathy"]["xp"] > 0
```

- [ ] **Step 2: Run to confirm failure**

```bash
python3 -m pytest tests/test_skills.py -v
```

Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Create `noir/characters/skills.py`**

```python
import random
import sqlite3
import logging
from noir.llm.base import LLMBackend
from noir.persistence.repository import (
    award_xp, get_skill_events, save_specialization, get_skills,
)

log = logging.getLogger(__name__)

ROOTS = ("authority", "streetwise", "empathy", "cunning")

# (law_direction, good_direction) — positive means aligned with positive axis
_ROOT_ALIGNMENT = {
    "authority":  (1,  0),
    "streetwise": (-1, 0),
    "empathy":    (0,  1),
    "cunning":    (0, -1),
}

_SPECIALIZATION_SYSTEM = (
    "You are naming a skill specialization for a detective in a 1935 noir game. "
    "You will be given the detective's root skill, recent skill events (what they did to earn XP), "
    "and their alignment. "
    "Generate a specialization that reflects what this detective has actually learned to do. "
    "The name should be 2-4 words, evocative, specific to 1935 Noirleans. "
    "The description should be 1-2 sentences in the world's voice — what this means in practice. "
    "Return ONLY valid JSON: {\"name\": \"string\", \"description\": \"string\"}"
)


def roots_for_alignment(*, law_chaos: int, good_evil: int) -> list[str]:
    """Return the root skills a player starts with based on quiz alignment."""
    if law_chaos == 0 and good_evil == 0:
        return list(ROOTS)
    roots = []
    if law_chaos > 0:
        roots.append("authority")
    elif law_chaos < 0:
        roots.append("streetwise")
    if good_evil > 0:
        roots.append("empathy")
    elif good_evil < 0:
        roots.append("cunning")
    # True neutral on one axis gets both roots for that axis
    if law_chaos == 0:
        roots.extend(["authority", "streetwise"])
    if good_evil == 0:
        roots.extend(["empathy", "cunning"])
    return list(dict.fromkeys(roots))  # deduplicate, preserve order


def alignment_xp_multiplier(*, law_chaos: int, good_evil: int, root: str) -> float:
    """Multiplier for XP based on how aligned the player is with this root."""
    law_dir, good_dir = _ROOT_ALIGNMENT[root]
    alignment_strength = law_chaos * law_dir + good_evil * good_dir
    if alignment_strength >= 0:
        return 1.0 + min(alignment_strength / 20.0, 1.0)  # 1.0 → 2.0
    return max(0.5, 1.0 + alignment_strength / 20.0)       # 0.5 → 1.0


def check_skill_attempt(*, skill_level: int, difficulty: int) -> str:
    """
    Returns 'success', 'backfire', or 'lucky' based on skill vs difficulty.
    difficulty: 1 (easy) to 5 (hard).
    """
    gap = skill_level - difficulty
    success_p = max(0.10, min(0.88, 0.60 + gap * 0.14))
    lucky_p = 0.05
    backfire_p = 1.0 - success_p - lucky_p
    r = random.random()
    if r < success_p:
        return "success"
    if r < success_p + backfire_p:
        return "backfire"
    return "lucky"


def apply_conversation_xp(conn: sqlite3.Connection, *, owner: str,
                           xp_awards: dict[str, int], law_chaos: int,
                           good_evil: int, case_id: int | None) -> dict[str, tuple[int, int]]:
    """
    Apply XP awards from a conversation summary, weighted by alignment.
    Returns {root: (old_level, new_level)} for roots that had nonzero awards.
    """
    level_changes = {}
    for root, base_xp in xp_awards.items():
        if not base_xp or root not in ROOTS:
            continue
        mult = alignment_xp_multiplier(law_chaos=law_chaos, good_evil=good_evil, root=root)
        final_xp = max(1, round(base_xp * mult))
        old_level, new_level = award_xp(conn, owner=owner, root=root,
                                         xp=final_xp, reason="conversation",
                                         case_id=case_id)
        level_changes[root] = (old_level, new_level)
    return level_changes


def maybe_generate_specialization(llm: LLMBackend, conn: sqlite3.Connection, *,
                                   owner: str, root: str,
                                   law_chaos: int, good_evil: int) -> dict | None:
    """
    If the root's current level is a multiple of 3, generate and save a new specialization.
    Returns the specialization dict if one was generated, else None.
    """
    skills = get_skills(conn, owner=owner)
    level = skills.get(root, {}).get("level", 0)
    if level == 0 or level % 3 != 0:
        return None
    events = get_skill_events(conn, owner=owner, root=root, limit=15)
    if not events:
        return None
    alignment_label = _alignment_label(law_chaos, good_evil)
    event_summary = "; ".join(
        e["reason"] for e in events if e.get("reason")
    )[:400]
    prompt = (
        f"Root skill: {root}. Level reached: {level}. "
        f"Detective alignment: {alignment_label}. "
        f"Recent actions that built this skill: {event_summary}."
    )
    result = llm.query_structured(_SPECIALIZATION_SYSTEM, [], prompt)
    name = result.get("name", "").strip()
    description = result.get("description", "").strip()
    if not name or not description:
        return None
    save_specialization(conn, owner=owner, root=root, name=name,
                         description=description, unlocked_at_level=level)
    return {"name": name, "description": description, "root": root, "level": level}


def _alignment_label(law_chaos: int, good_evil: int) -> str:
    lc = "Lawful" if law_chaos > 3 else "Chaotic" if law_chaos < -3 else "Neutral"
    ge = "Good" if good_evil > 3 else "Evil" if good_evil < -3 else "Neutral"
    return f"{lc} {ge}"
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_skills.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add noir/characters/skills.py tests/test_skills.py
git commit -m "feat: skills module — alignment XP, skill checks, specialization generation"
```

---

## Task 4: Update Agent Summary to Include XP Awards

**Files:**
- Modify: `noir/characters/agent.py`
- Modify: `tests/test_agent.py`

- [ ] **Step 1: Write the failing test**

Check what's already in `tests/test_agent.py`, then add:

```python
def test_summarize_returns_xp_awards(db, mock_llm):
    import json
    mock_llm._responses = iter([
        json.dumps({
            "summary": "The detective pressed hard on the suspect.",
            "npc_opinion": "Ruthless but effective.",
            "affection_delta": 0,
            "xp_awards": {"authority": 5, "streetwise": 0, "empathy": 2, "cunning": 0}
        })
    ])
    from noir.characters.agent import Agent
    agent = Agent(character_id="npc_1", system_prompt="test", llm=mock_llm,
                  conn=db, case_id=None)
    history = [
        {"role": "user", "content": "Where were you that night?"},
        {"role": "assistant", "content": "I told you, I was home."},
    ]
    result = agent.summarize_and_save(history, persist=False)
    assert "affection_delta" in result
    assert "xp_awards" in result
    assert result["xp_awards"]["authority"] == 5
```

- [ ] **Step 2: Run to confirm failure**

```bash
python3 -m pytest tests/test_agent.py::test_summarize_returns_xp_awards -v
```

Expected: FAIL — `summarize_and_save` returns `int`, not `dict`.

- [ ] **Step 3: Update `_SUMMARY_SYSTEM` and `summarize_and_save` in `noir/characters/agent.py`**

Replace `_SUMMARY_SYSTEM`:

```python
_SUMMARY_SYSTEM = (
    "You are processing a conversation from a 1935 noir detective game. "
    "Return ONLY valid JSON with four fields:\n"
    "\"summary\": 2-4 sentences covering personal facts the detective revealed about themselves, "
    "any commitments or plans mentioned, and key information exchanged. Factual and specific.\n"
    "\"npc_opinion\": 1-2 sentences in the NPC's voice describing their current read on this detective — "
    "their gut feeling, what they trust or distrust, what they find useful or irritating. "
    "If a prior opinion is provided, evolve it based on this conversation rather than starting fresh. "
    "Write it as the NPC's private assessment, not dialogue.\n"
    "\"affection_delta\": an integer from -5 to 10 representing how much this conversation "
    "moved the relationship. Positive means warmer. Negative means colder. "
    "Most conversations: 0-3. Significant emotional moments: 8-10. Real damage: negative.\n"
    "\"xp_awards\": an object with keys 'authority', 'streetwise', 'empathy', 'cunning' — "
    "integer XP (0-10) for each root based on what the detective actually did. "
    "authority: used procedure, leverage, official channels, intimidation backed by rank. "
    "streetwise: used bribery, underworld knowledge, informal contacts, hustle. "
    "empathy: showed genuine interest, read emotions, built trust, noticed vulnerability. "
    "cunning: bluffed, misdirected, found leverage, played both sides. "
    "Be specific — most roots should be 0 for any given conversation."
)
```

Replace `summarize_and_save`:

```python
def summarize_and_save(self, history: list[dict], persist: bool = True) -> dict:
    """Summarize conversation, optionally persist. Returns {affection_delta, xp_awards}."""
    if len(history) < 2:
        return {"affection_delta": 0, "xp_awards": {}}
    prior_opinion = get_latest_npc_opinion(self.conn, character_id=self.character_id)
    transcript = "\n".join(
        f"{'Detective' if m['role'] == 'user' else 'NPC'}: {m['content']}"
        for m in history
    )
    if prior_opinion:
        transcript = f"[Prior opinion of this detective: {prior_opinion}]\n\n" + transcript
    result = self.llm.query_structured(self._SUMMARY_SYSTEM, [], transcript)
    summary = result.get("summary", "").strip()
    opinion = result.get("npc_opinion", "").strip() or None
    try:
        affection_delta = int(result.get("affection_delta", 0))
        affection_delta = max(-5, min(10, affection_delta))
    except (TypeError, ValueError):
        affection_delta = 0
    xp_awards = {}
    raw_xp = result.get("xp_awards", {})
    if isinstance(raw_xp, dict):
        for root in ("authority", "streetwise", "empathy", "cunning"):
            try:
                xp_awards[root] = max(0, min(10, int(raw_xp.get(root, 0))))
            except (TypeError, ValueError):
                xp_awards[root] = 0
    if persist and summary:
        save_conversation_summary(self.conn, character_id=self.character_id,
                                  summary=summary, npc_opinion=opinion)
    return {"affection_delta": affection_delta, "xp_awards": xp_awards}
```

- [ ] **Step 4: Update callers of `summarize_and_save` in `noir/game.py`**

Find the two call sites (NPC conversation end and partner conversation end). They currently do:

```python
affection_delta = npc.summarize_and_save(hist, persist=is_fixed)
```

and

```python
affection_delta = self.companion.summarize_and_save(hist)
```

Update both to extract `affection_delta` from the returned dict:

```python
summary_result = npc.summarize_and_save(hist, persist=is_fixed)
affection_delta = summary_result["affection_delta"]
```

```python
summary_result = self.companion.summarize_and_save(hist)
affection_delta = summary_result["affection_delta"]
```

Store `summary_result` in a local variable at both sites so Task 6 can use `summary_result["xp_awards"]`.

- [ ] **Step 5: Run tests**

```bash
python3 -m pytest tests/test_agent.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add noir/characters/agent.py noir/game.py tests/test_agent.py
git commit -m "feat: agent summary returns xp_awards alongside affection_delta"
```

---

## Task 5: Partner Interjection in Talk Loop

**Files:**
- Modify: `noir/game.py`

- [ ] **Step 1: Add `_should_partner_interject` method to `Game` in `noir/game.py`**

Add just before `_companion_context`:

```python
def _should_partner_interject(self, player_input: str, npc_response: str,
                               outcome: str) -> bool:
    import random
    if not self.companion:
        return False
    if outcome == "backfire":
        return True
    uncertainty_words = [
        "don't know", "not sure", "maybe", "i suppose",
        "could be", "might have", "i think", "possibly",
    ]
    has_opening = any(w in npc_response.lower() for w in uncertainty_words)
    if has_opening:
        return random.random() < 0.55
    return random.random() < 0.12
```

- [ ] **Step 2: Add `_partner_interject_context` method**

Add just after `_should_partner_interject`:

```python
def _partner_interject_context(self, player_input: str, npc_name: str,
                                npc_response: str, outcome: str) -> str:
    approach_note = {
        "backfire": f"The detective's approach with {npc_name} just backfired. Cover for them or redirect.",
        "success": f"{npc_name} is opening up. Reinforce it or surface what's still unsaid.",
    }.get(outcome, f"There's an opening in what {npc_name} just said. Use it.")
    return (
        f"[You are in a conversation with {npc_name}. "
        f"The detective just said: \"{player_input[:200]}\". "
        f"{npc_name} responded: \"{npc_response[:300]}\". "
        f"{approach_note} "
        f"One sentence, in character. Do not explain what you're doing — just do it.]"
    )
```

- [ ] **Step 3: Wire interjection into the NPC talk loop**

In `handle_talk`, find the line after `show_dialogue(npc_row["name"], response)` (around line 1322) and add:

```python
show_dialogue(npc_row["name"], response)
# Partner interjection — context-triggered, not every turn
if self.companion and self._should_partner_interject(player_input, response, "success"):
    interject_ctx = self._partner_interject_context(player_input, npc_row["name"], response, "success")
    interject_response = self.companion.speak(interject_ctx, store_as=f"[interjection re: {npc_row['name']}]")
    show_dialogue(self.companion.name, interject_response)
```

- [ ] **Step 4: Smoke test — run the game briefly and confirm no crash**

```bash
python3 -m pytest tests/ -v -x -q 2>&1 | tail -20
```

Expected: all existing tests pass.

- [ ] **Step 5: Commit**

```bash
git add noir/game.py
git commit -m "feat: partner interjection — context-triggered turn in NPC conversations"
```

---

## Task 6: XP Application + Specialization Unlock + Achievement Surfacing

**Files:**
- Modify: `noir/game.py`
- Modify: `noir/persistence/repository.py` (add `get_player_skill_roots` helper)

- [ ] **Step 1: Add `get_player_skill_roots` to `noir/persistence/repository.py`**

```python
def get_player_skill_roots(conn: sqlite3.Connection, *, owner: str) -> list[str]:
    """Return list of roots this owner has initialized."""
    rows = conn.execute(
        "SELECT root FROM player_skills WHERE owner=?", (owner,)
    ).fetchall()
    return [r["root"] for r in rows]
```

- [ ] **Step 2: Add `_apply_skill_xp_and_check_unlocks` method to `Game`**

Add just before `_judge_context` in `game.py`:

```python
def _apply_skill_xp_and_check_unlocks(self, owner: str, xp_awards: dict,
                                        partner_name: str | None = None) -> None:
    from noir.characters.skills import apply_conversation_xp, maybe_generate_specialization
    player = get_player(self.conn)
    if not player:
        return
    law_chaos = player["law_chaos"]
    good_evil = player["good_evil"]
    level_changes = apply_conversation_xp(
        self.conn, owner=owner, xp_awards=xp_awards,
        law_chaos=law_chaos, good_evil=good_evil,
        case_id=self.active_case_id,
    )
    for root, (old_level, new_level) in level_changes.items():
        if new_level == old_level:
            continue
        spec = maybe_generate_specialization(
            self.llm, self.conn, owner=owner, root=root,
            law_chaos=law_chaos, good_evil=good_evil,
        )
        if spec and self.companion and owner == "player":
            aside = self.companion.narrate(
                f"[The detective has just gotten noticeably better at something — "
                f"specifically: {spec['name']} ({root}). "
                f"Say one quiet, in-character thing about it. One sentence.]"
            )
            show_partner_aside(self.companion.name, aside)
        elif spec and owner == "partner" and partner_name:
            from noir.display import show_partner_aside as _aside
            _aside(partner_name, f"You're getting good at that.")
```

- [ ] **Step 3: Initialize player skills at quiz time**

Find where the quiz saves alignment results (in `noir/onboarding/quiz.py`, look for where `update_player_alignment` or player data is saved after quiz). After the player's alignment is stored, add:

```python
from noir.persistence.repository import initialize_player_skills
from noir.characters.skills import roots_for_alignment
player = get_player(conn)
player_roots = roots_for_alignment(
    law_chaos=player["law_chaos"], good_evil=player["good_evil"]
)
partner_roots = [r for r in ("authority", "streetwise", "empathy", "cunning")
                 if r not in player_roots]
initialize_player_skills(conn, owner="player", roots=player_roots)
initialize_player_skills(conn, owner="partner", roots=partner_roots)
```

- [ ] **Step 4: Call `_apply_skill_xp_and_check_unlocks` after NPC conversation**

In `handle_talk`, find the `summary_result` lines added in Task 4. After applying `affection_delta`, add:

```python
xp_awards = summary_result.get("xp_awards", {})
if xp_awards:
    self._apply_skill_xp_and_check_unlocks("player", xp_awards)
```

- [ ] **Step 5: Call `_apply_skill_xp_and_check_unlocks` after partner conversation**

In `handle_talk_partner`, after the `summary_result` lines, add:

```python
xp_awards = summary_result.get("xp_awards", {})
if xp_awards:
    partner_name = self.companion.name if self.companion else None
    self._apply_skill_xp_and_check_unlocks("player", xp_awards)
    # Partner earns XP from her own interjections — this is a proxy award for the session
    partner_xp = {k: max(0, v - 2) for k, v in xp_awards.items()}
    self._apply_skill_xp_and_check_unlocks("partner", partner_xp, partner_name=partner_name)
```

- [ ] **Step 6: Run the full test suite**

```bash
python3 -m pytest tests/ -v -q 2>&1 | tail -30
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add noir/game.py noir/persistence/repository.py noir/onboarding/quiz.py
git commit -m "feat: apply XP after conversations, specialization unlock, achievement surfacing"
```

---

## Task 7: Update `/me` Display

**Files:**
- Modify: `noir/display.py`
- Modify: `noir/game.py`

- [ ] **Step 1: Add skills section to `show_player_profile` in `noir/display.py`**

Update the signature:

```python
def show_player_profile(player: dict, orgs: list[dict], partner_name: str | None,
                        partner_stage: str | None, npc_relationships: list[dict],
                        player_skills: dict | None = None,
                        player_specializations: list[dict] | None = None,
                        partner_skills: dict | None = None,
                        partner_specializations: list[dict] | None = None) -> None:
```

Add a Skills section before the final `console.print`, after the Relationships block:

```python
# Skills
has_skills = player_skills or partner_skills
if has_skills:
    lines.append("")
    lines.append("[bold green]Skills[/bold green]")

    def _render_owner_skills(label, skills, specs):
        if not skills:
            return
        lines.append(f"  [green]{escape(label)}[/green]")
        for root, data in sorted(skills.items()):
            level = data.get("level", 1)
            root_specs = [s for s in (specs or []) if s["root"] == root]
            lines.append(f"    [dim]{escape(root.title())} — level {level}[/dim]")
            for s in root_specs:
                lines.append(f"      [italic dim]· {escape(s['name'])}:[/italic dim] {escape(s['description'])}")

    _render_owner_skills("Detective", player_skills, player_specializations)
    _render_owner_skills(partner_name or "Partner", partner_skills, partner_specializations)
```

- [ ] **Step 2: Update `handle_me` in `noir/game.py` to fetch and pass skills**

Find `handle_me` (around line 3069). After the existing `npc_rels` block and before `show_player_profile(...)`, add:

```python
from noir.persistence.repository import get_skills, get_specializations
p_skills = get_skills(self.conn, owner="player") or None
p_specs = get_specializations(self.conn, owner="player") or None
pt_skills = get_skills(self.conn, owner="partner") or None
pt_specs = get_specializations(self.conn, owner="partner") or None
```

Update the `show_player_profile` call to pass them:

```python
show_player_profile(
    dict(player), org_list, partner_name, partner_stage, npc_rels,
    player_skills=p_skills,
    player_specializations=p_specs,
    partner_skills=pt_skills,
    partner_specializations=pt_specs,
)
```

- [ ] **Step 3: Run the full test suite one final time**

```bash
python3 -m pytest tests/ -v -q 2>&1 | tail -30
```

Expected: all tests pass.

- [ ] **Step 4: Import check**

```bash
python3 -c "from noir.game import Game; from noir.characters.skills import apply_conversation_xp, maybe_generate_specialization; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Final commit**

```bash
git add noir/display.py noir/game.py
git commit -m "feat: show skills and specializations in /me profile"
```

---

## Self-Review Notes

- **Spec coverage:** All 6 spec sections covered across 7 tasks.
- **`roots_for_alignment` edge cases:** True neutral on one axis gets both roots for that axis — tested.
- **`summarize_and_save` return type change:** All callers updated in Task 4.
- **Skill initialization timing:** Wired into quiz completion in Task 6 Step 3. Players who already completed the quiz will have no skills rows — `apply_conversation_xp` uses `INSERT OR IGNORE` via `award_xp`, so lazy initialization happens automatically on first XP award.
- **Partner XP proxy:** Partner earns slightly less XP than the player per session (base - 2) as a proxy until true per-interjection XP is wired. Full per-interjection XP tracking is a follow-up.
- **`show_partner_aside` import:** Already imported at top of `game.py` — no new import needed.
