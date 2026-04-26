# Player Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a player inventory system with purchasable items, item requirements on jobs, and action-based consumable usage.

**Architecture:** Two new DB tables (`item_definitions`, `player_items`) added via `_MIGRATIONS` and seeded at startup from a static catalog in `noir/items.py`. Item requirements live in `noir/jobs/archetypes.json`. Purchases happen through conversation with Clarence Dufour at "Treme Pawn & Loan". Actions are triggered by `/use [item] [action]` or embedding-matched natural language.

**Tech Stack:** SQLite (existing migrations pattern), sentence-transformers via `noir.memory` (optional), Rich terminal UI (existing)

---

## File Map

| File | New/Modify | Responsibility |
|---|---|---|
| `noir/items.py` | **New** | Item catalog, `seed_item_definitions`, `ACTION_PHRASES`, `detect_item_action`, `get_job_required_items`, `check_job_requirements` |
| `noir/persistence/db.py` | Modify | 2 new migrations, call `seed_item_definitions` in `create_schema` |
| `noir/persistence/repository.py` | Modify | `get_player_items`, `add_player_item`, `use_item` |
| `noir/jobs/archetypes.json` | Modify | `required_items` on 4 archetypes |
| `noir/organizations.py` | Modify | Add Treme Pawn & Loan to `SEEDED_ORGANIZATIONS` |
| `noir/game.py` | Modify | `FIXED_LOCATIONS` + `FIXED_LOCATION_NPCS` (Dufour), `/items`, `/use`, arrival nudge, `/done` check, purchase detection, display updates |
| `noir/display.py` | Modify | `show_items()` panel |
| `tests/test_items.py` | **New** | Tests for seeding, repository functions, action detection, requirement checks |

---

### Task 1: `noir/items.py` — item catalog, seeding, and DB migrations

**Files:**
- Create: `noir/items.py`
- Modify: `noir/persistence/db.py`
- Test: `tests/test_items.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_items.py
import json
import pytest
import sqlite3
from noir.persistence.db import create_schema
from noir.persistence.repository import create_player


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    create_player(conn)
    yield conn
    conn.close()


def test_item_definitions_seeded(db):
    rows = db.execute("SELECT slug FROM item_definitions ORDER BY slug").fetchall()
    slugs = [r["slug"] for r in rows]
    assert "camera" in slugs
    assert "film" in slugs
    assert "revolver_38" in slugs
    assert "ammo_38" in slugs
    assert "lockpicks" in slugs
    assert "binoculars" in slugs
    assert "bribe_envelope" in slugs
    assert "disguise_kit" in slugs


def test_camera_requires_film(db):
    row = db.execute("SELECT * FROM item_definitions WHERE slug='camera'").fetchone()
    assert row["requires_slug"] == "film"
    assert row["consumable"] == 0
    actions = json.loads(row["actions"])
    assert "photograph" in actions
    assert actions["photograph"]["consumes"] == "film"


def test_film_is_consumable(db):
    row = db.execute("SELECT * FROM item_definitions WHERE slug='film'").fetchone()
    assert row["consumable"] == 1
    assert row["requires_slug"] is None


def test_ammo_price_is_4(db):
    row = db.execute("SELECT price FROM item_definitions WHERE slug='ammo_38'").fetchone()
    assert row["price"] == 4


def test_revolver_requires_ammo(db):
    row = db.execute("SELECT * FROM item_definitions WHERE slug='revolver_38'").fetchone()
    assert row["requires_slug"] == "ammo_38"
    actions = json.loads(row["actions"])
    assert "brandish" in actions
    assert "shoot" in actions
    assert actions["shoot"]["consumes"] == "ammo_38"


def test_player_items_table_exists(db):
    db.execute("SELECT * FROM player_items LIMIT 1")  # no error = table exists


def test_get_job_required_items_cheating_spouse():
    from noir.items import get_job_required_items
    reqs = get_job_required_items("cheating_spouse")
    assert len(reqs) == 1
    assert reqs[0]["slug"] == "camera"
    assert reqs[0]["needs_consumable"] is True


def test_get_job_required_items_unknown_returns_empty():
    from noir.items import get_job_required_items
    assert get_job_required_items("nonexistent_slug") == []


def test_detect_item_action_keyword_fallback(db):
    from noir.items import detect_item_action
    inventory = {"camera": 1, "film": 2}
    result = detect_item_action("I take a picture of them", inventory, db)
    assert result == ("camera", "photograph")


def test_detect_item_action_no_match(db):
    from noir.items import detect_item_action
    inventory = {"camera": 1}
    result = detect_item_action("I wave hello", inventory, db)
    assert result is None


def test_detect_item_action_not_owned(db):
    from noir.items import detect_item_action
    inventory = {}  # no camera
    result = detect_item_action("I take a picture", inventory, db)
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_items.py -v
```
Expected: multiple FAIL / ImportError — `noir.items` doesn't exist yet.

- [ ] **Step 3: Create `noir/items.py`**

```python
import json
import sqlite3
from pathlib import Path

ITEM_CATALOG = [
    {
        "slug": "camera",
        "name": "Camera",
        "description": "For documentation work.",
        "price": 12,
        "consumable": 0,
        "requires_slug": "film",
        "actions": {"photograph": {"consumes": "film"}},
    },
    {
        "slug": "film",
        "name": "Roll of Film",
        "description": "One roll per job.",
        "price": 2,
        "consumable": 1,
        "requires_slug": None,
        "actions": {},
    },
    {
        "slug": "lockpicks",
        "name": "Lockpick Set",
        "description": "Opens doors that would rather stay closed.",
        "price": 8,
        "consumable": 0,
        "requires_slug": None,
        "actions": {"pick": {}},
    },
    {
        "slug": "binoculars",
        "name": "Binoculars",
        "description": "Distance is perspective.",
        "price": 15,
        "consumable": 0,
        "requires_slug": None,
        "actions": {"observe": {}},
    },
    {
        "slug": "revolver_38",
        "name": ".38 Revolver",
        "description": "Loaded or not, it makes a point.",
        "price": 35,
        "consumable": 0,
        "requires_slug": "ammo_38",
        "actions": {"brandish": {}, "shoot": {"consumes": "ammo_38"}},
    },
    {
        "slug": "ammo_38",
        "name": ".38 Ammunition",
        "description": "Keep it dry.",
        "price": 4,
        "consumable": 1,
        "requires_slug": None,
        "actions": {},
    },
    {
        "slug": "bribe_envelope",
        "name": "Bribe Envelope",
        "description": "Already prepared.",
        "price": 2,
        "consumable": 1,
        "requires_slug": None,
        "actions": {"bribe": {"consumes": "bribe_envelope"}},
    },
    {
        "slug": "disguise_kit",
        "name": "Disguise Kit",
        "description": "Become someone else.",
        "price": 18,
        "consumable": 0,
        "requires_slug": None,
        "actions": {"disguise": {}},
    },
]

_SLUG_TO_ITEM: dict[str, dict] = {item["slug"]: item for item in ITEM_CATALOG}

_JOBS_ARCHETYPES_PATH = Path(__file__).parent / "jobs" / "archetypes.json"

ACTION_PHRASES: dict[tuple[str, str], list[str]] = {
    ("camera", "photograph"): [
        "I photograph them", "take a picture", "snap a photo",
        "use the camera", "I pull out my camera", "photograph the scene",
        "take a photograph",
    ],
    ("revolver_38", "brandish"): [
        "I draw my revolver", "pull out my gun", "show them my piece",
        "flash the revolver", "I level the gun at them",
    ],
    ("revolver_38", "shoot"): [
        "I shoot", "fire the revolver", "pull the trigger", "shoot at them",
    ],
    ("lockpicks", "pick"): [
        "pick the lock", "use the lockpicks", "I work the lock",
        "break in with the picks",
    ],
    ("binoculars", "observe"): [
        "use the binoculars", "watch through the binoculars",
        "I glass the area", "observe from a distance",
    ],
    ("bribe_envelope", "bribe"): [
        "slide the envelope", "offer the envelope", "hand over the envelope",
        "slip them money",
    ],
    ("disguise_kit", "disguise"): [
        "put on a disguise", "use the disguise kit", "change my appearance",
        "go in disguise",
    ],
}

_KEYWORD_MAP: dict[tuple[str, str], list[str]] = {
    ("camera", "photograph"): ["photograph", "camera", "picture", "photo", "snap"],
    ("revolver_38", "brandish"): ["revolver", "draw my gun", "show them my piece", "flash the revolver", "brandish"],
    ("revolver_38", "shoot"): ["shoot", "fire", "trigger"],
    ("lockpicks", "pick"): ["lockpick", "pick the lock", "picks"],
    ("binoculars", "observe"): ["binoculars", "glass the", "observe from"],
    ("bribe_envelope", "bribe"): ["envelope", "slip them money", "slide the envelope"],
    ("disguise_kit", "disguise"): ["disguise"],
}


def seed_item_definitions(conn: sqlite3.Connection) -> None:
    for item in ITEM_CATALOG:
        conn.execute(
            """INSERT OR IGNORE INTO item_definitions
               (slug, name, description, price, consumable, requires_slug, actions)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                item["slug"], item["name"], item["description"],
                item["price"], item["consumable"], item["requires_slug"],
                json.dumps(item["actions"]),
            ),
        )
    conn.commit()


def get_item_def(slug: str) -> dict | None:
    return _SLUG_TO_ITEM.get(slug)


def get_job_required_items(archetype_slug: str) -> list[dict]:
    """Return required_items list for a job archetype slug, or [] if none."""
    try:
        archetypes = json.loads(_JOBS_ARCHETYPES_PATH.read_text())
    except Exception:
        return []
    for a in archetypes:
        if a.get("slug") == archetype_slug:
            return a.get("required_items", [])
    return []


def check_job_requirements(
    archetype_slug: str,
    inventory: dict[str, int],
) -> list[str]:
    """Return display names of items missing from inventory for the given archetype. Empty = all met."""
    reqs = get_job_required_items(archetype_slug)
    missing = []
    for req in reqs:
        slug = req["slug"]
        item_def = get_item_def(slug)
        if not item_def:
            continue
        if inventory.get(slug, 0) < 1:
            missing.append(item_def["name"])
            continue
        if req.get("needs_consumable"):
            consumable_slug = item_def.get("requires_slug")
            if consumable_slug:
                consumable_def = get_item_def(consumable_slug)
                if inventory.get(consumable_slug, 0) < 1:
                    cname = consumable_def["name"] if consumable_def else consumable_slug
                    missing.append(cname)
    return missing


def get_consumables_to_decrement(archetype_slug: str) -> list[str]:
    """Return slugs of consumables that should be decremented on job completion."""
    reqs = get_job_required_items(archetype_slug)
    to_decrement = []
    for req in reqs:
        if not req.get("needs_consumable"):
            continue
        item_def = get_item_def(req["slug"])
        if item_def and item_def.get("requires_slug"):
            to_decrement.append(item_def["requires_slug"])
    return to_decrement


def detect_item_action(
    text: str,
    inventory: dict[str, int],
    conn: sqlite3.Connection,
) -> tuple[str, str] | None:
    """Return (item_slug, action_name) if text matches an item action the player can perform, else None."""
    owned = {slug for slug, qty in inventory.items() if qty > 0}

    try:
        import noir.memory as _mem
        if _mem.is_available():
            import numpy as np
            text_emb = _mem._encode(text)
            best_score = 0.0
            best_match: tuple[str, str] | None = None
            for (item_slug, action), phrases in ACTION_PHRASES.items():
                if item_slug not in owned:
                    continue
                phrase_embs = np.array([_mem._encode(p) for p in phrases])
                scores = np.dot(phrase_embs, text_emb) / (
                    np.linalg.norm(phrase_embs, axis=1) * np.linalg.norm(text_emb) + 1e-9
                )
                score = float(scores.max())
                if score > best_score:
                    best_score = score
                    best_match = (item_slug, action)
            if best_score >= 0.75 and best_match:
                return best_match
            return None
    except Exception:
        pass

    # Keyword fallback
    text_lower = text.lower()
    for (item_slug, action), keywords in _KEYWORD_MAP.items():
        if item_slug not in owned:
            continue
        if any(kw in text_lower for kw in keywords):
            return (item_slug, action)
    return None
```

- [ ] **Step 4: Add 2 migrations to `noir/persistence/db.py`**

In `_MIGRATIONS` list (after the last entry, before the closing `]`):

```python
    """CREATE TABLE IF NOT EXISTS item_definitions (
        slug TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL,
        price INTEGER NOT NULL,
        consumable INTEGER DEFAULT 0,
        requires_slug TEXT,
        actions TEXT DEFAULT '{}',
        FOREIGN KEY (requires_slug) REFERENCES item_definitions(slug)
    )""",
    """CREATE TABLE IF NOT EXISTS player_items (
        item_slug TEXT PRIMARY KEY,
        quantity INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (item_slug) REFERENCES item_definitions(slug)
    )""",
```

- [ ] **Step 5: Call `seed_item_definitions` in `create_schema`**

At the end of `create_schema` in `noir/persistence/db.py` (after the `_migrate_da_trust` call):

```python
    try:
        from noir.items import seed_item_definitions
        seed_item_definitions(conn)
    except Exception:
        pass
```

- [ ] **Step 6: Run tests**

```
pytest tests/test_items.py -v
```
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add noir/items.py noir/persistence/db.py tests/test_items.py
git commit -m "feat: item definitions DB schema, catalog, and seeding"
```

---

### Task 2: Repository functions — `get_player_items`, `add_player_item`, `use_item`

**Files:**
- Modify: `noir/persistence/repository.py`
- Test: `tests/test_items.py`

- [ ] **Step 1: Write failing tests** (add to `tests/test_items.py`)

```python
from noir.persistence.repository import (
    get_player_items, add_player_item, use_item,
)


def test_get_player_items_empty(db):
    items = get_player_items(db)
    assert items == {}


def test_add_player_item_creates_row(db):
    add_player_item(db, slug="camera", quantity=1)
    items = get_player_items(db)
    assert items["camera"] == 1


def test_add_player_item_stacks(db):
    add_player_item(db, slug="film", quantity=2)
    add_player_item(db, slug="film", quantity=3)
    items = get_player_items(db)
    assert items["film"] == 5


def test_use_item_decrements(db):
    add_player_item(db, slug="film", quantity=3)
    result = use_item(db, slug="film")
    assert result is True
    assert get_player_items(db)["film"] == 2


def test_use_item_fails_when_empty(db):
    result = use_item(db, slug="film")
    assert result is False


def test_use_item_fails_when_zero_quantity(db):
    add_player_item(db, slug="ammo_38", quantity=0)
    result = use_item(db, slug="ammo_38")
    assert result is False
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_items.py::test_get_player_items_empty -v
```
Expected: FAIL with ImportError

- [ ] **Step 3: Add functions to `noir/persistence/repository.py`** (append at end of file)

```python
def get_player_items(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT item_slug, quantity FROM player_items").fetchall()
    return {r["item_slug"]: r["quantity"] for r in rows}


def add_player_item(conn: sqlite3.Connection, *, slug: str, quantity: int = 1) -> None:
    conn.execute(
        """INSERT INTO player_items (item_slug, quantity) VALUES (?, ?)
           ON CONFLICT(item_slug) DO UPDATE SET quantity = quantity + ?""",
        (slug, quantity, quantity),
    )
    conn.commit()


def use_item(conn: sqlite3.Connection, *, slug: str) -> bool:
    """Decrement a consumable by 1. Returns True if item was present and decremented."""
    row = conn.execute(
        "SELECT quantity FROM player_items WHERE item_slug=?", (slug,)
    ).fetchone()
    if not row or row["quantity"] <= 0:
        return False
    conn.execute(
        "UPDATE player_items SET quantity = quantity - 1 WHERE item_slug=?", (slug,)
    )
    conn.commit()
    return True
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_items.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add noir/persistence/repository.py tests/test_items.py
git commit -m "feat: get_player_items, add_player_item, use_item repository functions"
```

---

### Task 3: `archetypes.json` — add `required_items` to 4 job archetypes

**Files:**
- Modify: `noir/jobs/archetypes.json`

- [ ] **Step 1: Add `required_items` to `cheating_spouse`**

In `noir/jobs/archetypes.json`, find the `cheating_spouse` entry and add after `"moral_weight": "medium"`:

```json
    "required_items": [
      {"slug": "camera", "needs_consumable": true}
    ]
```

- [ ] **Step 2: Add `required_items` to `surveillance`**

Find the `surveillance` entry and add after `"moral_weight": "low"`:

```json
    "required_items": [
      {"slug": "binoculars", "needs_consumable": false}
    ]
```

- [ ] **Step 3: Add `required_items` to `shadow_operation`**

Find the `shadow_operation` entry and add after `"moral_weight": "low"`:

```json
    "required_items": [
      {"slug": "binoculars", "needs_consumable": false}
    ]
```

- [ ] **Step 4: Add `required_items` to `debt_collection`**

Find the `debt_collection` entry and add after `"moral_weight": "medium"`:

```json
    "required_items": [
      {"slug": "revolver_38", "needs_consumable": false}
    ]
```

- [ ] **Step 5: Run existing tests**

```
pytest tests/test_items.py::test_get_job_required_items_cheating_spouse -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add noir/jobs/archetypes.json
git commit -m "feat: required_items on cheating_spouse, surveillance, shadow_operation, debt_collection archetypes"
```

---

### Task 4: Treme Pawn & Loan location + Clarence Dufour NPC

**Files:**
- Modify: `noir/organizations.py`
- Modify: `noir/game.py`

- [ ] **Step 1: Write failing test** (add to `tests/test_items.py`)

```python
def test_treme_pawn_org_seeded(db):
    row = db.execute(
        "SELECT id FROM organizations WHERE name='Treme Pawn & Loan'"
    ).fetchone()
    assert row is not None
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_items.py::test_treme_pawn_org_seeded -v
```
Expected: FAIL (org not seeded)

- [ ] **Step 3: Add organization to `noir/organizations.py`**

In `SEEDED_ORGANIZATIONS` list (append before closing `]` of the list):

```python
    {
        "name": "Treme Pawn & Loan",
        "type": "independent",
        "description": "A pawn and loan shop in the Tremé. Buys and sells without asking questions about provenance.",
        "is_hierarchical": False,
        "influence": 1,
    },
```

- [ ] **Step 4: Run test**

```
pytest tests/test_items.py::test_treme_pawn_org_seeded -v
```
Expected: PASS

- [ ] **Step 5: Add fixed location to `FIXED_LOCATIONS` in `noir/game.py`**

In `FIXED_LOCATIONS` list (append before closing `]`):

```python
    ("Treme Pawn & Loan", "A pawn shop in the Tremé that has been buying and selling since before the war. The proprietor asks no questions about where things came from."),
```

- [ ] **Step 6: Add Clarence Dufour to `FIXED_LOCATION_NPCS` in `noir/game.py`**

Append to `FIXED_LOCATION_NPCS` list (before closing `]`):

```python
    {
        "name": "Clarence Dufour",
        "location": "Treme Pawn & Loan",
        "role": "pawn shop proprietor",
        "org": "Treme Pawn & Loan",
        "org_role": "proprietor",
        "corruption": 0,
        "system_prompt": (
            "You are Clarence Dufour, Creole proprietor of Treme Pawn & Loan, 1935. "
            "You have run this shop since 1919 and you know what things are worth — to the penny. "
            "You ask no questions about where goods came from. You do not discuss your customers. "
            "When a detective comes in, you describe what's in stock and what it costs. "
            "If they want to buy something, they say so and you complete the sale. "
            "You carry: Camera ($12), Roll of Film ($2 each), Lockpick Set ($8), Binoculars ($15), "
            ".38 Revolver ($35), .38 Ammunition ($4 per box of 10 rounds), "
            "Bribe Envelope ($2 each), Disguise Kit ($18). "
            "Speak in the measured tones of someone who has learned that discretion is a business asset. "
            "You are not warm, but you are fair. "
            "PERIOD ACCURACY: It is 1935. No computers, no televisions, no zip codes."
        ),
    },
```

- [ ] **Step 7: Commit**

```bash
git add noir/organizations.py noir/game.py tests/test_items.py
git commit -m "feat: Treme Pawn & Loan fixed location and Clarence Dufour NPC"
```

---

### Task 5: `/items` display command

**Files:**
- Modify: `noir/display.py`
- Modify: `noir/game.py`

- [ ] **Step 1: Add `show_items` to `noir/display.py`** (append at end of file, before `show_help`)

```python
def show_items(items: dict[str, int], item_defs: list) -> None:
    """Display the player's current inventory."""
    owned = [(d, items.get(d["slug"], 0)) for d in item_defs if items.get(d["slug"], 0) > 0]
    if not owned:
        console.print(Panel(
            "[dim]Nothing on you.[/dim]",
            title="[bold white]What You're Carrying[/bold white]",
            border_style="white",
        ))
        return
    lines = []
    for item_def, qty in owned:
        if item_def["consumable"]:
            qty_str = str(qty)
        else:
            qty_str = "✓"
        lines.append(
            f"  [white]{item_def['name']:<22}[/white]"
            f"[yellow]{qty_str:<5}[/yellow]"
            f"[dim]{item_def['description']}[/dim]"
        )
    console.print(Panel(
        "\n".join(lines),
        title="[bold white]What You're Carrying[/bold white]",
        border_style="white",
    ))
```

- [ ] **Step 2: Add `handle_slash_items` to `noir/game.py`**

Add this method to the `Game` class (e.g. after `handle_slash_done`):

```python
def handle_slash_items(self) -> None:
    from noir.items import ITEM_CATALOG
    from noir.persistence.repository import get_player_items
    from noir.display import show_items
    inventory = get_player_items(self.conn)
    show_items(inventory, ITEM_CATALOG)
```

- [ ] **Step 3: Wire `/items` into the dispatch in `noir/game.py`**

In `_dispatch_slash`, after the `/done` branch (around line 2544):

```python
        elif slug == "/items":
            self.handle_slash_items()
```

Also add `/items` to the help text in `show_help` in `noir/display.py`. Find the `"[bold]Detective status:[/bold]"` section and after `/rep` add:
```
  /items — what you're carrying\n
```

Also add `/items` to `_PROMPT_HINT_PLAIN` in `noir/display.py`:
Replace the existing string by appending `  ·  /items` before the closing `"`.

- [ ] **Step 4: Commit**

```bash
git add noir/display.py noir/game.py
git commit -m "feat: /items command — player inventory display"
```

---

### Task 6: `/use [item] [action]` command

**Files:**
- Modify: `noir/game.py`
- Test: `tests/test_items.py`

- [ ] **Step 1: Write failing test** (add to `tests/test_items.py`)

```python
def test_check_job_requirements_missing(db):
    from noir.items import check_job_requirements
    inventory = {}  # no camera, no film
    missing = check_job_requirements("cheating_spouse", inventory)
    assert "Camera" in missing


def test_check_job_requirements_has_tool_but_missing_consumable(db):
    from noir.items import check_job_requirements
    inventory = {"camera": 1}  # camera present, no film
    missing = check_job_requirements("cheating_spouse", inventory)
    assert "Roll of Film" in missing
    assert "Camera" not in missing


def test_check_job_requirements_all_present(db):
    from noir.items import check_job_requirements
    inventory = {"camera": 1, "film": 2}
    missing = check_job_requirements("cheating_spouse", inventory)
    assert missing == []


def test_check_job_requirements_no_reqs(db):
    from noir.items import check_job_requirements
    inventory = {}
    missing = check_job_requirements("skip_trace", inventory)
    assert missing == []
```

- [ ] **Step 2: Run tests**

```
pytest tests/test_items.py::test_check_job_requirements_missing tests/test_items.py::test_check_job_requirements_all_present -v
```
Expected: PASS (check_job_requirements already implemented in Task 1)

- [ ] **Step 3: Add `handle_slash_use` to `noir/game.py`**

Add this method to the `Game` class:

```python
def handle_slash_use(self, args: str) -> None:
    """Handle /use [item] [action]. Validates item ownership, action validity, consumes if needed."""
    from noir.items import get_item_def
    from noir.persistence.repository import get_player_items, use_item as _use_item
    parts = args.strip().split()
    if len(parts) < 2:
        console.print("[dim]Use what, how? Try: /use camera photograph[/dim]")
        return

    item_slug = parts[0].lower()
    action_name = parts[1].lower()

    inventory = get_player_items(self.conn)
    if inventory.get(item_slug, 0) < 1:
        console.print(f"[dim]You don't have a {item_slug.replace('_', ' ')}.[/dim]")
        return

    item_def = get_item_def(item_slug)
    if not item_def:
        console.print("[dim]That's not something you're carrying.[/dim]")
        return

    import json as _json
    actions = item_def.get("actions", {})
    if action_name not in actions:
        valid = ", ".join(actions.keys()) or "none"
        console.print(f"[dim]You can't do that with a {item_def['name']}. Valid: {valid}[/dim]")
        return

    action_def = actions[action_name]
    consumes = action_def.get("consumes")
    if consumes:
        if inventory.get(consumes, 0) < 1:
            consumable_def = get_item_def(consumes)
            cname = consumable_def["name"] if consumable_def else consumes
            console.print(f"[dim]You need {cname} to do that.[/dim]")
            return
        _use_item(self.conn, slug=consumes)

    console.print(f"[dim]Done.[/dim]")
```

- [ ] **Step 4: Wire `/use` into dispatch in `noir/game.py`**

In `_dispatch_slash`, after the `/items` branch:

```python
        elif slug == "/use":
            args = raw.strip()[4:].strip()
            self.handle_slash_use(args)
```

Also add `/use [item] [action]` to the help text in `show_help` in `noir/display.py`, in the investigation section.

- [ ] **Step 5: Commit**

```bash
git add noir/game.py noir/display.py tests/test_items.py
git commit -m "feat: /use [item] [action] command with consumable validation"
```

---

### Task 7: Natural language action detection in NPC conversation loop

**Files:**
- Modify: `noir/game.py`

- [ ] **Step 1: Add `_maybe_trigger_item_action` method to the `Game` class**

Add this method (after `handle_slash_use`):

```python
def _maybe_trigger_item_action(self, text: str) -> None:
    """Detect and trigger item actions from natural language input."""
    from noir.items import detect_item_action, get_item_def
    from noir.persistence.repository import get_player_items, use_item as _use_item
    inventory = get_player_items(self.conn)
    if not inventory:
        return
    match = detect_item_action(text, inventory, self.conn)
    if not match:
        return
    item_slug, action_name = match
    item_def = get_item_def(item_slug)
    if not item_def:
        return
    actions = item_def.get("actions", {})
    action_def = actions.get(action_name, {})
    consumes = action_def.get("consumes")
    if consumes:
        if inventory.get(consumes, 0) < 1:
            consumable_def = get_item_def(consumes)
            cname = consumable_def["name"] if consumable_def else consumes
            console.print(f"[dim]You reach for the {item_def['name']} — but you're out of {cname}.[/dim]")
            return
        _use_item(self.conn, slug=consumes)
    console.print(f"[dim][{item_def['name']}][/dim]")
```

- [ ] **Step 2: Wire it into the NPC conversation loop**

In `_talk_npc`, right after `show_player_turn(player_input)` (around line 1633), add:

```python
            self._maybe_trigger_item_action(player_input)
```

- [ ] **Step 3: Run existing tests to confirm no regressions**

```
pytest -x -q
```
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add noir/game.py
git commit -m "feat: natural language item action detection in NPC conversations"
```

---

### Task 8: Purchase detection — Clarence Dufour

**Files:**
- Modify: `noir/game.py`

- [ ] **Step 1: Add `_check_purchase_from_dufour` method to the `Game` class**

Add this method (after `_maybe_trigger_item_action`):

```python
def _check_purchase_from_dufour(self, npc_row, response: str) -> None:
    """After Dufour responds, check if a purchase was made and update inventory."""
    _DUFOUR_KEYWORDS = ("buy", "purchase", "i'll take", "give me", "i want", "how much", "sell me")
    resp_lower = response.lower()
    if not any(kw in resp_lower for kw in _DUFOUR_KEYWORDS):
        return

    purchase = self.llm.query_structured(
        "Determine if this pawn shop proprietor's response indicates a completed sale to the detective. "
        "A sale means the proprietor acknowledged the detective is buying something specific. "
        "Return ONLY valid JSON: "
        "{\"item_purchased\": \"slug_or_null\", \"quantity\": 1}",
        [],
        f"Proprietor said: \"{response[:400]}\""
    )

    slug = purchase.get("item_purchased")
    if not slug or slug == "null":
        return

    from noir.items import get_item_def, ITEM_CATALOG
    valid_slugs = {item["slug"] for item in ITEM_CATALOG}
    if slug not in valid_slugs:
        return

    item_def = get_item_def(slug)
    if not item_def:
        return

    qty = 10 if slug == "ammo_38" else int(purchase.get("quantity") or 1)
    price = item_def["price"] * (10 if slug == "ammo_38" else 1)

    cash = get_player_cash(self.conn)
    if cash < price:
        console.print(f"[dim]You're short. {item_def['name']} costs ${price}.[/dim]")
        return

    from noir.persistence.repository import add_player_item
    add_player_item(self.conn, slug=slug, quantity=qty)
    update_player_cash(self.conn, delta=-price)

    if slug == "ammo_38":
        console.print(f"[dim]-${price}. Ten rounds of .38, added to your pocket.[/dim]")
    elif item_def["consumable"]:
        console.print(f"[dim]-${price}. {item_def['name']} added.[/dim]")
    else:
        console.print(f"[dim]-${price}. {item_def['name']} is yours.[/dim]")
```

- [ ] **Step 2: Wire it into the NPC conversation loop**

In the `_talk_npc` main loop, after `self._check_npc_job_offer(npc_row, response)` (around line 1675), add:

```python
            if npc_row["name"] == "Clarence Dufour":
                self._check_purchase_from_dufour(npc_row, response)
```

- [ ] **Step 3: Run existing tests**

```
pytest -x -q
```
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add noir/game.py
git commit -m "feat: purchase detection in conversation with Clarence Dufour"
```

---

### Task 9: Arrival nudge — partner warns about missing required items

**Files:**
- Modify: `noir/game.py`

- [ ] **Step 1: Add `_get_missing_required_items_for_active_job` helper to `Game`**

Add this method (after `_check_purchase_from_dufour`):

```python
def _get_missing_required_items_for_active_job(self) -> list[str]:
    """Return display names of required items missing for the active job, or []."""
    import json as _json
    from noir.items import check_job_requirements
    from noir.persistence.repository import get_player_items
    job = self.conn.execute(
        "SELECT case_data FROM cases WHERE case_type='job' AND status='active' LIMIT 1"
    ).fetchone()
    if not job:
        return []
    try:
        data = _json.loads(job["case_data"]) if isinstance(job["case_data"], str) else job["case_data"]
        archetype_slug = data.get("job_archetype", "")
    except Exception:
        return []
    if not archetype_slug:
        return []
    inventory = get_player_items(self.conn)
    return check_job_requirements(archetype_slug, inventory)
```

- [ ] **Step 2: Inject arrival nudge in `handle_go`**

In `handle_go`, after `show_location(...)` (around line 1354), add:

```python
        missing = self._get_missing_required_items_for_active_job()
        if missing and self.companion:
            missing_str = " and ".join(missing)
            nudge_prompt = (
                f"[The detective is heading to work on a job and is missing: {missing_str}. "
                f"Remind them in one in-character sentence — don't say 'the job', be specific about what they need.]"
            )
            nudge = self.companion.narrate(nudge_prompt, record=False)
            show_partner_aside(self.companion.name, nudge)
```

Note: the `else` branch of handle_go (when no companion) doesn't need the nudge — the partner is always present in practice.

- [ ] **Step 3: Run existing tests**

```
pytest -x -q
```
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add noir/game.py
git commit -m "feat: partner nudge on arrival when missing required job items"
```

---

### Task 10: `/done` hard block on missing items + consumable decrement

**Files:**
- Modify: `noir/game.py`

- [ ] **Step 1: Modify `handle_slash_done` to check requirements before completing**

In `handle_slash_done` (around line 3559), after the LLM verdict check (`if not verdict.get("completed", True)`), and before `complete_job(...)`, add:

```python
        # Item requirement check
        try:
            import json as _j
            _data = _j.loads(job["case_data"]) if isinstance(job["case_data"], str) else job["case_data"]
            _archetype = _data.get("job_archetype", "")
        except Exception:
            _archetype = ""

        if _archetype:
            from noir.items import check_job_requirements
            from noir.persistence.repository import get_player_items
            _missing = check_job_requirements(_archetype, get_player_items(self.conn))
            if _missing:
                missing_str = " and ".join(_missing)
                console.print(f"[dim]Can't close that out. You're still missing {missing_str}.[/dim]")
                return
```

- [ ] **Step 2: Decrement consumables on successful completion**

In `handle_slash_done`, right after `complete_job(...)` succeeds, add:

```python
        if _archetype:
            from noir.items import get_consumables_to_decrement
            from noir.persistence.repository import use_item as _use_item
            for consumable_slug in get_consumables_to_decrement(_archetype):
                _use_item(self.conn, slug=consumable_slug)
```

The full modified `handle_slash_done` flow (the relevant section):

```python
        if not verdict.get("completed", True):
            reason = verdict.get("reason") or "That one ain't wrapped up yet."
            console.print(f"[dim]{reason}[/dim]")
            return

        # parse archetype for item checks
        try:
            import json as _j
            _data = _j.loads(job["case_data"]) if isinstance(job["case_data"], str) else job["case_data"]
            _archetype = _data.get("job_archetype", "")
        except Exception:
            _archetype = ""

        if _archetype:
            from noir.items import check_job_requirements
            from noir.persistence.repository import get_player_items
            _missing = check_job_requirements(_archetype, get_player_items(self.conn))
            if _missing:
                missing_str = " and ".join(_missing)
                console.print(f"[dim]Can't close that out. You're still missing {missing_str}.[/dim]")
                return

        payout = job["payout"] or 0
        faction = job["faction"] or "private"
        tier = job["tier"] or 1
        complete_job(self.conn, case_id=job["id"], payout=payout, faction=faction, tier=tier)

        if _archetype:
            from noir.items import get_consumables_to_decrement
            from noir.persistence.repository import use_item as _use_item
            for consumable_slug in get_consumables_to_decrement(_archetype):
                _use_item(self.conn, slug=consumable_slug)

        if tier == 1:
            self._replenish_job_board()
        self._resume_on_hold()
        # ... rest of method unchanged
```

- [ ] **Step 3: Run existing tests**

```
pytest tests/test_jobs.py -v
```
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add noir/game.py
git commit -m "feat: /done hard blocks on missing required items, decrements consumables on completion"
```

---

### Task 11: Required items in `/job` and `/classifieds` display

**Files:**
- Modify: `noir/game.py`

- [ ] **Step 1: Add required items to `handle_slash_active_work`**

In `handle_slash_active_work`, at the end of the `if row["case_type"] == "job":` block, after the steps list (after the `for step in steps:` loop, before `console.print("\n".join(lines))`), add:

```python
            archetype_slug = data.get("job_archetype", "")
            if archetype_slug:
                from noir.items import get_job_required_items, get_item_def
                from noir.persistence.repository import get_player_items
                reqs = get_job_required_items(archetype_slug)
                if reqs:
                    inventory = get_player_items(self.conn)
                    req_parts = []
                    for req in reqs:
                        item_def = get_item_def(req["slug"])
                        if not item_def:
                            continue
                        has_item = inventory.get(req["slug"], 0) >= 1
                        color = "dim" if has_item else "yellow"
                        req_parts.append(f"[{color}]{item_def['name']}[/{color}]")
                        if req.get("needs_consumable") and item_def.get("requires_slug"):
                            consumable_def = get_item_def(item_def["requires_slug"])
                            if consumable_def:
                                has_consumable = inventory.get(item_def["requires_slug"], 0) >= 1
                                color = "dim" if has_consumable else "yellow"
                                req_parts.append(f"[{color}]{consumable_def['name']}[/{color}]")
                    if req_parts:
                        lines.append(f"\n[dim]Required:[/dim] {', '.join(req_parts)}")
```

- [ ] **Step 2: Add required items to `handle_slash_jobs` listings**

In `handle_slash_jobs`, inside the `for i, job in enumerate(jobs, 1):` loop, after the objective line (`lines.append(f"   [dim]{data.get('objective', '')}[/dim]")`), add:

```python
            archetype_slug = data.get("job_archetype", "")
            if archetype_slug:
                from noir.items import get_job_required_items, get_item_def
                reqs = get_job_required_items(archetype_slug)
                if reqs:
                    req_names = []
                    for req in reqs:
                        item_def = get_item_def(req["slug"])
                        if item_def:
                            req_names.append(item_def["name"])
                            if req.get("needs_consumable") and item_def.get("requires_slug"):
                                consumable_def = get_item_def(item_def["requires_slug"])
                                if consumable_def:
                                    req_names.append(consumable_def["name"])
                    if req_names:
                        lines.append(f"   [dim]Requires: {', '.join(req_names)}[/dim]")
```

- [ ] **Step 3: Run full test suite**

```
pytest -x -q
```
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add noir/game.py
git commit -m "feat: required items shown in /job and /classifieds display"
```
