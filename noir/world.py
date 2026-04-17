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
        return [npc for npc in npcs if npc["current_location_id"] == location_id]

    def find_location(self, name_fragment: str) -> sqlite3.Row | None:
        needle = name_fragment.lower()
        for loc in self.list_locations():
            if needle in loc["name"].lower():
                return loc
        return None
