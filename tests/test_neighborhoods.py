from noir.neighborhoods import seed_neighborhoods, get_neighborhood_id
from noir.persistence.repository import (
    get_neighborhood_for_location,
    get_travel_distance,
    get_neighborhood_factions,
    get_all_neighborhoods,
    get_neighborhood_by_slug,
    update_neighborhood_danger,
)


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


def test_get_all_neighborhoods(db):
    seed_neighborhoods(db)
    hoods = get_all_neighborhoods(db)
    assert len(hoods) == 12
    assert any(h["slug"] == "french_quarter" for h in hoods)


def test_get_neighborhood_factions(db):
    seed_neighborhoods(db)
    factions = get_neighborhood_factions(db, "french_quarter")
    assert set(factions) == {"nopd", "rossi", "archdiocese"}


def test_get_travel_distance_adjacent(db):
    seed_neighborhoods(db)
    dist = get_travel_distance(db, "french_quarter", "marigny")
    assert dist == 1


def test_get_travel_distance_not_connected(db):
    seed_neighborhoods(db)
    dist = get_travel_distance(db, "lower_ninth", "uptown")
    assert dist is None


def test_get_neighborhood_for_location(db):
    seed_neighborhoods(db)
    nid = db.execute(
        "SELECT id FROM neighborhoods WHERE slug='french_quarter'"
    ).fetchone()["id"]
    loc_id = db.execute(
        "INSERT INTO locations (name, description, is_fixed, neighborhood_id) VALUES (?, ?, 1, ?) RETURNING id",
        ("Café Du Monde", "A famous café.", nid)
    ).fetchone()["id"]
    db.commit()
    result = get_neighborhood_for_location(db, loc_id)
    assert result is not None
    assert result["slug"] == "french_quarter"


def test_get_neighborhood_by_slug(db):
    seed_neighborhoods(db)
    row = get_neighborhood_by_slug(db, "french_quarter")
    assert row is not None
    assert row["slug"] == "french_quarter"


def test_get_neighborhood_by_slug_missing(db):
    seed_neighborhoods(db)
    assert get_neighborhood_by_slug(db, "nonexistent") is None


def test_update_neighborhood_danger(db):
    seed_neighborhoods(db)
    update_neighborhood_danger(db, "french_quarter", 4)
    row = get_neighborhood_by_slug(db, "french_quarter")
    assert row["danger"] == 4
