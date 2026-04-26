from unittest.mock import MagicMock
from noir.neighborhoods import (
    seed_neighborhoods, get_neighborhood_id, compute_danger, recompute_all_danger, travel_time_minutes,
    assign_locations_to_neighborhoods, seed_bartenders, get_bartender_for_neighborhood,
)
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


def test_compute_danger_base():
    assert compute_danger([]) == 1


def test_compute_danger_no_opposing_factions():
    assert compute_danger(["archdiocese"]) == 1


def test_compute_danger_direct_opposition():
    assert compute_danger(["rossi", "castellano"]) == 3


def test_compute_danger_secondary_opposition():
    assert compute_danger(["nopd", "rossi"]) == 3


def test_compute_danger_clamps_to_5():
    danger = compute_danger(["rossi", "castellano", "nopd", "treme_club", "tallboys", "shorties"])
    assert danger <= 5
    assert danger >= 1


def test_recompute_all_danger_updates_db(db):
    seed_neighborhoods(db)
    recompute_all_danger(db)
    row = db.execute(
        "SELECT danger FROM neighborhoods WHERE slug='french_quarter'"
    ).fetchone()
    assert 1 <= row["danger"] <= 5


def test_travel_time_adjacent():
    assert travel_time_minutes(distance=1, is_ferry=False) == 15


def test_travel_time_two_blocks():
    assert travel_time_minutes(distance=2, is_ferry=False) == 30


def test_travel_time_ferry_surcharge():
    assert travel_time_minutes(distance=2, is_ferry=True) == 45


def test_fixed_locations_get_neighborhood(db):
    seed_neighborhoods(db)
    db.execute(
        "INSERT OR IGNORE INTO locations (name, description, is_fixed) VALUES (?, ?, 1)",
        ("Café Du Monde", "A famous café in the French Quarter near Jackson Square.")
    )
    db.commit()
    assign_locations_to_neighborhoods(db)
    row = db.execute(
        "SELECT neighborhood_id FROM locations WHERE name='Café Du Monde'"
    ).fetchone()
    assert row["neighborhood_id"] is not None


def test_get_bartender_for_neighborhood_none_before_seeding(db):
    seed_neighborhoods(db)
    assert get_bartender_for_neighborhood(db, "french_quarter") is None


def test_seed_bartenders_creates_npc(db):
    seed_neighborhoods(db)
    mock_llm = MagicMock()
    mock_llm.query.return_value = (
        '{"name": "Marie Tureaud", "sex": "female", "age": 38, '
        '"ethnicity": "Creole", "personality": "sharp and guarded", '
        '"bar_name": "The Gold Tooth", "bar_description": "A dim bar off Bourbon."}'
    )
    seed_bartenders(db, mock_llm)
    result = get_bartender_for_neighborhood(db, "french_quarter")
    assert result is not None
    assert result["name"] == "Marie Tureaud"


def test_seed_bartenders_idempotent(db):
    seed_neighborhoods(db)
    mock_llm = MagicMock()
    mock_llm.query.return_value = (
        '{"name": "Joe Blanc", "sex": "male", "age": 45, '
        '"ethnicity": "Cajun", "personality": "friendly", '
        '"bar_name": "The Rusty Nail", "bar_description": "A dive bar."}'
    )
    seed_bartenders(db, mock_llm)
    seed_bartenders(db, mock_llm)
    rows = db.execute("SELECT COUNT(*) FROM npcs WHERE role='bartender'").fetchone()[0]
    assert rows == 12
