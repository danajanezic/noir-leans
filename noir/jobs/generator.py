import json
import random
import sqlite3
from pathlib import Path
from noir.llm.base import LLMBackend
from noir.surnames import apply_job_surname_overrides

_ARCHETYPES_PATH = Path(__file__).parent / "archetypes.json"
_ARCHETYPES: list[dict] | None = None

_SYSTEM = (
    "You are generating a job assignment for a 1935 noir detective game set in Noirleans, Louisiana. "
    "Return ONLY valid JSON matching the exact structure requested. "
    "All names, locations, and details must be period-appropriate for 1935 New Orleans. "
    "NPCs must have authentic 1930s Louisiana names — draw from Creole, Cajun, Italian, Irish, "
    "and African-American naming traditions common to New Orleans. "
    "Use varied, distinct first names: e.g. Odette, Tomas, Félix, Rosalie, Beaumont, Léonce, "
    "Marguerite, Antoine, Céleste, Raoul, Isidore, Nadège, Émile, Delphine, Aristide. "
    "NEVER use 'Clem', 'Clement', or any variant. "
    "NEVER reuse names of established characters such as Roy, Arceneaux, or Thibodaux. "
    "Only use locations from the provided list — never invent new ones."
)


def _load_archetypes() -> list[dict]:
    global _ARCHETYPES
    if _ARCHETYPES is None:
        _ARCHETYPES = json.loads(_ARCHETYPES_PATH.read_text())
    return _ARCHETYPES


def _archetypes_for(faction: str, tier: int) -> list[dict]:
    all_archetypes = _load_archetypes()
    return [
        a for a in all_archetypes
        if a["tier"] == tier and (faction in a["factions"] or "any" in a["factions"])
    ]


def _fixed_locations(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM locations WHERE is_fixed=1 ORDER BY name"
    ).fetchall()
    return [r["name"] for r in rows]


def _used_first_names(conn: sqlite3.Connection) -> list[str]:
    """Collect first names already in use across NPCs and job case_data."""
    seen: set[str] = set()

    for row in conn.execute("SELECT name FROM npcs").fetchall():
        first = row["name"].split()[0].rstrip(",.")
        seen.add(first)

    for row in conn.execute(
        "SELECT case_data FROM cases WHERE case_type='job'"
    ).fetchall():
        try:
            data = json.loads(row["case_data"])
        except (json.JSONDecodeError, TypeError):
            continue
        for field in ("client_npc_name", "target"):
            val = data.get(field, "")
            if isinstance(val, str) and val:
                first = val.split()[0].rstrip(",.")
                seen.add(first)

    return sorted(seen)


class JobGenerator:

    def __init__(self, llm: LLMBackend, conn: sqlite3.Connection):
        self.llm = llm
        self.conn = conn

    def generate(self, *, faction: str, tier: int,
                 archetype_slug: str | None = None) -> dict | None:
        eligible = _archetypes_for(faction, tier)
        if not eligible:
            return None
        if archetype_slug:
            archetype = next((a for a in eligible if a["slug"] == archetype_slug), None)
            if archetype is None:
                return None
        else:
            archetype = random.choice(eligible)

        locations = _fixed_locations(self.conn)
        payout = random.randint(*archetype["payout_range"])
        used_names = _used_first_names(self.conn)

        prompt = (
            f"Faction: {faction}\n"
            f"Job type: {archetype['slug']} — {archetype['description']}\n"
            f"Tier: {tier}\n"
            f"Available locations (use only these): {', '.join(locations[:25])}\n"
            + (f"First names already in use — do NOT reuse any of these: {', '.join(used_names)}\n"
               if used_names else "")
            + "\n"
            f"Generate a specific job. Return JSON:\n"
            f'{{"objective": "one sentence describing what the detective must do", '
            f'"job_archetype": "{archetype["slug"]}", '
            f'"client_npc_name": "name of the NPC hiring the detective", '
            f'"target": "person, object, or information being sought", '
            f'"steps": ['
            f'{{"id": 1, "description": "first step", "completed": false}}, '
            f'{{"id": 2, "description": "second step", "completed": false}}'
            f'], '
            f'"resolution_condition": "report_to_client", '
            f'"moral_weight": "{archetype["moral_weight"]}"}}'
        )

        result = self.llm.query_structured(_SYSTEM, [], prompt)
        if not result or not result.get("objective"):
            return None
        apply_job_surname_overrides(result, faction)
        return {
            "faction": faction,
            "tier": tier,
            "title": archetype["title"],
            "payout": payout,
            "case_data": result,
        }

    def generate_board(self, *, faction: str, tier: int, count: int = 2) -> list[dict]:
        results = []
        eligible = _archetypes_for(faction, tier)
        archetypes = random.sample(eligible, min(count, len(eligible)))
        for archetype in archetypes:
            job = self.generate(faction=faction, tier=tier, archetype_slug=archetype["slug"])
            if job:
                results.append(job)
        return results
