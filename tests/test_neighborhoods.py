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
