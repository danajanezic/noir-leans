import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

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
                   content: str, case_id: int | None) -> None:
    conn.execute(
        "INSERT INTO conversation_history (character_id, role, content, case_id) VALUES (?, ?, ?, ?)",
        (character_id, role, content, case_id)
    )
    conn.commit()


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


def create_location(conn: sqlite3.Connection, *, name: str, description: str,
                    is_fixed: bool = False, case_id: int | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO locations (name, description, is_fixed, case_id) VALUES (?, ?, ?, ?)",
        (name, description, 1 if is_fixed else 0, case_id)
    )
    conn.commit()
    return cur.lastrowid


def get_location(conn: sqlite3.Connection, location_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM locations WHERE id=?", (location_id,)).fetchone()


def get_fixed_locations(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM locations WHERE is_fixed=1").fetchall()


def get_locations_for_case(conn: sqlite3.Connection, case_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM locations WHERE case_id=?", (case_id,)).fetchall()


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


def create_npc(conn: sqlite3.Connection, *, case_id: int, name: str, role: str,
               system_prompt: str, current_location_id: int,
               alignment: str = "True Neutral", age: int = 35) -> int:
    cur = conn.execute(
        "INSERT INTO npcs (case_id, name, role, system_prompt, current_location_id, alignment, age) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (case_id, name, role, system_prompt, current_location_id, alignment, age)
    )
    conn.commit()
    return cur.lastrowid


def get_npc(conn: sqlite3.Connection, npc_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM npcs WHERE id=?", (npc_id,)).fetchone()


def get_npcs_for_case(conn: sqlite3.Connection, case_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM npcs WHERE case_id=?", (case_id,)).fetchall()


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
                  evidence_summary: str) -> int:
    cur = conn.execute(
        "INSERT INTO arrests (case_id, npc_id, evidence_summary) VALUES (?, ?, ?)",
        (case_id, npc_id, evidence_summary)
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
                   is_killer: bool = False, race: str | None = None,
                   political_connections: str | None = None, alibi: str | None = None,
                   secret: str | None = None, backstory: str | None = None,
                   relationships: str | None = None) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO suspects
           (case_id, npc_id, is_killer, race, political_connections, alibi, secret, backstory, relationships)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (case_id, npc_id, 1 if is_killer else 0,
         race, political_connections, alibi, secret, backstory, relationships)
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
        """UPDATE player SET
           law_chaos = MAX(-16, MIN(16, law_chaos + ?)),
           good_evil = MAX(-16, MIN(16, good_evil + ?))
           WHERE id=1""",
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
