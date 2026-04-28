import sqlite3
from noir.llm.base import LLMBackend
from noir.persistence.repository import (
    save_partner, update_player_alignment, get_player, initialize_player_skills,
)

QUIZ_QUESTIONS = [
    {
        "question": "A man drops his wallet. You pick it up. Inside: $40 cash, a photo of his kids, and a folded note that says \"Payment received. The judge will rule by Friday.\" You:",
        "options": [
            "A. Return it, cash and all. Not your business.",
            "B. Return the wallet, keep the cash. Consider it a fine.",
            "C. Keep everything and follow up on the note.",
            "D. Drop it in the nearest sewer. Let him wonder.",
        ]
    },
    {
        "question": "The judge in a case you're working is dirty. You know it. You can't prove it. You:",
        "options": [
            "A. Keep digging until you can prove it. Justice takes time.",
            "B. Work around him. Get the result through other channels.",
            "C. Blackmail him into ruling your way just this once.",
            "D. Accept it. Every system has rot. You're just one detective.",
        ]
    },
    {
        "question": "Noirleans has a law you think is unjust. You:",
        "options": [
            "A. Follow it. Laws exist for reasons, even bad ones.",
            "B. Break it quietly when necessary, without making it a statement.",
            "C. Break it loudly. Bad laws deserve public contempt.",
            "D. Use it when convenient, ignore it when not.",
        ]
    },
    {
        "question": "A client is lying to you. You know it. You:",
        "options": [
            "A. Confront them directly. You won't work a case blind.",
            "B. Keep working and figure out the real truth yourself.",
            "C. Bill them double and let them discover you know.",
            "D. Drop the case. Life's too short for people who waste your time.",
        ]
    },
    {
        "question": "You get evidence that would solve the case — but you got it illegally. You:",
        "options": [
            "A. Use it. Results matter more than procedure.",
            "B. Find a way to get it legally obtained. It takes longer but it's right.",
            "C. Use it if the guilty party deserves it. Don't use it if they don't.",
            "D. Sell it to the DA and let them figure out the paperwork.",
        ]
    },
    {
        "question": "Someone confesses to a crime you're not working. It's bad. You:",
        "options": [
            "A. Turn them in. That's the only correct answer.",
            "B. Hear them out first. Context matters before consequences.",
            "C. Tell them to leave town and not come back.",
            "D. File it away. Information is currency.",
        ]
    },
    {
        "question": "The killer you just caught will walk on a technicality. You:",
        "options": [
            "A. Let it happen. The process has to mean something.",
            "B. Plant corroborating evidence. They're guilty.",
            "C. Leak it to someone who'll handle it outside the courts.",
            "D. Beat yourself up about it and drink heavily.",
        ]
    },
    {
        "question": "Someone asks you to keep a secret that would hurt an innocent person if you keep it. You:",
        "options": [
            "A. Tell the truth. Secrets like that fester.",
            "B. Keep it. You made a promise.",
            "C. Use the information to quietly fix the situation without disclosure.",
            "D. Tell the person being hurt, not anyone else.",
        ]
    },
]

# (law_delta, good_delta) per question index, per answer key A/B/C/D
ALIGNMENT_WEIGHTS = [
    # Q1: corrupt man's wallet
    {"A": (2, -1), "B": (-1, 0), "C": (-1, 1), "D": (-2, 0)},
    # Q2: dirty judge
    {"A": (2, 2), "B": (-1, 1), "C": (-2, 0), "D": (0, -1)},
    # Q3: unjust law
    {"A": (2, -1), "B": (-1, 1), "C": (-2, 1), "D": (-1, -1)},
    # Q4: lying client
    {"A": (1, 1), "B": (0, 1), "C": (0, -1), "D": (1, 0)},
    # Q5: illegal evidence
    {"A": (-2, 1), "B": (2, 2), "C": (-1, 0), "D": (-1, -1)},
    # Q6: crime confession
    {"A": (2, 1), "B": (0, 1), "C": (-2, 0), "D": (-1, -2)},
    # Q7: killer walks on technicality
    {"A": (2, 0), "B": (-2, -1), "C": (-1, 0), "D": (0, 0)},
    # Q8: secret that hurts innocent
    {"A": (0, 2), "B": (2, -1), "C": (-1, 1), "D": (0, 1)},
]

VALID_ALIGNMENTS = {
    "Lawful Good", "Neutral Good", "Chaotic Good",
    "Lawful Neutral", "True Neutral", "Chaotic Neutral",
    "Lawful Evil", "Neutral Evil", "Chaotic Evil",
}


def score_alignment(answers: list[str]) -> tuple[int, int]:
    """Map quiz answers to (law_total, good_total). Each axis: -16 to +16."""
    law_total = 0
    good_total = 0
    for i, answer in enumerate(answers):
        key = answer.strip().upper()
        if i < len(ALIGNMENT_WEIGHTS) and key in ALIGNMENT_WEIGHTS[i]:
            law_delta, good_delta = ALIGNMENT_WEIGHTS[i][key]
            law_total += law_delta
            good_total += good_delta
    return law_total, good_total


def resolve_alignment(law: int, good: int) -> str:
    """Bucket (law, good) integer scores into one of nine named alignments."""
    if law >= 4:
        law_axis = "Lawful"
    elif law <= -4:
        law_axis = "Chaotic"
    else:
        law_axis = "Neutral"

    if good >= 4:
        good_axis = "Good"
    elif good <= -4:
        good_axis = "Evil"
    else:
        good_axis = "Neutral"

    if law_axis == "Neutral" and good_axis == "Neutral":
        return "True Neutral"
    if law_axis == "Neutral":
        return f"Neutral {good_axis}"
    if good_axis == "Neutral":
        return f"{law_axis} Neutral"
    return f"{law_axis} {good_axis}"


def alignment_disposition(player_alignment: str, npc_alignment: str) -> str:
    """Return 'aligned', 'opposed', or 'neutral' based on axis distance.

    Opposed: both axes differ by 2 steps (diagonally opposite).
    Aligned: both axes within 1 step of each other.
    Neutral: everything else.
    """
    _AXIS_ORDER = ["Chaotic", "Neutral", "Lawful"]
    _GOOD_ORDER = ["Evil", "Neutral", "Good"]

    def _parse(alignment: str):
        if alignment == "True Neutral":
            return (1, 1)  # Neutral/Neutral indices
        parts = alignment.split()
        if len(parts) == 2:
            law_part, good_part = parts
        else:
            return (1, 1)
        law_idx = _AXIS_ORDER.index(law_part) if law_part in _AXIS_ORDER else 1
        good_idx = _GOOD_ORDER.index(good_part) if good_part in _GOOD_ORDER else 1
        return (law_idx, good_idx)

    p_law, p_good = _parse(player_alignment)
    n_law, n_good = _parse(npc_alignment)

    law_dist = abs(p_law - n_law)
    good_dist = abs(p_good - n_good)

    if law_dist == 2 and good_dist == 2:
        return "opposed"
    if law_dist <= 1 and good_dist <= 1:
        return "aligned"
    return "neutral"


QUIZ_SYSTEM_PROMPT = """You are a character generator for an absurdist noir detective game set in Noirleans, 1935 — a city drowning in Depression-era desperation, jazz, and corruption.
Based on a player's quiz answers and their determined alignment, you create their detective partner — a character who is
over-the-top, deeply human, and funny in the vein of Hitchhiker's Guide to the Galaxy meets
hard-boiled noir. The partner serves as the player's Ford Prefect: guide, confidant, and
deadpan explainer of a deeply strange world.

The partner's alignment should complement the player's — opening doors the player cannot. A Chaotic Good player needs a partner who can vouch for them with lawful institutions. A Lawful Evil player needs a partner who can reach people who distrust authority. Pick the alignment that makes the partner most useful as a social key.

Return ONLY valid JSON with these fields:
{
  "name": "string (a great noir name)",
  "sex": "male"|"female"|"nonbinary",
  "personality_archetype": "string (one of: world-weary cynic, manic optimist, detached alien observer, barely-contained chaos, philosophical pragmatist)",
  "speech_style": "string (e.g. terse and hard-boiled, verbose and tangential, relentlessly cheerful, philosophically distracted)",
  "relationship_stance": "string (e.g. exasperated, protective, competitive, devoted, professionally baffled)",
  "alignment": "string (one of: Lawful Good, Neutral Good, Chaotic Good, Lawful Neutral, True Neutral, Chaotic Neutral, Lawful Evil, Neutral Evil, Chaotic Evil)",
  "system_prompt": "string (3-4 sentences describing this character's voice, personality, and role as the player's partner and world guide. They should feel like Ford Prefect — confident about strange things, gently exasperated by the player, and completely at home in an absurd universe.)"
}"""


class Quiz:

    def __init__(self, *, conn: sqlite3.Connection, llm: LLMBackend):
        self.conn = conn
        self.llm = llm

    @staticmethod
    def _resolve_option(q_idx: int, answer: str) -> str:
        if q_idx >= len(QUIZ_QUESTIONS):
            return answer
        options = QUIZ_QUESTIONS[q_idx]["options"]
        key = answer.strip().upper()
        for opt in options:
            if opt.startswith(key + ".") or opt.startswith(key + " "):
                return opt
        return answer

    def generate_replacement(self) -> dict:
        """Generate a new partner from existing player stats — no quiz required."""
        from noir.persistence.repository import get_player_skill_roots
        from noir.characters.skills import roots_for_alignment
        player = get_player(self.conn)
        player_alignment = resolve_alignment(
            player["law_chaos"] if player else 0,
            player["good_evil"] if player else 0,
        )
        race = (player["race"] if player else None) or "unspecified"
        gender = (player["gender"] if player else None) or "unspecified"
        cases_solved = player["cases_solved"] if player else 0
        reputation = player["reputation"] if player else 100

        prompt = (
            f"Player alignment: {player_alignment}. "
            f"Race: {race}. Gender: {gender}. "
            f"Cases solved: {cases_solved}. Reputation: {reputation}/100.\n\n"
            "The detective's previous partner is dead. Generate a new partner who fits where "
            "this detective is now — shaped by experience, not a fresh start. "
            "Return the JSON partner profile."
        )
        self.llm.status_message = "Someone new steps out of the dark..."
        traits = self.llm.query_structured(QUIZ_SYSTEM_PROMPT, [], prompt)
        self.llm.status_message = "Thinking..."
        save_partner(
            self.conn,
            name=traits["name"],
            sex=traits["sex"],
            personality_archetype=traits["personality_archetype"],
            speech_style=traits["speech_style"],
            relationship_stance=traits["relationship_stance"],
            system_prompt=traits["system_prompt"],
            alignment=traits.get("alignment", "True Neutral"),
        )
        player_roots = roots_for_alignment(
            law_chaos=player["law_chaos"] if player else 0,
            good_evil=player["good_evil"] if player else 0,
        )
        partner_roots = [r for r in ("authority", "streetwise", "empathy", "cunning")
                         if r not in player_roots]
        initialize_player_skills(self.conn, owner="partner", roots=partner_roots)
        return traits

    def run(self, *, answers: list[str]) -> dict:
        law_total, good_total = score_alignment(answers)
        player_alignment = resolve_alignment(law_total, good_total)
        self.conn.execute("UPDATE player SET law_chaos=0, good_evil=0 WHERE id=1")
        self.conn.commit()
        update_player_alignment(self.conn, law_delta=law_total, good_delta=good_total)

        answers_text = "\n".join(
            f"Q{i+1}: {QUIZ_QUESTIONS[i]['question']}\nAnswer: {self._resolve_option(i, answer)}"
            for i, answer in enumerate(answers)
            if i < len(QUIZ_QUESTIONS)
        )
        prompt = (
            f"Player alignment: {player_alignment}.\n\n"
            f"A player has answered the following quiz questions:\n\n{answers_text}\n\n"
            "Based on these answers and the player's alignment, generate their detective partner. "
            "Return the JSON partner profile."
        )
        self.llm.status_message = "Creating your perfect antagonist..."
        traits = self.llm.query_structured(QUIZ_SYSTEM_PROMPT, [], prompt)
        self.llm.status_message = "Thinking..."
        save_partner(
            self.conn,
            name=traits["name"],
            sex=traits["sex"],
            personality_archetype=traits["personality_archetype"],
            speech_style=traits["speech_style"],
            relationship_stance=traits["relationship_stance"],
            system_prompt=traits["system_prompt"],
            alignment=traits.get("alignment", "True Neutral"),
        )
        from noir.characters.skills import roots_for_alignment
        player = get_player(self.conn)
        player_roots = roots_for_alignment(
            law_chaos=player["law_chaos"], good_evil=player["good_evil"]
        )
        partner_roots = [r for r in ("authority", "streetwise", "empathy", "cunning")
                         if r not in player_roots]
        initialize_player_skills(self.conn, owner="player", roots=player_roots)
        initialize_player_skills(self.conn, owner="partner", roots=partner_roots)
        return traits
