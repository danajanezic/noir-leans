"""Item catalog and inventory utilities for the player detective."""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)

# Path to jobs archetypes JSON (used for required_items lookup)
_JOBS_ARCHETYPES_PATH = Path(__file__).parent / "jobs" / "archetypes.json"

# ---------------------------------------------------------------------------
# Item catalog
# ---------------------------------------------------------------------------

ITEM_CATALOG = [
    {
        "slug": "camera",
        "name": "Camera",
        "description": "A battered box camera — catches folks in the act when the light's right.",
        "price": 12,
        "consumable": 0,
        "requires_slug": "film",
        "actions": {"photograph": {"consumes": "film"}},
    },
    {
        "slug": "film",
        "name": "Roll of Film",
        "description": "A roll of photographic film. Fits the box camera. Develops twelve exposures.",
        "price": 2,
        "consumable": 1,
        "requires_slug": None,
        "actions": {},
    },
    {
        "slug": "lockpicks",
        "name": "Lockpick Set",
        "description": "A slim leather roll of picks and tension wrenches — useful when doors won't open politely.",
        "price": 8,
        "consumable": 0,
        "requires_slug": None,
        "actions": {"pick": {}},
    },
    {
        "slug": "binoculars",
        "name": "Binoculars",
        "description": "Navy-surplus field glasses. Good for watching from a distance without being seen.",
        "price": 15,
        "consumable": 0,
        "requires_slug": None,
        "actions": {"observe": {}},
    },
    {
        "slug": "revolver_38",
        "name": ".38 Revolver",
        "description": "A snub-nosed .38 Special. Reliable at close quarters. Needs ammunition.",
        "price": 35,
        "consumable": 0,
        "requires_slug": "ammo_38",
        "actions": {"brandish": {}, "shoot": {"consumes": "ammo_38"}},
    },
    {
        "slug": "ammo_38",
        "name": ".38 Ammunition",
        "description": "A box of .38 Special cartridges. Six rounds, standard load.",
        "price": 4,
        "consumable": 1,
        "requires_slug": None,
        "actions": {},
    },
    {
        "slug": "bribe_envelope",
        "name": "Bribe Envelope",
        "description": "A plain envelope stuffed with walking-around money. Greases palms without a word.",
        "price": 2,
        "consumable": 1,
        "requires_slug": None,
        "actions": {"bribe": {"consumes": "bribe_envelope"}},
    },
    {
        "slug": "disguise_kit",
        "name": "Disguise Kit",
        "description": "A satchel of makeup, false whiskers, and cheap costumes. Changes a face well enough to fool a stranger.",
        "price": 18,
        "consumable": 0,
        "requires_slug": None,
        "actions": {"disguise": {}},
    },
]

# Slug-keyed lookup
_SLUG_TO_ITEM: dict = {item["slug"]: item for item in ITEM_CATALOG}

# ---------------------------------------------------------------------------
# Natural-language phrase mappings for detect_item_action
# ---------------------------------------------------------------------------

ACTION_PHRASES: dict[tuple, list[str]] = {
    ("camera", "photograph"): [
        "take a picture", "take a photo", "photograph", "snap a photo",
        "snap a picture", "shoot a photo", "get a shot", "take a shot",
        "capture on film", "use the camera",
    ],
    ("lockpicks", "pick"): [
        "pick the lock", "pick the door", "use the lockpicks", "use my picks",
        "jimmy the lock", "crack the lock",
    ],
    ("binoculars", "observe"): [
        "use the binoculars", "use my binoculars", "look through the glasses",
        "watch from afar", "observe from a distance", "glass the place",
        "peer through the binoculars",
    ],
    ("revolver_38", "brandish"): [
        "draw my gun", "pull my gun", "show the gun", "brandish the revolver",
        "pull the revolver", "flash the piece",
    ],
    ("revolver_38", "shoot"): [
        "shoot", "fire the gun", "fire the revolver", "pull the trigger",
        "open fire",
    ],
    ("bribe_envelope", "bribe"): [
        "bribe", "slip them money", "hand over the envelope",
        "grease their palm", "pay them off", "offer a bribe",
    ],
    ("disguise_kit", "disguise"): [
        "put on a disguise", "use the disguise kit", "change my appearance",
        "put on a costume", "disguise myself",
    ],
}

# Keyword fallback: maps individual keywords -> (item_slug, action_name)
_KEYWORD_MAP: dict[str, tuple] = {
    # camera / photograph
    "picture": ("camera", "photograph"),
    "photo": ("camera", "photograph"),
    "photograph": ("camera", "photograph"),
    "snapshot": ("camera", "photograph"),
    "film": ("camera", "photograph"),
    # lockpicks / pick
    "lock": ("lockpicks", "pick"),
    "lockpick": ("lockpicks", "pick"),
    "jimmy": ("lockpicks", "pick"),
    # binoculars / observe
    "binoculars": ("binoculars", "observe"),
    "glasses": ("binoculars", "observe"),
    "observe": ("binoculars", "observe"),
    # revolver / brandish
    "gun": ("revolver_38", "brandish"),
    "revolver": ("revolver_38", "brandish"),
    "pistol": ("revolver_38", "brandish"),
    "piece": ("revolver_38", "brandish"),
    # revolver / shoot (more specific — checked after brandish)
    "shoot": ("revolver_38", "shoot"),
    "fire": ("revolver_38", "shoot"),
    # bribe / bribe
    "bribe": ("bribe_envelope", "bribe"),
    "envelope": ("bribe_envelope", "bribe"),
    "palm": ("bribe_envelope", "bribe"),
    # disguise / disguise
    "disguise": ("disguise_kit", "disguise"),
    "costume": ("disguise_kit", "disguise"),
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_item_def(slug: str) -> Optional[dict]:
    """Return item dict for *slug*, or None if not found."""
    return _SLUG_TO_ITEM.get(slug)


def get_job_required_items(archetype_slug: str) -> list:
    """Return the required_items list for the given job archetype slug, or []."""
    try:
        with open(_JOBS_ARCHETYPES_PATH, "r", encoding="utf-8") as fh:
            archetypes = json.load(fh)
        for arch in archetypes:
            if arch.get("slug") == archetype_slug:
                return arch.get("required_items", [])
    except Exception:
        pass
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
    inventory: dict,
    conn: sqlite3.Connection,
) -> Optional[tuple]:
    """Return (item_slug, action_name) from player text, or None.

    Only returns a result if the player actually owns the item (inventory has qty > 0).
    Tries semantic similarity via noir.memory if available, falls back to keywords.
    """
    owned = {slug for slug, qty in inventory.items() if qty > 0}
    if not owned:
        return None

    # --- Semantic path (optional) ---
    best: Optional[tuple] = None
    try:
        import noir.memory as _mem
        if _mem.is_available():
            import numpy as _np
            text_emb = _mem._encode(text)

            best_score = 0.0
            for (item_slug, action_name), phrases in ACTION_PHRASES.items():
                if item_slug not in owned:
                    continue
                for phrase in phrases:
                    phrase_emb = _mem._encode(phrase)
                    # cosine similarity
                    denom = (_np.linalg.norm(text_emb) * _np.linalg.norm(phrase_emb))
                    if denom == 0:
                        continue
                    score = float(_np.dot(text_emb, phrase_emb) / denom)
                    if score > best_score:
                        best_score = score
                        best = (item_slug, action_name)

            if best_score >= 0.75:
                return best
    except Exception:
        pass

    # --- Keyword fallback ---
    lower = text.lower()
    for keyword, (item_slug, action_name) in _KEYWORD_MAP.items():
        if keyword in lower and item_slug in owned:
            return (item_slug, action_name)

    return None


# ---------------------------------------------------------------------------
# DB seeding
# ---------------------------------------------------------------------------

def seed_item_definitions(conn: sqlite3.Connection) -> None:
    """INSERT OR IGNORE all items from ITEM_CATALOG into item_definitions."""
    for item in ITEM_CATALOG:
        conn.execute(
            """INSERT OR IGNORE INTO item_definitions
               (slug, name, description, price, consumable, requires_slug, actions)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                item["slug"],
                item["name"],
                item["description"],
                item["price"],
                item["consumable"],
                item["requires_slug"],
                json.dumps(item["actions"]),
            ),
        )
    conn.commit()
