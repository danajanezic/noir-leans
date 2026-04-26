import sqlite3
import json as _json
from noir.jobs.factions import OPPOSITION

_NEIGHBORHOODS = [
    ("mid_city",        "Mid-City",          ["nopd", "shorties"]),
    ("treme",           "Treme",             ["nopd", "colored_longshoremen"]),
    ("seventh_ward",    "7th Ward",          ["nopd", "colored_longshoremen"]),
    ("garden_district", "Garden District",   ["nopd", "tallboys"]),
    ("cbd",             "CBD",               ["nopd", "rossi", "shorties"]),
    ("french_quarter",  "French Quarter",    ["nopd", "rossi", "archdiocese"]),
    ("marigny",         "Marigny",           ["castellano"]),
    ("uptown",          "Uptown",            ["nopd", "tallboys"]),
    ("irish_channel",   "Irish Channel",     ["ila_231", "nopd"]),
    ("bywater",         "Bywater",           ["ila_231", "colored_longshoremen"]),
    ("lower_ninth",     "Lower 9th Ward",    ["colored_longshoremen", "nopd"]),
    ("algiers",         "Algiers",           ["nopd", "ila_231"]),
]

_ADJACENCY = [
    ("uptown",          "garden_district",  1),
    ("garden_district", "cbd",              1),
    ("cbd",             "french_quarter",   1),
    ("cbd",             "mid_city",         1),
    ("cbd",             "irish_channel",    1),
    ("french_quarter",  "treme",            1),
    ("french_quarter",  "marigny",          1),
    ("french_quarter",  "algiers",          2),
    ("treme",           "mid_city",         1),
    ("treme",           "seventh_ward",     1),
    ("marigny",         "seventh_ward",     1),
    ("marigny",         "bywater",          1),
    ("irish_channel",   "uptown",           1),
    ("bywater",         "lower_ninth",      1),
    ("seventh_ward",    "mid_city",         1),
]

_ALGIERS_SIDE = {"algiers"}


def seed_neighborhoods(conn: sqlite3.Connection) -> None:
    for slug, name, factions in _NEIGHBORHOODS:
        conn.execute(
            "INSERT OR IGNORE INTO neighborhoods (slug, name) VALUES (?, ?)",
            (slug, name),
        )

    for slug, _name, factions in _NEIGHBORHOODS:
        nid = get_neighborhood_id(conn, slug)
        for faction in factions:
            conn.execute(
                "INSERT OR IGNORE INTO neighborhood_factions (neighborhood_id, faction) VALUES (?, ?)",
                (nid, faction),
            )

    for from_slug, to_slug, distance in _ADJACENCY:
        from_id = get_neighborhood_id(conn, from_slug)
        to_id = get_neighborhood_id(conn, to_slug)
        conn.execute(
            "INSERT OR IGNORE INTO neighborhood_adjacency (from_id, to_id, distance) VALUES (?, ?, ?)",
            (from_id, to_id, distance),
        )
        conn.execute(
            "INSERT OR IGNORE INTO neighborhood_adjacency (from_id, to_id, distance) VALUES (?, ?, ?)",
            (to_id, from_id, distance),
        )

    conn.commit()
    assign_locations_to_neighborhoods(conn)


def get_neighborhood_id(conn: sqlite3.Connection, slug: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM neighborhoods WHERE slug = ?", (slug,)
    ).fetchone()
    return row["id"] if row else None


def travel_time_minutes(*, distance: int, is_ferry: bool) -> int:
    return distance * 15 + (15 if is_ferry else 0)


def is_algiers_crossing(from_slug: str, to_slug: str) -> bool:
    return (from_slug in _ALGIERS_SIDE) != (to_slug in _ALGIERS_SIDE)


def compute_danger(faction_slugs: list[str]) -> int:
    danger = 1
    slugs = set(faction_slugs)
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


_LOCATION_KEYWORDS: list[tuple[list[str], str]] = [
    (["french quarter", "bourbon", "royal street", "jackson square", "vieux carré", "café du monde"], "french_quarter"),
    (["treme", "tremé", "st. claude", "congo square"],                                                "treme"),
    (["garden district", "prytania", "coliseum square"],                                              "garden_district"),
    (["uptown", "tulane", "audubon"],                                                                 "uptown"),
    (["irish channel", "magazine street", "constance"],                                               "irish_channel"),
    (["cbd", "canal street", "poydras", "central business"],                                          "cbd"),
    (["mid-city", "mid city", "canal blvd", "city park"],                                             "mid_city"),
    (["marigny", "frenchmen street"],                                                                  "marigny"),
    (["bywater", "dauphine"],                                                                          "bywater"),
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

_BARTENDER_SYSTEM = (
    "You are writing a character for a 1935 New Orleans detective RPG. "
    "Return ONLY valid JSON matching the format above. No other text."
)


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


def seed_bartenders(conn: sqlite3.Connection, llm) -> None:
    for slug, _, _ in _NEIGHBORHOODS:
        if get_bartender_for_neighborhood(conn, slug) is not None:
            continue

        nid = get_neighborhood_id(conn, slug)
        hood_row = conn.execute("SELECT name FROM neighborhoods WHERE id=?", (nid,)).fetchone()
        factions = [
            r["faction"] for r in conn.execute(
                "SELECT faction FROM neighborhood_factions WHERE neighborhood_id=?", (nid,)
            ).fetchall()
        ]

        prompt = _BARTENDER_PROMPT.format(
            neighborhood_name=hood_row["name"],
            factions=", ".join(factions) if factions else "none"
        )
        try:
            raw = llm.query(prompt, system=_BARTENDER_SYSTEM)
            data = _json.loads(raw)
        except Exception:
            data = {
                "name": "The Barkeep",
                "sex": "male",
                "age": 45,
                "ethnicity": "unknown",
                "personality": "quiet and watchful",
                "bar_name": f"The {hood_row['name']} Bar",
                "bar_description": "A no-frills neighborhood bar.",
            }

        bar_name = data.get("bar_name", f"The {hood_row['name']} Bar")
        bar_desc = data.get("bar_description", "A neighborhood bar.")

        result = conn.execute(
            "INSERT OR IGNORE INTO locations (name, description, is_fixed, neighborhood_id) VALUES (?, ?, 1, ?) RETURNING id",
            (bar_name, bar_desc, nid)
        ).fetchone()
        if result is None:
            result = conn.execute("SELECT id FROM locations WHERE name=?", (bar_name,)).fetchone()
        loc_id = result["id"]
        conn.commit()

        bartender_system = (
            f"You are {data['name']}, bartender at {bar_name} in {hood_row['name']}, 1935 New Orleans. "
            f"You know your neighborhood well — its regulars, its factions, its gossip — but you keep your own counsel. "
            f"You can share: names of nearby establishments, mood on the street, faction activity hints. "
            f"Stay in character. Period-accurate language only. No modern slang. No case plot details."
        )
        conn.execute(
            "INSERT INTO npcs (case_id, name, role, system_prompt, current_location_id) VALUES (NULL, ?, 'bartender', ?, ?)",
            (data["name"], bartender_system, loc_id)
        )
        conn.commit()
