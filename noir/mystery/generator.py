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
REQUIRED_SUSPECT_FIELDS = {"name", "role", "alibi", "secret", "personality", "speech_style", "race", "political_connections", "backstory", "routine", "alignment", "age"}
REQUIRED_CLUE_FIELDS = {"description", "is_red_herring", "location"}
REQUIRED_LOCATION_FIELDS = {"name", "description"}

GENERATOR_SYSTEM_PROMPT = (
    _get_world_context() + "\n\n"
    "You are a mystery generator for this world. "
    "Generate richly detailed, darkly comic mysteries. Characters should be over-the-top and memorable. "
    "Causes of death should be absurd. Motives should be simultaneously petty and grandiose. "
    "The setting is period-accurate 1935: no phones in pockets, no computers, cash economy, Prohibition recently ended, fedoras mandatory. "
    "Never use the word 'Negro' or any racial slur in any field. Refer to Black characters as Black. "
    "Return ONLY valid JSON matching the requested schema. No prose, no markdown, just JSON."
)

DARK_PAST_CASE_SYSTEM_PROMPT = """You are a mystery generator for Noirleans, 1935. Generate a case directly tied to a partner's dark past — a crime they committed or were part of. The player must investigate this case knowing their partner is implicated. The tone is morally complex and personal. The partner should appear as a named NPC in the case (as a suspect or witness). Return ONLY valid JSON matching the case schema."""


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
        for r in rows:
            try:
                cd = json.loads(r["case_data"])
                victim = cd.get("victim", {}).get("name", "")
                if victim:
                    names.extend(victim.split())
                for s in cd.get("suspects", []):
                    names.extend(s.get("name", "").split())
            except Exception:
                pass
        from collections import Counter
        last_names = [n for n in names if len(n) > 3]
        recurring = [n for n, c in Counter(last_names).items() if c > 1]

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

    def generate(self, archetype_name: str, theme: str | None = None) -> dict:
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
            "Be inventive — causes of death should be absurd, specific, and varied. "
            "Examples of the kind of variety expected: trampled by escaped circus elephant, "
            "drowned in a vat of bootleg rum, death by trombone (blunt force), "
            "electrocuted by a faulty neon sign, buried alive in a shipment of oysters, "
            "suffocated by an exceptionally large bribe."
        ) if recent_causes else (
            "\n\nThe cause of death must be specific and absurd — not generic. "
            "Avoid: poison, shooting, stabbing used plainly. "
            "Instead: trampled by escaped circus elephant, drowned in bootleg rum, "
            "death by trombone, electrocuted by faulty neon sign."
        )

        prompt = (
            f"{archetype_prompt}{theme_text}{avoid_text}{names_text}\n\n"
            f"{player_context}\n\n"
            "Return a JSON object with this exact schema:\n"
            "{\n"
            '  "title": "string",\n'
            '  "victim": {"name": "string", "cause_of_death": "string", "found_at": "string (location name where body was discovered)"},\n'
            '  "killer_name": "string (must match one suspect name)",\n'
            '  "motive": "string",\n'
            '  "suspects": [\n'
            '    {"name": "string", "role": "suspect|witness|informant",\n'
            '     "race": "string (e.g. Black, white, Creole, Cajun, Italian, Irish — reflect the real demographic diversity of 1930s New Orleans)",\n'
            '     "political_connections": "string (e.g. none, alderman on payroll, police captain, judge, city council, organized crime, none — who protects them in 1935 Noirleans)",\n'
            '     "alibi": "string", "secret": "string",\n'
            '     "backstory": "string (2-3 sentences: who they were before this case, what shaped them, what they want)",\n'
            '     "personality": "string", "speech_style": "string",\n'
            '     "alignment": "string (one of: Lawful Good, Neutral Good, Chaotic Good, Lawful Neutral, True Neutral, Chaotic Neutral, Lawful Evil, Neutral Evil, Chaotic Evil — assign based on this character\'s role, morality, and relationship to authority)",\n'
            '     "age": "integer — the character\'s age in 1935. Guidelines: law enforcement / legal professionals: 28–65; working adults (merchants, laborers, clerks): 20–60; young adults (students, apprentices): 18–30. CRITICAL: respect relationship logic — a father must be at least 18 years older than his child, an employer typically older than an apprentice, a mentor older than their protégé. All ages are as of 1935.",\n'
            '     "routine": [{"time_start": "HH:MM", "time_end": "HH:MM", "location": "string (location name from the locations list, or \'home\' if unavailable)"}],\n'
            '     "relationships": [{"name": "string", "relationship": "string", "shared_facts": ["string — specific verifiable facts you both know, e.g. how long you\'ve worked together, where you first met, a shared event"]}]}\n'
            '  ],\n'
            '  "clues": [\n'
            '    {"description": "string", "is_red_herring": boolean, "location": "string"}\n'
            '  ],\n'
            '  "locations": [\n'
            '    {"name": "string", "description": "string"}\n'
            '  ]\n'
            "}"
        )

        case = self.llm.query_structured(GENERATOR_SYSTEM_PROMPT, [], prompt)

        if not _validate_case(case):
            error_msg = (
                f"The generated case is missing required fields or has invalid structure.\n"
                f"Required top-level fields: {REQUIRED_FIELDS}\n"
                f"Generated case keys: {set(case.keys())}\n"
                "Please regenerate with the complete schema."
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
        player = get_player(self.conn)
        player_context = _build_player_context(player)
        archetypes = list_archetypes(self.conn)
        archetype_name = _pick_best_archetype(self.llm, archetypes, crime_summary)

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
            "Return a JSON object with this exact schema:\n"
            "{\n"
            '  "title": "string",\n'
            '  "victim": {"name": "string", "cause_of_death": "string", "found_at": "string"},\n'
            '  "killer_name": "string (must match one suspect name)",\n'
            '  "motive": "string",\n'
            '  "suspects": [\n'
            '    {"name": "string", "role": "suspect|witness|informant",\n'
            '     "race": "string (e.g. Black, white, Creole, Cajun, Italian, Irish — reflect the real demographic diversity of 1930s New Orleans)",\n'
            '     "political_connections": "string (e.g. none, alderman on payroll, police captain, judge, city council, organized crime, none — who protects them in 1935 Noirleans)",\n'
            '     "alibi": "string", "secret": "string",\n'
            '     "backstory": "string (2-3 sentences: who they were before this case, what shaped them, what they want)",\n'
            '     "personality": "string", "speech_style": "string",\n'
            '     "alignment": "string (one of: Lawful Good, Neutral Good, Chaotic Good, Lawful Neutral, True Neutral, Chaotic Neutral, Lawful Evil, Neutral Evil, Chaotic Evil — assign based on this character\'s role, morality, and relationship to authority)",\n'
            '     "age": "integer — the character\'s age in 1935. Guidelines: law enforcement / legal professionals: 28–65; working adults (merchants, laborers, clerks): 20–60; young adults (students, apprentices): 18–30. CRITICAL: respect relationship logic — a father must be at least 18 years older than his child, an employer typically older than an apprentice, a mentor older than their protégé. All ages are as of 1935.",\n'
            '     "routine": [{"time_start": "HH:MM", "time_end": "HH:MM", "location": "string (location name from the locations list, or \'home\' if unavailable)"}],\n'
            '     "relationships": [{"name": "string", "relationship": "string", "shared_facts": ["string — specific verifiable facts you both know, e.g. how long you\'ve worked together, where you first met, a shared event"]}]}\n'
            '  ],\n'
            '  "clues": [\n'
            '    {"description": "string", "is_red_herring": boolean, "location": "string"}\n'
            '  ],\n'
            '  "locations": [\n'
            '    {"name": "string", "description": "string"}\n'
            '  ]\n'
            "}"
        )

        case = self.llm.query_structured(DARK_PAST_CASE_SYSTEM_PROMPT, [], prompt)
        if not _validate_case(case):
            error_msg = (
                f"The generated case is missing required fields or has invalid structure.\n"
                f"Required top-level fields: {REQUIRED_FIELDS}\n"
                f"Generated case keys: {set(case.keys())}\n"
                "Please regenerate with the complete schema."
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
