import sqlite3
from noir.persistence.repository import (
    get_fixed_locations, get_locations_for_case, get_npcs_for_case,
    get_game_time, get_npc_location_at_time, get_active_appointment,
)


class World:

    def __init__(self, *, conn: sqlite3.Connection, active_case_id: int | None):
        self.conn = conn
        self.active_case_id = active_case_id

    def list_locations(self) -> list[sqlite3.Row]:
        fixed = get_fixed_locations(self.conn)
        case_locs = get_locations_for_case(self.conn, self.active_case_id) if self.active_case_id else []
        return list(fixed) + list(case_locs)

    def _resolve_npc_location_id(self, npc: sqlite3.Row, game_time: int,
                                  loc_name_to_id: dict[str, int]) -> int | None:
        """Return the location_id where npc currently is, based on time/appointments/routine."""
        npc_id = npc["id"]

        # 1. Check pending appointment that has come due
        appt = get_active_appointment(self.conn, npc_id, game_time)
        if appt:
            loc_name = appt["location_name"]
            return loc_name_to_id.get(loc_name) or _fuzzy_match_loc(loc_name, loc_name_to_id)

        # 2. Check routine
        routine_loc = get_npc_location_at_time(self.conn, npc_id, game_time)
        if routine_loc:
            if routine_loc.lower() == "home":
                return None  # unavailable
            return loc_name_to_id.get(routine_loc) or _fuzzy_match_loc(routine_loc, loc_name_to_id)

        # 3. Fall back to stored location (set at case creation or via move_to)
        rows = self.conn.execute(
            "SELECT location_id FROM character_locations WHERE character_id=?",
            (f"npc_{npc_id}",)
        ).fetchone()
        if rows:
            return rows["location_id"]
        return npc["current_location_id"]

    def get_npcs_at(self, location_id: int) -> list[sqlite3.Row]:
        game_time = get_game_time(self.conn)
        all_locs = self.list_locations()
        loc_name_to_id = {loc["name"]: loc["id"] for loc in all_locs}
        precinct_id = loc_name_to_id.get("The Precinct")

        # World-persistent NPCs (case_id=NULL at fixed locations) always resolve.
        world_npcs = self.conn.execute(
            """SELECT n.* FROM npcs n
               JOIN locations l ON n.current_location_id = l.id
               WHERE n.case_id IS NULL AND l.is_fixed=1"""
        ).fetchall()

        # Case-specific NPCs only when there is an active case.
        case_npcs = get_npcs_for_case(self.conn, self.active_case_id) if self.active_case_id else []

        seen_ids: set[int] = set()
        result = []
        for npc in list(world_npcs) + list(case_npcs):
            if npc["id"] in seen_ids:
                continue
            seen_ids.add(npc["id"])
            if npc["detained"]:
                if location_id == precinct_id:
                    result.append(npc)
            elif self._resolve_npc_location_id(npc, game_time, loc_name_to_id) == location_id:
                result.append(npc)
        return result

    def find_location(self, name_fragment: str) -> sqlite3.Row | None:
        needle = name_fragment.lower().strip()
        for article in ("the ", "a ", "an "):
            if needle.startswith(article):
                needle = needle[len(article):]
                break
        locs = self.list_locations()
        for loc in locs:
            if needle in loc["name"].lower() or loc["name"].lower() in needle:
                return loc
        words = [w for w in needle.split() if len(w) >= 4]
        for loc in locs:
            loc_lower = loc["name"].lower()
            if any(w in loc_lower for w in words):
                return loc
        return None


def _fuzzy_match_loc(name: str, loc_name_to_id: dict[str, int]) -> int | None:
    needle = name.lower().strip()
    for loc_name, loc_id in loc_name_to_id.items():
        if needle in loc_name.lower() or loc_name.lower() in needle:
            return loc_id
    words = [w for w in needle.split() if len(w) >= 4]
    for loc_name, loc_id in loc_name_to_id.items():
        if any(w in loc_name.lower() for w in words):
            return loc_id
    return None
