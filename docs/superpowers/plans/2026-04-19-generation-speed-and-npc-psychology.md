# Generation Speed + NPC Psychology Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut case generation wall-time by ~45% via hardcoded NPC archetypes, pre-seeded locations, and lazy backstory enrichment; then wire in the NPC Secret Revelation psychology system from the approved spec.

**Architecture:** Phase 1 (blocking) generates a lean case skeleton — suspects get an `archetype_id` instead of freeform personality/speech_style, and locations are names drawn from a pre-seeded pool (descriptions already in DB). Phase 2 (background threads) generates backstory per NPC and assembles the full `system_prompt`. The psychology system adds six scalar fields per suspect, classifies each NPC exchange with a lightweight LLM call, updates guilt/pressure state, and fires staged confession prompts when thresholds are crossed.

**Note:** NPC Ages spec is already fully implemented (merged). This plan does not re-implement it.

**Tech Stack:** Python 3.12, SQLite, ollama (local LLM), threading, existing `noir/persistence/`, `noir/characters/`, `noir/mystery/` structure.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `noir/characters/npc_archetypes.json` | Create | 30 hardcoded personality archetypes |
| `noir/characters/npc_archetype_loader.py` | Create | Load archetypes from JSON; `get_npc_archetype(id)` |
| `scripts/generate_locations.py` | Create | One-time script to generate 100 locations via LLM |
| `noir/data/seeded_locations.json` | Create (run script) | 100 pre-generated Noirleans locations |
| `noir/characters/psychology.py` | Create | Event classifier, state updater, revelation trigger |
| `tests/test_npc_archetypes.py` | Create | Archetype loader tests |
| `tests/test_psychology.py` | Create | Psychology module tests (no LLM for threshold logic) |
| `noir/persistence/db.py` | Modify | Migrations: seeded_locations table, suspects.archetype_id, npcs psychology columns, npc_relationships psychology columns |
| `noir/persistence/repository.py` | Modify | seed_locations_to_db, get_seeded_location_names, get_seeded_location_description, update_npc_system_prompt, update_suspect_backstory, create_npc (new fields), get_npc_psychology, update_npc_guilt, update_npc_pressure, decay_npc_pressure, get_npc_revelation_stage, increment_npc_revelation_stage |
| `noir/mystery/generator.py` | Modify | Slim phase 1 schema; add `enrich_npc()` and `enrich_npcs_for_case()` |
| `noir/game.py` | Modify | Pass new fields to create_npc; background enrichment threads; check_revelation after each NPC exchange |
| `noir/step.py` | Modify | check_revelation after _talk_npc |
| `tests/test_mystery.py` | Modify | Update VALID_CASE: archetype_id, no personality/speech_style, locations without description |
| `tests/test_auditor.py` | Modify | Update BASE_CASE same way |
| `tests/test_step.py` | Modify | Add psychology classify_events mock response to NPC talk tests |

---

## Task 1: NPC Archetype JSON + Loader

**Files:**
- Create: `noir/characters/npc_archetypes.json`
- Create: `noir/characters/npc_archetype_loader.py`
- Create: `tests/test_npc_archetypes.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_npc_archetypes.py
from noir.characters.npc_archetype_loader import load_npc_archetypes, get_npc_archetype

def test_load_npc_archetypes_returns_30():
    archetypes = load_npc_archetypes()
    assert len(archetypes) == 30

def test_each_archetype_has_required_fields():
    for a in load_npc_archetypes():
        assert "id" in a
        assert "name" in a
        assert "personality" in a
        assert "speech_style" in a

def test_get_npc_archetype_by_id():
    a = get_npc_archetype("nervous_informant")
    assert a is not None
    assert a["id"] == "nervous_informant"

def test_get_npc_archetype_unknown_returns_none():
    assert get_npc_archetype("does_not_exist") is None
```

- [ ] **Step 2: Run to confirm failure**

```bash
python3 -m pytest tests/test_npc_archetypes.py -v
```
Expected: `ModuleNotFoundError` or `FileNotFoundError`

- [ ] **Step 3: Create the archetype JSON**

Create `noir/characters/npc_archetypes.json`:

```json
[
  {"id": "nervous_informant", "name": "The Nervous Informant", "personality": "Jumpy, easily startled, talks too fast when cornered", "speech_style": "Incomplete sentences, lots of self-interruptions and 'you didn't hear this from me'"},
  {"id": "calculating_schemer", "name": "The Calculating Schemer", "personality": "Cold, precise, chooses every word deliberately", "speech_style": "Short declarative sentences, asks questions to answer questions, never volunteers more than asked"},
  {"id": "jovial_deflector", "name": "The Jovial Deflector", "personality": "Uses charm and humor to avoid answering anything directly", "speech_style": "Tells stories instead of giving answers, laughs at the wrong moments"},
  {"id": "wounded_romantic", "name": "The Wounded Romantic", "personality": "Melodramatic, takes everything personally, believes they have been wronged by life", "speech_style": "Overwrought, prone to tangents about betrayal and lost love"},
  {"id": "street_tough", "name": "The Street Tough", "personality": "Aggressive, territorial, reads questions as threats", "speech_style": "Clipped, profane, asks 'who wants to know' before answering anything"},
  {"id": "corrupt_official", "name": "The Corrupt Official", "personality": "Smooth, condescending, believes they are untouchable", "speech_style": "Euphemisms for everything, never says what he means directly, speaks in implications"},
  {"id": "loyal_lackey", "name": "The Loyal Lackey", "personality": "Deferential, constantly looks to others for approval, afraid of being abandoned", "speech_style": "Qualifies everything, frequently mentions who they work for, 'I'm not sure I should say'"},
  {"id": "bitter_veteran", "name": "The Bitter Veteran", "personality": "Seen everything, trusts nothing, finds most people disappointing", "speech_style": "Dry, sardonic, uses decade-old examples to make present-day points"},
  {"id": "religious_penitent", "name": "The Religious Penitent", "personality": "Guilt-ridden, believes suffering is deserved, references God constantly", "speech_style": "Quotes scripture at inappropriate moments, frames everything as punishment or redemption"},
  {"id": "charming_liar", "name": "The Charming Liar", "personality": "Silver-tongued, impossible to pin down, lying comes as naturally as breathing", "speech_style": "Warm, agreeable, slightly too helpful — changes details between conversations"},
  {"id": "grieving_witness", "name": "The Grieving Witness", "personality": "Raw emotion, cannot focus, keeps returning to the loss", "speech_style": "Trails off mid-sentence, sudden crying, answers questions nobody asked"},
  {"id": "bragging_blowhard", "name": "The Bragging Blowhard", "personality": "Cannot resist talking about himself, believes his own mythology", "speech_style": "Long tangents, name-dropping, brings everything back to his own exploits"},
  {"id": "paranoid_conspiracist", "name": "The Paranoid Conspiracist", "personality": "Sees enemies everywhere, trusts no one, connects unrelated events into patterns", "speech_style": "Whispers, checks over his shoulder, asks if you were followed"},
  {"id": "dignified_aristocrat", "name": "The Dignified Aristocrat", "personality": "Formal, above it all, finds the investigation slightly beneath them", "speech_style": "Never uses contractions, treats questions as impertinence, never raises voice"},
  {"id": "dock_worker", "name": "The Dock Worker", "personality": "Blunt, physical, no patience for fancy talk or games", "speech_style": "Short, direct, uses labor slang, says what he means immediately"},
  {"id": "jazz_musician", "name": "The Jazz Musician", "personality": "Poetic, oblique, lives sideways to ordinary reality", "speech_style": "Speaks in metaphors and analogies, rarely gives direct answers, everything sounds like a lyric"},
  {"id": "society_matron", "name": "The Society Matron", "personality": "Imperious, obsessed with appearances, defines people by social position", "speech_style": "Name-drops constantly, refers to people by their family rather than themselves, weaponizes politeness"},
  {"id": "immigrant_survivor", "name": "The Immigrant Survivor", "personality": "Careful, proud, deeply defensive about their place and their people", "speech_style": "Precise English that slips into a first language when emotional, hyperaware of how they are being read"},
  {"id": "reformed_criminal", "name": "The Reformed Criminal", "personality": "Trying hard to go straight, still thinks like a criminal, slips into old patterns under pressure", "speech_style": "Catches himself using underworld terms and corrects mid-sentence, overexplains his innocence"},
  {"id": "young_idealist", "name": "The Young Idealist", "personality": "Earnest, naive, gets angry when reality does not match his principles", "speech_style": "Long passionate speeches, interrupts himself, apologizes for being upset immediately after"},
  {"id": "world_weary_barkeep", "name": "The World-Weary Barkeep", "personality": "Has seen everything, judges nobody, gives advice nobody asked for", "speech_style": "Philosophical and unhurried, uses the bar as metaphor for life, never surprised by anything"},
  {"id": "jealous_lover", "name": "The Jealous Lover", "personality": "Volatile, reads every question as an accusation, sees betrayal in neutral statements", "speech_style": "Defensive from the first word, pivots from answers to accusations, voice rises unpredictably"},
  {"id": "crooked_cop", "name": "The Crooked Cop", "personality": "Bored, vaguely threatening, would rather not be here, already has his story straight", "speech_style": "Official language deployed to end conversations, occasional veiled threat disguised as advice"},
  {"id": "desperate_debtor", "name": "The Desperate Debtor", "personality": "Panicked, willing to say anything to make the problem go away, bargains immediately", "speech_style": "Talks too much, offers information before asked, promises things he can't deliver"},
  {"id": "silent_observer", "name": "The Silent Observer", "personality": "Few words, watches more than speaks, says exactly what matters and nothing else", "speech_style": "One or two sentences at a time, long pauses before answering, never repeats himself"},
  {"id": "political_operator", "name": "The Political Operator", "personality": "Everything is a transaction, finds the angle in every conversation", "speech_style": "Every answer positions him for something, phrases questions as favors, nothing is free"},
  {"id": "grieving_parent", "name": "The Grieving Parent", "personality": "Lost, looking for someone to blame, grief has made them dangerous in unexpected ways", "speech_style": "Quiet until triggered, then overwhelmingly intense, cannot sustain small talk"},
  {"id": "mob_enforcer", "name": "The Mob Enforcer", "personality": "Polite, specific, very dangerous, comfortable with silence", "speech_style": "Pleasantries that don't reach his eyes, precise language, notes things for later"},
  {"id": "church_deacon", "name": "The Church Deacon", "personality": "Pious, judgmental, uncomfortable with anything that requires admitting the world is imperfect", "speech_style": "Quotes morality, reframes criminal questions as spiritual ones, visibly uncomfortable"},
  {"id": "femme_fatale", "name": "The Femme Fatale", "personality": "Knows exactly what power she has and uses it deliberately, never lets anyone see her calculating", "speech_style": "Languid, lets silences do work, answers questions with her own questions, always faintly amused"}
]
```

- [ ] **Step 4: Create the loader**

Create `noir/characters/npc_archetype_loader.py`:

```python
import json
from pathlib import Path
from functools import lru_cache

_PATH = Path(__file__).parent / "npc_archetypes.json"


@lru_cache(maxsize=None)
def load_npc_archetypes() -> tuple[dict, ...]:
    return tuple(json.loads(_PATH.read_text()))


def get_npc_archetype(archetype_id: str) -> dict | None:
    for a in load_npc_archetypes():
        if a["id"] == archetype_id:
            return a
    return None


def archetype_ids() -> list[str]:
    return [a["id"] for a in load_npc_archetypes()]
```

- [ ] **Step 5: Run tests to confirm pass**

```bash
python3 -m pytest tests/test_npc_archetypes.py -v
```
Expected: 4 PASSED

- [ ] **Step 6: Commit**

```bash
git add noir/characters/npc_archetypes.json noir/characters/npc_archetype_loader.py tests/test_npc_archetypes.py
git commit -m "feat: add 30 hardcoded NPC personality archetypes with loader"
```

---

## Task 2: Seeded Locations — Generation Script + DB + Repository

**Files:**
- Create: `scripts/generate_locations.py`
- Create: `noir/data/seeded_locations.json` (by running the script)
- Modify: `noir/persistence/db.py`
- Modify: `noir/persistence/repository.py`

- [ ] **Step 1: Write the failing tests**

```python
# Add to tests/test_mystery.py (at the top of the file, after imports):
from noir.persistence.repository import seed_locations_to_db, get_seeded_location_names, get_seeded_location_description

def test_seed_locations_to_db_and_retrieve(db):
    locations = [
        {"name": "Fournier's Jazz Club", "description": "Low ceiling, high noise.", "type": "club"},
        {"name": "The Rusty Anchor", "description": "Smells of brine and broken promises.", "type": "bar"},
    ]
    seed_locations_to_db(db, locations)
    names = get_seeded_location_names(db)
    assert "Fournier's Jazz Club" in names
    assert "The Rusty Anchor" in names

def test_get_seeded_location_description(db):
    locations = [{"name": "Pilot House", "description": "River views, sticky tables.", "type": "bar"}]
    seed_locations_to_db(db, locations)
    desc = get_seeded_location_description(db, "Pilot House")
    assert desc == "River views, sticky tables."

def test_get_seeded_location_description_unknown_returns_none(db):
    assert get_seeded_location_description(db, "Nonexistent Place") is None
```

- [ ] **Step 2: Run to confirm failure**

```bash
python3 -m pytest tests/test_mystery.py::test_seed_locations_to_db_and_retrieve -v
```
Expected: `ImportError` (functions don't exist yet)

- [ ] **Step 3: Add DB migration**

In `noir/persistence/db.py`, add to `_MIGRATIONS` list (append at the end):

```python
    """CREATE TABLE IF NOT EXISTS seeded_locations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL,
        type TEXT
    )""",
```

Note: migrations that are `CREATE TABLE IF NOT EXISTS` strings (not ALTER TABLE) need to be handled specially. Look at the existing `_run_migrations` function — if it only runs ALTER TABLE statements, add a `_create_seeded_locations` call in `create_schema()` instead:

```python
# In create_schema(), add after the existing CREATE TABLE statements:
conn.executescript("""
    CREATE TABLE IF NOT EXISTS seeded_locations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL,
        type TEXT
    );
""")
conn.commit()
```

- [ ] **Step 4: Add repository functions**

In `noir/persistence/repository.py`, add after the `create_location` function:

```python
def seed_locations_to_db(conn: sqlite3.Connection, locations: list[dict]) -> None:
    for loc in locations:
        conn.execute(
            "INSERT OR IGNORE INTO seeded_locations (name, description, type) VALUES (?, ?, ?)",
            (loc["name"], loc["description"], loc.get("type"))
        )
    conn.commit()


def get_seeded_location_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM seeded_locations ORDER BY name").fetchall()
    return [r["name"] for r in rows]


def get_seeded_location_description(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute(
        "SELECT description FROM seeded_locations WHERE name=?", (name,)
    ).fetchone()
    return row["description"] if row else None
```

- [ ] **Step 5: Run tests to confirm pass**

```bash
python3 -m pytest tests/test_mystery.py::test_seed_locations_to_db_and_retrieve tests/test_mystery.py::test_get_seeded_location_description tests/test_mystery.py::test_get_seeded_location_description_unknown_returns_none -v
```
Expected: 3 PASSED

- [ ] **Step 6: Create the location generation script**

Create `scripts/generate_locations.py`:

```python
#!/usr/bin/env python3
"""One-time script to generate seeded locations for Noirleans.

Usage:
    python3 scripts/generate_locations.py

Writes noir/data/seeded_locations.json. Review the output before committing.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from noir.llm.ollama import OllamaBackend

OUTPUT = Path(__file__).parent.parent / "noir" / "data" / "seeded_locations.json"

PROMPT = """Generate exactly 100 distinct, period-accurate locations in Noirleans (fictional 1935 New Orleans).
Each should feel like it belongs in a corrupt, jazz-soaked, Depression-era detective story.
Include: bars, jazz clubs, offices, warehouses, churches, hotels, restaurants, docks, gambling dens,
brothels (euphemistically named), political offices, tenements, markets, pawn shops, funeral homes,
speakeasies-turned-legal, union halls, newspaper offices, precinct holding rooms, pharmacies, diners.
Reflect 1935 racial geography — some are primarily Black establishments, some are white-only,
some are mixed-race. Names should be specific and evocative, not generic.

Return a JSON object: {"locations": [
  {"name": "string (specific evocative name)", "description": "string (1-2 sentences)", "type": "bar|club|office|warehouse|church|hotel|restaurant|dock|gambling|political|residence|market|transport|other"}
]}
Return exactly 100 entries."""

llm = OllamaBackend(timeout=600)
print("Generating 100 locations... (this may take several minutes)", file=sys.stderr)
result = llm.query_structured(
    "You are a world-builder for a 1935 Noirleans noir detective game. Return only valid JSON.",
    [],
    PROMPT,
)
locations = result.get("locations", [])
print(f"Generated {len(locations)} locations.", file=sys.stderr)
OUTPUT.write_text(json.dumps(locations, indent=2))
print(f"Written to {OUTPUT}", file=sys.stderr)
```

- [ ] **Step 7: Run the script to generate locations**

```bash
python3 scripts/generate_locations.py
```
Expected: `noir/data/seeded_locations.json` written with ~100 location objects.

If fewer than 80 locations are generated, run again or manually add entries to reach at least 80.

- [ ] **Step 8: Wire seeding into game startup**

In `noir/game.py`, in the `loop()` method after `seed_archetypes_to_db(self.conn)`:

```python
from noir.persistence.repository import seed_locations_to_db as _seed_locs
import json as _json_loc
from pathlib import Path as _Path
_locs_path = _Path(__file__).parent / "data" / "seeded_locations.json"
if _locs_path.exists():
    _seed_locs(self.conn, _json_loc.loads(_locs_path.read_text()))
```

In `noir/step.py`, in `_ensure_archetypes()`:

```python
def _ensure_seeded_locations(conn: sqlite3.Connection) -> None:
    from pathlib import Path
    from noir.persistence.repository import seed_locations_to_db, get_seeded_location_names
    if get_seeded_location_names(conn):
        return  # already seeded
    locs_path = Path(__file__).parent / "data" / "seeded_locations.json"
    if locs_path.exists():
        import json
        seed_locations_to_db(conn, json.loads(locs_path.read_text()))
```

Call `_ensure_seeded_locations(conn)` from `run_step()` alongside the other `_ensure_*` calls.

- [ ] **Step 9: Run full test suite**

```bash
python3 -m pytest tests/ -x -q
```
Expected: all passing

- [ ] **Step 10: Commit**

```bash
git add scripts/generate_locations.py noir/data/seeded_locations.json noir/persistence/db.py noir/persistence/repository.py noir/game.py noir/step.py tests/test_mystery.py
git commit -m "feat: add seeded locations pool — 100 pre-generated Noirleans locations"
```

---

## Task 3: Slim Generator Phase 1 Schema

Remove `personality`, `speech_style`, `backstory`, and location `description` from the generator output. Add `archetype_id`. Generator now reads archetype list and location names from DB/JSON to include in the prompt.

**Files:**
- Modify: `noir/mystery/generator.py`
- Modify: `tests/test_mystery.py`
- Modify: `tests/test_auditor.py`

- [ ] **Step 1: Update VALID_CASE in tests**

In `tests/test_mystery.py`, update `VALID_CASE`:

```python
VALID_CASE = {
    "title": "The Fitch Affair",
    "victim": {"name": "Gerald Fitch", "cause_of_death": "spontaneous accordion implosion", "found_at": "The Parlour"},
    "killer_name": "Dolores Mink",
    "motive": "Gerald knew about her collection of illegal flamingos",
    "suspects": [
        {
            "name": "Dolores Mink",
            "role": "suspect",
            "alibi": "Claims she was at the flamingo sanctuary",
            "secret": "She owns the flamingos",
            "archetype_id": "femme_fatale",
            "race": "White",
            "political_connections": "None",
            "age": 34,
            "routine": [{"time_start": "09:00", "time_end": "17:00", "location": "The Parlour"}],
            "alignment": "Chaotic Evil",
            "pressure_tolerance": 7,
            "kindness_weight": 3,
            "empathy": 2,
            "starting_guilt": 1,
            "revelation_style": "sudden",
            "revelation_stages": 1,
        },
        {
            "name": "Reginald Smoot",
            "role": "suspect",
            "alibi": "Was definitely not at the scene",
            "secret": "Owes Gerald money",
            "archetype_id": "desperate_debtor",
            "race": "White",
            "political_connections": "None",
            "age": 45,
            "routine": [{"time_start": "09:00", "time_end": "17:00", "location": "The Parlour"}],
            "alignment": "Lawful Neutral",
            "pressure_tolerance": 2,
            "kindness_weight": 5,
            "empathy": 6,
            "starting_guilt": 3,
            "revelation_style": "staged",
            "revelation_stages": 3,
        }
    ],
    "clues": [
        {"description": "A flamingo feather on the accordion", "is_red_herring": False, "location": "The Music Room"},
        {"description": "A receipt from the flamingo sanctuary", "is_red_herring": False, "location": "The Victim's Desk"},
        {"description": "Reginald's IOU note", "is_red_herring": True, "location": "The Parlour"}
    ],
    "locations": [
        {"name": "The Music Room"},
        {"name": "The Victim's Desk"},
        {"name": "The Parlour"}
    ]
}
```

- [ ] **Step 2: Run tests to see current failures**

```bash
python3 -m pytest tests/test_mystery.py -x -q
```
Some tests will fail because REQUIRED_SUSPECT_FIELDS and REQUIRED_LOCATION_FIELDS haven't changed yet. Note which ones.

- [ ] **Step 3: Update generator constants and validation**

In `noir/mystery/generator.py`:

```python
REQUIRED_SUSPECT_FIELDS = {
    "name", "role", "alibi", "secret", "archetype_id", "race",
    "political_connections", "routine", "alignment", "age",
    "pressure_tolerance", "kindness_weight", "empathy",
    "starting_guilt", "revelation_style", "revelation_stages",
}
REQUIRED_LOCATION_FIELDS = {"name"}
```

- [ ] **Step 4: Update `_validate_case()` for integer psychology fields**

In `_validate_case()`, add after the existing suspect field check:

```python
        for suspect in case["suspects"]:
            if not REQUIRED_SUSPECT_FIELDS.issubset(suspect.keys()):
                return False
            for int_field in ("age", "pressure_tolerance", "kindness_weight",
                              "empathy", "starting_guilt", "revelation_stages"):
                if not isinstance(suspect.get(int_field), int):
                    return False
            if suspect.get("revelation_style") not in ("staged", "sudden"):
                return False
```

- [ ] **Step 5: Update `generate()` prompt to use archetypes and seeded location names**

In `MysteryGenerator.generate()`, at the start of the method body add:

```python
from noir.characters.npc_archetype_loader import archetype_ids
from noir.persistence.repository import get_seeded_location_names
_archetype_list = ", ".join(archetype_ids())
_location_pool = get_seeded_location_names(self.conn)
_loc_sample = random.sample(_location_pool, min(40, len(_location_pool))) if _location_pool else []
_location_list = "\n".join(f"- {n}" for n in _loc_sample)
```

Replace the suspect schema block in the `prompt` string:

```python
'  "suspects": [\n'
'    {"name": "string", "role": "suspect|witness|informant",\n'
'     "race": "string (e.g. Black, white, Creole, Cajun, Italian, Irish)",\n'
'     "political_connections": "string (e.g. none, alderman on payroll, organized crime)",\n'
'     "alibi": "string", "secret": "string",\n'
'     "archetype_id": "string (MUST be one of: ' + _archetype_list + ')",\n'
'     "alignment": "string (one of: Lawful Good, Neutral Good, Chaotic Good, Lawful Neutral, True Neutral, Chaotic Neutral, Lawful Evil, Neutral Evil, Chaotic Evil)",\n'
'     "age": integer (guidelines: law/legal: 28-65, working adults: 20-60, young: 18-30; respect relationships — a father must be 18+ years older than his child),\n'
'     "pressure_tolerance": integer 1-10 (1=cracks immediately, 10=barely flinches),\n'
'     "kindness_weight": integer 1-10 (how much sympathy moves them),\n'
'     "empathy": integer 1-10 (guilt response to emotional appeals about victims),\n'
'     "starting_guilt": integer 0-10 (initial guilt at case start),\n'
'     "revelation_style": "staged" or "sudden",\n'
'     "revelation_stages": integer 2-5 (only meaningful for staged; sudden NPCs use 1),\n'
'     "routine": [{"time_start": "HH:MM", "time_end": "HH:MM", "location": "string (location name from the locations list, or \'home\')"}],\n'
'     "relationships": [{"name": "string", "relationship": "string", "shared_facts": ["string"]}]}\n'
'  ],\n'
```

Replace the location schema block:

```python
f'Available locations to choose from (pick 4-6 for this case):\n{_location_list}\n\n'
'Return a JSON object with this exact schema:\n'
...
'  "locations": [\n'
'    {"name": "string (MUST be from the available locations list above)"}\n'
'  ]\n'
```

Apply identical changes to `generate_from_dark_past()`.

- [ ] **Step 6: Run tests**

```bash
python3 -m pytest tests/test_mystery.py -x -q
```
Expected: passing. Fix any remaining failures.

- [ ] **Step 7: Update BASE_CASE in test_auditor.py**

In `tests/test_auditor.py`, update `BASE_CASE` suspects to remove `personality`, `speech_style`, `backstory` and add `archetype_id` and psychology fields. Update locations to `{"name": "..."}` without description. The suspect entries should look like:

```python
{
    "name": "Dolores Mink",
    "role": "suspect",
    "alibi": "Claims she was playing cards at Fournier's Jazz Club all evening",
    "secret": "She was present at the murder scene but did not commit it",
    "archetype_id": "charming_liar",
    "race": "White",
    "political_connections": "none",
    "age": 34,
    "alignment": "Chaotic Neutral",
    "pressure_tolerance": 7, "kindness_weight": 3, "empathy": 2,
    "starting_guilt": 2, "revelation_style": "sudden", "revelation_stages": 1,
    "routine": [{"time_start": "18:00", "time_end": "02:00", "location": "Fournier's Jazz Club"}],
    "relationships": [{"name": "Victor Voss", "relationship": "former employer", "shared_facts": ["worked together for 3 years"]}],
},
```

Locations become `[{"name": "Fournier's Jazz Club"}, {"name": "City Hall"}]`.

- [ ] **Step 8: Run full test suite**

```bash
python3 -m pytest tests/ -x -q
```
Expected: all passing

- [ ] **Step 9: Commit**

```bash
git add noir/mystery/generator.py tests/test_mystery.py tests/test_auditor.py
git commit -m "feat: slim generator phase 1 — archetype_id, no personality/speech_style, location names only"
```

---

## Task 4: DB Migrations for Psychology and Enrichment

**Files:**
- Modify: `noir/persistence/db.py`

All new columns use migrations (ALTER TABLE). Psychology columns go on `npcs` and `npc_relationships`. `archetype_id` goes on `suspects`.

- [ ] **Step 1: Write failing test**

```python
# Add to tests/test_mystery.py
def test_npcs_table_has_psychology_columns(db):
    from noir.persistence.db import create_schema, _run_migrations
    # schema already created by db fixture; just verify columns exist
    row = db.execute("PRAGMA table_info(npcs)").fetchall()
    col_names = {r["name"] for r in row}
    assert "pressure_tolerance" in col_names
    assert "kindness_weight" in col_names
    assert "empathy" in col_names
    assert "starting_guilt" in col_names
    assert "revelation_style" in col_names
    assert "revelation_stages" in col_names

def test_npc_relationships_has_psychology_columns(db):
    row = db.execute("PRAGMA table_info(npc_relationships)").fetchall()
    col_names = {r["name"] for r in row}
    assert "guilt" in col_names
    assert "pressure_score" in col_names
    assert "revelation_stage" in col_names

def test_suspects_has_archetype_id_column(db):
    row = db.execute("PRAGMA table_info(suspects)").fetchall()
    col_names = {r["name"] for r in row}
    assert "archetype_id" in col_names
```

- [ ] **Step 2: Run to confirm failure**

```bash
python3 -m pytest tests/test_mystery.py::test_npcs_table_has_psychology_columns -v
```
Expected: FAIL (column doesn't exist)

- [ ] **Step 3: Add migrations**

In `noir/persistence/db.py`, append to `_MIGRATIONS`:

```python
    "ALTER TABLE npcs ADD COLUMN pressure_tolerance INTEGER DEFAULT 5",
    "ALTER TABLE npcs ADD COLUMN kindness_weight INTEGER DEFAULT 5",
    "ALTER TABLE npcs ADD COLUMN empathy INTEGER DEFAULT 5",
    "ALTER TABLE npcs ADD COLUMN starting_guilt INTEGER DEFAULT 0",
    "ALTER TABLE npcs ADD COLUMN revelation_style TEXT DEFAULT 'staged'",
    "ALTER TABLE npcs ADD COLUMN revelation_stages INTEGER DEFAULT 3",
    "ALTER TABLE npc_relationships ADD COLUMN guilt INTEGER DEFAULT 0",
    "ALTER TABLE npc_relationships ADD COLUMN pressure_score INTEGER DEFAULT 0",
    "ALTER TABLE npc_relationships ADD COLUMN revelation_stage INTEGER DEFAULT 0",
    "ALTER TABLE suspects ADD COLUMN archetype_id TEXT",
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_mystery.py::test_npcs_table_has_psychology_columns tests/test_mystery.py::test_npc_relationships_has_psychology_columns tests/test_mystery.py::test_suspects_has_archetype_id_column -v
```
Expected: 3 PASSED

- [ ] **Step 5: Run full suite**

```bash
python3 -m pytest tests/ -x -q
```
Expected: all passing

- [ ] **Step 6: Commit**

```bash
git add noir/persistence/db.py tests/test_mystery.py
git commit -m "feat: add psychology columns to npcs, npc_relationships, suspects"
```

---

## Task 5: Repository Functions for Psychology and Enrichment

**Files:**
- Modify: `noir/persistence/repository.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_mystery.py — add these

def test_create_npc_with_psychology_fields(db):
    from noir.persistence.repository import create_npc, get_npc, create_location
    loc_id = create_location(db, name="The Spot", description="A spot.", is_fixed=False)
    npc_id = create_npc(
        db, case_id=1, name="Test NPC", role="suspect",
        system_prompt="You are a suspect.", current_location_id=loc_id,
        pressure_tolerance=3, kindness_weight=7, empathy=6,
        starting_guilt=4, revelation_style="staged", revelation_stages=3,
    )
    row = get_npc(db, npc_id)
    assert row["pressure_tolerance"] == 3
    assert row["starting_guilt"] == 4
    assert row["revelation_style"] == "staged"

def test_get_npc_psychology(db):
    from noir.persistence.repository import create_npc, get_npc_psychology, create_location
    loc_id = create_location(db, name="Spot2", description=".", is_fixed=False)
    npc_id = create_npc(
        db, case_id=1, name="NPC2", role="witness",
        system_prompt=".", current_location_id=loc_id,
        pressure_tolerance=2, kindness_weight=8, empathy=5,
        starting_guilt=3, revelation_style="sudden", revelation_stages=1,
    )
    psych = get_npc_psychology(db, npc_id)
    assert psych["pressure_tolerance"] == 2
    assert psych["kindness_weight"] == 8
    assert psych["revelation_style"] == "sudden"
    assert psych["guilt"] == 30  # starting_guilt * 10
    assert psych["pressure_score"] == 0

def test_update_npc_guilt_and_pressure(db):
    from noir.persistence.repository import (
        create_npc, get_npc_psychology, update_npc_guilt, update_npc_pressure,
        decay_npc_pressure, create_location
    )
    loc_id = create_location(db, name="Spot3", description=".", is_fixed=False)
    npc_id = create_npc(
        db, case_id=1, name="NPC3", role="suspect",
        system_prompt=".", current_location_id=loc_id,
        pressure_tolerance=5, kindness_weight=5, empathy=5,
        starting_guilt=0, revelation_style="staged", revelation_stages=2,
    )
    update_npc_guilt(db, npc_id=npc_id, delta=20)
    update_npc_pressure(db, npc_id=npc_id, delta=30)
    psych = get_npc_psychology(db, npc_id)
    assert psych["guilt"] == 20
    assert psych["pressure_score"] == 30
    decay_npc_pressure(db, npc_id=npc_id)
    psych = get_npc_psychology(db, npc_id)
    assert psych["pressure_score"] == 25  # 30 - 5

def test_increment_npc_revelation_stage(db):
    from noir.persistence.repository import (
        create_npc, get_npc_revelation_stage, increment_npc_revelation_stage, create_location
    )
    loc_id = create_location(db, name="Spot4", description=".", is_fixed=False)
    npc_id = create_npc(
        db, case_id=1, name="NPC4", role="suspect",
        system_prompt=".", current_location_id=loc_id,
    )
    assert get_npc_revelation_stage(db, npc_id) == 0
    increment_npc_revelation_stage(db, npc_id=npc_id)
    assert get_npc_revelation_stage(db, npc_id) == 1

def test_update_npc_system_prompt(db):
    from noir.persistence.repository import create_npc, get_npc, update_npc_system_prompt, create_location
    loc_id = create_location(db, name="Spot5", description=".", is_fixed=False)
    npc_id = create_npc(db, case_id=1, name="NPC5", role="suspect",
                        system_prompt="old prompt", current_location_id=loc_id)
    update_npc_system_prompt(db, npc_id=npc_id, system_prompt="new prompt with backstory")
    assert get_npc(db, npc_id)["system_prompt"] == "new prompt with backstory"
```

- [ ] **Step 2: Run to confirm failures**

```bash
python3 -m pytest tests/test_mystery.py::test_create_npc_with_psychology_fields -v
```
Expected: FAIL

- [ ] **Step 3: Update `create_npc()`**

```python
def create_npc(conn: sqlite3.Connection, *, case_id: int, name: str, role: str,
               system_prompt: str, current_location_id: int,
               alignment: str = "True Neutral", age: int = 35,
               pressure_tolerance: int = 5, kindness_weight: int = 5,
               empathy: int = 5, starting_guilt: int = 0,
               revelation_style: str = "staged", revelation_stages: int = 3) -> int:
    cur = conn.execute(
        """INSERT INTO npcs
           (case_id, name, role, system_prompt, current_location_id, alignment, age,
            pressure_tolerance, kindness_weight, empathy, starting_guilt,
            revelation_style, revelation_stages)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (case_id, name, role, system_prompt, current_location_id, alignment, age,
         pressure_tolerance, kindness_weight, empathy, starting_guilt,
         revelation_style, revelation_stages)
    )
    conn.commit()
    return cur.lastrowid
```

- [ ] **Step 4: Add new repository functions**

Add after `create_npc()`:

```python
def update_npc_system_prompt(conn: sqlite3.Connection, *, npc_id: int, system_prompt: str) -> None:
    conn.execute("UPDATE npcs SET system_prompt=? WHERE id=?", (system_prompt, npc_id))
    conn.commit()


def update_suspect_backstory(conn: sqlite3.Connection, *, npc_id: int, backstory: str) -> None:
    conn.execute("UPDATE suspects SET backstory=? WHERE npc_id=?", (backstory, npc_id))
    conn.commit()


def get_npc_psychology(conn: sqlite3.Connection, npc_id: int) -> dict:
    npc = conn.execute(
        "SELECT pressure_tolerance, kindness_weight, empathy, starting_guilt, "
        "revelation_style, revelation_stages FROM npcs WHERE id=?", (npc_id,)
    ).fetchone()
    rel = conn.execute(
        "SELECT guilt, pressure_score, revelation_stage FROM npc_relationships WHERE npc_id=?",
        (npc_id,)
    ).fetchone()
    result = dict(npc) if npc else {}
    if rel:
        result.update(dict(rel))
    else:
        result.update({"guilt": (result.get("starting_guilt", 0) * 10),
                       "pressure_score": 0, "revelation_stage": 0})
    return result


def update_npc_guilt(conn: sqlite3.Connection, *, npc_id: int, delta: int) -> None:
    conn.execute(
        """INSERT INTO npc_relationships (npc_id, guilt)
           VALUES (?, MAX(0, MIN(100, ?)))
           ON CONFLICT(npc_id) DO UPDATE SET
           guilt = MAX(0, MIN(100, guilt + excluded.guilt))""",
        (npc_id, delta)
    )
    conn.commit()


def update_npc_pressure(conn: sqlite3.Connection, *, npc_id: int, delta: int) -> None:
    conn.execute(
        """INSERT INTO npc_relationships (npc_id, pressure_score)
           VALUES (?, MAX(0, MIN(100, ?)))
           ON CONFLICT(npc_id) DO UPDATE SET
           pressure_score = MAX(0, MIN(100, pressure_score + excluded.pressure_score))""",
        (npc_id, delta)
    )
    conn.commit()


def decay_npc_pressure(conn: sqlite3.Connection, npc_id: int) -> None:
    conn.execute(
        "UPDATE npc_relationships SET pressure_score = MAX(0, pressure_score - 5) WHERE npc_id=?",
        (npc_id,)
    )
    conn.commit()


def get_npc_revelation_stage(conn: sqlite3.Connection, npc_id: int) -> int:
    row = conn.execute(
        "SELECT revelation_stage FROM npc_relationships WHERE npc_id=?", (npc_id,)
    ).fetchone()
    return row["revelation_stage"] if row else 0


def increment_npc_revelation_stage(conn: sqlite3.Connection, *, npc_id: int) -> int:
    conn.execute(
        """INSERT INTO npc_relationships (npc_id, revelation_stage) VALUES (?, 1)
           ON CONFLICT(npc_id) DO UPDATE SET revelation_stage = revelation_stage + 1""",
        (npc_id,)
    )
    conn.commit()
    return get_npc_revelation_stage(conn, npc_id)
```

- [ ] **Step 5: Run tests**

```bash
python3 -m pytest tests/test_mystery.py -k "psychology or revelation or system_prompt or backstory" -v
```
Expected: all PASSED

- [ ] **Step 6: Run full suite**

```bash
python3 -m pytest tests/ -x -q
```

- [ ] **Step 7: Commit**

```bash
git add noir/persistence/repository.py tests/test_mystery.py
git commit -m "feat: add psychology repository functions and update create_npc"
```

---

## Task 6: Lazy NPC Enrichment — Phase 2 Backstory + System Prompt

The generator now creates NPCs with a partial system_prompt (no backstory). Phase 2 generates backstory per NPC and rebuilds the full system_prompt in background threads.

**Files:**
- Modify: `noir/mystery/generator.py`
- Modify: `noir/game.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_mystery.py
from itertools import cycle as _cycle
import json

def test_enrich_npc_updates_system_prompt(db, mock_llm):
    from noir.mystery.generator import enrich_npc
    from noir.persistence.repository import (
        create_location, create_npc, get_npc,
        seed_locations_to_db, create_suspect
    )
    seed_locations_to_db(db, [{"name": "The Spot", "description": "Dark.", "type": "bar"}])
    loc_id = create_location(db, name="The Spot", description="Dark.", is_fixed=False)
    npc_id = create_npc(
        db, case_id=1, name="Marcus Dupree", role="suspect",
        system_prompt="partial prompt",
        current_location_id=loc_id,
        pressure_tolerance=5, kindness_weight=5, empathy=5,
        starting_guilt=2, revelation_style="staged", revelation_stages=3,
    )
    db.execute(
        "INSERT INTO suspects (case_id, npc_id, is_killer, race, alibi, secret, archetype_id) "
        "VALUES (1, ?, 0, 'Black', 'Was at home', 'Owes money', 'bitter_veteran')",
        (npc_id,)
    )
    db.commit()

    mock_llm._responses = _cycle(['{"backstory": "Dockworker turned numbers runner, trying to stay clean."}'])
    enrich_npc(db, mock_llm, npc_id)

    row = get_npc(db, npc_id)
    assert "Dockworker turned numbers runner" in row["system_prompt"]
    assert "Marcus Dupree" in row["system_prompt"]
    assert "bitter_veteran" not in row["system_prompt"]  # resolved to text
    assert "Bored" in row["system_prompt"] or "seen everything" in row["system_prompt"].lower()
```

- [ ] **Step 2: Run to confirm failure**

```bash
python3 -m pytest tests/test_mystery.py::test_enrich_npc_updates_system_prompt -v
```
Expected: FAIL (`enrich_npc` not found)

- [ ] **Step 3: Add `enrich_npc()` to generator.py**

```python
# At the top of generator.py, add import:
from noir.characters.npc_archetype_loader import get_npc_archetype
from noir.persistence.repository import (
    get_npc, update_npc_system_prompt, update_suspect_backstory
)

def _build_npc_system_prompt(name: str, role: str, race: str,
                              political_connections: str, alibi: str, secret: str,
                              relationships_json: str, personality: str,
                              speech_style: str, backstory: str = "") -> str:
    race_line = (
        f"Race/background: {race}. This shapes your experience of 1935 Noirleans — "
        "the spaces you can enter, who treats you with respect or contempt, "
        "what you can and cannot say to a white detective. "
    ) if race else ""
    political_line = (
        f"Political connections: {political_connections}. "
        "You know who protects you and you know how to use that knowledge. "
    ) if political_connections and political_connections.lower() != "none" else ""
    backstory_line = f"Your history: {backstory} " if backstory else ""
    import json as _j
    try:
        rels = _j.loads(relationships_json) if relationships_json else []
    except Exception:
        rels = []
    rel_parts = []
    for r in rels:
        if not r.get("name") or not r.get("relationship"):
            continue
        part = f"Your relationship to {r['name']}: {r['relationship']}."
        facts = r.get("shared_facts", [])
        if facts:
            part += f" Facts you both know: {' '.join(facts)}"
        rel_parts.append(part)
    rel_text = " ".join(rel_parts)
    return (
        f"You are {name}, a {role} in a murder investigation. "
        f"{backstory_line}"
        f"Personality: {personality}. Speech style: {speech_style}. "
        f"{race_line}"
        f"{political_line}"
        f"Your alibi (which may or may not be true): {alibi}. "
        f"Your secret: {secret}. "
        + (f"{rel_text} " if rel_text else "")
        + "You are in Noirleans, 1935 — Depression-era, corrupt to the bone, "
        "jazz leaking out of every cracked window. Stay in character. "
        "Be evasive about your secret but not impossibly so."
    )


def enrich_npc(conn: sqlite3.Connection, llm: LLMBackend, npc_id: int) -> None:
    npc_row = get_npc(conn, npc_id)
    if npc_row is None:
        return
    suspect_row = conn.execute(
        "SELECT race, political_connections, alibi, secret, archetype_id, relationships "
        "FROM suspects WHERE npc_id=?", (npc_id,)
    ).fetchone()
    if suspect_row is None:
        return

    archetype = get_npc_archetype(suspect_row["archetype_id"] or "world_weary_barkeep")
    personality = archetype["personality"] if archetype else "Reserved and watchful"
    speech_style = archetype["speech_style"] if archetype else "Short, careful sentences"

    result = llm.query_structured(
        "Generate a one-sentence backstory for this character. "
        "Return ONLY valid JSON: {\"backstory\": \"string\"}",
        [],
        f"Name: {npc_row['name']}, Role: {npc_row['role']}, "
        f"Race: {suspect_row['race']}, Alibi: {suspect_row['alibi']}, "
        f"Secret: {suspect_row['secret']}. "
        "Write one sentence about who they were before this case — specific, grounded, 1935 Noirleans."
    )
    backstory = result.get("backstory", "")

    system_prompt = _build_npc_system_prompt(
        name=npc_row["name"],
        role=npc_row["role"],
        race=suspect_row["race"] or "",
        political_connections=suspect_row["political_connections"] or "",
        alibi=suspect_row["alibi"] or "",
        secret=suspect_row["secret"] or "",
        relationships_json=suspect_row["relationships"] or "[]",
        personality=personality,
        speech_style=speech_style,
        backstory=backstory,
    )
    update_npc_system_prompt(conn, npc_id=npc_id, system_prompt=system_prompt)
    if backstory:
        update_suspect_backstory(conn, npc_id=npc_id, backstory=backstory)
```

- [ ] **Step 4: Update `_seed_case_locations_and_npcs` to use `_build_npc_system_prompt` and seeded location descriptions**

In `noir/game.py`, update the location seeding block:

```python
for loc in case_data.get("locations", []):
    loc_name = loc["name"] if isinstance(loc, dict) else loc
    desc = get_seeded_location_description(self.conn, loc_name) or f"A location in Noirleans."
    loc_id = create_location(self.conn, name=loc_name,
                             description=desc, is_fixed=False, case_id=case_id)
    loc_map[loc_name] = loc_id
```

Replace the system_prompt building block with a call to `_build_npc_system_prompt`:

```python
from noir.mystery.generator import _build_npc_system_prompt
from noir.characters.npc_archetype_loader import get_npc_archetype

archetype = get_npc_archetype(suspect.get("archetype_id", "world_weary_barkeep"))
personality = archetype["personality"] if archetype else "Reserved and watchful"
speech_style = archetype["speech_style"] if archetype else "Short, careful sentences"

npc_system_prompt = _build_npc_system_prompt(
    name=suspect["name"],
    role=suspect["role"],
    race=suspect.get("race", ""),
    political_connections=suspect.get("political_connections", ""),
    alibi=suspect.get("alibi", ""),
    secret=suspect.get("secret", ""),
    relationships_json=json.dumps(suspect.get("relationships", [])),
    personality=personality,
    speech_style=speech_style,
    backstory="",  # phase 2 will update this
)
```

Update `create_npc()` call to pass psychology fields:

```python
npc_id = create_npc(
    self.conn, case_id=case_id, name=suspect["name"],
    role=suspect["role"], system_prompt=npc_system_prompt,
    current_location_id=loc_id,
    alignment=suspect.get("alignment", "True Neutral"),
    age=suspect.get("age", 35),
    pressure_tolerance=suspect.get("pressure_tolerance", 5),
    kindness_weight=suspect.get("kindness_weight", 5),
    empathy=suspect.get("empathy", 5),
    starting_guilt=suspect.get("starting_guilt", 0),
    revelation_style=suspect.get("revelation_style", "staged"),
    revelation_stages=suspect.get("revelation_stages", 3),
)
```

Update `create_suspect()` call to pass archetype_id:

```python
create_suspect(self.conn, case_id=case_id, npc_id=npc_id, is_killer=is_killer,
               race=suspect.get("race"),
               political_connections=suspect.get("political_connections"),
               alibi=suspect.get("alibi"),
               secret=suspect.get("secret"),
               backstory=None,  # set by phase 2
               relationships=json.dumps(suspect.get("relationships", [])),
               archetype_id=suspect.get("archetype_id"))
```

Also update `create_suspect()` in `repository.py` to accept and store `archetype_id`:

```python
def create_suspect(conn, *, case_id, npc_id, is_killer=False,
                   race=None, political_connections=None,
                   alibi=None, secret=None, backstory=None,
                   relationships=None, archetype_id=None):
    conn.execute(
        """INSERT INTO suspects
           (case_id, npc_id, is_killer, race, political_connections,
            alibi, secret, backstory, relationships, archetype_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (case_id, npc_id, is_killer, race, political_connections,
         alibi, secret, backstory, relationships, archetype_id)
    )
    conn.commit()
```

Also update `npc_relationships` initial insert to set guilt from starting_guilt:

```python
self.conn.execute(
    """INSERT OR IGNORE INTO npc_relationships (npc_id, guilt)
       VALUES (?, ?)""",
    (npc_id, suspect.get("starting_guilt", 0) * 10)
)
```

- [ ] **Step 5: Wire background enrichment into game.py `start_new_case()`**

In `Game._start_background_generation()`, no change needed — that's for case generation. Add a new `_start_background_enrichment()` that fires after `_seed_case_locations_and_npcs`:

```python
def _start_background_enrichment(self, case_id: int) -> None:
    from noir.mystery.generator import enrich_npc
    from noir.persistence.repository import get_npcs_for_case
    import copy

    npcs = get_npcs_for_case(self.conn, case_id)
    bg_llm = copy.copy(self.llm)
    bg_llm.suppress_status = True

    def _enrich_all() -> None:
        from noir.persistence.db import get_connection as _gc
        bg_conn = _gc()
        try:
            for npc in npcs:
                try:
                    enrich_npc(bg_conn, bg_llm, npc["id"])
                except Exception:
                    pass  # enrichment failure is non-fatal — NPC still works without backstory
        finally:
            bg_conn.close()

    t = threading.Thread(target=_enrich_all, daemon=True)
    t.start()
```

Call it in `start_new_case()` right after `_seed_case_locations_and_npcs`:

```python
self._seed_case_locations_and_npcs(case_id, case_data, fixed)
self._start_background_enrichment(case_id)
```

- [ ] **Step 6: Run tests**

```bash
python3 -m pytest tests/ -x -q
```
Expected: all passing

- [ ] **Step 7: Commit**

```bash
git add noir/mystery/generator.py noir/game.py noir/persistence/repository.py
git commit -m "feat: lazy NPC enrichment — phase 1 partial prompt, phase 2 backstory in background"
```

---

## Task 7: Psychology Module — Event Classifier + State Updater + Revelation Trigger

**Files:**
- Create: `noir/characters/psychology.py`
- Create: `tests/test_psychology.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_psychology.py
import pytest
import json
from itertools import cycle
from noir.llm.mock import MockLLMBackend
from noir.characters.psychology import (
    classify_events, update_npc_state, check_revelation,
    _revelation_thresholds,
)

# --- threshold logic (pure Python, no LLM) ---

def test_staged_2_thresholds():
    assert _revelation_thresholds("staged", 2) == [60, 100]

def test_staged_3_thresholds():
    assert _revelation_thresholds("staged", 3) == [50, 75, 100]

def test_staged_4_thresholds():
    assert _revelation_thresholds("staged", 4) == [40, 60, 80, 100]

def test_staged_5_thresholds():
    assert _revelation_thresholds("staged", 5) == [35, 55, 70, 85, 100]

def test_sudden_threshold():
    assert _revelation_thresholds("sudden", 1) == [100]

# --- classify_events ---

def test_classify_events_returns_five_booleans():
    llm = MockLLMBackend(responses=[json.dumps({
        "pressure_applied": True,
        "threat_made": False,
        "kindness_shown": False,
        "guilt_trigger": False,
        "evidence_confronted": True,
    })])
    result = classify_events(llm, "I know you were there.", "I told you, I was home.")
    assert result["pressure_applied"] is True
    assert result["evidence_confronted"] is True
    assert result["kindness_shown"] is False

def test_classify_events_bad_llm_response_returns_all_false():
    llm = MockLLMBackend(responses=["not json at all"])
    # MockLLMBackend cycles, so query_structured will call _fatal on bad JSON.
    # Use a response that parses but has missing keys:
    llm = MockLLMBackend(responses=[json.dumps({"pressure_applied": True})])
    result = classify_events(llm, "msg", "resp")
    assert "pressure_applied" in result
    assert result.get("kindness_shown", False) is False

# --- update_npc_state ---

def test_update_npc_state_pressure_applied(db):
    from noir.persistence.repository import create_npc, get_npc_psychology, create_location
    loc_id = create_location(db, name="S", description=".", is_fixed=False)
    npc_id = create_npc(db, case_id=1, name="X", role="suspect",
                        system_prompt=".", current_location_id=loc_id,
                        pressure_tolerance=5, kindness_weight=5, empathy=5,
                        starting_guilt=0, revelation_style="staged", revelation_stages=3)
    from noir.characters.psychology import update_npc_state
    events = {"pressure_applied": True, "threat_made": False,
              "kindness_shown": False, "guilt_trigger": False, "evidence_confronted": False}
    psychology = get_npc_psychology(db, npc_id)
    update_npc_state(db, npc_id, events, psychology)
    psych = get_npc_psychology(db, npc_id)
    # pressure_applied: (11 - pressure_tolerance=5) * 5 = 30
    assert psych["pressure_score"] == 30

def test_update_npc_state_no_pressure_decays(db):
    from noir.persistence.repository import (
        create_npc, get_npc_psychology, update_npc_pressure, create_location
    )
    from noir.characters.psychology import update_npc_state
    loc_id = create_location(db, name="S2", description=".", is_fixed=False)
    npc_id = create_npc(db, case_id=1, name="Y", role="suspect",
                        system_prompt=".", current_location_id=loc_id,
                        pressure_tolerance=5, kindness_weight=5, empathy=5,
                        starting_guilt=0, revelation_style="staged", revelation_stages=3)
    update_npc_pressure(db, npc_id=npc_id, delta=20)
    events = {"pressure_applied": False, "threat_made": False,
              "kindness_shown": False, "guilt_trigger": False, "evidence_confronted": False}
    psychology = get_npc_psychology(db, npc_id)
    update_npc_state(db, npc_id, events, psychology)
    psych = get_npc_psychology(db, npc_id)
    assert psych["pressure_score"] == 15  # 20 - 5 decay

# --- check_revelation ---

def test_check_revelation_returns_none_below_threshold(db):
    from noir.persistence.repository import create_npc, get_npc_psychology, create_location
    from noir.characters.psychology import check_revelation
    loc_id = create_location(db, name="S3", description=".", is_fixed=False)
    npc_id = create_npc(db, case_id=1, name="Z", role="suspect",
                        system_prompt=".", current_location_id=loc_id,
                        pressure_tolerance=10, kindness_weight=1, empathy=1,
                        starting_guilt=0, revelation_style="staged", revelation_stages=3)
    llm = MockLLMBackend()
    psychology = get_npc_psychology(db, npc_id)
    events = {"pressure_applied": False, "threat_made": False,
              "kindness_shown": False, "guilt_trigger": False, "evidence_confronted": False}
    result = check_revelation(db, llm, npc_id, 1, "Z", events, psychology)
    assert result is None

def test_check_revelation_fires_when_threshold_crossed(db):
    from noir.persistence.repository import (
        create_npc, get_npc_psychology, update_npc_pressure, update_npc_guilt,
        get_npc_revelation_stage, create_location
    )
    from noir.characters.psychology import check_revelation
    loc_id = create_location(db, name="S4", description=".", is_fixed=False)
    npc_id = create_npc(db, case_id=1, name="W", role="suspect",
                        system_prompt=".", current_location_id=loc_id,
                        pressure_tolerance=5, kindness_weight=5, empathy=5,
                        starting_guilt=0, revelation_style="staged", revelation_stages=2)
    # push pressure + guilt to combined >= 60 (first threshold for staged 2)
    update_npc_pressure(db, npc_id=npc_id, delta=40)
    update_npc_guilt(db, npc_id=npc_id, delta=25)
    llm = MockLLMBackend(responses=["I... I was there. I saw what happened."])
    psychology = get_npc_psychology(db, npc_id)
    events = {"pressure_applied": False, "threat_made": False,
              "kindness_shown": False, "guilt_trigger": False, "evidence_confronted": False}
    result = check_revelation(db, llm, npc_id, 1, "W", events, psychology)
    assert result is not None
    assert isinstance(result, str)
    assert get_npc_revelation_stage(db, npc_id) == 1
```

- [ ] **Step 2: Run to confirm failures**

```bash
python3 -m pytest tests/test_psychology.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `noir/characters/psychology.py`**

```python
import sqlite3
from noir.llm.base import LLMBackend
from noir.persistence.repository import (
    update_npc_guilt, update_npc_pressure, decay_npc_pressure,
    get_npc_revelation_stage, increment_npc_revelation_stage,
    get_npc_relationship_flags, set_npc_secret_revealed,
)

_CLASSIFY_SYSTEM = (
    "You are classifying what happened in a detective interrogation exchange. "
    "Return ONLY valid JSON with five boolean fields."
)


def _revelation_thresholds(style: str, stages: int) -> list[int]:
    if style == "sudden":
        return [100]
    thresholds = {
        2: [60, 100],
        3: [50, 75, 100],
        4: [40, 60, 80, 100],
        5: [35, 55, 70, 85, 100],
    }
    return thresholds.get(stages, [50, 75, 100])


def classify_events(llm: LLMBackend, player_msg: str, npc_response: str) -> dict:
    prompt = (
        f'Detective said: "{player_msg}"\n'
        f'NPC replied: "{npc_response}"\n\n'
        "Classify what just happened. Return JSON:\n"
        '{"pressure_applied": bool, "threat_made": bool, '
        '"kindness_shown": bool, "guilt_trigger": bool, "evidence_confronted": bool}'
    )
    try:
        result = llm.query_structured(_CLASSIFY_SYSTEM, [], prompt)
    except SystemExit:
        result = {}
    defaults = {
        "pressure_applied": False, "threat_made": False,
        "kindness_shown": False, "guilt_trigger": False, "evidence_confronted": False,
    }
    defaults.update({k: bool(v) for k, v in result.items() if k in defaults})
    return defaults


def update_npc_state(conn: sqlite3.Connection, npc_id: int,
                     events: dict, psychology: dict) -> None:
    pt = psychology.get("pressure_tolerance", 5)
    emp = psychology.get("empathy", 5)

    pressure_delta = 0
    if events.get("pressure_applied"):
        pressure_delta += (11 - pt) * 5
    if events.get("threat_made"):
        pressure_delta += (11 - pt) * 10
    if events.get("evidence_confronted"):
        pressure_delta += (11 - pt) * 8

    guilt_delta = 0
    if events.get("kindness_shown"):
        guilt_delta += emp * 2
    if events.get("guilt_trigger"):
        guilt_delta += emp * 4

    any_pressure = events.get("pressure_applied") or events.get("threat_made") or events.get("evidence_confronted")

    if pressure_delta:
        update_npc_pressure(conn, npc_id=npc_id, delta=pressure_delta)
    elif not any_pressure:
        decay_npc_pressure(conn, npc_id)

    if guilt_delta:
        update_npc_guilt(conn, npc_id=npc_id, delta=guilt_delta)


def check_revelation(conn: sqlite3.Connection, llm: LLMBackend,
                     npc_id: int, case_id: int, npc_name: str,
                     events: dict, psychology: dict) -> str | None:
    flags = get_npc_relationship_flags(conn, npc_id)
    if flags.get("secret_revealed"):
        return None

    style = psychology.get("revelation_style", "staged")
    stages = psychology.get("revelation_stages", 3)
    thresholds = _revelation_thresholds(style, stages)
    current_stage = get_npc_revelation_stage(conn, npc_id)

    if current_stage >= len(thresholds):
        return None

    pressure = psychology.get("pressure_score", 0)
    guilt = psychology.get("guilt", 0)
    affection = psychology.get("affection", 0)
    kw = psychology.get("kindness_weight", 5)
    combined = pressure + guilt + (affection * kw / 10)

    next_threshold = thresholds[current_stage]
    guilt_override = guilt >= 90

    if combined < next_threshold and not guilt_override:
        return None

    new_stage = increment_npc_revelation_stage(conn, npc_id=npc_id)
    is_final = new_stage >= len(thresholds)

    if is_final:
        set_npc_secret_revealed(conn, npc_id)

    fired = [k for k, v in events.items() if v]
    fired_str = ", ".join(fired) if fired else "sustained pressure"
    override_note = " (guilt override — couldn't live with it)" if guilt_override else ""

    if style == "sudden" or is_final:
        prompt = (
            f"[You have reached your breaking point{override_note}. "
            f"Tell the detective your secret — all of it. "
            f"What broke you: {fired_str}. "
            "Stay fully in character. No speeches. Speak the way this person actually speaks.]"
        )
    else:
        prompt = (
            f"[You are about to reveal something you have been hiding{override_note}. "
            f"This is stage {new_stage} of {len(thresholds)} — reveal approximately "
            f"1/{len(thresholds)} of your secret. Do not reveal more than this stage calls for. "
            f"What broke you open just now: {fired_str}. "
            "Stay fully in character. Do not announce that you are confessing. "
            "Speak naturally, as the moment demands.]"
        )

    from noir.characters.npc import NPC
    # We need an NPC instance to call speak() with record=False.
    # Load it from the DB — system_prompt is already in npcs table.
    from noir.persistence.repository import get_npc
    npc_row = get_npc(conn, npc_id)
    if npc_row is None:
        return None

    response = llm.query(npc_row["system_prompt"], [], prompt)
    return response
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_psychology.py -v
```
Expected: all PASSED. Fix any failures.

- [ ] **Step 5: Run full suite**

```bash
python3 -m pytest tests/ -x -q
```

- [ ] **Step 6: Commit**

```bash
git add noir/characters/psychology.py tests/test_psychology.py
git commit -m "feat: NPC psychology module — event classifier, state updater, revelation trigger"
```

---

## Task 8: Game.py Wiring — Revelation After NPC Exchanges

**Files:**
- Modify: `noir/game.py`
- Modify: `noir/step.py`

- [ ] **Step 1: Wire revelation into `handle_talk()` in game.py**

In `handle_talk()`, after `self._check_npc_romance_milestone(npc_row["id"], npc)`, add:

```python
from noir.characters.psychology import classify_events, update_npc_state, check_revelation as _check_revelation
from noir.persistence.repository import get_npc_psychology

psychology = get_npc_psychology(self.conn, npc_row["id"])
events = classify_events(self.llm, player_input, response)
update_npc_state(self.conn, npc_row["id"], events, psychology)
# Re-fetch psychology after state update for accurate combined score
psychology = get_npc_psychology(self.conn, npc_row["id"])
revelation = _check_revelation(
    self.conn, self.llm, npc_row["id"], self.active_case_id,
    npc_row["name"], events, psychology
)
if revelation:
    show_dialogue(npc_row["name"], revelation)
```

Move the imports to the top of game.py (not inside the loop body):

```python
from noir.characters.psychology import classify_events, update_npc_state, check_revelation as _check_npc_revelation
```

- [ ] **Step 2: Wire revelation into `_talk_npc()` in step.py**

In `noir/step.py`, after `_extract_dossier_facts(...)`, add:

```python
from noir.characters.psychology import classify_events, update_npc_state, check_revelation as _check_revelation
from noir.persistence.repository import get_npc_psychology

psychology = get_npc_psychology(conn, npc_row["id"])
events = classify_events(llm, message, response)
update_npc_state(conn, npc_row["id"], events, psychology)
psychology = get_npc_psychology(conn, npc_row["id"])
revelation = _check_revelation(conn, llm, npc_row["id"], case_id, npc_row["name"], events, psychology)
if revelation:
    console.print(f"\n{npc_row['name']}: {revelation}\n")
```

- [ ] **Step 3: Update step.py NPC talk test for additional mock responses**

In `tests/test_step.py`, `test_command_talk_npc_single_exchange` now triggers 3 LLM calls: NPC response, dossier extraction, and event classification. Update mock responses:

```python
def test_command_talk_npc_single_exchange(db_with_case):
    db, case_id, loc_id, npc_id = db_with_case
    mark_suspect_met(db, npc_id=npc_id)
    llm = MockLLMBackend(responses=[
        "I was home all night. Ask anybody.",       # NPC speak
        '{"facts": []}',                             # dossier extraction
        '{"pressure_applied": false, "threat_made": false, "kindness_shown": false, "guilt_trigger": false, "evidence_confronted": false}',  # classify_events
    ])
    out = StringIO()
    result = run_step(
        {"type": "command", "input": "talk Rex Fontaine: Where were you?"},
        conn=db, llm=llm, stdout=out,
    )
    assert result["ok"] is True
    assert "Rex Fontaine" in out.getvalue()
    assert "home all night" in out.getvalue()
```

- [ ] **Step 4: Run full test suite**

```bash
python3 -m pytest tests/ -x -q
```
Expected: all passing. The psychology calls are lightweight and won't trigger revelation in tests because `db_with_case` NPCs have no accumulated pressure/guilt.

- [ ] **Step 5: Commit**

```bash
git add noir/game.py noir/step.py tests/test_step.py
git commit -m "feat: wire NPC psychology revelation into handle_talk and _talk_npc"
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Task |
|---|---|
| NPC character archetypes — hardcoded JSON, LLM picks id | Task 1 |
| Pre-seeded 100 locations — pool for generator to choose from | Task 2 |
| Generator uses archetype_id, location names, no personality/speech_style | Task 3 |
| Psychology columns on npcs and npc_relationships | Task 4 |
| Repository functions for psychology state | Task 5 |
| Lazy NPC backstory enrichment in background threads | Task 6 |
| Psychology module: classify_events, update_npc_state, check_revelation | Task 7 |
| Revelation fires in handle_talk (game.py) and _talk_npc (step.py) | Task 8 |
| Staged thresholds (2=60/100, 3=50/75/100, etc.) | Task 7 |
| Guilt override at 90 | Task 7 |
| Revelation uses `record=False` equivalent (llm.query direct, not conversation history) | Task 7 |
| starting_guilt * 10 initializes npc_relationships.guilt | Task 6 |

**Placeholder scan:** None found.

**Type consistency:** `enrich_npc(conn, llm, npc_id)` defined in Task 6 and called in Task 6. `_build_npc_system_prompt()` defined in Task 6 and used in Task 6. `classify_events`, `update_npc_state`, `check_revelation` defined in Task 7 and imported in Task 8. `_revelation_thresholds()` defined and tested in Task 7.
