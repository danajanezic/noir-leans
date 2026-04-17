import json
from noir.onboarding.quiz import Quiz
from noir.onboarding.cold_open import ColdOpen
from noir.persistence.repository import create_player, get_partner, get_history
from noir.llm.mock import MockLLMBackend

PARTNER_TRAITS = json.dumps({
    "name": "Vera",
    "sex": "female",
    "personality_archetype": "world-weary cynic",
    "speech_style": "terse and hard-boiled",
    "relationship_stance": "exasperated",
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


def test_cold_open_generates_bar_incident(db):
    create_player(db)
    llm = MockLLMBackend(responses=[BAR_INCIDENT])
    cold_open = ColdOpen(conn=db, llm=llm)
    incident = cold_open.generate_bar_incident()
    assert "badger" in incident.lower() or len(incident) > 20


def test_quiz_questions_are_defined():
    from noir.onboarding.quiz import QUIZ_QUESTIONS
    assert len(QUIZ_QUESTIONS) >= 6
    for q in QUIZ_QUESTIONS:
        assert "question" in q
        assert "options" in q
        assert len(q["options"]) >= 2
