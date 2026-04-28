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


# --- handle_slash_use tests ---

def _make_game(db):
    from noir.game import Game
    from noir.llm.mock import MockLLMBackend
    return Game(conn=db, llm=MockLLMBackend())


def test_handle_slash_use_too_few_args(db):
    game = _make_game(db)
    # Should not raise even with empty args
    game.handle_slash_use("")


def test_handle_slash_use_item_not_owned(db):
    game = _make_game(db)
    # Player has no items — should not raise
    assert get_player_items(db) == {}
    game.handle_slash_use("camera photograph")


def test_handle_slash_use_consumes_film(db):
    game = _make_game(db)
    add_player_item(db, slug="camera", quantity=1)
    add_player_item(db, slug="film", quantity=3)
    game.handle_slash_use("camera photograph")
    items = get_player_items(db)
    assert items.get("film", 0) == 2


def test_handle_slash_use_missing_consumable(db):
    game = _make_game(db)
    add_player_item(db, slug="camera", quantity=1)
    # no film — action should be blocked, film quantity stays 0
    game.handle_slash_use("camera photograph")
    items = get_player_items(db)
    assert items.get("film", 0) == 0


def test_maybe_trigger_item_action_consumes_film(db):
    game = _make_game(db)
    add_player_item(db, slug="camera", quantity=1)
    add_player_item(db, slug="film", quantity=3)
    game._maybe_trigger_item_action("I take a picture of them")
    items = get_player_items(db)
    assert items.get("film", 0) == 2  # decremented by 1


def test_maybe_trigger_item_action_blocked_without_consumable(db):
    game = _make_game(db)
    add_player_item(db, slug="camera", quantity=1)
    # no film
    game._maybe_trigger_item_action("I take a picture of them")
    items = get_player_items(db)
    assert items.get("film", 0) == 0  # still 0 — action was blocked


def test_dufour_shop_purchase_adds_item(db):
    """Buying an item deducts cash and adds it to inventory."""
    from noir.persistence.repository import get_player_cash, create_player, update_player_cash
    from noir.items import get_item_def
    create_player(db)
    starting_cash = get_player_cash(db)
    item_def = get_item_def("camera")
    add_player_item(db, slug="camera", quantity=1)
    update_player_cash(db, delta=-item_def["price"])
    assert get_player_items(db).get("camera", 0) == 1
    assert get_player_cash(db) == starting_cash - 12


def test_dufour_shop_ammo_adds_ten(db):
    """Ammo purchases add 10 rounds."""
    from noir.persistence.repository import create_player, update_player_cash
    create_player(db)
    update_player_cash(db, delta=100)
    add_player_item(db, slug="ammo_38", quantity=10)
    assert get_player_items(db).get("ammo_38", 0) == 10


def test_dufour_shop_insufficient_cash_no_item(db):
    """Player with no cash cannot afford any item."""
    from noir.persistence.repository import create_player, update_player_cash, get_player_cash
    from noir.items import ITEM_CATALOG
    create_player(db)
    starting = get_player_cash(db)
    update_player_cash(db, delta=-starting)
    camera = next(i for i in ITEM_CATALOG if i["slug"] == "camera")
    assert get_player_cash(db) < camera["price"]
    assert get_player_items(db) == {}


def test_get_missing_items_no_active_job(db):
    game = _make_game(db)
    # No active jobs — should return empty
    result = game._get_missing_required_items_for_active_job()
    assert result == []


def test_get_missing_items_active_job_with_missing_items(db):
    import json
    from noir.persistence.repository import add_player_item
    game = _make_game(db)
    # Insert an active cheating_spouse job (requires camera + film)
    db.execute(
        "INSERT INTO cases (archetype, title, case_type, status, case_data, payout, faction, tier) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("job", "Test Job", "job", "active", json.dumps({"job_archetype": "cheating_spouse"}), 60, "private", 1)
    )
    db.commit()
    # No camera in inventory
    result = game._get_missing_required_items_for_active_job()
    assert "Camera" in result


def test_get_missing_items_active_job_requirements_met(db):
    import json
    from noir.persistence.repository import add_player_item
    game = _make_game(db)
    db.execute(
        "INSERT INTO cases (archetype, title, case_type, status, case_data, payout, faction, tier) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("job", "Test Job", "job", "active", json.dumps({"job_archetype": "cheating_spouse"}), 60, "private", 1)
    )
    db.commit()
    add_player_item(db, slug="camera", quantity=1)
    add_player_item(db, slug="film", quantity=2)
    result = game._get_missing_required_items_for_active_job()
    assert result == []


def test_handle_slash_done_blocked_missing_items(db):
    """Job cannot be completed via /done when required items are missing."""
    import json
    from noir.llm.mock import MockLLMBackend
    game = _make_game(db)
    # Insert active cheating_spouse job (requires camera + film)
    db.execute(
        "INSERT INTO cases (archetype, title, case_type, status, case_data, payout, faction, tier) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("cheating_spouse", "Test Job", "job", "active",
         json.dumps({"job_archetype": "cheating_spouse"}), 60, "private", 1)
    )
    db.commit()
    # No camera in inventory — mock LLM to say job is complete
    game.llm = MockLLMBackend(responses=[json.dumps({"completed": True, "reason": ""})])
    game.handle_slash_done()
    # Job should still be active (not completed)
    row = db.execute("SELECT status FROM cases WHERE case_type='job' AND archetype='cheating_spouse'").fetchone()
    assert row["status"] == "active"


def test_handle_slash_done_decrements_consumable(db):
    """Film is decremented after cheating_spouse job completes via /done."""
    import json
    from noir.llm.mock import MockLLMBackend
    from noir.persistence.repository import add_player_item
    game = _make_game(db)
    db.execute(
        "INSERT INTO cases (archetype, title, case_type, status, case_data, payout, faction, tier) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("cheating_spouse", "Test Job", "job", "active",
         json.dumps({"job_archetype": "cheating_spouse"}), 60, "private", 1)
    )
    db.commit()
    add_player_item(db, slug="camera", quantity=1)
    add_player_item(db, slug="film", quantity=3)
    # Mock LLM to say job is complete
    game.llm = MockLLMBackend(responses=[json.dumps({"completed": True, "reason": ""})])
    game.handle_slash_done()
    items = get_player_items(db)
    assert items.get("film", 0) == 2  # decremented by 1


def test_handle_slash_active_work_with_required_items_no_crash(db):
    """Verify /job display doesn't crash for a job with required items."""
    import json
    game = _make_game(db)
    db.execute(
        "INSERT INTO cases (case_type, status, case_data, payout, faction, tier, archetype, title) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("job", "active", json.dumps({
            "job_archetype": "cheating_spouse",
            "objective": "Find out if they're cheating.",
            "steps": [{"id": 1, "description": "Follow the subject.", "completed": False}]
        }), 60, "private", 1, "cheating_spouse", "Test Job")
    )
    db.commit()
    # No items in inventory — should not crash, just show yellow required items
    game.handle_slash_active_work()  # no exception = pass


def test_handle_slash_jobs_with_required_items_no_crash(db, monkeypatch):
    """Verify /classifieds display doesn't crash for jobs with required items."""
    import json
    import noir.game as game_module
    game = _make_game(db)
    db.execute(
        "INSERT INTO cases (case_type, status, case_data, payout, faction, tier, archetype, title) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("job", "pending", json.dumps({
            "job_archetype": "cheating_spouse",
            "objective": "Find out if they're cheating.",
            "steps": []
        }), 60, "private", 1, "cheating_spouse", "Test Job")
    )
    db.commit()
    # Stub out the interactive prompt so it doesn't block in tests
    monkeypatch.setattr(game_module.console, "input", lambda *a, **kw: "")
    game.handle_slash_jobs("")  # no exception = pass
