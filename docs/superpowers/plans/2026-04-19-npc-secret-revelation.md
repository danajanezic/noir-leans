# NPC Secret Revelation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make NPC secret revelation depend on a per-NPC psychological profile — pressure tolerance, empathy, guilt — with dynamic state that responds to how the player interrogates them.

**Architecture:** Six psychological traits are generated per NPC and stored on the `npcs` table. Dynamic state (guilt, pressure score, revelation stage) lives on `npc_relationships`. After each NPC exchange, a Haiku call classifies the exchange into five boolean events; a pure-Python scorer updates state; when a combined threshold is crossed, a revelation prompt fires. All psychology logic lives in `noir/characters/psychology.py`.

**Tech Stack:** SQLite, Python 3.12+, pytest, `MockLLMBackend` (`noir/llm/mock.py`)

---

## File Map

| File | Role |
|------|------|
| `noir/persistence/db.py` | Add new columns to `npcs` and `npc_relationships` via `_MIGRATIONS` |
| `noir/persistence/repository.py` | Update `create_npc()`; add `initialize_npc_relationship()`, `get_npc_psychology()`, `get_npc_psychological_state()`, `update_npc_guilt()`, `update_npc_pressure()`, `get_npc_revelation_stage()`, `increment_npc_revelation_stage()` |
| `noir/characters/psychology.py` | New — `classify_exchange()`, state update helpers, threshold logic, `check_revelation()` |
| `noir/mystery/generator.py` | Add new fields to `REQUIRED_SUSPECT_FIELDS` and both generation prompts |
| `noir/game.py` | Pass new fields to `create_npc()`; replace raw INSERT with `initialize_npc_relationship()`; call `check_revelation()` |
| `tests/test_psychology.py` | New — all psychology tests |
| `tests/test_generator.py` | New — generator validation tests for new fields |

---

## Task 1: DB Schema Migrations

**Files:**
- Modify: `noir/persistence/db.py`
- Test: `tests/test_psychology.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_psychology.py
import sqlite3
import pytest
from noir.persistence.db import create_schema


def _make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def test_npcs_has_psychology_columns():
    conn = _make_conn()
    create_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(npcs)")}
    assert "pressure_tolerance" in cols
    assert "kindness_weight" in cols
    assert "empathy" in cols
    assert "starting_guilt" in cols
    assert "revelation_style" in cols
    assert "revelation_stages" in cols


def test_npc_relationships_has_psychology_columns():
    conn = _make_conn()
    create_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(npc_relationships)")}
    assert "guilt" in cols
    assert "pressure_score" in cols
    assert "revelation_stage" in cols
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_psychology.py -v
```

Expected: FAIL — columns not found.

- [ ] **Step 3: Add migrations to `noir/persistence/db.py`**

Append to the `_MIGRATIONS` list in `noir/persistence/db.py` (after the last existing entry):

```python
    "ALTER TABLE npcs ADD COLUMN pressure_tolerance INTEGER DEFAULT 5",
    "ALTER TABLE npcs ADD COLUMN kindness_weight INTEGER DEFAULT 5",
    "ALTER TABLE npcs ADD COLUMN empathy INTEGER DEFAULT 5",
    "ALTER TABLE npcs ADD COLUMN starting_guilt INTEGER DEFAULT 3",
    "ALTER TABLE npcs ADD COLUMN revelation_style TEXT DEFAULT 'sudden'",
    "ALTER TABLE npcs ADD COLUMN revelation_stages INTEGER DEFAULT 1",
    "ALTER TABLE npc_relationships ADD COLUMN guilt INTEGER DEFAULT 0",
    "ALTER TABLE npc_relationships ADD COLUMN pressure_score INTEGER DEFAULT 0",
    "ALTER TABLE npc_relationships ADD COLUMN revelation_stage INTEGER DEFAULT 0",
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python3 -m pytest tests/test_psychology.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add noir/persistence/db.py tests/test_psychology.py
git commit -m "feat: add psychology columns to npcs and npc_relationships"
```

---

## Task 2: Repository Functions

**Files:**
- Modify: `noir/persistence/repository.py`
- Test: `tests/test_psychology.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_psychology.py`:

```python
from noir.persistence.repository import (
    create_npc, initialize_npc_relationship,
    get_npc_psychology, get_npc_psychological_state,
    update_npc_guilt, update_npc_pressure,
    get_npc_revelation_stage, increment_npc_revelation_stage,
)


def _make_npc(conn, **kwargs) -> int:
    """Insert a minimal case+location and return a new npc_id."""
    conn.execute("INSERT INTO cases (archetype, title, case_data) VALUES ('test','test','{}')")
    case_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute("INSERT INTO locations (name, description) VALUES ('Office', 'A dim room')")
    loc_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    return create_npc(
        conn, case_id=case_id, name="Rex Fontaine", role="suspect",
        system_prompt="You are Rex.", current_location_id=loc_id, **kwargs
    )


def test_create_npc_stores_psychology():
    conn = _make_conn()
    create_schema(conn)
    npc_id = _make_npc(conn, pressure_tolerance=2, kindness_weight=8,
                       empathy=7, starting_guilt=6,
                       revelation_style="staged", revelation_stages=3)
    p = get_npc_psychology(conn, npc_id)
    assert p["pressure_tolerance"] == 2
    assert p["kindness_weight"] == 8
    assert p["empathy"] == 7
    assert p["starting_guilt"] == 6
    assert p["revelation_style"] == "staged"
    assert p["revelation_stages"] == 3


def test_initialize_npc_relationship_sets_guilt():
    conn = _make_conn()
    create_schema(conn)
    npc_id = _make_npc(conn, starting_guilt=5)
    initialize_npc_relationship(conn, npc_id, starting_guilt=5)
    state = get_npc_psychological_state(conn, npc_id)
    assert state["guilt"] == 50
    assert state["pressure_score"] == 0
    assert state["revelation_stage"] == 0


def test_update_npc_guilt_clamps():
    conn = _make_conn()
    create_schema(conn)
    npc_id = _make_npc(conn)
    initialize_npc_relationship(conn, npc_id)
    update_npc_guilt(conn, npc_id, 200)
    assert get_npc_psychological_state(conn, npc_id)["guilt"] == 100
    update_npc_guilt(conn, npc_id, -300)
    assert get_npc_psychological_state(conn, npc_id)["guilt"] == 0


def test_update_npc_pressure_clamps():
    conn = _make_conn()
    create_schema(conn)
    npc_id = _make_npc(conn)
    initialize_npc_relationship(conn, npc_id)
    update_npc_pressure(conn, npc_id, 150)
    assert get_npc_psychological_state(conn, npc_id)["pressure_score"] == 100
    update_npc_pressure(conn, npc_id, -300)
    assert get_npc_psychological_state(conn, npc_id)["pressure_score"] == 0


def test_increment_npc_revelation_stage():
    conn = _make_conn()
    create_schema(conn)
    npc_id = _make_npc(conn)
    initialize_npc_relationship(conn, npc_id)
    assert get_npc_revelation_stage(conn, npc_id) == 0
    increment_npc_revelation_stage(conn, npc_id)
    assert get_npc_revelation_stage(conn, npc_id) == 1
    increment_npc_revelation_stage(conn, npc_id)
    assert get_npc_revelation_stage(conn, npc_id) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_psychology.py -v
```

Expected: FAIL — new functions not defined.

- [ ] **Step 3: Update `create_npc()` in `noir/persistence/repository.py`**

Replace the existing `create_npc` signature and INSERT:

```python
def create_npc(conn: sqlite3.Connection, *, case_id: int, name: str, role: str,
               system_prompt: str, current_location_id: int,
               alignment: str = "True Neutral", age: int = 35,
               pressure_tolerance: int = 5, kindness_weight: int = 5,
               empathy: int = 5, starting_guilt: int = 3,
               revelation_style: str = "sudden", revelation_stages: int = 1) -> int:
    cur = conn.execute(
        "INSERT INTO npcs (case_id, name, role, system_prompt, current_location_id, alignment, age, "
        "pressure_tolerance, kindness_weight, empathy, starting_guilt, revelation_style, revelation_stages) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (case_id, name, role, system_prompt, current_location_id, alignment, age,
         pressure_tolerance, kindness_weight, empathy, starting_guilt, revelation_style, revelation_stages)
    )
    conn.commit()
    return cur.lastrowid
```

- [ ] **Step 4: Add new repository functions to `noir/persistence/repository.py`**

Add these after `set_npc_secret_revealed`:

```python
def initialize_npc_relationship(conn: sqlite3.Connection, npc_id: int,
                                 starting_guilt: int = 3) -> None:
    conn.execute(
        """INSERT INTO npc_relationships (npc_id, guilt)
           VALUES (?, ?)
           ON CONFLICT(npc_id) DO NOTHING""",
        (npc_id, starting_guilt * 10)
    )
    conn.commit()


def get_npc_psychology(conn: sqlite3.Connection, npc_id: int) -> dict:
    row = conn.execute(
        "SELECT pressure_tolerance, kindness_weight, empathy, starting_guilt, "
        "revelation_style, revelation_stages FROM npcs WHERE id=?",
        (npc_id,)
    ).fetchone()
    if row is None:
        return {
            "pressure_tolerance": 5, "kindness_weight": 5, "empathy": 5,
            "starting_guilt": 3, "revelation_style": "sudden", "revelation_stages": 1,
        }
    return dict(row)


def get_npc_psychological_state(conn: sqlite3.Connection, npc_id: int) -> dict:
    row = conn.execute(
        "SELECT guilt, pressure_score, revelation_stage FROM npc_relationships WHERE npc_id=?",
        (npc_id,)
    ).fetchone()
    if row is None:
        return {"guilt": 0, "pressure_score": 0, "revelation_stage": 0}
    return dict(row)


def update_npc_guilt(conn: sqlite3.Connection, npc_id: int, delta: int) -> None:
    conn.execute(
        "UPDATE npc_relationships SET guilt = MAX(0, MIN(100, guilt + ?)) WHERE npc_id=?",
        (delta, npc_id)
    )
    conn.commit()


def update_npc_pressure(conn: sqlite3.Connection, npc_id: int, delta: int) -> None:
    conn.execute(
        "UPDATE npc_relationships SET pressure_score = MAX(0, MIN(100, pressure_score + ?)) "
        "WHERE npc_id=?",
        (delta, npc_id)
    )
    conn.commit()


def get_npc_revelation_stage(conn: sqlite3.Connection, npc_id: int) -> int:
    row = conn.execute(
        "SELECT revelation_stage FROM npc_relationships WHERE npc_id=?", (npc_id,)
    ).fetchone()
    return row["revelation_stage"] if row else 0


def increment_npc_revelation_stage(conn: sqlite3.Connection, npc_id: int) -> None:
    conn.execute(
        "UPDATE npc_relationships SET revelation_stage = revelation_stage + 1 WHERE npc_id=?",
        (npc_id,)
    )
    conn.commit()
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_psychology.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add noir/persistence/repository.py tests/test_psychology.py
git commit -m "feat: add psychology repository functions"
```

---

## Task 3: Event Classification

**Files:**
- Create: `noir/characters/psychology.py`
- Test: `tests/test_psychology.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_psychology.py`:

```python
import json
from noir.llm.mock import MockLLMBackend
from noir.characters.psychology import classify_exchange


def test_classify_exchange_detects_pressure():
    llm = MockLLMBackend(responses=[json.dumps({
        "pressure_applied": True, "threat_made": False,
        "kindness_shown": False, "guilt_trigger": False, "evidence_confronted": False,
    })])
    result = classify_exchange("You keep changing your story.", "I told you everything.", llm)
    assert result["pressure_applied"] is True
    assert result["threat_made"] is False
    assert result["kindness_shown"] is False


def test_classify_exchange_defaults_to_false_on_empty_response():
    llm = MockLLMBackend(responses=[json.dumps({})])
    result = classify_exchange("Hello.", "Hello.", llm)
    assert result == {
        "pressure_applied": False, "threat_made": False, "kindness_shown": False,
        "guilt_trigger": False, "evidence_confronted": False,
    }


def test_classify_exchange_coerces_to_bool():
    llm = MockLLMBackend(responses=[json.dumps({
        "pressure_applied": 1, "threat_made": 0,
        "kindness_shown": 1, "guilt_trigger": 0, "evidence_confronted": 0,
    })])
    result = classify_exchange("Think of the children.", "I... I know.", llm)
    assert result["pressure_applied"] is True
    assert result["threat_made"] is False
    assert result["kindness_shown"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_psychology.py::test_classify_exchange_detects_pressure -v
```

Expected: FAIL — `psychology` module not found.

- [ ] **Step 3: Create `noir/characters/psychology.py`** with the classifier

```python
from __future__ import annotations

from noir.llm.base import LLMBackend

_CLASSIFY_SYSTEM = (
    "You are classifying a player-NPC exchange in a noir detective game. "
    "Return ONLY JSON with exactly these five boolean fields:\n"
    '{"pressure_applied": bool, "threat_made": bool, "kindness_shown": bool, '
    '"guilt_trigger": bool, "evidence_confronted": bool}\n\n'
    "pressure_applied: player pushed on the same topic or confronted with evidence\n"
    "threat_made: player threatened the NPC explicitly\n"
    "kindness_shown: player was sympathetic, warm, or supportive\n"
    "guilt_trigger: player referenced victim suffering, consequences, or people left behind\n"
    "evidence_confronted: player cited a specific contradiction in the NPC's story"
)


def classify_exchange(player_input: str, npc_response: str, llm: LLMBackend) -> dict:
    result = llm.query_structured(
        _CLASSIFY_SYSTEM, [],
        f"Player: {player_input!r}\nNPC: {npc_response!r}",
    )
    return {
        "pressure_applied": bool(result.get("pressure_applied", False)),
        "threat_made": bool(result.get("threat_made", False)),
        "kindness_shown": bool(result.get("kindness_shown", False)),
        "guilt_trigger": bool(result.get("guilt_trigger", False)),
        "evidence_confronted": bool(result.get("evidence_confronted", False)),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_psychology.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add noir/characters/psychology.py tests/test_psychology.py
git commit -m "feat: add NPC exchange event classifier"
```

---

## Task 4: State Update and Threshold Logic

**Files:**
- Modify: `noir/characters/psychology.py`
- Test: `tests/test_psychology.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_psychology.py`:

```python
from noir.characters.psychology import (
    _pressure_delta, _guilt_delta, _combined_score, _next_threshold,
)

_NO_EVENTS = {
    "pressure_applied": False, "threat_made": False,
    "kindness_shown": False, "guilt_trigger": False, "evidence_confronted": False,
}


def test_pressure_delta_decays_when_no_pressure():
    assert _pressure_delta(_NO_EVENTS, pressure_tolerance=5) == -5


def test_pressure_delta_higher_for_low_tolerance():
    events = {**_NO_EVENTS, "pressure_applied": True}
    low = _pressure_delta(events, pressure_tolerance=1)
    high = _pressure_delta(events, pressure_tolerance=9)
    assert low > high


def test_pressure_delta_threat_larger_than_push():
    push = _pressure_delta({**_NO_EVENTS, "pressure_applied": True}, pressure_tolerance=5)
    threat = _pressure_delta({**_NO_EVENTS, "threat_made": True}, pressure_tolerance=5)
    assert threat > push


def test_guilt_delta_zero_with_no_emotional_events():
    assert _guilt_delta(_NO_EVENTS, empathy=10) == 0


def test_guilt_delta_scales_with_empathy():
    events = {**_NO_EVENTS, "guilt_trigger": True}
    low = _guilt_delta(events, empathy=1)
    high = _guilt_delta(events, empathy=10)
    assert high > low


def test_combined_score():
    state = {"pressure_score": 30, "guilt": 20, "revelation_stage": 0}
    psychology = {"kindness_weight": 10, "revelation_style": "staged", "revelation_stages": 3}
    # 30 + 20 + (50 * 10 // 10) = 100
    assert _combined_score(state, psychology, affection=50) == 100


def test_next_threshold_sudden_unrevealed():
    assert _next_threshold(0, {"revelation_style": "sudden", "revelation_stages": 1}) == 100


def test_next_threshold_sudden_already_revealed():
    assert _next_threshold(1, {"revelation_style": "sudden", "revelation_stages": 1}) is None


def test_next_threshold_staged_2():
    p = {"revelation_style": "staged", "revelation_stages": 2}
    assert _next_threshold(0, p) == 60
    assert _next_threshold(1, p) == 100
    assert _next_threshold(2, p) is None


def test_next_threshold_staged_4():
    p = {"revelation_style": "staged", "revelation_stages": 4}
    assert _next_threshold(0, p) == 40
    assert _next_threshold(1, p) == 60
    assert _next_threshold(2, p) == 80
    assert _next_threshold(3, p) == 100
    assert _next_threshold(4, p) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_psychology.py -k "delta or threshold or combined" -v
```

Expected: FAIL — functions not defined.

- [ ] **Step 3: Add state helpers to `noir/characters/psychology.py`**

Append after `classify_exchange`:

```python
_STAGED_THRESHOLDS: dict[int, list[int]] = {
    2: [60, 100],
    3: [50, 75, 100],
    4: [40, 60, 80, 100],
    5: [35, 55, 70, 85, 100],
}


def _pressure_delta(events: dict, pressure_tolerance: int) -> int:
    resist = 11 - pressure_tolerance
    delta = 0
    if events["pressure_applied"]:
        delta += resist * 5
    if events["threat_made"]:
        delta += resist * 10
    if events["evidence_confronted"]:
        delta += resist * 8
    return delta if delta > 0 else -5


def _guilt_delta(events: dict, empathy: int) -> int:
    delta = 0
    if events["kindness_shown"]:
        delta += empathy * 2
    if events["guilt_trigger"]:
        delta += empathy * 4
    return delta


def _combined_score(state: dict, psychology: dict, affection: int) -> int:
    return (
        state["pressure_score"]
        + state["guilt"]
        + (affection * psychology["kindness_weight"] // 10)
    )


def _next_threshold(current_stage: int, psychology: dict) -> int | None:
    if psychology["revelation_style"] == "sudden":
        return 100 if current_stage == 0 else None
    thresholds = _STAGED_THRESHOLDS.get(psychology["revelation_stages"], [100])
    if current_stage >= len(thresholds):
        return None
    return thresholds[current_stage]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_psychology.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add noir/characters/psychology.py tests/test_psychology.py
git commit -m "feat: add NPC psychological state update and threshold logic"
```

---

## Task 5: Revelation Trigger

**Files:**
- Modify: `noir/characters/psychology.py`
- Test: `tests/test_psychology.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_psychology.py`:

```python
from noir.characters.psychology import _build_revelation_prompt, check_revelation
from noir.persistence.repository import set_npc_secret_revealed, get_npc_relationship_flags


class _MockNPC:
    def __init__(self, name="Rex Fontaine", response="I'll tell you everything."):
        self.name = name
        self._response = response
        self.speak_calls: list[str] = []

    def speak(self, prompt: str, record: bool = True) -> str:
        self.speak_calls.append(prompt)
        return self._response


def test_build_revelation_prompt_sudden():
    events = {**_NO_EVENTS, "pressure_applied": True}
    prompt = _build_revelation_prompt(stage=1, total_stages=1, events=events, style="sudden")
    assert "breaking point" in prompt
    assert "pressure_applied" in prompt


def test_build_revelation_prompt_staged():
    events = {**_NO_EVENTS, "guilt_trigger": True, "kindness_shown": True}
    prompt = _build_revelation_prompt(stage=2, total_stages=4, events=events, style="staged")
    assert "stage 2 of 4" in prompt
    assert "1/4 of your secret" in prompt
    assert "guilt_trigger" in prompt


def test_check_revelation_fires_staged_on_threshold():
    conn = _make_conn()
    create_schema(conn)
    # 4-stage NPC: threshold[0]=40. Set pressure=45 so after -5 decay combined=40 >= 40.
    npc_id = _make_npc(conn, pressure_tolerance=5, kindness_weight=1, empathy=1,
                       starting_guilt=0, revelation_style="staged", revelation_stages=4)
    initialize_npc_relationship(conn, npc_id, starting_guilt=0)
    update_npc_pressure(conn, npc_id, 45)

    npc = _MockNPC()
    llm = MockLLMBackend(responses=[
        json.dumps({k: False for k in ["pressure_applied","threat_made","kindness_shown","guilt_trigger","evidence_confronted"]}),
    ])
    result = check_revelation(npc_id, npc, "I'm watching you.", "Fine.", conn, llm)
    assert result is not None
    assert len(npc.speak_calls) == 1
    assert get_npc_revelation_stage(conn, npc_id) == 1
    assert not get_npc_relationship_flags(conn, npc_id)["secret_revealed"]  # stage 1 of 4, not final


def test_check_revelation_does_not_fire_below_threshold():
    conn = _make_conn()
    create_schema(conn)
    npc_id = _make_npc(conn, pressure_tolerance=10, kindness_weight=1, empathy=1,
                       starting_guilt=0, revelation_style="sudden", revelation_stages=1)
    initialize_npc_relationship(conn, npc_id, starting_guilt=0)

    npc = _MockNPC()
    llm = MockLLMBackend(responses=[
        json.dumps({k: False for k in ["pressure_applied","threat_made","kindness_shown","guilt_trigger","evidence_confronted"]}),
    ])
    result = check_revelation(npc_id, npc, "Nice day.", "Indeed.", conn, llm)
    assert result is None
    assert len(npc.speak_calls) == 0


def test_check_revelation_guilt_override():
    conn = _make_conn()
    create_schema(conn)
    npc_id = _make_npc(conn, pressure_tolerance=10, kindness_weight=1, empathy=1,
                       starting_guilt=9, revelation_style="sudden", revelation_stages=1)
    initialize_npc_relationship(conn, npc_id, starting_guilt=9)
    # guilt starts at 90 — override fires immediately regardless of combined score
    llm = MockLLMBackend(responses=[
        json.dumps({k: False for k in ["pressure_applied","threat_made","kindness_shown","guilt_trigger","evidence_confronted"]}),
    ])
    npc = _MockNPC(response="I did it.")
    result = check_revelation(npc_id, npc, "Hello.", "Hello.", conn, llm)
    assert result == "I did it."


def test_check_revelation_skips_if_already_revealed():
    conn = _make_conn()
    create_schema(conn)
    npc_id = _make_npc(conn)
    initialize_npc_relationship(conn, npc_id)
    set_npc_secret_revealed(conn, npc_id)

    npc = _MockNPC()
    llm = MockLLMBackend()
    result = check_revelation(npc_id, npc, "Anything.", "Anything.", conn, llm)
    assert result is None
    assert llm.calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_psychology.py -k "revelation" -v
```

Expected: FAIL — `check_revelation` and `_build_revelation_prompt` not defined.

- [ ] **Step 3: Add revelation functions to `noir/characters/psychology.py`**

Append after the threshold helpers:

```python
def _build_revelation_prompt(stage: int, total_stages: int,
                              events: dict, style: str) -> str:
    fired = [k for k, v in events.items() if v]
    events_desc = ", ".join(fired) if fired else "accumulated pressure and guilt"
    if style == "sudden":
        return (
            "[You have reached your breaking point. Tell the detective your secret — all of it. "
            f"What broke you: {events_desc}. "
            "Stay fully in character. No speeches. Speak the way this person actually speaks.]"
        )
    return (
        f"[You are about to reveal something you have been hiding. "
        f"This is stage {stage} of {total_stages} — reveal approximately "
        f"1/{total_stages} of your secret. Do not reveal more than this stage calls for. "
        f"What broke you open just now: {events_desc}. "
        "Stay fully in character. Do not announce that you are confessing. "
        "Speak naturally, as the moment demands.]"
    )


def check_revelation(
    npc_id: int,
    npc,
    player_input: str,
    npc_response: str,
    conn,
    llm: LLMBackend,
) -> str | None:
    from noir.persistence.repository import (
        get_npc_psychology, get_npc_psychological_state, get_npc_affection,
        get_npc_relationship_flags, update_npc_guilt, update_npc_pressure,
        get_npc_revelation_stage, increment_npc_revelation_stage,
        set_npc_secret_revealed,
    )

    if get_npc_relationship_flags(conn, npc_id)["secret_revealed"]:
        return None

    psychology = get_npc_psychology(conn, npc_id)
    events = classify_exchange(player_input, npc_response, llm)

    update_npc_pressure(conn, npc_id, _pressure_delta(events, psychology["pressure_tolerance"]))
    update_npc_guilt(conn, npc_id, _guilt_delta(events, psychology["empathy"]))

    state = get_npc_psychological_state(conn, npc_id)
    affection = get_npc_affection(conn, npc_id) or 0
    current_stage = get_npc_revelation_stage(conn, npc_id)
    threshold = _next_threshold(current_stage, psychology)

    if threshold is None:
        return None

    combined = _combined_score(state, psychology, affection)
    guilt_override = state["guilt"] >= 90

    if not guilt_override and combined < threshold:
        return None

    total = psychology["revelation_stages"] if psychology["revelation_style"] == "staged" else 1
    prompt = _build_revelation_prompt(
        stage=current_stage + 1,
        total_stages=total,
        events=events,
        style=psychology["revelation_style"],
    )
    revelation = npc.speak(prompt, record=False)
    increment_npc_revelation_stage(conn, npc_id)

    if get_npc_revelation_stage(conn, npc_id) >= total:
        set_npc_secret_revealed(conn, npc_id)

    return revelation
```

- [ ] **Step 4: Run all tests to verify they pass**

```bash
python3 -m pytest tests/test_psychology.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add noir/characters/psychology.py tests/test_psychology.py
git commit -m "feat: add check_revelation — NPC secret revelation trigger"
```

---

## Task 6: Generator — New Fields

**Files:**
- Modify: `noir/mystery/generator.py`
- Create: `tests/test_generator.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_generator.py
from noir.mystery.generator import REQUIRED_SUSPECT_FIELDS, _validate_case

_VALID_SUSPECT = {
    "name": "Rex Fontaine",
    "role": "suspect",
    "alibi": "was home",
    "secret": "he did it",
    "personality": "nervous",
    "speech_style": "clipped",
    "race": "white",
    "political_connections": "none",
    "backstory": "A former dockworker.",
    "routine": [{"time_start": "09:00", "time_end": "17:00", "location": "The Diner"}],
    "alignment": "Chaotic Neutral",
    "pressure_tolerance": 4,
    "kindness_weight": 6,
    "empathy": 5,
    "starting_guilt": 3,
    "revelation_style": "staged",
    "revelation_stages": 3,
    "relationships": [],
}

_VALID_CASE = {
    "title": "Death at the Docks",
    "victim": {"name": "Gerald Mink", "cause_of_death": "trombone", "found_at": "The Docks"},
    "killer_name": "Rex Fontaine",
    "motive": "jealousy",
    "suspects": [_VALID_SUSPECT, {**_VALID_SUSPECT, "name": "Vera Laine", "role": "witness"}],
    "clues": [{"description": "a bloodied fedora", "is_red_herring": False, "location": "The Docks"}],
    "locations": [{"name": "The Docks", "description": "Smells of fish and regret."}],
}


def test_required_suspect_fields_includes_psychology():
    assert "pressure_tolerance" in REQUIRED_SUSPECT_FIELDS
    assert "kindness_weight" in REQUIRED_SUSPECT_FIELDS
    assert "empathy" in REQUIRED_SUSPECT_FIELDS
    assert "starting_guilt" in REQUIRED_SUSPECT_FIELDS
    assert "revelation_style" in REQUIRED_SUSPECT_FIELDS
    assert "revelation_stages" in REQUIRED_SUSPECT_FIELDS


def test_validate_case_passes_with_psychology_fields():
    assert _validate_case(_VALID_CASE) is True


def test_validate_case_fails_missing_psychology_field():
    bad_suspect = {k: v for k, v in _VALID_SUSPECT.items() if k != "pressure_tolerance"}
    bad_case = {**_VALID_CASE, "suspects": [bad_suspect, bad_suspect]}
    assert _validate_case(bad_case) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_generator.py -v
```

Expected: FAIL — psychology fields missing from `REQUIRED_SUSPECT_FIELDS`.

- [ ] **Step 3: Update `REQUIRED_SUSPECT_FIELDS` in `noir/mystery/generator.py`**

```python
REQUIRED_SUSPECT_FIELDS = {
    "name", "role", "alibi", "secret", "personality", "speech_style", "race",
    "political_connections", "backstory", "routine", "alignment",
    "pressure_tolerance", "kindness_weight", "empathy", "starting_guilt",
    "revelation_style", "revelation_stages",
}
```

- [ ] **Step 4: Add psychology fields to the suspect schema in `generate()`**

In the `prompt` string inside `generate()`, find the suspect schema block (around the `"alignment"` line) and add after it:

```python
'     "pressure_tolerance": integer 1-10 (resistance to being pushed — 1=breaks immediately under pressure, 10=barely flinches),\n'
'     "kindness_weight": integer 1-10 (how much warmth and sympathy moves them),\n'
'     "empathy": integer 1-10 (how much their guilt responds to emotional appeals about victims and consequences),\n'
'     "starting_guilt": integer 0-10 (initial guilt at case start — 0=no guilt, 10=barely keeping it together),\n'
'     "revelation_style": "staged" or "sudden" (staged=reveals secret in pieces over multiple conversations, sudden=cracks all at once),\n'
'     "revelation_stages": integer 2-5 for staged NPCs, 1 for sudden NPCs}\n'
```

- [ ] **Step 5: Apply the same addition to `generate_from_dark_past()`**

Find the same suspect schema block in `generate_from_dark_past()` and add the identical six lines.

- [ ] **Step 6: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_generator.py -v
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add noir/mystery/generator.py tests/test_generator.py
git commit -m "feat: add psychology fields to mystery generator"
```

---

## Task 7: Wire Up in `game.py`

**Files:**
- Modify: `noir/game.py`

- [ ] **Step 1: Add import at the top of `noir/game.py`**

Add to the imports block (near the other character imports):

```python
from noir.characters.psychology import check_revelation
```

Add to the repository imports block:

```python
from noir.persistence.repository import (
    ...  # existing imports
    initialize_npc_relationship,
)
```

- [ ] **Step 2: Update the `create_npc()` call**

Find the `create_npc()` call in `game.py` (around line 322). It currently ends with `alignment=suspect.get("alignment", "True Neutral")`. Add the new keyword arguments:

```python
npc_id = create_npc(
    self.conn, case_id=case_id, name=suspect["name"],
    role=suspect["role"], system_prompt=npc_system_prompt,
    current_location_id=loc_id,
    alignment=suspect.get("alignment", "True Neutral"),
    pressure_tolerance=suspect.get("pressure_tolerance", 5),
    kindness_weight=suspect.get("kindness_weight", 5),
    empathy=suspect.get("empathy", 5),
    starting_guilt=suspect.get("starting_guilt", 3),
    revelation_style=suspect.get("revelation_style", "sudden"),
    revelation_stages=suspect.get("revelation_stages", 1),
)
```

- [ ] **Step 3: Replace raw `npc_relationships` INSERT with `initialize_npc_relationship`**

Find the line:

```python
self.conn.execute(
    "INSERT OR IGNORE INTO npc_relationships (npc_id) VALUES (?)", (npc_id,)
)
```

Replace it with:

```python
initialize_npc_relationship(self.conn, npc_id, suspect.get("starting_guilt", 3))
```

- [ ] **Step 4: Call `check_revelation` after the romance milestone check**

Find the NPC conversation handler in `game.py`. It contains:

```python
response = npc.speak(ctx + player_input)
show_dialogue(npc_row["name"], response)
self._check_npc_appointment(npc_row["id"], npc_row["name"], player_input, response)
self._check_npc_romance_milestone(npc_row["id"], npc)
```

Add the revelation check immediately after:

```python
revelation = check_revelation(
    npc_row["id"], npc, player_input, response, self.conn, self.llm
)
if revelation:
    show_dialogue(npc_row["name"], revelation)
```

- [ ] **Step 5: Run the full test suite**

```bash
python3 -m pytest tests/ -v
```

Expected: all PASS. No existing tests should be broken — `create_npc()` changes are backwards-compatible (all new params have defaults).

- [ ] **Step 6: Commit**

```bash
git add noir/game.py
git commit -m "feat: wire up NPC secret revelation in game loop"
```
