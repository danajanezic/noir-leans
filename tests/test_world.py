import pytest
from noir.world import World
from noir.persistence.repository import (
    create_case, create_location, create_npc
)


@pytest.fixture
def world_db(db):
    loc1 = create_location(db, name="The Rusty Anchor", description="Sticky floors.", is_fixed=True)
    loc2 = create_location(db, name="The Precinct", description="Stale coffee.", is_fixed=True)
    case_id = create_case(db, archetype="Christie", title="Test", case_data={})
    loc3 = create_location(db, name="Victim's Mansion", description="Ostentatious.", is_fixed=False, case_id=case_id)
    npc_id = create_npc(db, case_id=case_id, name="Dolores", role="suspect",
                        system_prompt="You are Dolores.", current_location_id=loc1)
    return db, loc1, loc2, loc3, npc_id, case_id


def test_world_lists_all_locations(world_db):
    db, loc1, loc2, loc3, _, case_id = world_db
    world = World(conn=db, active_case_id=case_id)
    locations = world.list_locations()
    names = {loc["name"] for loc in locations}
    assert "The Rusty Anchor" in names
    assert "The Precinct" in names
    assert "Victim's Mansion" in names


def test_world_get_npcs_at_location(world_db):
    db, loc1, _, _, npc_id, case_id = world_db
    world = World(conn=db, active_case_id=case_id)
    npcs = world.get_npcs_at(loc1)
    assert len(npcs) == 1
    assert npcs[0]["name"] == "Dolores"


def test_world_get_npcs_at_empty_location(world_db):
    db, _, loc2, _, _, case_id = world_db
    world = World(conn=db, active_case_id=case_id)
    assert world.get_npcs_at(loc2) == []


def test_world_find_location_by_name(world_db):
    db, loc1, _, _, _, case_id = world_db
    world = World(conn=db, active_case_id=case_id)
    loc = world.find_location("rusty anchor")
    assert loc is not None
    assert loc["id"] == loc1


def test_world_find_location_case_insensitive(world_db):
    db, _, loc2, _, _, case_id = world_db
    world = World(conn=db, active_case_id=case_id)
    loc = world.find_location("THE PRECINCT")
    assert loc is not None


def test_world_find_location_returns_none_for_unknown(world_db):
    db, _, _, _, _, case_id = world_db
    world = World(conn=db, active_case_id=case_id)
    assert world.find_location("nowhere special") is None
