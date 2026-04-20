"""Single-turn execution mode for LLM-driven testing.

Input (JSON):
  {"type": "onboard", "race": "...", "gender": "...", "answers": ["A", ...]}
  {"type": "command", "input": "..."}

talk syntax for command:
  "talk <npc name>: <message>"   — one exchange with an NPC
  "talk partner: <message>"      — one exchange with partner

Output: dict with at minimum {"ok": bool} and either "error" or "state".
Text output is written to stdout (or the provided stdout kwarg).
"""
import io
import json
import re
import sqlite3

from rich.console import Console

from noir.llm.base import LLMBackend
from noir.onboarding.cold_open import ColdOpen
from noir.onboarding.quiz import Quiz, QUIZ_QUESTIONS
from noir.persistence.repository import (
    get_partner, get_active_cases, get_case, get_character_location,
    get_evidence_for_case, get_player, update_player_identity,
    get_fixed_locations, get_locations_for_case, get_npcs_for_case,
    set_character_location, get_location, create_location,
    update_case_status, update_player_stats,
    get_player_suspects, add_player_suspect,
    get_history, add_dossier_facts, get_game_time,
)
from noir.characters.companion import Companion
from noir.characters.npc import NPC
from noir.world import World
from noir.cases.manager import CaseManager


_TALK_RE = re.compile(r'^talk\s+(.+?):\s*(.+)$', re.IGNORECASE)
_PARTNER_NAMES = {"partner", "my partner"}


def _make_console(stdout) -> Console:
    return Console(file=stdout, highlight=False, markup=False)


def _get_active_case_id(conn: sqlite3.Connection) -> int | None:
    rows = get_active_cases(conn)
    if rows:
        return rows[0]["id"]
    row = conn.execute(
        "SELECT id FROM cases WHERE status='in_trial' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row["id"] if row else None


def _game_state(conn: sqlite3.Connection, case_id: int | None) -> dict:
    player = get_player(conn)
    state: dict = {
        "reputation": player["reputation"] if player else 100,
        "cases_solved": player["cases_solved"] if player else 0,
        "evidence_count": 0,
        "active_case": None,
        "current_location": None,
    }
    if case_id:
        case = get_case(conn, case_id)
        if case:
            state["active_case"] = case["title"]
        state["evidence_count"] = len(get_evidence_for_case(conn, case_id))
    loc_id = get_character_location(conn, "player")
    if loc_id:
        loc = get_location(conn, loc_id)
        state["current_location"] = loc["name"] if loc else None
    return state


def _ensure_fixed_locations(conn: sqlite3.Connection) -> None:
    from noir.game import FIXED_LOCATIONS
    existing = {loc["name"] for loc in get_fixed_locations(conn)}
    for name, desc in FIXED_LOCATIONS:
        if name not in existing:
            create_location(conn, name=name, description=desc, is_fixed=True)


def _ensure_archetypes(conn: sqlite3.Connection) -> None:
    from noir.mystery.archetype_loader import seed_archetypes_to_db
    seed_archetypes_to_db(conn)


def _ensure_seeded_locations(conn: sqlite3.Connection) -> None:
    from pathlib import Path
    from noir.persistence.repository import seed_locations_to_db, get_seeded_location_names
    if get_seeded_location_names(conn):
        return  # already seeded
    locs_path = Path(__file__).parent / "data" / "seeded_locations.json"
    if locs_path.exists():
        import json
        seed_locations_to_db(conn, json.loads(locs_path.read_text()))


# ── public API ────────────────────────────────────────────────────────────────

def run_step(input_data: dict | str, *, conn: sqlite3.Connection,
             llm: LLMBackend, stdout=None) -> dict:
    """Execute one game turn. Returns a result dict."""
    if isinstance(input_data, str):
        try:
            input_data = json.loads(input_data)
        except json.JSONDecodeError as e:
            return {"ok": False, "error": f"Invalid JSON input: {e}"}

    if stdout is None:
        import sys
        stdout = sys.stdout

    console = _make_console(stdout)

    # Redirect the global display console so all show_* functions write to our stdout
    import noir.display as _display
    _orig_console = _display.console
    _display.console = console
    try:
        _ensure_fixed_locations(conn)
        _ensure_archetypes(conn)
        _ensure_seeded_locations(conn)

        step_type = input_data.get("type")

        if step_type == "onboard":
            return _handle_onboard(input_data, conn=conn, llm=llm, console=console)
        elif step_type == "command":
            return _handle_command(input_data, conn=conn, llm=llm, console=console)
        elif step_type == "accuse":
            return _handle_accuse(input_data, conn=conn, llm=llm, console=console)
        else:
            return {"ok": False, "error": f"Unknown step type: {step_type!r}. Use 'onboard', 'command', or 'accuse'."}
    finally:
        _display.console = _orig_console


def _handle_onboard(data: dict, *, conn: sqlite3.Connection,
                    llm: LLMBackend, console: Console) -> dict:
    if get_partner(conn):
        return {"ok": False, "error": "Partner already exists — onboarding already complete."}

    answers = data.get("answers", [])
    if len(answers) != len(QUIZ_QUESTIONS):
        return {"ok": False, "error": f"Expected {len(QUIZ_QUESTIONS)} quiz answers, got {len(answers)}."}

    race = data.get("race", "unspecified")
    gender = data.get("gender", "unspecified")
    update_player_identity(conn, race=race, gender=gender)

    cold_open = ColdOpen(llm=llm)
    incident = cold_open.generate_bar_incident()

    quiz = Quiz(conn=conn, llm=llm)
    traits = quiz.run(answers=answers)

    partner = Companion.load(conn=conn, llm=llm)
    intro_prompt = (
        f"Your detective partner has just woken up with amnesia from last night's incident. "
        f"Introduce yourself for the first time — they don't remember you. "
        f"Your name is {partner.name}. Use that name and no other. "
        f"Their quiz answers: {' | '.join(answers)}. "
        f"Keep it to 2-3 sentences, fully in character. "
        f"Reference the bar incident if it feels natural: {incident}"
    )
    intro = partner.narrate(intro_prompt)
    console.print(f"\n{partner.name}: {intro}\n")

    return {
        "ok": True,
        "partner": {"name": traits["name"], "personality": traits["personality_archetype"]},
        "incident": incident,
        "state": _game_state(conn, None),
    }


def _handle_accuse(data: dict, *, conn: sqlite3.Connection,
                   llm: LLMBackend, console: Console) -> dict:
    target = data.get("target", "").strip()
    if not target:
        return {"ok": False, "error": "No target specified."}

    case_id = _get_active_case_id(conn)
    if case_id is None:
        return {"ok": False, "error": "No active case."}

    npcs = get_npcs_for_case(conn, case_id)
    t = target.lower()
    npc_row = next((n for n in npcs if t in n["name"].lower()), None)
    if npc_row is None:
        return {"ok": False, "error": f"Can't find '{target}' in this case."}

    manager = CaseManager(conn=conn, case_id=case_id, llm=llm)
    arrest_id = manager.arrest(npc_id=npc_row["id"],
                               evidence_summary=manager.get_evidence_summary())
    arrest = conn.execute("SELECT * FROM arrests WHERE id=?", (arrest_id,)).fetchone()
    correct = bool(arrest["was_correct"]) if arrest else False

    update_case_status(conn, case_id=case_id, status="closed",
                       trial_outcome="correct" if correct else "wrong")
    if correct:
        update_player_stats(conn, cases_solved_delta=1)
    else:
        update_player_stats(conn, wrong_arrests_delta=1)

    return {
        "ok": True,
        "verdict": {"accused": npc_row["name"], "correct": correct},
        "state": _game_state(conn, case_id),
    }


def _handle_command(data: dict, *, conn: sqlite3.Connection,
                    llm: LLMBackend, console: Console) -> dict:
    raw = data.get("input", "").strip()
    if not raw:
        return {"ok": False, "error": "Empty command."}

    partner_row = get_partner(conn)
    if not partner_row:
        return {"ok": False, "error": "No partner — run onboarding first."}

    case_id = _get_active_case_id(conn)

    # talk <name>: <message>
    m = _TALK_RE.match(raw)
    if m:
        target, message = m.group(1).strip(), m.group(2).strip()
        if target.lower() in _PARTNER_NAMES:
            return _talk_partner(message, conn=conn, llm=llm, console=console,
                                 case_id=case_id)
        else:
            if case_id is None:
                return {"ok": False, "error": "No active case."}
            return _talk_npc(target, message, conn=conn, llm=llm, console=console,
                             case_id=case_id)

    # slash commands
    if raw.startswith("/"):
        if case_id is None and not _is_caseless_slash(raw):
            return {"ok": False, "error": "No active case."}
        _dispatch(raw, conn=conn, llm=llm, console=console, case_id=case_id)
        return {"ok": True, "state": _game_state(conn, case_id)}

    # natural language → partner interprets
    return _talk_partner(raw, conn=conn, llm=llm, console=console,
                         case_id=case_id)


def _is_caseless_slash(slug: str) -> bool:
    s = slug.strip().lower()
    return s in ("/help", "/romance", "/cases") or s.startswith("/cases")


def _talk_partner(message: str, *, conn: sqlite3.Connection, llm: LLMBackend,
                  console: Console, case_id: int | None) -> dict:
    companion = Companion.load(conn=conn, llm=llm)
    companion.case_id = case_id

    loc_id = get_character_location(conn, "player")
    loc_ctx = ""
    if loc_id:
        loc = get_location(conn, loc_id)
        if loc:
            loc_ctx = f"[Physical setting: inside {loc['name']}. {loc['description']}] "

    result = companion.interpret(loc_ctx + message)
    dialogue = result.get("dialogue", "")
    console.print(f"\n{companion.name}: {dialogue}\n")

    action = result.get("action")
    if action == "GO" and result.get("target") and case_id:
        _do_go(result["target"], conn=conn, llm=llm, console=console, case_id=case_id)

    return {"ok": True, "state": _game_state(conn, case_id)}


def _talk_npc(target: str, message: str, *, conn: sqlite3.Connection,
              llm: LLMBackend, console: Console, case_id: int) -> dict:
    npcs = get_npcs_for_case(conn, case_id)
    t = target.lower()
    npc_row = next((n for n in npcs if t in n["name"].lower()), None)
    if npc_row is None:
        return {"ok": False, "error": f"Can't find '{target}' in this case."}

    from noir.persistence.repository import mark_suspect_met
    mark_suspect_met(conn, npc_id=npc_row["id"])

    npc = NPC.load(conn=conn, llm=llm, npc_id=npc_row["id"], case_id=case_id)
    loc_id = get_character_location(conn, "player")
    loc_ctx = ""
    if loc_id:
        loc = get_location(conn, loc_id)
        if loc:
            loc_ctx = f"[You are currently at {loc['name']}. {loc['description']}] "

    response = npc.speak(loc_ctx + message)
    console.print(f"\n{npc_row['name']}: {response}\n")

    _extract_dossier_facts(npc_row["name"], npc_row["id"], conn=conn, llm=llm, case_id=case_id)

    return {"ok": True, "state": _game_state(conn, case_id)}


def _do_go(target: str, *, conn: sqlite3.Connection, llm: LLMBackend,
           console: Console, case_id: int) -> None:
    from noir.world import World
    world = World(conn=conn, active_case_id=case_id)
    loc = world.find_location(target)
    if loc:
        set_character_location(conn, character_id="player", location_id=loc["id"])
        npcs = world.get_npcs_at(loc["id"])
        console.print(f"\n[{loc['name']}] {loc['description']}")
        if npcs:
            console.print(f"Present: {', '.join(n['name'] for n in npcs)}")
        console.print()


def _extract_dossier_facts(npc_name: str, npc_id: int, *, conn: sqlite3.Connection,
                           llm: LLMBackend, case_id: int) -> None:
    history = get_history(conn, character_id=f"npc_{npc_id}", case_id=case_id)
    if not history:
        return
    transcript = "\n".join(
        f"{'Detective' if m['role'] == 'user' else npc_name}: {m['content']}"
        for m in history[-20:]
    )
    result = llm.query_structured(
        "Extract specific, concrete facts the detective just learned about this person from the conversation. "
        "Include: locations they mentioned, times/plans, admissions, contradictions, relationships, anything investigatively useful. "
        "Skip generic pleasantries. Each fact should be a single sentence. "
        "Return ONLY valid JSON: {\"facts\": [\"string\", ...]} — empty list if nothing new was learned.",
        [],
        f"Person: {npc_name}\n\nConversation:\n{transcript}"
    )
    facts = result.get("facts", [])
    if facts:
        add_dossier_facts(conn, case_id=case_id, npc_name=npc_name, facts=facts)


def _dispatch(raw: str, *, conn: sqlite3.Connection, llm: LLMBackend,
              console: Console, case_id: int | None) -> None:
    from noir.display import (
        show_locations, show_evidence, show_suspects, show_leads,
        show_help, show_cases, show_dossier, show_dossier_all,
    )
    from noir.persistence.repository import (
        get_player_suspects, get_clues_for_case, get_all_dossier, get_dossier,
        get_all_cases, get_evidence_for_case as _get_ev,
        get_met_suspects_for_case,
    )
    slug = raw.strip().lower()

    if slug == "/locations":
        fixed = get_fixed_locations(conn)
        case_locs = get_locations_for_case(conn, case_id) if case_id else []
        case_title = None
        if case_id:
            c = get_case(conn, case_id)
            case_title = c["title"] if c else None
        show_locations(list(fixed), list(case_locs), case_title)

    elif slug == "/evidence":
        ev = _get_ev(conn, case_id) if case_id else []
        show_evidence(list(ev))

    elif slug == "/suspects":
        if case_id:
            met = get_met_suspects_for_case(conn, case_id)
            player_s = get_player_suspects(conn, case_id)
            ev = _get_ev(conn, case_id)
            ev_by_npc: dict[int, list] = {}
            for e in ev:
                if e["accused_npc_id"]:
                    ev_by_npc.setdefault(e["accused_npc_id"], []).append(e)
            show_suspects(list(met), list(player_s), ev_by_npc)
        else:
            console.print("No active case.")

    elif slug == "/leads":
        if case_id:
            clues = get_clues_for_case(conn, case_id)
            ev = _get_ev(conn, case_id)
            non_rh = [c["description"] for c in clues if not c["is_red_herring"]]
            show_leads(non_rh, list(ev))

    elif slug == "/help":
        show_help()

    elif slug.startswith("/cases"):
        cases = get_all_cases(conn)
        show_cases(list(cases), case_id)

    elif slug.startswith("/dossier"):
        parts = raw.strip().split(None, 1)
        if case_id:
            if len(parts) > 1:
                name = parts[1].strip()
                facts = get_dossier(conn, case_id=case_id, npc_name=name)
                show_dossier(name, facts)
            else:
                entries = get_all_dossier(conn, case_id=case_id)
                show_dossier_all(entries)

    elif slug.startswith("/go ") or slug.startswith("/visit "):
        parts = raw.strip().split(None, 1)
        target = parts[1].strip() if len(parts) > 1 else ""
        if target.lower().startswith("to "):
            target = target[3:].strip()
        if case_id:
            _do_go(target, conn=conn, llm=llm, console=console, case_id=case_id)

    elif slug in ("/look", "/look around"):
        from noir.display import show_location
        loc_id = get_character_location(conn, "player")
        if loc_id:
            loc = get_location(conn, loc_id)
            world = World(conn=conn, active_case_id=case_id)
            npcs = world.get_npcs_at(loc_id) if case_id else []
            if loc:
                show_location(loc["name"], loc["description"],
                              [n["name"] for n in npcs],
                              game_time=get_game_time(conn))
        else:
            console.print("You're not sure where you are.")

    elif slug.startswith("/add "):
        if case_id is None:
            console.print("No active case to add suspects to.")
            return
        result = llm.query_structured(
            "Extract the suspect name and optional reason from this detective's note. "
            "Return ONLY valid JSON: {\"name\": \"string\", \"note\": \"string or null\"}",
            [],
            raw
        )
        name = result.get("name", "").strip()
        note = result.get("note") or None
        if not name:
            console.print("Couldn't work out who you meant.")
            return
        # Check against known case NPCs (fuzzy)
        needle = name.lower()
        npcs = get_npcs_for_case(conn, case_id)
        for npc in npcs:
            npc_lower = npc["name"].lower()
            needle_words = {w for w in needle.split() if len(w) > 2}
            npc_words = {w for w in npc_lower.split() if len(w) > 2}
            if needle in npc_lower or npc_lower in needle or (needle_words & npc_words):
                console.print(f"{npc['name']} is already on the case file.")
                return
        existing = get_player_suspects(conn, case_id)
        for s in existing:
            s_lower = s["name"].lower()
            if needle in s_lower or s_lower in needle:
                console.print(f"{s['name']} is already on your list.")
                return
        add_player_suspect(conn, case_id=case_id, name=name, note=note)
        note_str = f" — {note}" if note else ""
        console.print(f"Added {name} to your suspect list{note_str}.")

    else:
        console.print(f"Unknown command: {raw}")
