# Map & Neighborhoods — Design Spec

**Date:** 2026-04-26
**Status:** Approved for implementation

---

## Overview

Add a neighborhood layer to Noir-Leans: a Rich-rendered ASCII map the player can pull up at any time, a neighborhoods table that groups locations, distance-based travel costs, and seeded bartender NPCs in every neighborhood. Faction territory is tracked at the **location** level (not the neighborhood level), and co-present opposing factions drive the neighborhood danger rating.

---

## 1. The Map

A one-shot Rich canvas render — no terminal takeover, no curses. The player types `map` and sees the full city printed above the prompt, then the game continues normally.

### Layout

- **Canvas:** 94 × 31 characters, outer double-line frame
- **Water:** Lake Pontchartrain (row 1, full width); Mississippi River (flood-filled crescent, rows 20–24 depending on column)
- **Land background:** `rgb(28,12,2)` dark brown
- **Box interiors:** `on black`

### Neighborhood Boxes

Each box is 16 wide × 5 tall (`BW=16, BH=5`). Interior rows:
- Row 1: neighborhood name, centered, `bold white`
- Row 2: faction codes, centered, one letter per faction separated by spaces
- Row 3: danger bar (5 chars), centered — `░` green (1–2), `▒` yellow (3), `▓` bold red (4–5)

Current location gets a **double-line border** (`╔══╗`) in `bold white`; all others get a **single-line dim border** (`┌──┐`).

### Neighborhoods & Column Anchors

```
Columns: A=2  B=20  C=38  D=56  E=74
Rows:    R2=3  R3=9  R4=15

R2:  Mid-City (B)    Tremé (C)       7th Ward (D)
R3:  Garden Dist (A) CBD (B)         French Qtr (C)  Marigny (D)
R4:  Uptown (A)      Irish Ch. (B)                   Bywater (D)   Lower 9th (E)
     Algiers (C, row 25 — below the river)
```

### Faction Codes on Map

| Code | Faction | Color |
|------|---------|-------|
| P | NOPD | bold blue |
| R | Rossi Crime Family | bold red |
| C | Castellano Crime Family | bold yellow |
| I | ILA Local 231 | bold green |
| L | Colored Longshoremen's Association | bold magenta |
| S | Shorties | bold cyan |
| T | Tallboys | bold white |
| A | Archdiocese of New Orleans | yellow |

Faction presence shown on the map is **neighborhood-level** (which factions have significant presence). The danger bar is derived from faction opposition relationships at runtime (see §4).

---

## 2. Database Schema

### `neighborhoods` table

```sql
CREATE TABLE neighborhoods (
    id          INTEGER PRIMARY KEY,
    slug        TEXT UNIQUE NOT NULL,   -- e.g. "french_quarter"
    name        TEXT NOT NULL,          -- e.g. "French Quarter"
    danger      INTEGER NOT NULL DEFAULT 2  -- 1-5, recomputed at runtime
);
```

### `locations` table — add `neighborhood_id`

```sql
ALTER TABLE locations ADD COLUMN neighborhood_id INTEGER REFERENCES neighborhoods(id);
```

All existing seeded locations get assigned a `neighborhood_id` during migration based on their name/description. New case-generated locations inherit the neighborhood of their parent fixed location.

### `neighborhood_factions` table

Tracks which factions have territory presence in each neighborhood (for map display).

```sql
CREATE TABLE neighborhood_factions (
    neighborhood_id INTEGER NOT NULL REFERENCES neighborhoods(id),
    faction         TEXT NOT NULL,
    PRIMARY KEY (neighborhood_id, faction)
);
```

### `neighborhood_adjacency` table

Undirected graph stored as directed pairs (both directions seeded). Distance is in abstract "blocks" (1 = adjacent, 2 = one neighborhood apart, etc.).

```sql
CREATE TABLE neighborhood_adjacency (
    from_id     INTEGER NOT NULL REFERENCES neighborhoods(id),
    to_id       INTEGER NOT NULL REFERENCES neighborhoods(id),
    distance    INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (from_id, to_id)
);
```

---

## 3. Travel & Time Cost

Currently travel is instant. With neighborhoods, travel costs **game time** proportional to distance.

- **1 block away** (adjacent): 15 minutes
- **2 blocks:** 30 minutes
- **3 blocks:** 45 minutes
- **Algiers** (across the river): +15 minutes (ferry surcharge) on top of distance cost

### Travel Event Probability

Each travel leg rolls against an event probability table. Base chance = `distance × 5%`. Events are not implemented in this spec — the infrastructure (rolling on travel, passing distance to the event system) is.

### Adjacency Map (seeded data)

```
Uptown       ↔ Garden District (1)
Garden Dist  ↔ CBD (1)
CBD          ↔ French Quarter (1)
CBD          ↔ Mid-City (1)
French Qtr   ↔ Tremé (1)
French Qtr   ↔ Marigny (1)
French Qtr   ↔ Algiers (2, ferry)
Tremé        ↔ Mid-City (1)
Tremé        ↔ 7th Ward (1)
Marigny      ↔ 7th Ward (1)
Marigny      ↔ Bywater (1)
Irish Ch.    ↔ Uptown (1)
Irish Ch.    ↔ CBD (1)
Bywater      ↔ Lower 9th (1)
7th Ward     ↔ Mid-City (1)
```

---

## 4. Danger Rating

Neighborhood danger (1–5) is computed at runtime from faction co-presence using `OPPOSITION` in `noir/jobs/factions.py`:

- Base danger: 1
- For each pair of factions present in the neighborhood that are **direct** opponents: +2
- For each **secondary** opposition pair: +1
- Clamp to [1, 5]

This replaces the hardcoded danger values in `map_prototype.py`. The `neighborhoods.danger` column caches the last computed value; it is recomputed on game load and after any faction reputation change.

---

## 5. Bartender NPCs

Every neighborhood gets exactly one seeded bartender NPC tied to a bar in that neighborhood. Bartenders use the existing `NPC` / `Agent` conversation system fully — including affection tracking, romance eligibility, and relationship notes.

### Seeding

- On first run (or `--reset`), `MysteryGenerator` seeds one bartender per neighborhood
- Bartender identity (name, gender, ethnicity, personality) is generated by a single LLM call using a neighborhood-flavored prompt
- The bartender is stored in `characters` and linked to a fixed bar `location` in their neighborhood
- Bartenders are **not** tied to any case; they persist across all cases

### Information Role

Bartenders have access to neighborhood-local rumors. When interrogated, they can:
- Reveal other fixed locations in the neighborhood (new `go to` targets)
- Surface faction activity hints (flavor, not plot-critical)
- Give general mood/atmosphere for the neighborhood

This is implemented as NPC system-prompt context — no new mechanics, just seeded knowledge in their prompt.

---

## 6. Integration Points

| System | Change |
|--------|--------|
| `noir/persistence/db.py` | Add `neighborhoods`, `neighborhood_factions`, `neighborhood_adjacency` tables; migrate `locations` to add `neighborhood_id` |
| `noir/persistence/repository.py` | Add queries: get neighborhood for location, get adjacency/distance, get bartender for neighborhood |
| `noir/game.py` | `go to` command computes travel time via adjacency; `map` command renders the map |
| `noir/world.py` | No change required |
| `noir/mystery/generator.py` | Seed bartender NPCs on first run |
| `map_prototype.py` | Promote to `noir/display/map.py`; danger computed from factions at runtime |
| `noir/parser.py` | Add `map` as a recognized intent |

---

## 7. Out of Scope

- Travel events (infrastructure only — no event content)
- Per-neighborhood weather or time-of-day atmosphere
- Player-visible adjacency graph / route planning
- Faction territory changing over time
