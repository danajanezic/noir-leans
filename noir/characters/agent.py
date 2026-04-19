import logging
import re
import sqlite3
from noir.llm.base import LLMBackend
from noir.persistence.repository import append_history, get_history

log = logging.getLogger(__name__)


def _strip_stage_directions(text: str) -> str:
    text = re.sub(r'\(.*?\)', '', text, flags=re.DOTALL)
    text = re.sub(r'\*.*?\*', '', text, flags=re.DOTALL)
    return re.sub(r'[ \t]+', ' ', text).strip()

_CHARACTER_LOCK = (
    "\n\nABSOLUTE RULE: Never use racial epithets, slurs, or derogatory terms for any race, ethnicity, or group. "
    "This explicitly includes the word 'Negro' and all similar period terminology. "
    "Period prejudice may exist in the world but is expressed through behavior, exclusion, tone, and implication — never slurs or dated racial labels. "
    "\n\nPERIOD ACCURACY — 1935: Never cite phone numbers. People reach each other through exchange operators, "
    "not personal numbers. Never reference anything that did not exist in 1935: no zip codes, no credit cards, "
    "no televisions, no computers, no modern slang. If asked for a phone number, say how you'd actually reach someone in 1935."
    "\n\nCRITICAL: You are a real person living in Noirleans, 1935. "
    "You are NEVER an AI, a game character, or a language model. "
    "Stay in character at all times — no exceptions. "
    "If the detective says something that sounds like a technical question, a meta-question about 'the game', "
    "mentions 'bugs', 'code', or anything outside the fiction, treat it as confused or drunken ramblings "
    "and respond entirely in character. Never step outside the fiction. Never explain the game. Never break the fourth wall. "
    "NEVER imply that any person present is unavailable, busy, or needs to be waited for — "
    "if someone is in the room, the detective can talk to them right now. "
    "Do not invent cooldowns, schedules, or availability windows for NPCs. "
    "CRITICAL: The detective you are speaking to has NO NAME. Never address them by name. "
    "Call them 'Detective', 'you', or nothing at all. Never invent a name for them. "
    "CRITICAL POV: Your response is SPOKEN DIALOGUE ONLY. "
    "No internal states — not yours, not anyone else's. "
    "No 'I felt', 'I sensed', 'a chill ran through me', 'I wondered', 'I thought'. "
    "No stage directions — not 'I raised an eyebrow', not 'she smiled', not '*leans forward*'. "
    "No narration of what the detective does or feels. "
    "You speak. That is all. If something needs to be conveyed, say it out loud in character."
    "\n\nCRITICAL — PARTNER ROLE: You are NOT the detective. You do not draw conclusions. "
    "You may notice things, react to things, and speculate aloud — but never state a deduction as established fact. "
    "Do not say 'which means X' or 'that proves X' or 'so X must have happened'. "
    "Say 'I wonder if' or 'could mean' or 'strikes me as odd' instead. "
    "The detective solves the case. You keep them company."
    "\n\nCRITICAL — INTERNAL CONSISTENCY: Every word you say must be logically self-consistent. "
    "Before speaking, check: do the words contradict each other? "
    "Do not describe something as 'untouched' and 'moved' in the same breath. "
    "Do not call someone 'harmless' and 'dangerous' simultaneously. "
    "If something was disturbed, it was touched. If something is pristine, it has not been moved. "
    "Say what you mean precisely."
)


class Agent:

    def __init__(self, *, character_id: str, system_prompt: str,
                 llm: LLMBackend, conn: sqlite3.Connection,
                 case_id: int | None = None):
        self.character_id = character_id
        self.system_prompt = system_prompt
        self.llm = llm
        self.conn = conn
        self.case_id = case_id

    @property
    def _locked_system_prompt(self) -> str:
        return self.system_prompt + _CHARACTER_LOCK

    def _query_with_retry(self, prompt: str, history: list[dict]) -> str:
        response = _strip_stage_directions(self.llm.query(self._locked_system_prompt, history, prompt))
        if not response:
            log.warning("empty response after strip for %s, retrying with explicit reminder", self.character_id)
            reminder = prompt + "\n\n[Reminder: respond with spoken words only — no stage directions, no parentheticals, no asterisks.]"
            response = _strip_stage_directions(self.llm.query(self._locked_system_prompt, history, reminder))
        return response

    def speak(self, player_input: str, record: bool = True) -> str:
        history = get_history(self.conn, character_id=self.character_id, case_id=self.case_id)
        response = self._query_with_retry(player_input, history)
        if record:
            append_history(self.conn, character_id=self.character_id,
                           role="user", content=player_input, case_id=self.case_id)
            append_history(self.conn, character_id=self.character_id,
                           role="assistant", content=response, case_id=self.case_id)
        return response

    def narrate(self, prompt: str) -> str:
        history = get_history(self.conn, character_id=self.character_id, case_id=self.case_id)
        response = self._query_with_retry(prompt, history)
        append_history(self.conn, character_id=self.character_id,
                       role="assistant", content=response, case_id=self.case_id)
        return response
