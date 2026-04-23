# Alignment Quiz Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the onboarding quiz with 8 new questions that place the player on the D&D two-axis alignment spectrum (Lawful/Neutral/Chaotic × Good/Neutral/Evil), store alignment as two integers that drift over time, assign complementary alignment to the partner, and inject alignment disposition into NPC conversations.

**Architecture:** A pure Python scoring function maps quiz answers to two axis scores; migrations add alignment columns to `player`, `partner`, and `npcs`; the mystery generator adds alignment to suspects; NPC conversations get a disposition prefix computed from player/NPC/partner alignments at load time.

**Tech Stack:** Python, SQLite via `sqlite3`, pytest

---

## File Map

| Action | File | Change |
|--------|------|--------|
| Modify | `noir/persistence/db.py` | Add 4 migration entries (law_chaos, good_evil on player; alignment on partner; alignment on npcs) |
| Modify | `noir/onboarding/quiz.py` | Replace QUIZ_QUESTIONS, add ALIGNMENT_WEIGHTS, score_alignment(), resolve_alignment(), alignment_disposition(); update Quiz.run() and QUIZ_SYSTEM_PROMPT |
| Modify | `noir/persistence/repository.py` | Add get_alignment(), update_player_alignment(); update save_partner(), create_npc() |
| Modify | `noir/mystery/generator.py` | Add "alignment" to REQUIRED_SUSPECT_FIELDS; add to case JSON schema prompt |
| Modify | `noir/game.py:322` | Pass `alignment=suspect.get("alignment", "True Neutral")` to create_npc() |
| Modify | `noir/characters/npc.py` | Add `alignment` attribute; override `_locked_system_prompt` to prepend disposition prefix |
| Modify | `tests/test_onboarding.py` | Update PARTNER_TRAITS mock; add tests for score_alignment, resolve_alignment, alignment stored |
| Modify | `tests/test_persistence.py` | Add tests for get_alignment, update_player_alignment, save_partner with alignment |
| Modify | `tests/test_mystery.py` | Add "alignment" to VALID_CASE suspects; test REQUIRED_SUSPECT_FIELDS includes alignment |

---

## Task 1: Schema Migrations

**Files:**
- Modify: `noir/persistence/db.py`
- Test: `tests/test_persistence.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_persistence.py`:

```python
def test_player_has_alignment_columns(db):
    create_player(db)
    player = get_player(db)
    assert player["law_chaos"] == 0
    assert player["good_evil"] == 0

def test_partner_has_alignment_column(db):
    save_partner(db, name="Vera", sex="female", personality_archetype="cynic",
                 speech_style="terse", relationship_stance="exasperated",
                 system_prompt="You are Vera.", alignment="True Neutral")
    partner = get_partner(db)
    assert partner["alignment"] == "True Neutral"

def test_npc_has_alignment_column(db):
    case_id = create_case(db, archetype="test", title="T", case_data="{}")
    loc_id = create_location(db, name="Bar", description="A bar.", is_fixed=True)
    npc_id = create_npc(db, case_id=case_id, name="Rex", role="suspect",
                        system_prompt="You are Rex.", current_location_id=loc_id,
                        alignment="Chaotic Evil")
    npc = get_npc(db, npc_id)
    assert npc["alignment"] == "Chaotic Evil"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/danajanezic/code/noir-leans && python3 -m pytest tests/test_persistence.py::test_player_has_alignment_columns tests/test_persistence.py::test_partner_has_alignment_column tests/test_persistence.py::test_npc_has_alignment_column -v
```

Expected: all three FAIL — OperationalError (column does not exist) or TypeError (unexpected argument)

- [ ] **Step 3: Add migrations to db.py**

In `noir/persistence/db.py`, append four entries to `_MIGRATIONS`:

```python
_MIGRATIONS = [
    "ALTER TABLE partner ADD COLUMN affection INTEGER DEFAULT 0",
    "ALTER TABLE partner ADD COLUMN dark_past_state TEXT DEFAULT 'none'",
    "ALTER TABLE partner ADD COLUMN dark_past TEXT",
    "ALTER TABLE cases ADD COLUMN case_type TEXT DEFAULT 'standard'",
    "ALTER TABLE player ADD COLUMN race TEXT DEFAULT 'unspecified'",
    "ALTER TABLE player ADD COLUMN gender TEXT DEFAULT 'unspecified'",
    "ALTER TABLE evidence ADD COLUMN clue_id INTEGER REFERENCES clues(id)",
    "ALTER TABLE player ADD COLUMN game_time INTEGER DEFAULT 480",
    "ALTER TABLE evidence ADD COLUMN accused_npc_id INTEGER REFERENCES npcs(id)",
    # Alignment additions
    "ALTER TABLE player ADD COLUMN law_chaos INTEGER DEFAULT 0",
    "ALTER TABLE player ADD COLUMN good_evil INTEGER DEFAULT 0",
    "ALTER TABLE partner ADD COLUMN alignment TEXT DEFAULT 'True Neutral'",
    "ALTER TABLE npcs ADD COLUMN alignment TEXT DEFAULT 'True Neutral'",
]
```

- [ ] **Step 4: Update save_partner() and create_npc() signatures**

In `noir/persistence/repository.py`, update `save_partner()`:

```python
def save_partner(conn: sqlite3.Connection, *, name: str, sex: str,
                 personality_archetype: str, speech_style: str,
                 relationship_stance: str, system_prompt: str,
                 alignment: str = "True Neutral") -> None:
    conn.execute(
        """INSERT OR REPLACE INTO partner
           (id, name, sex, personality_archetype, speech_style, relationship_stance, system_prompt, alignment)
           VALUES (1, ?, ?, ?, ?, ?, ?, ?)""",
        (name, sex, personality_archetype, speech_style, relationship_stance, system_prompt, alignment)
    )
    conn.commit()
```

Update `create_npc()`:

```python
def create_npc(conn: sqlite3.Connection, *, case_id: int, name: str, role: str,
               system_prompt: str, current_location_id: int,
               alignment: str = "True Neutral") -> int:
    cur = conn.execute(
        "INSERT INTO npcs (case_id, name, role, system_prompt, current_location_id, alignment) VALUES (?, ?, ?, ?, ?, ?)",
        (case_id, name, role, system_prompt, current_location_id, alignment)
    )
    conn.commit()
    return cur.lastrowid
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Users/danajanezic/code/noir-leans && python3 -m pytest tests/test_persistence.py::test_player_has_alignment_columns tests/test_persistence.py::test_partner_has_alignment_column tests/test_persistence.py::test_npc_has_alignment_column -v
```

Expected: all three PASS

- [ ] **Step 6: Run full test suite**

```bash
cd /Users/danajanezic/code/noir-leans && python3 -m pytest -v
```

Expected: all tests pass (existing tests use positional/keyword args that still work with new defaults)

- [ ] **Step 7: Commit**

```bash
cd /Users/danajanezic/code/noir-leans && git add noir/persistence/db.py noir/persistence/repository.py tests/test_persistence.py
git commit -m "feat: add alignment schema migrations and update save_partner/create_npc signatures"
```

---

## Task 2: Scoring Functions

**Files:**
- Modify: `noir/onboarding/quiz.py`
- Test: `tests/test_onboarding.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_onboarding.py`:

```python
from noir.onboarding.quiz import score_alignment, resolve_alignment

def test_score_alignment_sums_weights():
    # Q1-A: law+2, good-1; Q2-A: law+2, good+2; rest all D (law-1,good-1 or law0,good0)
    # Use known answers that produce a deterministic total
    answers = ["A", "A", "D", "D", "D", "D", "D", "D"]
    law, good = score_alignment(answers)
    # Q1-A: law+2 good-1; Q2-A: law+2 good+2; Q3-D: law-1 good-1; Q4-D: law+1 good0;
    # Q5-D: law-1 good-1; Q6-D: law-1 good-2; Q7-D: law0 good0; Q8-D: law0 good+1
    assert law == 2
    assert good == -2

def test_resolve_alignment_lawful_good():
    assert resolve_alignment(4, 4) == "Lawful Good"

def test_resolve_alignment_true_neutral():
    assert resolve_alignment(0, 0) == "True Neutral"

def test_resolve_alignment_chaotic_evil():
    assert resolve_alignment(-4, -4) == "Chaotic Evil"

def test_resolve_alignment_lawful_neutral():
    assert resolve_alignment(5, 2) == "Lawful Neutral"

def test_resolve_alignment_neutral_good():
    assert resolve_alignment(0, 6) == "Neutral Good"

def test_resolve_alignment_chaotic_neutral():
    assert resolve_alignment(-5, 0) == "Chaotic Neutral"

def test_resolve_alignment_lawful_evil():
    assert resolve_alignment(6, -5) == "Lawful Evil"

def test_resolve_alignment_neutral_evil():
    assert resolve_alignment(1, -6) == "Neutral Evil"

def test_resolve_alignment_chaotic_good():
    assert resolve_alignment(-5, 5) == "Chaotic Good"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/danajanezic/code/noir-leans && python3 -m pytest tests/test_onboarding.py::test_score_alignment_sums_weights tests/test_onboarding.py::test_resolve_alignment_lawful_good -v
```

Expected: FAIL — ImportError (functions not defined)

- [ ] **Step 3: Replace QUIZ_QUESTIONS and add scoring functions in quiz.py**

Replace the entire contents of `noir/onboarding/quiz.py` with:

```python
import sqlite3
from noir.llm.base import LLMBackend
from noir.persistence.repository import save_partner, update_player_alignment

QUIZ_QUESTIONS = [
    {
        "question": "A man drops his wallet. You pick it up. Inside: $40 cash, a photo of his kids, and a folded note that says \"Payment received. The judge will rule by Friday.\" You:",
        "options": [
            "A. Return it, cash and all. Not your business.",
            "B. Return the wallet, keep the cash. Consider it a fine.",
            "C. Keep everything and follow up on the note.",
            "D. Drop it in the nearest sewer. Let him wonder.",
        ]
    },
    {
        "question": "The judge in a case you're working is dirty. You know it. You can't prove it. You:",
        "options": [
            "A. Keep digging until you can prove it. Justice takes time.",
            "B. Work around him. Get the result through other channels.",
            "C. Blackmail him into ruling your way just this once.",
            "D. Accept it. Every system has rot. You're just one detective.",
        ]
    },
    {
        "question": "Noirleans has a law you think is unjust. You:",
        "options": [
            "A. Follow it. Laws exist for reasons, even bad ones.",
            "B. Break it quietly when necessary, without making it a statement.",
            "C. Break it loudly. Bad laws deserve public contempt.",
            "D. Use it when convenient, ignore it when not.",
        ]
    },
    {
        "question": "A client is lying to you. You know it. You:",
        "options": [
            "A. Confront them directly. You won't work a case blind.",
            "B. Keep working and figure out the real truth yourself.",
            "C. Bill them double and let them discover you know.",
            "D. Drop the case. Life's too short for people who waste your time.",
        ]
    },
    {
        "question": "You get evidence that would solve the case — but you got it illegally. You:",
        "options": [
            "A. Use it. Results matter more than procedure.",
            "B. Find a way to get it legally obtained. It takes longer but it's right.",
            "C. Use it if the guilty party deserves it. Don't use it if they don't.",
            "D. Sell it to the DA and let them figure out the paperwork.",
        ]
    },
    {
        "question": "Someone confesses to a crime you're not working. It's bad. You:",
        "options": [
            "A. Turn them in. That's the only correct answer.",
            "B. Hear them out first. Context matters before consequences.",
            "C. Tell them to leave town and not come back.",
            "D. File it away. Information is currency.",
        ]
    },
    {
        "question": "The killer you just caught will walk on a technicality. You:",
        "options": [
            "A. Let it happen. The process has to mean something.",
            "B. Plant corroborating evidence. They're guilty.",
            "C. Leak it to someone who'll handle it outside the courts.",
            "D. Beat yourself up about it and drink heavily.",
        ]
    },
    {
        "question": "Someone asks you to keep a secret that would hurt an innocent person if you keep it. You:",
        "options": [
            "A. Tell the truth. Secrets like that fester.",
            "B. Keep it. You made a promise.",
            "C. Use the information to quietly fix the situation without disclosure.",
            "D. Tell the person being hurt, not anyone else.",
        ]
    },
]

# (law_delta, good_delta) per question index, per answer key A/B/C/D
ALIGNMENT_WEIGHTS = [
    # Q1: corrupt man's wallet
    {"A": (2, -1), "B": (-1, 0), "C": (-1, 1), "D": (-2, 0)},
    # Q2: dirty judge
    {"A": (2, 2), "B": (-1, 1), "C": (-2, 0), "D": (0, -1)},
    # Q3: unjust law
    {"A": (2, -1), "B": (-1, 1), "C": (-2, 1), "D": (-1, -1)},
    # Q4: lying client
    {"A": (1, 1), "B": (0, 1), "C": (0, -1), "D": (1, 0)},
    # Q5: illegal evidence
    {"A": (-2, 1), "B": (2, 2), "C": (-1, 0), "D": (-1, -1)},
    # Q6: crime confession
    {"A": (2, 1), "B": (0, 1), "C": (-2, 0), "D": (-1, -2)},
    # Q7: killer walks on technicality
    {"A": (2, 0), "B": (-2, -1), "C": (-1, 0), "D": (0, 0)},
    # Q8: secret that hurts innocent
    {"A": (0, 2), "B": (2, -1), "C": (-1, 1), "D": (0, 1)},
]

VALID_ALIGNMENTS = {
    "Lawful Good", "Neutral Good", "Chaotic Good",
    "Lawful Neutral", "True Neutral", "Chaotic Neutral",
    "Lawful Evil", "Neutral Evil", "Chaotic Evil",
}


def score_alignment(answers: list[str]) -> tuple[int, int]:
    """Map quiz answers to (law_total, good_total). Each axis: -16 to +16."""
    law_total = 0
    good_total = 0
    for i, answer in enumerate(answers):
        key = answer.strip().upper()
        if i < len(ALIGNMENT_WEIGHTS) and key in ALIGNMENT_WEIGHTS[i]:
            law_delta, good_delta = ALIGNMENT_WEIGHTS[i][key]
            law_total += law_delta
            good_total += good_delta
    return law_total, good_total


def resolve_alignment(law: int, good: int) -> str:
    """Bucket (law, good) integer scores into one of nine named alignments."""
    if law >= 4:
        law_axis = "Lawful"
    elif law <= -4:
        law_axis = "Chaotic"
    else:
        law_axis = "Neutral"

    if good >= 4:
        good_axis = "Good"
    elif good <= -4:
        good_axis = "Evil"
    else:
        good_axis = "Neutral"

    if law_axis == "Neutral" and good_axis == "Neutral":
        return "True Neutral"
    if law_axis == "Neutral":
        return f"Neutral {good_axis}"
    if good_axis == "Neutral":
        return f"{law_axis} Neutral"
    return f"{law_axis} {good_axis}"


def alignment_disposition(player_alignment: str, npc_alignment: str) -> str:
    """Return 'aligned', 'opposed', or 'neutral' based on axis distance.

    Opposed: both axes differ by 2 steps (diagonally opposite).
    Aligned: both axes within 1 step of each other.
    Neutral: everything else.
    """
    _AXIS_ORDER = ["Chaotic", "Neutral", "Lawful"]
    _GOOD_ORDER = ["Evil", "Neutral", "Good"]

    def _parse(alignment: str):
        if alignment == "True Neutral":
            return (1, 1)  # Neutral/Neutral indices
        parts = alignment.split()
        if len(parts) == 2:
            law_part, good_part = parts
        else:
            return (1, 1)
        law_idx = _AXIS_ORDER.index(law_part) if law_part in _AXIS_ORDER else 1
        good_idx = _GOOD_ORDER.index(good_part) if good_part in _GOOD_ORDER else 1
        return (law_idx, good_idx)

    p_law, p_good = _parse(player_alignment)
    n_law, n_good = _parse(npc_alignment)

    law_dist = abs(p_law - n_law)
    good_dist = abs(p_good - n_good)

    if law_dist == 2 and good_dist == 2:
        return "opposed"
    if law_dist <= 1 and good_dist <= 1:
        return "aligned"
    return "neutral"


QUIZ_SYSTEM_PROMPT = """You are a character generator for an absurdist noir detective game set in Noirleans, 1935 — a city drowning in Depression-era desperation, jazz, and corruption.
Based on a player's quiz answers and their determined alignment, you create their detective partner — a character who is
over-the-top, deeply human, and funny in the vein of Hitchhiker's Guide to the Galaxy meets
hard-boiled noir. The partner serves as the player's Ford Prefect: guide, confidant, and
deadpan explainer of a deeply strange world.

The partner's alignment should complement the player's — opening doors the player cannot. A Chaotic Good player needs a partner who can vouch for them with lawful institutions. A Lawful Evil player needs a partner who can reach people who distrust authority. Pick the alignment that makes the partner most useful as a social key.

Return ONLY valid JSON with these fields:
{
  "name": "string (a great noir name)",
  "sex": "male"|"female"|"nonbinary",
  "personality_archetype": "string (one of: world-weary cynic, manic optimist, detached alien observer, barely-contained chaos, philosophical pragmatist)",
  "speech_style": "string (e.g. terse and hard-boiled, verbose and tangential, relentlessly cheerful, philosophically distracted)",
  "relationship_stance": "string (e.g. exasperated, protective, competitive, devoted, professionally baffled)",
  "alignment": "string (one of: Lawful Good, Neutral Good, Chaotic Good, Lawful Neutral, True Neutral, Chaotic Neutral, Lawful Evil, Neutral Evil, Chaotic Evil)",
  "system_prompt": "string (3-4 sentences describing this character's voice, personality, and role as the player's partner and world guide. They should feel like Ford Prefect — confident about strange things, gently exasperated by the player, and completely at home in an absurd universe.)"
}"""


class Quiz:

    def __init__(self, *, conn: sqlite3.Connection, llm: LLMBackend):
        self.conn = conn
        self.llm = llm

    @staticmethod
    def _resolve_option(q_idx: int, answer: str) -> str:
        if q_idx >= len(QUIZ_QUESTIONS):
            return answer
        options = QUIZ_QUESTIONS[q_idx]["options"]
        key = answer.strip().upper()
        for opt in options:
            if opt.startswith(key + ".") or opt.startswith(key + " "):
                return opt
        return answer

    def run(self, *, answers: list[str]) -> dict:
        law_total, good_total = score_alignment(answers)
        player_alignment = resolve_alignment(law_total, good_total)
        update_player_alignment(self.conn, law_delta=law_total, good_delta=good_total)

        answers_text = "\n".join(
            f"Q{i+1}: {QUIZ_QUESTIONS[i]['question']}\nAnswer: {self._resolve_option(i, answer)}"
            for i, answer in enumerate(answers)
            if i < len(QUIZ_QUESTIONS)
        )
        prompt = (
            f"Player alignment: {player_alignment}.\n\n"
            f"A player has answered the following quiz questions:\n\n{answers_text}\n\n"
            "Based on these answers and the player's alignment, generate their detective partner. "
            "Return the JSON partner profile."
        )
        self.llm.status_message = "Creating your perfect antagonist..."
        traits = self.llm.query_structured(QUIZ_SYSTEM_PROMPT, [], prompt)
        self.llm.status_message = "Thinking..."
        save_partner(
            self.conn,
            name=traits["name"],
            sex=traits["sex"],
            personality_archetype=traits["personality_archetype"],
            speech_style=traits["speech_style"],
            relationship_stance=traits["relationship_stance"],
            system_prompt=traits["system_prompt"],
            alignment=traits.get("alignment", "True Neutral"),
        )
        return traits
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/danajanezic/code/noir-leans && python3 -m pytest tests/test_onboarding.py::test_score_alignment_sums_weights tests/test_onboarding.py::test_resolve_alignment_lawful_good tests/test_onboarding.py::test_resolve_alignment_true_neutral tests/test_onboarding.py::test_resolve_alignment_chaotic_evil tests/test_onboarding.py::test_resolve_alignment_lawful_neutral tests/test_onboarding.py::test_resolve_alignment_neutral_good tests/test_onboarding.py::test_resolve_alignment_chaotic_neutral tests/test_onboarding.py::test_resolve_alignment_lawful_evil tests/test_onboarding.py::test_resolve_alignment_neutral_evil tests/test_onboarding.py::test_resolve_alignment_chaotic_good -v
```

Expected: all PASS

- [ ] **Step 5: Run full test suite**

```bash
cd /Users/danajanezic/code/noir-leans && python3 -m pytest -v
```

Expected: all tests pass. Note: `test_quiz_questions_are_defined` still passes because new QUIZ_QUESTIONS has 8 items.

- [ ] **Step 6: Commit**

```bash
cd /Users/danajanezic/code/noir-leans && git add noir/onboarding/quiz.py tests/test_onboarding.py
git commit -m "feat: replace quiz questions with alignment-weighted set; add score_alignment, resolve_alignment, alignment_disposition"
```

---

## Task 3: Repository Alignment Functions

**Files:**
- Modify: `noir/persistence/repository.py`
- Test: `tests/test_persistence.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_persistence.py`:

```python
from noir.persistence.repository import (
    update_player_alignment, get_alignment
)

def test_update_player_alignment_sets_scores(db):
    create_player(db)
    update_player_alignment(db, law_delta=6, good_delta=-3)
    player = get_player(db)
    assert player["law_chaos"] == 6
    assert player["good_evil"] == -3

def test_update_player_alignment_accumulates(db):
    create_player(db)
    update_player_alignment(db, law_delta=3, good_delta=2)
    update_player_alignment(db, law_delta=2, good_delta=-1)
    player = get_player(db)
    assert player["law_chaos"] == 5
    assert player["good_evil"] == 1

def test_update_player_alignment_clamps_to_bounds(db):
    create_player(db)
    update_player_alignment(db, law_delta=20, good_delta=-20)
    player = get_player(db)
    assert player["law_chaos"] == 16
    assert player["good_evil"] == -16

def test_get_alignment_lawful_good(db):
    create_player(db)
    update_player_alignment(db, law_delta=5, good_delta=5)
    player = get_player(db)
    assert get_alignment(player) == "Lawful Good"

def test_get_alignment_true_neutral(db):
    create_player(db)
    player = get_player(db)
    assert get_alignment(player) == "True Neutral"

def test_get_alignment_chaotic_evil(db):
    create_player(db)
    update_player_alignment(db, law_delta=-6, good_delta=-6)
    player = get_player(db)
    assert get_alignment(player) == "Chaotic Evil"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/danajanezic/code/noir-leans && python3 -m pytest tests/test_persistence.py::test_update_player_alignment_sets_scores tests/test_persistence.py::test_get_alignment_lawful_good -v
```

Expected: FAIL — ImportError (functions not defined)

- [ ] **Step 3: Add update_player_alignment() and get_alignment() to repository.py**

Add after `update_player_stats()` in `noir/persistence/repository.py`:

```python
def update_player_alignment(conn: sqlite3.Connection, *,
                             law_delta: int = 0, good_delta: int = 0) -> None:
    conn.execute(
        """UPDATE player SET
           law_chaos = MAX(-16, MIN(16, law_chaos + ?)),
           good_evil = MAX(-16, MIN(16, good_evil + ?))
           WHERE id=1""",
        (law_delta, good_delta)
    )
    conn.commit()


def get_alignment(player: sqlite3.Row) -> str:
    from noir.onboarding.quiz import resolve_alignment
    return resolve_alignment(player["law_chaos"], player["good_evil"])
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/danajanezic/code/noir-leans && python3 -m pytest tests/test_persistence.py::test_update_player_alignment_sets_scores tests/test_persistence.py::test_update_player_alignment_accumulates tests/test_persistence.py::test_update_player_alignment_clamps_to_bounds tests/test_persistence.py::test_get_alignment_lawful_good tests/test_persistence.py::test_get_alignment_true_neutral tests/test_persistence.py::test_get_alignment_chaotic_evil -v
```

Expected: all PASS

- [ ] **Step 5: Run full test suite**

```bash
cd /Users/danajanezic/code/noir-leans && python3 -m pytest -v
```

Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
cd /Users/danajanezic/code/noir-leans && git add noir/persistence/repository.py tests/test_persistence.py
git commit -m "feat: add update_player_alignment and get_alignment to repository"
```

---

## Task 4: Update Quiz.run() Tests

**Files:**
- Test: `tests/test_onboarding.py`

The Quiz.run() implementation is already complete from Task 2. This task updates the existing tests that will now fail because the mock LLM response needs an `alignment` field, and adds a test that player alignment is stored.

- [ ] **Step 1: Run the existing onboarding tests to identify failures**

```bash
cd /Users/danajanezic/code/noir-leans && python3 -m pytest tests/test_onboarding.py -v
```

Expected: `test_quiz_saves_partner_to_db` and `test_quiz_prompt_includes_answers` may fail if the mock response lacks `alignment`.

- [ ] **Step 2: Update PARTNER_TRAITS and add alignment storage test**

In `tests/test_onboarding.py`, update `PARTNER_TRAITS` and add a new test:

```python
PARTNER_TRAITS = json.dumps({
    "name": "Vera",
    "sex": "female",
    "personality_archetype": "world-weary cynic",
    "speech_style": "terse and hard-boiled",
    "relationship_stance": "exasperated",
    "alignment": "Lawful Good",
    "system_prompt": "You are Vera, a world-weary detective's partner who finds everything mildly absurd."
})
```

Add new test:

```python
from noir.persistence.repository import get_player, update_player_alignment

def test_quiz_stores_player_alignment(db):
    create_player(db)
    llm = MockLLMBackend(responses=[PARTNER_TRAITS])
    quiz = Quiz(conn=db, llm=llm)
    # Q1-A: law+2 good-1, all others D: varying
    answers = ["A", "D", "D", "D", "D", "D", "D", "D"]
    quiz.run(answers=answers)
    player = get_player(db)
    # Scores should be non-zero (quiz scored and stored)
    assert player["law_chaos"] != 0 or player["good_evil"] != 0

def test_quiz_partner_alignment_stored(db):
    create_player(db)
    llm = MockLLMBackend(responses=[PARTNER_TRAITS])
    quiz = Quiz(conn=db, llm=llm)
    answers = ["A", "A", "A", "A", "A", "A", "A", "A"]
    quiz.run(answers=answers)
    partner = get_partner(db)
    assert partner["alignment"] == "Lawful Good"

def test_quiz_prompt_includes_player_alignment(db):
    create_player(db)
    llm = MockLLMBackend(responses=[PARTNER_TRAITS])
    quiz = Quiz(conn=db, llm=llm)
    answers = ["A", "A", "A", "A", "A", "A", "A", "A"]
    quiz.run(answers=answers)
    last_call = llm.calls[-1]
    assert "alignment" in last_call["user_input"].lower()
```

- [ ] **Step 3: Run all onboarding tests**

```bash
cd /Users/danajanezic/code/noir-leans && python3 -m pytest tests/test_onboarding.py -v
```

Expected: all PASS

- [ ] **Step 4: Run full test suite**

```bash
cd /Users/danajanezic/code/noir-leans && python3 -m pytest -v
```

Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
cd /Users/danajanezic/code/noir-leans && git add tests/test_onboarding.py
git commit -m "test: update onboarding tests for alignment quiz"
```

---

## Task 5: Add Alignment to Mystery Generator and Game

**Files:**
- Modify: `noir/mystery/generator.py`
- Modify: `noir/game.py:322`
- Test: `tests/test_mystery.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_mystery.py`:

```python
from noir.mystery.generator import REQUIRED_SUSPECT_FIELDS

def test_required_suspect_fields_includes_alignment():
    assert "alignment" in REQUIRED_SUSPECT_FIELDS
```

Also add `"alignment"` to the `VALID_CASE` suspect dictionaries in `test_mystery.py`. Find the existing `VALID_CASE` dict and add `"alignment": "Chaotic Evil"` and `"alignment": "Lawful Neutral"` to the two suspect entries respectively.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/danajanezic/code/noir-leans && python3 -m pytest tests/test_mystery.py::test_required_suspect_fields_includes_alignment -v
```

Expected: FAIL — AssertionError

- [ ] **Step 3: Update generator.py**

In `noir/mystery/generator.py`, update `REQUIRED_SUSPECT_FIELDS`:

```python
REQUIRED_SUSPECT_FIELDS = {"name", "role", "alibi", "secret", "personality", "speech_style", "race", "political_connections", "backstory", "routine", "alignment"}
```

In the `generate()` method's prompt string (around line 190), add `"alignment"` to the suspect schema. Find the suspects array schema and update it:

```python
'     "alignment": "string (one of: Lawful Good, Neutral Good, Chaotic Good, Lawful Neutral, True Neutral, Chaotic Neutral, Lawful Evil, Neutral Evil, Chaotic Evil — assign based on this character\'s role, morality, and relationship to authority)",\n'
```

Insert this line after `"speech_style"` in the prompt's suspect schema block.

- [ ] **Step 4: Update game.py to pass alignment to create_npc**

In `noir/game.py` around line 322, update the `create_npc` call:

```python
npc_id = create_npc(self.conn, case_id=case_id, name=suspect["name"],
                    role=suspect["role"], system_prompt=npc_system_prompt,
                    current_location_id=loc_id,
                    alignment=suspect.get("alignment", "True Neutral"))
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd /Users/danajanezic/code/noir-leans && python3 -m pytest tests/test_mystery.py -v
```

Expected: all PASS

- [ ] **Step 6: Run full test suite**

```bash
cd /Users/danajanezic/code/noir-leans && python3 -m pytest -v
```

Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
cd /Users/danajanezic/code/noir-leans && git add noir/mystery/generator.py noir/game.py tests/test_mystery.py
git commit -m "feat: add alignment to mystery generator suspects and NPC creation"
```

---

## Task 6: NPC Alignment Disposition Injection

**Files:**
- Modify: `noir/characters/npc.py`
- Test: `tests/test_agent.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_agent.py`:

```python
from noir.onboarding.quiz import alignment_disposition

def test_alignment_disposition_opposed():
    assert alignment_disposition("Lawful Good", "Chaotic Evil") == "opposed"
    assert alignment_disposition("Chaotic Evil", "Lawful Good") == "opposed"

def test_alignment_disposition_aligned():
    assert alignment_disposition("Lawful Good", "Neutral Good") == "aligned"
    assert alignment_disposition("Lawful Good", "Lawful Neutral") == "aligned"
    assert alignment_disposition("True Neutral", "True Neutral") == "aligned"

def test_alignment_disposition_neutral():
    assert alignment_disposition("Lawful Good", "Chaotic Neutral") == "neutral"
    assert alignment_disposition("Lawful Neutral", "Chaotic Neutral") == "neutral"

def test_npc_locked_prompt_includes_alignment_disposition(db, mock_llm):
    from itertools import cycle
    from noir.persistence.repository import (
        create_player, save_partner, update_player_alignment,
        create_case, create_location, create_npc
    )
    create_player(db)
    update_player_alignment(db, law_delta=6, good_delta=6)  # Lawful Good
    save_partner(db, name="Vera", sex="female", personality_archetype="cynic",
                 speech_style="terse", relationship_stance="exasperated",
                 system_prompt="You are Vera.", alignment="Neutral Good")
    case_id = create_case(db, archetype="test", title="T", case_data="{}")
    loc_id = create_location(db, name="Bar", description="A bar.", is_fixed=True)
    npc_id = create_npc(db, case_id=case_id, name="Rex", role="suspect",
                        system_prompt="You are Rex, a suspect.",
                        current_location_id=loc_id, alignment="Chaotic Evil")
    mock_llm._responses = cycle(["I know nothing."])
    npc = NPC.load(conn=db, llm=mock_llm, npc_id=npc_id, case_id=case_id)
    assert "opposed" in npc._locked_system_prompt.lower() or "conflict" in npc._locked_system_prompt.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/danajanezic/code/noir-leans && python3 -m pytest tests/test_agent.py::test_alignment_disposition_opposed tests/test_agent.py::test_npc_locked_prompt_includes_alignment_disposition -v
```

Expected: `test_alignment_disposition_opposed` PASS (already implemented), `test_npc_locked_prompt_includes_alignment_disposition` FAIL

- [ ] **Step 3: Update NPC to inject alignment disposition**

Replace `noir/characters/npc.py` with:

```python
import sqlite3
from noir.llm.base import LLMBackend
from noir.persistence.repository import get_npc, get_player, get_partner, update_npc_location, set_character_location
from noir.onboarding.quiz import alignment_disposition, resolve_alignment
from .agent import Agent


def _build_alignment_prefix(player_alignment: str, npc_alignment: str,
                              partner_alignment: str) -> str:
    disposition = alignment_disposition(player_alignment, npc_alignment)
    partner_disposition = alignment_disposition(partner_alignment, npc_alignment)

    if disposition == "aligned":
        disposition_note = "Your values broadly align. You are somewhat more open with them."
    elif disposition == "opposed":
        disposition_note = "Your values conflict fundamentally. You are guarded."
    else:
        return ""  # neutral — inject nothing

    prefix = f"[Player alignment: {player_alignment}. {disposition_note}"

    if partner_alignment != player_alignment and partner_disposition == "aligned":
        prefix += f" Their partner's alignment: {partner_alignment}. You find the partner more trustworthy. Their presence helps."

    prefix += "]"
    return prefix


class NPC(Agent):

    def __init__(self, *, npc_id: int, name: str, role: str,
                 current_location_id: int, alignment_prefix: str = "", **kwargs):
        super().__init__(**kwargs)
        self.npc_id = npc_id
        self.name = name
        self.role = role
        self.current_location_id = current_location_id
        self._alignment_prefix = alignment_prefix

    @property
    def _locked_system_prompt(self) -> str:
        base = super()._locked_system_prompt
        if self._alignment_prefix:
            return self._alignment_prefix + "\n\n" + base
        return base

    @classmethod
    def load(cls, *, conn: sqlite3.Connection, llm: LLMBackend,
             npc_id: int, case_id: int) -> "NPC":
        row = get_npc(conn, npc_id)
        if row is None:
            raise ValueError(f"NPC {npc_id} not found")

        alignment_prefix = ""
        player = get_player(conn)
        partner = get_partner(conn)
        if player and row["alignment"]:
            player_alignment = resolve_alignment(player["law_chaos"], player["good_evil"])
            partner_alignment = partner["alignment"] if partner and partner["alignment"] else "True Neutral"
            alignment_prefix = _build_alignment_prefix(
                player_alignment, row["alignment"], partner_alignment
            )

        return cls(
            character_id=f"npc_{npc_id}",
            system_prompt=row["system_prompt"],
            llm=llm,
            conn=conn,
            case_id=case_id,
            npc_id=npc_id,
            name=row["name"],
            role=row["role"],
            current_location_id=row["current_location_id"],
            alignment_prefix=alignment_prefix,
        )

    def move_to(self, location_id: int) -> None:
        self.current_location_id = location_id
        update_npc_location(self.conn, npc_id=self.npc_id, location_id=location_id)
        set_character_location(self.conn, character_id=self.character_id, location_id=location_id)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/danajanezic/code/noir-leans && python3 -m pytest tests/test_agent.py::test_alignment_disposition_opposed tests/test_agent.py::test_alignment_disposition_aligned tests/test_agent.py::test_alignment_disposition_neutral tests/test_agent.py::test_npc_locked_prompt_includes_alignment_disposition -v
```

Expected: all PASS

- [ ] **Step 5: Run full test suite**

```bash
cd /Users/danajanezic/code/noir-leans && python3 -m pytest -v
```

Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
cd /Users/danajanezic/code/noir-leans && git add noir/characters/npc.py tests/test_agent.py
git commit -m "feat: inject alignment disposition prefix into NPC system prompts"
```
