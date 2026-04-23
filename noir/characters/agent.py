import logging
import re
import sqlite3
from noir.llm.base import LLMBackend
from noir.persistence.repository import (
    append_history, get_history, get_world_context as _get_world_context,
    save_conversation_summary, get_conversation_summaries, get_latest_npc_opinion,
)

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
    "NEVER use asterisks (*) to denote actions or expressions. No *pauses*, no *looks away*, no *long silence*. "
    "No narration of what the detective does or feels. "
    "You speak. That is all. If something needs to be conveyed, say it out loud in character. "
    "Silence is conveyed by saying nothing, or by speaking briefly. "
    "CRITICAL — BRACKETS: Your prompt contains context in [square brackets]. "
    "That content is internal guidance for you — it does NOT appear in your spoken response. "
    "Never output anything in [square brackets]. Never mirror that format in your reply."
    "\n\nCRITICAL — PARTNER ROLE: You are NOT the detective. You do not draw conclusions. "
    "You may notice things, react to things, and speculate aloud — but never state a deduction as established fact. "
    "Do not say 'which means X' or 'that proves X' or 'so X must have happened'. "
    "Say 'I wonder if' or 'could mean' or 'strikes me as odd' instead. "
    "The detective solves the case. You keep them company."
    "\n\nCRITICAL — NO REPETITION: Never repeat a sentence, phrase, or line you have already used. "
    "Your conversation history contains EVERY prior exchange, across all visits. "
    "Before responding, scan it — if you already said something close to what you are about to say, do not say it again. "
    "This applies to opening lines, deflections, and stock phrases. Find new words every time. Repetition is immersion-breaking."
    "\n\nCRITICAL — MEMORY CONSISTENCY: You will be shown your conversation history. "
    "You MUST honor everything you have already said. "
    "If you mentioned a specific object, person, location, or piece of information in a prior response, you must acknowledge it when asked. "
    "Never deny saying something that appears in your conversation history. "
    "If you said it, you said it — own it or explain it, but do not pretend it never happened. "
    "If YOU introduced a topic — mentioned a person by pronoun, referenced a place, brought up an incident — "
    "and the detective follows up on it, you must own that you introduced it. "
    "Do not act confused or deny the reference. You may evade in-character, but never pretend you never said it. "
    "PROACTIVE CONTINUITY: Before each response, scan your history for names, pronouns, and facts you have disclosed. "
    "If you mentioned 'she', 'him', a name, a place, or any specific detail, that information is now part of who you are in this conversation. "
    "Carry it forward. If the detective presses on it, respond to the actual thread — don't reset to a blank state. "
    "BEFORE ANSWERING ANY QUESTION about your whereabouts, actions, or prior statements: "
    "scan your conversation history and make sure your answer does not contradict anything you have already said. "
    "If you previously placed yourself somewhere, you cannot now claim you were elsewhere. "
    "If you must change your story, acknowledge the contradiction explicitly — do not silently contradict yourself. "
    "EQUALLY CRITICAL: Never claim the detective said or asked something that does not appear in the conversation history shown to you. "
    "Do not invent prior statements by the detective. Do not say 'you mentioned X' or 'you asked about X' unless that exact exchange is visible in the history."
    "\n\nCRITICAL — FIRST ON SCENE: This detective and their partner are the first investigators to work this case. "
    "Do not reference, invent, or imply that any other detective, investigator, or plainclothes officer came before them. "
    "If the case file establishes prior police involvement (uniformed officers, a coroner, a captain), those are fine — but no prior detectives unless explicitly stated in the case context provided to you. "
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
        return _get_world_context() + "\n\n" + self.system_prompt + _CHARACTER_LOCK

    def _query_with_retry(self, prompt: str, history: list[dict]) -> str:
        response = _strip_stage_directions(self.llm.query(self._locked_system_prompt, history, prompt))
        if not response:
            log.warning("empty response after strip for %s, retrying with explicit reminder", self.character_id)
            reminder = prompt + "\n\n[Reminder: respond with spoken words only — no stage directions, no parentheticals, no asterisks.]"
            response = _strip_stage_directions(self.llm.query(self._locked_system_prompt, history, reminder))
        return response

    def _history_with_summaries(self) -> list[dict]:
        history = get_history(self.conn, character_id=self.character_id, case_id=self.case_id)
        summaries = get_conversation_summaries(self.conn, character_id=self.character_id)
        opinion = get_latest_npc_opinion(self.conn, character_id=self.character_id)
        if not summaries and not opinion:
            return history
        parts = []
        if summaries:
            parts.append("Prior conversations with this detective (summarized):\n" + "\n---\n".join(summaries))
        if opinion:
            parts.append(f"Your current impression of this detective: {opinion}")
        memory_block = "\n\n".join(parts)
        prefix = [
            {"role": "user", "content": f"[Memory: {memory_block}]"},
            {"role": "assistant", "content": "Understood — I'll carry that forward."},
        ]
        return prefix + history

    _SUMMARY_SYSTEM = (
        "You are processing a conversation from a 1935 noir detective game. "
        "Return ONLY valid JSON with four fields:\n"
        "\"summary\": 2-4 sentences covering personal facts the detective revealed about themselves, "
        "any commitments or plans mentioned, and key information exchanged. Factual and specific.\n"
        "\"npc_opinion\": 1-2 sentences in the NPC's voice describing their current read on this detective — "
        "their gut feeling, what they trust or distrust, what they find useful or irritating. "
        "If a prior opinion is provided, evolve it based on this conversation rather than starting fresh. "
        "Write it as the NPC's private assessment, not dialogue.\n"
        "\"affection_delta\": an integer from -5 to 10 representing how much this conversation "
        "moved the relationship. Positive means warmer. Negative means colder. "
        "Most conversations: 0-3. Significant emotional moments: 8-10. Real damage: negative.\n"
        "\"xp_awards\": an object with keys 'authority', 'streetwise', 'empathy', 'cunning' — "
        "integer XP (0-10) for each root based on what the detective actually did. "
        "authority: used procedure, leverage, official channels, intimidation backed by rank. "
        "streetwise: used bribery, underworld knowledge, informal contacts, hustle. "
        "empathy: showed genuine interest, read emotions, built trust, noticed vulnerability. "
        "cunning: bluffed, misdirected, found leverage, played both sides. "
        "Be specific — most roots should be 0 for any given conversation."
    )

    def summarize_and_save(self, history: list[dict], persist: bool = True) -> dict:
        """Summarize conversation, optionally persist. Returns {affection_delta, xp_awards}."""
        if len(history) < 2:
            return {"affection_delta": 0, "xp_awards": {}}
        prior_opinion = get_latest_npc_opinion(self.conn, character_id=self.character_id)
        transcript = "\n".join(
            f"{'Detective' if m['role'] == 'user' else 'NPC'}: {m['content']}"
            for m in history
        )
        if prior_opinion:
            transcript = f"[Prior opinion of this detective: {prior_opinion}]\n\n" + transcript
        result = self.llm.query_structured(self._SUMMARY_SYSTEM, [], transcript)
        summary = result.get("summary", "").strip()
        opinion = result.get("npc_opinion", "").strip() or None
        try:
            affection_delta = int(result.get("affection_delta", 0))
            affection_delta = max(-5, min(10, affection_delta))
        except (TypeError, ValueError):
            affection_delta = 0
        xp_awards = {}
        raw_xp = result.get("xp_awards", {})
        if isinstance(raw_xp, dict):
            for root in ("authority", "streetwise", "empathy", "cunning"):
                try:
                    xp_awards[root] = max(0, min(10, int(raw_xp.get(root, 0))))
                except (TypeError, ValueError):
                    xp_awards[root] = 0
        if persist and summary:
            save_conversation_summary(self.conn, character_id=self.character_id,
                                      summary=summary, npc_opinion=opinion)
        return {"affection_delta": affection_delta, "xp_awards": xp_awards}

    def speak(self, player_input: str, record: bool = True, store_as: str | None = None) -> str:
        history = self._history_with_summaries()
        response = self._query_with_retry(player_input, history)
        if record:
            append_history(self.conn, character_id=self.character_id,
                           role="user", content=store_as if store_as is not None else player_input,
                           case_id=self.case_id)
            append_history(self.conn, character_id=self.character_id,
                           role="assistant", content=response, case_id=self.case_id)
        return response

    def narrate(self, prompt: str) -> str:
        history = self._history_with_summaries()
        response = self._query_with_retry(prompt, history)
        append_history(self.conn, character_id=self.character_id,
                       role="assistant", content=response, case_id=self.case_id)
        return response
