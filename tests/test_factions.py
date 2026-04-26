import pytest
from noir.persistence.db import create_schema
import sqlite3


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    yield conn
    conn.close()


def test_all_factions_seeded_at_zero(db):
    from noir.persistence.repository import get_all_faction_reps
    reps = get_all_faction_reps(db)
    assert len(reps) == 19
    assert all(v == 0 for v in reps.values())


def test_faction_slugs_present(db):
    from noir.persistence.repository import get_all_faction_reps
    reps = get_all_faction_reps(db)
    for slug in [
        "da_office", "nopd", "parish_govt", "state_govt", "judiciary",
        "shorties", "tallboys", "chamber", "naacp",
        "rossi", "castellano", "ila_231", "colored_longshoremen",
        "archdiocese", "athletic_club", "knights_columbus", "treme_club",
        "bar_association", "press",
    ]:
        assert slug in reps, f"Missing faction: {slug}"


def test_private_not_seeded(db):
    from noir.persistence.repository import get_all_faction_reps
    reps = get_all_faction_reps(db)
    assert "private" not in reps


def test_job_offers_table_exists(db):
    db.execute("INSERT INTO npcs (name, role, system_prompt) VALUES ('Test', 'test', 'test')")
    npc_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute("INSERT INTO job_offers (npc_id) VALUES (?)", (npc_id,))
    db.commit()
    row = db.execute("SELECT * FROM job_offers").fetchone()
    assert row["accepted"] == 0


def test_cases_has_faction_tier_payout_columns(db):
    db.execute(
        "INSERT INTO cases (archetype, title, case_data, case_type, faction, tier, payout) "
        "VALUES ('job', 'Test Job', '{}', 'job', 'rossi', 1, 50)"
    )
    db.commit()
    row = db.execute("SELECT faction, tier, payout FROM cases WHERE case_type='job'").fetchone()
    assert row["faction"] == "rossi"
    assert row["tier"] == 1
    assert row["payout"] == 50


def test_get_faction_rep_returns_zero_initially(db):
    from noir.persistence.repository import get_faction_rep
    assert get_faction_rep(db, "rossi") == 0


def test_update_faction_rep_increases_rep(db):
    from noir.persistence.repository import update_faction_rep
    update_faction_rep(db, "rossi", 10)
    assert get_faction_rep(db, "rossi") == 10


def test_update_faction_rep_caps_at_100(db):
    from noir.persistence.repository import update_faction_rep
    update_faction_rep(db, "rossi", 200)
    assert get_faction_rep(db, "rossi") == 100


def test_update_faction_rep_floors_at_zero(db):
    from noir.persistence.repository import update_faction_rep
    update_faction_rep(db, "rossi", -50)
    assert get_faction_rep(db, "rossi") == 0


def test_update_faction_rep_returns_new_value(db):
    from noir.persistence.repository import update_faction_rep
    result = update_faction_rep(db, "rossi", 15)
    assert result == 15


def test_get_all_faction_reps_returns_dict(db):
    from noir.persistence.repository import update_faction_rep
    update_faction_rep(db, "rossi", 5)
    reps = get_all_faction_reps(db)
    assert isinstance(reps, dict)
    assert reps["rossi"] == 5
    assert reps["castellano"] == 0


def test_da_trust_migration_copies_to_faction_rep(db):
    from noir.persistence.repository import create_player, get_faction_rep
    from noir.persistence.db import _migrate_da_trust
    create_player(db)
    db.execute("UPDATE player SET da_trust=75 WHERE id=1")
    db.commit()
    db.execute("UPDATE faction_reputation SET reputation=0 WHERE faction='da_office'")
    db.commit()
    _migrate_da_trust(db)
    assert get_faction_rep(db, "da_office") == 75


def test_update_da_trust_writes_to_faction_rep(db):
    from noir.persistence.repository import update_da_trust, create_player
    create_player(db)
    update_da_trust(db, delta=20)
    assert get_faction_rep(db, "da_office") == 20


def test_update_da_trust_negative_delta(db):
    from noir.persistence.repository import update_da_trust, update_faction_rep, create_player
    create_player(db)
    update_faction_rep(db, "da_office", 50)
    update_da_trust(db, delta=-10)
    assert get_faction_rep(db, "da_office") == 40
