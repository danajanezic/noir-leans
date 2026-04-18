import sqlite3
import random

from noir.log import save_feedback
from noir.display import (
    show_location, show_dialogue, show_player_input_prompt, show_evidence_collected,
    show_arrest_confirmation, show_reputation, show_trial_status,
    show_help, show_locations, show_leads, show_suspects, show_player_status,
    show_travel_animation, travel_status, show_splash, typewrite, show_narrator,
    show_conversation_header, show_conversation_footer, show_evidence, console
)
from noir.parser import parse_command, Intent
from noir.llm.base import LLMBackend
from noir.persistence.repository import (
    create_player, get_player, get_partner, create_location,
    get_location, get_active_cases, get_case, get_fixed_locations,
    create_case, create_npc, set_character_location, get_npcs_for_case,
    get_locations_for_case, get_evidence_for_case,
    add_player_suspect, get_player_suspects,
    get_character_location,
    get_player_states, add_player_state, remove_player_state, clear_transient_states,
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
            "Stay in character. Short answers."
        ),
    },
]


_EXIT_PHRASES = {"done", "bye", "leave", "exit", "quit", "/exit", "/bye", "/done", "/quit", "/leave"}


_QUESTION_STARTERS = {"where", "what", "who", "which", "how", "when", "why", "should", "is", "are", "can", "could", "would", "do", "did"}


def _is_question(text: str) -> bool:
    t = text.strip()
    if t.endswith("?"):
        return True
    first = t.split()[0].lower() if t.split() else ""
    return first in _QUESTION_STARTERS


def _is_exit(text: str) -> bool:
    t = text.strip().lower()
    return t in _EXIT_PHRASES or (t.startswith("/") and not any(
        t.startswith(cmd) for cmd in ("/locations", "/leads", "/evidence", "/suspects", "/add", "/status", "/help")
    ))


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
        console.print("[dim]Press ENTER to continue...[/dim]")
        input()

        console.print(
            "[cyan]The voice continues:[/cyan]\n"
            "[italic]\"Before we get into it, I need to assess the damage. "
            "Answer honestly. Or as honestly as you can manage in your current condition.\"[/italic]\n"
        )

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
            f"Their quiz answers revealed their personality: {answers_summary}. "
            f"Keep it to 2-3 sentences, fully in character. "
            f"Reference the bar incident if it feels natural: {incident}"
        )
        console.print("\n[cyan]The figure comes into focus:[/cyan]\n")
        show_dialogue(self.companion.name, self.companion.narrate(intro_prompt))

    def start_new_case(self) -> None:
        gen = MysteryGenerator(llm=self.llm, conn=self.conn)
        archetype = gen.pick_random_archetype()
        theme = gen.pick_random_theme()
        case_data = gen.generate(archetype_name=archetype, theme=theme)

        fixed = {loc["name"]: loc["id"] for loc in get_fixed_locations(self.conn)}

        case_id = create_case(self.conn, archetype=archetype,
                              title=case_data["title"], case_data=case_data)
        self.active_case_id = case_id

        loc_map: dict[str, int] = {}
        for loc in case_data.get("locations", []):
            loc_id = create_location(self.conn, name=loc["name"], description=loc["description"],
                                     is_fixed=False, case_id=case_id)
            loc_map[loc["name"]] = loc_id

        found_at = case_data.get("victim", {}).get("found_at", "").lower()
        npc_locs = {k: v for k, v in loc_map.items() if k.lower() != found_at} or loc_map

        for suspect in case_data.get("suspects", []):
            loc_name = random.choice(list(npc_locs.keys())) if npc_locs else None
            loc_id = npc_locs.get(loc_name) or next(iter(fixed.values()))
            relationships = suspect.get("relationships", [])
            rel_text = (
                " ".join(
                    f"Your relationship to {r['name']}: {r['relationship']}."
                    for r in relationships if r.get("name") and r.get("relationship")
                )
            )
            victim = case_data.get("victim", {})
            npc_system_prompt = (
                f"You are {suspect['name']}, a {suspect['role']} in a murder investigation. "
                f"The victim is {victim.get('name', 'unknown')}, who was {victim.get('cause_of_death', 'killed')}. "
                f"This is a known fact in your world — never contradict it. "
                f"Personality: {suspect['personality']}. Speech style: {suspect['speech_style']}. "
                f"Your alibi (which may or may not be true): {suspect['alibi']}. "
                f"Your secret: {suspect['secret']}. "
                + (f"{rel_text} " if rel_text else "")
                + f"You are in Noirleans, 1935 — Depression-era, corrupt to the bone, jazz leaking out of every cracked window. Stay in character. "
                f"Be evasive about your secret but not impossibly so."
            )
            npc_id = create_npc(self.conn, case_id=case_id, name=suspect["name"],
                                role=suspect["role"], system_prompt=npc_system_prompt,
                                current_location_id=loc_id)
            set_character_location(self.conn, character_id=f"npc_{npc_id}", location_id=loc_id)

        self._seed_fixed_npcs(case_id)

        self.world = World(conn=self.conn, active_case_id=case_id)
        self.case_manager = CaseManager(conn=self.conn, case_id=case_id)

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
        loc = self.world.find_location(target)
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

        show_location(loc["name"], loc["description"], npc_names)
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
                    self.handle_talk(result.get("target") or target)
            else:
                console.print(f"[red]Can't find '{target}' around here.[/red]")
            return
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
            player_input = console.input(f"[dim]{npc_row['name']}[/dim] [bold white]>[/bold white] ")
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
            state_ctx = self._player_state_context()
            ctx = loc_ctx + (state_ctx or "") + (others_ctx or "")
            response = npc.speak(ctx + player_input if ctx else player_input)
            show_dialogue(npc_row["name"], response)
        show_conversation_footer(npc_row["name"])

    def _companion_context(self, player_input: str) -> str:
        import json as _json
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
                context_parts.append(
                    f"Active case: {case['title']}. "
                    f"Victim: {victim.get('name', '?')}, "
                    f"cause of death: {victim.get('cause_of_death', '?')}. "
                    f"{body_note} You are working a processed crime scene. "
                    f"Locations: {', '.join(locations)}."
                )
        if self.current_location_id:
            obs = self._observations.get(self.current_location_id, [])
            if obs:
                context_parts.append(f"What you've examined here: {' | '.join(obs[-4:])}")
        states = get_player_states(self.conn)
        if states:
            intensity_map = {1: "slightly", 2: "noticeably", 3: "severely"}
            state_descs = [
                f"{intensity_map.get(s['intensity'], '')} {s['state']}".strip()
                for s in states
            ]
            context_parts.append(f"Detective's condition: {', '.join(state_descs)}. React naturally to this.")
        if context_parts:
            return f"[{' | '.join(context_parts)}] {player_input}"
        return player_input

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
            player_input = console.input(f"[dim]{self.companion.name}[/dim] [bold white]>[/bold white] ")
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
            if first:
                player_input = self._companion_context(player_input)
                first = False
            response = self.companion.speak(player_input)
            show_dialogue(self.companion.name, response)
        show_conversation_footer(self.companion.name)

    def handle_arrest(self, target: str) -> None:
        if self.active_case_id is None or self.case_manager is None:
            console.print("[dim]No active case.[/dim]")
            return
        npcs = get_npcs_for_case(self.conn, self.active_case_id)
        npc_row = next((n for n in npcs if target.lower() in n["name"].lower()), None)
        if npc_row is None:
            console.print(f"[red]Can't find '{target}' to arrest.[/red]")
            return
        summary = self.case_manager.get_evidence_summary()
        self.case_manager.arrest(npc_id=npc_row["id"], evidence_summary=summary)
        show_arrest_confirmation(npc_row["name"])
        player = get_player(self.conn)
        show_reputation(player["reputation"])

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
        elif slug == "/suspects":
            self.handle_slash_suspects()
        elif slug.startswith("/add "):
            self.handle_slash_add(raw.strip())
        elif slug.startswith("/status"):
            self.handle_slash_status(raw.strip())
        elif slug in ("/help", "help"):
            show_help()

    def _relocate_npc(self, npc_name: str, location_id: int) -> None:
        if not self.active_case_id:
            return
        npcs = get_npcs_for_case(self.conn, self.active_case_id)
        npc = next((n for n in npcs if npc_name.lower() in n["name"].lower()), None)
        if npc:
            set_character_location(self.conn, character_id=f"npc_{npc['id']}", location_id=location_id)

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
        console.print(f"[bold]{self.companion.name}:[/bold] [dim](done / bye / exit to leave)[/dim]\n")
        while True:
            player_input = console.input("[bold white]>[/bold white] ")
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
        npcs = [n for n in get_npcs_for_case(self.conn, self.active_case_id)
                if n["role"] == "suspect"]
        player_suspects = get_player_suspects(self.conn, self.active_case_id)
        show_suspects(npcs, list(player_suspects))

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
        add_player_suspect(self.conn, case_id=self.active_case_id, name=name, note=note)
        note_str = f" — {note}" if note else ""
        console.print(f"[yellow]Added {name} to your suspect list{note_str}.[/yellow]")

    def handle_da(self) -> None:
        if self.active_case_id is None or self.case_manager is None:
            console.print("[dim]No active case to bring to the DA.[/dim]")
            return
        summary = self.case_manager.get_evidence_summary()
        ts = TrialSystem(conn=self.conn, case_id=self.active_case_id, llm=self.llm)
        result = ts.submit_to_da(evidence_summary=summary)
        show_dialogue("District Attorney", result.get("dialogue", "..."))
        if result.get("verdict") == "accepted":
            console.print("[green]Case accepted. It goes to trial.[/green]")
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
        else:
            console.print("[dim]Nothing here yet. Take a case to the DA first.[/dim]")

    def loop(self) -> None:
        show_splash()
        create_schema(self.conn)
        fixed_locs = self.setup_fixed_locations()
        seed_archetypes_to_db(self.conn)

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
            self.start_new_case()
        else:
            self.active_case_id = active_cases[0]["id"]
            self._seed_fixed_npcs(self.active_case_id)
            self.world = World(conn=self.conn, active_case_id=self.active_case_id)
            self.case_manager = CaseManager(conn=self.conn, case_id=self.active_case_id)
            case = get_case(self.conn, self.active_case_id)
            console.print(f"\n[bold red]Active case: {case['title']}[/bold red]")
            if self.companion:
                import json as _json
                cd = _json.loads(case["case_data"])
                victim = cd.get("victim", {})
                locations = [loc["name"] for loc in cd.get("locations", [])]
                clues = [c["description"] for c in cd.get("clues", []) if not c.get("is_red_herring")]
                recap_prompt = (
                    f"[You are both at: The Precinct. Resuming work on case: {case['title']}. "
                    f"Victim: {victim.get('name', '?')}, cause of death: {victim.get('cause_of_death', '?')}. "
                    f"Locations to investigate: {', '.join(locations)}. "
                    f"Known leads so far: {', '.join(clues[:2]) if clues else 'nothing solid yet'}.] "
                    f"Good. You're back. We have work to do. "
                    f"Physical setting: you are both INSIDE The Precinct, at the detective's desk. Indoors. No cars. "
                    f"Do NOT name suspects. Strongly steer toward the crime scene. Stay physically grounded here. Stay in character. 2-3 sentences."
                )
                show_dialogue(self.companion.name, self.companion.narrate(recap_prompt))

        saved_loc_id = get_character_location(self.conn, "player")
        start_loc_id = saved_loc_id or fixed_locs.get("The Precinct")
        if start_loc_id:
            self.current_location_id = start_loc_id
            loc = get_location(self.conn, start_loc_id)
            if loc:
                npcs = self.world.get_npcs_at(start_loc_id) if self.world else []
                show_location(loc["name"], loc["description"],
                              [n["name"] for n in npcs])

        if is_returning:
            console.print("[dim]Type 'help' at any time for a list of commands.[/dim]\n")
        else:
            show_help()

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

            if _is_exit(raw):
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
            if slug == "/suspects":
                self.handle_slash_suspects()
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
                                      [n["name"] for n in npcs])
            elif cmd.intent == Intent.EXAMINE:
                self.handle_examine(cmd.target)
            elif cmd.intent == Intent.COLLECT:
                if self.current_location_id and self.case_manager:
                    self.case_manager.collect_evidence(
                        description=cmd.target,
                        location_id=self.current_location_id,
                        source_npc_id=None,
                    )
                    show_evidence_collected(cmd.target)
            elif cmd.intent == Intent.HELP:
                show_help()
            elif cmd.intent == Intent.UNKNOWN:
                if self.companion:
                    result = self.companion.interpret(self._companion_context(cmd.raw))
                    show_dialogue(self.companion.name, result.get("dialogue", ""))
                    if not _is_question(cmd.raw):
                        action = result.get("action")
                        target = result.get("target") or ""
                        if action == "GO":
                            self.handle_go(target)
                            if result.get("moved_npc") and self.current_location_id:
                                self._relocate_npc(result["moved_npc"], self.current_location_id)
                        elif action == "EXAMINE":
                            self.handle_examine(target)
                        elif action == "COLLECT":
                            if self.current_location_id and self.case_manager:
                                self.case_manager.collect_evidence(
                                    description=target,
                                    location_id=self.current_location_id,
                                    source_npc_id=None,
                                )
                                show_evidence_collected(target)
                        elif action == "TALK":
                            self.handle_talk(target)
                else:
                    console.print(f"[dim]'{cmd.raw}' — not sure what to do with that.[/dim]")
