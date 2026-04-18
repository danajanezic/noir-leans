import json
import sqlite3
from datetime import datetime, timezone


def create_player(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT OR IGNORE INTO player (id) VALUES (1)")
    conn.commit()


def get_player(conn: sqlite3.Connection) -> sqlite3.Row:
    return conn.execute("SELECT * FROM player WHERE id=1").fetchone()


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
                 relationship_stance: str, system_prompt: str) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO partner
           (id, name, sex, personality_archetype, speech_style, relationship_stance, system_prompt)
           VALUES (1, ?, ?, ?, ?, ?, ?)""",
        (name, sex, personality_archetype, speech_style, relationship_stance, system_prompt)
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


def create_case(conn: sqlite3.Connection, *, archetype: str, title: str,
                case_data: dict) -> int:
    cur = conn.execute(
        "INSERT INTO cases (archetype, title, case_data) VALUES (?, ?, ?)",
        (archetype, title, json.dumps(case_data))
    )
    conn.commit()
    return cur.lastrowid


def get_case(conn: sqlite3.Connection, case_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()


def get_active_cases(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM cases WHERE status='active'").fetchall()


def update_case_status(conn: sqlite3.Connection, *, case_id: int, status: str,
                       trial_end_time: str | None = None,
                       trial_outcome: str | None = None) -> None:
    conn.execute(
        "UPDATE cases SET status=?, trial_end_time=?, trial_outcome=? WHERE id=?",
        (status, trial_end_time, trial_outcome, case_id)
    )
    conn.commit()


def create_npc(conn: sqlite3.Connection, *, case_id: int, name: str, role: str,
               system_prompt: str, current_location_id: int) -> int:
    cur = conn.execute(
        "INSERT INTO npcs (case_id, name, role, system_prompt, current_location_id) VALUES (?, ?, ?, ?, ?)",
        (case_id, name, role, system_prompt, current_location_id)
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


def add_evidence(conn: sqlite3.Connection, *, case_id: int, description: str,
                 source_npc_id: int | None, location_id: int) -> int:
    cur = conn.execute(
        "INSERT INTO evidence (case_id, description, source_npc_id, location_id) VALUES (?, ?, ?, ?)",
        (case_id, description, source_npc_id, location_id)
    )
    conn.commit()
    return cur.lastrowid


def get_evidence_for_case(conn: sqlite3.Connection, case_id: int) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM evidence WHERE case_id=?", (case_id,)).fetchall()


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
