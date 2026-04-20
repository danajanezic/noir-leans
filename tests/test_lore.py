from noir.lore import lore_memories_for_age, is_history_query


def test_age_60_remembers_all_7_events():
    # born 1875 — all events have age_during >= 12
    case_hooks, background = lore_memories_for_age(60)
    assert len(case_hooks) == 3   # short_assassination, longshoremen_strike, red_light_closure
    assert len(background) == 4   # prohibition_end, the_crash, short_rise, great_migration_acceleration


def test_age_25_excludes_red_light_closure():
    # born 1910 — red_light_closure 1917: age_during = 7 < 12
    case_hooks, background = lore_memories_for_age(25)
    combined = case_hooks + background
    assert not any("1917" in m for m in combined)


def test_age_25_remembers_6_events():
    # born 1910 — remembers crash, short_rise, longshoremen_strike, prohibition_end, short_assassination, great_migration_acceleration (6 total)
    case_hooks, background = lore_memories_for_age(25)
    assert len(case_hooks) == 2   # short_assassination, longshoremen_strike
    assert len(background) == 4   # the_crash, short_rise, prohibition_end, great_migration_acceleration


def test_age_10_remembers_nothing():
    # born 1925 — short_assassination 1935: age_during = 10 < 12
    case_hooks, background = lore_memories_for_age(10)
    assert case_hooks == []
    assert background == []


def test_memory_format_contains_year_and_summary():
    case_hooks, _ = lore_memories_for_age(60)
    for m in case_hooks:
        assert " — " in m
        year_str = m.split(" — ")[0]
        assert year_str.isdigit()


def test_is_history_query_matches_prohibition():
    assert is_history_query("Do you remember prohibition?")


def test_is_history_query_matches_strike():
    assert is_history_query("What happened during the strike?")


def test_is_history_query_matches_crash():
    assert is_history_query("Were you around for the crash?")


def test_is_history_query_no_match_on_simple_question():
    assert not is_history_query("Where were you last Tuesday?")


def test_is_history_query_case_insensitive():
    assert is_history_query("REMEMBER the crash?")


def test_is_history_query_no_false_positive_warning():
    assert not is_history_query("Just a warning about that door.")


def test_is_history_query_no_false_positive_short():
    assert not is_history_query("It was a short walk to the docks.")
