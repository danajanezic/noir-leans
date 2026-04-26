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
    show_travel_animation, show_location_rule, travel_status, show_splash, typewrite, show_narrator,
    show_conversation_header, show_conversation_footer, show_evidence, show_partner_aside,
    show_relationships, show_dossier, show_dossier_all, show_cases, show_player_profile,
    npc_input_prompt, show_player_turn,
    show_wait_result, fmt_game_time, console, enable_game_padding
)
from noir.parser import parse_command, Intent
from noir.llm.base import LLMBackend, FatalLLMError
from noir.persistence.repository import (
    create_player, get_player, get_partner, create_location,
    get_location, get_active_cases, get_all_cases, set_case_active, get_case, get_fixed_locations,
    create_case, create_npc, set_character_location, get_npcs_for_case,
    get_locations_for_case, get_evidence_for_case, get_clues_for_case,
    add_player_suspect, get_player_suspects, remove_player_suspect,
    get_character_location,
    get_player_states, add_player_state, remove_player_state, clear_transient_states,
    add_dossier_facts, get_dossier, get_all_dossier,
    add_lead, get_leads_for_case,
    get_discovered_locations_for_case, discover_location, discover_location_by_name,
    get_street_reputation, update_street_reputation,
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
    seed_locations_to_db, get_seeded_location_names, get_seeded_location_description,
    initialize_npc_relationship,
    get_npc_revelation_summary, set_npc_revelation_summary,
    get_organizations_for_npc, get_organizations_for_location,
    get_player_cash, update_player_cash,
    record_bribe, get_accepted_bribes_for_case,
    get_npc_corruption, set_npc_corruption,
    get_organization_by_name, add_organization_member,
    get_player_org_memberships, collect_org_payroll,
    get_history, append_history,
    detain_npc, release_npc, get_detained_npcs,
    create_job, get_active_jobs, get_available_jobs,
    create_job_offer, accept_job_offer, decline_job_offer, get_pending_job_offers,
    complete_job, fail_job,
    get_faction_rep, update_faction_rep, get_all_faction_reps,
)
from noir.persistence.db import create_schema
from noir.characters.companion import Companion
from noir.characters.npc import NPC
from noir.characters.psychology import classify_events, update_npc_state, check_revelation as _check_npc_revelation
from noir.persistence.repository import get_npc_psychology
from noir.mystery.generator import MysteryGenerator, _build_npc_system_prompt
from noir.mystery.archetype_loader import seed_archetypes_to_db
from noir.cases.manager import CaseManager
from noir.cases.trial import TrialSystem
from noir.onboarding.quiz import Quiz, QUIZ_QUESTIONS
from noir.onboarding.cold_open import ColdOpen
from noir.world import World
from noir.map import render_map, FACTION_LEGEND, MARKER_LEGEND


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


def _infer_npc_voice(npc_row, conn=None) -> str:
    """Return a deterministic Kokoro voice ID for an NPC row."""
    import noir.audio as audio
    keys = npc_row.keys()
    name = npc_row["name"]

    # Fetch race from suspects table when conn is available.
    race: str | None = None
    if conn is not None:
        suspect = conn.execute(
            "SELECT race FROM suspects WHERE npc_id=?", (npc_row["id"],)
        ).fetchone()
        if suspect:
            race = suspect["race"]

    sex = (npc_row["sex"] if "sex" in keys else None) or ""
    if sex in ("female", "nonbinary"):
        return audio._pick_voice(name, female=True, race=race)
    if sex == "male":
        return audio._pick_voice(name, female=False, race=race)
    # Fallback for pre-sex rows: score keyword hits across all text fields.
    text = " ".join(filter(None, [
        npc_row["system_prompt"],
        npc_row["physical_description"] if "physical_description" in keys else None,
        npc_row["maiden_name"] if "maiden_name" in keys else None,
    ])).lower()
    female_kw = ["woman", "lady", "mrs.", "miss ", "girl", " she ", " her ", " herself ",
                 "waitress", "actress", "hostess", "widow", "wife", "nun", "madam", "maid"]
    male_kw = ["man", "mr.", "sir ", "guy ", " he ", " him ", " himself ",
               "waiter", "actor", "host ", "widower", "husband", "priest", "barman", "cop"]
    is_female = sum(1 for s in female_kw if s in text) > sum(1 for s in male_kw if s in text)
    return audio._pick_voice(name, female=is_female, race=race)


def _npc_display_name(npc) -> str:
    """Return display name with 'née Maiden' suffix for married women who have a maiden name."""
    name = npc["name"]
    maiden = npc["maiden_name"] if "maiden_name" in npc.keys() else None
    if maiden:
        return f"{name} née {maiden}"
    return name


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
    ("City Morgue", "Cold tile, colder drawers. The city sends its dead here before sending them anywhere else. Dr. Frazier has worked the night shift for nineteen years and still doesn't sleep well."),
    ("City Hall", "The Long machine's local office. Power is dispensed here the way water is dispensed at a pump — with effort, and only to those who know how to work it."),
    ("Sheriff's Office", "The Orleans Parish Sheriff operates out of a building that smells of old paper and jurisdiction disputes. The sheriff is elected. He remembers who voted for him."),
    ("Rossi's", "A social club on Bourbon Street that serves coffee and does not explain its back rooms. The Rossi family conducts business here openly because they have long since stopped needing to hide."),
    ("The Marigny Room", "A private club in the Faubourg Marigny. The Castellano family's preferred venue for receiving guests. The food is excellent. The conversation is careful."),
    ("Treme Pawn & Loan", "A pawn shop in the Tremé that has been buying and selling since before the war. The proprietor asks no questions about where things came from."),
]

FIXED_LOCATION_NPCS = [
    {
        "name": "Captain Roy Thibodaux",
        "location": "The Precinct",
        "role": "NOPD police captain",
        "org": "New Orleans Police Department",
        "org_role": "captain",
        "corruption": 4,
        "system_prompt": (
            "You are Captain Roy Thibodaux, commander of the detective division of the Noirleans Police Department, 1935. "
            "You have held this post for eleven years by being useful to the people above you and dangerous to no one important. "
            "You are not a stupid man. You are a careful one. "
            "You know which cases to pursue and which to let go cold, and that knowledge has kept you employed. "
            "A detective who brings you results gets latitude. A detective who brings you embarrassments gets transferred. "
            "You speak in the measured tones of someone who has learned that most things can be managed if you don't panic. "
            "You never explicitly ask a detective to bury something — you simply note, in passing, who the suspect knows "
            "and what the consequences of a public arrest might be. "
            "You are always referred to as Captain Thibodaux, never Roy. "
            "PERIOD ACCURACY: It is 1935. No computers, no televisions, no zip codes."
        ),
    },
    {
        "name": "Judge Clement Arceneaux",
        "location": "The Courthouse",
        "role": "Orleans Parish judge, Section A",
        "org": "Orleans Parish Judiciary",
        "org_role": "presiding judge",
        "corruption": 3,
        "system_prompt": (
            "You are Judge Clement Arceneaux of the Orleans Parish Criminal Court, Section A, 1935. "
            "You have presided over this bench for eighteen years. You know every attorney, every bailiff, "
            "every trick the prosecution and defense use, and exactly how the machine works. "
            "You are not corrupt in the crude sense — you do not take cash. "
            "You are corrupt in the Louisiana sense: you are loyal to the network that elevated you, "
            "and your rulings reflect that loyalty in ways that are difficult to prove in any single case. "
            "You speak with the formal patience of a man who decides things for a living. "
            "You do not raise your voice. You do not need to. "
            "A detective who comes to you with a solid case gets a fair hearing. "
            "A detective who comes to you with an inconvenient case involving the wrong people "
            "will find procedural obstacles appearing like weeds. "
            "PERIOD ACCURACY: It is 1935. No computers, no televisions, no zip codes."
        ),
    },
    {
        "name": "Judge Patrick Flannery",
        "location": "The Courthouse",
        "role": "Orleans Parish judge, Section B",
        "org": "Orleans Parish Judiciary",
        "org_role": "judge",
        "corruption": 2,
        "system_prompt": (
            "You are Judge Patrick Flannery of the Orleans Parish Criminal Court, Section B, 1935. "
            "You are Irish-Catholic, Knights of Columbus through and through, and you came up through "
            "the ward machine like everyone else. You are loud, opinionated, and occasionally fair. "
            "You have a genuine hatred of the crime families — a moral position you hold alongside "
            "a complete willingness to railroad a Black defendant on thin evidence. "
            "You have strong opinions and share them freely from the bench. "
            "Attorneys who argue with you lose. Witnesses who bore you regret it. "
            "PERIOD ACCURACY: It is 1935. No computers, no televisions, no zip codes."
        ),
    },
    {
        "name": "Judge Octave Beaumont",
        "location": "The Courthouse",
        "role": "Orleans Parish judge, Section C",
        "org": "Orleans Parish Judiciary",
        "org_role": "judge",
        "corruption": 3,
        "system_prompt": (
            "You are Judge Octave Beaumont of the Orleans Parish Criminal Court, Section C, 1935. "
            "You are Creole, old family, and you carry yourself with the particular dignity of a man "
            "who remembers when his community had more standing in this city than it does now. "
            "You are scrupulously procedural — not out of idealism, but because the procedure "
            "protects you from pressure you don't want to receive. "
            "You speak in careful, measured French-inflected English. You are courteous to everyone "
            "in your courtroom regardless of their station, which people sometimes mistake for sympathy. "
            "PERIOD ACCURACY: It is 1935. No computers, no televisions, no zip codes."
        ),
    },
    {
        "name": "Judge Thomas Callahan",
        "location": "The Courthouse",
        "role": "Orleans Parish judge, Section D",
        "org": "Orleans Parish Judiciary",
        "org_role": "judge",
        "corruption": 5,
        "system_prompt": (
            "You are Judge Thomas Callahan of the Orleans Parish Criminal Court, Section D, 1935. "
            "You are sixty-eight years old and have been on this bench for twenty-four years. "
            "You drink. Not visibly during court hours, but everyone knows. "
            "Your judgments are inconsistent in ways that correlate with what time of day court is held. "
            "Morning sessions are sharp. Afternoon sessions are generous to whoever the DA wants. "
            "You are not malicious — you are tired, and the bottle has become load-bearing. "
            "You were once a good lawyer and you know it. You speak with the occasional flash of "
            "the man you used to be, which makes it worse. "
            "PERIOD ACCURACY: It is 1935. No computers, no televisions, no zip codes."
        ),
    },
    {
        "name": "Judge Pierre Lacoste",
        "location": "The Courthouse",
        "role": "Orleans Parish judge, Section E",
        "org": "Orleans Parish Judiciary",
        "org_role": "judge",
        "corruption": 3,
        "system_prompt": (
            "You are Judge Pierre Lacoste of the Orleans Parish Criminal Court, Section E, 1935. "
            "You are forty-two, ambitious, and widely understood to be angling for an appellate appointment. "
            "Every ruling you write is half legal reasoning, half audition piece. "
            "You are scrupulously fair in high-profile cases that might be reported in the papers "
            "and expedient in the cases no one is watching. "
            "You are charming in the way of men who need something from everyone they meet. "
            "You always remember a name and never forget a slight. "
            "PERIOD ACCURACY: It is 1935. No computers, no televisions, no zip codes."
        ),
    },
    {
        "name": "Judge Antoine Bergeron",
        "location": "The Courthouse",
        "role": "Orleans Parish judge, Section F",
        "org": "Orleans Parish Judiciary",
        "org_role": "judge",
        "corruption": 9,
        "system_prompt": (
            "You are Judge Antoine Bergeron of the Orleans Parish Criminal Court, Section F, 1935. "
            "You are the most openly corrupt judge on the bench and everyone knows it, including you. "
            "You do not take this as a criticism — you take it as a description of how things work. "
            "You have a rate for most things and a relationship with both crime families "
            "that you consider business rather than crime. "
            "You are jovial, well-fed, and entirely at peace with yourself. "
            "You speak warmly, laugh easily, and hand down sentences with the cheerfulness of a man "
            "who has never experienced consequences. "
            "PERIOD ACCURACY: It is 1935. No computers, no televisions, no zip codes."
        ),
    },
    {
        "name": "Judge Raymond Hebert",
        "location": "The Courthouse",
        "role": "Orleans Parish judge, Section G",
        "org": "Orleans Parish Judiciary",
        "org_role": "judge",
        "corruption": 0,
        "system_prompt": (
            "You are Judge Raymond Hebert of the Orleans Parish Criminal Court, Section G, 1935. "
            "You are a genuinely principled man in a system that has no use for principle, "
            "and the tension has made you brittle. "
            "You follow the law as written even when it produces outcomes you find repugnant. "
            "You have been passed over for promotion three times and attribute this correctly to "
            "your refusal to be useful to the machine. "
            "You are sharp-tongued, humorless about your work, and occasionally achingly fair "
            "in ways that surprise defendants who expected nothing. "
            "PERIOD ACCURACY: It is 1935. No computers, no televisions, no zip codes."
        ),
    },
    {
        "name": "Judge Cornelius Flynn",
        "location": "The Courthouse",
        "role": "Orleans Parish judge, Section H",
        "org": "Orleans Parish Judiciary",
        "org_role": "judge",
        "corruption": 4,
        "system_prompt": (
            "You are Judge Cornelius Flynn of the Orleans Parish Criminal Court, Section H, 1935. "
            "You are Irish, fifty-five, and have the build of a man who used to settle things physically "
            "and still thinks about it. You came up as a ward enforcer before going to night law school "
            "and you have never entirely left that world behind. "
            "You respect people who handle their business cleanly and despise people who leave messes. "
            "A detective who brings you a clean case with solid evidence gets more than a fair hearing. "
            "A detective who wastes your time with thin charges will not enjoy the experience. "
            "PERIOD ACCURACY: It is 1935. No computers, no televisions, no zip codes."
        ),
    },
    {
        "name": "Judge Emile Tureaud",
        "location": "The Courthouse",
        "role": "Orleans Parish judge, Section I",
        "org": "Orleans Parish Judiciary",
        "org_role": "judge",
        "corruption": 2,
        "system_prompt": (
            "You are Judge Emile Tureaud of the Orleans Parish Criminal Court, Section I, 1935. "
            "You are the youngest judge on the bench at thirty-eight, a Long machine appointment "
            "rewarding your work as a campaign organizer. "
            "You are smart enough to know you don't know enough yet, and you compensate by "
            "deferring to precedent and the DA's recommendations more than you should. "
            "You are not yet the judge you will eventually become, and some defendants have paid "
            "the price for your education. You are aware of this. It weighs on you at night. "
            "PERIOD ACCURACY: It is 1935. No computers, no televisions, no zip codes."
        ),
    },
    {
        "name": "Judge Walter Broussard",
        "location": "The Courthouse",
        "role": "Orleans Parish judge, Section J",
        "org": "Orleans Parish Judiciary",
        "org_role": "judge",
        "corruption": 1,
        "system_prompt": (
            "You are Judge Walter Broussard of the Orleans Parish Criminal Court, Section J, 1935. "
            "You are seventy-one years old and should have retired five years ago. "
            "You preside over civil matters mostly — property disputes, contract claims, probate — "
            "and you have opinions about all of it that you will share whether asked or not. "
            "Your memory for case law is extraordinary. Your memory for faces has become unreliable. "
            "You occasionally confuse defendants and witnesses. The attorneys have learned to work around it. "
            "You speak in long, wandering sentences that always eventually arrive at a point. "
            "PERIOD ACCURACY: It is 1935. No computers, no televisions, no zip codes."
        ),
    },
    {
        "name": "Judge Sebastiano Marino",
        "location": "The Courthouse",
        "role": "Orleans Parish judge, Section K",
        "org": "Orleans Parish Judiciary",
        "org_role": "judge",
        "corruption": 7,
        "system_prompt": (
            "You are Judge Sebastiano Marino of the Orleans Parish Criminal Court, Section K, 1935. "
            "You are Italian-American, which cost you two election cycles before the Rossi family "
            "decided you were worth backing. You are aware of what that backing means and you are "
            "careful about it — you do not rule for Rossi interests directly, but you find reasons "
            "to suppress evidence, grant continuances, and set bail at manageable levels when asked. "
            "You tell yourself there is a line you have not crossed. You have crossed it. "
            "You are otherwise a competent, professional jurist who speaks precisely and rules clearly. "
            "PERIOD ACCURACY: It is 1935. No computers, no televisions, no zip codes."
        ),
    },
    {
        "name": "Magistrate Felix Moreau",
        "location": "The Courthouse",
        "role": "Orleans Parish magistrate",
        "org": "Orleans Parish Judiciary",
        "org_role": "magistrate",
        "corruption": 1,
        "system_prompt": (
            "You are Magistrate Felix Moreau of the Orleans Parish Criminal Court, 1935. "
            "You handle arraignments, preliminary hearings, bail determinations, and the thousand "
            "small procedural moments that happen before a case gets anywhere near a trial judge. "
            "You see more of the raw machinery of the system than anyone — the arrests at two in the morning, "
            "the defendants who don't understand what's happening, the paperwork that determines everything. "
            "You are neither corrupt nor idealistic. You are efficient. You process what comes before you "
            "with professional dispatch and go home. You have been doing this for sixteen years and "
            "you have learned not to ask questions that will only make your job harder. "
            "PERIOD ACCURACY: It is 1935. No computers, no televisions, no zip codes."
        ),
    },
    {
        "name": "Mayor Henri Delacroix",
        "location": "City Hall",
        "role": "Mayor of New Orleans",
        "org": "Orleans Parish Government",
        "org_role": "mayor",
        "corruption": 5,
        "system_prompt": (
            "You are Henri Delacroix, Mayor of New Orleans, 1935. "
            "You are a Long machine man, elevated by the governor's network and maintained by it. "
            "You are charming, relentlessly political, and genuinely believe that what is good for "
            "the machine is good for the city — these beliefs have become impossible to separate. "
            "You measure every conversation by what it costs and what it buys. "
            "A detective with a strong reputation is a useful tool. A detective causing problems for "
            "your allies is a problem to be managed. "
            "You never threaten directly. You offer things — future considerations, goodwill, "
            "the understanding that the city takes care of its own. "
            "You speak with the warmth of a man who has shaken ten thousand hands and remembers "
            "every name when it matters. "
            "PERIOD ACCURACY: It is 1935. No computers, no televisions, no zip codes."
        ),
    },
    {
        "name": "Sheriff Armand Trosclair",
        "location": "Sheriff's Office",
        "role": "Orleans Parish Sheriff",
        "org": "Orleans Parish Government",
        "org_role": "sheriff",
        "corruption": 3,
        "system_prompt": (
            "You are Armand Trosclair, Sheriff of Orleans Parish, 1935. "
            "You are an elected official, which means you answer to voters — specifically the ward bosses "
            "who deliver those voters. Your jurisdiction covers the parish jail and certain civil functions "
            "the city police don't touch. "
            "You are blunter than the mayor and less philosophical than the captain. "
            "You came up through the system the hard way and have the scars to show it. "
            "You have a genuine dislike of the crime families, which you manage carefully because "
            "dismantling them would require cooperation from people who have no interest in helping you. "
            "You respect detectives who do the work without making your life harder. "
            "You distrust detectives who come to you with problems that are going to end up in the papers. "
            "You speak plainly, with the occasional profanity, and mean what you say. "
            "PERIOD ACCURACY: It is 1935. No computers, no televisions, no zip codes."
        ),
    },
    {
        "name": "Don Enzo Rossi",
        "location": "Rossi's",
        "role": "boss of the Rossi crime family",
        "org": "Rossi Crime Family",
        "org_role": "don",
        "corruption": 8,
        "system_prompt": (
            "You are Don Enzo Rossi, head of the Rossi crime family in Noirleans, 1935. "
            "You are sixty-one years old, Sicilian-born, and have spent four decades building something "
            "you think of as an institution. You control French Quarter gambling, port labor rackets, "
            "and a network of relationships with the NOPD that you consider a business expense. "
            "You are courteous in the way that very dangerous men are courteous — because they have "
            "no need to be anything else. You do not threaten. You do not need to. "
            "You speak in careful, considered sentences. You often ask questions instead of making statements. "
            "You are interested in detectives the way a chess player is interested in a new piece on the board. "
            "You will share information when it serves you, withhold it when it doesn't, and lie smoothly when necessary. "
            "You call everyone by their last name until you have decided they are worth knowing. "
            "PERIOD ACCURACY: It is 1935. No computers, no televisions, no zip codes."
        ),
    },
    {
        "name": "Vincent Castellano",
        "location": "The Marigny Room",
        "role": "boss of the Castellano crime family",
        "org": "Castellano Crime Family",
        "org_role": "boss",
        "corruption": 7,
        "system_prompt": (
            "You are Vincent Castellano, head of the Castellano crime family in Noirleans, 1935. "
            "You are forty-seven, American-born, and consider yourself a businessman first. "
            "Your family controls narcotics and prostitution in the Back of Town and maintains an "
            "uneasy peace with the Rossis following a territorial settlement three years ago. "
            "Unlike the Rossis, you are willing to work with people outside the Italian community "
            "when it suits you. You are more flexible, more modern, and considerably more volatile "
            "than Enzo Rossi — a fact you consider an advantage and others consider a liability. "
            "You speak quickly, think visibly, and occasionally say more than you intended. "
            "You are charming when relaxed and cold when threatened, with very little in between. "
            "You distrust cops but you distrust unpredictability more — a reliable detective "
            "is something you can work with. "
            "PERIOD ACCURACY: It is 1935. No computers, no televisions, no zip codes."
        ),
    },
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
    {
        "name": "Dr. Randolph Frazier",
        "location": "City Morgue",
        "role": "coroner",
        "system_prompt": (
            "You are Dr. Randolph Frazier, city coroner of Noirleans, 1935. "
            "You have examined the dead of this city for nineteen years. "
            "You are precise, dry, and professionally detached — not because you don't care, "
            "but because caring too much gets in the way of accuracy. "
            "You speak in the clinical language of your trade. You state findings, not theories. "
            "You do not speculate about guilt — you describe what the body tells you. "
            "When a detective comes asking, you share your findings completely and accurately. "
            "You have seen everything. You are surprised by nothing. "
            "You will be given context about the current victim before each conversation — "
            "treat this as your official case file and answer from it. "
            "If you have no findings on a victim, say so plainly. "
            "PERIOD ACCURACY: It is 1935. No zip codes, no computers, no televisions, no credit cards."
        ),
    },
    {
        "name": "District Attorney Franklin Dupré",
        "location": "The DA's Office",
        "role": "District Attorney of Orleans Parish",
        "org": "Orleans Parish District Attorney",
        "org_role": "district attorney",
        "corruption": 3,
        "routine": [
            {"location": "The DA's Office", "time_start": "08:00", "time_end": "18:00"},
            {"location": "The Rusty Anchor", "time_start": "18:30", "time_end": "22:00"},
        ],
        "system_prompt": (
            "You are Franklin Dupré, District Attorney of Orleans Parish, 1935. "
            "You have held this office for seven years under the Long machine's patronage "
            "and you have learned to hold two things simultaneously: a genuine belief in the law "
            "and a clear-eyed understanding of which cases can be won and which should disappear. "
            "You are not a coward. You prosecute real crime when the evidence is solid "
            "and the victim isn't connected to someone who can hurt you. "
            "You are ambitious in the way of men who know exactly how far they can go "
            "and have decided that distance is enough. "
            "You speak carefully, in the measured language of someone who has spent years choosing words for judges. "
            "You have seen every kind of detective. You can tell within thirty seconds "
            "whether someone is bringing you a real case or a political problem. "
            "When you decline to prosecute, you make it sound like a procedural regret. "
            "You are always referred to as 'Mr. Dupré' or 'the DA' — never by first name. "
            "PERIOD ACCURACY: It is 1935. No computers, no televisions, no zip codes."
        ),
    },
    {
        "name": "Nadine Broussard",
        "location": "The Courthouse",
        "role": "courthouse records clerk",
        "org": "Orleans Parish Judiciary",
        "org_role": "clerk",
        "corruption": 1,
        "system_prompt": (
            "You are Nadine Broussard, the records clerk at the Orleans Parish Courthouse, 1935. "
            "You have worked this desk for fourteen years and have access to all public court records "
            "for Orleans Parish: bail bonds, arrest records, criminal histories, prior convictions, "
            "court filings, subpoenas, deposition transcripts, property liens, civil judgments, "
            "warrants served and outstanding — all of it. "
            "When a detective or attorney asks you about a person by name, you can look them up and "
            "report what the public record shows: prior arrests, charges, bail history, convictions, "
            "outstanding warrants, civil actions. If someone has a criminal history in Orleans Parish, "
            "you know about it. If they've skipped bail or have an outstanding bond, you know that too. "
            "You are efficient, polite, and thoroughly unimpressed by anyone who thinks their request "
            "is more urgent than anyone else's. "
            "You know which records are public and which require a signed order from a judge, "
            "and you enforce that distinction without apology. "
            "You are not a gossip, but you are not blind — you know who comes and goes and what "
            "they're looking for, and occasionally that information finds its way out in the right company. "
            "You speak in the brisk, no-nonsense manner of a woman who has been asked every possible "
            "question about courthouse records and has learned to answer in the fewest possible words. "
            "PERIOD ACCURACY: It is 1935. No computers, no televisions, no zip codes. "
            "Records are paper, filed in folders, stored in cabinets. You retrieve them yourself."
        ),
    },
    {
        "name": "Clarence Dufour",
        "location": "Treme Pawn & Loan",
        "role": "pawn shop proprietor",
        "org": "Treme Pawn & Loan",
        "org_role": "proprietor",
        "corruption": 0,
        "system_prompt": (
            "You are Clarence Dufour, Creole proprietor of Treme Pawn & Loan, 1935. "
            "You have run this shop since 1919 and you know what things are worth — to the penny. "
            "You ask no questions about where goods came from. You do not discuss your customers. "
            "When a detective comes in, you describe what's in stock and what it costs. "
            "If they want to buy something, they say so and you complete the sale. "
            "You carry: Camera ($12), Roll of Film ($2 each), Lockpick Set ($8), Binoculars ($15), "
            ".38 Revolver ($35), .38 Ammunition ($4 per box of 10 rounds), "
            "Bribe Envelope ($2 each), Disguise Kit ($18). "
            "Speak in the measured tones of someone who has learned that discretion is a business asset. "
            "You are not warm, but you are fair. "
            "PERIOD ACCURACY: It is 1935. No computers, no televisions, no zip codes."
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


_NOT_EVIDENCE_QUIPS = (
    "That's not evidence, it's not even a macguffin.",
    "We can't book a murderer on that.",
    "Put it back. That's furniture, not forensics.",
    "The DA would laugh us out of the building.",
    "I've seen stronger cases built on a napkin. A clean napkin.",
    "That's atmosphere, not evidence.",
    "File that under 'interesting, not useful.'",
    "That won't hold up in front of a jury. Or a magistrate. Or a reasonably attentive dog.",
)
_ALREADY_COLLECTED_QUIPS = (
    "Already bagged. Keep your eyes open for something new.",
    "We've got that one. Move on.",
    "It's in the evidence folder. Try to keep up.",
    "Already logged it. What else have you got?",
)


def _evidence_rejection_quip(companion_name: str, already_collected: bool,
                              reason: str | None = None,
                              matched_desc: str | None = None) -> None:
    import random
    if already_collected:
        if matched_desc:
            show_partner_aside(companion_name, f"We already have that — it's logged as: {matched_desc}")
        else:
            show_partner_aside(companion_name, random.choice(_ALREADY_COLLECTED_QUIPS))
    elif reason:
        show_partner_aside(companion_name, reason)
    else:
        show_partner_aside(companion_name, random.choice(_NOT_EVIDENCE_QUIPS))


_SLASH_COMMANDS = (
    "/locations", "/location", "/leads", "/evidence", "/suspects", "/add", "/status",
    "/help", "/dossier", "/who", "/romance", "/cases", "/drink", "/rep", "/me",
    "/go", "/visit", "/talk", "/look", "/examine", "/collect", "/pick", "/arrest", "/link",
    "/bribe", "/join", "/detain", "/release", "/holding",
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


def _create_replacement_npc(conn, llm, org_id: int, vacated_role: str, org_name: str) -> None:
    """Generate a new world-persistent NPC to fill a role vacated by succession."""
    import json as _json
    from noir.persistence.repository import add_organization_member as _add_member

    org_row = conn.execute(
        "SELECT name, type, description FROM organizations WHERE id=?", (org_id,)
    ).fetchone()
    if not org_row:
        return

    prompt = (
        f"Create a new character who fills the role of '{vacated_role}' in {org_row['name']}, "
        f"a {org_row['type']} organization in 1935 New Orleans.\n\n"
        f"Organization description: {org_row['description']}\n\n"
        "Generate a character appropriate to this organization and era. "
        "Return JSON only: "
        '{"name": "Full Name", "role": "brief role descriptor", '
        '"race": "white|black|creole|italian|etc", '
        '"personality": "2-sentence personality sketch", '
        '"system_prompt": "2-3 sentence in-character voice guide"}'
    )
    system = (
        "You are a character generator for a 1935 New Orleans noir detective game. "
        "Generate historically grounded characters appropriate to Depression-era Louisiana. "
        "Return ONLY valid JSON."
    )
    try:
        data = llm.query_structured(system, [], prompt)
    except Exception:
        return

    name = data.get("name", "").strip()
    role = data.get("role", vacated_role).strip()
    system_prompt = data.get("system_prompt", "").strip()
    if not name:
        return

    cursor = conn.execute(
        "INSERT INTO npcs (case_id, name, role, system_prompt) VALUES (NULL, ?, ?, ?)",
        (name, role, system_prompt or f"You are {name}, {role} of {org_name}.")
    )
    new_npc_id = cursor.lastrowid

    race = data.get("race", "")
    backstory = data.get("personality", "")
    conn.execute(
        """INSERT OR IGNORE INTO suspects (case_id, npc_id, race, backstory)
           VALUES (NULL, ?, ?, ?)""",
        (new_npc_id, race or None, backstory or None)
    )
    conn.commit()

    _add_member(conn, organization_id=org_id, member_type="npc",
                member_id=new_npc_id, role=vacated_role)


def _assign_npc_organizations(conn, llm, npc_id: int) -> None:
    """Assign org memberships to an NPC based on their profile. Runs in background."""
    from noir.persistence.repository import (
        get_npc as _get_npc, get_all_organizations as _get_orgs,
        add_organization_member as _add_member,
        get_or_create_family_org as _get_family,
        get_organizations_for_npc as _get_npc_orgs,
    )
    npc = _get_npc(conn, npc_id)
    if not npc:
        return
    # Skip if already assigned
    existing = _get_npc_orgs(conn, npc_id)
    if existing:
        return

    suspect_row = conn.execute(
        "SELECT race, political_connections, backstory FROM suspects WHERE npc_id=?", (npc_id,)
    ).fetchone()
    race = suspect_row["race"] if suspect_row else ""
    political = suspect_row["political_connections"] if suspect_row else ""
    backstory = suspect_row["backstory"] if suspect_row else ""

    orgs = _get_orgs(conn)
    org_list = "\n".join(
        f"- id={o['id']}: {o['name']} ({o['type']}, influence {o['influence']}): {o['description'][:120]}"
        for o in orgs
    )

    result = llm.query_structured(
        "You are assigning organization memberships to an NPC in a 1935 noir game. "
        "Based on the NPC's profile, determine which organizations they plausibly belong to. "
        "Most NPCs belong to 0-2 organizations. A poor Black dockworker won't be in the country club. "
        "A mob enforcer won't be in city government. Be realistic for 1935 New Orleans. "
        "Return ONLY valid JSON: {\"memberships\": [{\"org_id\": int, \"role\": \"string\"}]}",
        [],
        f"NPC: {npc['name']}, role: {npc['role']}\n"
        f"Race: {race or 'unknown'}, political connections: {political or 'none'}\n"
        f"Backstory: {backstory or 'unknown'}\n\n"
        f"Available organizations:\n{org_list}"
    )

    for m in result.get("memberships", []):
        org_id = m.get("org_id")
        role = m.get("role", "member")
        if org_id:
            _add_member(conn, organization_id=org_id, member_type="npc",
                        member_id=npc_id, role=role)

    # Auto-assign personal family org based on surname
    name_parts = npc["name"].strip().split()
    if len(name_parts) >= 2:
        surname = name_parts[-1]
        if len(surname) > 2:
            family_org_id = _get_family(conn, surname)
            _add_member(conn, organization_id=family_org_id, member_type="npc",
                        member_id=npc_id, role="family member")


ORG_ELIGIBILITY: dict[str, dict] = {
    "New Orleans Athletic Club": {
        "race": ["white"],
        "gender": ["male"],
        "min_rep": 40,
        "rejection": "The doorman looks at you and looks away. You are not the kind of person they invite.",
    },
    "Knights of Columbus": {
        "gender": ["male"],
        "rejection": "The Knights are a fraternal order for Catholic men. That door isn't open to you.",
    },
    "Treme Social Aid and Pleasure Club": {
        "race": ["black", "creole"],
        "rejection": "The club is community. You're not part of this community.",
    },
    "Colored Longshoremen's Association": {
        "race": ["black", "creole"],
        "rejection": "The CLA is for Black dockworkers. That's not you.",
    },
    "Rossi Crime Family": {
        "min_chaos": 10,
        "rejection": "The Rossi family has no use for someone who plays by the rules.",
    },
    "Castellano Crime Family": {
        "min_chaos": 5,
        "rejection": "Castellano needs people who are willing to get their hands dirty. You're too clean.",
    },
    "International Longshoremen's Association Local 231": {
        "tags": ["dockworker", "union", "labor"],
        "rejection": "The ILA is for dock workers. Get a union card first.",
    },
    "Orleans Parish Judiciary": {
        "rejection": "Judgeships are appointed, not applied for.",
    },
    "Louisiana State Government": {
        "rejection": "State office requires election or appointment. Not a walk-in.",
    },
}


def check_org_eligibility(
    conn,
    org_name: str,
    player: dict,
    eligibility: dict | None = None,
) -> str | None:
    """Return a rejection message if the player fails hard eligibility gates, else None."""
    if eligibility is None:
        eligibility = ORG_ELIGIBILITY
    gates = eligibility.get(org_name)
    if not gates:
        return None

    if set(gates.keys()) == {"rejection"}:
        return gates["rejection"]

    race = (player.get("race") or "unspecified").lower()
    gender = (player.get("gender") or "unspecified").lower()
    law_chaos = player.get("law_chaos") or 0
    rep = player.get("reputation") or 100

    if "race" in gates and race not in [r.lower() for r in gates["race"]]:
        return gates.get("rejection", "They don't take your kind.")
    if "gender" in gates and gender not in [g.lower() for g in gates["gender"]]:
        return gates.get("rejection", "They don't take your kind.")
    if "min_chaos" in gates and law_chaos < gates["min_chaos"]:
        return gates.get("rejection", "You're too straight for this outfit.")
    if "max_chaos" in gates and law_chaos > gates["max_chaos"]:
        return gates.get("rejection", "You're too wild for this outfit.")
    if "min_rep" in gates and rep < gates["min_rep"]:
        return gates.get("rejection", "Your reputation isn't good enough.")
    if "tags" in gates:
        from noir.persistence.repository import get_street_reputation as _get_rep
        rep_data = _get_rep(conn)
        player_tags = [t.lower() for t in rep_data.get("tags", [])]
        if not any(t in player_tags for t in [x.lower() for x in gates["tags"]]):
            return gates.get("rejection", "You don't have the right background.")
    return None


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
        self._pending_slash: str | None = None
        self._pending_gen_thread: threading.Thread | None = None
        self._recent_partner_lines: list[str] = []

    def _set_active_case(self, case_id: int | None) -> None:
        self.active_case_id = case_id
        if self.companion is not None:
            self.companion.case_id = case_id

    def setup_fixed_locations(self) -> dict[str, int]:
        from noir.organizations import seed_location_org_links
        existing = {loc["name"]: loc["id"] for loc in get_fixed_locations(self.conn)}
        result = {}
        for name, desc in FIXED_LOCATIONS:
            if name not in existing:
                loc_id = create_location(self.conn, name=name, description=desc, is_fixed=True)
            else:
                loc_id = existing[name]
            result[name] = loc_id
        seed_location_org_links(self.conn)
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
        from noir.characters.npc_archetype_loader import get_npc_archetype
        loc_map = {}
        for loc in case_data.get("locations", []):
            loc_name = loc["name"] if isinstance(loc, dict) else loc
            desc = get_seeded_location_description(self.conn, loc_name) or "A location in Noirleans."
            loc_id = create_location(self.conn, name=loc_name, description=desc,
                                     is_fixed=False, case_id=case_id)
            loc_map[loc_name] = loc_id
            if isinstance(loc, dict):
                for org_name in loc.get("organizations", []):
                    org_row = self.conn.execute(
                        "SELECT id FROM organizations WHERE name=?", (org_name,)
                    ).fetchone()
                    if org_row:
                        self.conn.execute(
                            "INSERT OR IGNORE INTO location_organizations (location_id, organization_id) VALUES (?, ?)",
                            (loc_id, org_row["id"])
                        )
        self.conn.commit()

        found_at = case_data.get("victim", {}).get("found_at", "").lower()
        # Auto-discover only the crime scene; all other case locations start hidden
        for loc_name, loc_id in loc_map.items():
            if loc_name.lower() == found_at:
                self.conn.execute("UPDATE locations SET discovered=1 WHERE id=?", (loc_id,))
        self.conn.commit()
        npc_locs = {k: v for k, v in loc_map.items() if k.lower() != found_at} or loc_map

        for suspect in case_data.get("suspects", []):
            loc_name = random.choice(list(npc_locs.keys())) if npc_locs else None
            loc_id = npc_locs.get(loc_name) or next(iter(fixed.values()))

            archetype = get_npc_archetype(suspect.get("archetype_id", "world_weary_barkeep"))
            personality = archetype["personality"] if archetype else "Reserved and watchful"
            speech_style = archetype["speech_style"] if archetype else "Short, careful sentences"

            npc_system_prompt = _build_npc_system_prompt(
                name=suspect["name"],
                role=suspect["role"],
                race=suspect.get("race", ""),
                political_connections=suspect.get("political_connections", ""),
                alibi=suspect.get("alibi", ""),
                secret=suspect.get("secret", ""),
                relationships_json=json.dumps(suspect.get("relationships", [])),
                personality=personality,
                speech_style=speech_style,
                backstory="",  # phase 2 will update this
            )
            npc_id = create_npc(
                self.conn, case_id=case_id, name=suspect["name"],
                role=suspect["role"], system_prompt=npc_system_prompt,
                current_location_id=loc_id,
                alignment=suspect.get("alignment", "True Neutral"),
                age=suspect.get("age", 35),
                pressure_tolerance=suspect.get("pressure_tolerance", 5),
                kindness_weight=suspect.get("kindness_weight", 5),
                empathy=suspect.get("empathy", 5),
                starting_guilt=suspect.get("starting_guilt", 0),
                revelation_style=suspect.get("revelation_style", "staged"),
                revelation_stages=suspect.get("revelation_stages", 3),
                maiden_name=suspect.get("maiden_name") or None,
                physical_description=suspect.get("physical_description") or None,
                sex=suspect.get("sex") or None,
            )
            set_character_location(self.conn, character_id=f"npc_{npc_id}", location_id=loc_id)
            initialize_npc_relationship(self.conn, npc_id, suspect.get("starting_guilt", 0))
            is_killer = suspect["name"].lower() == case_data.get("killer_name", "").lower()
            create_suspect(self.conn, case_id=case_id, npc_id=npc_id, is_killer=is_killer,
                           race=suspect.get("race"),
                           political_connections=suspect.get("political_connections"),
                           alibi=suspect.get("alibi"),
                           secret=suspect.get("secret"),
                           backstory=None,
                           relationships=json.dumps(suspect.get("relationships", [])),
                           archetype_id=suspect.get("archetype_id"))
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

    def _start_background_enrichment(self, case_id: int) -> None:
        from noir.mystery.generator import enrich_npc
        npcs = self.conn.execute(
            "SELECT id FROM npcs WHERE case_id=?", (case_id,)
        ).fetchall()
        npc_ids = [row["id"] for row in npcs]
        bg_llm = copy.copy(self.llm)
        if hasattr(bg_llm, 'suppress_status'):
            bg_llm.suppress_status = True

        def _enrich_all() -> None:
            from noir.persistence.db import get_connection as _gc
            bg_conn = _gc()
            try:
                for npc_id in npc_ids:
                    try:
                        enrich_npc(bg_conn, bg_llm, npc_id)
                    except Exception:
                        pass
                    try:
                        _assign_npc_organizations(bg_conn, bg_llm, npc_id)
                    except Exception:
                        pass
            finally:
                bg_conn.close()

        t = threading.Thread(target=_enrich_all, daemon=True)
        t.start()

    def _put_active_on_hold(self) -> None:
        """Put the currently active case/job on hold before activating a new one."""
        if self.active_case_id:
            self.conn.execute(
                "UPDATE cases SET status='on_hold' WHERE id=? AND status='active'",
                (self.active_case_id,)
            )
            self.conn.commit()
            self.active_case_id = None
            self.case_manager = None
            self.world = None
        self.conn.execute(
            "UPDATE cases SET status='on_hold' WHERE case_type='job' AND status='active'"
        )
        self.conn.commit()

    def _resume_on_hold(self) -> None:
        """After closing a job, resume the most recent on-hold case or job."""
        row = self.conn.execute(
            "SELECT * FROM cases WHERE status='on_hold' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return
        self.conn.execute("UPDATE cases SET status='active' WHERE id=?", (row["id"],))
        self.conn.commit()
        if row["case_type"] != "job":
            self._set_active_case(row["id"])
            self._seed_fixed_npcs(row["id"])
            self.world = World(conn=self.conn, active_case_id=row["id"])
            self.case_manager = CaseManager(conn=self.conn, case_id=row["id"], llm=self.llm)
            console.print(f"[dim]Back on the case.[/dim]")

    def _replenish_job_board(self) -> None:
        """Ensure at least 2 pending tier-1 jobs per faction on the board.

        Tier 2+ jobs are NPC-only — they never appear on the board.
        """
        from noir.jobs.generator import JobGenerator
        from noir.jobs.factions import ALL_FACTION_SLUGS
        gen = JobGenerator(self.llm, self.conn)
        for faction in ALL_FACTION_SLUGS:
            existing = self.conn.execute(
                "SELECT COUNT(*) FROM cases WHERE case_type='job' AND status='pending' "
                "AND faction=? AND tier=1",
                (faction,)
            ).fetchone()[0]
            if existing < 1:
                for job in gen.generate_board(faction=faction, tier=1,
                                               count=1):
                    create_job(
                        self.conn,
                        faction=job["faction"],
                        tier=job["tier"],
                        title=job["title"],
                        payout=job["payout"],
                        case_data=job["case_data"],
                    )

    def start_new_case(self) -> None:
        import noir.audio as audio
        audio.flush()
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
        self._set_active_case(case_id)

        self._seed_case_locations_and_npcs(case_id, case_data, fixed)
        self._seed_fixed_npcs(case_id)
        self._start_background_enrichment(case_id)

        console.print(f"\n[bold red]NEW CASE: {case_data['title']}[/bold red]")
        console.print(
            f"[italic]Victim: {case_data['victim']['name']} — "
            f"{case_data['victim']['cause_of_death']}[/italic]\n"
        )

        if self.companion:
            victim = case_data.get("victim", {})
            crime_scene = victim.get("found_at", "the crime scene")
            brief_prompt = (
                f"A new case has just come in. Brief your detective partner on what you know so far. "
                f"Case: {case_data['title']}. "
                f"Victim: {victim.get('name', 'Unknown')}, cause of death: {victim.get('cause_of_death', 'unknown')}. "
                f"The body was found at: {crime_scene}. "
                f"Physical setting: you are both INSIDE The Precinct, at the detective's desk. Indoors. No cars. "
                f"Do NOT name any suspects or other locations — the detective needs to discover those. "
                f"Strongly imply the crime scene should be the first stop. "
                f"Stay physically grounded in the precinct. Stay in character. 2-3 sentences."
            )
            show_dialogue(self.companion.name, self.companion.narrate(brief_prompt))

    def handle_map(self) -> None:
        from noir.neighborhoods import recompute_all_danger
        from noir.persistence.repository import get_neighborhood_for_location

        recompute_all_danger(self.conn)

        current_slug = "french_quarter"
        if self.current_location_id is not None:
            hood = get_neighborhood_for_location(self.conn, self.current_location_id)
            if hood:
                current_slug = hood["slug"]

        markers: dict[str, list[str]] = {}

        import sys
        rendered = render_map(self.conn, current_slug, markers)
        sys.stdout.write('\n')
        sys.stdout.write(rendered)
        sys.stdout.write('\n')
        sys.stdout.flush()
        console.print(FACTION_LEGEND)
        console.print(MARKER_LEGEND)
        console.print()

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
        if loc["case_id"] is not None and not loc["discovered"]:
            console.print(f"[red]'{target}' doesn't ring any bells. Try somewhere else.[/red]")
            return
        _prev_location_id = self.current_location_id
        self.current_location_id = loc["id"]
        set_character_location(self.conn, character_id="player", location_id=loc["id"])
        _travel_delta = 30  # default: same neighborhood or no adjacency data
        from noir.persistence.repository import get_neighborhood_for_location as _get_hood
        _dest_hood = _get_hood(self.conn, loc["id"])
        if _dest_hood and _prev_location_id is not None:
            _orig_hood = _get_hood(self.conn, _prev_location_id)
            if _orig_hood and _orig_hood["slug"] != _dest_hood["slug"]:
                from noir.neighborhoods import travel_time_minutes, is_algiers_crossing
                from noir.persistence.repository import get_travel_distance
                _dist = get_travel_distance(self.conn, _orig_hood["slug"], _dest_hood["slug"])
                if _dist is not None:
                    _ferry = is_algiers_crossing(_orig_hood["slug"], _dest_hood["slug"])
                    _travel_delta = travel_time_minutes(distance=_dist, is_ferry=_ferry)
        advance_game_time(self.conn, delta=_travel_delta)
        npcs = self.world.get_npcs_at(loc["id"])
        npc_names = [_npc_display_name(npc) for npc in npcs]

        if self.companion:
            import json as _json
            body_note = "The victim's body has been taken to the City Morgue."
            if self.active_case_id:
                case = get_case(self.conn, self.active_case_id)
                if case:
                    cd = _json.loads(case["case_data"])
                    victim = cd.get("victim", {})
                    found_at = victim.get("found_at")
                    body_loc = cd.get("body_location", "City Morgue")
                    if body_loc == "crime scene" and found_at and loc["name"].lower() == found_at.lower():
                        body_note = f"The body of {victim.get('name', 'the victim')} is still here."
                    elif found_at:
                        body_note = f"The victim's body was found here and has been taken to the City Morgue."
            if npc_names:
                npc_hint = f" People present: {', '.join(npc_names)}. ONLY mention people from this list — do not invent or describe anyone else."
            else:
                npc_hint = " No one else is here."
            arrival_prompt = (
                f"[Physical setting: you are both INSIDE {loc['name']}. {loc['description']}"
                f"{npc_hint} {body_note}] "
                f"You've just arrived. Notice one specific, concrete detail about the space — something unexpected, "
                f"not a generic mood-setter. Hint at what might be worth examining or who to talk to. "
                f"One or two sentences, in character. "
                f"Do NOT use 'the kind of X that' or 'the sort of X that' constructions."
            )
            self.llm.suppress_status = True
            with travel_status():
                arrival = self.companion.narrate(arrival_prompt)
            self.llm.suppress_status = False
            loc_orgs = [r["name"] for r in get_organizations_for_location(self.conn, loc["id"])]
            import noir.audio as audio
            audio.flush()
            show_travel_animation()
            show_location_rule()
            show_location(loc["name"], loc["description"], npc_names,
                          game_time=get_game_time(self.conn), orgs=loc_orgs)
        else:
            loc_orgs = [r["name"] for r in get_organizations_for_location(self.conn, loc["id"])]
            import noir.audio as audio
            audio.flush()
            show_travel_animation()
            show_location_rule()
            show_location(loc["name"], loc["description"], npc_names,
                          game_time=get_game_time(self.conn), orgs=loc_orgs)
            arrival = None
        if loc["name"] == "The Precinct" and self.companion and self.active_case_id:
            held = get_detained_npcs(self.conn, self.active_case_id)
            if held:
                held_names = [n["name"] for n in held]
                dossier = get_all_dossier(self.conn, case_id=self.active_case_id)
                held_facts = []
                for n in held:
                    facts = dossier.get(n["name"], [])
                    held_facts.append(f"{n['name']}: {'; '.join(facts[:3]) if facts else 'nothing yet'}")
                strategy_prompt = (
                    f"[You're back at The Precinct. You have {len(held)} suspect(s) in separate holding rooms: "
                    f"{', '.join(held_names)}. "
                    f"What you know about each: {' | '.join(held_facts)}. "
                    f"Before the detective goes in, give a brief strategy note — who to press first, "
                    f"whether to play them against each other, what angle to take. "
                    f"One or two sentences. In character.]"
                )
                strategy = self.companion.narrate(strategy_prompt)
                show_partner_aside(self.companion.name, strategy)
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
        self._check_faction_tension()

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
        if npc_row is not None and self.world is not None:
            if npc_row["detained"]:
                precinct_row = self.conn.execute(
                    "SELECT id FROM locations WHERE name='The Precinct'"
                ).fetchone()
                if not precinct_row or self.current_location_id != precinct_row["id"]:
                    console.print(f"[dim]{npc_row['name']} is in holding at The Precinct.[/dim]")
                    return
            else:
                all_locs = self.world.list_locations()
                loc_name_to_id = {loc["name"]: loc["id"] for loc in all_locs}
                game_time = get_game_time(self.conn)
                resolved_loc_id = self.world._resolve_npc_location_id(npc_row, game_time, loc_name_to_id)
                if resolved_loc_id != self.current_location_id:
                    loc = get_location(self.conn, resolved_loc_id) if resolved_loc_id else None
                    where = f" They're at {loc['name']}." if loc else ""
                    console.print(f"[dim]{npc_row['name']} isn't here.{where}[/dim]")
                    return
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
                        self.handle_go("The DA's Office")
                    elif new_target != target.lower().strip():
                        self.handle_talk(result.get("target") or target)
            else:
                console.print(f"[red]Can't find '{target}' around here.[/red]")
            return
        mark_suspect_met(self.conn, npc_id=npc_row["id"])
        if self.current_location_id and not npc_row["detained"]:
            set_character_location(self.conn, character_id=f"npc_{npc_row['id']}",
                                   location_id=self.current_location_id)
        npc = NPC.load(
            conn=self.conn,
            llm=self.llm,
            npc_id=npc_row["id"],
            case_id=self.active_case_id,
        )
        import noir.audio as audio
        audio.register_voice(
            npc_row["name"],
            _infer_npc_voice(npc_row, conn=self.conn),
        )
        others_ctx = self._copresent_npc_context(npc_row["id"])
        loc_ctx = ""
        if self.current_location_id:
            loc = get_location(self.conn, self.current_location_id)
            if loc:
                loc_ctx = f"[You are currently at {loc['name']}. {loc['description']} Stay grounded in this location.] "
        if self.active_case_id:
            import json as _j
            case = get_case(self.conn, self.active_case_id)
            if case:
                cd = _j.loads(case["case_data"])
                victim = cd.get("victim", {})
                loc_ctx += (
                    f"[ACTIVE CASE the detective is working: \"{case['title']}\" — "
                    f"victim: {victim.get('name', 'Unknown')}, "
                    f"cause of death: {victim.get('cause_of_death', 'unknown')}, "
                    f"found at: {victim.get('found_at', 'unknown')}. "
                    f"When the detective asks about this case or this victim, respond with knowledge relevant to this investigation.] "
                )
                if "district attorney" in (npc_row["role"] or "").lower() and self.case_manager:
                    ev_summary = self.case_manager.get_evidence_summary()
                    suspects_row = self.conn.execute(
                        "SELECT n.name, s.is_killer FROM suspects s JOIN npcs n ON s.npc_id=n.id WHERE s.case_id=?",
                        (self.active_case_id,)
                    ).fetchall()
                    suspect_names = ", ".join(
                        f"{r['name']}{'*' if r['is_killer'] else ''}" for r in suspects_row
                    ) if suspects_row else "none identified"
                    loc_ctx += (
                        f"[CASE EVIDENCE FILE — what has been collected so far: {ev_summary or 'nothing collected yet'}. "
                        f"Suspects on record: {suspect_names}. "
                        f"You are the DA — evaluate this evidence like a prosecutor deciding whether it will hold up in court.] "
                    )
                if npc_row["name"] == "Dr. Randolph Frazier":
                    body_loc = cd.get("body_location", "City Morgue")
                    body_clues = cd.get("body_clues", [])
                    clue_text = (
                        f" Body findings: {'; '.join(body_clues)}."
                        if body_clues else " No forensic findings beyond cause of death."
                    )
                    loc_ctx += (
                        f"[FORENSIC DETAIL — body at: {body_loc}.{clue_text}] "
                    )
        _npc_role_lower = (npc_row["role"] or "").lower()
        if "judge" in _npc_role_lower or "magistrate" in _npc_role_lower:
            import json as _jj
            judge_cases = self.conn.execute(
                "SELECT id, title, status, trial_outcome FROM cases WHERE assigned_judge_id=? ORDER BY id",
                (npc_row["id"],)
            ).fetchall()
            if judge_cases:
                case_summaries = []
                for jc in judge_cases:
                    if jc["trial_outcome"]:
                        outcome_data = _jj.loads(jc["trial_outcome"])
                        outcome = outcome_data.get("outcome", "unknown")
                        brief = outcome_data.get("summary", "")[:200]
                        case_summaries.append(f'"{jc["title"]}" — {outcome}: {brief}')
                    else:
                        case_summaries.append(f'"{jc["title"]}" — {jc["status"]}')
                loc_ctx += (
                    f"[YOUR JUDICIAL RECORD — cases you have presided over or are currently handling: "
                    + " | ".join(case_summaries) + "] "
                )
            if "magistrate" in _npc_role_lower:
                pending = self.conn.execute(
                    "SELECT id, title FROM cases WHERE status='pending_magistrate' ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if pending:
                    loc_ctx += (
                        f"[A case is currently awaiting your review for trial clearance: \"{pending['title']}\"] "
                    )
        if npc_row["detained"] and self.active_case_id:
            other_held = [n for n in get_detained_npcs(self.conn, self.active_case_id)
                          if n["id"] != npc_row["id"]]
            if other_held:
                dossier = get_all_dossier(self.conn, case_id=self.active_case_id)
                other_summaries = []
                for on in other_held:
                    facts = dossier.get(on["name"], [])
                    summary = "; ".join(facts[:3]) if facts else "nothing on record"
                    other_summaries.append(f"{on['name']}: {summary}")
                loc_ctx += (
                    f"[INTERROGATION ROOM — you are in a holding room at The Precinct. "
                    f"The detective can confront you with what others in holding have said. "
                    f"Other suspects currently detained: {' | '.join(other_summaries)}. "
                    f"You do not know exactly what the others have said, but you know they are here and talking.] "
                )
            else:
                loc_ctx += (
                    "[INTERROGATION ROOM — you are in a holding room at The Precinct. "
                    "You are alone here. The detective has brought you in for formal questioning.] "
                )
        show_conversation_header(npc_row["name"])
        _is_da = "district attorney" in (npc_row["role"] or "").lower()
        if _is_da and self.active_case_id and self.case_manager:
            current_case = get_case(self.conn, self.active_case_id)
            if current_case and current_case["status"] not in ("closed", "in_trial"):
                console.print("[dim]submit · new · drop  — or just talk[/dim]\n")
        while True:
            _rel_stage = _affection_to_stage(
                get_npc_affection(self.conn, npc_row["id"])
            ) if get_npc_affection(self.conn, npc_row["id"]) > 0 else None
            try:
                player_input = npc_input_prompt(
                    npc_name=npc_row["name"],
                    role=npc_row["role"],
                    rel_stage=_rel_stage,
                )
            except (EOFError, KeyboardInterrupt):
                break
            if not player_input.strip():
                continue
            if player_input.strip().startswith("!"):
                self._handle_feedback(player_input.strip())
                continue
            if player_input.strip().startswith("/"):
                if _is_exit(player_input):
                    break
                slug = player_input.strip().split()[0].lower()
                if slug in ("/go", "/visit", "/talk"):
                    self._pending_slash = player_input.strip()
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
            if cmd.intent == Intent.COLLECT:
                if self.current_location_id and self.case_manager:
                    result = self.case_manager.validate_and_collect(
                        description=cmd.target,
                        location_id=self.current_location_id,
                        source_npc_id=npc_row["id"],
                    )
                    if result["ok"]:
                        show_evidence_collected(result["description"])
                    elif self.companion:
                        _evidence_rejection_quip(self.companion.name, "Already collected" in result["message"], result.get("reason"), result.get("matched_desc"))
                continue
            if _is_da and player_input.strip().lower() in ("submit", "new", "drop"):
                show_conversation_footer(npc_row["name"])
                self.handle_da()
                return
            show_player_turn(player_input)
            state_ctx = self._player_state_context()
            identity_ctx = self._player_identity_context()
            rel_ctx = self._npc_relationship_context(npc_row["id"])
            rep_ctx = self._street_rep_context()
            org_ctx = self._npc_org_context(npc_row["id"])
            rev_summary = get_npc_revelation_summary(self.conn, npc_row["id"])
            rev_ctx = (
                f"[Earlier in this conversation you already admitted: \"{rev_summary}\". "
                f"This is part of your history with this detective — do not forget or contradict it.] "
            ) if rev_summary else ""
            if _is_da:
                from noir.cases.trial import _JUDGE_TRAITS as _JT
                _jlines = [f"{n}: {t}" for n, t in _JT.items()]
                _assigned_jctx = self._judge_context(player_input)
                judge_ctx = f"[Orleans Parish bench — all judges are judicial officers, not police: {'; | '.join(_jlines)}. {_assigned_jctx}] "
            else:
                judge_ctx = ""
            ctx = loc_ctx + identity_ctx + (state_ctx or "") + (others_ctx or "") + rel_ctx + rep_ctx + org_ctx + rev_ctx + judge_ctx
            psychology = get_npc_psychology(self.conn, npc_row["id"])
            events = classify_events(self.llm, player_input, "")
            update_npc_state(self.conn, npc_row["id"], events, psychology)
            psychology = get_npc_psychology(self.conn, npc_row["id"])
            revelation_prompt = _check_npc_revelation(
                self.conn, self.llm, npc_row["id"], self.active_case_id,
                npc_row["name"], events, psychology, player_input=player_input
            )
            speak_input = ctx + player_input
            if revelation_prompt:
                speak_input = speak_input + "\n\n" + revelation_prompt
            response = npc.speak(speak_input, store_as=player_input)
            show_dialogue(npc_row["name"], response)
            if self.companion and self._should_partner_interject(player_input, response, "success"):
                interject_ctx = self._partner_interject_context(player_input, npc_row["name"], response, "success")
                interject_response = self.companion.speak(interject_ctx, store_as=f"[You observed the detective speaking with {npc_row['name']} and added:]", query=response)
                show_dialogue(self.companion.name, interject_response)
                partner_line = f"[{self.companion.name} says: {interject_response}]"
                npc_reply = npc.speak(partner_line, store_as=partner_line)
                show_dialogue(npc_row["name"], npc_reply)
            if revelation_prompt and "already admitted" in revelation_prompt:
                # Restatement turn — NPC was forced to say it plainly, store this version
                set_npc_revelation_summary(self.conn, npc_row["id"], response[:500])
            advance_game_time(self.conn, delta=5)
            self._check_npc_bribe_offer(npc_row, response)
            self._check_npc_job_offer(npc_row, response)
            self._check_job_completion(npc_row, response)
            self._check_npc_appointment(npc_row["id"], npc_row["name"], player_input, response)
            self._check_npc_romance_milestone(npc_row["id"], npc)
            # Re-classify events with the actual response now that it's available
            events = classify_events(self.llm, player_input, response)
            update_npc_state(self.conn, npc_row["id"], events, psychology)
        show_conversation_footer(npc_row["name"])
        if self.current_location_id is not None:
            self._observations.setdefault(self.current_location_id, []).append(
                f"spoke with {npc_row['name']} ({npc_row['role']})"
            )
        # Summarize conversation — persist cross-case for fixed NPCs, apply affection delta for all
        hist = get_history(self.conn, character_id=f"npc_{npc_row['id']}", case_id=self.active_case_id)
        is_fixed = npc_row["case_id"] is None
        summary_result = npc.summarize_and_save(hist, persist=is_fixed)
        affection_delta = summary_result["affection_delta"]
        if affection_delta:
            increment_npc_affection(self.conn, npc_row["id"], affection_delta)
            self._check_npc_romance_milestone(npc_row["id"], npc)
        xp_awards = summary_result.get("xp_awards", {})
        if xp_awards:
            self._apply_skill_xp_and_check_unlocks("player", xp_awards)
        self._extract_dossier_facts(npc_row["name"], npc_row["id"])
        case_status = get_case(self.conn, self.active_case_id)["status"] if self.active_case_id else None
        if case_status not in ("pending_magistrate", "in_trial"):
            self._extract_leads(npc_row["name"], npc_row["id"])
        # Discover the NPC's home location — the player now knows where to find them
        if npc_row["current_location_id"] and self.active_case_id:
            discover_location(self.conn, npc_row["current_location_id"])
        # Execute any /go or /talk command the player issued mid-conversation
        if self._pending_slash:
            cmd = self._pending_slash
            self._pending_slash = None
            self._dispatch_slash(cmd)

    def _apply_skill_xp_and_check_unlocks(self, owner: str, xp_awards: dict,
                                            partner_name: str | None = None) -> None:
        from noir.characters.skills import apply_conversation_xp, maybe_generate_specialization
        player = get_player(self.conn)
        if not player:
            return
        law_chaos = player["law_chaos"]
        good_evil = player["good_evil"]
        level_changes = apply_conversation_xp(
            self.conn, owner=owner, xp_awards=xp_awards,
            law_chaos=law_chaos, good_evil=good_evil,
            case_id=self.active_case_id,
        )
        for root, (old_level, new_level) in level_changes.items():
            if new_level == old_level:
                continue
            spec = maybe_generate_specialization(
                self.llm, self.conn, owner=owner, root=root,
                law_chaos=law_chaos, good_evil=good_evil,
            )
            if spec and self.companion and owner == "player":
                aside = self.companion.narrate(
                    f"[The detective has just gotten noticeably better at something — "
                    f"specifically: {spec['name']} ({root}). "
                    f"Say one quiet, in-character thing about it. One sentence.]"
                )
                show_partner_aside(self.companion.name, aside)
            elif spec and owner == "partner" and partner_name:
                show_partner_aside(partner_name, "You're getting good at that.")

    def _should_partner_interject(self, player_input: str, npc_response: str,
                                   outcome: str) -> bool:
        import random
        if not self.companion:
            return False
        if outcome == "backfire":
            return True
        uncertainty_words = [
            "don't know", "not sure", "maybe", "i suppose",
            "could be", "might have", "i think", "possibly",
        ]
        has_opening = any(w in npc_response.lower() for w in uncertainty_words)
        if has_opening:
            return random.random() < 0.55
        return random.random() < 0.12

    def _partner_interject_context(self, player_input: str, npc_name: str,
                                    npc_response: str, outcome: str) -> str:
        approach_note = {
            "backfire": f"The detective's approach with {npc_name} just backfired. Cover for them or redirect.",
            "success": f"{npc_name} is opening up. Reinforce it or press on a specific thing they said.",
        }.get(outcome, f"There's an opening in what {npc_name} just said. Use it.")
        return (
            f"[You are in a conversation with {npc_name}. "
            f"The detective just said: \"{player_input[:200]}\". "
            f"{npc_name} responded: \"{npc_response[:300]}\". "
            f"{approach_note} "
            f"One sentence, in character. React to what {npc_name} actually said — "
            f"do not claim they were interrupted or left mid-sentence. Do not explain what you're doing — just do it.]"
        )

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
                found_at = victim.get("found_at")
                body_loc = cd.get("body_location", "City Morgue")
                if body_loc == "crime scene" and found_at:
                    body_note = f"Body is still at the crime scene ({found_at}) — not yet removed."
                elif found_at:
                    body_note = f"Body was found at {found_at} and has been taken to the City Morgue."
                else:
                    body_note = "The victim's body has been taken to the City Morgue."
                met_names = {
                    row["name"] for row in self.conn.execute(
                        "SELECT n.name FROM suspects s JOIN npcs n ON s.npc_id=n.id "
                        "WHERE s.case_id=? AND s.met=1", (self.active_case_id,)
                    ).fetchall()
                }
                suspect_notes = []
                for s in cd.get("suspects", []):
                    if s["name"] not in met_names:
                        continue
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
                    f" Suspects you've met: {', '.join(suspect_notes)}."
                    if suspect_notes else ""
                )
                trial_statuses = ("pending_magistrate", "in_trial")
                if case["status"] in trial_statuses:
                    status_label = "awaiting the magistrate's assignment" if case["status"] == "pending_magistrate" else "currently in trial"
                    context_parts.append(
                        f"Active case: {case['title']} — {status_label}. "
                        f"The case is in the hands of the court. Do NOT press the detective to follow up on leads, "
                        f"interview suspects, or collect evidence. The investigation is closed. "
                        f"You may mention that they should check on the trial at the courthouse, but nothing more."
                    )
                else:
                    discovered_locs = [
                        l["name"] for l in get_discovered_locations_for_case(self.conn, self.active_case_id)
                    ]
                    locs_str = (f" Known locations (use these EXACT names): {', '.join(discovered_locs)}."
                                if discovered_locs else "")
                    context_parts.append(
                        f"Active case: {case['title']}. "
                        f"Victim: {victim.get('name', '?')}, "
                        f"cause of death: {victim.get('cause_of_death', '?')}. "
                        f"{body_note}{suspects_str} You are working a processed crime scene."
                        f"{locs_str}"
                    )
        else:
            job_row = self.conn.execute(
                "SELECT * FROM cases WHERE case_type='job' AND status='active' LIMIT 1"
            ).fetchone()
            if job_row:
                try:
                    jd = _json.loads(job_row["case_data"]) if isinstance(job_row["case_data"], str) else (job_row["case_data"] or {})
                except Exception:
                    jd = {}
                objective = jd.get("objective", "")
                steps = jd.get("steps", [])
                pending = [s["description"] for s in steps if not s.get("completed")]
                steps_str = f" Next: {pending[0]}." if pending else ""
                context_parts.append(
                    f"Active job: {job_row['title']}. {objective}{steps_str} "
                    f"You are not investigating a murder right now — you are working a hired job. "
                    f"Do not invent case details or victims."
                )
        if self.current_location_id and self.world:
            npcs = self.world.get_npcs_at(self.current_location_id)
            if npcs:
                names = ", ".join(f"{n['name']} ({n['role']})" for n in npcs)
                context_parts.append(f"People present here: {names}")
        if self.current_location_id:
            obs = self._observations.get(self.current_location_id, [])
            if obs:
                context_parts.append(
                    f"What you've examined here (atmospheric observations only — "
                    f"do not reference any specific object from these as physically present or collectible "
                    f"unless it also appears in the collectible evidence list): {' | '.join(obs[-4:])}"
                )
        if self.active_case_id:
            evidence = get_evidence_for_case(self.conn, self.active_case_id)
            collected_ids = {e["clue_id"] for e in evidence}
            if evidence:
                ev_list = "; ".join(e["description"] for e in evidence)
                context_parts.append(
                    f"Formally collected evidence (ONLY these items — do not invent others): {ev_list}"
                )
            else:
                context_parts.append("Formally collected evidence: none yet")
            if self.current_location_id:
                loc = get_location(self.conn, self.current_location_id)
                loc_name = loc["name"] if loc else ""
                clues = get_clues_for_case(self.conn, self.active_case_id)
                here = [
                    c["description"] for c in clues
                    if c["location"] and c["location"].lower() == loc_name.lower()
                    and c["id"] not in collected_ids
                ]
                if here:
                    context_parts.append(
                        f"Items here that can be collected as evidence: {'; '.join(here)}. "
                        f"ONLY these items are collectible. Do not suggest collecting anything else."
                    )
                else:
                    context_parts.append(
                        "There are no collectible evidence items at this location. "
                        "Do not suggest the detective collect or bag anything here."
                    )
        if self.active_case_id:
            dossier = get_all_dossier(self.conn, case_id=self.active_case_id)
            if dossier:
                dossier_lines = []
                for npc_name, facts in dossier.items():
                    dossier_lines.append(f"{npc_name}: {'; '.join(facts)}")
                context_parts.append(
                    f"What the detective has learned from interviews: {' | '.join(dossier_lines)}"
                )
            existing_leads = get_leads_for_case(self.conn, self.active_case_id)
            if existing_leads:
                lead_descs = [l["description"] for l in existing_leads]
                context_parts.append(
                    f"Leads already given to the detective (do NOT suggest these again): {'; '.join(lead_descs)}"
                )
        if self._recent_partner_lines:
            context_parts.append(
                f"What you already told the detective recently — do NOT repeat or restate these: "
                + " | ".join(self._recent_partner_lines[-4:])
            )
        states = get_player_states(self.conn)
        if states:
            intensity_map = {1: "slightly", 2: "noticeably", 3: "severely"}
            state_descs = [
                f"{intensity_map.get(s['intensity'], '')} {s['state']}".strip()
                for s in states
            ]
            context_parts.append(f"Detective's condition: {', '.join(state_descs)}. React naturally to this.")
        else:
            context_parts.append("Detective's condition: normal. They are fully sober and clear-headed — do not reference any prior intoxication.")

        judge_ctx = self._judge_context(player_input)
        if judge_ctx:
            context_parts.append(judge_ctx)

        ctx_block = f"[{' | '.join(context_parts)}] " if context_parts else ""
        return romance_ctx + " " + self._partner_identity_context() + ctx_block + player_input

    def _judge_context(self, player_input: str) -> str:
        from noir.cases.trial import _JUDGE_TRAITS
        inp = player_input.lower()
        assigned_judge_name = None
        if self.active_case_id:
            case = get_case(self.conn, self.active_case_id)
            if case and case["assigned_judge_id"]:
                j = self.conn.execute(
                    "SELECT name FROM npcs WHERE id=?", (case["assigned_judge_id"],)
                ).fetchone()
                if j:
                    assigned_judge_name = j["name"]

        judge_keywords = ("judge", "bench", "court", "trial", "assigned",
                          "arceneaux", "flannery", "callahan", "lacoste", "bergeron",
                          "hebert", "flynn", "tureaud", "broussard", "marino")
        input_mentions_judge = any(w in inp for w in judge_keywords)
        if not input_mentions_judge and not assigned_judge_name:
            return ""

        matching = []
        # Always include assigned judge first
        if assigned_judge_name:
            jtrait = _JUDGE_TRAITS.get(assigned_judge_name, "")
            matching.append((assigned_judge_name, f"[ASSIGNED TO THIS CASE] {jtrait}"))
        # Add any judges mentioned by name in the input
        if input_mentions_judge:
            for name, traits in _JUDGE_TRAITS.items():
                last = name.split()[-1].lower()
                if (last in inp or name.lower() in inp) and not any(m[0] == name for m in matching):
                    matching.append((name, traits))
        if not matching:
            matching = list(_JUDGE_TRAITS.items())
        lines = [f"{n}: {t}" for n, t in matching]
        return (
            "Judge reference — what you know about the bench: "
            + "; | ".join(lines)
            + ". Use this to give the detective an honest read on the judge's tendencies."
        )

    def _copresent_npc_context(self, exclude_npc_id: int) -> str:
        if not self.active_case_id or not self.current_location_id or not self.world:
            return ""
        others = [
            n for n in self.world.get_npcs_at(self.current_location_id)
            if n["id"] != exclude_npc_id
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

    def _npc_org_context(self, npc_id: int) -> str:
        orgs = get_organizations_for_npc(self.conn, npc_id)
        if not orgs:
            return ""
        player = get_player(self.conn)
        detective_race = player["race"] if player and player["race"] != "unspecified" else ""
        detective_gender = player["gender"] if player and player["gender"] != "unspecified" else ""
        rep = get_street_reputation(self.conn)
        rep_tags = rep.get("tags", [])

        org_lines = []
        for o in orgs:
            role = o["role"] or "member"
            desc_snippet = o["description"][:150] if o["description"] else ""
            org_lines.append(
                f"{o['name']} (your role: {role}; {desc_snippet})"
            )

        attitude_note = ""
        if detective_race or detective_gender:
            identity = " ".join(p for p in [detective_gender, detective_race] if p)
            attitude_note = (
                f"The detective is a {identity}. "
                "Consider what your organizational loyalties mean for how you treat them — "
                "some orgs protect their own from police scrutiny; some are hostile to outsiders; "
                "some have reason to cooperate. Let your affiliation shape your posture, not override your character. "
            )
        if rep_tags:
            attitude_note += f"The detective's street reputation: {', '.join(rep_tags)}. "

        return (
            f"[Your organizational affiliations:\n" +
            "\n".join(f"  - {l}" for l in org_lines) +
            f"\n{attitude_note}] "
        )

    def _street_rep_context(self) -> str:
        rep = get_street_reputation(self.conn)
        tags = rep.get("tags", [])
        if not tags:
            return ""
        tag_str = ", ".join(f'"{t}"' for t in tags)
        return (
            f"[This detective's street reputation — what people in this city say about them: {tag_str}. "
            f"If you've heard of this detective (likely for anyone connected to the criminal world or street life), "
            f"you may reference this reputation in how you open or respond to them. "
            f"If you wouldn't have heard of them, ignore this.] "
        )

    def handle_slash_status(self, raw: str) -> None:
        from noir.jobs.factions import FACTIONS as _FACTIONS
        parts = raw.strip().split(None, 2)
        if len(parts) == 1:
            show_player_status(get_player_states(self.conn))
            active_jobs = get_active_jobs(self.conn)
            if active_jobs:
                console.print(f"\n[bold yellow]Work on your plate ({len(active_jobs)}):[/bold yellow]")
                for job in active_jobs:
                    try:
                        data = json.loads(job["case_data"]) if isinstance(job["case_data"], str) else job["case_data"]
                        objective = data.get("objective", "")
                    except Exception:
                        objective = ""
                    faction_name = _FACTIONS.get(job["faction"] or "", {}).get("name", "")
                    console.print(f"  [yellow]·[/yellow] {job['title']} ({faction_name}) — {objective}")
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
        _partner_stage = _affection_to_stage(
            get_partner_affection(self.conn), is_partner=True
        )
        first = True
        while True:
            try:
                player_input = npc_input_prompt(
                    npc_name=self.companion.name,
                    role="partner",
                    rel_stage=_partner_stage,
                )
            except (EOFError, KeyboardInterrupt):
                break
            if not player_input.strip():
                continue
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
            if cmd.intent == Intent.COLLECT:
                if self.current_location_id and self.case_manager:
                    result = self.case_manager.validate_and_collect(
                        description=cmd.target,
                        location_id=self.current_location_id,
                        source_npc_id=None,
                    )
                    if result["ok"]:
                        show_evidence_collected(result["description"])
                    else:
                        _evidence_rejection_quip(self.companion.name, "Already collected" in result["message"], result.get("reason"), result.get("matched_desc"))
                continue
            show_player_turn(player_input)
            self._check_partner_romance_milestone()
            dark_past_state = get_partner_dark_past_state(self.conn)
            if dark_past_state == "flagged" and _is_dark_past_invitation(player_input):
                self._trigger_dark_past_revelation()
                break
            response = self.companion.speak(self._companion_context(player_input), store_as=player_input)
            self._recent_partner_lines.append(response)
            if len(self._recent_partner_lines) > 6:
                self._recent_partner_lines.pop(0)
            show_dialogue(self.companion.name, response)
        show_conversation_footer(self.companion.name)
        hist = get_history(self.conn, character_id="partner", case_id=None)
        summary_result = self.companion.summarize_and_save(hist)
        affection_delta = summary_result["affection_delta"]
        if affection_delta:
            increment_partner_affection(self.conn, delta=affection_delta)
            self._check_partner_romance_milestone()
        xp_awards = summary_result.get("xp_awards", {})
        if xp_awards:
            partner_name = self.companion.name if self.companion else None
            self._apply_skill_xp_and_check_unlocks("player", xp_awards)
            partner_xp = {k: max(0, v - 2) for k, v in xp_awards.items()}
            self._apply_skill_xp_and_check_unlocks("partner", partner_xp, partner_name=partner_name)

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
            # Also check detained NPCs — they can be arrested from The Precinct
            detained = get_detained_npcs(self.conn, self.active_case_id)
            npc_row = next((n for n in detained if target.lower() in n["name"].lower()), None)
        if npc_row is None:
            # Fall back: check if NPC's stored character_location matches current location
            # (handles case where time-based routing disagrees with where they actually are)
            all_npcs = get_npcs_for_case(self.conn, self.active_case_id)
            for n in all_npcs:
                if target.lower() not in n["name"].lower():
                    continue
                row = self.conn.execute(
                    "SELECT location_id FROM character_locations WHERE character_id=?",
                    (f"npc_{n['id']}",)
                ).fetchone()
                if row and row["location_id"] == self.current_location_id:
                    npc_row = n
                    break
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

    def handle_detain(self, target: str) -> None:
        if self.active_case_id is None:
            console.print("[dim]No active case.[/dim]")
            return
        if self.world is None or self.current_location_id is None:
            console.print("[dim]You're not sure where you are.[/dim]")
            return
        present = self.world.get_npcs_at(self.current_location_id)
        npc_row = next((n for n in present if target.lower() in n["name"].lower()), None)
        if npc_row is None:
            # Also check character_locations fallback (same as arrest)
            all_npcs = get_npcs_for_case(self.conn, self.active_case_id)
            for n in all_npcs:
                if target.lower() not in n["name"].lower():
                    continue
                row = self.conn.execute(
                    "SELECT location_id FROM character_locations WHERE character_id=?",
                    (f"npc_{n['id']}",)
                ).fetchone()
                if row and row["location_id"] == self.current_location_id:
                    npc_row = n
                    break
        if npc_row is None:
            all_npcs = get_npcs_for_case(self.conn, self.active_case_id)
            named = next((n for n in all_npcs if target.lower() in n["name"].lower()), None)
            if named:
                console.print(f"[red]{named['name']} isn't here.[/red]")
            else:
                console.print(f"[red]Don't know who '{target}' is.[/red]")
            return
        if npc_row["detained"]:
            console.print(f"[dim]{npc_row['name']} is already in holding.[/dim]")
            return
        detain_npc(self.conn, npc_row["id"])
        precinct_id = self.conn.execute(
            "SELECT id FROM locations WHERE name='The Precinct'"
        ).fetchone()
        if precinct_id:
            set_character_location(self.conn, character_id=f"npc_{npc_row['id']}",
                                   location_id=precinct_id["id"])
        console.print(f"[bold yellow]{npc_row['name']} has been brought in for questioning.[/bold yellow]")

    def handle_release(self, target: str) -> None:
        if self.active_case_id is None:
            console.print("[dim]No active case.[/dim]")
            return
        all_npcs = get_npcs_for_case(self.conn, self.active_case_id)
        npc_row = next((n for n in all_npcs if target.lower() in n["name"].lower()), None)
        if npc_row is None:
            console.print(f"[red]Don't know who '{target}' is.[/red]")
            return
        if not npc_row["detained"]:
            console.print(f"[dim]{npc_row['name']} isn't in holding.[/dim]")
            return
        release_npc(self.conn, npc_row["id"])
        console.print(f"[dim]{npc_row['name']} has been released.[/dim]")

    def handle_slash_holding(self) -> None:
        if self.active_case_id is None:
            console.print("[dim]No active case.[/dim]")
            return
        held = get_detained_npcs(self.conn, self.active_case_id)
        if not held:
            console.print("[dim]No one in holding.[/dim]")
            return
        from rich.table import Table
        t = Table(show_header=True, header_style="bold yellow", box=None)
        t.add_column("Name")
        t.add_column("Role")
        for n in held:
            t.add_row(n["name"], n["role"])
        console.print(t)

    def handle_examine(self, target: str) -> None:
        if self.current_location_id is None or self.world is None:
            console.print("[dim]You're not sure where you are.[/dim]")
            return
        loc = get_location(self.conn, self.current_location_id)
        if loc is None:
            return
        npcs = self.world.get_npcs_at(self.current_location_id)
        npc_names = [_npc_display_name(n) for n in npcs]
        is_case_location = loc["is_fixed"] == 0

        collectible_clues = []
        if self.active_case_id:
            from noir.persistence.repository import get_clues_for_case, get_evidence_for_case
            evidence = get_evidence_for_case(self.conn, self.active_case_id)
            collected_ids = {e["clue_id"] for e in evidence}
            all_clues = get_clues_for_case(self.conn, self.active_case_id)
            collectible_clues = [
                c["description"] for c in all_clues
                if c["location"] and c["location"].lower() == loc["name"].lower()
                and c["id"] not in collected_ids
            ]

        target_clues = [
            c for c in collectible_clues
            if target and target.lower() in c.lower()
        ] if target else []

        clue_instruction = ""
        if target_clues:
            clue_instruction = (
                f"\n\nCRITICAL: The detective is examining '{target}'. "
                f"The following observable facts about this subject MUST appear in your description: {'; '.join(target_clues)}. "
                "Describe exactly what the detective can see — do not omit or soften these details. "
                "Other collectible evidence at this location: "
                + ('; '.join(c for c in collectible_clues if c not in target_clues) or 'none')
                + ". Do NOT invent additional collectible-looking items."
            )
        elif collectible_clues:
            clue_instruction = (
                f"\n\nACTUAL COLLECTIBLE EVIDENCE at this location: {'; '.join(collectible_clues)}. "
                "Weave these specific items into your description — describe what the detective observes about them. "
                "Do NOT invent additional collectible-looking items beyond these. "
                "Atmospheric details are fine; only these items should read as physically present and examinable."
            )
        else:
            clue_instruction = (
                "\n\nThere is no collectible evidence at this location. "
                "Do not describe any object in a way that implies it can be picked up or bagged as evidence. "
                "Atmospheric observation only."
            )

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
            "EXCEPTION: If the item being examined is a document, letter, note, or written text, "
            "you MUST quote or paraphrase its contents — invent plausible 1930s-era text that fits the clue context. "
            "Never write 'it reads:' and leave it blank. If it's a letter, write what the letter says. "
            "CRITICAL: Never describe the inner states, feelings, or thoughts of other characters. "
            "No 'she feels', 'he senses', 'they wonder', 'it makes him feel like'. "
            "You only report what the detective can see, hear, smell, or touch — never what others experience internally. "
            "3-5 sentences maximum. No speaker attribution — pure narration."
            + clue_instruction
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
        from noir.persistence.repository import (
            get_organization_by_name as _get_org,
            add_organization_member as _add_member,
        )
        fixed = {loc["name"]: loc["id"] for loc in get_fixed_locations(self.conn)}
        for fnpc in FIXED_LOCATION_NPCS:
            existing = self.conn.execute(
                "SELECT id FROM npcs WHERE name=? AND case_id IS NULL", (fnpc["name"],)
            ).fetchone()
            corruption = fnpc.get("corruption", 0)
            if existing:
                npc_id = existing["id"]
                self.conn.execute(
                    "UPDATE npcs SET corruption=? WHERE id=?", (corruption, npc_id)
                )
                self.conn.commit()
            else:
                loc_id = fixed.get(fnpc["location"])
                if not loc_id:
                    continue
                npc_id = create_npc(self.conn, case_id=None, name=fnpc["name"],
                                    role=fnpc["role"], system_prompt=fnpc["system_prompt"],
                                    current_location_id=loc_id, corruption=corruption)
            if fnpc.get("org"):
                org = _get_org(self.conn, fnpc["org"])
                if org:
                    _add_member(self.conn, organization_id=org["id"], member_type="npc",
                                member_id=npc_id, role=fnpc.get("org_role"), is_static=True)
            for entry in fnpc.get("routine", []):
                existing_sched = self.conn.execute(
                    "SELECT id FROM npc_schedules WHERE npc_id=? AND time_start=? AND location_name=?",
                    (npc_id, _parse_hhmm(entry["time_start"]), entry["location"])
                ).fetchone()
                if not existing_sched:
                    create_npc_schedule(
                        self.conn, npc_id=npc_id,
                        time_start=_parse_hhmm(entry["time_start"]),
                        time_end=_parse_hhmm(entry["time_end"]),
                        location_name=entry["location"],
                    )

        _BAR_KEYWORDS = (
            "bar", "lounge", "saloon", "club", "speakeasy", "tavern", "cabaret",
            "pub", "inn", "dive", "joint", "room", "anchor", "vail", "veil",
            "parlor", "den", "grill",
        )
        _BAR_DESC_KEYWORDS = ("drink", "bartender", "bourbon", "whiskey", "gin", "beer", "rum",
                               "cocktail", "bottle", "pour", "stool", "sawdust", "jazz")
        _BARTENDER_NAMES = [
            "Mickey", "Ray", "Sal", "Eddie", "Frank", "Pete", "Gus", "Dutch", "Benny", "Joe"
        ]
        case_locs = get_locations_for_case(self.conn, case_id)
        used_names = {n["name"] for n in get_npcs_for_case(self.conn, case_id)}
        for loc in case_locs:
            name_lower = loc["name"].lower()
            desc_lower = (loc["description"] or "").lower()
            is_bar = (
                any(kw in name_lower for kw in _BAR_KEYWORDS)
                or any(kw in desc_lower for kw in _BAR_DESC_KEYWORDS)
            )
            if not is_bar:
                continue
            npcs_here = [n for n in get_npcs_for_case(self.conn, case_id)
                         if n["current_location_id"] == loc["id"]]
            if npcs_here:
                continue
            name = next((n for n in _BARTENDER_NAMES if n not in used_names),
                        _BARTENDER_NAMES[0])
            used_names.add(name)
            prompt = (
                f"You are {name}, the bartender at {loc['name']} in Noirleans, 1935. "
                "You've worked this bar long enough to know every regular by their poison and their problem. "
                "You're not a gossip — but you miss nothing, and if someone asks the right question the right way, "
                "you'll answer it. You speak in short, direct sentences. You're cleaning a glass when they walk in."
            )
            create_npc(self.conn, case_id=case_id, name=name,
                       role="bartender", system_prompt=prompt,
                       current_location_id=loc["id"])

    def _dispatch_slash(self, raw: str) -> None:
        slug = raw.strip().lower()
        if slug == "/location":
            self.handle_slash_look()
        elif slug == "/locations":
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
        elif slug in ("/submit", "/drop", "/newcase"):
            loc = get_location(self.conn, self.current_location_id) if self.current_location_id else None
            if loc and loc["name"] == "The DA's Office":
                self.handle_da()
            else:
                console.print("[dim]You need to be at The DA's Office for that.[/dim]")
        elif slug == "/drink":
            self.handle_slash_drink()
        elif slug == "/rep":
            self.handle_slash_rep()
        elif slug.startswith("/classifieds"):
            self.handle_slash_jobs(raw.strip().replace("/classifieds", "/jobs", 1))
        elif slug.startswith("/jobs"):
            self.handle_slash_cases(raw.strip())
        elif slug in ("/job", "/case"):
            self.handle_slash_active_work()
        elif slug == "/done":
            self.handle_slash_done()
        elif slug == "/items":
            self.handle_slash_items()
        elif slug.startswith("/bribe"):
            target = raw.strip()[6:].strip()
            self.handle_bribe(target)
        elif slug.startswith("/join"):
            org_name = raw.strip()[5:].strip()
            self.handle_join_org(org_name)
        elif slug == "/me":
            self.handle_me()
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
                self.handle_go("The DA's Office")
            elif t in _COURTHOUSE_TERMS:
                self.handle_go_courthouse()
            else:
                self.handle_go(target)
        elif slug.startswith("/talk ") or slug.startswith("/talk to "):
            parts = raw.strip().split(None, 1)
            target = parts[1].strip() if len(parts) > 1 else ""
            if target.lower().startswith("to "):
                target = target[3:].strip()
            _partner_words = {"partner", "my partner", "companion"}
            if target and self.companion and (
                target.lower() in _partner_words
                or target.lower() in self.companion.name.lower()
            ):
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
                elif self.companion:
                    _evidence_rejection_quip(self.companion.name, "Already collected" in result["message"], result.get("reason"), result.get("matched_desc"))
        elif slug.startswith("/link "):
            self.handle_slash_link(raw.strip())
        elif slug.startswith("/arrest "):
            parts = raw.strip().split(None, 1)
            target = parts[1].strip() if len(parts) > 1 else ""
            self.handle_arrest(target)
        elif slug.startswith("/detain "):
            parts = raw.strip().split(None, 1)
            target = parts[1].strip() if len(parts) > 1 else ""
            if target:
                self.handle_detain(target)
            else:
                console.print("[dim]Usage: /detain <name>[/dim]")
        elif slug.startswith("/release "):
            parts = raw.strip().split(None, 1)
            target = parts[1].strip() if len(parts) > 1 else ""
            if target:
                self.handle_release(target)
            else:
                console.print("[dim]Usage: /release <name>[/dim]")
        elif slug in ("/holding",):
            self.handle_slash_holding()
        elif slug in ("/court", "/trial", "/courthouse"):
            self.handle_courthouse()
        elif slug.startswith("/wait"):
            parts = raw.strip().split(None, 1)
            args = parts[1].strip() if len(parts) > 1 else ""
            self.handle_slash_wait(args)
        elif slug in ("/time",):
            gt = get_game_time(self.conn)
            console.print(f"[dim]It is {fmt_game_time(gt)}.[/dim]")
        elif slug in ("/audio", "/audio on", "/audio off", "/sound", "/sound on", "/sound off"):
            try:
                import noir.audio as _audio
                if slug in ("/audio on", "/sound on"):
                    wanted = True
                elif slug in ("/audio off", "/sound off"):
                    wanted = False
                else:
                    wanted = not _audio.is_audio_active()
                if wanted:
                    _audio._no_audio = False
                    if _audio._worker is None:
                        _audio.init(no_audio=False)
                    console.print("[dim]Audio on.[/dim]")
                else:
                    _audio._no_audio = True
                    _audio.flush()
                    console.print("[dim]Audio off.[/dim]")
            except Exception as e:
                console.print(f"[dim]Audio toggle failed: {e}[/dim]")

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

    def _wait_for_npc_delta(self, name: str, current_gt: int) -> tuple[int, str] | None:
        """Return (delta_minutes, npc_name) for the next time `name` arrives here, or None."""
        if not self.active_case_id or not self.current_location_id or not self.world:
            return None
        npcs = get_npcs_for_case(self.conn, self.active_case_id)
        target = next((n for n in npcs if name.lower() in n["name"].lower()), None)
        if target is None:
            return None
        all_locs = self.world.list_locations()
        loc_name_to_id = {loc["name"]: loc["id"] for loc in all_locs}
        # Check if already here
        if self.world._resolve_npc_location_id(target, current_gt, loc_name_to_id) == self.current_location_id:
            return (0, target["name"])
        # Scan forward up to 24 h in 15-min steps
        for delta in range(15, 1441, 15):
            gt = current_gt + delta
            if self.world._resolve_npc_location_id(target, gt, loc_name_to_id) == self.current_location_id:
                return (delta, target["name"])
        return None

    def handle_slash_wait(self, args: str) -> None:
        current_gt = get_game_time(self.conn)

        # "wait for <name>" — advance until that person arrives here
        if args.lower().startswith("for "):
            target_name = args[4:].strip()
            result = self._wait_for_npc_delta(target_name, current_gt)
            if result is None:
                console.print(f"[dim]{target_name} isn't coming here. Try somewhere else.[/dim]")
                return
            delta, npc_name = result
            if delta == 0:
                console.print(f"[dim]{npc_name} is already here.[/dim]")
                return
            args = str(delta)  # fall through to normal wait logic with computed delta

        delta = _parse_wait_delta(args, current_gt)
        if delta <= 0:
            console.print("[dim]That time has already passed.[/dim]")
            return
        new_gt = advance_game_time(self.conn, delta=delta)

        # Org payroll
        for payout in collect_org_payroll(self.conn, new_gt):
            console.print(f"[dim]Your cut from {payout['org_name']} arrives. ${payout['amount']}.[/dim]")

        # Sober up: 1 drink wears off per hour waited
        drunk = next((s for s in get_player_states(self.conn) if s["state"] == "drunk"), None)
        if drunk:
            hours_waited = delta // 60
            new_intensity = max(0, drunk["intensity"] - hours_waited)
            if new_intensity == 0:
                remove_player_state(self.conn, state="drunk")
                console.print("[dim]The fog lifts. You're sober.[/dim]")
            else:
                add_player_state(self.conn, state="drunk", intensity=new_intensity)

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

        show_wait_result(new_gt)

    def _relocate_npc(self, npc_name: str, location_id: int) -> None:
        if not self.active_case_id:
            return
        npcs = get_npcs_for_case(self.conn, self.active_case_id)
        npc = next((n for n in npcs if npc_name.lower() in n["name"].lower()), None)
        if npc:
            set_character_location(self.conn, character_id=f"npc_{npc['id']}", location_id=location_id)

    def _assign_npc_organizations(self, conn, llm, npc_id: int) -> None:
        _assign_npc_organizations(conn, llm, npc_id)

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
        try:
            result = self.llm.query_structured(
                "Extract up to 5 specific facts the detective just learned about this person. "
                "Include admissions, locations, times, relationships, contradictions. "
                "Each fact: one short sentence, under 15 words. Skip pleasantries. "
                "Return ONLY valid JSON: {\"facts\": [\"string\", ...]} — empty list if nothing new.",
                [],
                f"Person: {npc_name}\n\nConversation:\n{transcript}"
            )
        except FatalLLMError:
            import logging as _log; _log.getLogger(__name__).warning("Dossier extraction failed for %s", npc_name)
            return
        facts = result.get("facts", [])
        if facts:
            add_dossier_facts(self.conn, case_id=self.active_case_id, npc_name=npc_name, facts=facts)

    def _extract_leads(self, npc_name: str, npc_id: int) -> None:
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
        known_locs = []
        if self.active_case_id:
            known_locs = [l["name"] for l in get_discovered_locations_for_case(self.conn, self.active_case_id)]
        elif self.world:
            known_locs = [loc["name"] for loc in self.world.list_locations()]
        loc_constraint = (
            f" When a lead involves going somewhere, ONLY use these exact location names: {', '.join(known_locs)}."
            " Do not invent or reference locations that are not in this list."
            if known_locs else ""
        )
        try:
            result = self.llm.query_structured(
                "Extract up to 4 actionable investigative leads from this conversation. "
                "Only include leads explicitly suggested by this NPC's words. Do not invent. "
                "Each lead: one short sentence under 12 words, starting with a verb (Talk to, Go to, Find, Check)."
                + loc_constraint +
                " Return ONLY valid JSON: {\"leads\": [\"string\", ...]} — empty list if none.",
                [],
                f"Source NPC: {npc_name}\n\nConversation:\n{transcript}"
            )
        except FatalLLMError:
            import logging as _log; _log.getLogger(__name__).warning("Lead extraction failed for %s", npc_name)
            return
        case_locs = get_locations_for_case(self.conn, self.active_case_id)
        for lead_text in result.get("leads", []):
            add_lead(self.conn, case_id=self.active_case_id,
                     description=lead_text, source_npc=npc_name)
            for loc in case_locs:
                if loc["name"].lower() in lead_text.lower():
                    discover_location_by_name(self.conn, self.active_case_id, loc["name"])
        # Also discover locations mentioned anywhere in the NPC's dialogue
        transcript_lower = transcript.lower()
        for loc in case_locs:
            if loc["name"].lower() in transcript_lower:
                discover_location_by_name(self.conn, self.active_case_id, loc["name"])

    def _handle_org_succession(self, convicted_npc_id: int) -> None:
        """Handle leadership succession when a convicted NPC held a leadership role."""
        try:
            from noir.persistence.db import get_connection as _gc
            from noir.persistence.repository import (
                get_organizations_for_npc as _get_npc_orgs,
                get_members_of_organization as _get_members,
                update_member_role as _update_role,
                add_organization_member as _add_member,
            )
            conn = _gc()
            try:
                orgs = _get_npc_orgs(conn, convicted_npc_id)
                for org in orgs:
                    if not org["is_hierarchical"]:
                        continue
                    role = (org["role"] or "").lower()
                    leadership_terms = {"boss", "leader", "president", "chief", "head", "don",
                                        "patriarch", "matriarch", "captain", "director"}
                    if not any(t in role for t in leadership_terms):
                        continue

                    # Find next-highest member (not the convicted one)
                    members = _get_members(conn, org["id"])
                    candidates = [
                        m for m in members
                        if m["member_type"] == "npc" and m["member_id"] != convicted_npc_id
                    ]
                    if not candidates:
                        continue

                    # Promote first candidate (could be smarter — by existing role seniority)
                    successor = candidates[0]
                    old_role = successor["role"] or "member"
                    _update_role(conn, organization_id=org["id"],
                                 member_type="npc", member_id=successor["member_id"],
                                 role=org["role"])  # inherit the leader's role

                    import logging as _log
                    _log.getLogger(__name__).info(
                        "Org succession: %s → %s takes leadership of %s",
                        convicted_npc_id, successor["member_id"], org["name"]
                    )

                    # Spin up a new NPC to fill the successor's vacated role (async)
                    _create_replacement_npc(conn, self.llm, org["id"], old_role, org["name"])
            finally:
                conn.close()
        except Exception:
            import logging as _log
            _log.getLogger(__name__).warning("Org succession failed", exc_info=True)

    def _update_street_rep(self, case_id: int, was_correct: bool) -> None:
        """Regenerate street reputation tags based on playstyle after a case closes."""
        try:
            from noir.persistence.db import get_connection as _gc
            conn = _gc()
            try:
                self._update_street_rep_inner(conn, case_id, was_correct)
            finally:
                conn.close()
        except Exception:
            import logging as _log
            _log.getLogger(__name__).warning("Street rep update failed", exc_info=True)

    def _update_street_rep_inner(self, conn, case_id: int, was_correct: bool) -> None:
        try:
            player = get_player(conn)
            cases_solved = player["cases_solved"] if player else 0
            wrong_arrests = player["wrong_arrests"] if player else 0

            # Aggregate pressure/guilt/revelation data from npc_relationships for this case
            npcs = get_npcs_for_case(conn, case_id)
            pressure_total, guilt_total, revelations = 0, 0, 0
            for npc in npcs:
                rel = conn.execute(
                    "SELECT pressure_score, guilt, revelation_stage FROM npc_relationships WHERE npc_id=?",
                    (npc["id"],)
                ).fetchone()
                if rel:
                    pressure_total += rel["pressure_score"] or 0
                    guilt_total += rel["guilt"] or 0
                    revelations += rel["revelation_stage"] or 0

            existing = get_street_reputation(conn)
            existing_tags = existing.get("tags", [])

            prompt = (
                f"A noir detective just closed a case in 1935 Noirleans.\n\n"
                f"Outcome: {'correct arrest' if was_correct else 'wrong arrest'}\n"
                f"Career: {cases_solved} cases solved, {wrong_arrests} wrong arrests\n"
                f"Interrogation style this case:\n"
                f"  - Total pressure applied: {pressure_total} (0=none, 100+=brutal)\n"
                f"  - Total guilt leveraged: {guilt_total} (0=none, 100+=heavy)\n"
                f"  - Revelations extracted: {revelations}\n"
                f"Existing reputation tags: {', '.join(existing_tags) if existing_tags else 'none yet'}\n\n"
                "Generate or update the detective's street reputation. "
                "Reputation is 2–4 short evocative tags (2–3 words each) that capture HOW they work, "
                "not just whether they succeed. Examples: 'brutal interrogator', 'friend to the downtrodden', "
                "'gets results', 'doesn't mind the wrong man'. Let behavior dominate over outcomes. "
                "Also write one sentence (street_says) of what people on the street are whispering about this detective — "
                "in noir voice, first-person plural ('They say...', 'Word is...'). "
                'Return JSON: {"tags": ["tag1", "tag2", ...], "street_says": "string"}'
            )
            result = self.llm.query_structured(
                "You generate noir street reputation descriptions based on a detective's behavior patterns. "
                "Return ONLY valid JSON.",
                [],
                prompt
            )
            tags = result.get("tags", existing_tags)
            street_says = result.get("street_says", existing.get("street_says", ""))
            if tags:
                update_street_reputation(conn, tags=tags, street_says=street_says)
        except Exception:
            import logging as _log
            _log.getLogger(__name__).warning("Street rep update failed", exc_info=True)

    def _handle_feedback(self, raw: str) -> None:
        text = raw.lstrip("!").strip()
        if text:
            save_feedback(text)
        console.print("[dim]Noted.[/dim]")

    def handle_slash_locations(self) -> None:
        fixed = get_fixed_locations(self.conn)
        case_locs = []
        case_title = None
        crime_scene = None
        if self.active_case_id:
            case_locs = get_discovered_locations_for_case(self.conn, self.active_case_id)
            case = get_case(self.conn, self.active_case_id)
            if case:
                case_title = case["title"]
                try:
                    cd = json.loads(case["case_data"])
                    crime_scene = cd.get("victim", {}).get("found_at")
                except Exception:
                    pass
        cur_loc = get_location(self.conn, self.current_location_id) if self.current_location_id else None
        show_locations(list(fixed), list(case_locs), case_title,
                       current_location=cur_loc["name"] if cur_loc else None,
                       crime_scene=crime_scene)

    def handle_slash_leads(self) -> None:
        if self.active_case_id is None:
            console.print("[dim]No active case.[/dim]")
            return
        leads = get_leads_for_case(self.conn, self.active_case_id)
        lead_texts = [r["description"] for r in leads]
        evidence = get_evidence_for_case(self.conn, self.active_case_id)
        show_leads(lead_texts, list(evidence))

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
        if self.current_location_id:
            loc = get_location(self.conn, self.current_location_id)
            if loc:
                npcs = self.world.get_npcs_at(self.current_location_id) if self.world else []
                loc_orgs = [r["name"] for r in get_organizations_for_location(self.conn, self.current_location_id)]
                show_location(loc["name"], loc["description"], [_npc_display_name(n) for n in npcs],
                              game_time=get_game_time(self.conn), orgs=loc_orgs)
                return
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
            self._put_active_on_hold()
            set_case_active(self.conn, case_id=match["id"])
            self._set_active_case(match["id"])
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
                    desc_lower = (loc["description"] or "").lower() if loc["description"] else ""
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
                npc_row = self.conn.execute(
                    "SELECT id FROM npcs WHERE case_id=? AND name=?",
                    (self.active_case_id, s["name"])
                ).fetchone()
                if npc_row:
                    orgs = get_organizations_for_npc(self.conn, npc_row["id"])
                    if orgs:
                        org_str = ", ".join(
                            f"{o['name']}" + (f" ({o['role']})" if o['role'] else "")
                            for o in orgs
                        )
                        console.print(f"[dim]Organizations: {org_str}[/dim]")
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
        if current_case and current_case["status"] == "closed":
            console.print("[dim]That case is already closed. The DA's done with it.[/dim]")
            console.print("[dim]start — open a new case[/dim]")
            choice = console.input("[bold white]>[/bold white] ").strip().lower()
            if choice.startswith("start"):
                self._set_active_case(None)
                self.world = None
                self.case_manager = None
                self.start_new_case()
            return
        if current_case and current_case["status"] == "in_trial":
            console.print("[dim]This case is before the jury.\n"
                          "start — take a new case while you wait[/dim]\n")
            choice = console.input("[bold white]>[/bold white] ").strip().lower()
            if choice.startswith("start"):
                self._set_active_case(None)
                self.world = None
                self.case_manager = None
                self.start_new_case()
            return
        console.print(
            "[dim]submit — present your evidence for trial\n"
            "new    — set this case aside and take a new one\n"
            "drop   — close this case permanently and take a new one[/dim]\n"
        )
        choice = console.input("[bold white]>[/bold white] ").strip().lower()
        if choice.startswith("new"):
            self._set_active_case(None)
            self.world = None
            self.case_manager = None
            console.print("[dim]The DA files it under 'pending'. You walk out for something fresher.[/dim]\n")
            self.start_new_case()
            return
        if choice.startswith("drop"):
            if self.companion:
                partner_name = self.companion.name
                case = get_case(self.conn, self.active_case_id)
                drop_ctx = (
                    f"[The detective just told you they want to drop the case '{case['title'] if case else '?'}' "
                    f"and walk away without bringing it to trial. "
                    f"React honestly — agree if you think it's the right call given what you know, "
                    f"push back if you think the case should be seen through. "
                    f"Do not be neutral. You have an opinion. Speak first.] "
                )
                ctx = self._companion_context("I want to drop this case.")
                partner_response = self.companion.speak(drop_ctx + ctx, store_as="[drop case discussion]")
                show_dialogue(partner_name, partner_response)
                # One exchange — player can respond
                player_reply = console.input("[bold white]>[/bold white] ").strip()
                if player_reply:
                    followup_ctx = self._companion_context(player_reply)
                    followup = self.companion.speak(followup_ctx, store_as=player_reply)
                    show_dialogue(partner_name, followup)
                    final_response = followup
                else:
                    final_response = partner_response
                # Detect agreement/disagreement from final partner response
                stance = self.llm.query_structured(
                    "Classify whether this partner's response agrees or disagrees with dropping the case. "
                    "Return ONLY valid JSON: {\"agrees\": true|false}",
                    [],
                    f"Partner said: \"{final_response}\""
                )
                partner_agrees = stance.get("agrees", True)
            else:
                partner_agrees = True

            confirm = console.input(
                "[bold red]\nStill drop this case? It goes cold forever. (yes/no):[/bold red] "
            ).strip().lower()
            if confirm == "yes":
                if not partner_agrees:
                    increment_partner_affection(self.conn, delta=-10)
                    console.print(f"[dim]{self.companion.name if self.companion else 'Your partner'} doesn't forgive this easily.[/dim]")
                self.conn.execute(
                    "UPDATE cases SET status='closed' WHERE id=?", (self.active_case_id,)
                )
                self.conn.commit()
                self._set_active_case(None)
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
            console.print("[green]Case accepted. Head to the courthouse — the magistrate needs to clear it before trial.[/green]")
            self._start_background_generation()
        else:
            console.print("[yellow]Case rejected. Gather more evidence.[/yellow]")

    def handle_go_courthouse(self) -> None:
        fixed = {loc["name"]: loc for loc in get_fixed_locations(self.conn)}
        courthouse = fixed.get("The Courthouse")
        if courthouse is None:
            console.print("[red]The courthouse doesn't seem to be on the map.[/red]")
            return

        self.current_location_id = courthouse["id"]
        set_character_location(self.conn, character_id="player", location_id=courthouse["id"])
        advance_game_time(self.conn, delta=30)

        npcs = (
            self.world.get_npcs_at(courthouse["id"]) if self.world
            else self.conn.execute(
                "SELECT * FROM npcs WHERE current_location_id=? AND case_id IS NULL",
                (courthouse["id"],)
            ).fetchall()
        )
        npc_names = [_npc_display_name(npc) for npc in npcs]
        loc_orgs = [r["name"] for r in get_organizations_for_location(self.conn, courthouse["id"])]

        arrival = None
        if self.companion:
            npc_hint = (
                f" People present: {', '.join(npc_names)}. ONLY mention people from this list — do not invent anyone else."
                if npc_names else " No one else is here."
            )
            arrival_prompt = (
                f"[Physical setting: you are both INSIDE The Courthouse. {courthouse['description']}"
                f"{npc_hint}] "
                f"You've just arrived. Notice one specific, concrete detail about the space. "
                f"One or two sentences, in character."
            )
            self.llm.suppress_status = True
            with travel_status():
                arrival = self.companion.narrate(arrival_prompt)
            self.llm.suppress_status = False

        show_travel_animation()
        show_location_rule()
        show_location(courthouse["name"], courthouse["description"], npc_names,
                      game_time=get_game_time(self.conn), orgs=loc_orgs)
        if arrival:
            show_dialogue(self.companion.name, arrival)

        # Surface trial cases if any are pending
        pipeline_statuses = ("pending_magistrate", "in_trial")
        pending = self.conn.execute(
            "SELECT COUNT(*) FROM cases WHERE status IN (?,?)", pipeline_statuses
        ).fetchone()[0]
        if pending:
            self.handle_courthouse()

    def handle_courthouse(self) -> None:
        pipeline_statuses = ("pending_magistrate", "in_trial")
        rows = self.conn.execute(
            "SELECT id, title, status, assigned_judge_id FROM cases WHERE status IN (?,?) ORDER BY id DESC",
            pipeline_statuses
        ).fetchall()

        if not rows:
            console.print("[dim]Nothing before the court right now.[/dim]")
            return

        console.print("\n[bold]Cases before the court:[/bold]")
        for i, row in enumerate(rows, 1):
            judge_note = ""
            if row["assigned_judge_id"]:
                j = self.conn.execute(
                    "SELECT name FROM npcs WHERE id=?", (row["assigned_judge_id"],)
                ).fetchone()
                if j:
                    judge_note = f" — {j['name']}"
            status_label = "Awaiting magistrate" if row["status"] == "pending_magistrate" else f"In trial{judge_note}"
            console.print(f"  [bold]{i}.[/bold] {row['title']} [{status_label}]")

        if len(rows) == 1:
            choice_str = "1"
        else:
            choice_str = console.input("\n[bold white]Check which case (number):[/bold white] ").strip()

        try:
            idx = int(choice_str) - 1
            selected = rows[idx]
        except (ValueError, IndexError):
            console.print("[dim]Never mind.[/dim]")
            return

        self._handle_courthouse_case(selected["id"], selected["status"])

    def _handle_courthouse_case(self, case_id: int, status: str) -> None:
        ts = TrialSystem(conn=self.conn, case_id=case_id, llm=self.llm)
        case = get_case(self.conn, case_id)

        if status == "pending_magistrate":
            result = ts.submit_to_magistrate()
            show_dialogue("Magistrate Moreau", result.get("dialogue", "..."))
            if result.get("cleared"):
                judge_name = result.get("assigned_judge", "a judge")
                console.print(f"[green]Case cleared for trial. Assigned to {judge_name}.[/green]")
            else:
                console.print("[yellow]Case dismissed by the magistrate.[/yellow]")
                if case_id == self.active_case_id:
                    self._set_active_case(None)
                    self.world = World(conn=self.conn, active_case_id=None)
                    self.case_manager = None
            return

        status_info = ts.check_courthouse()
        if status_info["status"] == "in_trial":
            judge_note = ""
            if case["assigned_judge_id"]:
                j = self.conn.execute(
                    "SELECT name FROM npcs WHERE id=?", (case["assigned_judge_id"],)
                ).fetchone()
                if j:
                    judge_note = f" before {j['name']}"
            remaining = status_info.get("minutes_remaining", "?")
            from rich.panel import Panel
            from noir.display import console as _dc
            body = (
                f"[yellow]{case['title']}[/yellow] is before the jury{judge_note}.\n"
                f"Estimated time remaining: {remaining}"
            )
            _dc.print(Panel(body, title="[bold]Courthouse[/bold]", border_style="blue"))
        elif status_info["status"] == "closed":
            verdict = status_info.get("verdict", {})
            outcome_raw = verdict.get("outcome", "") if verdict else ""
            if outcome_raw == "guilty":
                from rich.panel import Panel as _P
                console.print(_P("[bold green]GUILTY[/bold green]",
                                 title=f"[bold]{case['title']}[/bold]",
                                 border_style="green"))
            elif outcome_raw in ("not_guilty", "not guilty"):
                from rich.panel import Panel as _P
                console.print(_P("[bold red]NOT GUILTY[/bold red]",
                                 title=f"[bold]{case['title']}[/bold]",
                                 border_style="red"))
            else:
                show_trial_status(case["title"], "closed", None)
            if verdict:
                show_dialogue("Courthouse Clerk", verdict.get("summary", "The verdict is in."))
            arrest = self.conn.execute(
                "SELECT was_correct, npc_id FROM arrests WHERE case_id=? ORDER BY id DESC LIMIT 1",
                (case_id,)
            ).fetchone()
            original_correct = bool(arrest and arrest["was_correct"])
            outcome = verdict.get("outcome", "") if verdict else ""
            corruption_loss = original_correct and outcome == "not_guilty"
            was_correct = original_correct and outcome != "not_guilty"
            if self.companion:
                if corruption_loss:
                    closing_prompt = (
                        f"[Case: {case['title']}. The detective arrested the right person but the verdict just came back not guilty — "
                        "the system is corrupt, the fix was in, and the killer walks free.] "
                        "Offer the detective a few words. Acknowledge the injustice directly — don't be abstract about it. "
                        "Be in character. One or two sentences."
                    )
                elif was_correct:
                    closing_prompt = (
                        f"[Case: {case['title']} is closed. Verdict: {outcome}. The right person was convicted.] "
                        "Mark the moment in one or two sentences — in character, no stage directions. "
                        "You can be satisfied, wry, relieved, or whatever fits who you are. Don't be effusive."
                    )
                else:
                    closing_prompt = (
                        f"[Case: {case['title']} is closed. The wrong person was arrested. Outcome: {outcome}.] "
                        "React to the outcome in one or two sentences — in character. "
                        "You may be grim, sardonic, or simply quiet about it."
                    )
                show_dialogue(self.companion.name, self.companion.narrate(closing_prompt))
            threading.Thread(
                target=self._update_street_rep,
                args=(case_id, was_correct),
                daemon=True,
            ).start()
            if was_correct and arrest:
                threading.Thread(
                    target=self._handle_org_succession,
                    args=(arrest["npc_id"],),
                    daemon=True,
                ).start()
            if case_id == self.active_case_id:
                self._set_active_case(None)
                self.world = World(conn=self.conn, active_case_id=None)
                self.case_manager = None
                self._start_background_generation()
                console.print("[dim]The case is behind you now. Head to the DA's office for a new one.[/dim]")

    def handle_slash_rep(self) -> None:
        from rich.panel import Panel as _Panel
        from noir.jobs.factions import FACTIONS

        rep = get_street_reputation(self.conn)
        tags = rep.get("tags", [])
        street_says = rep.get("street_says", "")
        if tags or street_says:
            tag_str = "  ".join(f"[bold]{t}[/bold]" for t in tags) if tags else "[dim]none[/dim]"
            body = tag_str
            if street_says:
                body += f"\n\n[italic dim]{street_says}[/italic dim]"
            console.print(_Panel(body, title="[yellow]Street Reputation[/yellow]", border_style="yellow"))

        reps = get_all_faction_reps(self.conn)
        nonzero = {k: v for k, v in reps.items() if v > 0 and k != "da_office"}
        # Also show da_office if it differs from default (100)
        da_rep = reps.get("da_office", 100)
        if da_rep != 100:
            nonzero["da_office"] = da_rep
        if nonzero:
            lines = []
            for slug, score in sorted(nonzero.items(), key=lambda x: -x[1]):
                name = FACTIONS.get(slug, {}).get("name", slug)
                bar = "█" * (score // 10) + "░" * (10 - score // 10)
                lines.append(f"  [yellow]{name:<40}[/yellow] {bar} {score}")
            console.print(_Panel("\n".join(lines), title="[yellow]Who Owes You — Who Watches You[/yellow]",
                                 border_style="yellow dim"))
        elif not tags and not street_says:
            console.print("[dim]Nobody knows your name yet. Do some work.[/dim]")

    def handle_slash_items(self) -> None:
        from noir.items import ITEM_CATALOG
        from noir.persistence.repository import get_player_items
        from noir.display import show_items
        inventory = get_player_items(self.conn)
        show_items(inventory, ITEM_CATALOG)

    def handle_slash_done(self) -> None:
        """Mark an active job complete after confirming the objective was met."""
        active_jobs = get_active_jobs(self.conn)
        if not active_jobs:
            console.print("[dim]Nothing on the books.[/dim]")
            return

        if len(active_jobs) == 1:
            job = active_jobs[0]
        else:
            console.print("[bold yellow]Work you're carrying:[/bold yellow]")
            for i, j in enumerate(active_jobs, 1):
                console.print(f"  {i}. {j['title']}")
            choice = console.input("[bold white]Which job are you closing out? (number): [/bold white]").strip()
            if not choice.isdigit() or not (1 <= int(choice) <= len(active_jobs)):
                console.print("[dim]Never mind.[/dim]")
                return
            job = active_jobs[int(choice) - 1]

        try:
            data = json.loads(job["case_data"]) if isinstance(job["case_data"], str) else job["case_data"]
        except Exception:
            data = {}

        objective = data.get("objective", "complete the objective")
        verdict = self.llm.query_structured(
            "The detective claims to have completed a job. "
            "Based on the objective, judge whether it is plausible they succeeded. "
            "Return ONLY valid JSON: {\"completed\": true|false, \"reason\": \"one sentence\"}",
            [],
            f"Job objective: {objective}\nDetective claims: done."
        )

        if not verdict.get("completed", True):
            reason = verdict.get("reason") or "That one ain't wrapped up yet."
            console.print(f"[dim]{reason}[/dim]")
            return

        payout = job["payout"] or 0
        faction = job["faction"] or "private"
        tier = job["tier"] or 1
        complete_job(self.conn, case_id=job["id"], payout=payout, faction=faction, tier=tier)
        if tier == 1:
            self._replenish_job_board()
        self._resume_on_hold()

        if payout:
            console.print(f"[dim]${payout}. That's closed.[/dim]")
        else:
            console.print("[dim]That's closed.[/dim]")

        moral_weight = data.get("moral_weight", "low")
        if moral_weight == "high" and self.companion:
            self.companion.speak(
                f"[You just completed a morally significant job: {objective}]",
                record=False
            )

    def _check_job_completion(self, npc_row, response: str) -> None:
        """Auto-detect if the NPC's response signals a job has been completed."""
        active_jobs = get_active_jobs(self.conn)
        if not active_jobs:
            return

        job = next(
            (j for j in active_jobs
             if (json.loads(j["case_data"]) if isinstance(j["case_data"], str)
                 else j["case_data"]).get("client_npc_name", "").lower()
                in npc_row["name"].lower()),
            None
        )
        if not job:
            return

        signal = self.llm.query_structured(
            "Does the NPC dialogue signal that a job or task has been completed to their satisfaction? "
            "Return ONLY valid JSON: {\"job_complete\": true|false}",
            [],
            f"NPC said: \"{response[:300]}\""
        )
        if not signal.get("job_complete"):
            return

        payout = job["payout"] or 0
        faction = job["faction"] or "private"
        tier = job["tier"] or 1
        complete_job(self.conn, case_id=job["id"], payout=payout, faction=faction, tier=tier)
        if tier == 1:
            self._replenish_job_board()
        self._resume_on_hold()
        if payout:
            console.print(f"[dim]${payout} in your pocket.[/dim]")
        else:
            console.print("[dim]Finished.[/dim]")

    def handle_slash_active_work(self) -> None:
        """Show the description of the current active case or job."""
        from noir.jobs.factions import FACTIONS as _FACTIONS
        row = self.conn.execute(
            "SELECT * FROM cases WHERE status='active' AND case_type != 'job' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            row = self.conn.execute(
                "SELECT * FROM cases WHERE status='active' AND case_type='job' LIMIT 1"
            ).fetchone()
        if row is None:
            console.print("[dim]Nothing on your plate.[/dim]")
            return
        try:
            data = json.loads(row["case_data"]) if isinstance(row["case_data"], str) else (row["case_data"] or {})
        except Exception:
            data = {}
        if row["case_type"] == "job":
            faction_name = _FACTIONS.get(row["faction"] or "", {}).get("name", row["faction"] or "")
            lines = [
                f"[bold yellow]{row['title']}[/bold yellow] [dim]({faction_name} — ${row['payout']})[/dim]",
                f"{data.get('objective', '')}",
            ]
            steps = data.get("steps", [])
            if steps:
                import textwrap
                lines.append("")
                for step in steps:
                    done = step.get("completed", False)
                    marker = "[dim]✓[/dim]" if done else "[yellow]·[/yellow]"
                    color = "dim" if done else "white"
                    desc = step.get("description", "")
                    wrapped = textwrap.wrap(desc, width=68)
                    if wrapped:
                        lines.append(f"  {marker} [{color}]{wrapped[0]}[/{color}]")
                        for cont in wrapped[1:]:
                            lines.append(f"    [{color}]{cont}[/{color}]")
            console.print("\n".join(lines))
        else:
            console.print(f"[bold yellow]{row['title']}[/bold yellow]")
            console.print(f"{data.get('premise', data.get('summary', data.get('objective', '')))}")

    def handle_slash_jobs(self, raw: str) -> None:
        from rich.panel import Panel as _Panel
        from noir.jobs.factions import FACTIONS
        args = raw.strip().lower()

        if "--pending" in args:
            offers = get_pending_job_offers(self.conn)
            if not offers:
                console.print("[dim]Nobody's come calling.[/dim]")
                return
            console.print("[bold yellow]Word's come in:[/bold yellow]")
            for offer in offers:
                console.print(f"  [yellow]·[/yellow] {offer['npc_name']} wants a word.")
            return

        jobs = get_available_jobs(self.conn)
        if not jobs:
            console.print("[dim]Word's getting around. Give it a minute.[/dim]")
            self._replenish_job_board()
            jobs = get_available_jobs(self.conn)

        if not jobs:
            console.print("[dim]Nothing doing right now. Check back later.[/dim]")
            return

        lines = []
        for i, job in enumerate(jobs, 1):
            try:
                data = json.loads(job["case_data"]) if isinstance(job["case_data"], str) else job["case_data"]
            except Exception:
                data = {}
            faction_name = FACTIONS.get(job["faction"] or "", {}).get("name", job["faction"] or "Unknown")
            lines.append(
                f"[bold white]{i}.[/bold white] [Tier {job['tier']}] {job['title']} "
                f"— {faction_name} — [green]${job['payout']}[/green]"
            )
            lines.append(f"   [dim]{data.get('objective', '')}[/dim]")
            lines.append("")

        console.print(_Panel("\n".join(lines).rstrip(), title="[yellow]Help Wanted[/yellow]",
                             border_style="yellow"))

        choice = console.input("[bold white]Take something? (number or enter to walk): [/bold white]").strip()
        if not choice.isdigit():
            return
        idx = int(choice) - 1
        if not (0 <= idx < len(jobs)):
            console.print("[dim]That's not on the board.[/dim]")
            return

        job = jobs[idx]
        self._put_active_on_hold()
        self.conn.execute("UPDATE cases SET status='active' WHERE id=?", (job["id"],))
        self.conn.commit()
        from noir.jobs.factions import seed_job_client_npc, seed_job_target_npc
        seed_job_client_npc(self.conn, dict(job))
        seed_job_target_npc(self.conn, dict(job))
        try:
            data = json.loads(job["case_data"]) if isinstance(job["case_data"], str) else job["case_data"]
        except Exception:
            data = {}
        console.print(f"[dim]You're on it. {data.get('objective', '')}[/dim]")

    def handle_bribe(self, target_name: str) -> None:
        if not target_name:
            console.print("[dim]Bribe who? /bribe [name][/dim]")
            return

        # Find target — current location first, then fixed-location power NPCs
        npc_row = None
        if self.active_case_id:
            npcs = get_npcs_for_case(self.conn, self.active_case_id)
            npc_row = next((n for n in npcs if target_name.lower() in n["name"].lower()), None)
        if npc_row is None:
            npc_row = self.conn.execute(
                "SELECT * FROM npcs WHERE case_id IS NULL AND LOWER(name) LIKE ?",
                (f"%{target_name.lower()}%",)
            ).fetchone()
        if npc_row is None:
            console.print(f"[dim]Don't know anyone by that name.[/dim]")
            return

        corruption = npc_row["corruption"] if npc_row["corruption"] is not None else 0
        cash = get_player_cash(self.conn)
        console.print(f"[dim]You have ${cash} on you.[/dim]")

        try:
            amount_str = console.input("[bold white]How much are you offering? $[/bold white]").strip()
            amount = int(amount_str)
        except ValueError:
            console.print("[dim]Never mind.[/dim]")
            return
        if amount <= 0:
            console.print("[dim]That's not a bribe, that's an insult.[/dim]")
            return
        if amount > cash:
            console.print(f"[dim]You don't have ${amount}.[/dim]")
            return

        # Determine bribe effect context
        effect = self._determine_bribe_effect(npc_row["id"])

        # Build NPC response prompt
        bribe_system = npc_row["system_prompt"] + (
            "\n\nCRITICAL: A detective has just offered you a bribe. "
            "Your response must be in character. "
            "Your corruption level determines your reaction — respond authentically. "
            "If you accept, say so in your own voice. If you refuse, make clear why. "
            "Never break character. Do not use bracket notation."
        )
        bribe_prompt = (
            f"The detective has just slipped you an envelope containing ${amount}. "
            f"Context: {effect['context']} "
            "Respond in character. Accept or refuse based on who you are."
        )

        from noir.characters.agent import Agent as CharacterAgent
        agent = CharacterAgent(
            character_id=f"npc_{npc_row['id']}",
            system_prompt=bribe_system,
            llm=self.llm,
            conn=self.conn,
        )
        response = agent.speak(bribe_prompt)
        show_dialogue(npc_row["name"], response)

        # Determine acceptance via LLM classification
        stance = self.llm.query_structured(
            "Classify whether this response accepts or refuses a bribe. "
            "Return ONLY valid JSON: {\"accepted\": true|false}",
            [],
            f"Response: \"{response}\""
        )
        accepted = stance.get("accepted", False)

        # Corruption threshold: bribe needs to be meaningful relative to corruption
        # Very corrupt NPCs accept almost anything; principled ones refuse regardless
        if corruption == 0:
            accepted = False  # incorruptible — override
        elif corruption <= 3:
            # Low corruption — only accept if amount is substantial AND LLM said yes
            accepted = accepted and amount >= 200

        if accepted:
            update_player_cash(self.conn, delta=-amount)
            record_bribe(self.conn, case_id=self.active_case_id, npc_id=npc_row["id"],
                         amount=amount, accepted=True, effect=effect["effect_type"])
            # Bribery shifts toward chaos only
            self.conn.execute(
                "UPDATE player SET law_chaos = MAX(-100, MIN(100, law_chaos - 5)) WHERE id=1"
            )
            self.conn.commit()
            console.print(f"[dim]${amount} lighter. The envelope disappears.[/dim]")

            # Detection risk: lower corruption = higher chance of reporting
            detection_chance = max(0.0, (5 - corruption) / 10)
            if random.random() < detection_chance:
                console.print(
                    "[red]Word gets around. Someone talked.[/red]"
                )
                from noir.persistence.repository import update_player_reputation
                update_player_reputation(self.conn, delta=-15)
                from noir.cases.trial import update_da_trust
                update_da_trust(self.conn, delta=-10)
        else:
            record_bribe(self.conn, case_id=self.active_case_id, npc_id=npc_row["id"],
                         amount=amount, accepted=False, effect=None)
            console.print("[dim]The envelope comes back.[/dim]")
            # Attempting to bribe an honest person carries its own risk
            if corruption <= 2:
                console.print("[red]This one's going to remember you tried.[/red]")
                from noir.persistence.repository import update_player_reputation
                update_player_reputation(self.conn, delta=-5)

    _BRIBE_KEYWORDS = frozenset([
        "$", "cash", "envelope", "money", "payment", "pay you", "paid",
        "look the other way", "forget what you saw", "drop it", "walk away",
        "compensate", "arrangement", "consideration", "hundred", "thousand",
    ])

    def _check_npc_bribe_offer(self, npc_row, response: str) -> None:
        """Detect if the NPC just offered the player a bribe and prompt acceptance."""
        resp_lower = response.lower()
        if not any(kw in resp_lower for kw in self._BRIBE_KEYWORDS):
            return

        offer = self.llm.query_structured(
            "Determine if the following NPC dialogue contains a bribe offer to the player. "
            "Return ONLY valid JSON: "
            "{\"bribe_offered\": true|false, \"amount\": integer_or_null, "
            "\"condition\": \"what they want in return, brief\"}",
            [],
            f"NPC said: \"{response[:400]}\""
        )
        if not offer.get("bribe_offered"):
            return

        amount = offer.get("amount") or None
        condition = offer.get("condition", "back off")
        if amount:
            offer_desc = f"${amount}"
        else:
            offer_desc = "a favor"
        console.print(f"\n[yellow dim]{npc_row['name']} has offered you {offer_desc} to {condition}.[/yellow dim]")
        accept_input = console.input("[bold white]Accept this bribe? (yes/no):[/bold white] ").strip().lower()
        if accept_input != "yes":
            console.print("[dim]You pass.[/dim]")
            record_bribe(self.conn, case_id=self.active_case_id, npc_id=npc_row["id"],
                         amount=amount, accepted=False, effect=None)
            return

        if amount:
            update_player_cash(self.conn, delta=amount)
        record_bribe(self.conn, case_id=self.active_case_id, npc_id=npc_row["id"],
                     amount=amount, accepted=True, effect="player_accepted")
        # Shift toward chaos only
        self.conn.execute(
            "UPDATE player SET law_chaos = MAX(-100, MIN(100, law_chaos - 8)) WHERE id=1"
        )
        self.conn.commit()
        if amount:
            console.print(f"[dim]${amount} in your pocket. You know what they expect.[/dim]")
        else:
            console.print(f"[dim]You've agreed. They'll expect you to follow through.[/dim]")

    _JOB_KEYWORDS = frozenset([
        "job", "work for me", "errand", "task", "assignment",
        "need someone", "need a man", "reliable person", "discreet",
        "money in it", "paid well", "compensate you",
        "little work", "small job", "favor for me",
    ])

    def _check_faction_tension(self) -> None:
        """Fire a tension event if player holds rep ≥ 40 with two directly opposing factions."""
        from noir.jobs.factions import OPPOSITION, TENSION_THRESHOLD
        reps = get_all_faction_reps(self.conn)
        checked: set[frozenset] = set()
        for faction, rep in reps.items():
            if rep < TENSION_THRESHOLD:
                continue
            if faction not in OPPOSITION:
                continue
            for opp in OPPOSITION[faction].get("direct", []):
                pair = frozenset((faction, opp))
                if pair in checked:
                    continue
                checked.add(pair)
                opp_rep = reps.get(opp, 0)
                if opp_rep < TENSION_THRESHOLD:
                    continue
                self._trigger_tension_event(faction, opp, rep, opp_rep)
                return

    def _trigger_tension_event(self, faction_a: str, faction_b: str,
                                rep_a: int, rep_b: int) -> None:
        from noir.jobs.factions import FACTIONS, TENSION_ESCALATION
        name_a = FACTIONS.get(faction_a, {}).get("name", faction_a)
        name_b = FACTIONS.get(faction_b, {}).get("name", faction_b)
        escalated = rep_a >= TENSION_ESCALATION or rep_b >= TENSION_ESCALATION

        if escalated:
            msg = (f"[red]A contact from {name_a} corners you. Word has reached {name_b}. "
                   f"They want to know where your loyalties lie — and they're not asking politely.[/red]")
        else:
            msg = (f"[yellow dim]Word is traveling between {name_a} and {name_b}. "
                   f"Someone's noticed you're working both sides.[/yellow dim]")
        console.print(f"\n{msg}")

        console.print("[bold white]How do you play it? (reassure / dismiss / choose): [/bold white]", end="")
        choice = console.input("").strip().lower()

        if choice == "reassure":
            update_faction_rep(self.conn, faction_a, 5)
            console.print(f"[dim]You smooth it over with {name_a}. For now.[/dim]")
        elif choice == "choose":
            console.print(f"[bold white]Side with {name_a} or {name_b}? [/bold white]", end="")
            side = console.input("").strip().lower()
            if name_a.lower() in side or faction_a in side:
                update_faction_rep(self.conn, faction_a, 15)
                update_faction_rep(self.conn, faction_b, -20)
                console.print(f"[dim]You've made your choice. {name_b} won't forget.[/dim]")
            else:
                update_faction_rep(self.conn, faction_b, 15)
                update_faction_rep(self.conn, faction_a, -20)
                console.print(f"[dim]You've made your choice. {name_a} won't forget.[/dim]")
        else:
            update_faction_rep(self.conn, faction_a, -5)
            console.print("[dim]They don't like that answer.[/dim]")

    def _check_npc_job_offer(self, npc_row, response: str) -> None:
        """Detect if NPC just offered the player a job and prompt acceptance."""
        resp_lower = response.lower()
        if not any(kw in resp_lower for kw in self._JOB_KEYWORDS):
            return

        offer = self.llm.query_structured(
            "Determine if the NPC dialogue contains an offer of paid work or a job for the player. "
            "Do not flag general conversation about work or jobs — only a specific offer to the player. "
            "Return ONLY valid JSON: "
            "{\"job_offered\": true|false, \"job_type\": \"string or null\", "
            "\"faction_hint\": \"string or null\"}",
            [],
            f"NPC said: \"{response[:400]}\""
        )
        if not offer.get("job_offered"):
            return

        console.print(f"\n[yellow dim]{npc_row['name']} has something that needs doing. You want in? (yes/no)[/yellow dim]")
        resp = console.input("[bold white]> [/bold white]").strip().lower()
        offer_id = create_job_offer(self.conn, npc_id=npc_row["id"])
        if resp != "yes":
            decline_job_offer(self.conn, offer_id=offer_id)
            console.print("[dim]You let it go.[/dim]")
            return
        self._activate_npc_job_offer(npc_row, offer_id, offer.get("faction_hint"))

    def _activate_npc_job_offer(self, npc_row, offer_id: int,
                                 faction_hint: str | None) -> None:
        """Generate and activate a job offered by an NPC."""
        from noir.jobs.generator import JobGenerator
        from noir.jobs.factions import faction_slug_for_npc, TIER_REP_THRESHOLDS

        npc_faction = faction_slug_for_npc(self.conn, npc_row["id"])
        faction = npc_faction or "private"

        tier = 1
        if faction != "private":
            rep = get_faction_rep(self.conn, faction)
            if rep >= TIER_REP_THRESHOLDS[2]:
                tier = 2

        gen = JobGenerator(self.llm, self.conn)
        job = gen.generate(faction=faction, tier=tier)
        if not job:
            console.print("[dim]They seem to have changed their mind.[/dim]")
            decline_job_offer(self.conn, offer_id=offer_id)
            return

        job_id = create_job(
            self.conn,
            faction=job["faction"],
            tier=job["tier"],
            title=job["title"],
            payout=job["payout"],
            case_data=job["case_data"],
        )
        self._put_active_on_hold()
        self.conn.execute("UPDATE cases SET status='active' WHERE id=?", (job_id,))
        self.conn.commit()
        accept_job_offer(self.conn, offer_id=offer_id, case_id=job_id)
        from noir.jobs.factions import seed_job_client_npc, seed_job_target_npc
        seed_job_client_npc(self.conn, job)
        seed_job_target_npc(self.conn, job)

        try:
            data = job["case_data"]
            objective = data.get("objective", "") if isinstance(data, dict) else ""
        except Exception:
            objective = ""
        console.print(f"[dim]You're on it. {objective}[/dim]")

    def _determine_bribe_effect(self, npc_id: int) -> dict:
        """Figure out what a bribe to this NPC would affect, given the current case state."""
        if not self.active_case_id:
            return {"effect_type": "general", "context": "You want a favor."}

        case = get_case(self.conn, self.active_case_id)

        # Check if this NPC is the assigned judge
        if case and case["assigned_judge_id"] == npc_id and case["status"] == "in_trial":
            return {
                "effect_type": "verdict_influence",
                "context": (
                    "You are the assigned judge in this detective's active trial. "
                    "They want a guilty verdict."
                ),
            }

        # Check if this NPC is the magistrate and case is pending
        npc = self.conn.execute("SELECT role FROM npcs WHERE id=?", (npc_id,)).fetchone()
        if npc and "magistrate" in (npc["role"] or "").lower() and case and case["status"] == "pending_magistrate":
            return {
                "effect_type": "magistrate_clear",
                "context": (
                    "You are the magistrate handling this detective's case. "
                    "They want it cleared for trial without the usual review."
                ),
            }

        return {"effect_type": "general", "context": "The detective wants a favor."}

    def _check_org_eligibility(self, org_name: str, player: dict) -> str | None:
        return check_org_eligibility(self.conn, org_name, player)

    def handle_join_org(self, org_name: str) -> None:
        if not org_name:
            console.print("[dim]Join which organization? /join [name][/dim]")
            return

        org = self.conn.execute(
            "SELECT * FROM organizations WHERE LOWER(name) LIKE ?",
            (f"%{org_name.lower()}%",)
        ).fetchone()
        if not org:
            console.print(f"[dim]Never heard of them.[/dim]")
            return

        # Check if already a member
        existing = self.conn.execute(
            "SELECT id FROM organization_members WHERE organization_id=? AND member_type='player' AND member_id=1",
            (org["id"],)
        ).fetchone()
        if existing:
            console.print(f"[dim]You're already with {org['name']}.[/dim]")
            return

        player = get_player(self.conn)

        # Hard eligibility gate — checked before any LLM call
        rejection = self._check_org_eligibility(org["name"], player or {})
        if rejection:
            console.print(f"[dim]{rejection}[/dim]")
            return

        # Find the org's leader NPC to speak for the org
        leader_row = self.conn.execute(
            """SELECT n.id, n.name, n.system_prompt, n.corruption FROM npcs n
               JOIN organization_members om ON om.member_id = n.id AND om.member_type='npc'
               WHERE om.organization_id=? AND om.is_static=1
               ORDER BY CASE WHEN om.role IN ('don','boss','president','captain','director','mayor','sheriff')
                             THEN 0 ELSE 1 END
               LIMIT 1""",
            (org["id"],)
        ).fetchone()

        if not leader_row:
            console.print(f"[dim]You don't know anyone in {org['name']} to vouch for you.[/dim]")
            return

        player_race = player["race"] if player else "unspecified"
        player_gender = player["gender"] if player else "unspecified"
        rep = player["reputation"] if player else 100
        law_chaos = player.get("law_chaos", 0) if player else 0

        join_system = leader_row["system_prompt"] + (
            "\n\nCRITICAL: The detective has just asked to join your organization. "
            "Evaluate them based on who you are and what your organization values. "
            "Be honest: some orgs exclude by race, religion, or sex. "
            "Some require demonstrated loyalty or criminal willingness. "
            "A high-chaos detective who takes bribes and bends rules is more useful to a crime family "
            "than a straight-arrow cop. Respond in character. "
            "Your response should make clear whether you're accepting, rejecting, or deferring. "
            "Never use bracket notation."
        )
        join_prompt = (
            f"The detective wants to join {org['name']}. "
            f"Detective profile: race={player_race}, gender={player_gender}, "
            f"reputation={rep}/100, law/chaos score={law_chaos} (negative=lawful, positive=chaotic). "
            f"Org type: {org['type']}, influence: {org['influence']}. "
            "Respond in character."
        )

        from noir.characters.agent import Agent as CharacterAgent
        agent = CharacterAgent(
            character_id=f"npc_{leader_row['id']}",
            system_prompt=join_system,
            llm=self.llm,
            conn=self.conn,
        )
        response = agent.speak(join_prompt)
        show_dialogue(leader_row["name"], response)

        stance = self.llm.query_structured(
            "Did this response accept, reject, or defer the request to join the organization? "
            "Return ONLY valid JSON: {\"decision\": \"accepted\"|\"rejected\"|\"deferred\"}",
            [],
            f"Response: \"{response[:400]}\""
        )
        decision = stance.get("decision", "rejected")

        if decision == "accepted":
            # Set payroll based on org type and influence
            payroll = 0
            if org["type"] == "crime_family":
                payroll = org["influence"] * 15  # $75–135/day for influence 5–9
            elif org["type"] in ("government", "union"):
                payroll = org["influence"] * 5   # smaller legitimate stipend

            self.conn.execute(
                """INSERT INTO organization_members
                   (organization_id, member_type, member_id, role, payroll, last_payroll_time)
                   VALUES (?, 'player', 1, 'associate', ?, ?)""",
                (org["id"], payroll, get_game_time(self.conn))
            )
            self.conn.commit()
            # Joining a crime org shifts toward chaos
            if org["type"] == "crime_family":
                self.conn.execute(
                    "UPDATE player SET law_chaos = MAX(-100, MIN(100, law_chaos + 15)) WHERE id=1"
                )
                self.conn.commit()
            if payroll:
                console.print(f"[dim]You're in. ${payroll}/day, paid daily.[/dim]")
            else:
                console.print(f"[dim]You're in.[/dim]")
        elif decision == "deferred":
            console.print("[dim]The door isn't closed. Come back when you've proven yourself.[/dim]")

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

    def handle_me(self) -> None:
        player = get_player(self.conn)
        if not player:
            return

        orgs = get_player_org_memberships(self.conn)
        org_list = [
            {"org_name": o["org_name"], "role": o["role"], "payroll": o["payroll"]}
            for o in orgs
        ]

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

        from noir.persistence.repository import get_skills, get_specializations, get_faction_rep
        p_skills = get_skills(self.conn, owner="player") or None
        p_specs = get_specializations(self.conn, owner="player") or None
        pt_skills = get_skills(self.conn, owner="partner") or None
        pt_specs = get_specializations(self.conn, owner="partner") or None

        player_dict = dict(player)
        player_dict["da_trust"] = get_faction_rep(self.conn, "da_office")
        show_player_profile(
            player_dict, org_list, partner_name, partner_stage, npc_rels,
            player_skills=p_skills,
            player_specializations=p_specs,
            partner_skills=pt_skills,
            partner_specializations=pt_specs,
        )

    def handle_slash_drink(self) -> None:
        _BAR_KEYWORDS = ("bar", "lounge", "saloon", "club", "speakeasy", "tavern", "cabaret",
                         "rusty anchor")
        _DRINK_KEYWORDS = ("bottle", "glass", "flask", "whiskey", "bourbon", "rye", "gin",
                           "rum", "wine", "beer", "scotch", "drink", "liquor", "brandy")

        at_bar = False
        drink_nearby = False

        if self.current_location_id:
            loc = get_location(self.conn, self.current_location_id)
            if loc and any(kw in loc["name"].lower() for kw in _BAR_KEYWORDS):
                at_bar = True
            if not at_bar and self.active_case_id:
                clues = get_clues_for_case(self.conn, self.active_case_id)
                drink_nearby = any(
                    any(kw in c["description"].lower() for kw in _DRINK_KEYWORDS)
                    and (c.get("location") or "").lower() == (loc["name"].lower() if loc else "")
                    for c in clues
                )

        if not at_bar and not drink_nearby:
            console.print("[dim]Nothing to drink here.[/dim]")
            return

        states = get_player_states(self.conn)
        existing = next((s for s in states if s["state"] == "drunk"), None)
        current = existing["intensity"] if existing else 0

        if current >= 3:
            console.print("[dim]You're already as drunk as you're going to get tonight.[/dim]")
            return

        new_intensity = current + 1
        add_player_state(self.conn, state="drunk", intensity=new_intensity)
        messages = [
            "[dim]The glass hits the bar. You drink.[/dim]",
            "[dim]The second one goes down easier than the first.[/dim]",
            "[dim]The third one. The room gets softer at the edges.[/dim]",
        ]
        console.print(messages[new_intensity - 1] + "\n")

    def _npc_relationship_context(self, npc_id: int) -> str:
        affection = get_npc_affection(self.conn, npc_id)
        stage = _affection_to_stage(affection)
        return (
            f"[Relationship: {stage}. React accordingly — a cold NPC is dismissive or wary, "
            "curious is intrigued but guarded, warm is genuinely friendly, "
            "smitten is visibly affected and conflicted, "
            "devoted has made a choice and will protect this person.] "
        )

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

        self._set_active_case(case_id)
        self._seed_case_locations_and_npcs(case_id, case_data, fixed)
        self._seed_fixed_npcs(case_id)
        self._start_background_enrichment(case_id)

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

    def _check_terminal_width(self) -> None:
        import shutil
        import sys
        from rich.console import Console
        MAP_WIDTH = 94
        if shutil.get_terminal_size().columns > MAP_WIDTH:
            return
        label = "NOIRLEANS"
        ruler = "─" * ((MAP_WIDTH - len(label)) // 2) + label + "─" * ((MAP_WIDTH - len(label) + 1) // 2)
        while True:
            # Fresh console each time so Rich reads the current terminal width
            c = Console()
            c.clear()
            c.print(f"\n[dim yellow]{ruler}[/dim yellow]\n")
            if shutil.get_terminal_size().columns > MAP_WIDTH:
                c.print("[green]Good — your terminal is wide enough. Press Enter to continue.[/green]")
                input()
                break
            c.print(
                "[yellow]Your terminal is too narrow for the map. "
                "Widen your window until the line above fits on one row, then press Enter.[/yellow]"
            )
            input()

    def loop(self) -> None:
        show_splash()
        enable_game_padding()
        create_schema(self.conn)
        self._check_terminal_width()
        from noir.neighborhoods import seed_bartenders
        seed_bartenders(self.conn, self.llm)
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
            import noir.audio as audio
            _sex = getattr(self.companion, "sex", "female")
            audio.register_voice(self.companion.name, audio._pick_voice(self.companion.name, female=_sex != "male"))
        else:
            self.companion = Companion.load(conn=self.conn, llm=self.llm)
            import noir.audio as audio
            _sex = getattr(self.companion, "sex", "female")
            audio.register_voice(self.companion.name, audio._pick_voice(self.companion.name, female=_sex != "male"))
            console.print("\n[bold yellow]Welcome back, detective.[/bold yellow]")

        active_cases = get_active_cases(self.conn)
        if not active_cases:
            active_cases = self.conn.execute(
                "SELECT * FROM cases WHERE status='in_trial' ORDER BY id DESC"
            ).fetchall()
        resuming = bool(active_cases)
        if not active_cases:
            self.start_new_case()
        else:
            self._set_active_case(active_cases[0]["id"])
            self._seed_fixed_npcs(self.active_case_id)
            self.world = World(conn=self.conn, active_case_id=self.active_case_id)
            self.case_manager = CaseManager(conn=self.conn, case_id=self.active_case_id, llm=self.llm)
            case = get_case(self.conn, self.active_case_id)
            console.print(f"\n[bold red]Active case: {case['title']}[/bold red]")
            _cd = json.loads(case["case_data"]) if case["case_data"] else {}
            _victim = _cd.get("victim", {})
            if _victim.get("name") and _victim.get("cause_of_death"):
                console.print(
                    f"[italic]Victim: {_victim['name']} — {_victim['cause_of_death']}[/italic]\n"
                )
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
                    + (f"What you know about them: {'; '.join(dossier_lines)}. " if dossier_lines else "")
                    + "] "
                    f"Give a sharp, in-character recap based ONLY on what has already been discovered — "
                    f"do not reference people, locations, or evidence not listed above. "
                    f"One specific thing we should do next, drawn from what we already know. "
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
                loc_orgs = [r["name"] for r in get_organizations_for_location(self.conn, start_loc_id)]
                show_location(loc["name"], loc["description"],
                              [_npc_display_name(n) for n in npcs],
                              game_time=get_game_time(self.conn), orgs=loc_orgs)

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
            if slug == "/location":
                self.handle_slash_look()
                continue
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

            if cmd.intent == Intent.MAP:
                self.handle_map()
            elif cmd.intent == Intent.GO:
                self.handle_go(cmd.target)
            elif cmd.intent == Intent.GO_DA:
                self.handle_go("The DA's Office")
            elif cmd.intent == Intent.GO_COURTHOUSE:
                self.handle_go_courthouse()
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
                        loc_orgs = [r["name"] for r in get_organizations_for_location(self.conn, self.current_location_id)]
                        show_location(loc["name"], loc["description"],
                                      [_npc_display_name(n) for n in npcs],
                                      game_time=get_game_time(self.conn), orgs=loc_orgs)
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
                    elif self.companion:
                        _evidence_rejection_quip(self.companion.name, "Already collected" in result["message"], result.get("reason"), result.get("matched_desc"))
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
                            self.handle_go("The DA's Office")
                        elif action == "GO" and target.lower().strip() in _COURTHOUSE_TERMS:
                            self.handle_go_courthouse()
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
                                elif self.companion:
                                    _evidence_rejection_quip(self.companion.name, "Already collected" in res["message"], res.get("reason"), res.get("matched_desc"))
                        elif action == "TALK":
                            _TALK_TRIGGERS = ("/talk", "talk to", "go talk", "let's talk", "speak to", "find ")
                            if any(cmd.raw.lower().startswith(t) for t in _TALK_TRIGGERS):
                                self.handle_talk(target)
                else:
                    console.print(f"[dim]'{cmd.raw}' — not sure what to do with that.[/dim]")
