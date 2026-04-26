# Player Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a player inventory system with purchasable items, item requirements on jobs/cases, and action-based consumable usage.

**Architecture:** Two new DB tables (`item_definitions`, `player_items`) seeded at startup. Item requirements live in `archetypes.json`. Purchases happen through conversation with a new permanent pawn shop NPC. Item actions are triggered via `/use [item] [action]` or embedding-matched natural language, consuming the appropriate consumables.

**Tech Stack:** SQLite (existing), sentence-transformers (existing optional memory module), Rich terminal UI (existing)

---

## Item Catalog

| slug | name | price | consumable | requires_slug | actions |
|---|---|---|---|---|---|
| camera | Camera | $12 | no | film | photograph (consumes film) |
| film | Roll of Film | $2 | yes | — | — |
| lockpicks | Lockpick Set | $8 | no | — | pick |
| binoculars | Binoculars | $15 | no | — | observe |
| revolver_38 | .38 Revolver | $35 | no | ammo_38 | brandish, shoot (consumes ammo_38) |
| ammo_38 | .38 Ammunition | $4/box of 10 | yes | — | — |
| bribe_envelope | Bribe Envelope | $2 | yes | — | bribe (consumes self) |
| disguise_kit | Disguise Kit | $18 | no | — | disguise |

Ammo is always sold in boxes of 10 — purchasing adds 10 to quantity.

---

## Schema

### `item_definitions` table
```sql
CREATE TABLE item_definitions (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    price INTEGER NOT NULL,
    consumable INTEGER DEFAULT 0,
    requires_slug TEXT,
    actions TEXT DEFAULT '{}',
    FOREIGN KEY (requires_slug) REFERENCES item_definitions(slug)
);
```

`actions` is a JSON object mapping action name → `{"consumes": slug_or_null}`. Example:
```json
{"photograph": {"consumes": "film"}, "brandish": {}, "shoot": {"consumes": "ammo_38"}}
```

### `player_items` table
```sql
CREATE TABLE player_items (
    item_slug TEXT PRIMARY KEY,
    quantity INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (item_slug) REFERENCES item_definitions(slug)
);
```

Both tables added via `_MIGRATIONS` in `noir/persistence/db.py`. Item catalog seeded at startup via `seed_item_definitions(conn)` in a new `noir/items.py` module. `create_schema` calls `seed_item_definitions` after migrations.

---

## Pawn Shop & Shopkeeper

New fixed location: **"Treme Pawn & Loan"** — added to `FIXED_LOCATION_ORGS` (no org affiliation, independent) and to the fixed location seed list.

New permanent NPC in `FIXED_LOCATION_NPCS`:

**Clarence Dufour** — Creole proprietor, been running the shop since 1919. Knows what things are worth. Asks no questions about provenance. Doesn't discuss his customers. When the player talks to him, he describes what's in stock and what it costs. Purchases happen through conversation.

Purchase detection: after each NPC response in a conversation with Dufour, a lightweight LLM structured call checks:
```json
{"item_purchased": "slug_or_null", "quantity": integer}
```
Same pattern as bribe/job-offer detection. If a purchase is detected, `player_items` is updated and `update_player_cash(conn, delta=-price)` is called. Ammo purchases always set quantity to +10 regardless of what the LLM returns.

---

## Item Requirements on Archetypes

`archetypes.json` gets an optional `required_items` field on each archetype entry:

```json
"required_items": [
  {"slug": "camera", "needs_consumable": true}
]
```

`needs_consumable: true` means both the tool AND its linked consumable must be present. `false` means the tool alone suffices.

Initial requirements:
- `cheating_spouse` → `[{"slug": "camera", "needs_consumable": true}]`
- `surveillance` → `[{"slug": "binoculars", "needs_consumable": false}]`
- `shadow_operation` → `[{"slug": "binoculars", "needs_consumable": false}]`
- `debt_collection` → `[{"slug": "revolver_38", "needs_consumable": false}]`

---

## Item Checks

### On Arrival (soft nudge via partner)
When `handle_go` moves the player to a new location and the active job has `required_items`:
- Check if any required items (or their consumables) are missing from `player_items`
- If missing, the partner delivers an in-character nudge: *"You're going to need a camera and film for this."*
- Not a hard block — the player can still enter the location

### On `/done` (hard block)
Before completing a job, check `required_items` against inventory. If any required item or needed consumable is missing, block with in-character message and return without completing. Consumable items are decremented by 1 on successful completion.

---

## Item Actions

### Explicit: `/use [item] [action]`
e.g. `/use camera photograph` — validates item is in inventory, action is valid, consumable present if needed, then decrements consumable and records the action.

### Natural language: embedding detection
Each action has reference phrases stored in `noir/items.py`:
```python
ACTION_PHRASES = {
    ("camera", "photograph"): [
        "I photograph them", "take a picture", "snap a photo",
        "use the camera", "I pull out my camera",
    ],
    ("revolver_38", "shoot"): [...],
    ...
}
```

After the player types input in any context (conversation or exploration), the input is compared against reference phrases using sentence-transformer cosine similarity. Threshold: 0.75. If matched, action is triggered. Keyword fallback when memory module is not installed.

---

## Display

### `/items`
Panel showing owned items. Non-consumables show `✓`. Consumables show quantity. Items not owned are not shown.

```
┌─ What You're Carrying ──────────────────────────────┐
│  Camera              ✓   For documentation work.    │
│  Roll of Film        3   One roll per job.           │
│  .38 Revolver        ✓   Loaded or not, it makes    │
│                          a point.                   │
│  .38 Ammunition      10  Keep it dry.               │
└─────────────────────────────────────────────────────┘
```

### `/job` (active job view)
After the steps list, if the archetype has `required_items`, show a `Required:` line. Items already owned shown dim. Missing items shown in yellow.

### `/classifieds` board
Each job listing shows required items inline below the objective if `required_items` is non-empty:
```
1. [Tier 1] Domestic Inquiry — Private — $60
   Confirm or deny a client's suspicion about their partner.
   Requires: Camera, Roll of Film
```

---

## New Files
- `noir/items.py` — item catalog, seeding function, action phrases, embedding detection helper

## Modified Files
- `noir/persistence/db.py` — 2 new migrations, `seed_item_definitions` call in `create_schema`
- `noir/persistence/repository.py` — `get_player_items`, `add_player_item`, `use_item` (decrement consumable)
- `noir/jobs/archetypes.json` — `required_items` on relevant archetypes
- `noir/game.py` — `/items` command, `/use` command, arrival check, `/done` check, purchase detection in Dufour conversation, display updates in `/job` and `/classifieds`
- `noir/display.py` — `/items` panel renderer, required items display helpers
- `FIXED_LOCATION_NPCS` in `noir/game.py` — Clarence Dufour entry
- `FIXED_LOCATION_ORGS` in `noir/organizations.py` — Treme Pawn & Loan
