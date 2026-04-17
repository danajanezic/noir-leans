import sqlite3
from noir.llm.base import LLMBackend
from noir.persistence.repository import save_partner

QUIZ_QUESTIONS = [
    {
        "question": "It's 3am. You're standing in the rain outside a warehouse you probably shouldn't be near. What are you drinking?",
        "options": [
            "A. Bourbon. The world owes me something.",
            "B. Coffee, black. I need my wits.",
            "C. Nothing. I don't get thirsty in crisis situations.",
            "D. Whatever was in the flask. I've stopped asking.",
        ]
    },
    {
        "question": "A witness tells you they saw nothing. Their left eye twitches. You:",
        "options": [
            "A. Push harder. Everyone saw something.",
            "B. Let it go. They'll talk when they're ready.",
            "C. Note it down and move on. Evidence, not intuition.",
            "D. Buy them a drink first.",
        ]
    },
    {
        "question": "Your office catches fire while you're in it. You grab:",
        "options": [
            "A. The case files. Obviously.",
            "B. Your hat. A detective without a hat is just a person.",
            "C. Nothing. I was leaving anyway.",
            "D. The bottle in the bottom drawer.",
        ]
    },
    {
        "question": "The city is corrupt from top to bottom. You think:",
        "options": [
            "A. Someone has to try.",
            "B. At least I know who to bribe.",
            "C. This is fine. This is just how things are.",
            "D. I'm going to need a bigger client list.",
        ]
    },
    {
        "question": "Describe your ideal Saturday morning.",
        "options": [
            "A. Sleeping through it.",
            "B. Already working a case. Time is a flat circle.",
            "C. Reading. Knowledge is the only real weapon.",
            "D. Pretending the week didn't happen.",
        ]
    },
    {
        "question": "Someone calls you a good detective. You:",
        "options": [
            "A. Say nothing. They're probably wrong.",
            "B. Say nothing. They're probably setting you up for something.",
            "C. Thank them, sincerely. Kindness matters.",
            "D. Ask what they want.",
        ]
    },
    {
        "question": "A case goes cold. You:",
        "options": [
            "A. Keep working it. Every case deserves an answer.",
            "B. Move on. The city has enough unsolved problems.",
            "C. Blame the system, because it's usually the system.",
            "D. Take a job that pays better for a while.",
        ]
    },
    {
        "question": "Your partner. What do you need from them?",
        "options": [
            "A. Honesty, even when it hurts.",
            "B. Competence. I'll handle the rest.",
            "C. Someone to talk to. This job is lonely.",
            "D. Someone who can drive. I am a liability behind the wheel.",
        ]
    },
]

QUIZ_SYSTEM_PROMPT = """You are a character generator for an absurdist noir detective game.
Based on a player's quiz answers, you create their detective partner — a character who is
over-the-top, deeply human, and funny in the vein of Hitchhiker's Guide to the Galaxy meets
hard-boiled noir. The partner serves as the player's Ford Prefect: guide, confidant, and
deadpan explainer of a deeply strange world.

Return ONLY valid JSON with these fields:
{
  "name": "string (a great noir name)",
  "sex": "male"|"female"|"nonbinary",
  "personality_archetype": "string (one of: world-weary cynic, manic optimist, detached alien observer, barely-contained chaos, philosophical pragmatist)",
  "speech_style": "string (e.g. terse and hard-boiled, verbose and tangential, relentlessly cheerful, philosophically distracted)",
  "relationship_stance": "string (e.g. exasperated, protective, competitive, devoted, professionally baffled)",
  "system_prompt": "string (3-4 sentences describing this character's voice, personality, and role as the player's partner and world guide. They should feel like Ford Prefect — confident about strange things, gently exasperated by the player, and completely at home in an absurd universe.)"
}"""


class Quiz:

    def __init__(self, *, conn: sqlite3.Connection, llm: LLMBackend):
        self.conn = conn
        self.llm = llm

    def run(self, *, answers: list[str]) -> dict:
        answers_text = "\n".join(
            f"Q{i+1}: {QUIZ_QUESTIONS[i]['question']}\nA: {answer}"
            for i, answer in enumerate(answers)
            if i < len(QUIZ_QUESTIONS)
        )
        prompt = (
            f"A player has answered the following quiz questions:\n\n{answers_text}\n\n"
            "Based on these answers, generate their detective partner. "
            "Return the JSON partner profile."
        )
        traits = self.llm.query_structured(QUIZ_SYSTEM_PROMPT, [], prompt)
        save_partner(
            self.conn,
            name=traits["name"],
            sex=traits["sex"],
            personality_archetype=traits["personality_archetype"],
            speech_style=traits["speech_style"],
            relationship_stance=traits["relationship_stance"],
            system_prompt=traits["system_prompt"],
        )
        return traits
