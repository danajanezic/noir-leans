import json
import sqlite3
from noir.persistence.repository import (
    get_case, get_evidence_for_case, get_all_dossier,
    get_locations_for_case, get_fixed_locations,
)


def build_case_recap(conn: sqlite3.Connection, case_id: int) -> dict:
    case = get_case(conn, case_id)
    case_data = json.loads(case["case_data"])
    victim = case_data.get("victim", {})

    evidence = get_evidence_for_case(conn, case_id)

    suspect_rows = conn.execute(
        "SELECT n.id, n.name, n.role, s.met FROM npcs n "
        "JOIN suspects s ON s.npc_id = n.id "
        "WHERE s.case_id=?",
        (case_id,)
    ).fetchall()
    met_suspects = [r for r in suspect_rows if r["met"]]
    unmet_suspects = [r for r in suspect_rows if not r["met"]]

    dossier = get_all_dossier(conn, case_id=case_id)

    player_loc = conn.execute(
        "SELECT location_id FROM character_locations WHERE character_id='player'"
    ).fetchone()
    visited_ids = set()
    if player_loc:
        visited_ids.add(player_loc["location_id"])

    case_locs = get_locations_for_case(conn, case_id)
    locations_visited = [l for l in case_locs if l["id"] in visited_ids]
    locations_unvisited = [l for l in case_locs if l["id"] not in visited_ids]

    return {
        "case_title": case["title"],
        "victim_name": victim.get("name", "Unknown"),
        "cause_of_death": victim.get("cause_of_death", "unknown"),
        "found_at": victim.get("found_at", "unknown"),
        "evidence_count": len(evidence),
        "evidence": [
            {
                "description": e["description"],
                "accused_npc_name": e["accused_npc_name"],
                "location_name": e["location_name"],
            }
            for e in evidence
        ],
        "met_suspects": [{"name": r["name"], "role": r["role"]} for r in met_suspects],
        "unmet_suspects": [{"name": r["name"], "role": r["role"]} for r in unmet_suspects],
        "dossier": dossier,
        "locations_visited": [{"name": l["name"]} for l in locations_visited],
        "locations_unvisited": [{"name": l["name"]} for l in locations_unvisited],
    }
