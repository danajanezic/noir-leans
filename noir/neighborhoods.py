import sqlite3

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


def get_neighborhood_id(conn: sqlite3.Connection, slug: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM neighborhoods WHERE slug = ?", (slug,)
    ).fetchone()
    return row["id"] if row else None


def is_algiers_crossing(from_slug: str, to_slug: str) -> bool:
    return (from_slug in _ALGIERS_SIDE) != (to_slug in _ALGIERS_SIDE)
