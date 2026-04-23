import random
import sqlite3
import logging
from noir.llm.base import LLMBackend
from noir.persistence.repository import (
    award_xp, get_skill_events, save_specialization, get_skills,
)

log = logging.getLogger(__name__)

ROOTS = ("authority", "streetwise", "empathy", "cunning")

# (law_direction, good_direction) — positive means aligned with positive axis
_ROOT_ALIGNMENT = {
    "authority":  (1,  0),
    "streetwise": (-1, 0),
    "empathy":    (0,  1),
    "cunning":    (0, -1),
}

_SPECIALIZATION_SYSTEM = (
    "You are naming a skill specialization for a detective in a 1935 noir game. "
    "You will be given the detective's root skill, recent skill events (what they did to earn XP), "
    "and their alignment. "
    "Generate a specialization that reflects what this detective has actually learned to do. "
    "The name should be 2-4 words, evocative, specific to 1935 Noirleans. "
    "The description should be 1-2 sentences in the world's voice — what this means in practice. "
    "Return ONLY valid JSON: {\"name\": \"string\", \"description\": \"string\"}"
)


def roots_for_alignment(*, law_chaos: int, good_evil: int) -> list[str]:
    """Return the root skills a player starts with based on quiz alignment."""
    if law_chaos == 0 and good_evil == 0:
        return list(ROOTS)
    roots = []
    if law_chaos > 0:
        roots.append("authority")
    elif law_chaos < 0:
        roots.append("streetwise")
    if good_evil > 0:
        roots.append("empathy")
    elif good_evil < 0:
        roots.append("cunning")
    # True neutral on one axis gets both roots for that axis
    if law_chaos == 0:
        roots.extend(["authority", "streetwise"])
    if good_evil == 0:
        roots.extend(["empathy", "cunning"])
    return list(dict.fromkeys(roots))  # deduplicate, preserve order


def alignment_xp_multiplier(*, law_chaos: int, good_evil: int, root: str) -> float:
    """Multiplier for XP based on how aligned the player is with this root."""
    law_dir, good_dir = _ROOT_ALIGNMENT[root]
    alignment_strength = law_chaos * law_dir + good_evil * good_dir
    if alignment_strength >= 0:
        return 1.0 + min(alignment_strength / 20.0, 1.0)  # 1.0 -> 2.0
    return max(0.5, 1.0 + alignment_strength / 20.0)       # 0.5 -> 1.0


def check_skill_attempt(*, skill_level: int, difficulty: int) -> str:
    """
    Returns 'success', 'backfire', or 'lucky' based on skill vs difficulty.
    difficulty: 1 (easy) to 5 (hard).
    """
    gap = skill_level - difficulty
    success_p = max(0.10, min(0.88, 0.60 + gap * 0.14))
    lucky_p = 0.05
    backfire_p = 1.0 - success_p - lucky_p
    r = random.random()
    if r < success_p:
        return "success"
    if r < success_p + backfire_p:
        return "backfire"
    return "lucky"


def apply_conversation_xp(conn: sqlite3.Connection, *, owner: str,
                           xp_awards: dict[str, int], law_chaos: int,
                           good_evil: int, case_id: int | None) -> dict[str, tuple[int, int]]:
    """
    Apply XP awards from a conversation summary, weighted by alignment.
    Returns {root: (old_level, new_level)} for roots that had nonzero awards.
    """
    level_changes = {}
    for root, base_xp in xp_awards.items():
        if not base_xp or root not in ROOTS:
            continue
        mult = alignment_xp_multiplier(law_chaos=law_chaos, good_evil=good_evil, root=root)
        final_xp = max(1, round(base_xp * mult))
        old_level, new_level = award_xp(conn, owner=owner, root=root,
                                         xp=final_xp, reason="conversation",
                                         case_id=case_id)
        level_changes[root] = (old_level, new_level)
    return level_changes


def maybe_generate_specialization(llm: LLMBackend, conn: sqlite3.Connection, *,
                                   owner: str, root: str,
                                   law_chaos: int, good_evil: int) -> dict | None:
    """
    If the root's current level is a multiple of 3, generate and save a new specialization.
    Returns the specialization dict if one was generated, else None.
    """
    skills = get_skills(conn, owner=owner)
    level = skills.get(root, {}).get("level", 0)
    if level == 0 or level % 3 != 0:
        return None
    events = get_skill_events(conn, owner=owner, root=root, limit=15)
    if not events:
        return None
    alignment_label = _alignment_label(law_chaos, good_evil)
    event_summary = "; ".join(
        e["reason"] for e in events if e.get("reason")
    )[:400]
    prompt = (
        f"Root skill: {root}. Level reached: {level}. "
        f"Detective alignment: {alignment_label}. "
        f"Recent actions that built this skill: {event_summary}."
    )
    result = llm.query_structured(_SPECIALIZATION_SYSTEM, [], prompt)
    name = result.get("name", "").strip()
    description = result.get("description", "").strip()
    if not name or not description:
        return None
    save_specialization(conn, owner=owner, root=root, name=name,
                         description=description, unlocked_at_level=level)
    return {"name": name, "description": description, "root": root, "level": level}


def _alignment_label(law_chaos: int, good_evil: int) -> str:
    lc = "Lawful" if law_chaos > 3 else "Chaotic" if law_chaos < -3 else "Neutral"
    ge = "Good" if good_evil > 3 else "Evil" if good_evil < -3 else "Neutral"
    return f"{lc} {ge}"
