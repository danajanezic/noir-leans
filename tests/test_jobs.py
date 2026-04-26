import pytest
import sqlite3
from noir.persistence.db import create_schema
from noir.persistence.repository import (
    create_player,
    get_faction_rep, update_faction_rep,
    create_job, get_active_jobs, get_available_jobs,
    create_job_offer, accept_job_offer, decline_job_offer, get_pending_job_offers,
    complete_job, fail_job,
    get_player_cash,
)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    create_player(conn)
    yield conn
    conn.close()


@pytest.fixture
def npc_id(db):
    db.execute("INSERT INTO npcs (name, role, system_prompt) VALUES ('Test NPC', 'test', 'test')")
    db.commit()
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def test_create_job_stores_faction_tier_payout(db):
    job_id = create_job(db, faction="rossi", tier=1, title="Rough Errand",
                        payout=50, case_data={"objective": "Find Vitale"})
    row = db.execute("SELECT * FROM cases WHERE id=?", (job_id,)).fetchone()
    assert row["case_type"] == "job"
    assert row["faction"] == "rossi"
    assert row["tier"] == 1
    assert row["payout"] == 50
    assert row["status"] == "pending"


def test_get_available_jobs_returns_only_tier1(db):
    create_job(db, faction="rossi", tier=1, title="Tier1 Job", payout=50, case_data={})
    create_job(db, faction="naacp", tier=2, title="Tier2 Job", payout=150, case_data={})
    jobs = get_available_jobs(db)
    titles = [j["title"] for j in jobs]
    assert "Tier1 Job" in titles
    assert "Tier2 Job" not in titles  # tier 2+ are NPC-only, never on the board


def test_get_available_jobs_excludes_tier2_even_with_rep(db):
    update_faction_rep(db, "naacp", 30)
    create_job(db, faction="naacp", tier=2, title="Tier2 Job", payout=150, case_data={})
    jobs = get_available_jobs(db)
    titles = [j["title"] for j in jobs]
    assert "Tier2 Job" not in titles  # tier 2+ only surface through NPC offers


def test_on_hold_job_not_returned_by_get_active_jobs(db):
    job_id = create_job(db, faction="rossi", tier=1, title="On Hold Job", payout=50, case_data={})
    db.execute("UPDATE cases SET status='on_hold' WHERE id=?", (job_id,))
    db.commit()
    jobs = get_active_jobs(db)
    assert len(jobs) == 0


def test_get_active_jobs_returns_accepted_jobs(db):
    job_id = create_job(db, faction="rossi", tier=1, title="Active Job", payout=50, case_data={})
    db.execute("UPDATE cases SET status='active' WHERE id=?", (job_id,))
    db.commit()
    jobs = get_active_jobs(db)
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Active Job"


def test_complete_job_pays_out_and_increases_rep(db):
    job_id = create_job(db, faction="rossi", tier=1, title="Done Job", payout=60, case_data={})
    db.execute("UPDATE cases SET status='active' WHERE id=?", (job_id,))
    db.commit()
    complete_job(db, case_id=job_id, payout=60, faction="rossi", tier=1)
    assert get_player_cash(db) == 560  # 500 starting + 60
    assert get_faction_rep(db, "rossi") == 8  # tier 1 gain


def test_complete_rossi_job_hurts_castellano(db):
    update_faction_rep(db, "castellano", 20)
    job_id = create_job(db, faction="rossi", tier=1, title="Rossi Job", payout=50, case_data={})
    db.execute("UPDATE cases SET status='active' WHERE id=?", (job_id,))
    db.commit()
    complete_job(db, case_id=job_id, payout=50, faction="rossi", tier=1)
    assert get_faction_rep(db, "castellano") == 12  # 20 - 8


def test_complete_shorties_job_does_not_hurt_naacp(db):
    update_faction_rep(db, "naacp", 30)
    job_id = create_job(db, faction="shorties", tier=1, title="Shorties Job", payout=50, case_data={})
    db.execute("UPDATE cases SET status='active' WHERE id=?", (job_id,))
    db.commit()
    complete_job(db, case_id=job_id, payout=50, faction="shorties", tier=1)
    assert get_faction_rep(db, "naacp") == 30  # unchanged


def test_complete_tallboys_job_hurts_naacp(db):
    update_faction_rep(db, "naacp", 30)
    job_id = create_job(db, faction="tallboys", tier=1, title="Tallboys Job", payout=50, case_data={})
    db.execute("UPDATE cases SET status='active' WHERE id=?", (job_id,))
    db.commit()
    complete_job(db, case_id=job_id, payout=50, faction="tallboys", tier=1)
    assert get_faction_rep(db, "naacp") == 22  # 30 - 8


def test_complete_tallboys_job_hurts_treme_and_colored_longshoremen(db):
    update_faction_rep(db, "treme_club", 20)
    update_faction_rep(db, "colored_longshoremen", 20)
    job_id = create_job(db, faction="tallboys", tier=1, title="Tallboys Job 2", payout=50, case_data={})
    db.execute("UPDATE cases SET status='active' WHERE id=?", (job_id,))
    db.commit()
    complete_job(db, case_id=job_id, payout=50, faction="tallboys", tier=1)
    assert get_faction_rep(db, "treme_club") == 12          # 20 - 8
    assert get_faction_rep(db, "colored_longshoremen") == 12  # 20 - 8


def test_fail_job_applies_rep_penalty_no_payout(db):
    job_id = create_job(db, faction="rossi", tier=1, title="Failed Job", payout=60, case_data={})
    db.execute("UPDATE cases SET status='active' WHERE id=?", (job_id,))
    db.commit()
    update_faction_rep(db, "rossi", 20)
    fail_job(db, case_id=job_id, faction="rossi", tier=1)
    assert get_player_cash(db) == 500  # no payout
    assert get_faction_rep(db, "rossi") == 10  # 20 - 10
    row = db.execute("SELECT status FROM cases WHERE id=?", (job_id,)).fetchone()
    assert row["status"] == "failed"


def test_job_offer_created_and_declined(db, npc_id):
    offer_id = create_job_offer(db, npc_id=npc_id)
    offers = get_pending_job_offers(db)
    assert len(offers) == 1
    decline_job_offer(db, offer_id=offer_id)
    offers = get_pending_job_offers(db)
    assert len(offers) == 0


def test_job_offer_accepted_links_case(db, npc_id):
    offer_id = create_job_offer(db, npc_id=npc_id)
    job_id = create_job(db, faction="rossi", tier=1, title="Offered Job", payout=50, case_data={})
    db.execute("UPDATE cases SET status='active' WHERE id=?", (job_id,))
    db.commit()
    accept_job_offer(db, offer_id=offer_id, case_id=job_id)
    row = db.execute("SELECT * FROM job_offers WHERE id=?", (offer_id,)).fetchone()
    assert row["accepted"] == 1
    assert row["case_id"] == job_id


from noir.jobs.factions import TENSION_THRESHOLD, OPPOSITION
from noir.persistence.repository import get_all_faction_reps


def test_opposing_factions_above_threshold_detected(db):
    update_faction_rep(db, "rossi", TENSION_THRESHOLD)
    update_faction_rep(db, "castellano", TENSION_THRESHOLD)
    reps = get_all_faction_reps(db)
    tension_pairs = []
    for faction, rep in reps.items():
        if rep < TENSION_THRESHOLD:
            continue
        if faction not in OPPOSITION:
            continue
        for opp in OPPOSITION[faction].get("direct", []):
            if reps.get(opp, 0) >= TENSION_THRESHOLD:
                tension_pairs.append((faction, opp))
    assert ("rossi", "castellano") in tension_pairs or ("castellano", "rossi") in tension_pairs


def test_neutral_factions_do_not_trigger_tension(db):
    update_faction_rep(db, "shorties", TENSION_THRESHOLD)
    update_faction_rep(db, "naacp", TENSION_THRESHOLD)
    reps = get_all_faction_reps(db)
    tension_pairs = []
    for faction, rep in reps.items():
        if rep < TENSION_THRESHOLD:
            continue
        if faction not in OPPOSITION:
            continue
        for opp in OPPOSITION[faction].get("direct", []):
            if reps.get(opp, 0) >= TENSION_THRESHOLD:
                tension_pairs.append((faction, opp))
    assert ("shorties", "naacp") not in tension_pairs
    assert ("naacp", "shorties") not in tension_pairs
