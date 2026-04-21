import sqlite3
from pathlib import Path

DB_PATH = Path.home() / ".noir_detective" / "game.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS player (
    id INTEGER PRIMARY KEY,
    reputation INTEGER DEFAULT 100,
    cases_solved INTEGER DEFAULT 0,
    wrong_arrests INTEGER DEFAULT 0,
    race TEXT DEFAULT 'unspecified',
    gender TEXT DEFAULT 'unspecified',
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
    affection INTEGER DEFAULT 0,
    dark_past_state TEXT DEFAULT 'none',
    dark_past TEXT,
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
    case_type TEXT DEFAULT 'standard',
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
    case_id INTEGER,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    current_location_id INTEGER,
    FOREIGN KEY (case_id) REFERENCES cases(id),
    FOREIGN KEY (current_location_id) REFERENCES locations(id)
);

CREATE TABLE IF NOT EXISTS clues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    location TEXT,
    is_red_herring INTEGER DEFAULT 0,
    FOREIGN KEY (case_id) REFERENCES cases(id)
);

CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL,
    clue_id INTEGER NOT NULL,
    source_npc_id INTEGER,
    accused_npc_id INTEGER,
    location_id INTEGER NOT NULL,
    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (case_id) REFERENCES cases(id),
    FOREIGN KEY (clue_id) REFERENCES clues(id),
    FOREIGN KEY (source_npc_id) REFERENCES npcs(id),
    FOREIGN KEY (accused_npc_id) REFERENCES npcs(id)
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

CREATE TABLE IF NOT EXISTS bribes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER,
    npc_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    accepted INTEGER DEFAULT 0,
    effect TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (case_id) REFERENCES cases(id),
    FOREIGN KEY (npc_id) REFERENCES npcs(id)
);

CREATE INDEX IF NOT EXISTS idx_bribes_case ON bribes(case_id);

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

CREATE TABLE IF NOT EXISTS player_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    state TEXT NOT NULL UNIQUE,
    intensity INTEGER DEFAULT 1,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS player_suspects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    note TEXT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (case_id) REFERENCES cases(id)
);

CREATE TABLE IF NOT EXISTS npc_relationships (
    npc_id INTEGER PRIMARY KEY,
    affection INTEGER DEFAULT 0,
    clue_volunteered INTEGER DEFAULT 0,
    secret_revealed INTEGER DEFAULT 0,
    FOREIGN KEY (npc_id) REFERENCES npcs(id)
);

CREATE TABLE IF NOT EXISTS dossier (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL,
    npc_name TEXT NOT NULL,
    fact TEXT NOT NULL,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (case_id) REFERENCES cases(id)
);

CREATE TABLE IF NOT EXISTS npc_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    npc_id INTEGER NOT NULL,
    time_start INTEGER NOT NULL,
    time_end INTEGER NOT NULL,
    location_name TEXT NOT NULL,
    FOREIGN KEY (npc_id) REFERENCES npcs(id)
);

CREATE TABLE IF NOT EXISTS npc_appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    npc_id INTEGER NOT NULL,
    game_time INTEGER NOT NULL,
    location_name TEXT NOT NULL,
    fulfilled INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (npc_id) REFERENCES npcs(id)
);

CREATE TABLE IF NOT EXISTS suspects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER,
    npc_id INTEGER NOT NULL UNIQUE,
    is_killer INTEGER DEFAULT 0,
    met INTEGER DEFAULT 0,
    race TEXT,
    political_connections TEXT,
    alibi TEXT,
    secret TEXT,
    backstory TEXT,
    relationships TEXT,
    FOREIGN KEY (case_id) REFERENCES cases(id),
    FOREIGN KEY (npc_id) REFERENCES npcs(id)
);

CREATE INDEX IF NOT EXISTS idx_suspects_case ON suspects(case_id);
CREATE INDEX IF NOT EXISTS idx_dossier_case_name ON dossier(case_id, npc_name);
CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);
CREATE INDEX IF NOT EXISTS idx_clues_case ON clues(case_id);
CREATE INDEX IF NOT EXISTS idx_npc_schedules_npc ON npc_schedules(npc_id);
CREATE INDEX IF NOT EXISTS idx_npc_appointments_npc ON npc_appointments(npc_id);
CREATE INDEX IF NOT EXISTS idx_conversation_history_character ON conversation_history(character_id);
CREATE INDEX IF NOT EXISTS idx_conversation_history_case ON conversation_history(case_id);
CREATE INDEX IF NOT EXISTS idx_npcs_case ON npcs(case_id);
CREATE INDEX IF NOT EXISTS idx_evidence_case ON evidence(case_id);
CREATE INDEX IF NOT EXISTS idx_arrests_case ON arrests(case_id);
CREATE INDEX IF NOT EXISTS idx_locations_case ON locations(case_id);

CREATE TABLE IF NOT EXISTS seeded_locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    type TEXT
);

CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    source_npc TEXT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (case_id) REFERENCES cases(id)
);

CREATE TABLE IF NOT EXISTS street_reputation (
    id INTEGER PRIMARY KEY,
    tags TEXT DEFAULT '[]',
    street_says TEXT DEFAULT '',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL,
    description TEXT NOT NULL,
    is_hierarchical INTEGER DEFAULT 0,
    is_seeded INTEGER DEFAULT 0,
    influence INTEGER DEFAULT 5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS organization_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL,
    member_type TEXT NOT NULL DEFAULT 'npc',
    member_id INTEGER NOT NULL,
    role TEXT,
    is_static INTEGER DEFAULT 0,
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (organization_id) REFERENCES organizations(id)
);

CREATE TABLE IF NOT EXISTS location_organizations (
    location_id INTEGER NOT NULL,
    organization_id INTEGER NOT NULL,
    PRIMARY KEY (location_id, organization_id),
    FOREIGN KEY (organization_id) REFERENCES organizations(id)
);

CREATE INDEX IF NOT EXISTS idx_org_members_org ON organization_members(organization_id);
CREATE INDEX IF NOT EXISTS idx_org_members_member ON organization_members(member_type, member_id);
"""


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


_MIGRATIONS = [
    "ALTER TABLE partner ADD COLUMN affection INTEGER DEFAULT 0",
    "ALTER TABLE partner ADD COLUMN dark_past_state TEXT DEFAULT 'none'",
    "ALTER TABLE partner ADD COLUMN dark_past TEXT",
    "ALTER TABLE cases ADD COLUMN case_type TEXT DEFAULT 'standard'",
    "ALTER TABLE player ADD COLUMN race TEXT DEFAULT 'unspecified'",
    "ALTER TABLE player ADD COLUMN gender TEXT DEFAULT 'unspecified'",
    "ALTER TABLE evidence ADD COLUMN clue_id INTEGER REFERENCES clues(id)",
    "ALTER TABLE player ADD COLUMN game_time INTEGER DEFAULT 480",
    "ALTER TABLE evidence ADD COLUMN accused_npc_id INTEGER REFERENCES npcs(id)",
    "ALTER TABLE player ADD COLUMN law_chaos INTEGER DEFAULT 0",
    "ALTER TABLE player ADD COLUMN good_evil INTEGER DEFAULT 0",
    "ALTER TABLE partner ADD COLUMN alignment TEXT DEFAULT 'True Neutral'",
    "ALTER TABLE npcs ADD COLUMN alignment TEXT DEFAULT 'True Neutral'",
    "ALTER TABLE npcs ADD COLUMN age INTEGER DEFAULT 35",
    "ALTER TABLE npcs ADD COLUMN pressure_tolerance INTEGER DEFAULT 5",
    "ALTER TABLE npcs ADD COLUMN kindness_weight INTEGER DEFAULT 5",
    "ALTER TABLE npcs ADD COLUMN empathy INTEGER DEFAULT 5",
    "ALTER TABLE npcs ADD COLUMN starting_guilt INTEGER DEFAULT 0",
    "ALTER TABLE npcs ADD COLUMN revelation_style TEXT DEFAULT 'staged'",
    "ALTER TABLE npcs ADD COLUMN revelation_stages INTEGER DEFAULT 3",
    "ALTER TABLE npc_relationships ADD COLUMN guilt INTEGER DEFAULT 0",
    "ALTER TABLE npc_relationships ADD COLUMN pressure_score INTEGER DEFAULT 0",
    "ALTER TABLE npc_relationships ADD COLUMN revelation_stage INTEGER DEFAULT 0",
    "ALTER TABLE suspects ADD COLUMN archetype_id TEXT",
    "CREATE TABLE IF NOT EXISTS street_reputation (id INTEGER PRIMARY KEY, tags TEXT DEFAULT '[]', street_says TEXT DEFAULT '', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
    "ALTER TABLE npc_relationships ADD COLUMN revelation_summary TEXT",
    "ALTER TABLE player ADD COLUMN da_trust INTEGER DEFAULT 100",
    "ALTER TABLE cases ADD COLUMN assigned_judge_id INTEGER",
    "ALTER TABLE player ADD COLUMN cash INTEGER DEFAULT 500",
    "ALTER TABLE npcs ADD COLUMN corruption INTEGER DEFAULT 0",
    "ALTER TABLE organization_members ADD COLUMN payroll INTEGER DEFAULT 0",
    "ALTER TABLE organization_members ADD COLUMN last_payroll_time INTEGER DEFAULT 0",
]


def _backfill_clues(conn: sqlite3.Connection) -> None:
    """Populate clues table from case_data JSON for any cases that have none."""
    import json as _json
    cases = conn.execute("SELECT id, case_data FROM cases").fetchall()
    for case in cases:
        existing = conn.execute(
            "SELECT COUNT(*) FROM clues WHERE case_id=?", (case["id"],)
        ).fetchone()[0]
        if existing:
            continue
        try:
            cd = _json.loads(case["case_data"])
        except Exception:
            continue
        for clue in cd.get("clues", []):
            conn.execute(
                "INSERT INTO clues (case_id, description, location, is_red_herring) VALUES (?, ?, ?, ?)",
                (case["id"], clue["description"],
                 clue.get("location"), 1 if clue.get("is_red_herring") else 0)
            )
    conn.commit()


def _make_case_id_nullable(conn: sqlite3.Connection) -> None:
    """Recreate npcs and suspects tables to allow case_id=NULL (world-persistent rows)."""
    for row in conn.execute("PRAGMA table_info('npcs')").fetchall():
        if row["name"] == "case_id" and row["notnull"] == 0:
            return  # already nullable

    conn.executescript("""
PRAGMA foreign_keys = OFF;

DROP TABLE IF EXISTS npcs_new;
CREATE TABLE npcs_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    current_location_id INTEGER,
    alignment TEXT DEFAULT 'True Neutral',
    age INTEGER DEFAULT 35,
    pressure_tolerance INTEGER DEFAULT 5,
    kindness_weight INTEGER DEFAULT 5,
    empathy INTEGER DEFAULT 5,
    starting_guilt INTEGER DEFAULT 0,
    revelation_style TEXT DEFAULT 'staged',
    revelation_stages INTEGER DEFAULT 3,
    FOREIGN KEY (case_id) REFERENCES cases(id),
    FOREIGN KEY (current_location_id) REFERENCES locations(id)
);
INSERT INTO npcs_new SELECT * FROM npcs;
DROP TABLE npcs;
ALTER TABLE npcs_new RENAME TO npcs;

DROP TABLE IF EXISTS suspects_new;
CREATE TABLE suspects_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER,
    npc_id INTEGER NOT NULL UNIQUE,
    is_killer INTEGER DEFAULT 0,
    met INTEGER DEFAULT 0,
    race TEXT,
    political_connections TEXT,
    alibi TEXT,
    secret TEXT,
    backstory TEXT,
    relationships TEXT,
    archetype_id TEXT,
    FOREIGN KEY (case_id) REFERENCES cases(id),
    FOREIGN KEY (npc_id) REFERENCES npcs(id)
);
INSERT INTO suspects_new SELECT * FROM suspects;
DROP TABLE suspects;
ALTER TABLE suspects_new RENAME TO suspects;

CREATE INDEX IF NOT EXISTS idx_suspects_case ON suspects(case_id);
CREATE INDEX IF NOT EXISTS idx_npcs_case ON npcs(case_id);

PRAGMA foreign_keys = ON;
""")


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for sql in _MIGRATIONS:
        try:
            conn.execute(sql)
        except Exception:
            pass  # column already exists
    conn.commit()
    _make_case_id_nullable(conn)
    _backfill_clues(conn)
    from noir.organizations import seed_organizations
    seed_organizations(conn)
