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


def test_check_purchase_from_dufour_adds_item(db):
    """When LLM confirms a sale, item is added and cash deducted."""
    import json
    from noir.persistence.repository import get_player_cash, update_player_cash, create_player
    from noir.llm.mock import MockLLMBackend
    create_player(db)
    game = _make_game(db)
    starting_cash = get_player_cash(db)
    # Fake npc_row
    npc_row = {"name": "Clarence Dufour"}
    # Mock LLM to return camera purchase (response must be a JSON string)
    game.llm = MockLLMBackend(responses=[
        json.dumps({"item_purchased": "camera", "quantity": 1})
    ])
    game._check_purchase_from_dufour(npc_row, "Sure, I'll take your twelve dollars — that camera is yours.")
    items = get_player_items(db)
    assert items.get("camera", 0) == 1
    cash = get_player_cash(db)
    assert cash == starting_cash - 12  # camera costs $12


def test_check_purchase_from_dufour_no_purchase_on_null(db):
    """When LLM returns null slug, no item is added."""
    import json
    from noir.llm.mock import MockLLMBackend
    game = _make_game(db)
    npc_row = {"name": "Clarence Dufour"}
    game.llm = MockLLMBackend(responses=[
        json.dumps({"item_purchased": None, "quantity": 0})
    ])
    game._check_purchase_from_dufour(npc_row, "I have cameras, yes. How much did you say you want to buy?")
    assert get_player_items(db) == {}


def test_check_purchase_from_dufour_ammo_adds_ten(db):
    """Ammo purchases always add 10 rounds regardless of LLM quantity."""
    import json
    from noir.persistence.repository import update_player_cash, create_player
    from noir.llm.mock import MockLLMBackend
    create_player(db)
    game = _make_game(db)
    update_player_cash(db, delta=100)
    npc_row = {"name": "Clarence Dufour"}
    game.llm = MockLLMBackend(responses=[
        json.dumps({"item_purchased": "ammo_38", "quantity": 1})
    ])
    game._check_purchase_from_dufour(npc_row, "Here are your cartridges — I want forty dollars for the box.")
    items = get_player_items(db)
    assert items.get("ammo_38", 0) == 10


def test_check_purchase_from_dufour_insufficient_cash(db):
    """When player can't afford it, no item is added."""
    import json
    from noir.persistence.repository import get_player_cash, create_player, update_player_cash
    from noir.llm.mock import MockLLMBackend
    create_player(db)
    # Drain cash to below camera price ($12)
    starting = get_player_cash(db)
    update_player_cash(db, delta=-(starting))  # drain to 0 (MAX(0,...) clamp)
    game = _make_game(db)
    npc_row = {"name": "Clarence Dufour"}
    game.llm = MockLLMBackend(responses=[
        json.dumps({"item_purchased": "camera", "quantity": 1})
    ])
    game._check_purchase_from_dufour(npc_row, "Sure, I'll take twelve dollars for that camera.")
    assert get_player_items(db) == {}
