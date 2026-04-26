from noir.neighborhoods import seed_neighborhoods, get_neighborhood_id


def test_neighborhoods_table_exists(db):
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='neighborhoods'"
    ).fetchone()
    assert row is not None


def test_neighborhood_factions_table_exists(db):
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='neighborhood_factions'"
    ).fetchone()
    assert row is not None


def test_neighborhood_adjacency_table_exists(db):
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='neighborhood_adjacency'"
    ).fetchone()
    assert row is not None


def test_locations_has_neighborhood_id(db):
    cols = [r[1] for r in db.execute("PRAGMA table_info('locations')").fetchall()]
    assert "neighborhood_id" in cols


def test_seed_neighborhoods_creates_all_12(db):
    seed_neighborhoods(db)
    count = db.execute("SELECT COUNT(*) FROM neighborhoods").fetchone()[0]
    assert count == 12


def test_seed_neighborhoods_idempotent(db):
    seed_neighborhoods(db)
    seed_neighborhoods(db)
    count = db.execute("SELECT COUNT(*) FROM neighborhoods").fetchone()[0]
    assert count == 12


def test_seed_adjacency_creates_edges(db):
    seed_neighborhoods(db)
    count = db.execute("SELECT COUNT(*) FROM neighborhood_adjacency").fetchone()[0]
    assert count == 30  # 15 pairs × 2 directions


def test_adjacency_is_symmetric(db):
    seed_neighborhoods(db)
    rows = db.execute(
        "SELECT from_id, to_id FROM neighborhood_adjacency"
    ).fetchall()
    pairs = {(r["from_id"], r["to_id"]) for r in rows}
    for from_id, to_id in list(pairs):
        assert (to_id, from_id) in pairs, f"Missing reverse edge {to_id} -> {from_id}"


def test_get_neighborhood_id(db):
    seed_neighborhoods(db)
    nid = get_neighborhood_id(db, "french_quarter")
    assert nid is not None
    assert isinstance(nid, int)
