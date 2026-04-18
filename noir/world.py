import sqlite3
from noir.persistence.repository import (
    get_fixed_locations, get_locations_for_case, get_npcs_for_case
)


class World:

    def __init__(self, *, conn: sqlite3.Connection, active_case_id: int | None):
        self.conn = conn
        self.active_case_id = active_case_id

    def list_locations(self) -> list[sqlite3.Row]:
        fixed = get_fixed_locations(self.conn)
        case_locs = get_locations_for_case(self.conn, self.active_case_id) if self.active_case_id else []
        return list(fixed) + list(case_locs)

    def get_npcs_at(self, location_id: int) -> list[sqlite3.Row]:
        if self.active_case_id is None:
            return []
        npcs = get_npcs_for_case(self.conn, self.active_case_id)
        rows = self.conn.execute(
            "SELECT character_id, location_id FROM character_locations"
        ).fetchall()
        authoritative = {r["character_id"]: r["location_id"] for r in rows}
        return [
            npc for npc in npcs
            if authoritative.get(f"npc_{npc['id']}", npc["current_location_id"]) == location_id
        ]

    def find_location(self, name_fragment: str) -> sqlite3.Row | None:
        needle = name_fragment.lower().strip()
        for article in ("the ", "a ", "an "):
            if needle.startswith(article):
                needle = needle[len(article):]
                break
        locs = self.list_locations()
        # exact substring match first
        for loc in locs:
            if needle in loc["name"].lower() or loc["name"].lower() in needle:
                return loc
        # word-level fallback: any significant word (4+ chars) in needle matches loc name
        words = [w for w in needle.split() if len(w) >= 4]
        for loc in locs:
            loc_lower = loc["name"].lower()
            if any(w in loc_lower for w in words):
                return loc
        return None
