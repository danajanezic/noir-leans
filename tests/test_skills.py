import sqlite3
import json
import pytest
from noir.persistence.db import create_schema
from noir.persistence.repository import (
    initialize_player_skills, get_skills, award_xp, log_skill_event
)
from noir.characters.skills import (
    alignment_xp_multiplier,
    check_skill_attempt,
    roots_for_alignment,
    apply_conversation_xp,
    maybe_generate_specialization,
)
from noir.llm.mock import MockLLMBackend


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    yield conn
    conn.close()


def test_roots_for_alignment_lawful_good():
    roots = roots_for_alignment(law_chaos=10, good_evil=10)
    assert "authority" in roots
    assert "empathy" in roots


def test_roots_for_alignment_chaotic_evil():
    roots = roots_for_alignment(law_chaos=-10, good_evil=-10)
    assert "streetwise" in roots
    assert "cunning" in roots


def test_roots_for_true_neutral():
    roots = roots_for_alignment(law_chaos=0, good_evil=0)
    assert set(roots) == {"authority", "streetwise", "empathy", "cunning"}


def test_alignment_xp_multiplier_aligned():
    # Lawful player using Authority (lawful root) — should get bonus
    mult = alignment_xp_multiplier(law_chaos=15, good_evil=0, root="authority")
    assert mult > 1.0


def test_alignment_xp_multiplier_opposed():
    # Lawful player using Streetwise (chaotic root) — should get penalty
    mult = alignment_xp_multiplier(law_chaos=15, good_evil=0, root="streetwise")
    assert mult < 1.0


def test_alignment_xp_multiplier_neutral():
    # Neutral player — should be near 1.0 for any root
    mult = alignment_xp_multiplier(law_chaos=0, good_evil=0, root="authority")
    assert abs(mult - 1.0) < 0.05


def test_check_skill_attempt_returns_valid_outcome():
    for _ in range(50):
        outcome = check_skill_attempt(skill_level=1, difficulty=1)
        assert outcome in ("success", "backfire", "lucky")


def test_check_skill_attempt_skilled_mostly_succeeds():
    results = [check_skill_attempt(skill_level=5, difficulty=1) for _ in range(200)]
    success_rate = results.count("success") / 200
    assert success_rate > 0.75


def test_check_skill_attempt_unskilled_can_still_succeed():
    results = [check_skill_attempt(skill_level=1, difficulty=5) for _ in range(200)]
    assert "success" in results  # nonzero success rate
    assert "lucky" in results


def test_apply_conversation_xp(db):
    initialize_player_skills(db, owner="player", roots=["authority", "empathy"])
    xp_awards = {"authority": 8, "empathy": 5, "streetwise": 0, "cunning": 0}
    apply_conversation_xp(db, owner="player", xp_awards=xp_awards,
                          law_chaos=10, good_evil=10, case_id=None)
    skills = get_skills(db, owner="player")
    assert skills["authority"]["xp"] > 0
    assert skills["empathy"]["xp"] > 0


def test_maybe_generate_specialization_at_divisible_level(db, mock_llm):
    """Test that specialization is generated at levels divisible by 3."""
    initialize_player_skills(db, owner="player", roots=["authority"])

    # Award XP to reach level 3 (divisible by 3)
    # Level is calculated as 1 + xp // 100, so to get level 3 we need xp >= 200
    award_xp(db, owner="player", root="authority", xp=200, reason="test_event_1")
    log_skill_event(db, owner="player", root="authority", xp=100, reason="defeated suspect")
    log_skill_event(db, owner="player", root="authority", xp=100, reason="interrogated witness")

    # Verify we're at level 3
    skills = get_skills(db, owner="player")
    assert skills["authority"]["level"] == 3

    # Mock the LLM to return a specialization
    mock_llm._responses = iter([json.dumps({
        "name": "Iron Stare",
        "description": "Makes suspects nervous."
    })])

    result = maybe_generate_specialization(
        mock_llm, db,
        owner="player", root="authority",
        law_chaos=10, good_evil=10
    )

    assert result is not None
    assert result["name"] == "Iron Stare"
    assert result["description"] == "Makes suspects nervous."
    assert result["root"] == "authority"
    assert result["level"] == 3


def test_maybe_generate_specialization_at_non_divisible_level(db, mock_llm):
    """Test that specialization is NOT generated at levels not divisible by 3."""
    initialize_player_skills(db, owner="player", roots=["authority"])

    # Award XP to reach level 2 (not divisible by 3)
    award_xp(db, owner="player", root="authority", xp=100, reason="test_event")

    # Verify we're at level 2
    skills = get_skills(db, owner="player")
    assert skills["authority"]["level"] == 2

    result = maybe_generate_specialization(
        mock_llm, db,
        owner="player", root="authority",
        law_chaos=10, good_evil=10
    )

    assert result is None


def test_maybe_generate_specialization_at_level_6(db, mock_llm):
    """Test specialization at another divisible-by-3 level (level 6)."""
    initialize_player_skills(db, owner="player", roots=["cunning"])

    # Award XP to reach level 6 (need xp >= 500)
    award_xp(db, owner="player", root="cunning", xp=500, reason="backstabbed rival")

    skills = get_skills(db, owner="player")
    assert skills["cunning"]["level"] == 6

    # Mock the LLM to return a specialization
    mock_llm._responses = iter([json.dumps({
        "name": "Silent Knife",
        "description": "Strike without warning or trace."
    })])

    result = maybe_generate_specialization(
        mock_llm, db,
        owner="player", root="cunning",
        law_chaos=-10, good_evil=-10
    )

    assert result is not None
    assert result["name"] == "Silent Knife"
    assert result["description"] == "Strike without warning or trace."
    assert result["root"] == "cunning"
    assert result["level"] == 6
