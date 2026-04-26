# Map & Neighborhoods Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Rich-rendered ASCII neighborhood map, distance-based travel time, and seeded bartender NPCs to Noir-Leans.

**Architecture:** Neighborhoods are a new DB layer between the city and individual locations. The map is a one-shot Rich canvas render triggered by the `map` command. Travel through `go to` gains a time cost derived from a neighborhood adjacency graph. Bartenders are persistent world NPCs seeded once per neighborhood, outside the case system.

**Tech Stack:** Python 3.11+, SQLite (via existing `noir/persistence/`), Rich>=13.0, existing `NPC`/`Agent` character system, `claude` CLI backend.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `noir/persistence/db.py` | Modify | Add 3 new tables + `locations.neighborhood_id` migration |
| `noir/persistence/repository.py` | Modify | Add neighborhood/adjacency/bartender queries |
| `noir/map.py` | **Create** | Rich canvas map renderer (promoted from `map_prototype.py`); `noir/display.py` already exists as a flat file so the map lives here |
| `noir/neighborhoods.py` | **Create** | Neighborhood seeding, danger computation, bartender seeding |
| `noir/parser.py` | Modify | Add `MAP` intent |
| `noir/game.py` | Modify | Handle `MAP` intent; add travel time cost to `handle_go` |
| `tests/test_neighborhoods.py` | **Create** | Tests for danger computation, adjacency, repository queries |
| `tests/test_map.py` | **Create** | Tests for map render output |

---

## Task 1: DB Schema — neighborhoods, neighborhood_factions, neighborhood_adjacency

**Files:**
- Modify: `noir/persistence/db.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_neighborhoods.py
import pytest
import sqlite3
from noir.persistence.db import create_schema


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    create_schema(c)
    return c


def test_neighborhoods_table_exists(conn):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='neighborhoods'"
    ).fetchone()
    assert row is not None


def test_neighborhood_factions_table_exists(conn):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='neighborhood_factions'"
    ).fetchone()
    assert row is not None


def test_neighborhood_adjacency_table_exists(conn):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='neighborhood_adjacency'"
    ).fetchone()
    assert row is not None


def test_locations_has_neighborhood_id(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info('locations')").fetchall()]
    assert "neighborhood_id" in cols
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_neighborhoods.py -v
```
Expected: 4 FAILs — tables don't exist yet.

- [ ] **Step 3: Add migrations to `noir/persistence/db.py`**

Add the three new `CREATE TABLE` statements to `SCHEMA` (after the existing `location_organizations` block):

```python
CREATE TABLE IF NOT EXISTS neighborhoods (
    id      INTEGER PRIMARY KEY,
    slug    TEXT UNIQUE NOT NULL,
    name    TEXT NOT NULL,
    danger  INTEGER NOT NULL DEFAULT 2
);

CREATE TABLE IF NOT EXISTS neighborhood_factions (
    neighborhood_id INTEGER NOT NULL REFERENCES neighborhoods(id),
    faction         TEXT NOT NULL,
    PRIMARY KEY (neighborhood_id, faction)
);

CREATE TABLE IF NOT EXISTS neighborhood_adjacency (
    from_id  INTEGER NOT NULL REFERENCES neighborhoods(id),
    to_id    INTEGER NOT NULL REFERENCES neighborhoods(id),
    distance INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (from_id, to_id)
);
```

Add the `locations.neighborhood_id` migration to `_MIGRATIONS` (append at the end):

```python
"ALTER TABLE locations ADD COLUMN neighborhood_id INTEGER REFERENCES neighborhoods(id)",
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_neighborhoods.py -v
```
Expected: 4 PASSes.

- [ ] **Step 5: Commit**

```bash
git add noir/persistence/db.py tests/test_neighborhoods.py
git commit -m "feat: add neighborhoods, neighborhood_factions, neighborhood_adjacency schema"
```

---

## Task 2: Seed neighborhoods and adjacency data

**Files:**
- Create: `noir/neighborhoods.py`
- Modify: `tests/test_neighborhoods.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_neighborhoods.py

from noir.neighborhoods import seed_neighborhoods, get_neighborhood_id


def test_seed_neighborhoods_creates_all_12(conn):
    seed_neighborhoods(conn)
    count = conn.execute("SELECT COUNT(*) FROM neighborhoods").fetchone()[0]
    assert count == 12


def test_seed_neighborhoods_idempotent(conn):
    seed_neighborhoods(conn)
    seed_neighborhoods(conn)
    count = conn.execute("SELECT COUNT(*) FROM neighborhoods").fetchone()[0]
    assert count == 12


def test_seed_adjacency_creates_edges(conn):
    seed_neighborhoods(conn)
    count = conn.execute("SELECT COUNT(*) FROM neighborhood_adjacency").fetchone()[0]
    assert count > 0


def test_adjacency_is_symmetric(conn):
    seed_neighborhoods(conn)
    rows = conn.execute(
        "SELECT from_id, to_id FROM neighborhood_adjacency"
    ).fetchall()
    pairs = {(r["from_id"], r["to_id"]) for r in rows}
    for from_id, to_id in list(pairs):
        assert (to_id, from_id) in pairs, f"Missing reverse edge {to_id} -> {from_id}"


def test_get_neighborhood_id(conn):
    seed_neighborhoods(conn)
    nid = get_neighborhood_id(conn, "french_quarter")
    assert nid is not None
    assert isinstance(nid, int)
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_neighborhoods.py::test_seed_neighborhoods_creates_all_12 -v
```
Expected: FAIL — `noir.neighborhoods` not found.

- [ ] **Step 3: Create `noir/neighborhoods.py`**

```python
import sqlite3

# (slug, name, factions, danger_override=None)
_NEIGHBORHOODS = [
    ("mid_city",       "Mid-City",          ["P", "S"],      None),
    ("treme",          "Treme",             ["P", "L"],      None),
    ("seventh_ward",   "7th Ward",          ["P", "L"],      None),
    ("garden_district","Garden District",   ["P", "T"],      None),
    ("cbd",            "CBD",               ["P", "R", "S"], None),
    ("french_quarter", "French Quarter",    ["P", "R", "A"], None),
    ("marigny",        "Marigny",           ["C"],           None),
    ("uptown",         "Uptown",            ["P", "T"],      None),
    ("irish_channel",  "Irish Channel",     ["I", "P"],      None),
    ("bywater",        "Bywater",           ["I", "L"],      None),
    ("lower_ninth",    "Lower 9th Ward",    ["L", "P"],      None),
    ("algiers",        "Algiers",           ["P", "I"],      None),
]

# (from_slug, to_slug, distance)
_ADJACENCY = [
    ("uptown",         "garden_district", 1),
    ("garden_district","cbd",             1),
    ("cbd",            "french_quarter",  1),
    ("cbd",            "mid_city",        1),
    ("cbd",            "irish_channel",   1),
    ("french_quarter", "treme",           1),
    ("french_quarter", "marigny",         1),
    ("french_quarter", "algiers",         2),
    ("treme",          "mid_city",        1),
    ("treme",          "seventh_ward",    1),
    ("marigny",        "seventh_ward",    1),
    ("marigny",        "bywater",         1),
    ("irish_channel",  "uptown",          1),
    ("bywater",        "lower_ninth",     1),
    ("seventh_ward",   "mid_city",        1),
]

_ALGIERS_SLUGS = {"algiers"}


def seed_neighborhoods(conn: sqlite3.Connection) -> None:
    for slug, name, factions, _ in _NEIGHBORHOODS:
        conn.execute(
            "INSERT OR IGNORE INTO neighborhoods (slug, name) VALUES (?, ?)",
            (slug, name)
        )
    conn.commit()

    for slug, _, factions, _ in _NEIGHBORHOODS:
        nid = get_neighborhood_id(conn, slug)
        for faction in factions:
            conn.execute(
                "INSERT OR IGNORE INTO neighborhood_factions (neighborhood_id, faction) VALUES (?, ?)",
                (nid, faction)
            )

    for from_slug, to_slug, dist in _ADJACENCY:
        from_id = get_neighborhood_id(conn, from_slug)
        to_id   = get_neighborhood_id(conn, to_slug)
        conn.execute(
            "INSERT OR IGNORE INTO neighborhood_adjacency (from_id, to_id, distance) VALUES (?, ?, ?)",
            (from_id, to_id, dist)
        )
        conn.execute(
            "INSERT OR IGNORE INTO neighborhood_adjacency (from_id, to_id, distance) VALUES (?, ?, ?)",
            (to_id, from_id, dist)
        )
    conn.commit()


def get_neighborhood_id(conn: sqlite3.Connection, slug: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM neighborhoods WHERE slug=?", (slug,)
    ).fetchone()
    return row["id"] if row else None


def is_algiers_crossing(from_slug: str, to_slug: str) -> bool:
    return (from_slug in _ALGIERS_SLUGS) != (to_slug in _ALGIERS_SLUGS)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_neighborhoods.py -v
```
Expected: all PASSes.

- [ ] **Step 5: Commit**

```bash
git add noir/neighborhoods.py tests/test_neighborhoods.py
git commit -m "feat: seed 12 neighborhoods and adjacency graph"
```

---

## Task 3: Repository queries for neighborhoods

**Files:**
- Modify: `noir/persistence/repository.py`
- Modify: `tests/test_neighborhoods.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_neighborhoods.py

from noir.neighborhoods import seed_neighborhoods
from noir.persistence.repository import (
    get_neighborhood_for_location,
    get_travel_distance,
    get_neighborhood_factions,
    get_all_neighborhoods,
)


def test_get_all_neighborhoods(conn):
    seed_neighborhoods(conn)
    hoods = get_all_neighborhoods(conn)
    assert len(hoods) == 12
    assert any(h["slug"] == "french_quarter" for h in hoods)


def test_get_neighborhood_factions(conn):
    seed_neighborhoods(conn)
    factions = get_neighborhood_factions(conn, "french_quarter")
    assert set(factions) == {"P", "R", "A"}


def test_get_travel_distance_adjacent(conn):
    seed_neighborhoods(conn)
    dist = get_travel_distance(conn, "french_quarter", "marigny")
    assert dist == 1


def test_get_travel_distance_not_connected(conn):
    seed_neighborhoods(conn)
    dist = get_travel_distance(conn, "lower_ninth", "uptown")
    assert dist is None


def test_get_neighborhood_for_location(conn):
    seed_neighborhoods(conn)
    nid = conn.execute(
        "SELECT id FROM neighborhoods WHERE slug='french_quarter'"
    ).fetchone()["id"]
    loc_id = conn.execute(
        "INSERT INTO locations (name, description, is_fixed, neighborhood_id) VALUES (?, ?, 1, ?) RETURNING id",
        ("Café Du Monde", "A famous café.", nid)
    ).fetchone()["id"]
    conn.commit()
    result = get_neighborhood_for_location(conn, loc_id)
    assert result is not None
    assert result["slug"] == "french_quarter"
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_neighborhoods.py -k "test_get_all_neighborhoods or test_get_neighborhood_factions or test_get_travel_distance or test_get_neighborhood_for" -v
```
Expected: 4 FAILs — functions not imported.

- [ ] **Step 3: Add functions to `noir/persistence/repository.py`**

Append at the end of the file:

```python
def get_all_neighborhoods(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM neighborhoods ORDER BY id").fetchall()


def get_neighborhood_factions(conn: sqlite3.Connection, slug: str) -> list[str]:
    rows = conn.execute(
        """SELECT nf.faction FROM neighborhood_factions nf
           JOIN neighborhoods n ON n.id = nf.neighborhood_id
           WHERE n.slug = ?""",
        (slug,)
    ).fetchall()
    return [r["faction"] for r in rows]


def get_travel_distance(conn: sqlite3.Connection, from_slug: str, to_slug: str) -> int | None:
    row = conn.execute(
        """SELECT na.distance FROM neighborhood_adjacency na
           JOIN neighborhoods fn ON fn.id = na.from_id
           JOIN neighborhoods tn ON tn.id = na.to_id
           WHERE fn.slug = ? AND tn.slug = ?""",
        (from_slug, to_slug)
    ).fetchone()
    return row["distance"] if row else None


def get_neighborhood_for_location(conn: sqlite3.Connection, location_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT n.* FROM neighborhoods n
           JOIN locations l ON l.neighborhood_id = n.id
           WHERE l.id = ?""",
        (location_id,)
    ).fetchone()


def get_neighborhood_by_slug(conn: sqlite3.Connection, slug: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM neighborhoods WHERE slug=?", (slug,)
    ).fetchone()


def update_neighborhood_danger(conn: sqlite3.Connection, slug: str, danger: int) -> None:
    conn.execute(
        "UPDATE neighborhoods SET danger=? WHERE slug=?", (danger, slug)
    )
    conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_neighborhoods.py -v
```
Expected: all PASSes.

- [ ] **Step 5: Commit**

```bash
git add noir/persistence/repository.py tests/test_neighborhoods.py
git commit -m "feat: add neighborhood repository queries"
```

---

## Task 4: Danger computation

**Files:**
- Modify: `noir/neighborhoods.py`
- Modify: `tests/test_neighborhoods.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_neighborhoods.py

from noir.neighborhoods import compute_danger, recompute_all_danger


def test_compute_danger_base(conn):
    # No opposing factions → danger 1
    assert compute_danger([]) == 1


def test_compute_danger_direct_opposition(conn):
    # rossi + castellano are direct opponents → +2
    danger = compute_danger(["rossi", "castellano"])
    assert danger == 3


def test_compute_danger_clamps_to_5(conn):
    # Multiple direct oppositions
    danger = compute_danger(["rossi", "castellano", "nopd", "treme_club", "tallboys", "shorties"])
    assert danger <= 5


def test_recompute_all_danger_updates_db(conn):
    seed_neighborhoods(conn)
    recompute_all_danger(conn)
    row = conn.execute(
        "SELECT danger FROM neighborhoods WHERE slug='irish_channel'"
    ).fetchone()
    assert 1 <= row["danger"] <= 5
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_neighborhoods.py -k "danger" -v
```
Expected: FAILs.

- [ ] **Step 3: Add `compute_danger` and `recompute_all_danger` to `noir/neighborhoods.py`**

```python
from noir.jobs.factions import OPPOSITION


def compute_danger(faction_slugs: list[str]) -> int:
    danger = 1
    slugs = set(faction_slugs)
    for slug in slugs:
        opp = OPPOSITION.get(slug, {})
        for other in opp.get("direct", []):
            if other in slugs:
                danger += 2
        for other in opp.get("secondary", []):
            if other in slugs:
                danger += 1
    # Each pair counted twice (once per side) so halve, round up, re-add base
    # Avoid double-counting: only count pairs where slug < other lexicographically
    danger = 1
    for slug in slugs:
        opp = OPPOSITION.get(slug, {})
        for other in opp.get("direct", []):
            if other in slugs and slug < other:
                danger += 2
        for other in opp.get("secondary", []):
            if other in slugs and slug < other:
                danger += 1
    return max(1, min(5, danger))


def recompute_all_danger(conn: sqlite3.Connection) -> None:
    from noir.persistence.repository import get_neighborhood_factions, update_neighborhood_danger
    hoods = conn.execute("SELECT slug FROM neighborhoods").fetchall()
    for hood in hoods:
        slug = hood["slug"]
        factions = get_neighborhood_factions(conn, slug)
        danger = compute_danger(factions)
        update_neighborhood_danger(conn, slug, danger)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_neighborhoods.py -k "danger" -v
```
Expected: all PASSes.

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
pytest tests/ -v --tb=short
```
Expected: all existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add noir/neighborhoods.py tests/test_neighborhoods.py
git commit -m "feat: danger computation from faction opposition"
```

---

## Task 5: Map renderer

**Files:**
- Create: `noir/display/map.py`

The map renderer is a direct promotion of `map_prototype.py` into the package. It takes live DB data for the player's current location and discovered case markers rather than hardcoded values.

- [ ] **Step 1: Create `noir/display/` package if needed**

```bash
touch noir/display/__init__.py
```

Check if `noir/display.py` already exists as a module file (it does — it's the existing display module). The map goes in a new subdirectory. Since `noir/display.py` already exists, we can't create `noir/display/` as a directory. Instead, place the map module at `noir/map.py`.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_map.py
import sqlite3
from noir.persistence.db import create_schema
from noir.neighborhoods import seed_neighborhoods
from noir.map import render_map


def test_render_map_returns_string(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)
    seed_neighborhoods(conn)
    result = render_map(conn, current_neighborhood_slug="french_quarter", markers={})
    assert isinstance(result, str)
    assert "FRENCH QTR" in result


def test_render_map_marks_active_box(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)
    seed_neighborhoods(conn)
    result = render_map(conn, current_neighborhood_slug="french_quarter", markers={})
    # Double-line border chars appear for the active box
    assert "╔" in result
    assert "╝" in result


def test_render_map_no_markers(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)
    seed_neighborhoods(conn)
    result = render_map(conn, current_neighborhood_slug="mid_city", markers={})
    assert "MID-CITY" in result
```

- [ ] **Step 3: Run to verify it fails**

```bash
pytest tests/test_map.py -v
```
Expected: FAILs — `noir.map` not found.

- [ ] **Step 4: Create `noir/map.py`**

This is a clean port of `map_prototype.py` with two changes: (a) it accepts live data instead of hardcoded values, and (b) it returns a string (the rendered map) instead of printing directly.

```python
"""Rich ASCII map of Noirleans neighborhoods."""
import sqlite3
from io import StringIO
from rich.console import Console
from rich.text import Text
from noir.persistence.repository import get_all_neighborhoods, get_neighborhood_factions

W, H = 94, 31

FACTION_COLORS = {
    'P': 'bold blue',
    'R': 'bold red',
    'C': 'bold yellow',
    'I': 'bold green',
    'L': 'bold magenta',
    'S': 'bold cyan',
    'T': 'bold white',
    'A': 'yellow',
}

LOCATION_MARKER_COLORS = {
    '✦': 'bold red',
    '⌂': 'white',
    '⚑': 'bold yellow',
    '◉': 'bold cyan',
    '☎': 'bold green',
    '✝': 'dim white',
    '⚜': 'bold yellow',
}

# slug → (box_row, box_col, display_name)
NEIGHBORHOOD_LAYOUT = {
    "mid_city":        (3,  20, "MID-CITY"),
    "treme":           (3,  38, "TREME"),
    "seventh_ward":    (3,  56, "7TH WARD"),
    "garden_district": (9,   2, "GARDEN DIST"),
    "cbd":             (9,  20, "CBD"),
    "french_quarter":  (9,  38, "FRENCH QTR"),
    "marigny":         (9,  56, "MARIGNY"),
    "uptown":          (15,  2, "UPTOWN"),
    "irish_channel":   (15, 20, "IRISH CH."),
    "bywater":         (15, 56, "BYWATER"),
    "lower_ninth":     (15, 74, "LOWER 9TH"),
    "algiers":         (25, 38, "ALGIERS"),
}

BW, BH = 16, 5

RIVER_CTRL = [
    ( 1, 21), (15, 22), (30, 21), (45, 20), (58, 21), (74, 22), (93, 21),
]
GLOBAL_TOP = 20


def _river_row_at(col: int) -> int:
    for i in range(len(RIVER_CTRL) - 1):
        c1, r1 = RIVER_CTRL[i]
        c2, r2 = RIVER_CTRL[i + 1]
        if c1 <= col <= c2:
            t = (col - c1) / (c2 - c1)
            return round(r1 + t * (r2 - r1))
    return RIVER_CTRL[-1][1]


def render_map(
    conn: sqlite3.Connection,
    current_neighborhood_slug: str,
    markers: dict[str, list[str]],  # slug → list of marker symbols
) -> str:
    canvas       = [[' ']   * W for _ in range(H)]
    styles       = [[None]  * W for _ in range(H)]
    box_interior = [[False] * W for _ in range(H)]
    active_int   = [[False] * W for _ in range(H)]

    def put(r, c, ch, style=None):
        if 0 <= r < H and 0 <= c < W:
            canvas[r][c] = ch
            if style is not None:
                styles[r][c] = style

    def hline(r, c1, c2, ch='─', style='white'):
        for c in range(c1, c2 + 1):
            put(r, c, ch, style)

    def vline(c, r1, r2, ch='│', style='white'):
        for r in range(r1, r2 + 1):
            put(r, c, ch, style)

    def txt(r, c, s, style=None):
        for i, ch in enumerate(s):
            put(r, c + i, ch, style)

    def box(r, c, h, w, style='white', double=False, title=None):
        if double:
            tl, tr, bl, br, h_ch, v_ch = '╔', '╗', '╚', '╝', '═', '║'
        else:
            tl, tr, bl, br, h_ch, v_ch = '┌', '┐', '└', '┘', '─', '│'
        put(r, c, tl, style); put(r, c + w - 1, tr, style)
        put(r + h - 1, c, bl, style); put(r + h - 1, c + w - 1, br, style)
        hline(r,         c + 1, c + w - 2, h_ch, style)
        hline(r + h - 1, c + 1, c + w - 2, h_ch, style)
        vline(c,         r + 1, r + h - 2, v_ch, style)
        vline(c + w - 1, r + 1, r + h - 2, v_ch, style)
        if title:
            label = f' {title} '[: w - 2]
            pad = max(0, (w - 2 - len(label)) // 2)
            txt(r, c + 1 + pad, label, style)

    def neighborhood_box(r, c, name, factions, danger, here, slug_markers):
        box(r, c, BH, BW,
            style='bold white' if here else 'dim white',
            double=here, title=name)
        for ri in range(r + 1, r + BH - 1):
            for ci in range(c + 1, c + BW - 1):
                box_interior[ri][ci] = True
                if here:
                    active_int[ri][ci] = True

        factions_width = max(0, len(factions) * 2 - 1)
        fc = c + 1 + (BW - 2 - factions_width) // 2
        for code in factions:
            put(r + 1, fc, code, FACTION_COLORS.get(code, 'white'))
            fc += 2

        if danger <= 2:
            bar_ch, bar_style = '░', 'green'
        elif danger <= 3:
            bar_ch, bar_style = '▒', 'yellow'
        else:
            bar_ch, bar_style = '▓', 'bold red'
        bar_start = c + 1 + (BW - 2 - 5) // 2
        for i in range(5):
            if i < danger:
                put(r + 2, bar_start + i, bar_ch, bar_style)
            else:
                put(r + 2, bar_start + i, '·', 'dim white')

        if slug_markers:
            mw = max(0, len(slug_markers) * 2 - 1)
            mc = c + 1 + (BW - 2 - mw) // 2
            for sym in slug_markers:
                put(r + 3, mc, sym, LOCATION_MARKER_COLORS.get(sym, 'white'))
                mc += 2

    # Outer frame
    hline(0,     0, W - 1, '═', 'dim yellow')
    hline(H - 1, 0, W - 1, '═', 'dim yellow')
    put(0,     0,     '╔', 'dim yellow'); put(0,     W - 1, '╗', 'dim yellow')
    put(H - 1, 0,     '╚', 'dim yellow'); put(H - 1, W - 1, '╝', 'dim yellow')
    for r in range(1, H - 1):
        put(r, 0,     '║', 'dim yellow')
        put(r, W - 1, '║', 'dim yellow')

    title_str = "  N O I R L E A N S  ·  1 9 3 5  "
    txt(0, (W - len(title_str)) // 2, title_str, 'dim yellow')

    # Water
    inner = W - 2
    lake_label = " Lake Pontchartrain "
    waves = (inner - len(lake_label)) // 2
    lake_line = "≋" * waves + lake_label + "≋" * (inner - waves - len(lake_label))
    txt(1, 1, lake_line[:inner], 'cyan')

    for col in range(1, W - 1):
        r = _river_row_at(col)
        for rr in range(GLOBAL_TOP, r + 3):
            put(rr, col, '≋', 'cyan')
    river_label = " Mississippi River "
    lc = (W - len(river_label)) // 2
    txt(GLOBAL_TOP + 1, lc, river_label, 'cyan')

    # Neighborhood boxes
    hoods = get_all_neighborhoods(conn)
    hood_danger = {h["slug"]: h["danger"] for h in hoods}

    for slug, (row, col, display_name) in NEIGHBORHOOD_LAYOUT.items():
        factions = get_neighborhood_factions(conn, slug)
        danger   = hood_danger.get(slug, 2)
        here     = (slug == current_neighborhood_slug)
        neighborhood_box(row, col, display_name, factions, danger, here, markers.get(slug, []))

    # Danger side key (right of map, vertically centered)
    def _danger_row(symbol, label, style):
        t = Text()
        t.append('   ')
        t.append(symbol, style=style)
        t.append(f' {label}', style='dim white')
        return t

    key_items = [
        Text('   Danger:', style='bold white'),
        Text(''),
        _danger_row('░', 'low',    'green'),
        Text(''),
        _danger_row('▒', 'medium', 'yellow'),
        Text(''),
        _danger_row('▓', 'high',   'bold red'),
    ]
    key_start = (H - len(key_items)) // 2
    danger_side = {key_start + i: t for i, t in enumerate(key_items)}

    # Render
    LAND_BG = 'on rgb(28,12,2)'
    BOX_BG  = 'on black'

    def _unbold(st):
        if st is None:
            return None
        return st.replace('bold ', '')

    sio = StringIO()
    console = Console(file=sio, highlight=False)
    result = Text()
    for r in range(H):
        row_text = Text()
        for c in range(W):
            ch = canvas[r][c]
            st = styles[r][c]
            if 1 <= r < H - 1 and 1 <= c < W - 1 and ch != '≋':
                bg = BOX_BG if box_interior[r][c] else LAND_BG
                st = f'{st} {bg}' if st else bg
                if box_interior[r][c] and not active_int[r][c]:
                    st = _unbold(st)
            row_text.append(ch, style=st)
        if r in danger_side:
            row_text.append_text(danger_side[r])
        result.append_text(row_text)
        result.append('\n')
    console.print(result, end='')
    return sio.getvalue()


FACTION_LEGEND = (
    "  [bold blue]P[/] NOPD  "
    "[bold red]R[/] Rossi  "
    "[bold yellow]C[/] Castellano  "
    "[bold green]I[/] ILA 231  "
    "[bold magenta]L[/] Col. Longshoremen  "
    "[bold cyan]S[/] Shorties  "
    "[bold white]T[/] Tallboys  "
    "[yellow]A[/] Archdiocese"
)

MARKER_LEGEND = (
    "  [bold red]✦[/] Crime scene  "
    "[white]⌂[/] Premises  "
    "[bold yellow]⚑[/] Stakeout  "
    "[bold cyan]◉[/] Evidence  "
    "[bold green]☎[/] Contact  "
    "[dim white]✝[/] Church/mortuary  "
    "[bold yellow]⚜[/] Bar/tavern"
)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_map.py -v
```
Expected: all PASSes.

- [ ] **Step 6: Commit**

```bash
git add noir/map.py tests/test_map.py
git commit -m "feat: Rich ASCII map renderer (noir/map.py)"
```

---

## Task 6: Parser — add MAP intent

**Files:**
- Modify: `noir/parser.py`
- Modify: `tests/test_map.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_map.py

from noir.parser import parse_command, Intent


def test_parse_map_command():
    assert parse_command("map").intent == Intent.MAP


def test_parse_map_command_variants():
    assert parse_command("show map").intent == Intent.MAP
    assert parse_command("open map").intent == Intent.MAP
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_map.py::test_parse_map_command -v
```
Expected: FAIL — `Intent.MAP` not found.

- [ ] **Step 3: Add `MAP` to `Intent` enum and `_RULES` in `noir/parser.py`**

```python
class Intent(Enum):
    GO = auto()
    GO_DA = auto()
    GO_COURTHOUSE = auto()
    TALK = auto()
    TALK_PARTNER = auto()
    ARREST = auto()
    COLLECT = auto()
    EXAMINE = auto()
    LOOK = auto()
    HELP = auto()
    MAP = auto()          # ← add this
    SHOOT_PARTNER = auto()
    UNKNOWN = auto()
```

Add to `_RULES` before the `UNKNOWN` fallback:

```python
(r"^(?:map|show map|open map|view map)$", Intent.MAP, 0),
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_map.py -v
```
Expected: all PASSes.

- [ ] **Step 5: Commit**

```bash
git add noir/parser.py tests/test_map.py
git commit -m "feat: add MAP intent to parser"
```

---

## Task 7: Wire map command into game loop

**Files:**
- Modify: `noir/game.py`

- [ ] **Step 1: Add import and handler to `noir/game.py`**

In the import block at the top of `game.py`, add:

```python
from noir.map import render_map, FACTION_LEGEND, MARKER_LEGEND
```

Add `Intent.MAP` to the import from `noir.parser`:

```python
from noir.parser import parse_command, Intent
```
(already imported — just add `MAP` to the dispatch below)

In `Game.loop()`, find the `if cmd.intent == Intent.GO:` block and add the MAP handler before it:

```python
if cmd.intent == Intent.MAP:
    self.handle_map()
elif cmd.intent == Intent.GO:
    ...
```

Add the `handle_map` method to the `Game` class (near `handle_go`):

```python
def handle_map(self) -> None:
    from noir.neighborhoods import recompute_all_danger
    from noir.persistence.repository import get_neighborhood_for_location

    recompute_all_danger(self.conn)

    current_slug = None
    if self.current_location_id is not None:
        hood = get_neighborhood_for_location(self.conn, self.current_location_id)
        if hood:
            current_slug = hood["slug"]
    if current_slug is None:
        current_slug = "french_quarter"  # default starting neighborhood

    # Build markers from discovered case locations
    markers: dict[str, list[str]] = {}
    if self.active_case_id:
        discovered = get_discovered_locations_for_case(self.conn, self.active_case_id)
        for loc in discovered:
            hood = get_neighborhood_for_location(self.conn, loc["id"])
            if hood is None:
                continue
            slug = hood["slug"]
            loc_type = loc.get("location_type") or "⌂"
            markers.setdefault(slug, [])
            if loc_type not in markers[slug]:
                markers[slug].append(loc_type)

    rendered = render_map(self.conn, current_slug, markers)
    console.print()
    console.print(rendered, end='')
    console.print()
    console.print(FACTION_LEGEND)
    console.print(MARKER_LEGEND)
    console.print()
```

- [ ] **Step 2: Verify by running the game manually**

```bash
python main.py
```

Type `map` at the prompt. Expected: the ASCII map renders, with the French Quarter double-bordered (or whatever the player's current neighborhood is), faction codes, and danger bars visible. No crash.

- [ ] **Step 3: Commit**

```bash
git add noir/game.py
git commit -m "feat: wire map command into game loop"
```

---

## Task 8: Distance-based travel time

**Files:**
- Modify: `noir/game.py`
- Modify: `tests/test_neighborhoods.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_neighborhoods.py

from noir.neighborhoods import travel_time_minutes


def test_travel_time_adjacent():
    assert travel_time_minutes(distance=1, is_ferry=False) == 15


def test_travel_time_two_blocks():
    assert travel_time_minutes(distance=2, is_ferry=False) == 30


def test_travel_time_ferry_surcharge():
    assert travel_time_minutes(distance=2, is_ferry=True) == 45
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_neighborhoods.py -k "travel_time" -v
```
Expected: FAILs.

- [ ] **Step 3: Add `travel_time_minutes` to `noir/neighborhoods.py`**

```python
def travel_time_minutes(*, distance: int, is_ferry: bool) -> int:
    return distance * 15 + (15 if is_ferry else 0)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_neighborhoods.py -k "travel_time" -v
```
Expected: PASSes.

- [ ] **Step 5: Update `handle_go` in `noir/game.py` to use distance-based time**

Find this line in `handle_go` (currently around line 1274):

```python
advance_game_time(self.conn, delta=30)
```

Replace it with:

```python
# Compute travel time from neighborhood adjacency
_travel_delta = 30  # default (same neighborhood or no data)
_dest_hood = get_neighborhood_for_location(self.conn, loc["id"])
if _dest_hood and self.current_location_id is not None:
    _orig_hood = get_neighborhood_for_location(self.conn, self.current_location_id)
    if _orig_hood and _orig_hood["slug"] != _dest_hood["slug"]:
        from noir.neighborhoods import travel_time_minutes, is_algiers_crossing
        from noir.persistence.repository import get_travel_distance
        _dist = get_travel_distance(self.conn, _orig_hood["slug"], _dest_hood["slug"])
        if _dist is not None:
            _ferry = is_algiers_crossing(_orig_hood["slug"], _dest_hood["slug"])
            _travel_delta = travel_time_minutes(distance=_dist, is_ferry=_ferry)
advance_game_time(self.conn, delta=_travel_delta)
```

Add the missing imports at the top of `handle_go` (or at top of game.py imports):

```python
from noir.persistence.repository import get_neighborhood_for_location
```

- [ ] **Step 6: Run all tests**

```bash
pytest tests/ -v --tb=short
```
Expected: all PASSes.

- [ ] **Step 7: Commit**

```bash
git add noir/neighborhoods.py noir/game.py tests/test_neighborhoods.py
git commit -m "feat: distance-based travel time cost"
```

---

## Task 9: Seed neighborhoods on game start

**Files:**
- Modify: `noir/persistence/db.py`

`create_schema` already calls `seed_organizations` and `seed_faction_reputation` after migrations. We add `seed_neighborhoods` to the same flow.

- [ ] **Step 1: Add to `create_schema` in `noir/persistence/db.py`**

Find the end of `create_schema`:

```python
    _migrate_da_trust(conn)
```

Add after it:

```python
    try:
        from noir.neighborhoods import seed_neighborhoods, recompute_all_danger
        seed_neighborhoods(conn)
        recompute_all_danger(conn)
    except Exception:
        pass
```

- [ ] **Step 2: Verify with a full game reset**

```bash
python main.py --reset
```

Then type `map`. Expected: map renders with correct danger bars computed from faction opposition (not hardcoded values).

- [ ] **Step 3: Run tests**

```bash
pytest tests/ -v --tb=short
```
Expected: all PASSes.

- [ ] **Step 4: Commit**

```bash
git add noir/persistence/db.py
git commit -m "feat: auto-seed neighborhoods and danger on game start"
```

---

## Task 10: Assign existing fixed locations to neighborhoods

**Files:**
- Modify: `noir/neighborhoods.py`

Seeded locations in `seeded_locations` and `locations` tables have name/description hints we can use to assign `neighborhood_id`. This is a one-time migration run inside `seed_neighborhoods` after seeding the neighborhoods themselves.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_neighborhoods.py

from noir.persistence.repository import seed_locations_to_db


def test_fixed_locations_get_neighborhood(conn):
    seed_neighborhoods(conn)
    # Seed a location with a known neighborhood hint
    conn.execute(
        "INSERT OR IGNORE INTO locations (name, description, is_fixed) VALUES (?, ?, 1)",
        ("Café Du Monde", "A famous café in the French Quarter near Jackson Square.", 0)
    )
    conn.commit()
    from noir.neighborhoods import assign_locations_to_neighborhoods
    assign_locations_to_neighborhoods(conn)
    row = conn.execute(
        "SELECT neighborhood_id FROM locations WHERE name='Café Du Monde'"
    ).fetchone()
    assert row["neighborhood_id"] is not None
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_neighborhoods.py::test_fixed_locations_get_neighborhood -v
```
Expected: FAIL.

- [ ] **Step 3: Add `assign_locations_to_neighborhoods` to `noir/neighborhoods.py`**

```python
# Keyword hints for neighborhood assignment — checked against location name + description
_LOCATION_KEYWORDS: list[tuple[list[str], str]] = [
    (["french quarter", "bourbon", "royal street", "jackson square", "vieux carré", "café du monde"], "french_quarter"),
    (["treme", "tremé", "st. claude", "congo square"],                                                "treme"),
    (["garden district", "prytania", "coliseum square"],                                              "garden_district"),
    (["uptown", "tulane", "audubon"],                                                                 "uptown"),
    (["irish channel", "magazine street", "constance"],                                               "irish_channel"),
    (["cbd", "canal street", "poydras", "central business"],                                          "cbd"),
    (["mid-city", "mid city", "canal blvd", "city park"],                                             "mid_city"),
    (["marigny", "frenchmen street"],                                                                  "marigny"),
    (["bywater", "dauphine", "royal street bywater"],                                                  "bywater"),
    (["lower ninth", "lower 9th", "jourdan"],                                                          "lower_ninth"),
    (["seventh ward", "7th ward", "gentilly"],                                                         "seventh_ward"),
    (["algiers", "west bank", "patterson"],                                                             "algiers"),
]


def assign_locations_to_neighborhoods(conn: sqlite3.Connection) -> None:
    locs = conn.execute(
        "SELECT id, name, description FROM locations WHERE neighborhood_id IS NULL AND is_fixed=1"
    ).fetchall()
    for loc in locs:
        text = (loc["name"] + " " + (loc["description"] or "")).lower()
        for keywords, slug in _LOCATION_KEYWORDS:
            if any(kw in text for kw in keywords):
                nid = get_neighborhood_id(conn, slug)
                if nid:
                    conn.execute(
                        "UPDATE locations SET neighborhood_id=? WHERE id=?",
                        (nid, loc["id"])
                    )
                break
    conn.commit()
```

Add `assign_locations_to_neighborhoods(conn)` call inside `seed_neighborhoods` after the adjacency seeding.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_neighborhoods.py -v
```
Expected: all PASSes.

- [ ] **Step 5: Commit**

```bash
git add noir/neighborhoods.py tests/test_neighborhoods.py
git commit -m "feat: assign fixed locations to neighborhoods by keyword"
```

---

## Task 11: Bartender NPC seeding

**Files:**
- Modify: `noir/neighborhoods.py`
- Modify: `noir/game.py`

Bartenders are persistent world NPCs (no `case_id`). They are seeded once — if a bartender already exists for a neighborhood bar, skip it.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_neighborhoods.py

from unittest.mock import MagicMock
from noir.neighborhoods import seed_bartenders, get_bartender_for_neighborhood


def test_get_bartender_for_neighborhood_none_before_seeding(conn):
    seed_neighborhoods(conn)
    result = get_bartender_for_neighborhood(conn, "french_quarter")
    assert result is None


def test_seed_bartenders_creates_npcs(conn):
    seed_neighborhoods(conn)
    mock_llm = MagicMock()
    mock_llm.query.return_value = (
        '{"name": "Marie Tureaud", "sex": "female", "age": 38, '
        '"ethnicity": "Creole", "personality": "sharp and guarded", '
        '"bar_name": "The Gold Tooth", "bar_description": "A dim bar off Bourbon."}'
    )
    seed_bartenders(conn, mock_llm)
    result = get_bartender_for_neighborhood(conn, "french_quarter")
    assert result is not None
    assert result["name"] == "Marie Tureaud"


def test_seed_bartenders_idempotent(conn):
    seed_neighborhoods(conn)
    mock_llm = MagicMock()
    mock_llm.query.return_value = (
        '{"name": "Joe Blanc", "sex": "male", "age": 45, '
        '"ethnicity": "Cajun", "personality": "friendly", '
        '"bar_name": "The Rusty Nail", "bar_description": "A dive bar."}'
    )
    seed_bartenders(conn, mock_llm)
    seed_bartenders(conn, mock_llm)
    rows = conn.execute(
        "SELECT COUNT(*) FROM npcs WHERE role='bartender'"
    ).fetchone()[0]
    assert rows == 12  # exactly one per neighborhood
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_neighborhoods.py -k "bartender" -v
```
Expected: FAILs.

- [ ] **Step 3: Add bartender seeding to `noir/neighborhoods.py`**

```python
import json as _json

_BARTENDER_PROMPT = """You are generating a bartender NPC for a 1935 New Orleans detective RPG.
Neighborhood: {neighborhood_name}
Dominant factions: {factions}

Generate a bartender who fits this neighborhood's character. Return ONLY valid JSON:
{{
  "name": "Full Name",
  "sex": "male|female",
  "age": <integer 25-65>,
  "ethnicity": "e.g. Creole, Irish, Italian, Black Creole, Cajun",
  "personality": "2-3 word description",
  "bar_name": "Name of the bar",
  "bar_description": "One sentence describing the bar's atmosphere."
}}"""

_BARTENDER_SYSTEM_PROMPT = """You are a 1935 New Orleans bartender. You know your neighborhood well —
its regulars, its factions, its gossip — but you keep your own counsel.
You can reveal: the names of other establishments nearby, the mood on the street,
which factions have been causing trouble. You do NOT reveal case plot details.
Stay in character. Period-accurate language only. No modern slang."""


def get_bartender_for_neighborhood(conn: sqlite3.Connection, slug: str) -> sqlite3.Row | None:
    nid = get_neighborhood_id(conn, slug)
    if nid is None:
        return None
    return conn.execute(
        """SELECT n.* FROM npcs n
           JOIN locations l ON l.id = n.current_location_id
           WHERE n.role='bartender' AND l.neighborhood_id=?""",
        (nid,)
    ).fetchone()


def seed_bartenders(conn, llm) -> None:
    for slug, _, _, _ in _NEIGHBORHOODS:
        if get_bartender_for_neighborhood(conn, slug) is not None:
            continue

        nid = get_neighborhood_id(conn, slug)
        hood_row = conn.execute("SELECT name FROM neighborhoods WHERE id=?", (nid,)).fetchone()
        factions = get_neighborhood_factions(conn, slug)

        prompt = _BARTENDER_PROMPT.format(
            neighborhood_name=hood_row["name"],
            factions=", ".join(factions) if factions else "none"
        )
        try:
            raw = llm.query(prompt, system=_BARTENDER_SYSTEM_PROMPT)
            data = _json.loads(raw)
        except Exception:
            data = {
                "name": f"The Barkeep ({hood_row['name']})",
                "sex": "male",
                "age": 45,
                "ethnicity": "unknown",
                "personality": "quiet and watchful",
                "bar_name": f"The {hood_row['name']} Bar",
                "bar_description": "A no-frills neighborhood bar.",
            }

        bar_name = data.get("bar_name", f"The {hood_row['name']} Bar")
        bar_desc = data.get("bar_description", "A neighborhood bar.")

        loc_id = conn.execute(
            """INSERT OR IGNORE INTO locations (name, description, is_fixed, neighborhood_id)
               VALUES (?, ?, 1, ?) RETURNING id""",
            (bar_name, bar_desc, nid)
        ).fetchone()
        if loc_id is None:
            loc_id = conn.execute(
                "SELECT id FROM locations WHERE name=?", (bar_name,)
            ).fetchone()
        loc_id = loc_id["id"]
        conn.commit()

        system_prompt = (
            f"{_BARTENDER_SYSTEM_PROMPT}\n\n"
            f"Your name is {data['name']}. You work at {bar_name} in {hood_row['name']}. "
            f"Your personality: {data.get('personality', 'guarded')}."
        )
        conn.execute(
            """INSERT INTO npcs (case_id, name, role, system_prompt, current_location_id)
               VALUES (NULL, ?, 'bartender', ?, ?)""",
            (data["name"], system_prompt, loc_id)
        )
        conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_neighborhoods.py -k "bartender" -v
```
Expected: all PASSes.

- [ ] **Step 5: Wire `seed_bartenders` into game startup in `noir/game.py`**

In `Game.__init__` or the game startup flow, find where `seed_organizations` or `seed_faction_reputation` is called (search for `seed_organizations` — it's called inside `create_schema`). We call `seed_bartenders` separately because it needs the LLM backend.

Find the `Game` class `__init__` method. After `create_schema(self.conn)` is called, add:

```python
from noir.neighborhoods import seed_bartenders
seed_bartenders(self.conn, self.llm)
```

- [ ] **Step 6: Run all tests**

```bash
pytest tests/ -v --tb=short
```
Expected: all PASSes.

- [ ] **Step 7: Commit**

```bash
git add noir/neighborhoods.py noir/game.py tests/test_neighborhoods.py
git commit -m "feat: seed one bartender NPC per neighborhood"
```

---

## Task 12: Smoke test full flow

- [ ] **Step 1: Reset and run the game**

```bash
python main.py --reset
```

Complete onboarding, then:
1. Type `map` — verify the map renders cleanly with danger bars
2. Type `go to The Precinct` — verify travel time is deducted from game clock
3. Type `map` again — verify player marker (double-border) is on the correct neighborhood
4. Type `go to` a bar that was seeded as a bartender location — verify the bartender is present and conversable

- [ ] **Step 2: Run full test suite one final time**

```bash
pytest tests/ -v --tb=short
```
Expected: all PASSes.

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: map and neighborhoods — complete implementation"
```
