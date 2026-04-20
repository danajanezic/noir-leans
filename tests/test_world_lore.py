import json
from pathlib import Path

LORE_PATH = Path(__file__).parent.parent / "noir" / "data" / "world_lore.json"

FAULT_LINES = {
    "race", "machine_politics", "labor_capital",
    "old_vs_new_money", "church_vs_vice", "federal_intrusion", "assassination_backlash"
}


def _load():
    return json.loads(LORE_PATH.read_text())


def test_lore_file_exists():
    assert LORE_PATH.exists()


def test_lore_has_required_top_level_arrays():
    lore = _load()
    assert "figures" in lore
    assert "factions" in lore
    assert "events" in lore
    assert isinstance(lore["figures"], list)
    assert isinstance(lore["factions"], list)
    assert isinstance(lore["events"], list)


def test_figures_have_required_fields():
    figures = _load()["figures"]
    assert len(figures) > 0
    for f in figures:
        assert "id" in f
        assert "noirleans_name" in f
        assert "role" in f
        assert "status" in f
        assert "summary" in f
        assert "fault_lines" in f
        for fl in f["fault_lines"]:
            assert fl in FAULT_LINES, f"Unknown fault_line '{fl}' in figure '{f['id']}'"


def test_factions_have_required_fields():
    factions = _load()["factions"]
    assert len(factions) > 0
    for f in factions:
        assert "id" in f
        assert "name" in f
        assert "summary" in f
        assert "fault_lines" in f
        for fl in f["fault_lines"]:
            assert fl in FAULT_LINES, f"Unknown fault_line '{fl}' in faction '{f['id']}'"


def test_events_have_required_fields():
    events = _load()["events"]
    assert len(events) > 0
    for e in events:
        assert "id" in e
        assert "start" in e
        assert "month" in e["start"]
        assert "year" in e["start"]
        assert "summary" in e
        assert "fault_lines" in e
        assert "case_hook" in e
        assert isinstance(e["case_hook"], bool)
        for fl in e["fault_lines"]:
            assert fl in FAULT_LINES, f"Unknown fault_line '{fl}' in event '{e['id']}'"


def test_howie_short_figure_exists():
    figures = _load()["figures"]
    ids = {f["id"] for f in figures}
    assert "howie_short" in ids


def test_assassination_event_exists():
    events = _load()["events"]
    ids = {e["id"] for e in events}
    assert "short_assassination" in ids


def test_shortites_faction_exists():
    factions = _load()["factions"]
    ids = {f["id"] for f in factions}
    assert "shortites" in ids
