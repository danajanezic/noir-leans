import json
import sqlite3
import random
from pathlib import Path
from noir.llm.base import LLMBackend
from noir.persistence.repository import (
    get_player, list_archetypes, get_archetype, get_world_context as _get_world_context
)
from noir.mystery.auditor import CaseAuditor

REQUIRED_FIELDS = {"title", "victim", "killer_name", "motive", "suspects", "clues", "locations"}
REQUIRED_SUSPECT_FIELDS = {
    "name", "role", "alibi", "secret", "archetype_id", "race",
    "political_connections", "alignment", "age",
    "pressure_tolerance", "kindness_weight", "empathy",
    "starting_guilt", "revelation_style", "revelation_stages",
}
REQUIRED_CLUE_FIELDS = {"description", "is_red_herring", "location"}
REQUIRED_LOCATION_FIELDS = {"name"}

GENERATOR_SYSTEM_PROMPT = (
    _get_world_context() + "\n\n"
    "You are a mystery generator for this world. "
    "Generate richly detailed noir mysteries. Characters should be vivid and memorable. "
    "Causes of death should be specific, unexpected, and varied — they can be darkly comic, brutal, banal, or strange, but never generic. Motives should feel simultaneously petty and grandiose. "
    "ABSOLUTE PROHIBITION: The cause of death must NEVER involve drowning, submersion, or liquid suffocation in any form — no drowning in tureens, barrels, vats, rivers, bathtubs, pools, or any other vessel or body of water. Violating this rule invalidates the entire case. "
    "The setting is period-accurate 1935: no phones in pockets, no computers, cash economy, Prohibition recently ended, fedoras mandatory. "
    "Never use the word 'Negro' or any racial slur in any field. Refer to Black characters as Black. "
    "Return ONLY valid JSON matching the requested schema. No prose, no markdown, just JSON. "
    "For body_location: choose 'crime scene' roughly half the time (body still at the scene) and 'City Morgue' the other half (body removed). "
    "For body_clues: include 0-3 forensic details found on the body (wounds, ligature marks, objects in pockets, etc.) — "
    "sometimes there are none, sometimes one key clue. Place these in the body_clues array, not in the main clues array. "
    "In the main clues array, set the location of body-related clues to match body_location "
    "(either the crime scene location name, or 'City Morgue'). "
    "CLUE LOCATIONS: Each clue's location must match where it would logically be found. "
    "Forensic clues belong at the crime scene or City Morgue. "
    "Personal effects and correspondence belong at the victim's home or workplace. "
    "Financial records belong at an office, bank, or City Hall. "
    "Pawned or sold items belong at a pawn shop or business. "
    "Spread clues across the case's locations — at most half the clues should share the same location. "
    "NPC ROUTINES: Each NPC needs exactly 1-2 routine entries — no more. "
    "Place them at locations that reflect where this person actually lives or works. "
    "At least one entry must be at a location other than the crime scene."
)

DARK_PAST_CASE_SYSTEM_PROMPT = """You are a mystery generator for Noirleans, 1935. Generate a case directly tied to a partner's dark past — a crime they committed or were part of. The player must investigate this case knowing their partner is implicated. The tone is morally complex and personal. The partner should appear as a named NPC in the case (as a suspect or witness). Return ONLY valid JSON matching the case schema."""


def _case_schema(archetype_list: str, org_list: str) -> str:
    return (
        "{\n"
        '  "title": "string",\n'
        '  "victim": {"name": "string", "cause_of_death": "string", "found_at": "string (location name where body was discovered)"},\n'
        '  "body_location": "crime scene" or "City Morgue" (where the body currently is — at the crime scene or moved to the City Morgue),\n'
        '  "body_clues": ["string"] (0-3 forensic clues found on or with the body — wounds, marks, objects; can be empty []),\n'
        '  "killer_name": "string (must match one suspect name)",\n'
        '  "motive": "string",\n'
        '  "suspects": [\n'
        '    {"name": "string", "role": "suspect|witness|informant",\n'
        '     "sex": "male"|"female"|"nonbinary",\n'
        '     "race": "string (e.g. Black, white, Creole, Cajun, Italian, Irish)",\n'
        '     "political_connections": "string (e.g. none, alderman on payroll, police captain, organized crime)",\n'
        '     "alibi": "string", "secret": "string",\n'
        f'     "archetype_id": "string (MUST be one of: {archetype_list})",\n'
        '     "alignment": "string (one of: Lawful Good, Neutral Good, Chaotic Good, Lawful Neutral, True Neutral, Chaotic Neutral, Lawful Evil, Neutral Evil, Chaotic Evil)",\n'
        '     "age": integer,\n'
        '     "pressure_tolerance": integer 1-10,\n'
        '     "kindness_weight": integer 1-10,\n'
        '     "empathy": integer 1-10,\n'
        '     "starting_guilt": integer 0-10,\n'
        '     "revelation_style": "staged" or "sudden" — use "sudden" only for emotionally fragile or guilt-ridden characters who will crack all at once; use "staged" for controlled, criminal, or self-protective characters who reveal slowly under accumulating pressure,\n'
        '     "revelation_stages": integer (2-5 for staged; higher = harder to crack; 1 for sudden),\n'
        '     "routine": [{"location": "string (must be a case location name)", "time_start": "HH:MM", "time_end": "HH:MM"}] (1-2 entries — where this character can be found; at least one must NOT be the crime scene),\n'
        '     "relationships": [{"name": "string", "relationship": "string"}]}\n'
        '  ],\n'
        '  "clues": [\n'
        '    {"description": "string", "is_red_herring": boolean, "location": "string"}\n'
        '  ],\n'
        '  "locations": [\n'
        f'    {{"name": "string", "organizations": ["string"] (0-1 org names from this list that control this location: {org_list}; use [] if none apply; a single location should not be controlled by two rival criminal organizations)}}\n'
        '  ]\n'
        "}"
    )


def _build_npc_system_prompt(name: str, role: str, race: str,
                              political_connections: str, alibi: str, secret: str,
                              relationships_json: str, personality: str,
                              speech_style: str, backstory: str = "",
                              contact_locations: dict | None = None,
                              peer_descriptions: dict | None = None) -> str:
    import json as _j
    race_line = (
        f"Race/background: {race}. This shapes your experience of 1935 Noirleans — "
        "the spaces you can enter, who treats you with respect or contempt, "
        "what you can and cannot say to a white detective. "
    ) if race else ""
    political_line = (
        f"Political connections: {political_connections}. "
        "You know who protects you and you know how to use that knowledge. "
    ) if political_connections and political_connections.lower() not in ("none", "") else ""
    backstory_line = f"Your history: {backstory} " if backstory else ""
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
        if contact_locations and r["name"] in contact_locations:
            part += f" [PRIVATE: If the detective asks where to find {r['name']}, you can tell them: {contact_locations[r['name']]}. Do not volunteer this — only share it if directly asked how to reach them.]"
        rel_parts.append(part)
    rel_text = " ".join(rel_parts)
    peer_text = ""
    if peer_descriptions:
        lines = [f"{n}: {d}" for n, d in peer_descriptions.items()]
        peer_text = (
            " [PRIVATE — how others in this case look, so you can describe them if asked without using their name: "
            + "; ".join(lines) + "]"
        )
    return (
        f"You are {name}, a {role} in a murder investigation. "
        f"{backstory_line}"
        f"Personality: {personality}. Speech style: {speech_style}. "
        f"{race_line}"
        f"{political_line}"
        f"Your alibi (which may or may not be true): {alibi}. "
        f"Your secret: {secret}. "
        "You guard this with your life — you do not volunteer it, hint at it, or confirm it under casual questioning. "
        "You will only reveal it if the game system explicitly tells you to (you will see an instruction in brackets). "
        "Until that instruction appears, treat your secret as information you will take to the grave. "
        "You may deny, deflect, lie, change the subject, or go silent — but you do not crack."
        + (f" {rel_text}" if rel_text else "")
        + peer_text
        + " You are in Noirleans, 1935 — Depression-era, corrupt to the bone, "
        "jazz leaking out of every cracked window. Stay in character."
    )


def enrich_npc(conn, llm, npc_id: int) -> None:
    from noir.persistence.repository import (
        get_npc, update_npc_system_prompt, update_suspect_backstory,
        get_locations_for_case,
    )
    from noir.characters.npc_archetype_loader import get_npc_archetype

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

    import json as _j

    # Collect case locations for routine generation
    case_loc_names: list[str] = []
    if npc_row["case_id"] is not None:
        case_locs = get_locations_for_case(conn, npc_row["case_id"])
        case_loc_names = [l["name"] for l in case_locs]

    existing_rels: list[dict] = []
    try:
        existing_rels = _j.loads(suspect_row["relationships"] or "[]")
    except Exception:
        pass
    rel_names = [r.get("name", "") for r in existing_rels if r.get("name")]

    detail_result = llm.query_structured(
        "Generate detail fields for this 1935 Noirleans character. "
        "Return ONLY valid JSON matching the schema exactly — no extra fields, no markdown.",
        [],
        f"Character: {npc_row['name']}, role: {npc_row['role']}, race: {suspect_row['race']}, "
        f"alibi: {suspect_row['alibi']}, secret: {suspect_row['secret']}.\n"
        f"Case locations available: {', '.join(case_loc_names) or 'none'}.\n"
        f"Related characters: {', '.join(rel_names) or 'none'}.\n\n"
        "Return JSON with exactly this schema:\n"
        "{\n"
        '  "backstory": "one sentence about who they were before this case",\n'
        '  "physical_description": "one sentence: height, build, coloring, distinctive features, clothing (1935 era)",\n'
        '  "maiden_name": "string or null — married women\'s pre-marriage surname; null otherwise",\n'
        '  "shared_facts": {"<character_name>": ["fact1", "fact2"]} (1-2 facts per related character; {} if none)\n'
        "}"
    )

    backstory = detail_result.get("backstory", "")
    physical_description = detail_result.get("physical_description") or None
    maiden_name = detail_result.get("maiden_name") or None

    # Persist physical_description and maiden_name
    if physical_description or maiden_name:
        conn.execute(
            "UPDATE npcs SET physical_description=COALESCE(?, physical_description), "
            "maiden_name=COALESCE(?, maiden_name) WHERE id=?",
            (physical_description, maiden_name, npc_id)
        )
        conn.commit()

    # Merge shared_facts into relationships and persist
    shared_facts_map: dict[str, list] = {}
    try:
        shared_facts_map = detail_result.get("shared_facts") or {}
        if not isinstance(shared_facts_map, dict):
            shared_facts_map = {}
    except Exception:
        pass
    enriched_rels = []
    for r in existing_rels:
        rel = dict(r)
        facts = shared_facts_map.get(rel.get("name", ""), [])
        if facts:
            rel["shared_facts"] = facts
        enriched_rels.append(rel)
    if enriched_rels != existing_rels:
        conn.execute(
            "UPDATE suspects SET relationships=? WHERE npc_id=?",
            (_j.dumps(enriched_rels), npc_id)
        )
        conn.commit()

    contact_locations: dict[str, str] = {}
    for r in enriched_rels:
        rel_name = r.get("name")
        if not rel_name:
            continue
        npc_id_row = conn.execute(
            "SELECT n.id FROM npcs n WHERE n.case_id=? AND n.name=?",
            (npc_row["case_id"], rel_name),
        ).fetchone()
        if not npc_id_row:
            continue
        schedule_rows = conn.execute(
            "SELECT time_start, time_end, location_name FROM npc_schedules WHERE npc_id=?",
            (npc_id_row["id"],)
        ).fetchall()
        if schedule_rows:
            entries = [
                f"{s['location_name']} from {s['time_start']//60:02d}:{s['time_start']%60:02d}"
                f" to {s['time_end']//60:02d}:{s['time_end']%60:02d}"
                for s in schedule_rows
            ]
            contact_locations[rel_name] = "; ".join(entries)

    peer_descriptions: dict[str, str] = {}
    if npc_row["case_id"] is not None:
        for row in conn.execute(
            "SELECT name, physical_description FROM npcs "
            "WHERE case_id=? AND id!=? AND physical_description IS NOT NULL",
            (npc_row["case_id"], npc_id),
        ).fetchall():
            peer_descriptions[row["name"]] = row["physical_description"]

    system_prompt = _build_npc_system_prompt(
        name=npc_row["name"],
        role=npc_row["role"],
        race=suspect_row["race"] or "",
        political_connections=suspect_row["political_connections"] or "",
        alibi=suspect_row["alibi"] or "",
        secret=suspect_row["secret"] or "",
        relationships_json=_j.dumps(enriched_rels),
        personality=personality,
        speech_style=speech_style,
        backstory=backstory,
        contact_locations=contact_locations or None,
        peer_descriptions=peer_descriptions or None,
    )
    update_npc_system_prompt(conn, npc_id=npc_id, system_prompt=system_prompt)
    if backstory:
        update_suspect_backstory(conn, npc_id=npc_id, backstory=backstory)


def _pick_best_archetype(llm, archetypes: list, crime_summary: str) -> str:
    archetype_names = [a["name"] for a in archetypes]
    if not archetype_names:
        return "Agatha Christie"
    prompt = (
        f"Crime summary: {crime_summary}\n\n"
        f"Available archetypes: {', '.join(archetype_names)}\n\n"
        "Which archetype best fits this crime? Return ONLY valid JSON: "
        '{"archetype": "string (exact name from the list)"}'
    )
    result = llm.query_structured(
        "You are selecting the best mystery archetype for a specific crime. Return only valid JSON.",
        [],
        prompt
    )
    chosen = result.get("archetype", archetype_names[0])
    return chosen if chosen in archetype_names else archetype_names[0]


def _build_player_context(player: sqlite3.Row) -> str:
    reputation = player["reputation"] if player else 100
    cases_solved = player["cases_solved"] if player else 0
    wrong_arrests = player["wrong_arrests"] if player else 0

    if cases_solved == 0:
        difficulty = "easy"
        notes = "This is the player's first case. NPCs should be forthcoming. Clues should point clearly at the killer with minimal red herrings (1 max)."
    elif wrong_arrests > cases_solved:
        difficulty = "easy"
        notes = "Player struggles with wrong arrests. Keep red herrings obvious. NPCs should volunteer information."
    elif reputation > 80 and cases_solved > 3:
        difficulty = "medium"
        notes = "Experienced player with good reputation. 2-3 red herrings. NPCs are moderately forthcoming."
    else:
        difficulty = "easy"
        notes = "Developing player. 1-2 red herrings. NPCs lean toward being helpful."

    return (
        f"Player profile: difficulty={difficulty}, cases_solved={cases_solved}, "
        f"wrong_arrests={wrong_arrests}, reputation={reputation}. "
        f"Calibration notes: {notes}"
    )


def _validate_case(case: dict) -> bool:
    if not REQUIRED_FIELDS.issubset(case.keys()):
        return False
    if not isinstance(case["suspects"], list) or len(case["suspects"]) < 2:
        return False
    for suspect in case["suspects"]:
        if not REQUIRED_SUSPECT_FIELDS.issubset(suspect.keys()):
            return False
        for int_field in ("age", "pressure_tolerance", "kindness_weight",
                          "empathy", "starting_guilt", "revelation_stages"):
            if not isinstance(suspect.get(int_field), int):
                return False
        if suspect.get("revelation_style") not in ("staged", "sudden"):
            return False
    if not isinstance(case["clues"], list) or len(case["clues"]) < 1:
        return False
    for clue in case["clues"]:
        if not REQUIRED_CLUE_FIELDS.issubset(clue.keys()):
            return False
    if not isinstance(case["locations"], list) or len(case["locations"]) < 1:
        return False
    for loc in case["locations"]:
        if not REQUIRED_LOCATION_FIELDS.issubset(loc.keys()):
            return False
    return True


class MysteryGenerator:

    def __init__(self, *, llm: LLMBackend, conn: sqlite3.Connection):
        self.llm = llm
        self.conn = conn

    def _recent_names(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT case_data FROM cases ORDER BY id DESC LIMIT 6"
        ).fetchall()
        names = []
        recent_names: list[str] = []
        for i, r in enumerate(rows):
            try:
                cd = json.loads(r["case_data"])
                victim = cd.get("victim", {}).get("name", "")
                tokens = []
                if victim:
                    tokens.extend(victim.split())
                for s in cd.get("suspects", []):
                    tokens.extend(s.get("name", "").split())
                names.extend(tokens)
                if i < 2:
                    recent_names.extend(tokens)
            except Exception:
                pass
        from collections import Counter
        last_names = [n for n in names if len(n) > 3]
        recurring = [n for n, c in Counter(last_names).items() if c > 1]
        # Always ban every name from the two most-recent cases, not just recurring ones
        for n in recent_names:
            if len(n) > 3 and n not in recurring:
                recurring.append(n)

        # always ban the partner's family name
        partner_row = self.conn.execute("SELECT name FROM partner WHERE id=1").fetchone()
        if partner_row and partner_row["name"]:
            partner_last = partner_row["name"].split()[-1]
            if partner_last not in recurring:
                recurring.append(partner_last)

        return recurring

    def _recent_causes(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT case_data FROM cases ORDER BY id DESC LIMIT 6"
        ).fetchall()
        causes = []
        for r in rows:
            try:
                cd = json.loads(r["case_data"])
                c = cd.get("victim", {}).get("cause_of_death", "")
                if c:
                    causes.append(c)
            except Exception:
                pass
        return causes

    def _recent_crime_scenes(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT case_data FROM cases ORDER BY id DESC LIMIT 4"
        ).fetchall()
        scenes = []
        for r in rows:
            try:
                cd = json.loads(r["case_data"])
                loc = cd.get("victim", {}).get("found_at", "")
                if loc:
                    scenes.append(loc)
            except Exception:
                pass
        return scenes

    def generate(self, archetype_name: str, theme: str | None = None) -> dict:
        from noir.characters.npc_archetype_loader import archetype_ids
        from noir.persistence.repository import get_seeded_location_names
        import random
        _archetype_list = ", ".join(archetype_ids())
        _location_pool = get_seeded_location_names(self.conn)
        _loc_sample = random.sample(_location_pool, min(40, len(_location_pool))) if _location_pool else []
        _location_list = "\n".join(f"- {n}" for n in _loc_sample)
        _org_list = ", ".join(
            r[0] for r in self.conn.execute("SELECT name FROM organizations ORDER BY influence DESC").fetchall()
        )

        player = get_player(self.conn)
        player_context = _build_player_context(player)

        archetype_row = get_archetype(self.conn, archetype_name)
        if archetype_row:
            archetype_prompt = archetype_row["seed_prompt"]
        else:
            archetype_prompt = f"Generate a mystery in the style of {archetype_name}."

        theme_text = f"\n\nAdditional theme to weave in: {theme}" if theme else ""

        recent_names = self._recent_names()
        names_text = (
            f"\n\nDo NOT reuse these family names that have already appeared: {', '.join(recent_names)}. "
            "Every character must have a distinct, era-appropriate name."
        ) if recent_names else ""
        names_text += (
            "\n\nCRITICAL NAME RULE: Within this case, no two characters may share a family name "
            "unless they are explicitly written as relatives (e.g. siblings, spouses). "
            "The victim, killer, and every suspect must have distinct family names."
        )

        recent_causes = self._recent_causes()
        avoid_text = (
            f"\n\nDo NOT use any of these recently used causes of death: {', '.join(recent_causes)}. "
            "Be inventive — causes of death should be specific, unexpected, and varied. "
            "They can be brutal, ironic, banal, or strange — the only requirement is that "
            "they feel particular to this victim, this place, this moment. "
            "Avoid any form of drowning. Do not use generic causes like 'shot', 'stabbed', 'poisoned' without specific detail."
        ) if recent_causes else (
            "\n\nThe cause of death must be specific and particular — not generic. "
            "Avoid any form of drowning. Avoid: shot, stabbed, poisoned used without vivid detail. "
            "The cause should feel tied to this victim, this setting, this world."
        )

        recent_scenes = self._recent_crime_scenes()
        scenes_text = (
            f"\n\nDo NOT use any of these recently used crime scene locations: {', '.join(recent_scenes)}. "
            "The murder must happen somewhere new."
        ) if recent_scenes else ""

        schema = _case_schema(_archetype_list, _org_list)
        prompt = (
            f"{archetype_prompt}{theme_text}{avoid_text}{names_text}{scenes_text}\n\n"
            f"{player_context}\n\n"
            f"Available locations to choose from (pick 4-6 for this case):\n{_location_list}\n\n"
            f"Return a JSON object with this exact schema:\n{schema}"
        )

        case = self.llm.query_structured(GENERATOR_SYSTEM_PROMPT, [], prompt)

        if not _validate_case(case):
            missing = REQUIRED_FIELDS - set(case.keys())
            error_msg = (
                f"The case JSON is missing or malformed. Missing top-level fields: {missing or 'none — check suspect fields'}.\n"
                f"Locations MUST be chosen from this list:\n{_location_list}\n\n"
                f"{names_text}\n\n"
                f"{avoid_text}\n\n"
                f"{scenes_text}\n\n"
                f"Return a corrected JSON object using exactly this schema:\n{schema}"
            )
            case = self.llm.query_structured(GENERATOR_SYSTEM_PROMPT, [], error_msg)
            if not _validate_case(case):
                self.llm._fatal()

        auditor = CaseAuditor(llm=self.llm)
        case = auditor.audit_and_fix(case, GENERATOR_SYSTEM_PROMPT)
        if not _validate_case(case):
            self.llm._fatal()

        return case

    def pick_random_archetype(self) -> str:
        archetypes = list_archetypes(self.conn)
        if not archetypes:
            return "Agatha Christie"
        return random.choice(archetypes)["name"]

    def generate_from_dark_past(self, crime_summary: str, theme: str, partner_name: str) -> tuple[dict, str]:
        from noir.characters.npc_archetype_loader import archetype_ids
        from noir.persistence.repository import get_seeded_location_names
        import random
        _archetype_list = ", ".join(archetype_ids())
        _location_pool = get_seeded_location_names(self.conn)
        _loc_sample = random.sample(_location_pool, min(40, len(_location_pool))) if _location_pool else []
        _location_list = "\n".join(f"- {n}" for n in _loc_sample)
        _org_list = ", ".join(
            r[0] for r in self.conn.execute("SELECT name FROM organizations ORDER BY influence DESC").fetchall()
        )

        player = get_player(self.conn)
        player_context = _build_player_context(player)
        archetypes = list_archetypes(self.conn)
        archetype_name = _pick_best_archetype(self.llm, archetypes, crime_summary)

        schema = _case_schema(_archetype_list, _org_list)
        recent_names = self._recent_names()
        banned_names_text = (
            f"Do NOT reuse these family names: {', '.join(recent_names)}. "
        ) if recent_names else ""

        prompt = (
            f"This case is built around the following crime from the detective's partner's past:\n"
            f"{crime_summary}\n\n"
            f"The partner's name is {partner_name} — they must appear as a named suspect or witness.\n"
            f"Theme: {theme}\n\n"
            f"{player_context}\n\n"
            f"{banned_names_text}"
            "CRITICAL NAME RULE: Within this case, no two characters may share a family name "
            "unless they are explicitly written as relatives. The victim and every suspect must have distinct family names.\n\n"
            "Generate the case. The partner should be implicated but not obviously guilty — "
            "the player must investigate to understand what really happened. "
            f"Available locations to choose from (pick 4-6 for this case):\n{_location_list}\n\n"
            f"Return a JSON object with this exact schema:\n{schema}"
        )

        case = self.llm.query_structured(DARK_PAST_CASE_SYSTEM_PROMPT, [], prompt)
        if not _validate_case(case):
            missing = REQUIRED_FIELDS - set(case.keys())
            error_msg = (
                f"The case JSON is missing or malformed. Missing top-level fields: {missing or 'none — check suspect fields'}.\n"
                f"Locations MUST be chosen from this list:\n{_location_list}\n\n"
                + (f"{banned_names_text}\n\n" if banned_names_text else "")
                + f"Return a corrected JSON object using exactly this schema:\n{schema}"
            )
            case = self.llm.query_structured(DARK_PAST_CASE_SYSTEM_PROMPT, [], error_msg)
            if not _validate_case(case):
                self.llm._fatal()

        if case.get("killer_name", "").lower() == partner_name.lower():
            correction = (
                f"The generated case incorrectly sets {partner_name} as the killer. "
                f"{partner_name} must appear as a suspect or witness but must NOT be killer_name. "
                "Regenerate with a different killer who is actually guilty."
            )
            case = self.llm.query_structured(DARK_PAST_CASE_SYSTEM_PROMPT, [], correction)
            if not _validate_case(case) or case.get("killer_name", "").lower() == partner_name.lower():
                self.llm._fatal()

        auditor = CaseAuditor(llm=self.llm)
        case = auditor.audit_and_fix(case, DARK_PAST_CASE_SYSTEM_PROMPT)
        if not _validate_case(case):
            self.llm._fatal()

        return case, archetype_name

    def pick_random_theme(self) -> str | None:
        themes_path = Path(__file__).parent / "themes.json"
        try:
            themes = json.loads(themes_path.read_text())
            return random.choice(themes) if themes else None
        except Exception:
            return None
