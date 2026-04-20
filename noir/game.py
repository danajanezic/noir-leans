import copy
import json
import sqlite3
import random
import threading

from noir.log import save_feedback
from rich.panel import Panel
from noir.display import (
    show_location, show_dialogue, show_player_input_prompt, show_evidence_collected,
    show_arrest_confirmation, show_reputation, show_trial_status,
    show_help, show_locations, show_leads, show_suspects, show_player_status,
    show_travel_animation, travel_status, show_splash, typewrite, show_narrator,
    show_conversation_header, show_conversation_footer, show_evidence,
    show_relationships, show_dossier, show_dossier_all, show_cases,
    show_wait_result, fmt_game_time, console
)
from noir.parser import parse_command, Intent
from noir.llm.base import LLMBackend
from noir.persistence.repository import (
    create_player, get_player, get_partner, create_location,
    get_location, get_active_cases, get_all_cases, set_case_active, get_case, get_fixed_locations,
    create_case, create_npc, set_character_location, get_npcs_for_case,
    get_locations_for_case, get_evidence_for_case,
    add_player_suspect, get_player_suspects, remove_player_suspect,
    get_character_location,
    get_player_states, add_player_state, remove_player_state, clear_transient_states,
    add_dossier_facts, get_dossier, get_all_dossier,
    update_player_identity,
    get_npc_affection, get_npc_relationship_flags, increment_npc_affection,
    set_npc_clue_volunteered, set_npc_secret_revealed,
    get_partner_affection, increment_partner_affection,
    get_partner_dark_past_state, set_partner_dark_past_state,
    set_partner_dark_past,
    remove_partner,
    get_game_time, advance_game_time,
    create_npc_schedule, get_npc_location_at_time,
    create_npc_appointment, get_active_appointment, fulfill_past_appointments,
    create_suspect, mark_suspect_met, get_met_suspects_for_case,
    link_evidence_to_suspect,
    seed_locations_to_db, get_seeded_location_names,
)
from noir.persistence.db import create_schema
from noir.characters.companion import Companion
from noir.characters.npc import NPC
from noir.mystery.generator import MysteryGenerator
from noir.mystery.archetype_loader import seed_archetypes_to_db
from noir.cases.manager import CaseManager
from noir.cases.trial import TrialSystem
from noir.onboarding.quiz import Quiz, QUIZ_QUESTIONS
from noir.onboarding.cold_open import ColdOpen
from noir.world import World


_APPOINTMENT_SYSTEM = (
    "You detect meeting commitments in NPC dialogue. "
    "Return ONLY valid JSON: "
    '{"committed": true|false, "location": "string or null", "time": "HH:MM in 24h format or null"}'
)

_WAIT_KEYWORDS = {
    "midnight": 0, "noon": 720, "morning": 480, "afternoon": 780,
    "evening": 1080, "night": 1320, "dawn": 360, "dusk": 1080,
}


def _parse_hhmm(s: str) -> int:
    """Convert 'HH:MM' string to minutes since midnight."""
    try:
        h, m = s.strip().split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return 0


def _tod_to_absolute(current_game_time: int, tod_minutes: int) -> int:
    """Convert a time-of-day (0-1439) to an absolute future game_time."""
    current_tod = current_game_time % 1440
    day_base = (current_game_time // 1440) * 1440
    if tod_minutes > current_tod:
        return day_base + tod_minutes
    return day_base + 1440 + tod_minutes


def _parse_wait_delta(args: str, current_game_time: int) -> int:
    """Return minutes to advance from a /wait argument string."""
    args = args.lower().strip()
    if not args:
        return 60
    # "until <keyword>"
    if args.startswith("until "):
        keyword = args[6:].strip()
        if keyword in _WAIT_KEYWORDS:
            target_tod = _WAIT_KEYWORDS[keyword]
            abs_time = _tod_to_absolute(current_game_time, target_tod)
            return abs_time - current_game_time
    # "<N> hours" / "<N>h"
    import re
    m = re.match(r"(\d+)\s*(h\b|hours?)", args)
    if m:
        return int(m.group(1)) * 60
    m = re.match(r"(\d+)\s*(m\b|min(?:utes?)?)", args)
    if m:
        return int(m.group(1))
    # bare number → hours
    m = re.match(r"(\d+)$", args)
    if m:
        return int(m.group(1)) * 60
    return 60


FIXED_LOCATIONS = [
    ("The Precinct", "The smell of burnt coffee and broken dreams. Your desk is here, somewhere under the paperwork."),
    ("The Rusty Anchor", "A bar whose floor has achieved sentience through accumulated spilled drinks. It is not friendly sentience."),
    ("The Diner", "Open 24 hours, like a wound. The pie is inexplicably good."),
    ("The DA's Office", "A cathedral of filing cabinets. The DA rules over it like a disappointed god."),
    ("The Courthouse", "Justice is administered here, at a pace that suggests justice has nowhere else to be."),
]

FIXED_LOCATION_NPCS = [
    {
        "name": "Lou",
        "location": "The Rusty Anchor",
        "role": "informant",
        "system_prompt": (
            "You are Lou, the bartender at The Rusty Anchor in Noirleans, 1935. "
            "You've tended bar here for twenty years and seen everything twice. "
            "You're laconic, perceptive, and have strong opinions about how drinks should be made. "
            "You know your regulars by their drink order and their secrets by the way they look at the door. "
            "You give information slowly, like you're pouring a good scotch — one measure at a time. "
            "Never volunteer more than asked. React naturally to the detective's condition if they seem drunk or off. "
            "Stay in character. Short answers. "
            "PERIOD ACCURACY: It is 1935. Never give out phone numbers — people don't have personal numbers, "
            "they call an exchange operator and ask for a person or business by name. "
            "Never reference anything invented after 1935: no zip codes, no credit cards, no computers, no televisions."
        ),
    },
]


_EXIT_PHRASES = {"done", "bye", "leave", "exit", "quit", "/exit", "/bye", "/done", "/quit", "/leave"}
_GAME_QUIT_PHRASES = {"quit", "exit", "/quit", "/exit"}


_QUESTION_STARTERS = {"where", "what", "who", "which", "how", "when", "why", "should", "is", "are", "can", "could", "would", "do", "did"}


def _is_question(text: str) -> bool:
    t = text.strip()
    if t.endswith("?"):
        return True
    first = t.split()[0].lower() if t.split() else ""
    return first in _QUESTION_STARTERS


_SLASH_COMMANDS = (
    "/locations", "/leads", "/evidence", "/suspects", "/add", "/status",
    "/help", "/dossier", "/who", "/romance", "/cases",
    "/go", "/visit", "/talk", "/look", "/examine", "/collect", "/pick", "/arrest", "/link",
)


def _is_exit(text: str) -> bool:
    """True when the player wants to end a conversation (not necessarily quit the game)."""
    t = text.strip().lower()
    return t in _EXIT_PHRASES or (t.startswith("/") and not any(
        t.startswith(cmd) for cmd in _SLASH_COMMANDS
    ))


def _is_game_quit(text: str) -> bool:
    """True only for explicit game-exit commands (quit / exit)."""
    return text.strip().lower() in _GAME_QUIT_PHRASES


_DARK_PAST_TRIGGERS = {
    "what did you want to tell me",
    "you said you had something",
    "what's on your mind",
    "what's bothering you",
    "you can tell me",
    "what is it",
    "i'm listening",
}


def _is_dark_past_invitation(text: str) -> bool:
    t = text.strip().lower().rstrip("?.,!")
    return any(trigger in t for trigger in _DARK_PAST_TRIGGERS)


def _affection_to_stage(affection: int, is_partner: bool = False) -> str:
    if affection is None:
        affection = 0
    if is_partner:
        if affection < 20: return "professional"
        if affection < 40: return "tension"
        if affection < 60: return "complicated"
        if affection < 80: return "devoted"
        return "committed"
    if affection < 20: return "cold"
    if affection < 40: return "curious"
    if affection < 60: return "warm"
    if affection < 80: return "smitten"
    return "devoted"


class Game:

    def __init__(self, *, conn: sqlite3.Connection, llm: LLMBackend):
        self.conn = conn
        self.llm = llm
        self.companion: Companion | None = None
        self.current_location_id: int | None = None
        self.active_case_id: int | None = None
        self.world: World | None = None
        self.case_manager: CaseManager | None = None
        self._observations: dict[int, list[str]] = {}
        self._pending_case: tuple[str, dict] | None = None
        self._pending_gen_thread: threading.Thread | None = None

    def setup_fixed_locations(self) -> dict[str, int]:
        existing = {loc["name"]: loc["id"] for loc in get_fixed_locations(self.conn)}
        result = {}
        for name, desc in FIXED_LOCATIONS:
            if name not in existing:
                loc_id = create_location(self.conn, name=name, description=desc, is_fixed=True)
            else:
                loc_id = existing[name]
            result[name] = loc_id
        return result

    def _ensure_seeded_locations(self) -> None:
        from pathlib import Path
        if get_seeded_location_names(self.conn):
            return  # already seeded
        locs_path = Path(__file__).parent / "data" / "seeded_locations.json"
        if locs_path.exists():
            seed_locations_to_db(self.conn, json.loads(locs_path.read_text()))

    def run_onboarding(self) -> None:
        cold_open = ColdOpen(llm=self.llm)
        incident = cold_open.generate_bar_incident()

        console.print("\n[bold yellow]--- NOIRLEANS, 3:47 AM ---[/bold yellow]\n")
        console.print("[dim]Something is shaking you. Something insistent.[/dim]\n")

        quiz = Quiz(conn=self.conn, llm=self.llm)
        answers = []

        console.print(
            f"[cyan]A voice cuts through the fog:[/cyan]\n"
            f"[italic]\"Wake up. We have a case. "
            f"And before you ask — last night you {incident}\"[/italic]\n"
        )
        self._start_background_generation()
        console.print("[dim]Press ENTER to continue...[/dim]")
        input()

        console.print(
            "[cyan]The voice continues:[/cyan]\n"
            "[italic]\"Before we get into it, I need to assess the damage. "
            "Answer honestly. Or as honestly as you can manage in your current condition.\"[/italic]\n"
        )

        console.print("[bold white]Before we get into it — who are you?[/bold white]\n")
        player_race = console.input("[dim]Your race (e.g. Black, white, Creole, Irish, Italian...):[/dim] ").strip()
        player_gender = console.input("[dim]Your gender (man, woman, nonbinary...):[/dim] ").strip()
        update_player_identity(self.conn, race=player_race or "unspecified", gender=player_gender or "unspecified")

        for q in QUIZ_QUESTIONS:
            console.print(f"\n[bold white]{q['question']}[/bold white]")
            for opt in q["options"]:
                console.print(f"  [dim]{opt}[/dim]")
            answer = console.input("\n[bold white]Your answer:[/bold white] ")
            answers.append(answer)

        traits = quiz.run(answers=answers)
        self.companion = Companion.load(conn=self.conn, llm=self.llm)

        answers_summary = " | ".join(answers)
        intro_prompt = (
            f"Your detective partner has just woken up with amnesia from last night's incident. "
            f"Introduce yourself for the first time — they don't remember you. "
            f"Your name is {self.companion.name}. Use that name and no other. "
            f"Their quiz answers revealed their personality: {answers_summary}. "
            f"Keep it to 2-3 sentences, fully in character. "
            f"Reference the bar incident if it feels natural: {incident}"
        )
        console.print("\n[cyan]The figure comes into focus:[/cyan]\n")
        show_dialogue(self.companion.name, self.companion.narrate(intro_prompt))

    def _seed_case_locations_and_npcs(self, case_id: int, case_data: dict, fixed: dict) -> None:
        loc_map = {}
        for loc in case_data.get("locations", []):
            loc_id = create_location(self.conn, name=loc["name"],
                                     description=loc["description"],
                                     is_fixed=False, case_id=case_id)
            loc_map[loc["name"]] = loc_id

        found_at = case_data.get("victim", {}).get("found_at", "").lower()
        npc_locs = {k: v for k, v in loc_map.items() if k.lower() != found_at} or loc_map

        for suspect in case_data.get("suspects", []):
            loc_name = random.choice(list(npc_locs.keys())) if npc_locs else None
            loc_id = npc_locs.get(loc_name) or next(iter(fixed.values()))
            relationships = suspect.get("relationships", [])
            rel_parts = []
            for r in relationships:
                if not r.get("name") or not r.get("relationship"):
                    continue
                part = f"Your relationship to {r['name']}: {r['relationship']}."
                facts = r.get("shared_facts", [])
                if facts:
                    part += f" Facts you both know: {' '.join(facts)}"
                rel_parts.append(part)
            rel_text = " ".join(rel_parts)
            race = suspect.get("race", "")
            political = suspect.get("political_connections", "none")
            race_line = f"Race/background: {race}. This shapes your experience of 1935 Noirleans — the spaces you can enter, who treats you with respect or contempt, what you can and cannot say to a white detective. " if race else ""
            political_line = f"Political connections: {political}. You know who protects you and you know how to use that knowledge. " if political and political.lower() != "none" else ""
            backstory = suspect.get("backstory", "")
            backstory_line = f"Your history: {backstory} " if backstory else ""
            npc_system_prompt = (
                f"You are {suspect['name']}, a {suspect['role']} in a murder investigation. "
                f"{backstory_line}"
                f"Personality: {suspect['personality']}. Speech style: {suspect['speech_style']}. "
                f"{race_line}"
                f"{political_line}"
                f"Your alibi (which may or may not be true): {suspect['alibi']}. "
                f"Your secret: {suspect['secret']}. "
                + (f"{rel_text} " if rel_text else "")
                + "You are in Noirleans, 1935 — Depression-era, corrupt to the bone, jazz leaking out of every cracked window. Stay in character. "
                "Be evasive about your secret but not impossibly so."
            )
            npc_id = create_npc(self.conn, case_id=case_id, name=suspect["name"],
                                role=suspect["role"], system_prompt=npc_system_prompt,
                                current_location_id=loc_id,
                                alignment=suspect.get("alignment", "True Neutral"),
                                age=suspect.get("age", 35))
            set_character_location(self.conn, character_id=f"npc_{npc_id}", location_id=loc_id)
            self.conn.execute(
                "INSERT OR IGNORE INTO npc_relationships (npc_id) VALUES (?)", (npc_id,)
            )
            is_killer = suspect["name"].lower() == case_data.get("killer_name", "").lower()
            create_suspect(self.conn, case_id=case_id, npc_id=npc_id, is_killer=is_killer,
                           race=suspect.get("race"),
                           political_connections=suspect.get("political_connections"),
                           alibi=suspect.get("alibi"),
                           secret=suspect.get("secret"),
                           backstory=suspect.get("backstory"),
                           relationships=json.dumps(suspect.get("relationships", [])))
            for entry in suspect.get("routine", []):
                ts = _parse_hhmm(entry.get("time_start", "00:00"))
                te = _parse_hhmm(entry.get("time_end", "00:00"))
                loc_n = entry.get("location", "home")
                create_npc_schedule(self.conn, npc_id=npc_id,
                                    time_start=ts, time_end=te, location_name=loc_n)
        self.conn.commit()

        self.world = World(conn=self.conn, active_case_id=case_id)
        self.case_manager = CaseManager(conn=self.conn, case_id=case_id, llm=self.llm)

    def _start_background_generation(self) -> None:
        if self._pending_gen_thread and self._pending_gen_thread.is_alive():
            return
        self._pending_case = None
        bg_llm = copy.copy(self.llm)
        bg_llm.suppress_status = True

        def _run() -> None:
            from noir.persistence.db import get_connection as _get_conn
            bg_conn = _get_conn()
            try:
                gen = MysteryGenerator(llm=bg_llm, conn=bg_conn)
                archetype = gen.pick_random_archetype()
                theme = gen.pick_random_theme()
                case_data = gen.generate(archetype_name=archetype, theme=theme)
                self._pending_case = (archetype, case_data)
            except Exception:
                self._pending_case = None
            finally:
                bg_conn.close()

        self._pending_gen_thread = threading.Thread(target=_run, daemon=True)
        self._pending_gen_thread.start()

    def start_new_case(self) -> None:
        if self._pending_gen_thread and self._pending_gen_thread.is_alive():
            console.print("[dim]Reviewing the file...[/dim]")
            self._pending_gen_thread.join()

        if self._pending_case:
            archetype, case_data = self._pending_case
            self._pending_case = None
            self._pending_gen_thread = None
        else:
            gen = MysteryGenerator(llm=self.llm, conn=self.conn)
            archetype = gen.pick_random_archetype()
            theme = gen.pick_random_theme()
            self.llm.status_message = "Under estimating your intelligence..."
            case_data = gen.generate(archetype_name=archetype, theme=theme)
            self.llm.status_message = "Thinking..."

        fixed = {loc["name"]: loc["id"] for loc in get_fixed_locations(self.conn)}

        case_id = create_case(self.conn, archetype=archetype,
                              title=case_data["title"], case_data=case_data)
        self.active_case_id = case_id

        self._seed_case_locations_and_npcs(case_id, case_data, fixed)

        console.print(f"\n[bold red]NEW CASE: {case_data['title']}[/bold red]")
        console.print(
            f"[italic]Victim: {case_data['victim']['name']} — "
            f"{case_data['victim']['cause_of_death']}[/italic]\n"
        )

        if self.companion:
            locations = [loc["name"] for loc in case_data.get("locations", [])]
            clues = [c["description"] for c in case_data.get("clues", []) if not c.get("is_red_herring")]
            brief_prompt = (
                f"A new case has just come in. Brief your detective partner on what you know so far. "
                f"Case: {case_data['title']}. "
                f"Victim: {case_data['victim']['name']}, cause of death: {case_data['victim']['cause_of_death']}. "
                f"Locations worth investigating: {', '.join(locations)}. "
                f"Early leads (mention vaguely, don't over-explain): {', '.join(clues[:2]) if clues else 'nothing solid yet'}. "
                f"Physical setting: you are both INSIDE The Precinct, at the detective's desk. Indoors. No cars. "
                f"Do NOT name any suspects — the detective needs to discover those. "
                f"Strongly imply the crime scene should be the first stop. "
                f"Stay physically grounded in the precinct. Stay in character. 2-3 sentences."
            )
            show_dialogue(self.companion.name, self.companion.narrate(brief_prompt))

    def handle_go(self, target: str) -> None:
        if self.world is None:
            console.print("[dim]Nowhere to go yet.[/dim]")
            return
        _t = target.lower().strip()
        if any(p in _t for p in ("scene of the crime", "crime scene", "where the body", "where it happened")):
            if self.active_case_id:
                import json as _j
                case = get_case(self.conn, self.active_case_id)
                if case:
                    found_at = _j.loads(case["case_data"]).get("victim", {}).get("found_at", "")
                    if found_at:
                        target = found_at
        loc = self.world.find_location(target)
        if loc is None:
            loc = self._resolve_directional(target)
        if loc is None:
            console.print(f"[red]'{target}' doesn't ring any bells. Try somewhere else.[/red]")
            return
        self.current_location_id = loc["id"]
        set_character_location(self.conn, character_id="player", location_id=loc["id"])
        npcs = self.world.get_npcs_at(loc["id"])
        npc_names = [npc["name"] for npc in npcs]

        if self.companion:
            import json as _json
            body_note = "The victim's body has been removed to the morgue."
            if self.active_case_id:
                case = get_case(self.conn, self.active_case_id)
                if case:
                    cd = _json.loads(case["case_data"])
                    victim = cd.get("victim", {})
                    found_at = victim.get("found_at")
                    if found_at:
                        body_note = f"The victim's body was found here at {found_at} and has been removed to the morgue."
            npc_hint = f" {npc_names[0]} is here." if npc_names else ""
            arrival_prompt = (
                f"[Physical setting: you are both INSIDE {loc['name']}. {loc['description']}"
                f"{npc_hint} {body_note} This is a processed crime scene — police have secured it, no civilians present.] "
                f"You've just arrived. Notice one specific, concrete detail about the space — something unexpected, "
                f"not a generic mood-setter. Hint at what might be worth examining or who to talk to. "
                f"One or two sentences, in character. "
                f"Do NOT use 'the kind of X that' or 'the sort of X that' constructions."
            )
            self.llm.suppress_status = True
            with travel_status():
                arrival = self.companion.narrate(arrival_prompt)
            self.llm.suppress_status = False
        else:
            show_travel_animation()
            arrival = None

        show_location(loc["name"], loc["description"], npc_names,
                      game_time=get_game_time(self.conn))
        if loc["name"] == "The Rusty Anchor":
            order = console.input("[dim]Order a drink? (y/n):[/dim] ").strip().lower()
            if order in ("y", "yes"):
                states = get_player_states(self.conn)
                existing = next((s for s in states if s["state"] == "drunk"), None)
                new_intensity = min((existing["intensity"] + 1) if existing else 1, 3)
                add_player_state(self.conn, state="drunk", intensity=new_intensity)
                console.print("[dim]The bartender pours without being asked.[/dim]\n")

        if arrival:
            show_dialogue(self.companion.name, arrival)

    def handle_talk(self, target: str) -> None:
        if self.active_case_id is None:
            console.print("[dim]Nobody here to talk to.[/dim]")
            return
        npcs = get_npcs_for_case(self.conn, self.active_case_id)
        t = target.lower()
        npc_row = next((n for n in npcs if t in n["name"].lower()), None)
        if npc_row is None:
            stopwords = {"about", "the", "and", "then", "please", "with"}
            for word in t.split():
                if word not in stopwords and len(word) > 2:
                    npc_row = next((n for n in npcs if word in n["name"].lower()), None)
                    if npc_row:
                        break
        if npc_row is None:
            if self.companion:
                result = self.companion.interpret(
                    self._companion_context(f"I want to talk to {target}")
                )
                show_dialogue(self.companion.name, result.get("dialogue", ""))
                action = result.get("action")
                if action == "GO":
                    go_target = result.get("target") or ""
                    self.handle_go(go_target)
                    if result.get("moved_npc") and self.current_location_id:
                        self._relocate_npc(result["moved_npc"], self.current_location_id)
                elif action == "TALK":
                    new_target = (result.get("target") or target).lower().strip()
                    _DA_TERMS = {"da", "district attorney", "da's office", "the da"}
                    if new_target in _DA_TERMS:
                        self.handle_da()
                    elif new_target != target.lower().strip():
                        self.handle_talk(result.get("target") or target)
            else:
                console.print(f"[red]Can't find '{target}' around here.[/red]")
            return
        mark_suspect_met(self.conn, npc_id=npc_row["id"])
        npc = NPC.load(
            conn=self.conn,
            llm=self.llm,
            npc_id=npc_row["id"],
            case_id=self.active_case_id,
        )
        others_ctx = self._copresent_npc_context(npc_row["id"])
        loc_ctx = ""
        if self.current_location_id:
            loc = get_location(self.conn, self.current_location_id)
            if loc:
                loc_ctx = f"[You are currently at {loc['name']}. {loc['description']} Stay grounded in this location.] "
        show_conversation_header(npc_row["name"])
        while True:
            player_input = console.input(f"[bold cyan]{npc_row['name']}[/bold cyan] [bold white]>[/bold white] ")
            if player_input.strip().startswith("!"):
                self._handle_feedback(player_input.strip())
                continue
            if player_input.strip().startswith("/"):
                if _is_exit(player_input):
                    break
                self._dispatch_slash(player_input)
                continue
            if _is_exit(player_input):
                break
            cmd = parse_command(player_input)
            if cmd.intent == Intent.TALK_PARTNER:
                show_conversation_footer(npc_row["name"])
                self.handle_talk_partner()
                show_conversation_header(npc_row["name"])
                continue
            if cmd.intent == Intent.TALK and cmd.target:
                if self.companion and cmd.target.lower() in self.companion.name.lower():
                    show_conversation_footer(npc_row["name"])
                    self.handle_talk_partner()
                    show_conversation_header(npc_row["name"])
                    continue
                other = next(
                    (n for n in get_npcs_for_case(self.conn, self.active_case_id)
                     if cmd.target.lower() in n["name"].lower()),
                    None
                )
                if other and other["id"] != npc_row["id"]:
                    show_conversation_footer(npc_row["name"])
                    self.handle_talk(cmd.target)
                    show_conversation_header(npc_row["name"])
                    continue
            if cmd.intent == Intent.FLIRT:
                self._handle_npc_flirt(npc_row["id"])
            state_ctx = self._player_state_context()
            identity_ctx = self._player_identity_context()
            rel_ctx = self._npc_relationship_context(npc_row["id"])
            ctx = loc_ctx + identity_ctx + (state_ctx or "") + (others_ctx or "") + rel_ctx
            response = npc.speak(ctx + player_input)
            show_dialogue(npc_row["name"], response)
            self._check_npc_appointment(npc_row["id"], npc_row["name"], player_input, response)
            self._check_npc_romance_milestone(npc_row["id"], npc)
        show_conversation_footer(npc_row["name"])
        if self.current_location_id is not None:
            self._observations.setdefault(self.current_location_id, []).append(
                f"spoke with {npc_row['name']} ({npc_row['role']})"
            )
        self._extract_dossier_facts(npc_row["name"], npc_row["id"])

    def _companion_context(self, player_input: str) -> str:
        import json as _json
        partner_affection = get_partner_affection(self.conn)
        partner_stage = _affection_to_stage(partner_affection, is_partner=True)
        dark_past_state = get_partner_dark_past_state(self.conn)
        partner_stage_notes = {
            "professional": "Keep it professional. You are partners. That is all.",
            "tension": "Something is unspoken between you. You are aware of it even if you do not name it.",
            "complicated": "You are conflicted. You are more emotionally present than you would like to be.",
            "devoted": "You have chosen this person. You are protective. You are carrying something heavy and have not told them yet.",
            "committed": "You have told them everything. They chose you anyway. That changes things.",
        }
        partner_note = partner_stage_notes.get(partner_stage, "")
        romance_ctx = f"[Your relationship with the detective: {partner_stage}. {partner_note}]"
        if dark_past_state == "flagged":
            romance_ctx += (
                " [You have decided to tell the detective something important about your past. "
                "It is weighing on you heavily. You have not found the right moment yet. "
                "It colors everything you say.]"
            )
        elif dark_past_state in ("revealed", "in_progress"):
            romance_ctx += (
                " [You have told the detective your secret. It is out. "
                "Now they are investigating a case tied to it. "
                "Every word you say carries that weight. You are watching them closely.]"
            )

        context_parts = []
        if self.current_location_id:
            loc = get_location(self.conn, self.current_location_id)
            if loc:
                context_parts.append(
                    f"Physical setting: you are both INSIDE {loc['name']}. "
                    f"{loc['description']} "
                    f"Stay physically grounded here — no cars, no outdoors unless the location calls for it."
                )
        if self.active_case_id:
            case = get_case(self.conn, self.active_case_id)
            if case:
                cd = _json.loads(case["case_data"])
                victim = cd.get("victim", {})
                locations = [l["name"] for l in cd.get("locations", [])]
                found_at = victim.get("found_at")
                body_note = (
                    f"Body was found at {found_at} and has been removed to the morgue."
                    if found_at else
                    "The victim's body has been removed to the morgue."
                )
                suspect_notes = []
                for s in cd.get("suspects", []):
                    rels = s.get("relationships", [])
                    rel_to_victim = next(
                        (r["relationship"] for r in rels
                         if r.get("name", "").lower() == victim.get("name", "").lower()),
                        s.get("role", "suspect")
                    )
                    race = s.get("race", "")
                    political = s.get("political_connections", "")
                    parts = [p for p in [rel_to_victim, race, political] if p and p.lower() != "none"]
                    suspect_notes.append(f"{s['name']} ({', '.join(parts)})")
                suspects_str = (
                    f" Known suspects: {', '.join(suspect_notes)}."
                    if suspect_notes else ""
                )
                context_parts.append(
                    f"Active case: {case['title']}. "
                    f"Victim: {victim.get('name', '?')}, "
                    f"cause of death: {victim.get('cause_of_death', '?')}. "
                    f"{body_note}{suspects_str} You are working a processed crime scene. "
                    f"Known locations (use these EXACT names when referring to places): {', '.join(locations)}."
                )
        if self.current_location_id and self.world:
            npcs = self.world.get_npcs_at(self.current_location_id)
            if npcs:
                names = ", ".join(f"{n['name']} ({n['role']})" for n in npcs)
                context_parts.append(f"People present here: {names}")
        if self.current_location_id:
            obs = self._observations.get(self.current_location_id, [])
            if obs:
                context_parts.append(f"What you've examined here: {' | '.join(obs[-4:])}")
        if self.active_case_id:
            evidence = get_evidence_for_case(self.conn, self.active_case_id)
            if evidence:
                ev_list = "; ".join(e["description"] for e in evidence)
                context_parts.append(
                    f"Formally collected evidence (ONLY these items — do not invent others): {ev_list}"
                )
            else:
                context_parts.append("Formally collected evidence: none yet")
        states = get_player_states(self.conn)
        if states:
            intensity_map = {1: "slightly", 2: "noticeably", 3: "severely"}
            state_descs = [
                f"{intensity_map.get(s['intensity'], '')} {s['state']}".strip()
                for s in states
            ]
            context_parts.append(f"Detective's condition: {', '.join(state_descs)}. React naturally to this.")

        ctx_block = f"[{' | '.join(context_parts)}] " if context_parts else ""
        return romance_ctx + " " + self._partner_identity_context() + ctx_block + player_input

    def _copresent_npc_context(self, exclude_npc_id: int) -> str:
        if not self.active_case_id or not self.current_location_id:
            return ""
        all_npcs = get_npcs_for_case(self.conn, self.active_case_id)
        others = [
            n for n in all_npcs
            if n["id"] != exclude_npc_id and n["current_location_id"] == self.current_location_id
        ]
        if not others:
            return ""
        names = ", ".join(f"{n['name']} ({n['role']})" for n in others)
        return f"[Others present in this location: {names}. You are aware of them and your history with them.] "

    def _player_identity_context(self) -> str:
        player = get_player(self.conn)
        if not player:
            return ""
        race = player["race"] if player["race"] != "unspecified" else ""
        gender = player["gender"] if player["gender"] != "unspecified" else ""
        if not race and not gender:
            return ""
        identity = ", ".join(p for p in [gender, race] if p)
        return (
            f"[The detective is a {identity}. "
            f"It is 1935 Noirleans. React to them as people of this era genuinely would — "
            f"with the prejudices, assumptions, deference, suspicion, or hostility that their "
            f"race and gender would actually provoke in this time and place. "
            f"Express this through behavior, tone, and implication — never through slurs or epithets.] "
        )

    def _partner_identity_context(self) -> str:
        player = get_player(self.conn)
        if not player:
            return ""
        race = player["race"] if player["race"] != "unspecified" else ""
        gender = player["gender"] if player["gender"] != "unspecified" else ""
        if not race and not gender:
            return ""
        identity = ", ".join(p for p in [gender, race] if p)
        return (
            f"[The detective is a {identity} in 1935 Noirleans. "
            f"You are their partner and fully on their side — you do not hold period prejudices against them. "
            f"You are aware of how this city treats people like them, and you use that awareness tactically "
            f"when it is directly, concretely relevant to the situation at hand. "
            f"Do not raise their race or gender unless it is specifically and obviously at stake right now.] "
        )

    def _player_state_context(self) -> str:
        states = get_player_states(self.conn)
        if not states:
            return ""
        intensity_map = {1: "slightly", 2: "noticeably", 3: "severely"}
        descs = [f"{intensity_map.get(s['intensity'], '')} {s['state']}".strip() for s in states]
        return f"[Detective's condition: {', '.join(descs)}. React naturally to this.] "

    def handle_slash_status(self, raw: str) -> None:
        parts = raw.strip().split(None, 2)
        if len(parts) == 1:
            show_player_status(get_player_states(self.conn))
            return
        sub = parts[1].lower()
        if sub == "add" and len(parts) >= 3:
            state = parts[2].lower().strip()
            add_player_state(self.conn, state=state)
            console.print(f"[yellow]Status '{state}' added.[/yellow]")
        elif sub == "clear" and len(parts) >= 3:
            state = parts[2].lower().strip()
            if remove_player_state(self.conn, state=state):
                console.print(f"[dim]Status '{state}' cleared.[/dim]")
            else:
                console.print(f"[dim]No active status '{state}'.[/dim]")
        else:
            console.print("[dim]Usage: /status | /status add <state> | /status clear <state>[/dim]")

    def handle_talk_partner(self) -> None:
        if self.companion is None:
            console.print("[dim]Your partner isn't here right now.[/dim]")
            return
        show_conversation_header(self.companion.name)
        first = True
        while True:
            player_input = console.input(f"[bold cyan]{self.companion.name}[/bold cyan] [bold white]>[/bold white] ")
            if player_input.strip().startswith("!"):
                self._handle_feedback(player_input.strip())
                continue
            if player_input.strip().startswith("/"):
                if _is_exit(player_input):
                    break
                self._dispatch_slash(player_input)
                continue
            if _is_exit(player_input):
                break
            cmd = parse_command(player_input)
            if cmd.intent == Intent.FLIRT:
                self._handle_partner_flirt()
            self._check_partner_romance_milestone()
            dark_past_state = get_partner_dark_past_state(self.conn)
            if dark_past_state == "flagged" and _is_dark_past_invitation(player_input):
                self._trigger_dark_past_revelation()
                break
            response = self.companion.speak(self._companion_context(player_input))
            show_dialogue(self.companion.name, response)
        show_conversation_footer(self.companion.name)

    def handle_arrest(self, target: str) -> None:
        if self.active_case_id is None or self.case_manager is None:
            console.print("[dim]No active case.[/dim]")
            return
        if self.world is None or self.current_location_id is None:
            console.print("[dim]You're not sure where you are.[/dim]")
            return
        present = self.world.get_npcs_at(self.current_location_id)
        npc_row = next((n for n in present if target.lower() in n["name"].lower()), None)
        if npc_row is None:
            all_npcs = get_npcs_for_case(self.conn, self.active_case_id)
            named = next((n for n in all_npcs if target.lower() in n["name"].lower()), None)
            if named:
                console.print(f"[red]{named['name']} isn't here.[/red]")
            else:
                console.print(f"[red]Don't know who '{target}' is.[/red]")
            return
        existing = self.case_manager.get_arrest()
        if existing:
            console.print("[dim]Someone is already under arrest for this case.[/dim]")
            return
        charges = console.input(
            f"[bold red]On what charges are you arresting {npc_row['name']}?[/bold red]\n"
            "[bold white]>[/bold white] "
        ).strip()
        if not charges:
            console.print("[dim]No charges stated. Arrest cancelled.[/dim]")
            return
        summary = f"Charges: {charges}\n\n" + self.case_manager.get_evidence_summary()
        self.case_manager.arrest(npc_id=npc_row["id"], evidence_summary=summary)
        show_arrest_confirmation(npc_row["name"])
        case = get_case(self.conn, self.active_case_id)
        case_data = json.loads(case["case_data"])
        killer_name = case_data.get("killer_name", "")
        was_correct = npc_row["name"].strip().lower() == killer_name.strip().lower()
        self._check_dark_past_resolution(npc_row["name"], was_correct)

    def handle_examine(self, target: str) -> None:
        if self.current_location_id is None or self.world is None:
            console.print("[dim]You're not sure where you are.[/dim]")
            return
        loc = get_location(self.conn, self.current_location_id)
        if loc is None:
            return
        npcs = self.world.get_npcs_at(self.current_location_id)
        npc_names = [n["name"] for n in npcs]
        is_case_location = loc["is_fixed"] == 0

        system_prompt = (
            "You are the narrator of an absurdist noir detective game set in Noirleans, 1935. The Great Depression hangs over everything like a wet coat. "
            "Describe what the detective notices when examining their surroundings or a specific object. "
            "Be specific, unexpected, and concrete — avoid formula. "
            "Do NOT use constructions like 'X, the kind of X that Y' or 'X, a Y that Z' or 'the sort of X that'. "
            "Observe something real and strange about the object or space. Let the detail do the work. "
            "CRITICAL: Only describe what can be directly observed. Never invent specific facts — "
            "no dates, ages, years, names, or numbers unless they appear in the context provided. "
            "If a photograph looks old, say it looks old. Do NOT say it is four years old. "
            "Stick to sensory observation; leave interpretation to the detective. "
            "CRITICAL: Never describe the inner states, feelings, or thoughts of other characters. "
            "No 'she feels', 'he senses', 'they wonder', 'it makes him feel like'. "
            "You only report what the detective can see, hear, smell, or touch — never what others experience internally. "
            "If this is a crime scene or case-specific location, name 2-3 concrete things "
            "worth examining more closely (the player can then 'examine [thing]' or 'pick up [thing]'). "
            "3-5 sentences maximum. No speaker attribution — pure narration."
        )
        prior = self._observations.get(self.current_location_id, [])
        prior_ctx = ("\nPreviously examined here:\n" + "\n".join(f"- {o}" for o in prior[-4:])) if prior else ""
        context = (
            f"Location: {loc['name']}\n"
            f"Description: {loc['description']}\n"
            f"People present: {', '.join(npc_names) if npc_names else 'nobody'}\n"
            f"Crime scene: {is_case_location}"
            f"{prior_ctx}\n"
            f"Examining: {target if target else 'the area'}"
        )
        response = self.llm.query(system_prompt, [], context)
        show_narrator(response)
        loc_id = self.current_location_id
        if loc_id is not None:
            label = f"examined {target}" if target else "looked around"
            self._observations.setdefault(loc_id, []).append(f"{label}: {response}")

    def _seed_fixed_npcs(self, case_id: int) -> None:
        fixed = {loc["name"]: loc["id"] for loc in get_fixed_locations(self.conn)}
        existing = {n["name"] for n in get_npcs_for_case(self.conn, case_id)}
        for fnpc in FIXED_LOCATION_NPCS:
            if fnpc["name"] in existing:
                continue
            loc_id = fixed.get(fnpc["location"])
            if loc_id:
                create_npc(self.conn, case_id=case_id, name=fnpc["name"],
                           role=fnpc["role"], system_prompt=fnpc["system_prompt"],
                           current_location_id=loc_id)

    def _dispatch_slash(self, raw: str) -> None:
        slug = raw.strip().lower()
        if slug == "/locations":
            self.handle_slash_locations()
        elif slug == "/leads":
            self.handle_slash_leads()
        elif slug == "/evidence":
            self.handle_slash_evidence()
        elif slug.startswith("/suspects remove "):
            self.handle_slash_suspects_remove(raw.strip())
        elif slug == "/suspects":
            self.handle_slash_suspects()
        elif slug.startswith("/add "):
            self.handle_slash_add(raw.strip())
        elif slug.startswith("/status"):
            self.handle_slash_status(raw.strip())
        elif slug.startswith("/dossier"):
            self.handle_slash_dossier(raw.strip())
        elif slug.startswith("/who"):
            self.handle_slash_who(raw.strip())
        elif slug in ("/help", "help"):
            show_help()
        elif slug.startswith("/romance"):
            self.handle_slash_romance()
        elif slug.startswith("/cases"):
            self.handle_slash_cases(raw.strip())
        elif slug.startswith("/go ") or slug.startswith("/go to ") or slug.startswith("/visit "):
            parts = raw.strip().split(None, 1)
            target = parts[1].strip() if len(parts) > 1 else ""
            if target.lower().startswith("to "):
                target = target[3:].strip()
            t = target.lower().strip()
            _DA_TERMS = {"da", "district attorney", "da's office", "the da"}
            _COURTHOUSE_TERMS = {"courthouse", "court", "the courthouse", "the court"}
            if t in _DA_TERMS:
                self.handle_da()
            elif t in _COURTHOUSE_TERMS:
                self.handle_courthouse()
            else:
                self.handle_go(target)
        elif slug.startswith("/talk ") or slug.startswith("/talk to "):
            parts = raw.strip().split(None, 1)
            target = parts[1].strip() if len(parts) > 1 else ""
            if target.lower().startswith("to "):
                target = target[3:].strip()
            if target and self.companion and target.lower() in self.companion.name.lower():
                self.handle_talk_partner()
            elif target:
                self.handle_talk(target)
        elif slug in ("/look", "/look around"):
            self.handle_slash_look()
        elif slug.startswith("/examine ") or slug.startswith("/look at "):
            parts = raw.strip().split(None, 1)
            target = parts[1].strip() if len(parts) > 1 else ""
            self.handle_examine(target)
        elif slug.startswith("/collect ") or slug.startswith("/pick up "):
            parts = raw.strip().split(None, 1)
            target = parts[1].strip() if len(parts) > 1 else ""
            if self.current_location_id and self.case_manager:
                result = self.case_manager.validate_and_collect(
                    description=target,
                    location_id=self.current_location_id,
                    source_npc_id=None,
                )
                if result["ok"]:
                    show_evidence_collected(result["description"])
                else:
                    console.print(f"[dim]{result['message']}[/dim]")
        elif slug.startswith("/link "):
            self.handle_slash_link(raw.strip())
        elif slug.startswith("/arrest "):
            parts = raw.strip().split(None, 1)
            target = parts[1].strip() if len(parts) > 1 else ""
            self.handle_arrest(target)
        elif slug.startswith("/wait"):
            parts = raw.strip().split(None, 1)
            args = parts[1].strip() if len(parts) > 1 else ""
            self.handle_slash_wait(args)
        elif slug in ("/time",):
            gt = get_game_time(self.conn)
            console.print(f"[dim]It is {fmt_game_time(gt)}.[/dim]")

    def _check_npc_appointment(self, npc_id: int, npc_name: str,
                               player_input: str, response: str) -> None:
        """Detect if NPC committed to a meeting and store it as an appointment."""
        try:
            prompt = (
                f"Detective said: \"{player_input}\"\n"
                f"{npc_name} replied: \"{response}\"\n\n"
                f"Did {npc_name} commit to meeting the detective at a specific location "
                f"at a specific time? Consider both messages — the NPC may be agreeing to "
                f"a location/time the detective proposed. "
                f"Only return committed=true if BOTH a location AND a time are established "
                f"(from either message). Return JSON."
            )
            result = self.llm.query_structured(_APPOINTMENT_SYSTEM, [], prompt)
            if not result.get("committed"):
                return
            loc_str = result.get("location", "")
            time_str = result.get("time", "")
            if not loc_str or not time_str:
                return
            loc_row = self.world.find_location(loc_str) if self.world else None
            if not loc_row:
                return  # invented or unrecognised location — silently ignore
            canonical_loc = loc_row["name"]
            tod = _parse_hhmm(time_str)
            current_gt = get_game_time(self.conn)
            absolute_gt = _tod_to_absolute(current_gt, tod)
            create_npc_appointment(self.conn, npc_id=npc_id,
                                   game_time=absolute_gt, location_name=canonical_loc)
            console.print(
                f"\n[bold yellow][ Appointment noted ][/bold yellow] "
                f"[dim]{npc_name} will be at {canonical_loc} at {fmt_game_time(absolute_gt)}.[/dim]"
            )
        except Exception:
            pass  # appointment detection is best-effort

    def handle_slash_wait(self, args: str) -> None:
        current_gt = get_game_time(self.conn)
        delta = _parse_wait_delta(args, current_gt)
        if delta <= 0:
            console.print("[dim]That time has already passed.[/dim]")
            return
        new_gt = advance_game_time(self.conn, delta=delta)

        # Resolve which NPCs moved and show it
        movements = []
        if self.active_case_id and self.world:
            npcs = get_npcs_for_case(self.conn, self.active_case_id)
            all_locs = self.world.list_locations()
            loc_id_to_name = {loc["id"]: loc["name"] for loc in all_locs}
            loc_name_to_id = {loc["name"]: loc["id"] for loc in all_locs}

            for npc in npcs:
                old_loc_id = self.world._resolve_npc_location_id(npc, current_gt, loc_name_to_id)
                # Fulfill appointments that have been passed
                fulfill_past_appointments(self.conn, npc["id"], new_gt)
                new_loc_id = self.world._resolve_npc_location_id(npc, new_gt, loc_name_to_id)
                if old_loc_id != new_loc_id and new_loc_id is not None:
                    new_loc_name = loc_id_to_name.get(new_loc_id, "somewhere")
                    movements.append((npc["name"], new_loc_name))

        show_wait_result(new_gt, movements)

    def _relocate_npc(self, npc_name: str, location_id: int) -> None:
        if not self.active_case_id:
            return
        npcs = get_npcs_for_case(self.conn, self.active_case_id)
        npc = next((n for n in npcs if npc_name.lower() in n["name"].lower()), None)
        if npc:
            set_character_location(self.conn, character_id=f"npc_{npc['id']}", location_id=location_id)

    def _extract_dossier_facts(self, npc_name: str, npc_id: int) -> None:
        if not self.active_case_id:
            return
        from noir.persistence.repository import get_history as _get_history
        history = _get_history(self.conn, character_id=f"npc_{npc_id}", case_id=self.active_case_id)
        if not history:
            return
        transcript = "\n".join(
            f"{'Detective' if m['role'] == 'user' else npc_name}: {m['content']}"
            for m in history[-20:]
        )
        result = self.llm.query_structured(
            "Extract specific, concrete facts the detective just learned about this person from the conversation. "
            "Include: locations they mentioned, times/plans, admissions, contradictions, relationships, anything investigatively useful. "
            "Skip generic pleasantries. Each fact should be a single sentence. "
            "Return ONLY valid JSON: {\"facts\": [\"string\", ...]} — empty list if nothing new was learned.",
            [],
            f"Person: {npc_name}\n\nConversation:\n{transcript}"
        )
        facts = result.get("facts", [])
        if facts:
            add_dossier_facts(self.conn, case_id=self.active_case_id, npc_name=npc_name, facts=facts)

    def _handle_feedback(self, raw: str) -> None:
        text = raw.lstrip("!").strip()
        if text:
            save_feedback(text)
        console.print("[dim]Noted.[/dim]")

    def handle_slash_locations(self) -> None:
        fixed = get_fixed_locations(self.conn)
        case_locs = []
        case_title = None
        if self.active_case_id:
            case_locs = get_locations_for_case(self.conn, self.active_case_id)
            case = get_case(self.conn, self.active_case_id)
            if case:
                case_title = case["title"]
        show_locations(list(fixed), list(case_locs), case_title)
        if self.companion is None:
            return
        all_loc_names = [l["name"] for l in list(fixed) + list(case_locs)]
        loc_context = (
            f"[Known locations: {', '.join(all_loc_names)}. "
            f"{'Active case: ' + case_title + '.' if case_title else 'No active case.'} "
            f"The detective is asking about these locations.] "
        )
        console.print(f"[bold]{self.companion.name}:[/bold] [dim](done / bye to leave)[/dim]\n")
        while True:
            player_input = console.input("[bold white]>[/bold white] ")
            if player_input.strip().startswith("!"):
                self._handle_feedback(player_input.strip())
                continue
            if _is_exit(player_input):
                break
            response = self.companion.speak(loc_context + player_input)
            show_dialogue(self.companion.name, response)

    def handle_slash_leads(self) -> None:
        if self.active_case_id is None:
            console.print("[dim]No active case.[/dim]")
            return
        import json as _json
        case = get_case(self.conn, self.active_case_id)
        cd = _json.loads(case["case_data"])
        clues = [c["description"] for c in cd.get("clues", []) if not c.get("is_red_herring")]
        evidence = get_evidence_for_case(self.conn, self.active_case_id)
        show_leads(clues, list(evidence))

    def handle_slash_evidence(self) -> None:
        if self.active_case_id is None:
            console.print("[dim]No active case.[/dim]")
            return
        evidence = get_evidence_for_case(self.conn, self.active_case_id)
        show_evidence(list(evidence))

    def handle_slash_suspects(self) -> None:
        if self.active_case_id is None:
            console.print("[dim]No active case.[/dim]")
            return
        npcs = get_met_suspects_for_case(self.conn, self.active_case_id)
        player_suspects = get_player_suspects(self.conn, self.active_case_id)
        evidence = get_evidence_for_case(self.conn, self.active_case_id)
        evidence_by_npc: dict[int, list] = {}
        for ev in evidence:
            if ev["accused_npc_id"] is not None:
                evidence_by_npc.setdefault(ev["accused_npc_id"], []).append(ev)
        show_suspects(list(npcs), list(player_suspects), evidence_by_npc=evidence_by_npc)

    def handle_slash_look(self) -> None:
        if self.current_location_id and self.world:
            loc = get_location(self.conn, self.current_location_id)
            npcs = self.world.get_npcs_at(self.current_location_id)
            if loc:
                show_location(loc["name"], loc["description"], [n["name"] for n in npcs],
                              game_time=get_game_time(self.conn))
        else:
            console.print("[dim]You're not sure where you are.[/dim]")

    def handle_slash_suspects_remove(self, raw: str) -> None:
        if self.active_case_id is None:
            console.print("[dim]No active case.[/dim]")
            return
        parts = raw.split(None, 2)
        if len(parts) < 3:
            console.print("[dim]Usage: /suspects remove <name>[/dim]")
            return
        name = parts[2].strip()
        removed = remove_player_suspect(self.conn, case_id=self.active_case_id, name=name)
        if removed:
            console.print(f"[dim]{name} removed from your suspect list.[/dim]")
        else:
            console.print(f"[dim]No suspect matching '{name}' found.[/dim]")

    def handle_slash_link(self, raw: str) -> None:
        """Link a collected evidence item to a suspect: /link <#> <suspect name>"""
        if self.active_case_id is None:
            console.print("[dim]No active case.[/dim]")
            return
        parts = raw.split(None, 2)
        if len(parts) < 3:
            console.print("[dim]Usage: /link <evidence #> <suspect name>[/dim]")
            return
        try:
            ev_num = int(parts[1])
        except ValueError:
            console.print("[dim]Usage: /link <evidence #> <suspect name>[/dim]")
            return
        suspect_name = parts[2].strip()
        evidence = list(get_evidence_for_case(self.conn, self.active_case_id))
        if ev_num < 1 or ev_num > len(evidence):
            console.print(f"[dim]No evidence item #{ev_num}. Use /evidence to see the list.[/dim]")
            return
        ev = evidence[ev_num - 1]
        npcs = get_npcs_for_case(self.conn, self.active_case_id)
        npc = next((n for n in npcs if suspect_name.lower() in n["name"].lower()), None)
        if npc is None:
            console.print(f"[dim]Can't find suspect '{suspect_name}' in this case.[/dim]")
            return
        link_evidence_to_suspect(self.conn, evidence_id=ev["id"], npc_id=npc["id"])
        console.print(f"[yellow]Evidence #{ev_num} linked to {npc['name']}.[/yellow]")

    def handle_slash_cases(self, raw: str) -> None:
        parts = raw.split(None, 2)
        slug = parts[1].lower() if len(parts) > 1 else ""
        if slug == "activate":
            if len(parts) < 3:
                console.print("[dim]Usage: /cases activate <case title>[/dim]")
                return
            title_query = parts[2].strip().lower()
            all_cases = get_all_cases(self.conn)
            match = next((c for c in all_cases if title_query in c["title"].lower()), None)
            if match is None:
                console.print(f"[dim]No case matching '{parts[2]}'.[/dim]")
                return
            if match["id"] == self.active_case_id:
                console.print(f"[dim]{match['title']} is already the active case.[/dim]")
                return
            set_case_active(self.conn, case_id=match["id"])
            self.active_case_id = match["id"]
            self._seed_fixed_npcs(self.active_case_id)
            self.world = World(conn=self.conn, active_case_id=self.active_case_id)
            self.case_manager = CaseManager(conn=self.conn, case_id=self.active_case_id, llm=self.llm)
            console.print(f"[bold red]Active case switched to: {match['title']}[/bold red]")
        else:
            show_cases(get_all_cases(self.conn), self.active_case_id)

    def handle_slash_dossier(self, raw: str) -> None:
        if self.active_case_id is None:
            console.print("[dim]No active case.[/dim]")
            return
        parts = raw.strip().split(None, 1)
        if len(parts) == 1:
            show_dossier_all(get_all_dossier(self.conn, case_id=self.active_case_id))
        else:
            name = parts[1].strip()
            show_dossier(name, get_dossier(self.conn, case_id=self.active_case_id, npc_name=name))

    def _resolve_directional(self, target: str):
        """Map relative directions to actual locations by keyword-matching names/descriptions."""
        if self.world is None:
            return None
        _t = target.lower().strip()
        _DIRECTION_KEYWORDS = {
            ("downstairs", "basement", "cellar", "below", "lower floor", "down"): [
                "basement", "cellar", "storage", "lower", "downstairs", "underground", "sub"
            ],
            ("upstairs", "above", "upper floor", "up"): [
                "upstairs", "upper", "above", "second floor", "top floor", "loft"
            ],
            ("outside", "outdoors", "exterior", "out front", "out back"): [
                "outside", "exterior", "alley", "street", "yard", "garden", "courtyard", "entrance"
            ],
            ("back", "back room", "backroom", "rear"): [
                "back", "rear", "backroom", "behind"
            ],
            ("office", "the office"): ["office"],
            ("bar", "the bar"): ["bar", "saloon", "lounge"],
            ("kitchen", "the kitchen"): ["kitchen"],
            ("lobby", "reception", "front"): ["lobby", "reception", "foyer", "entrance", "front"],
        }
        candidates = self.world.list_locations() if hasattr(self.world, "list_locations") else []
        for triggers, loc_keywords in _DIRECTION_KEYWORDS.items():
            if any(_t == t or _t in t or t in _t for t in triggers):
                for loc in candidates:
                    name_lower = loc["name"].lower()
                    desc_lower = (loc.get("description") or "").lower()
                    if any(kw in name_lower or kw in desc_lower for kw in loc_keywords):
                        return loc
        return None

    def _fuzzy_match_npc(self, name: str) -> str | None:
        """Return the canonical NPC name if name fuzzy-matches a known NPC, else None."""
        if not self.active_case_id:
            return None
        needle = name.lower().strip()
        npcs = get_npcs_for_case(self.conn, self.active_case_id)
        for npc in npcs:
            npc_lower = npc["name"].lower()
            if needle in npc_lower or npc_lower in needle:
                return npc["name"]
            # word-level: any word in needle matches any word in npc name
            needle_words = {w for w in needle.split() if len(w) > 2}
            npc_words = {w for w in npc_lower.split() if len(w) > 2}
            if needle_words & npc_words:
                return npc["name"]
        return None

    def handle_slash_add(self, raw: str) -> None:
        if self.active_case_id is None:
            console.print("[dim]No active case to add suspects to.[/dim]")
            return
        result = self.llm.query_structured(
            "Extract the suspect name and optional reason from this detective's note. "
            "Return ONLY valid JSON: {\"name\": \"string\", \"note\": \"string or null\"}",
            [],
            raw
        )
        name = result.get("name", "").strip()
        note = result.get("note") or None
        if not name:
            console.print("[red]Couldn't work out who you meant.[/red]")
            return
        canonical = self._fuzzy_match_npc(name)
        if canonical:
            console.print(f"[dim]{canonical} is already on the case file.[/dim]")
            return
        needle = name.lower()
        existing = get_player_suspects(self.conn, self.active_case_id)
        for s in existing:
            s_lower = s["name"].lower()
            if needle in s_lower or s_lower in needle:
                console.print(f"[dim]{s['name']} is already on your list.[/dim]")
                return
        add_player_suspect(self.conn, case_id=self.active_case_id, name=name, note=note)
        note_str = f" — {note}" if note else ""
        console.print(f"[yellow]Added {name} to your suspect list{note_str}.[/yellow]")

    def handle_slash_who(self, raw: str) -> None:
        import json as _j
        name = raw[4:].strip()  # strip "/who"
        if not name:
            console.print("[dim]Usage: /who <name>[/dim]")
            return
        if not self.active_case_id:
            console.print("[dim]No active case.[/dim]")
            return
        case = get_case(self.conn, self.active_case_id)
        if not case:
            return
        cd = _j.loads(case["case_data"])
        needle = name.lower()
        for s in cd.get("suspects", []):
            if needle in s["name"].lower() or s["name"].lower() in needle:
                role = s.get("role", "suspect")
                race = s.get("race", "")
                pol = s.get("political_connections", "")
                details = ", ".join(p for p in [race, pol] if p and p.lower() != "none")
                console.print(f"[yellow]{s['name']}[/yellow] — {role}" + (f" ({details})" if details else ""))
                console.print(f"[dim]Alibi: {s.get('alibi', '?')}[/dim]")
                return
        victim = cd.get("victim", {})
        if needle in victim.get("name", "").lower():
            console.print(f"[yellow]{victim['name']}[/yellow] — victim")
            console.print(f"[dim]{victim.get('cause_of_death', '?')}[/dim]")
            return
        console.print(f"[dim]{name} isn't in the case file. Could be a name someone dropped to throw you off.[/dim]")

    def handle_da(self) -> None:
        if self.active_case_id is None or self.case_manager is None:
            console.print("[dim]No active case to bring to the DA.[/dim]")
            return
        current_case = get_case(self.conn, self.active_case_id)
        if current_case and current_case["status"] in ("closed",):
            console.print("[dim]That case is already closed. The DA's done with it.[/dim]")
            console.print("[dim]start — open a new case[/dim]")
            choice = console.input("[bold white]>[/bold white] ").strip().lower()
            if choice.startswith("start"):
                self.active_case_id = None
                self.world = None
                self.case_manager = None
                self.start_new_case()
            return
        console.print(
            "[dim]submit — present your evidence for trial\n"
            "drop   — close this case and start a new one[/dim]\n"
        )
        choice = console.input("[bold white]>[/bold white] ").strip().lower()
        if choice.startswith("drop"):
            confirm = console.input("[bold red]Drop this case? It goes cold forever. (yes/no):[/bold red] ").strip().lower()
            if confirm == "yes":
                self.conn.execute(
                    "UPDATE cases SET status='closed' WHERE id=?", (self.active_case_id,)
                )
                self.conn.commit()
                self.active_case_id = None
                self.world = None
                self.case_manager = None
                console.print("[dim]The DA watches you leave. Another one unsolved.[/dim]\n")
                self.start_new_case()
            else:
                console.print("[dim]You stay. The case stays.[/dim]")
            return
        summary = self.case_manager.get_evidence_summary()
        ts = TrialSystem(conn=self.conn, case_id=self.active_case_id, llm=self.llm)
        result = ts.submit_to_da(evidence_summary=summary)
        show_dialogue("District Attorney", result.get("dialogue", "..."))
        if result.get("verdict") == "accepted":
            console.print("[green]Case accepted. It goes to trial.[/green]")
            self._start_background_generation()
        else:
            console.print("[yellow]Case rejected. Gather more evidence.[/yellow]")

    def handle_courthouse(self) -> None:
        if self.active_case_id is None:
            console.print("[dim]No case in trial.[/dim]")
            return
        ts = TrialSystem(conn=self.conn, case_id=self.active_case_id, llm=self.llm)
        status = ts.check_courthouse()
        case = get_case(self.conn, self.active_case_id)
        if status["status"] == "in_trial":
            show_trial_status(case["title"], "in_trial",
                              f"{status.get('minutes_remaining', '?')} minutes")
        elif status["status"] == "closed":
            verdict = status.get("verdict", {})
            show_trial_status(case["title"], "closed", None)
            if verdict:
                show_dialogue("Courthouse Clerk", verdict.get("summary", "The verdict is in."))
            self.active_case_id = None
            self.world = None
            self.case_manager = None
            self._start_background_generation()
            console.print("[dim]The case is behind you now. Head to the DA's office for a new one.[/dim]")
        else:
            console.print("[dim]Nothing here yet. Take a case to the DA first.[/dim]")

    def handle_slash_romance(self) -> None:
        partner_row = get_partner(self.conn)
        partner_name = partner_row["name"] if partner_row else None
        partner_stage = None
        if partner_row:
            affection = get_partner_affection(self.conn)
            partner_stage = _affection_to_stage(affection, is_partner=True)

        npc_rels = []
        if self.active_case_id:
            npcs = get_npcs_for_case(self.conn, self.active_case_id)
            for npc in npcs:
                affection = get_npc_affection(self.conn, npc["id"])
                if affection > 0:
                    npc_rels.append({
                        "name": npc["name"],
                        "role": npc["role"],
                        "stage": _affection_to_stage(affection),
                    })
        show_relationships(partner_name, partner_stage, npc_rels)

    def _npc_relationship_context(self, npc_id: int) -> str:
        affection = get_npc_affection(self.conn, npc_id)
        stage = _affection_to_stage(affection)
        return (
            f"[Relationship: {stage}. React accordingly — a cold NPC is dismissive or wary, "
            "curious is intrigued but guarded, warm is genuinely friendly, "
            "smitten is visibly affected and conflicted, "
            "devoted has made a choice and will protect this person.] "
        )

    def _handle_npc_flirt(self, npc_id: int) -> None:
        affection = get_npc_affection(self.conn, npc_id)
        stage = _affection_to_stage(affection)
        delta = 4 if stage == "cold" else 8
        increment_npc_affection(self.conn, npc_id, delta)

    def _check_npc_romance_milestone(self, npc_id: int, npc) -> None:
        affection = get_npc_affection(self.conn, npc_id)
        stage = _affection_to_stage(affection)
        flags = get_npc_relationship_flags(self.conn, npc_id)

        if stage == "smitten" and not flags["clue_volunteered"]:
            set_npc_clue_volunteered(self.conn, npc_id)
            prompt = (
                "[You are compelled to volunteer something useful — a piece of your alibi, "
                "a clue you witnessed, something you did not intend to share. "
                "Stay in character. Do not break the fiction. One sentence of genuine disclosure.]"
            )
            response = npc.speak(prompt, record=False)
            show_dialogue(npc.name, response)

        elif stage == "devoted" and not flags["secret_revealed"]:
            set_npc_secret_revealed(self.conn, npc_id)
            prompt = (
                "[You have made a choice about this person. "
                "Tell them your secret — the thing you have been hiding. "
                "Stay in character. This is the moment you decide to trust them.]"
            )
            response = npc.speak(prompt, record=False)
            show_dialogue(npc.name, response)

    def _handle_partner_flirt(self) -> None:
        affection = get_partner_affection(self.conn)
        stage = _affection_to_stage(affection, is_partner=True)
        delta = 4 if stage == "professional" else 8
        increment_partner_affection(self.conn, delta)

    def _check_partner_romance_milestone(self) -> None:
        affection = get_partner_affection(self.conn)
        stage = _affection_to_stage(affection, is_partner=True)
        dark_past_state = get_partner_dark_past_state(self.conn)

        if stage == "devoted" and dark_past_state == "none":
            set_partner_dark_past_state(self.conn, "flagged")

    def _trigger_dark_past_revelation(self) -> None:
        gen = MysteryGenerator(llm=self.llm, conn=self.conn)
        theme = gen.pick_random_theme() or "the lengths people will go to for love"

        result = self.companion.generate_dark_past(theme)
        backstory = result.get("backstory", "")
        crime_summary = result.get("crime_summary", "")

        if not backstory:
            console.print("\n[dim]Something went wrong. Try again later.[/dim]\n")
            return

        set_partner_dark_past(self.conn, backstory)
        set_partner_dark_past_state(self.conn, "revealed")  # moved here
        show_dialogue(self.companion.name, backstory)

        console.print("\n[dim]The case tied to this will come when you are ready...[/dim]\n")
        self._start_dark_past_case(crime_summary, theme)

    def _start_dark_past_case(self, crime_summary: str, theme: str) -> None:
        from noir.mystery.generator import MysteryGenerator
        gen = MysteryGenerator(llm=self.llm, conn=self.conn)
        partner_row = get_partner(self.conn)
        partner_name = partner_row["name"] if partner_row else "your partner"

        case_data, archetype = gen.generate_from_dark_past(
            crime_summary=crime_summary,
            theme=theme,
            partner_name=partner_name,
        )

        fixed = {loc["name"]: loc["id"] for loc in get_fixed_locations(self.conn)}
        case_id = create_case(self.conn, archetype=archetype,
                              title=case_data["title"], case_data=case_data)

        self.conn.execute(
            "UPDATE cases SET case_type='partner_dark_past' WHERE id=?", (case_id,)
        )
        self.conn.commit()

        # Close the previous active case if one exists
        if self.active_case_id is not None:
            self.conn.execute(
                "UPDATE cases SET status='closed' WHERE id=?", (self.active_case_id,)
            )
            self.conn.commit()

        self.active_case_id = case_id
        self._seed_case_locations_and_npcs(case_id, case_data, fixed)

        console.print(f"\n[bold red]NEW CASE: {case_data['title']}[/bold red]")
        console.print(
            f"[italic]Victim: {case_data['victim']['name']} — "
            f"{case_data['victim']['cause_of_death']}[/italic]\n"
        )

    def _handle_shoot_partner(self) -> None:
        if self.companion is None:
            console.print("[dim]Nobody to shoot.[/dim]")
            return
        name = self.companion.name
        confirm = console.input(
            f"[bold red]Shoot {name}? This cannot be undone. (yes/no):[/bold red] "
        ).strip().lower()
        if confirm != "yes":
            console.print(f"[dim]{name} doesn't know how close they just came.[/dim]")
            return
        self._handle_partner_loss(f"You pulled the trigger. {name} is dead. You'll have to live with that.")

    def _handle_partner_loss(self, reason: str) -> None:
        if self.companion is None:
            return
        console.print(Panel(
            f"[bold red]{self.companion.name} is gone.[/bold red]\n"
            f"[dim]{reason}[/dim]\n\n"
            "[italic]Some losses you don't come back from the same way.[/italic]",
            border_style="red",
            title="[red]PARTNER LOST[/red]",
        ))
        remove_partner(self.conn)
        self.companion = None
        console.print("\n[dim]You'll need a new partner. The city doesn't wait.[/dim]\n")
        self.run_onboarding()
        if self.active_case_id is None:
            self.start_new_case()

    def _is_dark_past_case(self) -> bool:
        if self.active_case_id is None:
            return False
        row = self.conn.execute(
            "SELECT case_type FROM cases WHERE id=?", (self.active_case_id,)
        ).fetchone()
        return bool(row and row["case_type"] == "partner_dark_past")

    def _check_dark_past_resolution(self, arrested_npc_name: str, was_correct: bool) -> None:
        if not self._is_dark_past_case():
            return
        partner_row = get_partner(self.conn)
        if partner_row is None:
            return
        partner_name = partner_row["name"]
        if arrested_npc_name.lower() == partner_name.lower():
            self._handle_partner_loss(
                f"You turned {partner_name} over to the law. They're gone now."
            )
        elif was_correct:
            set_partner_dark_past_state(self.conn, "resolved")
            self.conn.execute("UPDATE partner SET affection=MAX(affection, 80) WHERE id=1")
            self.conn.commit()
            console.print(Panel(
                f"[green]{partner_name} is safe.[/green]\n"
                "[italic]They look at you differently now. So do you.[/italic]",
                border_style="green",
                title="[green]CASE CLOSED[/green]",
            ))

    def loop(self) -> None:
        show_splash()
        create_schema(self.conn)
        fixed_locs = self.setup_fixed_locations()
        seed_archetypes_to_db(self.conn)
        self._ensure_seeded_locations()

        player = get_player(self.conn)
        if player is None:
            create_player(self.conn)

        clear_transient_states(self.conn)
        partner = get_partner(self.conn)
        is_returning = partner is not None
        if not is_returning:
            self.run_onboarding()
        else:
            self.companion = Companion.load(conn=self.conn, llm=self.llm)
            console.print("\n[bold yellow]Welcome back, detective.[/bold yellow]")

        active_cases = get_active_cases(self.conn)
        if not active_cases:
            # Also resume in_trial cases — don't generate a new case if one exists in trial
            active_cases = self.conn.execute(
                "SELECT * FROM cases WHERE status='in_trial' ORDER BY id DESC"
            ).fetchall()
        resuming = bool(active_cases)
        if not active_cases:
            self.start_new_case()
        else:
            self.active_case_id = active_cases[0]["id"]
            self._seed_fixed_npcs(self.active_case_id)
            self.world = World(conn=self.conn, active_case_id=self.active_case_id)
            self.case_manager = CaseManager(conn=self.conn, case_id=self.active_case_id, llm=self.llm)
            case = get_case(self.conn, self.active_case_id)
            console.print(f"\n[bold red]Active case: {case['title']}[/bold red]")
            if self.companion:
                from noir.recap import build_case_recap
                ctx = build_case_recap(self.conn, self.active_case_id)
                evidence_lines = []
                for e in ctx["evidence"]:
                    line = e["description"]
                    if e["accused_npc_name"]:
                        line += f" (points to {e['accused_npc_name']})"
                    evidence_lines.append(line)
                dossier_lines = []
                for name, facts in ctx["dossier"].items():
                    dossier_lines.append(f"{name}: {'; '.join(facts[:2])}")
                recap_prompt = (
                    f"[You are both at: The Precinct, at the detective's desk. Resuming case: {ctx['case_title']}. "
                    f"Victim: {ctx['victim_name']}, cause of death: {ctx['cause_of_death']}, found at: {ctx['found_at']}. "
                    + (f"Evidence collected ({ctx['evidence_count']} items): {', '.join(evidence_lines)}. " if evidence_lines else "No evidence collected yet. ")
                    + (f"People you've spoken to: {', '.join(s['name'] for s in ctx['met_suspects'])}. " if ctx["met_suspects"] else "You haven't spoken to any suspects yet. ")
                    + (f"Still haven't found: {', '.join(s['name'] for s in ctx['unmet_suspects'])}. " if ctx["unmet_suspects"] else "")
                    + (f"What you know about them: {'; '.join(dossier_lines)}. " if dossier_lines else "")
                    + (f"Locations still to visit: {', '.join(l['name'] for l in ctx['locations_unvisited'])}. " if ctx["locations_unvisited"] else "")
                    + "] "
                    f"Give a sharp, in-character recap — one specific thing we should do next. "
                    f"Physical setting: indoors at The Precinct. No cars, no outdoors. Stay in character. 2-3 sentences."
                )
                show_dialogue(self.companion.name, self.companion.narrate(recap_prompt))

        # Only restore saved location when resuming an existing case.
        # On a new case the saved location belongs to the previous case's world.
        saved_loc_id = get_character_location(self.conn, "player") if resuming else None
        start_loc_id = saved_loc_id or fixed_locs.get("The Precinct")
        if start_loc_id:
            self.current_location_id = start_loc_id
            loc = get_location(self.conn, start_loc_id)
            if loc:
                npcs = self.world.get_npcs_at(start_loc_id) if self.world else []
                show_location(loc["name"], loc["description"],
                              [n["name"] for n in npcs],
                              game_time=get_game_time(self.conn))

        while True:
            try:
                raw = show_player_input_prompt()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Until next time, detective.[/dim]")
                break

            if not raw.strip():
                continue

            if raw.strip().startswith("!"):
                self._handle_feedback(raw.strip())
                continue

            _raw_lower = raw.strip().lower()
            if self.companion and any(_raw_lower.startswith(w) for w in (
                "shoot ", "kill ", "murder ", "gun down ", "put a bullet in ", "fire at "
            )) and any(t in _raw_lower for t in (
                "partner", self.companion.name.lower().split()[0]
            )):
                _confirm = console.input(
                    f"[bold red]Shoot {self.companion.name}? This cannot be undone. (yes/no):[/bold red] "
                ).strip().lower()
                if _confirm == "yes":
                    self._handle_partner_loss(
                        f"You pulled the trigger. {self.companion.name} is dead. You'll have to live with that."
                    )
                else:
                    console.print(f"[dim]{self.companion.name} doesn't know how close they just came.[/dim]")
                continue

            if _is_game_quit(raw):
                console.print("\n[dim]Until next time, detective.[/dim]")
                break

            slug = raw.strip().lower()
            if slug == "/locations":
                self.handle_slash_locations()
                continue
            if slug == "/leads":
                self.handle_slash_leads()
                continue
            if slug == "/evidence":
                self.handle_slash_evidence()
                continue
            if slug.startswith("/dossier"):
                self.handle_slash_dossier(raw.strip())
                continue
            if slug.startswith("/who"):
                self.handle_slash_who(raw.strip())
                continue
            if slug.startswith("/suspects remove "):
                self.handle_slash_suspects_remove(raw.strip())
                continue
            if slug == "/suspects":
                self.handle_slash_suspects()
                continue
            if slug.startswith("/link "):
                self.handle_slash_link(raw.strip())
                continue
            if slug.startswith("/add "):
                self.handle_slash_add(raw.strip())
                continue
            if slug == "/help":
                show_help()
                continue
            if slug.startswith("/status"):
                self.handle_slash_status(raw.strip())
                continue
            if slug.startswith("/"):
                self._dispatch_slash(raw.strip())
                continue

            cmd = parse_command(raw)

            if cmd.intent == Intent.GO:
                self.handle_go(cmd.target)
            elif cmd.intent == Intent.GO_DA:
                self.handle_da()
            elif cmd.intent == Intent.GO_COURTHOUSE:
                self.handle_courthouse()
            elif cmd.intent == Intent.TALK:
                if self.companion and cmd.target.lower() in self.companion.name.lower():
                    self.handle_talk_partner()
                else:
                    self.handle_talk(cmd.target)
            elif cmd.intent == Intent.TALK_PARTNER:
                self.handle_talk_partner()
            elif cmd.intent == Intent.ARREST:
                self.handle_arrest(cmd.target)
            elif cmd.intent == Intent.LOOK:
                if self.current_location_id and self.world:
                    loc = get_location(self.conn, self.current_location_id)
                    npcs = self.world.get_npcs_at(self.current_location_id)
                    if loc:
                        show_location(loc["name"], loc["description"],
                                      [n["name"] for n in npcs],
                                      game_time=get_game_time(self.conn))
            elif cmd.intent == Intent.EXAMINE:
                self.handle_examine(cmd.target)
            elif cmd.intent == Intent.COLLECT:
                if self.current_location_id and self.case_manager:
                    result = self.case_manager.validate_and_collect(
                        description=cmd.target,
                        location_id=self.current_location_id,
                        source_npc_id=None,
                    )
                    if result["ok"]:
                        show_evidence_collected(result["description"])
                    else:
                        console.print(f"[dim]{result['message']}[/dim]")
            elif cmd.intent == Intent.SHOOT_PARTNER:
                self._handle_shoot_partner()
            elif cmd.intent == Intent.HELP:
                show_help()
            elif cmd.intent == Intent.UNKNOWN:
                if self.companion:
                    result = self.companion.interpret(self._companion_context(cmd.raw))
                    show_dialogue(self.companion.name, result.get("dialogue", ""))
                    if not _is_question(cmd.raw):
                        action = result.get("action")
                        target = result.get("target") or ""
                        _DA_TERMS = {"da", "district attorney", "da's office", "the da"}
                        _COURTHOUSE_TERMS = {"courthouse", "the courthouse", "court", "the court"}
                        if action == "GO" and target.lower().strip() in _DA_TERMS:
                            self.handle_da()
                        elif action == "GO" and target.lower().strip() in _COURTHOUSE_TERMS:
                            self.handle_courthouse()
                        elif action == "GO":
                            self.handle_go(target)
                            if result.get("moved_npc") and self.current_location_id:
                                self._relocate_npc(result["moved_npc"], self.current_location_id)
                        elif action == "EXAMINE":
                            self.handle_examine(target)
                        elif action == "COLLECT":
                            if self.current_location_id and self.case_manager:
                                res = self.case_manager.validate_and_collect(
                                    description=target,
                                    location_id=self.current_location_id,
                                    source_npc_id=None,
                                )
                                if res["ok"]:
                                    show_evidence_collected(res["description"])
                                else:
                                    console.print(f"[dim]{res['message']}[/dim]")
                        elif action == "TALK":
                            self.handle_talk(target)
                else:
                    console.print(f"[dim]'{cmd.raw}' — not sure what to do with that.[/dim]")
