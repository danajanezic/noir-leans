from noir.characters.npc_archetype_loader import load_npc_archetypes, get_npc_archetype, archetype_ids


def test_load_npc_archetypes_count():
    archetypes = load_npc_archetypes()
    assert len(archetypes) == 45


def test_each_archetype_has_required_fields():
    for a in load_npc_archetypes():
        assert "id" in a
        assert "name" in a
        assert "personality" in a
        assert "speech_style" in a
        assert isinstance(a["personality"], str) and a["personality"]
        assert isinstance(a["speech_style"], str) and a["speech_style"]


def test_get_npc_archetype_by_id():
    a = get_npc_archetype("nervous_informant")
    assert a is not None
    assert a["id"] == "nervous_informant"


def test_get_npc_archetype_unknown_returns_none():
    assert get_npc_archetype("does_not_exist") is None


def test_archetype_ids_returns_all_unique():
    ids = archetype_ids()
    assert len(ids) == 45
    assert len(set(ids)) == len(ids)  # no duplicates
