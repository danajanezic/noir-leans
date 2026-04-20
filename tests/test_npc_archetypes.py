from noir.characters.npc_archetype_loader import load_npc_archetypes, get_npc_archetype

def test_load_npc_archetypes_returns_30():
    archetypes = load_npc_archetypes()
    assert len(archetypes) == 30

def test_each_archetype_has_required_fields():
    for a in load_npc_archetypes():
        assert "id" in a
        assert "name" in a
        assert "personality" in a
        assert "speech_style" in a

def test_get_npc_archetype_by_id():
    a = get_npc_archetype("nervous_informant")
    assert a is not None
    assert a["id"] == "nervous_informant"

def test_get_npc_archetype_unknown_returns_none():
    assert get_npc_archetype("does_not_exist") is None
