import sqlite3
import random
from noir.llm.base import LLMBackend
from noir.persistence.repository import (
    get_player, list_archetypes, get_archetype
)

REQUIRED_FIELDS = {"title", "victim", "killer_name", "motive", "suspects", "clues", "locations"}
REQUIRED_SUSPECT_FIELDS = {"name", "role", "alibi", "secret", "personality", "speech_style"}
REQUIRED_CLUE_FIELDS = {"description", "is_red_herring", "location"}
REQUIRED_LOCATION_FIELDS = {"name", "description"}

GENERATOR_SYSTEM_PROMPT = """You are a mystery generator for an absurdist noir detective game.
Generate richly detailed, darkly comic mysteries. Characters should be over-the-top and memorable.
Causes of death should be absurd. Motives should be simultaneously petty and grandiose.
Return ONLY valid JSON matching the requested schema. No prose, no markdown, just JSON."""

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

    def generate(self, archetype_name: str) -> dict:
        player = get_player(self.conn)
        player_context = _build_player_context(player)

        archetype_row = get_archetype(self.conn, archetype_name)
        if archetype_row:
            archetype_prompt = archetype_row["seed_prompt"]
        else:
            archetype_prompt = f"Generate a mystery in the style of {archetype_name}."

        prompt = (
            f"{archetype_prompt}\n\n"
            f"{player_context}\n\n"
            "Return a JSON object with this exact schema:\n"
            "{\n"
            '  "title": "string",\n'
            '  "victim": {"name": "string", "cause_of_death": "string"},\n'
            '  "killer_name": "string (must match one suspect name)",\n'
            '  "motive": "string",\n'
            '  "suspects": [\n'
            '    {"name": "string", "role": "suspect|witness|informant",\n'
            '     "alibi": "string", "secret": "string",\n'
            '     "personality": "string", "speech_style": "string"}\n'
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

        prompt = (
            f"This case is built around the following crime from the detective's partner's past:\n"
            f"{crime_summary}\n\n"
            f"The partner's name is {partner_name} — they must appear as a named suspect or witness.\n"
            f"Theme: {theme}\n\n"
            f"{player_context}\n\n"
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
            '     "alibi": "string", "secret": "string",\n'
            '     "personality": "string", "speech_style": "string",\n'
            '     "relationships": [{"name": "string", "relationship": "string"}]}\n'
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
            case = self.llm.query_structured(DARK_PAST_CASE_SYSTEM_PROMPT, [], prompt)
            if not _validate_case(case):
                self.llm._fatal()

        return case, archetype_name

    def pick_random_theme(self) -> str:
        themes = [
            "the lengths people will go to for love",
            "loyalty that became a trap",
            "a debt that could never be repaid",
            "the moment an ordinary person crossed a line",
            "what fear makes people capable of",
            "the difference between justice and revenge",
            "survival at someone else's expense",
        ]
        return random.choice(themes)
