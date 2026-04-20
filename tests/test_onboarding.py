import json
from noir.onboarding.quiz import Quiz, QUIZ_QUESTIONS, score_alignment, resolve_alignment, alignment_disposition
from noir.onboarding.cold_open import ColdOpen
from noir.persistence.repository import create_player, get_player, get_partner
from noir.llm.mock import MockLLMBackend

PARTNER_TRAITS = json.dumps({
    "name": "Vera",
    "sex": "female",
    "personality_archetype": "world-weary cynic",
    "speech_style": "terse and hard-boiled",
    "relationship_stance": "exasperated",
    "alignment": "Lawful Good",
    "system_prompt": "You are Vera, a world-weary detective's partner who finds everything mildly absurd."
})

BAR_INCIDENT = json.dumps({
    "incident": "You attempted to conduct an interrogation of a taxidermied badger. The badger, to everyone's surprise, had a better alibi than most of the actual suspects."
})


def test_quiz_saves_partner_to_db(db):
    create_player(db)
    llm = MockLLMBackend(responses=[PARTNER_TRAITS])
    quiz = Quiz(conn=db, llm=llm)
    answers = [
        "bourbon — the world definitely owes me something",
        "I'd try to reason with the fire",
        "instinct over evidence",
        "I'd rather work alone but won't admit it",
        "already working a case",
        "say nothing, they're probably wrong",
        "keep working it",
        "someone to talk to",
    ]
    quiz.run(answers=answers)
    partner = get_partner(db)
    assert partner is not None
    assert partner["name"] == "Vera"
    assert partner["sex"] == "female"


def test_quiz_prompt_includes_answers(db):
    create_player(db)
    llm = MockLLMBackend(responses=[PARTNER_TRAITS])
    quiz = Quiz(conn=db, llm=llm)
    answers = ["answer one", "answer two"]
    quiz.run(answers=answers)
    last_call = llm.calls[-1]
    assert "answer one" in last_call["user_input"]


def test_cold_open_generates_bar_incident():
    llm = MockLLMBackend(responses=[BAR_INCIDENT])
    cold_open = ColdOpen(llm=llm)
    incident = cold_open.generate_bar_incident()
    assert "badger" in incident.lower()


def test_quiz_questions_are_defined():
    assert len(QUIZ_QUESTIONS) >= 6
    for q in QUIZ_QUESTIONS:
        assert "question" in q
        assert "options" in q
        assert len(q["options"]) >= 2


def test_score_alignment_sums_weights():
    # Q1-A: law+2, good-1; Q2-A: law+2, good+2; Q3-D: law-1, good-1; Q4-D: law+1, good0;
    # Q5-D: law-1, good-1; Q6-D: law-1, good-2; Q7-D: law0, good0; Q8-D: law0, good+1
    answers = ["A", "A", "D", "D", "D", "D", "D", "D"]
    law, good = score_alignment(answers)
    assert law == 2
    assert good == -2

def test_resolve_alignment_lawful_good():
    assert resolve_alignment(4, 4) == "Lawful Good"

def test_resolve_alignment_true_neutral():
    assert resolve_alignment(0, 0) == "True Neutral"

def test_resolve_alignment_chaotic_evil():
    assert resolve_alignment(-4, -4) == "Chaotic Evil"

def test_resolve_alignment_lawful_neutral():
    assert resolve_alignment(5, 2) == "Lawful Neutral"

def test_resolve_alignment_neutral_good():
    assert resolve_alignment(0, 6) == "Neutral Good"

def test_resolve_alignment_chaotic_neutral():
    assert resolve_alignment(-5, 0) == "Chaotic Neutral"

def test_resolve_alignment_lawful_evil():
    assert resolve_alignment(6, -5) == "Lawful Evil"

def test_resolve_alignment_neutral_evil():
    assert resolve_alignment(1, -6) == "Neutral Evil"

def test_resolve_alignment_chaotic_good():
    assert resolve_alignment(-5, 5) == "Chaotic Good"


def test_quiz_stores_player_alignment(db):
    create_player(db)
    llm = MockLLMBackend(responses=[PARTNER_TRAITS])
    quiz = Quiz(conn=db, llm=llm)
    answers = ["A", "D", "D", "D", "D", "D", "D", "D"]
    quiz.run(answers=answers)
    player = get_player(db)
    law, good = score_alignment(answers)
    assert player["law_chaos"] == law
    assert player["good_evil"] == good


def test_quiz_partner_alignment_stored(db):
    create_player(db)
    llm = MockLLMBackend(responses=[PARTNER_TRAITS])
    quiz = Quiz(conn=db, llm=llm)
    answers = ["A", "A", "A", "A", "A", "A", "A", "A"]
    quiz.run(answers=answers)
    partner = get_partner(db)
    assert partner["alignment"] == "Lawful Good"


def test_quiz_prompt_includes_player_alignment(db):
    create_player(db)
    llm = MockLLMBackend(responses=[PARTNER_TRAITS])
    quiz = Quiz(conn=db, llm=llm)
    answers = ["A", "A", "A", "A", "A", "A", "A", "A"]
    quiz.run(answers=answers)
    last_call = llm.calls[-1]
    assert "alignment" in last_call["user_input"].lower()


def test_alignment_disposition_opposed():
    assert alignment_disposition("Lawful Good", "Chaotic Evil") == "opposed"
    assert alignment_disposition("Chaotic Evil", "Lawful Good") == "opposed"


def test_alignment_disposition_aligned():
    assert alignment_disposition("Lawful Good", "Neutral Good") == "aligned"
    assert alignment_disposition("Lawful Good", "Lawful Neutral") == "aligned"
    assert alignment_disposition("True Neutral", "True Neutral") == "aligned"


def test_alignment_disposition_neutral():
    assert alignment_disposition("Lawful Good", "Chaotic Neutral") == "neutral"
    assert alignment_disposition("Lawful Neutral", "Chaotic Neutral") == "neutral"
