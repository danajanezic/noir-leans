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
    relationship_notes TEXT,
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
    discovered INTEGER DEFAULT 0,
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

CREATE TABLE IF NOT EXISTS conversation_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    npc_opinion TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_conv_summaries_character ON conversation_summaries(character_id);

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

CREATE TABLE IF NOT EXISTS player_skills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner TEXT NOT NULL,
    root TEXT NOT NULL,
    level INTEGER DEFAULT 1,
    xp INTEGER DEFAULT 0,
    UNIQUE(owner, root)
);

CREATE TABLE IF NOT EXISTS player_specializations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner TEXT NOT NULL,
    root TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    unlocked_at_level INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS skill_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner TEXT NOT NULL,
    root TEXT NOT NULL,
    xp_awarded INTEGER NOT NULL,
    reason TEXT,
    case_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_player_skills_owner ON player_skills(owner);
CREATE INDEX IF NOT EXISTS idx_skill_events_owner_root ON skill_events(owner, root);

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

CREATE TABLE IF NOT EXISTS neighborhoods (
    id      INTEGER PRIMARY KEY,
    slug    TEXT UNIQUE NOT NULL,
    name    TEXT NOT NULL,
    danger  INTEGER NOT NULL DEFAULT 2
);

CREATE TABLE IF NOT EXISTS neighborhood_factions (
    neighborhood_id INTEGER NOT NULL REFERENCES neighborhoods(id),
    faction         TEXT NOT NULL,
    PRIMARY KEY (neighborhood_id, faction)
);

CREATE TABLE IF NOT EXISTS neighborhood_adjacency (
    from_id  INTEGER NOT NULL REFERENCES neighborhoods(id),
    to_id    INTEGER NOT NULL REFERENCES neighborhoods(id),
    distance INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (from_id, to_id)
);
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
    "ALTER TABLE locations ADD COLUMN discovered INTEGER DEFAULT 0",
    "CREATE TABLE IF NOT EXISTS conversation_summaries (id INTEGER PRIMARY KEY AUTOINCREMENT, character_id TEXT NOT NULL, summary TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
    "CREATE INDEX IF NOT EXISTS idx_conv_summaries_character ON conversation_summaries(character_id)",
    "ALTER TABLE conversation_summaries ADD COLUMN npc_opinion TEXT",
    "CREATE TABLE IF NOT EXISTS player_skills (id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, root TEXT NOT NULL, level INTEGER DEFAULT 1, xp INTEGER DEFAULT 0, UNIQUE(owner, root))",
    "CREATE TABLE IF NOT EXISTS player_specializations (id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, root TEXT NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL, unlocked_at_level INTEGER NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
    "CREATE TABLE IF NOT EXISTS skill_events (id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, root TEXT NOT NULL, xp_awarded INTEGER NOT NULL, reason TEXT, case_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
    "CREATE INDEX IF NOT EXISTS idx_player_skills_owner ON player_skills(owner)",
    "CREATE INDEX IF NOT EXISTS idx_skill_events_owner_root ON skill_events(owner, root)",
    "ALTER TABLE partner ADD COLUMN relationship_notes TEXT",
    "ALTER TABLE conversation_summaries ADD COLUMN case_id INTEGER",
    "ALTER TABLE npcs ADD COLUMN maiden_name TEXT",
    "ALTER TABLE npcs ADD COLUMN physical_description TEXT",
    "ALTER TABLE npcs ADD COLUMN detained INTEGER DEFAULT 0",
    "ALTER TABLE npcs ADD COLUMN sex TEXT",
    "ALTER TABLE conversation_history ADD COLUMN embedding BLOB",
    "ALTER TABLE cases ADD COLUMN faction TEXT",
    "ALTER TABLE cases ADD COLUMN tier INTEGER",
    "ALTER TABLE cases ADD COLUMN payout INTEGER",
    """CREATE TABLE IF NOT EXISTS faction_reputation (
        faction TEXT PRIMARY KEY,
        reputation INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS job_offers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        npc_id INTEGER NOT NULL,
        case_id INTEGER,
        offered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        accepted INTEGER DEFAULT 0,
        FOREIGN KEY (npc_id) REFERENCES npcs(id),
        FOREIGN KEY (case_id) REFERENCES cases(id)
    )""",
    "ALTER TABLE locations ADD COLUMN neighborhood_id INTEGER REFERENCES neighborhoods(id)",
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
        if row[1] == "case_id" and row[3] == 0:
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


def _migrate_da_trust(conn: sqlite3.Connection) -> None:
    """One-time copy of legacy player.da_trust into faction_reputation for da_office."""
    player = conn.execute("SELECT da_trust FROM player WHERE id=1").fetchone()
    if player is None:
        return
    da_trust = player["da_trust"] if player["da_trust"] is not None else 100
    existing = conn.execute(
        "SELECT reputation FROM faction_reputation WHERE faction='da_office'"
    ).fetchone()
    if existing is not None and existing["reputation"] == 0 and da_trust > 0:
        conn.execute(
            "UPDATE faction_reputation SET reputation=? WHERE faction='da_office'",
            (da_trust,)
        )
        conn.commit()


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
    try:
        from noir.jobs.factions import seed_faction_reputation
        seed_faction_reputation(conn)
    except ImportError:
        pass
    _migrate_da_trust(conn)
