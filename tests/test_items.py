import json
import pytest
from noir.persistence.db import create_schema
from noir.persistence.repository import (
    get_player_items, add_player_item, use_item,
)


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


def test_revolver_requires_ammo(db):
    row = db.execute("SELECT * FROM item_definitions WHERE slug='revolver_38'").fetchone()
    assert row["requires_slug"] == "ammo_38"
    actions = json.loads(row["actions"])
    assert "brandish" in actions
    assert "shoot" in actions
    assert actions["shoot"]["consumes"] == "ammo_38"


def test_player_items_table_exists(db):
    db.execute("SELECT * FROM player_items LIMIT 1")  # no error = table exists


@pytest.mark.xfail(reason="archetypes.json required_items added in Task 3")
def test_get_job_required_items_cheating_spouse():
    from noir.items import get_job_required_items
    reqs = get_job_required_items("cheating_spouse")
    assert len(reqs) == 1
    assert reqs[0]["slug"] == "camera"
    assert reqs[0]["needs_consumable"] is True


def test_get_job_required_items_unknown_returns_empty():
    from noir.items import get_job_required_items
    assert get_job_required_items("nonexistent_slug") == []


def test_detect_item_action_keyword_fallback(db):
    from noir.items import detect_item_action
    inventory = {"camera": 1, "film": 2}
    result = detect_item_action("I take a picture of them", inventory)
    assert result == ("camera", "photograph")


def test_detect_item_action_no_match(db):
    from noir.items import detect_item_action
    inventory = {"camera": 1}
    result = detect_item_action("I wave hello", inventory)
    assert result is None


def test_check_job_requirements_no_reqs(db):
    from noir.items import check_job_requirements
    # skip_trace has no required_items
    missing = check_job_requirements("skip_trace", {})
    assert missing == []


def test_detect_item_action_not_owned(db):
    from noir.items import detect_item_action
    inventory = {}  # no camera
    result = detect_item_action("I take a picture", inventory)
    assert result is None


def test_get_player_items_empty(db):
    items = get_player_items(db)
    assert items == {}


def test_add_player_item_creates_row(db):
    add_player_item(db, slug="camera", quantity=1)
    items = get_player_items(db)
    assert items["camera"] == 1


def test_add_player_item_stacks(db):
    add_player_item(db, slug="film", quantity=2)
    add_player_item(db, slug="film", quantity=3)
    items = get_player_items(db)
    assert items["film"] == 5


def test_use_item_decrements(db):
    add_player_item(db, slug="film", quantity=3)
    result = use_item(db, slug="film")
    assert result is True
    assert get_player_items(db)["film"] == 2


def test_use_item_fails_when_empty(db):
    result = use_item(db, slug="film")
    assert result is False


def test_use_item_fails_when_zero_quantity(db):
    add_player_item(db, slug="ammo_38", quantity=0)
    result = use_item(db, slug="ammo_38")
    assert result is False


def test_use_item_last_unit_removes_from_inventory(db):
    add_player_item(db, slug="film", quantity=1)
    use_item(db, slug="film")
    assert "film" not in get_player_items(db)


def test_treme_pawn_org_seeded(db):
    row = db.execute(
        "SELECT id FROM organizations WHERE name='Treme Pawn & Loan'"
    ).fetchone()
    assert row is not None


def test_check_job_requirements_missing(db):
    from noir.items import check_job_requirements
    inventory = {}  # no camera, no film
    missing = check_job_requirements("cheating_spouse", inventory)
    assert "Camera" in missing


def test_check_job_requirements_has_tool_but_missing_consumable(db):
    from noir.items import check_job_requirements
    inventory = {"camera": 1}  # camera present, no film
    missing = check_job_requirements("cheating_spouse", inventory)
    assert "Roll of Film" in missing
    assert "Camera" not in missing


def test_check_job_requirements_all_present(db):
    from noir.items import check_job_requirements
    inventory = {"camera": 1, "film": 2}
    missing = check_job_requirements("cheating_spouse", inventory)
    assert missing == []


def test_check_job_requirements_no_reqs(db):
    from noir.items import check_job_requirements
    inventory = {}
    missing = check_job_requirements("skip_trace", inventory)
    assert missing == []
