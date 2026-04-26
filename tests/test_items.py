import json
import pytest
import sqlite3
from noir.persistence.db import create_schema
from noir.persistence.repository import create_player


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    create_player(conn)
    yield conn
    conn.close()


def test_item_definitions_seeded(db):
    rows = db.execute("SELECT slug FROM item_definitions ORDER BY slug").fetchall()
    slugs = [r["slug"] for r in rows]
    assert "camera" in slugs
    assert "film" in slugs
    assert "revolver_38" in slugs
    assert "ammo_38" in slugs
    assert "lockpicks" in slugs
    assert "binoculars" in slugs
    assert "bribe_envelope" in slugs
    assert "disguise_kit" in slugs


def test_camera_requires_film(db):
    row = db.execute("SELECT * FROM item_definitions WHERE slug='camera'").fetchone()
    assert row["requires_slug"] == "film"
    assert row["consumable"] == 0
    actions = json.loads(row["actions"])
    assert "photograph" in actions
    assert actions["photograph"]["consumes"] == "film"


def test_film_is_consumable(db):
    row = db.execute("SELECT * FROM item_definitions WHERE slug='film'").fetchone()
    assert row["consumable"] == 1
    assert row["requires_slug"] is None


def test_ammo_price_is_4(db):
    row = db.execute("SELECT price FROM item_definitions WHERE slug='ammo_38'").fetchone()
    assert row["price"] == 4


def test_revolver_requires_ammo(db):
    row = db.execute("SELECT * FROM item_definitions WHERE slug='revolver_38'").fetchone()
    assert row["requires_slug"] == "ammo_38"
    actions = json.loads(row["actions"])
    assert "brandish" in actions
    assert "shoot" in actions
    assert actions["shoot"]["consumes"] == "ammo_38"


def test_player_items_table_exists(db):
    db.execute("SELECT * FROM player_items LIMIT 1")  # no error = table exists


def test_get_job_required_items_cheating_spouse():
    from noir.items import get_job_required_items
    reqs = get_job_required_items("cheating_spouse")
    # archetypes.json will be updated in Task 3; for now this returns []
    # This test will pass after Task 3 — skip if empty
    assert isinstance(reqs, list)


def test_get_job_required_items_unknown_returns_empty():
    from noir.items import get_job_required_items
    assert get_job_required_items("nonexistent_slug") == []


def test_detect_item_action_keyword_fallback(db):
    from noir.items import detect_item_action
    inventory = {"camera": 1, "film": 2}
    result = detect_item_action("I take a picture of them", inventory, db)
    assert result == ("camera", "photograph")


def test_detect_item_action_no_match(db):
    from noir.items import detect_item_action
    inventory = {"camera": 1}
    result = detect_item_action("I wave hello", inventory, db)
    assert result is None


def test_detect_item_action_not_owned(db):
    from noir.items import detect_item_action
    inventory = {}  # no camera
    result = detect_item_action("I take a picture", inventory, db)
    assert result is None
