import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

try:
    import noir.memory as _mem
except Exception:
    _mem = None

_WORLD_CONTEXT_PATH = Path(__file__).parent.parent / "data" / "world_context.txt"


def get_world_context() -> str:
    return _WORLD_CONTEXT_PATH.read_text()


def create_player(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT OR IGNORE INTO player (id) VALUES (1)")
    conn.commit()


def get_player(conn: sqlite3.Connection) -> sqlite3.Row:
    return conn.execute("SELECT * FROM player WHERE id=1").fetchone()


def update_player_identity(conn: sqlite3.Connection, *, race: str, gender: str) -> None:
    conn.execute("UPDATE player SET race=?, gender=? WHERE id=1", (race, gender))
    conn.commit()


def update_player_reputation(conn: sqlite3.Connection, *, delta: int) -> None:
    conn.execute("UPDATE player SET reputation = reputation + ? WHERE id=1", (delta,))
    conn.commit()


def update_da_trust(conn: sqlite3.Connection, *, delta: int) -> None:
    conn.execute(
        "UPDATE player SET da_trust = MAX(0, MIN(100, COALESCE(da_trust, 100) + ?)) WHERE id=1",
        (delta,)
    )
    conn.commit()


def update_player_stats(conn: sqlite3.Connection, *,
                        cases_solved_delta: int = 0, wrong_arrests_delta: int = 0) -> None:
    conn.execute(
        "UPDATE player SET cases_solved = cases_solved + ?, wrong_arrests = wrong_arrests + ? WHERE id=1",
        (cases_solved_delta, wrong_arrests_delta)
    )
    conn.commit()


def save_partner(conn: sqlite3.Connection, *, name: str, sex: str,
                 personality_archetype: str, speech_style: str,
                 relationship_stance: str, system_prompt: str,
                 alignment: str = "True Neutral") -> None:
    conn.execute(
        """INSERT OR REPLACE INTO partner
           (id, name, sex, personality_archetype, speech_style, relationship_stance, system_prompt, alignment)
           VALUES (1, ?, ?, ?, ?, ?, ?, ?)""",
        (name, sex, personality_archetype, speech_style, relationship_stance, system_prompt, alignment)
    )
    conn.commit()


def get_partner(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM partner WHERE id=1").fetchone()


def append_history(conn: sqlite3.Connection, *, character_id: str, role: str,
                   content: str, case_id: int | None) -> int:
    cursor = conn.execute(
        "INSERT INTO conversation_history (character_id, role, content, case_id) VALUES (?, ?, ?, ?)",
        (character_id, role, content, case_id)
    )
    conn.commit()
    row_id: int = cursor.lastrowid
    if _mem is not None:
        try:
            _mem.enqueue(row_id=row_id, text=content)
        except Exception:
            pass
    return row_id


def get_history(conn: sqlite3.Connection, *, character_id: str,
                case_id: int | None = None) -> list[dict]:
    if case_id is not None:
        rows = conn.execute(
            "SELECT role, content FROM conversation_history WHERE character_id=? AND case_id=? ORDER BY id",
            (character_id, case_id)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT role, content FROM conversation_history WHERE character_id=? ORDER BY id",
            (character_id,)
        ).fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in rows]


def save_conversation_summary(conn: sqlite3.Connection, *, character_id: str,
                               summary: str, npc_opinion: str | None = None,
                               case_id: int | None = None) -> None:
    conn.execute(
        "INSERT INTO conversation_summaries (character_id, summary, npc_opinion, case_id) VALUES (?, ?, ?, ?)",
        (character_id, summary, npc_opinion, case_id)
    )
    conn.commit()


def get_conversation_summaries(conn: sqlite3.Connection, *, character_id: str,
                               case_id: int | None = None) -> list[str]:
    if case_id is not None:
        rows = conn.execute(
            "SELECT summary FROM conversation_summaries WHERE character_id=? AND case_id=? ORDER BY id",
            (character_id, case_id)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT summary FROM conversation_summaries WHERE character_id=? ORDER BY id",
            (character_id,)
        ).fetchall()
    return [r["summary"] for r in rows]


def get_latest_npc_opinion(conn: sqlite3.Connection, *, character_id: str) -> str | None:
    row = conn.execute(
        "SELECT npc_opinion FROM conversation_summaries WHERE character_id=? AND npc_opinion IS NOT NULL ORDER BY id DESC LIMIT 1",
        (character_id,)
    ).fetchone()
    return row["npc_opinion"] if row else None


def get_partner_relationship(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT relationship_notes FROM partner WHERE id=1").fetchone()
    return row["relationship_notes"] if row else None


def save_partner_relationship(conn: sqlite3.Connection, notes: str) -> None:
    conn.execute("UPDATE partner SET relationship_notes=? WHERE id=1", (notes,))
    conn.commit()


_XP_PER_LEVEL = 100


def initialize_player_skills(conn: sqlite3.Connection, *, owner: str, roots: list[str]) -> None:
    for root in roots:
        conn.execute(
            "INSERT OR IGNORE INTO player_skills (owner, root, level, xp) VALUES (?, ?, 1, 0)",
            (owner, root)
        )
    conn.commit()


def get_skills(conn: sqlite3.Connection, *, owner: str) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT root, level, xp FROM player_skills WHERE owner=?", (owner,)
    ).fetchall()
    return {r["root"]: {"level": r["level"], "xp": r["xp"]} for r in rows}


def award_xp(conn: sqlite3.Connection, *, owner: str, root: str,
             xp: int, reason: str | None = None, case_id: int | None = None) -> tuple[int, int]:
    """Award XP to a root skill. Returns (old_level, new_level)."""
    conn.execute(
        "INSERT OR IGNORE INTO player_skills (owner, root, level, xp) VALUES (?, ?, 1, 0)",
        (owner, root)
    )
    row = conn.execute(
        "SELECT level, xp FROM player_skills WHERE owner=? AND root=?", (owner, root)
    ).fetchone()
    old_level = row["level"]
    new_xp = row["xp"] + xp
    new_level = 1 + new_xp // _XP_PER_LEVEL
    conn.execute(
        "UPDATE player_skills SET xp=?, level=? WHERE owner=? AND root=?",
        (new_xp, new_level, owner, root)
    )
    log_skill_event(conn, owner=owner, root=root, xp=xp, reason=reason, case_id=case_id)
    conn.commit()
    return old_level, new_level


def get_specializations(conn: sqlite3.Connection, *, owner: str) -> list[dict]:
    rows = conn.execute(
        "SELECT root, name, description, unlocked_at_level, created_at "
        "FROM player_specializations WHERE owner=? ORDER BY created_at",
        (owner,)
    ).fetchall()
    return [dict(r) for r in rows]


def save_specialization(conn: sqlite3.Connection, *, owner: str, root: str,
                         name: str, description: str, unlocked_at_level: int) -> None:
    conn.execute(
        "INSERT INTO player_specializations (owner, root, name, description, unlocked_at_level) VALUES (?, ?, ?, ?, ?)",
        (owner, root, name, description, unlocked_at_level)
    )
    conn.commit()


def log_skill_event(conn: sqlite3.Connection, *, owner: str, root: str,
                     xp: int, reason: str | None = None, case_id: int | None = None) -> None:
    conn.execute(
        "INSERT INTO skill_events (owner, root, xp_awarded, reason, case_id) VALUES (?, ?, ?, ?, ?)",
        (owner, root, xp, reason, case_id)
    )


def get_skill_events(conn: sqlite3.Connection, *, owner: str, root: str,
                      limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT root, xp_awarded, reason, case_id, created_at "
        "FROM skill_events WHERE owner=? AND root=? ORDER BY id DESC LIMIT ?",
        (owner, root, limit)
    ).fetchall()
    return [dict(r) for r in rows]


def get_player_skill_roots(conn: sqlite3.Connection, *, owner: str) -> list[str]:
    rows = conn.execute(
        "SELECT root FROM player_skills WHERE owner=?", (owner,)
    ).fetchall()
    return [r["root"] for r in rows]


def create_location(conn: sqlite3.Connection, *, name: str, description: str,
                    is_fixed: bool = False, case_id: int | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO locations (name, description, is_fixed, case_id) VALUES (?, ?, ?, ?)",
        (name, description, 1 if is_fixed else 0, case_id)
    )
    conn.commit()
    return cur.lastrowid


def seed_locations_to_db(conn: sqlite3.Connection, locations: list[dict]) -> None:
    for loc in locations:
        conn.execute(
            "INSERT OR IGNORE INTO seeded_locations (name, description, type) VALUES (?, ?, ?)",
            (loc["name"], loc["description"], loc.get("type"))
        )
    conn.commit()


def get_seeded_location_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM seeded_locations ORDER BY name").fetchall()
    return [r["name"] for r in rows]


def get_seeded_location_description(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute(
        "SELECT description FROM seeded_locations WHERE name=?", (name,)
    ).fetchone()
    return row["description"] if row else None


def get_location(conn: sqlite3.Connection, location_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM locations WHERE id=?", (location_id,)).fetchone()


def get_fixed_locations(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM locations WHERE is_fixed=1").fetchall()


def get_locations_for_case(conn: sqlite3.Connection, case_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM locations WHERE case_id=?", (case_id,)).fetchall()


def get_discovered_locations_for_case(conn: sqlite3.Connection, case_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM locations WHERE case_id=? AND discovered=1", (case_id,)
    ).fetchall()


def discover_location(conn: sqlite3.Connection, location_id: int) -> None:
    conn.execute("UPDATE locations SET discovered=1 WHERE id=?", (location_id,))
    conn.commit()


def discover_location_by_name(conn: sqlite3.Connection, case_id: int, name: str) -> bool:
    """Discover a case location by name (case-insensitive). Returns True if found."""
    row = conn.execute(
        "SELECT id FROM locations WHERE case_id=? AND lower(name)=lower(?)",
        (case_id, name)
    ).fetchone()
    if row:
        conn.execute("UPDATE locations SET discovered=1 WHERE id=?", (row["id"],))
        conn.commit()
        return True
    return False


def create_clue(conn: sqlite3.Connection, *, case_id: int, description: str,
                location: str | None = None, is_red_herring: bool = False) -> int:
    cur = conn.execute(
        "INSERT INTO clues (case_id, description, location, is_red_herring) VALUES (?, ?, ?, ?)",
        (case_id, description, location, 1 if is_red_herring else 0)
    )
    conn.commit()
    return cur.lastrowid


def get_clues_for_case(conn: sqlite3.Connection, case_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM clues WHERE case_id=?", (case_id,)
    ).fetchall()


def create_case(conn: sqlite3.Connection, *, archetype: str, title: str,
                case_data: dict) -> int:
    cur = conn.execute(
        "INSERT INTO cases (archetype, title, case_data) VALUES (?, ?, ?)",
        (archetype, title, json.dumps(case_data))
    )
    case_id = cur.lastrowid
    for clue in case_data.get("clues", []):
        conn.execute(
            "INSERT INTO clues (case_id, description, location, is_red_herring) VALUES (?, ?, ?, ?)",
            (case_id, clue["description"],
             clue.get("location"), 1 if clue.get("is_red_herring") else 0)
        )
    body_loc = case_data.get("body_location", "City Morgue")
    clue_location = "City Morgue" if body_loc == "City Morgue" else case_data.get("victim", {}).get("found_at")
    for desc in case_data.get("body_clues", []):
        conn.execute(
            "INSERT INTO clues (case_id, description, location, is_red_herring) VALUES (?, ?, ?, ?)",
            (case_id, desc, clue_location, 0)
        )
    conn.commit()
    return case_id


def get_case(conn: sqlite3.Connection, case_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()


def get_active_cases(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM cases WHERE status='active'").fetchall()


def get_all_cases(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM cases ORDER BY id DESC").fetchall()


def set_case_active(conn: sqlite3.Connection, *, case_id: int) -> None:
    conn.execute("UPDATE cases SET status='active' WHERE id=?", (case_id,))
    conn.commit()


def update_case_status(conn: sqlite3.Connection, *, case_id: int, status: str,
                       trial_end_time: str | None = None,
                       trial_outcome: str | None = None) -> None:
    conn.execute(
        "UPDATE cases SET status=?, trial_end_time=?, trial_outcome=? WHERE id=?",
        (status, trial_end_time, trial_outcome, case_id)
    )
    conn.commit()


def create_npc(conn: sqlite3.Connection, *, case_id: int | None, name: str, role: str,
               system_prompt: str, current_location_id: int,
               alignment: str = "True Neutral", age: int = 35,
               pressure_tolerance: int = 5, kindness_weight: int = 5,
               empathy: int = 5, starting_guilt: int = 0,
               revelation_style: str = "staged", revelation_stages: int = 3,
               corruption: int = 0, maiden_name: str | None = None,
               physical_description: str | None = None,
               sex: str | None = None) -> int:
    cur = conn.execute(
        """INSERT INTO npcs
           (case_id, name, role, system_prompt, current_location_id, alignment, age,
            pressure_tolerance, kindness_weight, empathy, starting_guilt,
            revelation_style, revelation_stages, corruption, maiden_name, physical_description, sex)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (case_id, name, role, system_prompt, current_location_id, alignment, age,
         pressure_tolerance, kindness_weight, empathy, starting_guilt,
         revelation_style, revelation_stages, corruption, maiden_name, physical_description, sex)
    )
    conn.commit()
    return cur.lastrowid


def get_npc(conn: sqlite3.Connection, npc_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM npcs WHERE id=?", (npc_id,)).fetchone()


def detain_npc(conn: sqlite3.Connection, npc_id: int) -> None:
    conn.execute("UPDATE npcs SET detained=1 WHERE id=?", (npc_id,))
    conn.commit()


def release_npc(conn: sqlite3.Connection, npc_id: int) -> None:
    conn.execute("UPDATE npcs SET detained=0 WHERE id=?", (npc_id,))
    conn.commit()


def get_detained_npcs(conn: sqlite3.Connection, case_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM npcs WHERE case_id=? AND detained=1", (case_id,)
    ).fetchall()


def update_npc_system_prompt(conn: sqlite3.Connection, *, npc_id: int, system_prompt: str) -> None:
    conn.execute("UPDATE npcs SET system_prompt=? WHERE id=?", (system_prompt, npc_id))
    conn.commit()


def update_suspect_backstory(conn: sqlite3.Connection, *, npc_id: int, backstory: str) -> None:
    conn.execute("UPDATE suspects SET backstory=? WHERE npc_id=?", (backstory, npc_id))
    conn.commit()


def get_npc_psychology(conn: sqlite3.Connection, npc_id: int) -> dict:
    npc = conn.execute(
        "SELECT pressure_tolerance, kindness_weight, empathy, starting_guilt, "
        "revelation_style, revelation_stages FROM npcs WHERE id=?", (npc_id,)
    ).fetchone()
    rel = conn.execute(
        "SELECT guilt, pressure_score, revelation_stage FROM npc_relationships WHERE npc_id=?",
        (npc_id,)
    ).fetchone()
    result = dict(npc) if npc else {}
    if rel:
        result.update(dict(rel))
    else:
        # No relationship row yet — compute default guilt from starting_guilt
        result.update({
            "guilt": (result.get("starting_guilt", 0) * 10),
            "pressure_score": 0,
            "revelation_stage": 0,
        })
    return result


def initialize_npc_relationship(conn: sqlite3.Connection, npc_id: int,
                                 starting_guilt: int = 3) -> None:
    conn.execute(
        """INSERT INTO npc_relationships (npc_id, guilt)
           VALUES (?, ?)
           ON CONFLICT(npc_id) DO NOTHING""",
        (npc_id, starting_guilt * 10)
    )
    conn.commit()


def update_npc_guilt(conn: sqlite3.Connection, *, npc_id: int, delta: int) -> None:
    conn.execute(
        """INSERT INTO npc_relationships (npc_id, guilt)
           VALUES (?, MAX(0, MIN(100, ?)))
           ON CONFLICT(npc_id) DO UPDATE SET
           guilt = MAX(0, MIN(100, guilt + excluded.guilt))""",
        (npc_id, delta)
    )
    conn.commit()


def update_npc_pressure(conn: sqlite3.Connection, *, npc_id: int, delta: int) -> None:
    conn.execute(
        """INSERT INTO npc_relationships (npc_id, pressure_score)
           VALUES (?, MAX(0, MIN(100, ?)))
           ON CONFLICT(npc_id) DO UPDATE SET
           pressure_score = MAX(0, MIN(100, pressure_score + excluded.pressure_score))""",
        (npc_id, delta)
    )
    conn.commit()


def decay_npc_pressure(conn: sqlite3.Connection, npc_id: int) -> None:
    conn.execute(
        "UPDATE npc_relationships SET pressure_score = MAX(0, pressure_score - 5) WHERE npc_id=?",
        (npc_id,)
    )
    conn.commit()


def get_npc_revelation_stage(conn: sqlite3.Connection, npc_id: int) -> int:
    row = conn.execute(
        "SELECT revelation_stage FROM npc_relationships WHERE npc_id=?", (npc_id,)
    ).fetchone()
    return row["revelation_stage"] if row else 0


def increment_npc_revelation_stage(conn: sqlite3.Connection, *, npc_id: int) -> int:
    conn.execute(
        """INSERT INTO npc_relationships (npc_id, revelation_stage) VALUES (?, 1)
           ON CONFLICT(npc_id) DO UPDATE SET revelation_stage = revelation_stage + 1""",
        (npc_id,)
    )
    conn.commit()
    return get_npc_revelation_stage(conn, npc_id)


def get_npcs_for_case(conn: sqlite3.Connection, case_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT n.* FROM npcs n WHERE n.case_id=?
           UNION ALL
           SELECT n.* FROM npcs n
           JOIN locations l ON n.current_location_id = l.id
           WHERE n.case_id IS NULL AND l.is_fixed=1""",
        (case_id,)
    ).fetchall()


def update_npc_location(conn: sqlite3.Connection, *, npc_id: int, location_id: int) -> None:
    conn.execute("UPDATE npcs SET current_location_id=? WHERE id=?", (location_id, npc_id))
    conn.commit()


def set_character_location(conn: sqlite3.Connection, *, character_id: str, location_id: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO character_locations (character_id, location_id, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(character_id) DO UPDATE SET location_id=?, updated_at=?""",
        (character_id, location_id, now, location_id, now)
    )
    conn.commit()


def get_character_location(conn: sqlite3.Connection, character_id: str) -> int | None:
    row = conn.execute(
        "SELECT location_id FROM character_locations WHERE character_id=?", (character_id,)
    ).fetchone()
    return row["location_id"] if row else None


def add_evidence(conn: sqlite3.Connection, *, case_id: int, clue_id: int,
                 source_npc_id: int | None, location_id: int) -> int:
    cur = conn.execute(
        "INSERT INTO evidence (case_id, clue_id, source_npc_id, location_id) VALUES (?, ?, ?, ?)",
        (case_id, clue_id, source_npc_id, location_id)
    )
    conn.commit()
    return cur.lastrowid


def get_evidence_for_case(conn: sqlite3.Connection, case_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT e.id, e.case_id, e.clue_id, e.source_npc_id, e.accused_npc_id, e.location_id, "
        "e.collected_at, c.description, c.is_red_herring, l.name AS location_name, "
        "an.name AS accused_npc_name "
        "FROM evidence e "
        "JOIN clues c ON c.id = e.clue_id "
        "LEFT JOIN locations l ON l.id = e.location_id "
        "LEFT JOIN npcs an ON an.id = e.accused_npc_id "
        "WHERE e.case_id=?",
        (case_id,)
    ).fetchall()


def link_evidence_to_suspect(conn: sqlite3.Connection, *, evidence_id: int, npc_id: int) -> None:
    conn.execute("UPDATE evidence SET accused_npc_id=? WHERE id=?", (npc_id, evidence_id))
    conn.commit()


def create_arrest(conn: sqlite3.Connection, *, case_id: int, npc_id: int,
                  evidence_summary: str, was_correct: bool | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO arrests (case_id, npc_id, evidence_summary, was_correct) VALUES (?, ?, ?, ?)",
        (case_id, npc_id, evidence_summary, int(was_correct) if was_correct is not None else None)
    )
    conn.commit()
    return cur.lastrowid


def update_arrest_verdict(conn: sqlite3.Connection, *, arrest_id: int, was_correct: bool) -> None:
    conn.execute("UPDATE arrests SET was_correct=? WHERE id=?", (1 if was_correct else 0, arrest_id))
    conn.commit()


def save_archetype(conn: sqlite3.Connection, *, name: str, description: str,
                   seed_prompt: str) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO mystery_archetypes (name, description, seed_prompt)
           VALUES (?, ?, ?)""",
        (name, description, seed_prompt)
    )
    conn.commit()


def get_archetype(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM mystery_archetypes WHERE name=?", (name,)
    ).fetchone()


def list_archetypes(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM mystery_archetypes").fetchall()


def get_player_states(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM player_states ORDER BY added_at").fetchall()


def add_player_state(conn: sqlite3.Connection, *, state: str, intensity: int = 1) -> None:
    conn.execute(
        "INSERT INTO player_states (state, intensity) VALUES (?, ?) "
        "ON CONFLICT(state) DO UPDATE SET intensity=?, added_at=CURRENT_TIMESTAMP",
        (state, intensity, intensity)
    )
    conn.commit()


def remove_player_state(conn: sqlite3.Connection, *, state: str) -> bool:
    cur = conn.execute("DELETE FROM player_states WHERE state=?", (state,))
    conn.commit()
    return cur.rowcount > 0


def clear_transient_states(conn: sqlite3.Connection) -> None:
    """Clear states that shouldn't persist across sessions (drunk, sleepy)."""
    conn.execute("DELETE FROM player_states WHERE state IN ('drunk', 'sleepy', 'tired')")
    conn.commit()


def add_player_suspect(conn: sqlite3.Connection, *, case_id: int, name: str,
                       note: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO player_suspects (case_id, name, note) VALUES (?, ?, ?)",
        (case_id, name, note)
    )
    conn.commit()
    return cur.lastrowid


def get_player_suspects(conn: sqlite3.Connection, case_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM player_suspects WHERE case_id=? ORDER BY added_at", (case_id,)
    ).fetchall()


def remove_player_suspect(conn: sqlite3.Connection, *, case_id: int, name: str) -> bool:
    cur = conn.execute(
        "DELETE FROM player_suspects WHERE case_id=? AND lower(name) LIKE lower(?)",
        (case_id, f"%{name}%")
    )
    conn.commit()
    return cur.rowcount > 0


def get_npc_affection(conn: sqlite3.Connection, npc_id: int) -> int:
    row = conn.execute(
        "SELECT affection FROM npc_relationships WHERE npc_id=?", (npc_id,)
    ).fetchone()
    return row["affection"] if row else 0


def set_npc_affection(conn: sqlite3.Connection, npc_id: int, affection: int) -> None:
    affection = max(0, min(100, affection))
    conn.execute(
        """INSERT INTO npc_relationships (npc_id, affection)
           VALUES (?, ?)
           ON CONFLICT(npc_id) DO UPDATE SET affection=?""",
        (npc_id, affection, affection)
    )
    conn.commit()


def increment_npc_affection(conn: sqlite3.Connection, npc_id: int, delta: int) -> int:
    conn.execute(
        """INSERT INTO npc_relationships (npc_id, affection)
           VALUES (?, MIN(100, MAX(0, ?)))
           ON CONFLICT(npc_id) DO UPDATE SET affection = MIN(100, MAX(0, affection + ?))""",
        (npc_id, delta, delta)
    )
    conn.commit()
    row = conn.execute(
        "SELECT affection FROM npc_relationships WHERE npc_id=?", (npc_id,)
    ).fetchone()
    return row["affection"]


def get_npc_relationship_flags(conn: sqlite3.Connection, npc_id: int) -> dict:
    row = conn.execute(
        "SELECT clue_volunteered, secret_revealed FROM npc_relationships WHERE npc_id=?",
        (npc_id,)
    ).fetchone()
    if row is None:
        return {"clue_volunteered": 0, "secret_revealed": 0}
    return {"clue_volunteered": row["clue_volunteered"], "secret_revealed": row["secret_revealed"]}


def set_npc_clue_volunteered(conn: sqlite3.Connection, npc_id: int) -> None:
    conn.execute(
        """INSERT INTO npc_relationships (npc_id, clue_volunteered)
           VALUES (?, 1)
           ON CONFLICT(npc_id) DO UPDATE SET clue_volunteered=1""",
        (npc_id,)
    )
    conn.commit()


def set_npc_secret_revealed(conn: sqlite3.Connection, npc_id: int) -> None:
    conn.execute(
        """INSERT INTO npc_relationships (npc_id, secret_revealed)
           VALUES (?, 1)
           ON CONFLICT(npc_id) DO UPDATE SET secret_revealed=1""",
        (npc_id,)
    )
    conn.commit()


def get_npc_revelation_summary(conn: sqlite3.Connection, npc_id: int) -> str | None:
    row = conn.execute(
        "SELECT revelation_summary FROM npc_relationships WHERE npc_id=?", (npc_id,)
    ).fetchone()
    return row["revelation_summary"] if row else None


def set_npc_revelation_summary(conn: sqlite3.Connection, npc_id: int, summary: str) -> None:
    conn.execute(
        """INSERT INTO npc_relationships (npc_id, revelation_summary)
           VALUES (?, ?)
           ON CONFLICT(npc_id) DO UPDATE SET revelation_summary=excluded.revelation_summary""",
        (npc_id, summary)
    )
    conn.commit()


def get_partner_affection(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT affection FROM partner WHERE id=1").fetchone()
    return row["affection"] if row else 0


def increment_partner_affection(conn: sqlite3.Connection, delta: int) -> int:
    conn.execute(
        "UPDATE partner SET affection = MIN(100, MAX(0, affection + ?)) WHERE id=1",
        (delta,)
    )
    conn.commit()
    row = conn.execute("SELECT affection FROM partner WHERE id=1").fetchone()
    return row["affection"] if row else 0


def get_partner_dark_past_state(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT dark_past_state FROM partner WHERE id=1").fetchone()
    return row["dark_past_state"] if row else "none"


def set_partner_dark_past_state(conn: sqlite3.Connection, state: str) -> None:
    conn.execute("UPDATE partner SET dark_past_state=? WHERE id=1", (state,))
    conn.commit()


def set_partner_dark_past(conn: sqlite3.Connection, dark_past: str) -> None:
    conn.execute("UPDATE partner SET dark_past=? WHERE id=1", (dark_past,))
    conn.commit()


def get_partner_dark_past(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT dark_past FROM partner WHERE id=1").fetchone()
    return row["dark_past"] if row else None


def add_dossier_facts(conn: sqlite3.Connection, *, case_id: int, npc_name: str, facts: list[str]) -> None:
    for fact in facts:
        conn.execute(
            "INSERT INTO dossier (case_id, npc_name, fact) VALUES (?, ?, ?)",
            (case_id, npc_name, fact)
        )
    conn.commit()


def get_dossier(conn: sqlite3.Connection, *, case_id: int, npc_name: str) -> list[str]:
    rows = conn.execute(
        "SELECT fact FROM dossier WHERE case_id=? AND LOWER(npc_name) LIKE ? ORDER BY added_at",
        (case_id, f"%{npc_name.lower()}%")
    ).fetchall()
    return [r["fact"] for r in rows]


def get_all_dossier(conn: sqlite3.Connection, *, case_id: int) -> dict[str, list[str]]:
    rows = conn.execute(
        "SELECT npc_name, fact FROM dossier WHERE case_id=? ORDER BY npc_name, added_at",
        (case_id,)
    ).fetchall()
    result: dict[str, list[str]] = {}
    for r in rows:
        result.setdefault(r["npc_name"], []).append(r["fact"])
    return result


def get_game_time(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT game_time FROM player WHERE id=1").fetchone()
    return row["game_time"] if row and row["game_time"] is not None else 480


def advance_game_time(conn: sqlite3.Connection, *, delta: int) -> int:
    conn.execute("UPDATE player SET game_time = game_time + ? WHERE id=1", (delta,))
    conn.commit()
    return get_game_time(conn)


def create_npc_schedule(conn: sqlite3.Connection, *, npc_id: int,
                        time_start: int, time_end: int, location_name: str) -> None:
    conn.execute(
        "INSERT INTO npc_schedules (npc_id, time_start, time_end, location_name) VALUES (?, ?, ?, ?)",
        (npc_id, time_start, time_end, location_name)
    )


def get_npc_schedule_entries(conn: sqlite3.Connection, npc_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM npc_schedules WHERE npc_id=? ORDER BY time_start", (npc_id,)
    ).fetchall()


def get_npc_location_at_time(conn: sqlite3.Connection, npc_id: int, game_time: int) -> str | None:
    tod = game_time % 1440
    entries = get_npc_schedule_entries(conn, npc_id)
    for e in entries:
        s, end = e["time_start"], e["time_end"]
        if s <= end:
            if s <= tod < end:
                return e["location_name"]
        else:  # spans midnight
            if tod >= s or tod < end:
                return e["location_name"]
    return None


def create_npc_appointment(conn: sqlite3.Connection, *, npc_id: int,
                           game_time: int, location_name: str) -> int:
    cur = conn.execute(
        "INSERT INTO npc_appointments (npc_id, game_time, location_name) VALUES (?, ?, ?)",
        (npc_id, game_time, location_name)
    )
    conn.commit()
    return cur.lastrowid


def get_active_appointment(conn: sqlite3.Connection, npc_id: int,
                           game_time: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM npc_appointments WHERE npc_id=? AND fulfilled=0 "
        "AND game_time <= ? ORDER BY game_time DESC LIMIT 1",
        (npc_id, game_time)
    ).fetchone()


def fulfill_past_appointments(conn: sqlite3.Connection, npc_id: int, game_time: int) -> None:
    conn.execute(
        "UPDATE npc_appointments SET fulfilled=1 WHERE npc_id=? AND game_time < ?",
        (npc_id, game_time)
    )
    conn.commit()


def create_suspect(conn: sqlite3.Connection, *, case_id: int, npc_id: int,
                   is_killer: bool = False, met: bool = False,
                   race: str | None = None,
                   political_connections: str | None = None, alibi: str | None = None,
                   secret: str | None = None, backstory: str | None = None,
                   relationships: str | None = None,
                   archetype_id: str | None = None) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO suspects
           (case_id, npc_id, is_killer, met, race, political_connections,
            alibi, secret, backstory, relationships, archetype_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (case_id, npc_id, int(is_killer), int(met), race, political_connections,
         alibi, secret, backstory, relationships, archetype_id)
    )
    conn.commit()


def mark_suspect_met(conn: sqlite3.Connection, *, npc_id: int) -> None:
    conn.execute("UPDATE suspects SET met=1 WHERE npc_id=?", (npc_id,))
    conn.commit()


def get_suspect_by_npc(conn: sqlite3.Connection, npc_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM suspects WHERE npc_id=?", (npc_id,)).fetchone()


def get_met_suspects_for_case(conn: sqlite3.Connection, case_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT n.* FROM npcs n JOIN suspects s ON s.npc_id=n.id "
        "WHERE s.case_id=? AND s.met=1 AND n.role='suspect'",
        (case_id,)
    ).fetchall()


def update_player_alignment(conn: sqlite3.Connection, *,
                             law_delta: int = 0, good_delta: int = 0) -> None:
    conn.execute(
        "UPDATE player SET law_chaos = law_chaos + ?, good_evil = good_evil + ? WHERE id=1",
        (law_delta, good_delta)
    )
    conn.commit()


def get_alignment(player: sqlite3.Row) -> str:
    from noir.onboarding.quiz import resolve_alignment
    return resolve_alignment(player["law_chaos"], player["good_evil"])


def remove_partner(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE partner SET dark_past_state='lost' WHERE id=1")
    conn.execute("DELETE FROM conversation_history WHERE character_id='partner'")
    conn.commit()


def add_lead(conn: sqlite3.Connection, *, case_id: int, description: str,
             source_npc: str | None = None) -> None:
    existing = conn.execute(
        "SELECT id FROM leads WHERE case_id=? AND description=?", (case_id, description)
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO leads (case_id, description, source_npc) VALUES (?, ?, ?)",
            (case_id, description, source_npc)
        )
        conn.commit()


def get_leads_for_case(conn: sqlite3.Connection, case_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM leads WHERE case_id=? ORDER BY id ASC", (case_id,)
    ).fetchall()


def get_all_organizations(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM organizations ORDER BY influence DESC").fetchall()


def get_organization_by_name(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM organizations WHERE name=?", (name,)).fetchone()


def get_or_create_family_org(conn: sqlite3.Connection, surname: str) -> int:
    name = f"{surname} Family"
    row = conn.execute("SELECT id FROM organizations WHERE name=?", (name,)).fetchone()
    if row:
        return row["id"]
    conn.execute(
        """INSERT INTO organizations (name, type, description, is_hierarchical, is_seeded, influence)
           VALUES (?, 'personal_family', ?, 1, 0, 2)""",
        (name, f"The {surname} family, a personal family unit.")
    )
    conn.commit()
    return conn.execute("SELECT id FROM organizations WHERE name=?", (name,)).fetchone()["id"]


def get_organizations_for_location(conn: sqlite3.Connection, location_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT o.* FROM organizations o
           JOIN location_organizations lo ON lo.organization_id = o.id
           WHERE lo.location_id=?
           ORDER BY o.influence DESC""",
        (location_id,)
    ).fetchall()


def get_organizations_for_npc(conn: sqlite3.Connection, npc_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT o.*, om.role FROM organizations o
           JOIN organization_members om ON om.organization_id = o.id
           WHERE om.member_type='npc' AND om.member_id=?
           ORDER BY o.influence DESC""",
        (npc_id,)
    ).fetchall()


def get_organizations_for_player(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT o.*, om.role FROM organizations o
           JOIN organization_members om ON om.organization_id = o.id
           WHERE om.member_type='player' AND om.member_id=1
           ORDER BY o.influence DESC"""
    ).fetchall()


def get_members_of_organization(conn: sqlite3.Connection, org_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT om.*, n.name as npc_name, n.role as npc_role
           FROM organization_members om
           LEFT JOIN npcs n ON om.member_type='npc' AND om.member_id=n.id
           WHERE om.organization_id=?
           ORDER BY om.role""",
        (org_id,)
    ).fetchall()


def add_organization_member(conn: sqlite3.Connection, *, organization_id: int,
                             member_type: str, member_id: int,
                             role: str | None = None, is_static: bool = False) -> None:
    existing = conn.execute(
        "SELECT id FROM organization_members WHERE organization_id=? AND member_type=? AND member_id=?",
        (organization_id, member_type, member_id)
    ).fetchone()
    if existing:
        if role:
            conn.execute(
                "UPDATE organization_members SET role=? WHERE id=?",
                (role, existing["id"])
            )
    else:
        conn.execute(
            """INSERT INTO organization_members (organization_id, member_type, member_id, role, is_static)
               VALUES (?, ?, ?, ?, ?)""",
            (organization_id, member_type, member_id, role, 1 if is_static else 0)
        )
    conn.commit()


def update_member_role(conn: sqlite3.Connection, *, organization_id: int,
                        member_type: str, member_id: int, role: str) -> None:
    conn.execute(
        """UPDATE organization_members SET role=?
           WHERE organization_id=? AND member_type=? AND member_id=?""",
        (role, organization_id, member_type, member_id)
    )
    conn.commit()


def get_player_cash(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT cash FROM player WHERE id=1").fetchone()
    return row["cash"] if row and row["cash"] is not None else 0


def update_player_cash(conn: sqlite3.Connection, *, delta: int) -> int:
    conn.execute(
        "UPDATE player SET cash = MAX(0, COALESCE(cash, 0) + ?) WHERE id=1", (delta,)
    )
    conn.commit()
    return get_player_cash(conn)


def record_bribe(conn: sqlite3.Connection, *, case_id: int | None, npc_id: int,
                 amount: int, accepted: bool, effect: str | None) -> int:
    cur = conn.execute(
        "INSERT INTO bribes (case_id, npc_id, amount, accepted, effect) VALUES (?, ?, ?, ?, ?)",
        (case_id, npc_id, amount, 1 if accepted else 0, effect)
    )
    conn.commit()
    return cur.lastrowid


def get_accepted_bribes_for_case(conn: sqlite3.Connection, case_id: int) -> list:
    return conn.execute(
        "SELECT * FROM bribes WHERE case_id=? AND accepted=1", (case_id,)
    ).fetchall()


def get_npc_corruption(conn: sqlite3.Connection, npc_id: int) -> int:
    row = conn.execute("SELECT corruption FROM npcs WHERE id=?", (npc_id,)).fetchone()
    return row["corruption"] if row and row["corruption"] is not None else 0


def set_npc_corruption(conn: sqlite3.Connection, npc_id: int, corruption: int) -> None:
    conn.execute("UPDATE npcs SET corruption=? WHERE id=?", (corruption, npc_id))
    conn.commit()


def get_player_org_memberships(conn: sqlite3.Connection) -> list:
    return conn.execute(
        """SELECT om.*, o.name as org_name, o.type as org_type, o.influence
           FROM organization_members om
           JOIN organizations o ON o.id = om.organization_id
           WHERE om.member_type='player' AND om.member_id=1"""
    ).fetchall()


def collect_org_payroll(conn: sqlite3.Connection, current_game_time: int) -> list[dict]:
    """Pay out any org payroll that has come due (daily = 1440 game minutes). Returns list of payouts."""
    memberships = conn.execute(
        """SELECT om.id, om.organization_id, om.payroll, om.last_payroll_time, o.name
           FROM organization_members om
           JOIN organizations o ON o.id = om.organization_id
           WHERE om.member_type='player' AND om.member_id=1 AND om.payroll > 0"""
    ).fetchall()
    payouts = []
    for m in memberships:
        last = m["last_payroll_time"] or 0
        if current_game_time - last >= 1440:
            amount = m["payroll"]
            conn.execute(
                "UPDATE organization_members SET last_payroll_time=? WHERE id=?",
                (current_game_time, m["id"])
            )
            conn.execute(
                "UPDATE player SET cash = COALESCE(cash, 0) + ? WHERE id=1", (amount,)
            )
            payouts.append({"org_name": m["name"], "amount": amount})
    if payouts:
        conn.commit()
    return payouts


def get_street_reputation(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT tags, street_says FROM street_reputation WHERE id=1").fetchone()
    if not row:
        return {"tags": [], "street_says": ""}
    import json as _json
    return {
        "tags": _json.loads(row["tags"] or "[]"),
        "street_says": row["street_says"] or "",
    }


def update_street_reputation(conn: sqlite3.Connection, *,
                              tags: list[str], street_says: str) -> None:
    import json as _json
    conn.execute(
        """INSERT INTO street_reputation (id, tags, street_says, updated_at)
           VALUES (1, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(id) DO UPDATE SET
               tags=excluded.tags,
               street_says=excluded.street_says,
               updated_at=excluded.updated_at""",
        (_json.dumps(tags), street_says)
    )
    conn.commit()
