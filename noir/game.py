import json
import sqlite3
import random

from rich.panel import Panel

from noir.display import (
    show_location, show_dialogue, show_player_input_prompt, show_evidence_collected,
    show_arrest_confirmation, show_reputation, show_trial_status,
    show_help, show_relationships, console
)
from noir.parser import parse_command, Intent
from noir.llm.base import LLMBackend
from noir.persistence.repository import (
    create_player, get_player, get_partner, create_location,
    get_location, get_active_cases, get_case, get_fixed_locations,
    create_case, create_npc, set_character_location, get_npcs_for_case,
    get_npc_affection, get_npc_relationship_flags, increment_npc_affection,
    set_npc_clue_volunteered, set_npc_secret_revealed,
    get_partner_affection, increment_partner_affection,
    get_partner_dark_past_state, set_partner_dark_past_state,
    set_partner_dark_past, get_partner_dark_past,
    remove_partner,
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

        console.print("\n[bold yellow]--- NOIR CITY, 3:47 AM ---[/bold yellow]\n")
        console.print("[dim]Something is shaking you. Something insistent.[/dim]\n")

        quiz = Quiz(conn=self.conn, llm=self.llm)
        answers = []

        console.print(
            f"[cyan]A voice cuts through the fog:[/cyan]\n"
            f"[italic]\"Wake up. We have a case. Also, last night you {incident} "
            f"I've had to explain this to three different people already.\"[/italic]\n"
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

        console.print(
            f"\n[cyan]The figure comes into focus:[/cyan]\n"
            f"[italic]\"{traits['name']} is the name. "
            f"I'm your partner. I have been for two years. "
            f"You'll remember that eventually. Probably.\"[/italic]\n"
        )

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
            rel_text = " ".join(
                f"Your relationship to {r['name']}: {r['relationship']}."
                for r in relationships if r.get("name") and r.get("relationship")
            )
            npc_system_prompt = (
                f"You are {suspect['name']}, a {suspect['role']} in a murder investigation. "
                f"Personality: {suspect['personality']}. Speech style: {suspect['speech_style']}. "
                f"Your alibi (which may or may not be true): {suspect['alibi']}. "
                f"Your secret: {suspect['secret']}. "
                + (f"{rel_text} " if rel_text else "")
                + "You are in Noirleans, 1935 — Depression-era, corrupt to the bone, jazz leaking out of every cracked window. Stay in character. "
                "Be evasive about your secret but not impossibly so."
            )
            npc_id = create_npc(self.conn, case_id=case_id, name=suspect["name"],
                                role=suspect["role"], system_prompt=npc_system_prompt,
                                current_location_id=loc_id)
            set_character_location(self.conn, character_id=f"npc_{npc_id}", location_id=loc_id)

        self.world = World(conn=self.conn, active_case_id=case_id)
        self.case_manager = CaseManager(conn=self.conn, case_id=case_id)

    def start_new_case(self) -> None:
        gen = MysteryGenerator(llm=self.llm, conn=self.conn)
        archetype = gen.pick_random_archetype()
        case_data = gen.generate(archetype_name=archetype)

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

    def handle_go(self, target: str) -> None:
        if self.world is None:
            console.print("[dim]Nowhere to go yet.[/dim]")
            return
        loc = self.world.find_location(target)
        if loc is None:
            console.print(f"[red]'{target}' doesn't ring any bells. Try somewhere else.[/red]")
            return
        self.current_location_id = loc["id"]
        npcs = self.world.get_npcs_at(loc["id"])
        npc_names = [npc["name"] for npc in npcs]
        show_location(loc["name"], loc["description"], npc_names)

    def handle_talk(self, target: str) -> None:
        if self.active_case_id is None:
            console.print("[dim]Nobody here to talk to.[/dim]")
            return
        npcs = get_npcs_for_case(self.conn, self.active_case_id)
        npc_row = next((n for n in npcs if target.lower() in n["name"].lower()), None)
        if npc_row is None:
            console.print(f"[red]Can't find '{target}' around here.[/red]")
            return
        npc = NPC.load(
            conn=self.conn,
            llm=self.llm,
            npc_id=npc_row["id"],
            case_id=self.active_case_id,
        )
        console.print(f"\n[bold]Talking to {npc_row['name']}...[/bold] (type 'done' to stop)\n")
        while True:
            player_input = console.input("[bold white]You:[/bold white] ")
            if player_input.strip().lower() == "done":
                break
            cmd = parse_command(player_input)
            if cmd.intent == Intent.FLIRT:
                self._handle_npc_flirt(npc_row["id"])
            rel_ctx = self._npc_relationship_context(npc_row["id"])
            response = npc.speak(rel_ctx + player_input)
            show_dialogue(npc_row["name"], response)
            self._check_npc_romance_milestone(npc_row["id"], npc)

    def handle_talk_partner(self) -> None:
        if self.companion is None:
            console.print("[dim]Your partner isn't here right now.[/dim]")
            return
        console.print(f"\n[bold]Talking to your partner...[/bold] (type 'done' to stop)\n")
        while True:
            player_input = console.input("[bold white]You:[/bold white] ")
            if player_input.strip().startswith("/"):
                continue
            if player_input.strip().lower() == "done":
                break
            cmd = parse_command(player_input)
            if cmd.intent == Intent.FLIRT:
                self._handle_partner_flirt()
            dark_past_state = get_partner_dark_past_state(self.conn)
            if dark_past_state == "flagged" and _is_dark_past_invitation(player_input):
                self._trigger_dark_past_revelation()
                break
            self._check_partner_romance_milestone()
            response = self.companion.speak(self._companion_context(player_input))
            show_dialogue(self.companion.name, response)

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
        case = get_case(self.conn, self.active_case_id)
        case_data = json.loads(case["case_data"])
        killer_name = case_data.get("killer_name", "")
        was_correct = npc_row["name"].strip().lower() == killer_name.strip().lower()
        self._check_dark_past_resolution(npc_row["name"], was_correct)

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
        show_dialogue(self.companion.name, backstory)

        console.print("\n[dim]The case tied to this will come when you are ready...[/dim]\n")
        self._start_dark_past_case(crime_summary, theme)
        set_partner_dark_past_state(self.conn, "revealed")

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
        self.active_case_id = None  # clear stale case reference
        console.print("\n[dim]You'll need a new partner. The city doesn't wait.[/dim]\n")
        self.run_onboarding()

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

    def _companion_context(self, player_input: str) -> str:
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
        return romance_ctx + " " + player_input

    def loop(self) -> None:
        create_schema(self.conn)
        fixed_locs = self.setup_fixed_locations()
        seed_archetypes_to_db(self.conn)

        player = get_player(self.conn)
        if player is None:
            create_player(self.conn)

        partner = get_partner(self.conn)
        if partner is None:
            self.run_onboarding()
        else:
            self.companion = Companion.load(conn=self.conn, llm=self.llm)
            console.print("\n[bold yellow]Welcome back, detective.[/bold yellow]")
            show_dialogue(self.companion.name, self.companion.speak("Good. You're back. We have work to do."))

        active_cases = get_active_cases(self.conn)
        if not active_cases:
            self.start_new_case()
        else:
            self.active_case_id = active_cases[0]["id"]
            self.world = World(conn=self.conn, active_case_id=self.active_case_id)
            self.case_manager = CaseManager(conn=self.conn, case_id=self.active_case_id)
            case = get_case(self.conn, self.active_case_id)
            console.print(f"\n[bold red]Active case: {case['title']}[/bold red]")

        precinct_id = fixed_locs.get("The Precinct")
        if precinct_id:
            self.current_location_id = precinct_id
            loc = get_location(self.conn, precinct_id)
            if loc:
                show_location(loc["name"], loc["description"], [])

        show_help()

        while True:
            try:
                raw = show_player_input_prompt()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Until next time, detective.[/dim]")
                break

            if not raw.strip():
                continue

            cmd = parse_command(raw)

            if cmd.intent == Intent.GO:
                self.handle_go(cmd.target)
            elif cmd.intent == Intent.GO_DA:
                self.handle_da()
            elif cmd.intent == Intent.GO_COURTHOUSE:
                self.handle_courthouse()
            elif cmd.intent == Intent.TALK:
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
                console.print(f"[italic]You examine {cmd.target} carefully. It stares back.[/italic]")
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
            elif raw.strip().lower().startswith("/romance"):
                self.handle_slash_romance()
            elif cmd.intent == Intent.UNKNOWN:
                console.print(f"[dim]'{cmd.raw}' — not sure what to do with that.[/dim]")
