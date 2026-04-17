import sqlite3
from pathlib import Path

DB_PATH = Path.home() / ".noir_detective" / "game.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS player (
    id INTEGER PRIMARY KEY,
    reputation INTEGER DEFAULT 100,
    cases_solved INTEGER DEFAULT 0,
    wrong_arrests INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS partner (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    sex TEXT NOT NULL,
    personality_archetype TEXT NOT NULL,
    speech_style TEXT NOT NULL,
    relationship_stance TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conversation_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    case_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    archetype TEXT NOT NULL,
    title TEXT NOT NULL,
    case_data TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    trial_end_time TEXT,
    trial_outcome TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    is_fixed INTEGER DEFAULT 0,
    case_id INTEGER,
    FOREIGN KEY (case_id) REFERENCES cases(id)
);

CREATE TABLE IF NOT EXISTS npcs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    current_location_id INTEGER,
    FOREIGN KEY (case_id) REFERENCES cases(id),
    FOREIGN KEY (current_location_id) REFERENCES locations(id)
);

CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    source_npc_id INTEGER,
    location_id INTEGER NOT NULL,
    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (case_id) REFERENCES cases(id)
);

CREATE TABLE IF NOT EXISTS arrests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL,
    npc_id INTEGER NOT NULL,
    evidence_summary TEXT NOT NULL,
    was_correct INTEGER,
    arrested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (case_id) REFERENCES cases(id),
    FOREIGN KEY (npc_id) REFERENCES npcs(id)
);

CREATE TABLE IF NOT EXISTS character_locations (
    character_id TEXT PRIMARY KEY,
    location_id INTEGER NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (location_id) REFERENCES locations(id)
);

CREATE TABLE IF NOT EXISTS mystery_archetypes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    seed_prompt TEXT NOT NULL
);
"""


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
