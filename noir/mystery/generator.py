import json
import sqlite3
import random
from pathlib import Path
from noir.llm.base import LLMBackend
from noir.persistence.repository import (
    get_player, list_archetypes, get_archetype
)

REQUIRED_FIELDS = {"title", "victim", "killer_name", "motive", "suspects", "clues", "locations"}
REQUIRED_SUSPECT_FIELDS = {"name", "role", "alibi", "secret", "personality", "speech_style"}
REQUIRED_CLUE_FIELDS = {"description", "is_red_herring", "location"}
REQUIRED_LOCATION_FIELDS = {"name", "description"}

GENERATOR_SYSTEM_PROMPT = """You are a mystery generator for an absurdist noir detective game set in Noirleans, a city that exists somewhere between New Orleans and a fever dream. The year is 1935. The Great Depression has hollowed out the middle class and left the desperate and the corrupt to sort things out between themselves. Jazz plays from buildings with no electricity. Bread lines stretch past speakeasies. Everyone is either on the take or on the run.
Generate richly detailed, darkly comic mysteries. Characters should be over-the-top and memorable.
Causes of death should be absurd. Motives should be simultaneously petty and grandiose.
The setting is period-accurate 1930s: no phones in pockets, no computers, cash economy, Prohibition recently ended, fedoras mandatory.
Return ONLY valid JSON matching the requested schema. No prose, no markdown, just JSON."""


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

    def generate(self, archetype_name: str, theme: str | None = None) -> dict:
        player = get_player(self.conn)
        player_context = _build_player_context(player)

        archetype_row = get_archetype(self.conn, archetype_name)
        if archetype_row:
            archetype_prompt = archetype_row["seed_prompt"]
        else:
            archetype_prompt = f"Generate a mystery in the style of {archetype_name}."

        theme_text = f"\n\nAdditional theme to weave in: {theme}" if theme else ""

        prompt = (
            f"{archetype_prompt}{theme_text}\n\n"
            f"{player_context}\n\n"
            "Return a JSON object with this exact schema:\n"
            "{\n"
            '  "title": "string",\n'
            '  "victim": {"name": "string", "cause_of_death": "string", "found_at": "string (location name where body was discovered)"},\n'
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

    def pick_random_theme(self) -> str | None:
        themes_path = Path(__file__).parent / "themes.json"
        try:
            themes = json.loads(themes_path.read_text())
            return random.choice(themes) if themes else None
        except Exception:
            return None
