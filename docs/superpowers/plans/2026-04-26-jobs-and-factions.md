# Jobs and Faction System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a parallel job system where the player earns faction-specific reputation by taking work from 19 factions, with tier gates, NPC job offers, board browsing, job resolution, and cross-faction tension.

**Architecture:** Extend the `cases` table with `faction`, `tier`, `payout` nullable columns and `case_type='job'`. Add `faction_reputation` and `job_offers` tables. Fold `da_trust` into `faction_reputation`. New module `noir/jobs/` handles factions, archetypes, and generation. Game.py adds `/jobs` command, NPC offer detection, `/done` resolution, and tension events on location transitions.

**Tech Stack:** SQLite (schema migrations), Python, existing `llm.query_structured` pattern, Rich console output.

---

## File Map

**Create:**
- `noir/jobs/__init__.py` — empty package marker
- `noir/jobs/factions.py` — faction slugs, display names, opposition matrix, tier constants, org-to-faction mapping
- `noir/jobs/archetypes.json` — hand-authored job archetype templates
- `noir/jobs/generator.py` — `JobGenerator` class: fills archetype templates via LLM
- `tests/test_factions.py` — faction reputation behavioral tests
- `tests/test_jobs.py` — job lifecycle behavioral tests

**Modify:**
- `noir/persistence/db.py` — add 5 migration entries, call `seed_faction_reputation` and `_migrate_da_trust` in `create_schema`
- `noir/persistence/repository.py` — add faction rep functions, job CRUD functions, redirect `update_da_trust` / `get_da_trust`
- `noir/organizations.py` — add Shorties, Tallboys, Chamber of Commerce, NAACP, The Press to `SEEDED_ORGANIZATIONS`
- `noir/cases/trial.py` — replace `player["da_trust"]` reads with `get_faction_rep(conn, "da_office")`
- `noir/display.py` — replace `player.get("da_trust", 100)` with `get_faction_rep(conn, "da_office")`, add faction rep to status
- `noir/game.py` — add `/jobs` command, `_check_npc_job_offer`, `_activate_npc_job_offer`, `_replenish_job_board`, `_check_faction_tension`, `/done` command, wire into `_dispatch_slash` and location transitions

---

## Task 1: Schema migrations

**Files:**
- Modify: `noir/persistence/db.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_factions.py
import pytest
from noir.persistence.db import create_schema
from noir.persistence.repository import get_faction_rep, get_all_faction_reps
import sqlite3


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    yield conn
    conn.close()


def test_all_factions_seeded_at_zero(db):
    reps = get_all_faction_reps(db)
    assert len(reps) == 19
    assert all(v == 0 for v in reps.values())


def test_faction_slugs_present(db):
    reps = get_all_faction_reps(db)
    for slug in [
        "da_office", "nopd", "parish_govt", "state_govt", "judiciary",
        "shorties", "tallboys", "chamber", "naacp",
        "rossi", "castellano", "ila_231", "colored_longshoremen",
        "archdiocese", "athletic_club", "knights_columbus", "treme_club",
        "bar_association", "press",
    ]:
        assert slug in reps, f"Missing faction: {slug}"


def test_private_not_seeded(db):
    reps = get_all_faction_reps(db)
    assert "private" not in reps


def test_job_offers_table_exists(db):
    db.execute("INSERT INTO npcs (name, role, system_prompt) VALUES ('Test', 'test', 'test')")
    npc_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute("INSERT INTO job_offers (npc_id) VALUES (?)", (npc_id,))
    db.commit()
    row = db.execute("SELECT * FROM job_offers").fetchone()
    assert row["accepted"] == 0


def test_cases_has_faction_tier_payout_columns(db):
    db.execute(
        "INSERT INTO cases (archetype, title, case_data, case_type, faction, tier, payout) "
        "VALUES ('job', 'Test Job', '{}', 'job', 'rossi', 1, 50)"
    )
    db.commit()
    row = db.execute("SELECT faction, tier, payout FROM cases WHERE case_type='job'").fetchone()
    assert row["faction"] == "rossi"
    assert row["tier"] == 1
    assert row["payout"] == 50
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/danajanezic/code/noir-leans
venv/bin/pytest tests/test_factions.py -v 2>&1 | head -40
```

Expected: FAIL — `get_faction_rep` not defined, tables don't exist.

- [ ] **Step 3: Add migrations to `noir/persistence/db.py`**

In `_MIGRATIONS` list, append these five entries at the end (before the closing bracket):

```python
    "ALTER TABLE cases ADD COLUMN faction TEXT",
    "ALTER TABLE cases ADD COLUMN tier INTEGER",
    "ALTER TABLE cases ADD COLUMN payout INTEGER",
    """CREATE TABLE IF NOT EXISTS faction_reputation (
        faction TEXT PRIMARY KEY,
        reputation INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS job_offers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        npc_id INTEGER NOT NULL,
        case_id INTEGER,
        offered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        accepted INTEGER DEFAULT 0,
        FOREIGN KEY (npc_id) REFERENCES npcs(id),
        FOREIGN KEY (case_id) REFERENCES cases(id)
    )""",
```

- [ ] **Step 4: Add `seed_faction_reputation` and `_migrate_da_trust` calls to `create_schema`**

At the bottom of `create_schema` in `noir/persistence/db.py`, after the existing `seed_organizations(conn)` call:

```python
    from noir.jobs.factions import seed_faction_reputation
    seed_faction_reputation(conn)
    _migrate_da_trust(conn)
```

Add `_migrate_da_trust` function to `noir/persistence/db.py` (above `create_schema`):

```python
def _migrate_da_trust(conn: sqlite3.Connection) -> None:
    """One-time copy of legacy player.da_trust into faction_reputation for da_office."""
    player = conn.execute("SELECT da_trust FROM player WHERE id=1").fetchone()
    if player is None:
        return
    da_trust = player["da_trust"] if player["da_trust"] is not None else 100
    existing = conn.execute(
        "SELECT reputation FROM faction_reputation WHERE faction='da_office'"
    ).fetchone()
    if existing is not None and existing["reputation"] == 0 and da_trust > 0:
        conn.execute(
            "UPDATE faction_reputation SET reputation=? WHERE faction='da_office'",
            (da_trust,)
        )
        conn.commit()
```

- [ ] **Step 5: Run tests to verify schema tests pass** (faction rep functions don't exist yet — those tests will still fail; the schema tests should pass)

```bash
venv/bin/pytest tests/test_factions.py::test_job_offers_table_exists tests/test_factions.py::test_cases_has_faction_tier_payout_columns -v
```

Expected: PASS for those two; others still fail (no `get_faction_rep` yet).

- [ ] **Step 6: Commit**

```bash
git add noir/persistence/db.py tests/test_factions.py
git commit -m "feat: schema migrations — faction_reputation, job_offers, cases job columns"
```

---

## Task 2: Faction constants module

**Files:**
- Create: `noir/jobs/__init__.py`
- Create: `noir/jobs/factions.py`

- [ ] **Step 1: Create `noir/jobs/__init__.py`**

```python
```
(Empty file.)

- [ ] **Step 2: Create `noir/jobs/factions.py`**

```python
import sqlite3

FACTIONS: dict[str, dict] = {
    "da_office":            {"name": "DA's Office",                          "type": "government"},
    "nopd":                 {"name": "New Orleans Police Department",        "type": "government"},
    "parish_govt":          {"name": "Orleans Parish Government",            "type": "government"},
    "state_govt":           {"name": "Louisiana State Government",           "type": "government"},
    "judiciary":            {"name": "Orleans Parish Judiciary",             "type": "government"},
    "shorties":             {"name": "Shorties",                             "type": "political"},
    "tallboys":             {"name": "Tallboys",                             "type": "political"},
    "chamber":              {"name": "Chamber of Commerce",                  "type": "political"},
    "naacp":                {"name": "NAACP",                                "type": "civic"},
    "rossi":                {"name": "Rossi Crime Family",                   "type": "crime_family"},
    "castellano":           {"name": "Castellano Crime Family",              "type": "crime_family"},
    "ila_231":              {"name": "ILA Local 231",                        "type": "union"},
    "colored_longshoremen": {"name": "Colored Longshoremen's Association",   "type": "union"},
    "archdiocese":          {"name": "Archdiocese of New Orleans",           "type": "church"},
    "athletic_club":        {"name": "New Orleans Athletic Club",            "type": "fraternal"},
    "knights_columbus":     {"name": "Knights of Columbus",                  "type": "fraternal"},
    "treme_club":           {"name": "Treme Social Aid and Pleasure Club",   "type": "fraternal"},
    "bar_association":      {"name": "Noirleans Bar Association",            "type": "professional"},
    "press":                {"name": "The Press",                            "type": "press"},
}

ALL_FACTION_SLUGS = list(FACTIONS.keys())

OPPOSITION: dict[str, dict[str, list[str]]] = {
    "rossi":                {"direct": ["castellano"],                                          "secondary": ["nopd", "da_office"]},
    "castellano":           {"direct": ["rossi"],                                               "secondary": ["nopd", "da_office"]},
    "shorties":             {"direct": ["tallboys"],                                            "secondary": []},
    "tallboys":             {"direct": ["shorties", "naacp", "treme_club", "colored_longshoremen"], "secondary": []},
    "chamber":              {"direct": ["ila_231", "colored_longshoremen"],                    "secondary": ["naacp", "treme_club"]},
    "nopd":                 {"direct": ["rossi", "castellano"],                                "secondary": ["naacp", "treme_club"]},
    "da_office":            {"direct": ["rossi", "castellano"],                                "secondary": []},
    "naacp":                {"direct": ["tallboys", "chamber"],                                "secondary": ["nopd"]},
    "ila_231":              {"direct": ["chamber"],                                            "secondary": []},
    "colored_longshoremen": {"direct": ["chamber"],                                            "secondary": []},
    "treme_club":           {"direct": ["nopd", "chamber"],                                    "secondary": ["tallboys"]},
}

TIER_REP_THRESHOLDS = {1: 0, 2: 25, 3: 60}
TIER_REP_GAINS      = {1: 8,  2: 20, 3: 40}
TIER_REP_LOSSES     = {1: 10, 2: 20, 3: 40}
OPPOSITION_PENALTY_DIRECT    = 8
OPPOSITION_PENALTY_SECONDARY = 4
TENSION_THRESHOLD   = 40
TENSION_ESCALATION  = 60

ORG_NAME_TO_FACTION: dict[str, str] = {
    "Orleans Parish Government":                    "parish_govt",
    "Louisiana State Government":                   "state_govt",
    "New Orleans Police Department":                "nopd",
    "Orleans Parish Judiciary":                     "judiciary",
    "Rossi Crime Family":                           "rossi",
    "Castellano Crime Family":                      "castellano",
    "International Longshoremen's Association Local 231": "ila_231",
    "Colored Longshoremen's Association":           "colored_longshoremen",
    "Archdiocese of New Orleans":                   "archdiocese",
    "New Orleans Athletic Club":                    "athletic_club",
    "Knights of Columbus":                          "knights_columbus",
    "Treme Social Aid and Pleasure Club":           "treme_club",
    "Noirleans Bar Association":                    "bar_association",
    "Shorties":                                     "shorties",
    "Tallboys":                                     "tallboys",
    "Chamber of Commerce":                          "chamber",
    "NAACP New Orleans Chapter":                    "naacp",
    "The Press":                                    "press",
}


def faction_slug_for_npc(conn: sqlite3.Connection, npc_id: int) -> str | None:
    """Return the highest-influence faction slug for an NPC, or None."""
    rows = conn.execute(
        """SELECT o.name FROM organizations o
           JOIN organization_members om ON om.organization_id = o.id
           WHERE om.member_type='npc' AND om.member_id=?
           ORDER BY o.influence DESC""",
        (npc_id,)
    ).fetchall()
    for row in rows:
        slug = ORG_NAME_TO_FACTION.get(row["name"])
        if slug:
            return slug
    return None


def seed_faction_reputation(conn: sqlite3.Connection) -> None:
    for slug in ALL_FACTION_SLUGS:
        conn.execute(
            "INSERT OR IGNORE INTO faction_reputation (faction, reputation) VALUES (?, 0)",
            (slug,)
        )
    conn.commit()


def get_opposition_penalties(faction: str) -> list[tuple[str, int]]:
    """Return list of (faction_slug, penalty_amount) for completing a job for `faction`."""
    opp = OPPOSITION.get(faction, {})
    penalties = []
    for opp_faction in opp.get("direct", []):
        penalties.append((opp_faction, OPPOSITION_PENALTY_DIRECT))
    for opp_faction in opp.get("secondary", []):
        penalties.append((opp_faction, OPPOSITION_PENALTY_SECONDARY))
    return penalties
```

- [ ] **Step 3: Run the faction slug/seeding tests**

```bash
venv/bin/pytest tests/test_factions.py::test_all_factions_seeded_at_zero tests/test_factions.py::test_faction_slugs_present tests/test_factions.py::test_private_not_seeded -v
```

Expected: PASS for all three.

- [ ] **Step 4: Commit**

```bash
git add noir/jobs/__init__.py noir/jobs/factions.py
git commit -m "feat: faction constants module — slugs, opposition matrix, org mapping, seeding"
```

---

## Task 3: Repository — faction reputation functions

**Files:**
- Modify: `noir/persistence/repository.py`

- [ ] **Step 1: Write the failing tests** (add to `tests/test_factions.py`)

```python
from noir.persistence.repository import (
    get_faction_rep, update_faction_rep, get_all_faction_reps,
    create_player,
)


def test_get_faction_rep_returns_zero_initially(db):
    assert get_faction_rep(db, "rossi") == 0


def test_update_faction_rep_increases_rep(db):
    update_faction_rep(db, "rossi", 10)
    assert get_faction_rep(db, "rossi") == 10


def test_update_faction_rep_caps_at_100(db):
    update_faction_rep(db, "rossi", 200)
    assert get_faction_rep(db, "rossi") == 100


def test_update_faction_rep_floors_at_zero(db):
    update_faction_rep(db, "rossi", -50)
    assert get_faction_rep(db, "rossi") == 0


def test_update_faction_rep_returns_new_value(db):
    result = update_faction_rep(db, "rossi", 15)
    assert result == 15


def test_get_all_faction_reps_returns_dict(db):
    update_faction_rep(db, "rossi", 5)
    reps = get_all_faction_reps(db)
    assert isinstance(reps, dict)
    assert reps["rossi"] == 5
    assert reps["castellano"] == 0
```

- [ ] **Step 2: Run to verify they fail**

```bash
venv/bin/pytest tests/test_factions.py -k "rep" -v 2>&1 | head -30
```

Expected: FAIL — `get_faction_rep` not defined.

- [ ] **Step 3: Add functions to `noir/persistence/repository.py`** (after `update_da_trust`, around line 43)

```python
def get_faction_rep(conn: sqlite3.Connection, faction: str) -> int:
    row = conn.execute(
        "SELECT reputation FROM faction_reputation WHERE faction=?", (faction,)
    ).fetchone()
    return row["reputation"] if row else 0


def update_faction_rep(conn: sqlite3.Connection, faction: str, delta: int) -> int:
    conn.execute(
        "UPDATE faction_reputation SET reputation = MAX(0, MIN(100, reputation + ?)) WHERE faction=?",
        (delta, faction)
    )
    conn.commit()
    return get_faction_rep(conn, faction)


def get_all_faction_reps(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT faction, reputation FROM faction_reputation ORDER BY faction"
    ).fetchall()
    return {r["faction"]: r["reputation"] for r in rows}
```

- [ ] **Step 4: Run tests**

```bash
venv/bin/pytest tests/test_factions.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add noir/persistence/repository.py tests/test_factions.py
git commit -m "feat: faction reputation repository functions — get, update, get_all"
```

---

## Task 4: Redirect `da_trust` → faction rep; update callers

**Files:**
- Modify: `noir/persistence/repository.py`
- Modify: `noir/cases/trial.py`
- Modify: `noir/display.py`

- [ ] **Step 1: Write the failing test** (add to `tests/test_factions.py`)

```python
from noir.persistence.repository import update_da_trust


def test_da_trust_migration_copies_to_faction_rep(db):
    create_player(db)
    db.execute("UPDATE player SET da_trust=75 WHERE id=1")
    db.commit()
    # Re-run migration manually
    from noir.persistence.db import _migrate_da_trust
    # Reset da_office to 0 first (seeding already ran in fixture)
    db.execute("UPDATE faction_reputation SET reputation=0 WHERE faction='da_office'")
    db.commit()
    _migrate_da_trust(db)
    assert get_faction_rep(db, "da_office") == 75


def test_update_da_trust_writes_to_faction_rep(db):
    update_da_trust(db, delta=20)
    assert get_faction_rep(db, "da_office") == 20


def test_update_da_trust_negative_delta(db):
    update_faction_rep(db, "da_office", 50)
    update_da_trust(db, delta=-10)
    assert get_faction_rep(db, "da_office") == 40
```

- [ ] **Step 2: Run to verify they fail**

```bash
venv/bin/pytest tests/test_factions.py -k "da_trust" -v 2>&1 | head -20
```

Expected: FAIL — `update_da_trust` still writes to `player.da_trust`.

- [ ] **Step 3: Replace `update_da_trust` in `noir/persistence/repository.py`**

Replace the existing `update_da_trust` function (lines 37–42):

```python
def update_da_trust(conn: sqlite3.Connection, *, delta: int) -> None:
    update_faction_rep(conn, "da_office", delta)
```

- [ ] **Step 4: Update `noir/cases/trial.py` — replace two `player["da_trust"]` reads**

In `trial.py`, find the import line (line 8):
```python
from noir.persistence.repository import (
    get_evidence_for_case, get_all_dossier, update_da_trust,
```
Add `get_faction_rep` to that import.

Find line 192 (inside `_build_context` or similar):
```python
        da_trust = player["da_trust"] if player and "da_trust" in player.keys() else 100
```
Replace with:
```python
        da_trust = get_faction_rep(self.conn, "da_office")
```

Find line 472 (second occurrence):
```python
        da_trust = player["da_trust"] if player and "da_trust" in player.keys() else 100
```
Replace with:
```python
        da_trust = get_faction_rep(self.conn, "da_office")
```

- [ ] **Step 5: Update `noir/display.py` — replace `player.get("da_trust", 100)` (line 755)**

First, update the function signature of the display function that uses `da_trust` to accept `conn` if it doesn't already. Check how it's called:

```bash
grep -n "def.*status\|def.*player_status\|da_trust" noir/display.py | head -10
```

Then replace:
```python
                 f"[cyan]DA trust:[/cyan] {player.get('da_trust', 100)}")
```
with:
```python
                 f"[cyan]DA trust:[/cyan] {da_trust}")
```

And in the function that calls this line, add `da_trust = get_faction_rep(conn, "da_office")` before the line, passing `conn` from the caller. (Check how `display.py` receives its data — if it doesn't have `conn`, pass `da_trust` as a parameter from `game.py`.)

- [ ] **Step 6: Run the da_trust tests plus the full test suite**

```bash
venv/bin/pytest tests/test_factions.py -v
venv/bin/pytest tests/ -x -q 2>&1 | tail -20
```

Expected: All test_factions tests PASS. Full suite PASS (no regressions).

- [ ] **Step 7: Commit**

```bash
git add noir/persistence/repository.py noir/cases/trial.py noir/display.py tests/test_factions.py
git commit -m "feat: redirect da_trust to faction_reputation — update_da_trust, trial.py, display.py"
```

---

## Task 5: Add missing organizations + repository job CRUD

**Files:**
- Modify: `noir/organizations.py`
- Modify: `noir/persistence/repository.py`
- Create: `tests/test_jobs.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_jobs.py
import json
import pytest
import sqlite3
from noir.persistence.db import create_schema
from noir.persistence.repository import (
    create_player,
    get_faction_rep, update_faction_rep,
    create_job, get_active_jobs, get_available_jobs,
    create_job_offer, accept_job_offer, decline_job_offer, get_pending_job_offers,
    complete_job, fail_job,
    get_player_cash, update_player_cash,
)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    create_player(conn)
    yield conn
    conn.close()


@pytest.fixture
def npc_id(db):
    db.execute("INSERT INTO npcs (name, role, system_prompt) VALUES ('Test NPC', 'test', 'test')")
    db.commit()
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def test_create_job_stores_faction_tier_payout(db):
    job_id = create_job(db, faction="rossi", tier=1, title="Rough Errand",
                        payout=50, case_data={"objective": "Find Vitale"})
    row = db.execute("SELECT * FROM cases WHERE id=?", (job_id,)).fetchone()
    assert row["case_type"] == "job"
    assert row["faction"] == "rossi"
    assert row["tier"] == 1
    assert row["payout"] == 50
    assert row["status"] == "pending"


def test_get_available_jobs_filters_by_faction_rep(db):
    create_job(db, faction="rossi", tier=1, title="Tier1 Job", payout=50, case_data={})
    create_job(db, faction="naacp", tier=2, title="Tier2 Job", payout=150, case_data={})
    jobs = get_available_jobs(db)
    titles = [j["title"] for j in jobs]
    assert "Tier1 Job" in titles
    assert "Tier2 Job" not in titles  # rep=0 < threshold=25


def test_get_available_jobs_includes_tier2_when_rep_sufficient(db):
    update_faction_rep(db, "naacp", 30)
    create_job(db, faction="naacp", tier=2, title="Tier2 Unlocked", payout=150, case_data={})
    jobs = get_available_jobs(db)
    titles = [j["title"] for j in jobs]
    assert "Tier2 Unlocked" in titles


def test_get_active_jobs_returns_accepted_jobs(db):
    job_id = create_job(db, faction="rossi", tier=1, title="Active Job", payout=50, case_data={})
    db.execute("UPDATE cases SET status='active' WHERE id=?", (job_id,))
    db.commit()
    jobs = get_active_jobs(db)
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Active Job"


def test_complete_job_pays_out_and_increases_rep(db):
    job_id = create_job(db, faction="rossi", tier=1, title="Done Job", payout=60, case_data={})
    db.execute("UPDATE cases SET status='active' WHERE id=?", (job_id,))
    db.commit()
    complete_job(db, case_id=job_id, payout=60, faction="rossi", tier=1)
    assert get_player_cash(db) == 560  # 500 starting + 60
    assert get_faction_rep(db, "rossi") == 8  # tier 1 gain


def test_complete_rossi_job_hurts_castellano(db):
    job_id = create_job(db, faction="rossi", tier=1, title="Rossi Job", payout=50, case_data={})
    db.execute("UPDATE cases SET status='active' WHERE id=?", (job_id,))
    db.commit()
    complete_job(db, case_id=job_id, payout=50, faction="rossi", tier=1)
    assert get_faction_rep(db, "castellano") == 0  # was 0, -8 floors at 0
    # Give castellano some rep first
    update_faction_rep(db, "castellano", 20)
    job_id2 = create_job(db, faction="rossi", tier=1, title="Rossi Job 2", payout=50, case_data={})
    db.execute("UPDATE cases SET status='active' WHERE id=?", (job_id2,))
    db.commit()
    complete_job(db, case_id=job_id2, payout=50, faction="rossi", tier=1)
    assert get_faction_rep(db, "castellano") == 12  # 20 - 8


def test_complete_shorties_job_does_not_hurt_naacp(db):
    update_faction_rep(db, "naacp", 30)
    job_id = create_job(db, faction="shorties", tier=1, title="Shorties Job", payout=50, case_data={})
    db.execute("UPDATE cases SET status='active' WHERE id=?", (job_id,))
    db.commit()
    complete_job(db, case_id=job_id, payout=50, faction="shorties", tier=1)
    assert get_faction_rep(db, "naacp") == 30  # unchanged


def test_complete_tallboys_job_hurts_naacp(db):
    update_faction_rep(db, "naacp", 30)
    job_id = create_job(db, faction="tallboys", tier=1, title="Tallboys Job", payout=50, case_data={})
    db.execute("UPDATE cases SET status='active' WHERE id=?", (job_id,))
    db.commit()
    complete_job(db, case_id=job_id, payout=50, faction="tallboys", tier=1)
    assert get_faction_rep(db, "naacp") == 22  # 30 - 8


def test_complete_tallboys_job_hurts_treme_and_colored_longshoremen(db):
    update_faction_rep(db, "treme_club", 20)
    update_faction_rep(db, "colored_longshoremen", 20)
    job_id = create_job(db, faction="tallboys", tier=1, title="Tallboys Job", payout=50, case_data={})
    db.execute("UPDATE cases SET status='active' WHERE id=?", (job_id,))
    db.commit()
    complete_job(db, case_id=job_id, payout=50, faction="tallboys", tier=1)
    assert get_faction_rep(db, "treme_club") == 12         # 20 - 8
    assert get_faction_rep(db, "colored_longshoremen") == 12  # 20 - 8


def test_fail_job_applies_rep_penalty_no_payout(db):
    job_id = create_job(db, faction="rossi", tier=1, title="Failed Job", payout=60, case_data={})
    db.execute("UPDATE cases SET status='active' WHERE id=?", (job_id,))
    db.commit()
    update_faction_rep(db, "rossi", 20)
    fail_job(db, case_id=job_id, faction="rossi", tier=1)
    assert get_player_cash(db) == 500  # no payout
    assert get_faction_rep(db, "rossi") == 10  # 20 - 10
    row = db.execute("SELECT status FROM cases WHERE id=?", (job_id,)).fetchone()
    assert row["status"] == "failed"


def test_job_offer_created_and_declined(db, npc_id):
    offer_id = create_job_offer(db, npc_id=npc_id)
    offers = get_pending_job_offers(db)
    assert len(offers) == 1
    decline_job_offer(db, offer_id=offer_id)
    offers = get_pending_job_offers(db)
    assert len(offers) == 0


def test_job_offer_accepted_links_case(db, npc_id):
    offer_id = create_job_offer(db, npc_id=npc_id)
    job_id = create_job(db, faction="rossi", tier=1, title="Offered Job", payout=50, case_data={})
    db.execute("UPDATE cases SET status='active' WHERE id=?", (job_id,))
    db.commit()
    accept_job_offer(db, offer_id=offer_id, case_id=job_id)
    row = db.execute("SELECT * FROM job_offers WHERE id=?", (offer_id,)).fetchone()
    assert row["accepted"] == 1
    assert row["case_id"] == job_id
```

- [ ] **Step 2: Run to verify they fail**

```bash
venv/bin/pytest tests/test_jobs.py -v 2>&1 | head -30
```

Expected: FAIL — functions not defined.

- [ ] **Step 3: Add missing organizations to `noir/organizations.py`**

In `SEEDED_ORGANIZATIONS` list, append before the closing `]`:

```python
    {
        "name": "Shorties",
        "type": "political",
        "description": (
            "Supporters of the Short machine — the populist political network built by Governor Short "
            "and maintained by his successors. Provides patronage jobs, infrastructure contracts, and "
            "political protection to its members. Deliberately race-neutral in its public programs, "
            "which is both its strength and the source of its enemies. Membership spans class and "
            "neighborhood lines in a way unusual for New Orleans politics."
        ),
        "is_hierarchical": 1,
        "influence": 8,
    },
    {
        "name": "Tallboys",
        "type": "political",
        "description": (
            "The anti-Short coalition — a loose alliance of old-guard political families, business "
            "interests, and reactionary elements who feel the Short machine stole what was rightfully "
            "theirs. The coalition includes former KKK members who lost power during the Short years "
            "and have not forgotten it. Unified by resentment more than ideology. Predominantly white, "
            "Catholic, and drawn from families with pre-Short political ties."
        ),
        "is_hierarchical": 0,
        "influence": 6,
    },
    {
        "name": "Chamber of Commerce",
        "type": "political",
        "description": (
            "The organized voice of New Orleans business interests. Aggressively anti-union, "
            "hostile to labor organizing, and focused on keeping wages low and regulations light. "
            "Corrupt in the way of influence peddling and favorable contracts rather than street-level "
            "graft. Members are merchants, manufacturers, and property owners. Membership is exclusively "
            "white."
        ),
        "is_hierarchical": 1,
        "influence": 7,
    },
    {
        "name": "NAACP New Orleans Chapter",
        "type": "civic",
        "description": (
            "The New Orleans chapter of the National Association for the Advancement of Colored People. "
            "Focused on legal challenges to segregation, voter suppression, and police brutality. "
            "Operates with limited resources under constant pressure. Membership is Black and includes "
            "professionals, clergy, and community leaders. Works through legal channels where possible; "
            "maintains community networks where it cannot."
        ),
        "is_hierarchical": 1,
        "influence": 5,
    },
    {
        "name": "The Press",
        "type": "press",
        "description": (
            "The loose network of journalists, editors, and publishers working in Noirleans — "
            "primarily the white dailies but including the Black press. The press has the power to "
            "expose and to bury, and everyone in the city knows it. Journalists are poorly paid, "
            "often corrupt, and occasionally brave. Membership is informal — anyone with press "
            "credentials and a story."
        ),
        "is_hierarchical": 0,
        "influence": 5,
    },
```

- [ ] **Step 4: Add job CRUD functions to `noir/persistence/repository.py`**

Add after `get_all_faction_reps` (or at end of faction section):

```python
def create_job(conn: sqlite3.Connection, *, faction: str, tier: int,
               title: str, payout: int, case_data: dict) -> int:
    cur = conn.execute(
        """INSERT INTO cases (archetype, title, case_data, status, case_type, faction, tier, payout)
           VALUES ('job', ?, ?, 'pending', 'job', ?, ?, ?)""",
        (title, json.dumps(case_data), faction, tier, payout)
    )
    conn.commit()
    return cur.lastrowid


def get_active_jobs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM cases WHERE case_type='job' AND status='active' ORDER BY created_at"
    ).fetchall()


def get_available_jobs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    from noir.jobs.factions import TIER_REP_THRESHOLDS
    rows = conn.execute(
        """SELECT c.*, COALESCE(fr.reputation, 0) as faction_rep
           FROM cases c
           LEFT JOIN faction_reputation fr ON c.faction = fr.faction
           WHERE c.case_type='job' AND c.status='pending'
           ORDER BY c.tier, c.created_at"""
    ).fetchall()
    return [r for r in rows if (r["faction_rep"] or 0) >= TIER_REP_THRESHOLDS.get(r["tier"] or 1, 0)]


def create_job_offer(conn: sqlite3.Connection, *, npc_id: int) -> int:
    cur = conn.execute("INSERT INTO job_offers (npc_id) VALUES (?)", (npc_id,))
    conn.commit()
    return cur.lastrowid


def accept_job_offer(conn: sqlite3.Connection, *, offer_id: int, case_id: int) -> None:
    conn.execute(
        "UPDATE job_offers SET accepted=1, case_id=? WHERE id=?",
        (case_id, offer_id)
    )
    conn.commit()


def decline_job_offer(conn: sqlite3.Connection, *, offer_id: int) -> None:
    conn.execute("UPDATE job_offers SET accepted=-1 WHERE id=?", (offer_id,))
    conn.commit()


def get_pending_job_offers(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT jo.*, n.name as npc_name FROM job_offers jo
           JOIN npcs n ON jo.npc_id = n.id
           WHERE jo.accepted=0 ORDER BY jo.offered_at DESC"""
    ).fetchall()


def complete_job(conn: sqlite3.Connection, *, case_id: int,
                 payout: int, faction: str, tier: int) -> None:
    from noir.jobs.factions import TIER_REP_GAINS, get_opposition_penalties
    conn.execute("UPDATE cases SET status='completed' WHERE id=?", (case_id,))
    conn.commit()
    update_player_cash(conn, delta=payout)
    update_faction_rep(conn, faction, TIER_REP_GAINS[tier])
    for opp_faction, penalty in get_opposition_penalties(faction):
        update_faction_rep(conn, opp_faction, -penalty)


def fail_job(conn: sqlite3.Connection, *, case_id: int, faction: str, tier: int) -> None:
    from noir.jobs.factions import TIER_REP_LOSSES
    conn.execute("UPDATE cases SET status='failed' WHERE id=?", (case_id,))
    conn.commit()
    update_faction_rep(conn, faction, -TIER_REP_LOSSES[tier])
```

Also add `json` import at the top of `repository.py` if not present (it is — check line 1).

- [ ] **Step 5: Run tests**

```bash
venv/bin/pytest tests/test_jobs.py -v
venv/bin/pytest tests/ -x -q 2>&1 | tail -10
```

Expected: All test_jobs tests PASS. Full suite PASS.

- [ ] **Step 6: Commit**

```bash
git add noir/organizations.py noir/persistence/repository.py tests/test_jobs.py
git commit -m "feat: job CRUD repository functions + opposition penalties; add 5 missing organizations"
```

---

## Task 6: Job archetypes data + generator module

**Files:**
- Create: `noir/jobs/archetypes.json`
- Create: `noir/jobs/generator.py`

- [ ] **Step 1: Create `noir/jobs/archetypes.json`**

```json
[
  {
    "slug": "skip_trace",
    "tier": 1,
    "factions": ["any"],
    "title": "Skip Trace",
    "description": "Find a person who has gone missing or is avoiding someone. Report their location.",
    "payout_range": [25, 60],
    "moral_weight": "low",
    "step_templates": [
      "Ask around about {target} — last seen near {location_1}",
      "Confirm {target}'s current whereabouts",
      "Report back to {client}"
    ]
  },
  {
    "slug": "message_delivery",
    "tier": 1,
    "factions": ["rossi", "castellano", "shorties", "tallboys", "parish_govt"],
    "title": "Message Delivery",
    "description": "Carry something to someone without being seen or stopped.",
    "payout_range": [30, 65],
    "moral_weight": "low",
    "step_templates": [
      "Pick up the package from {client}",
      "Deliver it to {target} at {location_1} without attracting attention",
      "Confirm delivery"
    ]
  },
  {
    "slug": "surveillance",
    "tier": 1,
    "factions": ["any"],
    "title": "Surveillance",
    "description": "Watch a location or person and report what you observe.",
    "payout_range": [35, 75],
    "moral_weight": "low",
    "step_templates": [
      "Get into position near {location_1} without being noticed",
      "Observe {target} for one period",
      "Report findings to {client}"
    ]
  },
  {
    "slug": "serve_papers",
    "tier": 1,
    "factions": ["da_office", "bar_association", "judiciary"],
    "title": "Serve Papers",
    "description": "Deliver legal notice to someone who doesn't want to receive it.",
    "payout_range": [25, 50],
    "moral_weight": "low",
    "step_templates": [
      "Locate {target}",
      "Serve the papers — they will resist",
      "Confirm service to {client}"
    ]
  },
  {
    "slug": "cheating_spouse",
    "tier": 1,
    "factions": ["private"],
    "title": "Domestic Inquiry",
    "description": "Confirm or deny a client's suspicion about their partner.",
    "payout_range": [40, 75],
    "moral_weight": "medium",
    "step_templates": [
      "Establish {target}'s routine",
      "Observe {target} at {location_1}",
      "Report the truth to {client} — whatever it is"
    ]
  },
  {
    "slug": "debt_collection",
    "tier": 1,
    "factions": ["rossi", "castellano"],
    "title": "Debt Collection",
    "description": "Recover money owed using persuasion or pressure.",
    "payout_range": [35, 70],
    "moral_weight": "medium",
    "step_templates": [
      "Find {target} at {location_1}",
      "Collect the debt — by whatever means necessary",
      "Return the money to {client}"
    ]
  },
  {
    "slug": "evidence_retrieval",
    "tier": 2,
    "factions": ["da_office", "rossi", "castellano", "bar_association"],
    "title": "Evidence Retrieval",
    "description": "Get something incriminating before someone else does.",
    "payout_range": [100, 200],
    "moral_weight": "medium",
    "step_templates": [
      "Locate where {target} is being kept at {location_1}",
      "Retrieve it before it disappears",
      "Decide who it goes to — {client} or someone else",
      "Deliver and collect"
    ]
  },
  {
    "slug": "stolen_property",
    "tier": 2,
    "factions": ["private", "rossi", "castellano"],
    "title": "Stolen Property",
    "description": "Recover an object. Who gets it back is your call.",
    "payout_range": [100, 200],
    "moral_weight": "medium",
    "step_templates": [
      "Find out who took {target}",
      "Track it to {location_1}",
      "Recover it",
      "Return it — to {client} or to whoever deserves it"
    ]
  },
  {
    "slug": "witness_protection",
    "tier": 2,
    "factions": ["da_office", "naacp", "press"],
    "title": "Witness Protection",
    "description": "Keep an NPC alive and talking long enough to matter.",
    "payout_range": [120, 250],
    "moral_weight": "high",
    "step_templates": [
      "Find {target} at {location_1} before someone else does",
      "Keep {target} safe through the conversation",
      "Get {target} to {client} in one piece"
    ]
  },
  {
    "slug": "dig_up_dirt",
    "tier": 2,
    "factions": ["shorties", "tallboys", "chamber", "press", "naacp"],
    "title": "Dig Up Dirt",
    "description": "Find compromising information on a target. Decide what to do with it.",
    "payout_range": [120, 240],
    "moral_weight": "medium",
    "step_templates": [
      "Find where {target}'s secrets are kept",
      "Get the information at {location_1}",
      "Decide: hand it to {client}, sell it higher, or bury it"
    ]
  },
  {
    "slug": "union_job",
    "tier": 2,
    "factions": ["ila_231", "colored_longshoremen"],
    "title": "Union Work",
    "description": "Protect a worker, expose a scab, or document a violation.",
    "payout_range": [100, 180],
    "moral_weight": "medium",
    "step_templates": [
      "Find {target} at {location_1}",
      "Complete the union's objective",
      "Report back to {client}"
    ]
  },
  {
    "slug": "shadow_operation",
    "tier": 2,
    "factions": ["nopd", "shorties", "tallboys", "parish_govt"],
    "title": "Shadow Operation",
    "description": "Tail a target across multiple locations over one game day.",
    "payout_range": [130, 250],
    "moral_weight": "low",
    "step_templates": [
      "Pick up {target}'s trail at {location_1}",
      "Follow without being made",
      "Track to {location_2}",
      "Report the full account to {client}"
    ]
  },
  {
    "slug": "faction_power_play",
    "tier": 3,
    "factions": ["any"],
    "title": "Power Play",
    "description": "Actions that shift which faction controls a key city role or location.",
    "payout_range": [400, 800],
    "moral_weight": "high",
    "step_templates": [
      "Understand who currently holds {target}",
      "Undermine their position through {location_1}",
      "Ensure {client}'s candidate or interest fills the vacuum",
      "Cover your tracks"
    ]
  },
  {
    "slug": "arc_mission",
    "tier": 3,
    "factions": ["any"],
    "title": "Arc Mission",
    "description": "Multi-step job evolving over several cases with recurring NPCs.",
    "payout_range": [500, 1000],
    "moral_weight": "high",
    "step_templates": [
      "Make first contact with {target}",
      "Complete the first stage of {client}'s plan",
      "Survive the complication at {location_1}",
      "Deliver the final result"
    ]
  },
  {
    "slug": "exposure",
    "tier": 3,
    "factions": ["press", "naacp"],
    "title": "Exposure",
    "description": "Expose a corrupt figure publicly. Consequences ripple.",
    "payout_range": [400, 700],
    "moral_weight": "high",
    "step_templates": [
      "Gather irrefutable evidence against {target}",
      "Secure corroboration at {location_1}",
      "Deliver to {client} for publication",
      "Manage the fallout"
    ]
  },
  {
    "slug": "cover_up",
    "tier": 3,
    "factions": ["rossi", "castellano", "shorties", "tallboys", "parish_govt"],
    "title": "Cover-Up",
    "description": "Bury evidence or silence witnesses to protect a faction's interests.",
    "payout_range": [450, 900],
    "moral_weight": "high",
    "step_templates": [
      "Identify what needs to disappear",
      "Neutralize the threat at {location_1}",
      "Ensure {target} stays quiet",
      "Confirm to {client} that it's done"
    ]
  }
]
```

- [ ] **Step 2: Create `noir/jobs/generator.py`**

```python
import json
import random
import sqlite3
from pathlib import Path
from noir.llm.base import LLMBackend

_ARCHETYPES_PATH = Path(__file__).parent / "archetypes.json"
_ARCHETYPES: list[dict] | None = None

_SYSTEM = (
    "You are generating a job assignment for a 1935 noir detective game set in Noirleans, Louisiana. "
    "Return ONLY valid JSON matching the exact structure requested. "
    "All names, locations, and details must be period-appropriate for 1935 New Orleans. "
    "NPCs must have 1930s Louisiana names. "
    "Only use locations from the provided list — never invent new ones."
)


def _load_archetypes() -> list[dict]:
    global _ARCHETYPES
    if _ARCHETYPES is None:
        _ARCHETYPES = json.loads(_ARCHETYPES_PATH.read_text())
    return _ARCHETYPES


def _archetypes_for(faction: str, tier: int) -> list[dict]:
    all_archetypes = _load_archetypes()
    return [
        a for a in all_archetypes
        if a["tier"] == tier and (faction in a["factions"] or "any" in a["factions"])
    ]


def _fixed_locations(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM locations WHERE is_fixed=1 ORDER BY name"
    ).fetchall()
    return [r["name"] for r in rows]


class JobGenerator:

    def __init__(self, llm: LLMBackend, conn: sqlite3.Connection):
        self.llm = llm
        self.conn = conn

    def generate(self, *, faction: str, tier: int,
                 archetype_slug: str | None = None) -> dict | None:
        eligible = _archetypes_for(faction, tier)
        if not eligible:
            return None
        if archetype_slug:
            archetype = next((a for a in eligible if a["slug"] == archetype_slug), None)
            if archetype is None:
                return None
        else:
            archetype = random.choice(eligible)

        locations = _fixed_locations(self.conn)
        payout = random.randint(*archetype["payout_range"])

        prompt = (
            f"Faction: {faction}\n"
            f"Job type: {archetype['slug']} — {archetype['description']}\n"
            f"Tier: {tier}\n"
            f"Available locations (use only these): {', '.join(locations[:25])}\n\n"
            f"Generate a specific job. Return JSON:\n"
            f'{{"objective": "one sentence describing what the detective must do", '
            f'"job_archetype": "{archetype["slug"]}", '
            f'"client_npc_name": "name of the NPC hiring the detective", '
            f'"target": "person, object, or information being sought", '
            f'"steps": ['
            f'{{"id": 1, "description": "first step", "completed": false}}, '
            f'{{"id": 2, "description": "second step", "completed": false}}'
            f'], '
            f'"resolution_condition": "report_to_client", '
            f'"moral_weight": "{archetype["moral_weight"]}"}}'
        )

        result = self.llm.query_structured(_SYSTEM, [], prompt)
        if not result or not result.get("objective"):
            return None
        return {
            "faction": faction,
            "tier": tier,
            "title": archetype["title"],
            "payout": payout,
            "case_data": result,
        }

    def generate_board(self, *, faction: str, tier: int, count: int = 2) -> list[dict]:
        results = []
        eligible = _archetypes_for(faction, tier)
        archetypes = random.sample(eligible, min(count, len(eligible)))
        for archetype in archetypes:
            job = self.generate(faction=faction, tier=tier, archetype_slug=archetype["slug"])
            if job:
                results.append(job)
        return results
```

- [ ] **Step 3: Verify archetypes load cleanly**

```bash
cd /Users/danajanezic/code/noir-leans
venv/bin/python -c "
from noir.jobs.generator import _load_archetypes
archetypes = _load_archetypes()
print(f'{len(archetypes)} archetypes loaded')
tier1 = [a['slug'] for a in archetypes if a['tier'] == 1]
tier2 = [a['slug'] for a in archetypes if a['tier'] == 2]
tier3 = [a['slug'] for a in archetypes if a['tier'] == 3]
print(f'Tier 1: {tier1}')
print(f'Tier 2: {tier2}')
print(f'Tier 3: {tier3}')
"
```

Expected: `16 archetypes loaded`, all slugs present in correct tiers.

- [ ] **Step 4: Run full test suite**

```bash
venv/bin/pytest tests/ -x -q 2>&1 | tail -10
```

Expected: PASS (no regressions).

- [ ] **Step 5: Commit**

```bash
git add noir/jobs/archetypes.json noir/jobs/generator.py
git commit -m "feat: job archetypes data (16 templates) and JobGenerator module"
```

---

## Task 7: `/jobs` command + job board replenishment

**Files:**
- Modify: `noir/game.py`

- [ ] **Step 1: Add imports to `noir/game.py`**

Near the top of `game.py` where other repository imports live, add:

```python
from noir.persistence.repository import (
    # existing imports ...
    create_job, get_active_jobs, get_available_jobs,
    create_job_offer, accept_job_offer, decline_job_offer, get_pending_job_offers,
    complete_job, fail_job,
    get_faction_rep, update_faction_rep, get_all_faction_reps,
)
from noir.jobs.factions import FACTIONS, TIER_REP_THRESHOLDS
```

- [ ] **Step 2: Add `_replenish_job_board` method to `Game` class**

Add this method near `start_new_case` (around line 1114):

```python
def _replenish_job_board(self) -> None:
    """Ensure at least 2 tier-1 jobs per faction on the board; tier-2+ if rep qualifies."""
    from noir.jobs.generator import JobGenerator
    from noir.jobs.factions import ALL_FACTION_SLUGS, TIER_REP_THRESHOLDS
    gen = JobGenerator(self.llm, self.conn)
    for faction in ALL_FACTION_SLUGS:
        if faction == "private":
            continue
        for tier in (1, 2, 3):
            threshold = TIER_REP_THRESHOLDS.get(tier, 0)
            if get_faction_rep(self.conn, faction) < threshold:
                continue
            existing = self.conn.execute(
                "SELECT COUNT(*) FROM cases WHERE case_type='job' AND status='pending' "
                "AND faction=? AND tier=?",
                (faction, tier)
            ).fetchone()[0]
            if existing < 2:
                for job in gen.generate_board(faction=faction, tier=tier,
                                              count=2 - existing):
                    create_job(
                        self.conn,
                        faction=job["faction"],
                        tier=job["tier"],
                        title=job["title"],
                        payout=job["payout"],
                        case_data=job["case_data"],
                    )
```

- [ ] **Step 3: Add `handle_slash_jobs` method to `Game` class**

Add near `handle_slash_rep` (around line 3359):

```python
def handle_slash_jobs(self, raw: str) -> None:
    from rich.panel import Panel as _Panel
    args = raw.strip().lower()

    if "--pending" in args:
        offers = get_pending_job_offers(self.conn)
        if not offers:
            console.print("[dim]No pending job offers.[/dim]")
            return
        console.print("[bold yellow]Pending job offers:[/bold yellow]")
        for offer in offers:
            console.print(f"  [yellow]·[/yellow] {offer['npc_name']} has work for you.")
        return

    jobs = get_available_jobs(self.conn)
    if not jobs:
        console.print("[dim]Generating jobs — one moment.[/dim]")
        self._replenish_job_board()
        jobs = get_available_jobs(self.conn)

    if not jobs:
        console.print("[dim]Nothing on the board right now.[/dim]")
        return

    lines = []
    for i, job in enumerate(jobs, 1):
        try:
            data = json.loads(job["case_data"]) if isinstance(job["case_data"], str) else job["case_data"]
        except Exception:
            data = {}
        faction_name = FACTIONS.get(job["faction"] or "", {}).get("name", job["faction"] or "Unknown")
        lines.append(
            f"[bold white]{i}.[/bold white] [Tier {job['tier']}] {job['title']} "
            f"— {faction_name} — [green]${job['payout']}[/green]"
        )
        lines.append(f"   [dim]{data.get('objective', '')}[/dim]")
        lines.append("")

    console.print(_Panel("\n".join(lines).rstrip(), title="[yellow]Available Jobs[/yellow]",
                         border_style="yellow"))

    choice = console.input("[bold white]Take a job? (number or enter to skip): [/bold white]").strip()
    if not choice.isdigit():
        return
    idx = int(choice) - 1
    if not (0 <= idx < len(jobs)):
        console.print("[dim]Invalid selection.[/dim]")
        return

    job = jobs[idx]
    self.conn.execute("UPDATE cases SET status='active' WHERE id=?", (job["id"],))
    self.conn.commit()
    try:
        data = json.loads(job["case_data"]) if isinstance(job["case_data"], str) else job["case_data"]
    except Exception:
        data = {}
    console.print(f"[dim]Job accepted: {job['title']}. Objective: {data.get('objective', '')}[/dim]")
```

- [ ] **Step 4: Wire `/jobs` into `_dispatch_slash`**

In `_dispatch_slash` (around line 2343), add after the `/rep` branch:

```python
        elif slug.startswith("/jobs"):
            self.handle_slash_jobs(raw.strip())
```

Also add `/done` stub (implemented in Task 9):

```python
        elif slug == "/done":
            self.handle_slash_done()
```

- [ ] **Step 5: Add `/jobs` to the help text**

```bash
grep -n "def show_help\|/rep\|/drink\|/bribe" noir/game.py | head -10
```

Find `show_help()` in `display.py` or `game.py` and add:
```
/jobs          Browse available jobs
/jobs --pending  Jobs offered by NPCs
/done          Mark active job complete
```

- [ ] **Step 6: Smoke-test manually** (no automated test for board display — it's IO)

```bash
venv/bin/pytest tests/ -x -q 2>&1 | tail -10
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add noir/game.py
git commit -m "feat: /jobs command — board listing, job selection, board replenishment"
```

---

## Task 8: NPC job offer detection

**Files:**
- Modify: `noir/game.py`

- [ ] **Step 1: Add `_JOB_KEYWORDS` and `_check_npc_job_offer` to `Game` class**

Add `_JOB_KEYWORDS` near `_BRIBE_KEYWORDS` (around line 3484):

```python
    _JOB_KEYWORDS = frozenset([
        "job", "work for me", "errand", "task", "assignment",
        "need someone", "need a man", "reliable person", "discreet",
        "money in it", "paid well", "compensate you",
        "little work", "small job", "favor for me",
    ])
```

Add `_check_npc_job_offer` method after `_check_npc_bribe_offer`:

```python
def _check_npc_job_offer(self, npc_row, response: str) -> None:
    """Detect if NPC just offered the player a job and prompt acceptance."""
    resp_lower = response.lower()
    if not any(kw in resp_lower for kw in self._JOB_KEYWORDS):
        return

    offer = self.llm.query_structured(
        "Determine if the NPC dialogue contains an offer of paid work or a job for the player. "
        "Do not flag general conversation about work or jobs — only a specific offer to the player. "
        "Return ONLY valid JSON: "
        "{\"job_offered\": true|false, \"job_type\": \"string or null\", "
        "\"faction_hint\": \"string or null\"}",
        [],
        f"NPC said: \"{response[:400]}\""
    )
    if not offer.get("job_offered"):
        return

    console.print(f"\n[yellow dim]{npc_row['name']} has work for you. Interested? (yes/no)[/yellow dim]")
    resp = console.input("[bold white]> [/bold white]").strip().lower()
    offer_id = create_job_offer(self.conn, npc_id=npc_row["id"])
    if resp != "yes":
        decline_job_offer(self.conn, offer_id=offer_id)
        console.print("[dim]You pass.[/dim]")
        return
    self._activate_npc_job_offer(npc_row, offer_id, offer.get("faction_hint"))
```

Add `_activate_npc_job_offer` method:

```python
def _activate_npc_job_offer(self, npc_row, offer_id: int,
                             faction_hint: str | None) -> None:
    """Generate and activate a job offered by an NPC."""
    from noir.jobs.generator import JobGenerator
    from noir.jobs.factions import faction_slug_for_npc, TIER_REP_THRESHOLDS

    npc_faction = faction_slug_for_npc(self.conn, npc_row["id"])
    faction = npc_faction or "private"

    tier = 1
    if faction != "private":
        rep = get_faction_rep(self.conn, faction)
        if rep >= TIER_REP_THRESHOLDS[2]:
            tier = 2

    gen = JobGenerator(self.llm, self.conn)
    job = gen.generate(faction=faction, tier=tier)
    if not job:
        console.print("[dim]They seem to have changed their mind.[/dim]")
        decline_job_offer(self.conn, offer_id=offer_id)
        return

    job_id = create_job(
        self.conn,
        faction=job["faction"],
        tier=job["tier"],
        title=job["title"],
        payout=job["payout"],
        case_data=job["case_data"],
    )
    self.conn.execute("UPDATE cases SET status='active' WHERE id=?", (job_id,))
    self.conn.commit()
    accept_job_offer(self.conn, offer_id=offer_id, case_id=job_id)

    try:
        data = job["case_data"]
        objective = data.get("objective", "") if isinstance(data, dict) else ""
    except Exception:
        objective = ""
    console.print(f"[dim]Job taken. {objective}[/dim]")
```

- [ ] **Step 2: Wire `_check_npc_job_offer` into the NPC conversation loop**

In the NPC conversation loop (around line 1546, after `_check_npc_bribe_offer`):

```python
            self._check_npc_bribe_offer(npc_row, response)
            self._check_npc_job_offer(npc_row, response)  # ADD THIS LINE
            self._check_npc_appointment(npc_row["id"], npc_row["name"], player_input, response)
```

- [ ] **Step 3: Run full test suite**

```bash
venv/bin/pytest tests/ -x -q 2>&1 | tail -10
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add noir/game.py
git commit -m "feat: NPC job offer detection — _check_npc_job_offer wired into conversation loop"
```

---

## Task 9: Job resolution — `/done` command + auto-detect

**Files:**
- Modify: `noir/game.py`

- [ ] **Step 1: Add `handle_slash_done` method to `Game` class**

```python
def handle_slash_done(self) -> None:
    """Mark an active job complete after confirming with the client NPC."""
    from rich.panel import Panel as _Panel

    active_jobs = get_active_jobs(self.conn)
    if not active_jobs:
        console.print("[dim]No active jobs.[/dim]")
        return

    if len(active_jobs) == 1:
        job = active_jobs[0]
    else:
        console.print("[bold yellow]Active jobs:[/bold yellow]")
        for i, j in enumerate(active_jobs, 1):
            console.print(f"  {i}. {j['title']}")
        choice = console.input("[bold white]Which job are you completing? (number): [/bold white]").strip()
        if not choice.isdigit() or not (1 <= int(choice) <= len(active_jobs)):
            console.print("[dim]Cancelled.[/dim]")
            return
        job = active_jobs[int(choice) - 1]

    try:
        data = json.loads(job["case_data"]) if isinstance(job["case_data"], str) else job["case_data"]
    except Exception:
        data = {}

    objective = data.get("objective", "complete the objective")
    verdict = self.llm.query_structured(
        "The detective claims to have completed a job. "
        "Based on the objective, judge whether it is plausible they succeeded. "
        "Return ONLY valid JSON: {\"completed\": true|false, \"reason\": \"one sentence\"}",
        [],
        f"Job objective: {objective}\nDetective claims: done."
    )

    if not verdict.get("completed", True):
        console.print(f"[dim]{verdict.get('reason', 'The job is not done yet.')}[/dim]")
        return

    payout = job["payout"] or 0
    faction = job["faction"] or "private"
    tier = job["tier"] or 1
    complete_job(self.conn, case_id=job["id"], payout=payout, faction=faction, tier=tier)

    if payout:
        console.print(f"[dim]Job done. ${payout} collected.[/dim]")
    else:
        console.print("[dim]Job done.[/dim]")

    moral_weight = data.get("moral_weight", "low")
    if moral_weight == "high" and self.companion:
        self.companion.speak(
            f"[You just completed a morally significant job: {objective}]",
            record=False
        )
```

- [ ] **Step 2: Add auto-detect in the NPC conversation loop**

After the `_check_npc_job_offer` call (around line 1546), add:

```python
            self._check_job_completion(npc_row, response)
```

Add `_check_job_completion` method:

```python
def _check_job_completion(self, npc_row, response: str) -> None:
    """Auto-detect if the NPC's response signals job completion."""
    active_jobs = get_active_jobs(self.conn)
    if not active_jobs:
        return

    job = next(
        (j for j in active_jobs
         if (json.loads(j["case_data"]) if isinstance(j["case_data"], str)
             else j["case_data"]).get("client_npc_name", "").lower()
            in npc_row["name"].lower()),
        None
    )
    if not job:
        return

    signal = self.llm.query_structured(
        "Does the NPC dialogue signal that a job or task has been completed to their satisfaction? "
        "Return ONLY valid JSON: {\"job_complete\": true|false}",
        [],
        f"NPC said: \"{response[:300]}\""
    )
    if not signal.get("job_complete"):
        return

    payout = job["payout"] or 0
    faction = job["faction"] or "private"
    tier = job["tier"] or 1
    complete_job(self.conn, case_id=job["id"], payout=payout, faction=faction, tier=tier)
    if payout:
        console.print(f"[dim]Job complete. ${payout} in your pocket.[/dim]")
    else:
        console.print("[dim]Job complete.[/dim]")
```

- [ ] **Step 3: Run full test suite**

```bash
venv/bin/pytest tests/ -x -q 2>&1 | tail -10
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add noir/game.py
git commit -m "feat: job resolution — /done command and auto-detect on NPC completion signal"
```

---

## Task 10: Cross-faction tension events

**Files:**
- Modify: `noir/game.py`

- [ ] **Step 1: Write the failing test** (add to `tests/test_jobs.py`)

```python
from noir.jobs.factions import TENSION_THRESHOLD, OPPOSITION


def test_opposing_factions_above_threshold_detected(db):
    update_faction_rep(db, "rossi", TENSION_THRESHOLD)
    update_faction_rep(db, "castellano", TENSION_THRESHOLD)
    reps = get_all_faction_reps(db)
    tension_pairs = []
    for faction, rep in reps.items():
        if rep < TENSION_THRESHOLD:
            continue
        if faction not in OPPOSITION:
            continue
        for opp in OPPOSITION[faction].get("direct", []):
            if reps.get(opp, 0) >= TENSION_THRESHOLD:
                tension_pairs.append((faction, opp))
    assert ("rossi", "castellano") in tension_pairs or ("castellano", "rossi") in tension_pairs


def test_neutral_factions_do_not_trigger_tension(db):
    update_faction_rep(db, "shorties", TENSION_THRESHOLD)
    update_faction_rep(db, "naacp", TENSION_THRESHOLD)
    reps = get_all_faction_reps(db)
    tension_pairs = []
    for faction, rep in reps.items():
        if rep < TENSION_THRESHOLD:
            continue
        if faction not in OPPOSITION:
            continue
        for opp in OPPOSITION[faction].get("direct", []):
            if reps.get(opp, 0) >= TENSION_THRESHOLD:
                tension_pairs.append((faction, opp))
    # shorties and naacp are not direct oppositions
    assert ("shorties", "naacp") not in tension_pairs
    assert ("naacp", "shorties") not in tension_pairs
```

- [ ] **Step 2: Run to verify tests pass** (these test the data, not game.py)

```bash
venv/bin/pytest tests/test_jobs.py -k "tension" -v
```

Expected: PASS (pure data assertions).

- [ ] **Step 3: Add `_check_faction_tension` to `Game` class**

```python
def _check_faction_tension(self) -> None:
    """Fire a tension event if player holds ≥ 40 rep with two directly opposing factions."""
    from noir.jobs.factions import OPPOSITION, TENSION_THRESHOLD, TENSION_ESCALATION
    reps = get_all_faction_reps(self.conn)
    checked: set[frozenset] = set()
    for faction, rep in reps.items():
        if rep < TENSION_THRESHOLD:
            continue
        if faction not in OPPOSITION:
            continue
        for opp in OPPOSITION[faction].get("direct", []):
            pair = frozenset((faction, opp))
            if pair in checked:
                continue
            checked.add(pair)
            opp_rep = reps.get(opp, 0)
            if opp_rep < TENSION_THRESHOLD:
                continue
            self._trigger_tension_event(faction, opp, rep, opp_rep)
            return

def _trigger_tension_event(self, faction_a: str, faction_b: str,
                            rep_a: int, rep_b: int) -> None:
    from noir.jobs.factions import FACTIONS, TENSION_ESCALATION
    name_a = FACTIONS.get(faction_a, {}).get("name", faction_a)
    name_b = FACTIONS.get(faction_b, {}).get("name", faction_b)
    escalated = rep_a >= TENSION_ESCALATION or rep_b >= TENSION_ESCALATION

    if escalated:
        msg = (f"[red]A contact from {name_a} corners you. Word has reached {name_b}. "
               f"They want to know where your loyalties lie — and they're not asking politely.[/red]")
    else:
        msg = (f"[yellow dim]Word is traveling between {name_a} and {name_b}. "
               f"Someone's noticed you're working both sides.[/yellow dim]")
    console.print(f"\n{msg}")

    console.print("[bold white]How do you respond? (reassure / dismiss / choose): [/bold white]", end="")
    choice = console.input("").strip().lower()

    if choice == "reassure":
        update_faction_rep(self.conn, faction_a, 5)
        console.print(f"[dim]You smooth it over with {name_a}. For now.[/dim]")
    elif choice == "choose":
        console.print(f"[bold white]Side with {name_a} or {name_b}? [/bold white]", end="")
        side = console.input("").strip().lower()
        if name_a.lower() in side or faction_a in side:
            update_faction_rep(self.conn, faction_a, 15)
            update_faction_rep(self.conn, faction_b, -20)
            console.print(f"[dim]You've made your choice. {name_b} won't forget.[/dim]")
        else:
            update_faction_rep(self.conn, faction_b, 15)
            update_faction_rep(self.conn, faction_a, -20)
            console.print(f"[dim]You've made your choice. {name_a} won't forget.[/dim]")
    else:
        update_faction_rep(self.conn, faction_a, -5)
        console.print("[dim]They don't like that answer.[/dim]")
```

- [ ] **Step 4: Wire `_check_faction_tension` into location transitions**

Find `handle_go` in `game.py` (the method that transitions locations). After the location transition completes and before returning, add:

```bash
grep -n "def handle_go\b" noir/game.py
```

Then at the end of the `handle_go` method, before `return`:

```python
        self._check_faction_tension()
```

- [ ] **Step 5: Run full test suite**

```bash
venv/bin/pytest tests/ -x -q 2>&1 | tail -10
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add noir/game.py tests/test_jobs.py
git commit -m "feat: cross-faction tension events on location transitions"
```

---

## Task 11: Display updates — faction rep in `/status` and `/rep`

**Files:**
- Modify: `noir/display.py`
- Modify: `noir/game.py`

- [ ] **Step 1: Update `handle_slash_rep` in `game.py` to show faction standings**

Replace the existing `handle_slash_rep` method body (around line 3359):

```python
def handle_slash_rep(self) -> None:
    from rich.panel import Panel as _Panel
    from noir.jobs.factions import FACTIONS

    # Street rep (existing)
    rep = get_street_reputation(self.conn)
    tags = rep.get("tags", [])
    street_says = rep.get("street_says", "")
    tag_str = "  ".join(f"[bold]{t}[/bold]" for t in tags) if tags else "[dim]none[/dim]"
    body = tag_str
    if street_says:
        body += f"\n\n[italic dim]{street_says}[/italic dim]"
    console.print(_Panel(body, title="[yellow]Street Reputation[/yellow]", border_style="yellow"))

    # Faction standings
    reps = get_all_faction_reps(self.conn)
    nonzero = {k: v for k, v in reps.items() if v > 0}
    if nonzero:
        lines = []
        for slug, score in sorted(nonzero.items(), key=lambda x: -x[1]):
            name = FACTIONS.get(slug, {}).get("name", slug)
            bar = "█" * (score // 10) + "░" * (10 - score // 10)
            lines.append(f"  [yellow]{name:<40}[/yellow] {bar} {score}")
        console.print(_Panel("\n".join(lines), title="[yellow]Faction Standing[/yellow]",
                             border_style="yellow dim"))
    else:
        console.print("[dim]No faction standing yet. Take some jobs.[/dim]")
```

- [ ] **Step 2: Update `/status` to show active jobs count**

In `handle_slash_status` (around line 1960), after printing case info, add:

```python
        active_jobs = get_active_jobs(self.conn)
        if active_jobs:
            console.print(f"\n[bold yellow]Active jobs ({len(active_jobs)}):[/bold yellow]")
            for job in active_jobs:
                try:
                    data = json.loads(job["case_data"]) if isinstance(job["case_data"], str) else job["case_data"]
                    objective = data.get("objective", "")
                except Exception:
                    objective = ""
                faction_name = FACTIONS.get(job["faction"] or "", {}).get("name", "")
                console.print(f"  [yellow]·[/yellow] {job['title']} ({faction_name}) — {objective}")
```

- [ ] **Step 3: Run full test suite**

```bash
venv/bin/pytest tests/ -x -q 2>&1 | tail -10
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add noir/game.py noir/display.py
git commit -m "feat: faction standings in /rep; active jobs in /status"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|-----------------|------|
| `faction_reputation` table seeded with 19 factions | Task 1 |
| `faction`, `tier`, `payout` columns on cases | Task 1 |
| `job_offers` table | Task 1 |
| `da_trust` migrated to faction rep | Task 4 |
| All 19 faction slugs + opposition matrix | Task 2 |
| 5 missing orgs (Shorties, Tallboys, Chamber, NAACP, Press) | Task 5 |
| `create_job`, `complete_job`, `fail_job`, etc. | Task 5 |
| Rep gains/losses per tier | Task 5 |
| Opposition penalties (Tallboys → NAACP direct; Shorties → NAACP neutral) | Task 5 |
| 16 job archetypes across 3 tiers | Task 6 |
| `JobGenerator` with LLM fill | Task 6 |
| `/jobs` board command | Task 7 |
| Job board replenishment | Task 7 |
| NPC job offer detection | Task 8 |
| `/done` command | Task 9 |
| Auto-detect completion | Task 9 |
| Cross-faction tension at ≥ 40 | Task 10 |
| Faction rep in `/rep` | Task 11 |
| Active jobs in `/status` | Task 11 |

**Tier 3 city consequences:** Explicitly deferred per spec.
**Recurring named NPCs for arc missions:** Deferred per spec.
**`/jobs --pending` re-visit:** Implemented in Task 7 (display only; acceptance via `/jobs --pending` is shown but NPC re-approach is implicit).

**Type consistency check:** All tasks use `create_job`, `complete_job`, `fail_job`, `get_faction_rep`, `update_faction_rep` — consistent throughout. `case_data` is always a `dict` passed to `json.dumps` in `create_job`. `job["case_data"]` is always decoded with `json.loads` before use.
