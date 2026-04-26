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

FACTION_HOME_LOCATION: dict[str, str] = {
    "da_office":            "The DA's Office",
    "nopd":                 "The Precinct",
    "parish_govt":          "City Hall",
    "state_govt":           "City Hall",
    "judiciary":            "The Courthouse",
    "bar_association":      "The Courthouse",
    "rossi":                "Rossi's",
    "castellano":           "The Marigny Room",
    "shorties":             "The Rusty Anchor",
    "tallboys":             "The Rusty Anchor",
    "ila_231":              "The Rusty Anchor",
    "colored_longshoremen": "The Rusty Anchor",
    "chamber":              "City Hall",
    "naacp":                "The Diner",
    "treme_club":           "The Diner",
    "press":                "The Diner",
    "archdiocese":          "The Diner",
    "athletic_club":        "The Diner",
    "knights_columbus":     "The Diner",
}

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


def seed_job_client_npc(conn: sqlite3.Connection, job: dict) -> None:
    """Create the job's client NPC in the world if they don't already exist."""
    try:
        import json
        data = json.loads(job["case_data"]) if isinstance(job["case_data"], str) else (job.get("case_data") or {})
    except Exception:
        return

    client_name = (data.get("client_npc_name") or "").strip()
    if not client_name:
        return

    if conn.execute("SELECT id FROM npcs WHERE name=?", (client_name,)).fetchone():
        return

    faction = job.get("faction") or "private"
    faction_name = FACTIONS.get(faction, {}).get("name", faction)
    objective = data.get("objective", "")

    home_loc_name = FACTION_HOME_LOCATION.get(faction)
    location_id = None
    if home_loc_name:
        loc = conn.execute("SELECT id FROM locations WHERE name=?", (home_loc_name,)).fetchone()
        if loc:
            location_id = loc["id"]

    system_prompt = (
        f"You are {client_name}, a figure connected to {faction_name} in 1935 New Orleans. "
        f"You have hired a detective for the following job: {objective}. "
        f"You are businesslike and guarded. Speak in period-appropriate 1935 Louisiana register. "
        f"Do not discuss matters unrelated to the job. Do not break character."
    )

    conn.execute(
        "INSERT INTO npcs (name, role, current_location_id, system_prompt) VALUES (?, ?, ?, ?)",
        (client_name, "client", location_id, system_prompt)
    )
    conn.commit()


_NON_PERSON_PREFIXES = (
    "sealed", "a ", "an ", "the ", "individuals", "unauthorized", "city ",
    "patrons", "documents", "records", "evidence", "information", "visitors",
    "anyone", "whoever", "after-hours", "unauthorized",
)

_TARGET_BEHAVIOR: dict[str, str] = {
    "skip_trace": (
        "You have been missing for several days — laying low, avoiding questions. "
        "You are nervous around strangers and will not immediately explain yourself. "
        "Trust must be earned before you open up about where you've been or why. "
        "If cornered or threatened, you may crack or bolt."
    ),
    "debt_collection": (
        "You owe money and know someone may come to collect. "
        "You are evasive — claim the debt is disputed or that you'll pay when you can. "
        "You are tense. If you feel cornered, you may get aggressive or try to leave."
    ),
    "serve_papers": (
        "You know legal papers are being served and have been deliberately avoiding them. "
        "You will deny your identity or claim the named party isn't here. "
        "If cornered, you may try to leave suddenly."
    ),
    "cheating_spouse": (
        "You are carrying on a private relationship you have no intention of discussing with strangers. "
        "You are discreet and will deny anything personal if asked directly. "
        "If confronted with evidence, you may become defensive, pleading, or angry."
    ),
    "surveillance": (
        "You are going about your normal business, unaware of being watched. "
        "You speak naturally about your work and daily routine. "
        "You are not obviously hiding anything, though you keep certain associations private."
    ),
    "shadow_operation": (
        "You are going about your business unaware of being followed. "
        "You deflect questions about your recent movements without obvious suspicion. "
        "You have meetings and destinations you consider private."
    ),
    "witness_protection": (
        "You have information that puts you in danger and you know it. "
        "You are frightened and do not trust easily — anyone could be working for the other side. "
        "If the detective can convince you they are genuine, you will talk. Until then, you stall."
    ),
}


def _extract_target_name(target_str: str) -> str | None:
    """Return a person's name from a job target description, or None if target is not a person."""
    if not target_str:
        return None
    lower = target_str.lower()
    if any(lower.startswith(p) for p in _NON_PERSON_PREFIXES):
        return None
    name_part = target_str.split(",")[0].split(" and ")[0].strip()
    words = name_part.split()
    if not words or not words[0][0].isupper():
        return None
    return " ".join(words[:4])


def _step_location_id(conn: sqlite3.Connection, steps: list) -> int | None:
    """Return the location_id of the first fixed location mentioned in the job steps."""
    fixed = {
        row["name"].lower(): row["id"]
        for row in conn.execute("SELECT id, name FROM locations WHERE is_fixed=1").fetchall()
    }
    for step in steps:
        desc = step.get("description", "").lower()
        for loc_name, loc_id in fixed.items():
            if loc_name in desc:
                return loc_id
    return None


def seed_job_target_npc(conn: sqlite3.Connection, job: dict) -> None:
    """Create the job's target NPC in the world if the target is a person and doesn't exist yet."""
    try:
        import json
        data = json.loads(job["case_data"]) if isinstance(job["case_data"], str) else (job.get("case_data") or {})
    except Exception:
        return

    target_name = _extract_target_name(data.get("target", ""))
    if not target_name:
        return
    if conn.execute("SELECT id FROM npcs WHERE name=?", (target_name,)).fetchone():
        return

    archetype = data.get("job_archetype", "")
    behavior = _TARGET_BEHAVIOR.get(archetype, (
        "You are going about your business in 1935 New Orleans. "
        "You are not looking for trouble, but you are guarded with strangers."
    ))
    objective = data.get("objective", "")

    system_prompt = (
        f"You are {target_name}, a resident of 1935 New Orleans. "
        f"{behavior} "
        f"The detective investigating this matter is working on: {objective}. "
        f"Speak in period-appropriate 1935 Louisiana register. Do not break character."
    )

    location_id = _step_location_id(conn, data.get("steps", []))

    conn.execute(
        "INSERT INTO npcs (name, role, current_location_id, system_prompt) VALUES (?, ?, ?, ?)",
        (target_name, "target", location_id, system_prompt)
    )
    conn.commit()


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
