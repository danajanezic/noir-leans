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
    "rossi":                {"direct": ["castellano"],                                               "secondary": ["nopd", "da_office"]},
    "castellano":           {"direct": ["rossi"],                                                    "secondary": ["nopd", "da_office"]},
    "shorties":             {"direct": ["tallboys"],                                                 "secondary": []},
    "tallboys":             {"direct": ["shorties", "naacp", "treme_club", "colored_longshoremen"],  "secondary": []},
    "chamber":              {"direct": ["ila_231", "colored_longshoremen"],                          "secondary": ["naacp", "treme_club"]},
    "nopd":                 {"direct": ["rossi", "castellano"],                                      "secondary": ["naacp", "treme_club"]},
    "da_office":            {"direct": ["rossi", "castellano"],                                      "secondary": []},
    "naacp":                {"direct": ["tallboys", "chamber"],                                      "secondary": ["nopd"]},
    "ila_231":              {"direct": ["chamber"],                                                  "secondary": []},
    "colored_longshoremen": {"direct": ["chamber"],                                                  "secondary": []},
    "treme_club":           {"direct": ["nopd", "chamber"],                                          "secondary": ["tallboys"]},
}

TIER_REP_THRESHOLDS = {1: 0, 2: 25, 3: 60}
TIER_REP_GAINS      = {1: 8,  2: 20, 3: 40}
TIER_REP_LOSSES     = {1: 10, 2: 20, 3: 40}
OPPOSITION_PENALTY_DIRECT    = 8
OPPOSITION_PENALTY_SECONDARY = 4
TENSION_THRESHOLD   = 40
TENSION_ESCALATION  = 60

ORG_NAME_TO_FACTION: dict[str, str] = {
    "Orleans Parish Government":                          "parish_govt",
    "Louisiana State Government":                         "state_govt",
    "New Orleans Police Department":                      "nopd",
    "Orleans Parish Judiciary":                           "judiciary",
    "Rossi Crime Family":                                 "rossi",
    "Castellano Crime Family":                            "castellano",
    "International Longshoremen's Association Local 231": "ila_231",
    "Colored Longshoremen's Association":                 "colored_longshoremen",
    "Archdiocese of New Orleans":                         "archdiocese",
    "New Orleans Athletic Club":                          "athletic_club",
    "Knights of Columbus":                                "knights_columbus",
    "Treme Social Aid and Pleasure Club":                 "treme_club",
    "Noirleans Bar Association":                          "bar_association",
    "Shorties":                                           "shorties",
    "Tallboys":                                           "tallboys",
    "Chamber of Commerce":                                "chamber",
    "NAACP New Orleans Chapter":                          "naacp",
    "The Press":                                          "press",
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


_FACTION_DEFAULTS: dict[str, int] = {
    "da_office": 100,  # matches legacy player.da_trust default
}


def seed_faction_reputation(conn: sqlite3.Connection) -> None:
    for slug in ALL_FACTION_SLUGS:
        default = _FACTION_DEFAULTS.get(slug, 0)
        conn.execute(
            "INSERT OR IGNORE INTO faction_reputation (faction, reputation) VALUES (?, ?)",
            (slug, default)
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
