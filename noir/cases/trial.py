import json
import random
import sqlite3
from noir.llm.base import LLMBackend
from noir.persistence.repository import (
    update_case_status, get_case, append_history, get_history,
    update_player_reputation, update_player_stats, get_player, get_game_time,
    get_evidence_for_case, get_all_dossier, update_da_trust, get_faction_rep,
    get_accepted_bribes_for_case, update_player_cash,
)

DA_CHARACTER_ID = "da"
CLERK_CHARACTER_ID = "clerk"
MAGISTRATE_CHARACTER_ID = "magistrate"

# How each judge's character shapes verdicts — passed to the verdict LLM
_JUDGE_TRAITS = {
    "Judge Clement Arceneaux": (
        "machine loyalist; creates procedural obstacles for cases involving political allies; "
        "fair when no political pressure exists"
    ),
    "Judge Patrick Flannery": (
        "harsh sentencer; genuine hatred of crime families — unusually likely to convict mob members; "
        "racially biased against Black defendants, likely to convict on thin evidence"
    ),
    "Judge Octave Beaumont": (
        "procedurally strict; suppresses evidence on technical grounds; "
        "will acquit if the state's procedure was sloppy regardless of guilt"
    ),
    "Judge Thomas Callahan": (
        "functional alcoholic; morning sessions sharp, afternoon sessions drift toward the prosecution; "
        "outcomes are inconsistent and somewhat random"
    ),
    "Judge Pierre Lacoste": (
        "ambitious; fair in cases that might be reported in the papers; "
        "expedient and pro-prosecution in cases no one is watching"
    ),
    "Judge Antoine Bergeron": (
        "openly corrupt; has an established rate with both crime families; "
        "significantly more likely to acquit when organized crime is involved"
    ),
    "Judge Raymond Hebert": (
        "genuinely principled; follows the law as written; "
        "less susceptible to political or org pressure than any other judge; "
        "will acquit on procedural grounds but not political ones"
    ),
    "Judge Cornelius Flynn": (
        "former ward enforcer; respects clean solid cases; "
        "harsh on thin charges; moderate susceptibility to org influence"
    ),
    "Judge Emile Tureaud": (
        "young and deferential; follows DA recommendations closely; "
        "gives prosecution benefit of the doubt; low susceptibility to defense pressure"
    ),
    "Judge Walter Broussard": (
        "elderly, unreliable memory; confuses defendants and witnesses; "
        "outcomes are genuinely random — his competence is not reliable"
    ),
    "Judge Sebastiano Marino": (
        "backed by the Rossi crime family specifically; "
        "highly likely to acquit Rossi-connected defendants; "
        "normal susceptibility for all other cases"
    ),
}

DA_SYSTEM_PROMPT = """You are the District Attorney of Noirleans, 1935.

You are a political creature first, a lawyer second. You decide which cases to prosecute based on
what is good for your career — not what is just. You operate within the corrupt machinery of
Depression-era Louisiana and you know exactly how it works.

Your calculus when evaluating an arrest:
- A detective with a strong reputation brings you winners. A detective with a weak reputation
  brings you embarrassments. Adjust your willingness accordingly.
- A detective's DA trust score reflects how often they have brought you solid, verified evidence
  versus fabricated or unsubstantiated claims. Low DA trust means you scrutinize every piece.
- Wealthy suspects and politically connected suspects have lawyers, friends in high places, and
  the ability to make your life difficult. You need ironclad evidence before touching them.
- Suspects with no money, no connections, no political protection — you will prosecute these
  cases on almost any charge the detective names. Juries in this city convict who they want
  to convict, and nobody important will complain. This is the system you work in.
- The charges themselves matter less than whether you think you can win.

You are also evaluating the quality of each evidence item against the dossier facts provided.
Some evidence items may be fabricated or unsupported — you do not always catch this, but when
something contradicts what witnesses actually said or cannot be verified, flag it by name.
You catch fabrications probabilistically — sharp ones maybe 70% of the time, sloppy ones always.

You are not evil — you are practical. You have convinced yourself this is how the world works
and you are simply being realistic. You speak with bureaucratic confidence and occasional
flashes of self-justifying philosophy.

Return ONLY valid JSON: {
  "verdict": "accepted"|"rejected",
  "reasoning": "string",
  "dialogue": "string (your in-character spoken response — call out any flagged items by name)",
  "flagged_evidence": ["item description", ...] (list of specific evidence items you find unsubstantiated — empty list if none)
}"""

CLERK_SYSTEM_PROMPT = """You are the courthouse clerk — a person of indeterminate age who has worked
in this building so long they have become architecturally load-bearing. You know the status of every
trial in this building and report it with the weary precision of someone who has seen it all,
including the time a man was acquitted because the jury found his hat insufficiently sinister.
You speak in a dry, matter-of-fact tone with occasional flashes of unexpected poetry."""

MAGISTRATE_SYSTEM_PROMPT = """You are Magistrate Felix Moreau of the Orleans Parish Criminal Court, 1935.
You handle arraignments, preliminary hearings, and the procedural gate before cases reach trial.
Your job is not to decide guilt — it is to decide whether there is enough probable cause to proceed.

Your standard is low but real: is there an arrest, are there charges, and is there at least some
evidence that a crime occurred and that this person might have done it? You are not the DA.
You do not weigh political considerations. You do not care about connections or influence.
You care about whether the paperwork is in order and whether probable cause exists.

You have seen sixteen years of cases come through this office. You are efficient and dispassionate.
You clear most things the DA sends you. You dismiss cases where the arrest has no evidentiary basis
whatsoever, or where the charges don't fit what the evidence shows.

When you dismiss, you say so plainly and explain the procedural deficiency. When you clear,
you assign the case to a trial judge and note it on the record.

Return ONLY valid JSON: {
  "cleared": true|false,
  "reasoning": "string",
  "dialogue": "string (your in-character spoken response — brief, procedural, matter-of-fact)",
  "assigned_judge": "string (full name of assigned judge, only if cleared — leave null if dismissed)"
}"""


def _suspect_profile(conn: sqlite3.Connection, case_id: int) -> dict:
    """Pull the arrested suspect's details for the DA's consideration."""
    arrest = conn.execute(
        "SELECT npc_id FROM arrests WHERE case_id=? ORDER BY id DESC LIMIT 1", (case_id,)
    ).fetchone()
    if not arrest:
        return {}
    npc = conn.execute("SELECT * FROM npcs WHERE id=?", (arrest["npc_id"],)).fetchone()
    if not npc:
        return {}
    suspect_row = conn.execute(
        "SELECT * FROM suspects WHERE npc_id=?", (arrest["npc_id"],)
    ).fetchone()
    if suspect_row:
        relationships = json.loads(suspect_row["relationships"] or "[]")
        return {
            "name": npc["name"],
            "role": npc["role"],
            "race": suspect_row["race"] or "unknown",
            "political_connections": suspect_row["political_connections"] or "none",
            "relationships": relationships,
        }
    # fallback for old cases without suspects table rows
    case = get_case(conn, case_id)
    case_data = json.loads(case["case_data"])
    for suspect in case_data.get("suspects", []):
        if suspect["name"].lower() == npc["name"].lower():
            return {
                "name": suspect["name"],
                "role": suspect.get("role", ""),
                "race": suspect.get("race", "unknown"),
                "political_connections": suspect.get("political_connections", "none"),
                "relationships": suspect.get("relationships", []),
            }
    return {"name": npc["name"], "role": npc["role"]}


class TrialSystem:

    def __init__(self, *, conn: sqlite3.Connection, case_id: int, llm: LLMBackend):
        self.conn = conn
        self.case_id = case_id
        self.llm = llm

    def submit_to_da(self, *, evidence_summary: str) -> dict:
        arrest = self.conn.execute(
            "SELECT id FROM arrests WHERE case_id=? LIMIT 1", (self.case_id,)
        ).fetchone()
        if not arrest:
            return {
                "verdict": "rejected",
                "reasoning": "No arrest on record.",
                "flagged_evidence": [],
                "dialogue": (
                    "You walk in here with evidence and no body in cuffs? "
                    "I prosecute suspects, detective, not abstractions. "
                    "Arrest someone first. Then come talk to me."
                ),
            }

        player = get_player(self.conn)
        reputation = player["reputation"] if player else 100
        da_trust = get_faction_rep(self.conn, "da_office")
        suspect = _suspect_profile(self.conn, self.case_id)

        connections = ", ".join(
            f"{r['name']} ({r['relationship']})"
            for r in suspect.get("relationships", [])
            if r.get("relationship")
        ) or "none known"

        # Build individual evidence list
        evidence_items = get_evidence_for_case(self.conn, self.case_id)
        evidence_list = "\n".join(
            f"- {e['description']}" for e in evidence_items
        ) or "No evidence collected."

        # Build dossier for cross-checking
        dossier_dict = get_all_dossier(self.conn, case_id=self.case_id)
        dossier_lines = []
        for npc_name, facts in dossier_dict.items():
            for fact in facts:
                dossier_lines.append(f"- {npc_name}: {fact}")
        dossier_text = "\n".join(dossier_lines) or "None."

        # Suspect org memberships
        arrested = self.conn.execute(
            "SELECT npc_id FROM arrests WHERE case_id=? ORDER BY id DESC LIMIT 1",
            (self.case_id,)
        ).fetchone()
        suspect_orgs = []
        if arrested:
            org_rows = self.conn.execute(
                """SELECT o.name, o.type, o.influence, om.role
                   FROM organizations o
                   JOIN organization_members om ON o.id = om.organization_id
                   WHERE om.member_type='npc' AND om.member_id=?
                   ORDER BY o.influence DESC""",
                (arrested["npc_id"],)
            ).fetchall()
            def _influence_label(n: int) -> str:
                if n >= 9: return "dominant citywide power"
                if n >= 7: return "major political/criminal force"
                if n >= 5: return "significant local presence"
                if n >= 3: return "minor faction"
                return "fringe group"
            suspect_orgs = [
                f"{r['name']} ({r['type']}, {_influence_label(r['influence'])}" +
                (f", role: {r['role']}" if r['role'] else "") + ")"
                for r in org_rows
            ]

        history = get_history(self.conn, character_id=DA_CHARACTER_ID)
        political = suspect.get("political_connections", "none")
        detective_gender = player["gender"] if player and player["gender"] != "unspecified" else "unknown"
        org_text = "\n".join(f"- {o}" for o in suspect_orgs) if suspect_orgs else "None known."
        prompt = (
            f"Detective reputation: {reputation}/100. DA trust: {da_trust}/100. Gender: {detective_gender}.\n"
            f"Arrested suspect: {suspect.get('name', 'unknown')}, {suspect.get('role', '')}.\n"
            f"Suspect political connections: {political}.\n"
            f"Suspect personal connections: {connections}.\n"
            f"Suspect organizational memberships (higher influence = more political risk for you):\n{org_text}\n\n"
            f"Evidence submitted (evaluate each item):\n{evidence_list}\n\n"
            f"What witnesses actually said (dossier — use this to verify evidence):\n{dossier_text}\n\n"
            "Decide whether to prosecute. Cross-check evidence against the dossier. "
            "Flag any items that appear fabricated or unsupported. "
            "Apply your real calculus — reputation, DA trust, org influence, connections, political risk. "
            "High-influence org membership means powerful lawyers, favors, and blowback if you lose. "
            "Be honest with yourself about why you're deciding what you're deciding, "
            "even if your dialogue softens it. "
            'Return JSON with verdict, reasoning, dialogue, and flagged_evidence list.'
        )
        result = self.llm.query_structured(DA_SYSTEM_PROMPT, history, prompt)

        append_history(self.conn, character_id=DA_CHARACTER_ID, role="user",
                       content=prompt, case_id=None)
        append_history(self.conn, character_id=DA_CHARACTER_ID, role="assistant",
                       content=result.get("dialogue", ""), case_id=None)

        if result.get("verdict") == "accepted":
            update_case_status(self.conn, case_id=self.case_id, status="pending_magistrate")

        return result

    def submit_to_magistrate(self) -> dict:
        case = get_case(self.conn, self.case_id)
        if case["status"] != "pending_magistrate":
            return {
                "cleared": False,
                "dialogue": "This case hasn't been accepted by the DA yet.",
                "reasoning": "Wrong status.",
            }

        # Check for a prior accepted bribe targeting this magistrate review
        bribes = get_accepted_bribes_for_case(self.conn, self.case_id)
        if any(b["effect"] == "magistrate_clear" for b in bribes):
            duration = random.randint(240, 480)
            end_game_time = get_game_time(self.conn) + duration
            judge_rows = self.conn.execute(
                """SELECT n.id, n.name FROM npcs n
                   JOIN organization_members om ON om.member_id = n.id AND om.member_type='npc'
                   JOIN organizations o ON o.id = om.organization_id
                   WHERE o.name='Orleans Parish Judiciary' AND om.role != 'magistrate'
                   AND n.case_id IS NULL"""
            ).fetchall()
            judge_id, judge_name = None, "a judge"
            if judge_rows:
                chosen = random.choice(judge_rows)
                judge_id, judge_name = chosen["id"], chosen["name"]
            if judge_id:
                self.conn.execute(
                    "UPDATE cases SET assigned_judge_id=? WHERE id=?", (judge_id, self.case_id)
                )
                self.conn.commit()
            update_case_status(self.conn, case_id=self.case_id, status="in_trial",
                               trial_end_time=str(end_game_time))
            return {
                "cleared": True,
                "dialogue": "Everything appears to be in order. Assigned to " + judge_name + ".",
                "reasoning": "Cleared.",
                "assigned_judge": judge_name,
            }

        arrest = self.conn.execute(
            "SELECT id FROM arrests WHERE case_id=? LIMIT 1", (self.case_id,)
        ).fetchone()
        if not arrest:
            return {
                "cleared": False,
                "dialogue": "No arrest on file. I can't arraign a ghost.",
                "reasoning": "No arrest record.",
            }

        evidence_items = get_evidence_for_case(self.conn, self.case_id)
        evidence_list = "\n".join(f"- {e['description']}" for e in evidence_items) or "None."
        suspect = _suspect_profile(self.conn, self.case_id)

        # Build list of available trial judges (exclude magistrate)
        judge_rows = self.conn.execute(
            """SELECT n.id, n.name FROM npcs n
               JOIN organization_members om ON om.member_id = n.id AND om.member_type='npc'
               JOIN organizations o ON o.id = om.organization_id
               WHERE o.name='Orleans Parish Judiciary'
               AND om.role != 'magistrate'
               AND n.case_id IS NULL""",
        ).fetchall()
        judge_names = [r["name"] for r in judge_rows]
        judge_list = "\n".join(f"- {n}" for n in judge_names) or "No judges available."

        history = get_history(self.conn, character_id=MAGISTRATE_CHARACTER_ID)
        prompt = (
            f"Arrested suspect: {suspect.get('name', 'unknown')}, {suspect.get('role', '')}.\n"
            f"Charges supported by evidence:\n{evidence_list}\n\n"
            f"Available trial judges (assign one if cleared):\n{judge_list}\n\n"
            "Determine whether probable cause exists to proceed to trial. "
            "If cleared, assign one judge from the list. Return JSON."
        )
        result = self.llm.query_structured(MAGISTRATE_SYSTEM_PROMPT, history, prompt)

        append_history(self.conn, character_id=MAGISTRATE_CHARACTER_ID, role="user",
                       content=prompt, case_id=self.case_id)
        append_history(self.conn, character_id=MAGISTRATE_CHARACTER_ID, role="assistant",
                       content=result.get("dialogue", ""), case_id=self.case_id)

        if result.get("cleared"):
            assigned_name = result.get("assigned_judge")
            judge_id = None
            if assigned_name:
                row = next((r for r in judge_rows if r["name"] == assigned_name), None)
                if row:
                    judge_id = row["id"]
            # Fall back to random if LLM picked an invalid name
            if judge_id is None and judge_rows:
                chosen = random.choice(judge_rows)
                judge_id = chosen["id"]
                result["assigned_judge"] = chosen["name"]

            duration = random.randint(240, 480)  # 4–8 in-game hours
            end_game_time = get_game_time(self.conn) + duration
            self.conn.execute(
                "UPDATE cases SET assigned_judge_id=? WHERE id=?", (judge_id, self.case_id)
            )
            self.conn.commit()
            update_case_status(self.conn, case_id=self.case_id, status="in_trial",
                               trial_end_time=str(end_game_time))

        return result

    def check_courthouse(self) -> dict:
        case = get_case(self.conn, self.case_id)

        if case["status"] == "pending_magistrate":
            return {"status": "pending_magistrate"}

        if case["status"] == "in_trial" and case["trial_end_time"]:
            try:
                end_game_time = int(case["trial_end_time"])
            except (ValueError, TypeError):
                # Legacy case with real datetime — treat as already elapsed
                end_game_time = 0
            current_game_time = get_game_time(self.conn)
            if current_game_time >= end_game_time:
                verdict = self._generate_verdict(case)
                update_case_status(self.conn, case_id=self.case_id, status="closed",
                                   trial_outcome=json.dumps(verdict))
                return {"status": "closed", "verdict": verdict}
            remaining = end_game_time - current_game_time
            h, m = divmod(remaining, 60)
            time_str = f"{h}h {m}m" if h else f"{m}m"
            return {"status": "in_trial", "minutes_remaining": time_str}

        if case["status"] == "closed":
            return {"status": "closed",
                    "verdict": json.loads(case["trial_outcome"]) if case["trial_outcome"] else {}}

        return {"status": case["status"]}

    def _generate_verdict(self, case: sqlite3.Row) -> dict:
        arrest = self.conn.execute(
            "SELECT was_correct, npc_id FROM arrests WHERE case_id=? ORDER BY id DESC LIMIT 1",
            (self.case_id,)
        ).fetchone()
        was_correct = bool(arrest and arrest["was_correct"])

        # Identify assigned judge and their traits
        judge_name = "unknown judge"
        judge_traits = ""
        if case["assigned_judge_id"]:
            judge_row = self.conn.execute(
                "SELECT name FROM npcs WHERE id=?", (case["assigned_judge_id"],)
            ).fetchone()
            if judge_row:
                judge_name = judge_row["name"]
                judge_traits = _JUDGE_TRAITS.get(judge_name, "")

        # Org influence affects conviction probability — powerful orgs have better lawyers
        max_org_influence = 0
        org_protection_note = ""
        if arrest:
            org_rows = self.conn.execute(
                """SELECT o.influence, o.name FROM organizations o
                   JOIN organization_members om ON o.id = om.organization_id
                   WHERE om.member_type='npc' AND om.member_id=?
                   ORDER BY o.influence DESC LIMIT 1""",
                (arrest["npc_id"],)
            ).fetchone()
            if org_rows:
                max_org_influence = org_rows["influence"]
                if max_org_influence >= 7:
                    acquittal_chance = 0.35
                    org_protection_note = (
                        f" The suspect's affiliation with {org_rows['name']} brought "
                        f"substantial legal resources and political pressure to bear."
                    )
                elif max_org_influence >= 4:
                    acquittal_chance = 0.15
                    org_protection_note = (
                        f" The suspect's connections through {org_rows['name']} complicated the prosecution."
                    )
                else:
                    acquittal_chance = 0.0
            else:
                acquittal_chance = 0.0

            # Even a correct arrest can be acquitted due to org protection
            if was_correct and acquittal_chance > 0 and random.random() < acquittal_chance:
                was_correct = False  # acquitted despite being guilty

        # Check for accepted judge bribe
        bribes = get_accepted_bribes_for_case(self.conn, self.case_id)
        judge_bribed = any(b["effect"] == "verdict_influence" for b in bribes)
        if judge_bribed and not was_correct:
            was_correct = True  # bribed verdict overrides innocence
        bribe_note = " The verdict was influenced by considerations beyond the evidence." if judge_bribed else ""

        # Check if fabricated evidence was flagged by the DA (stored in DA history)
        da_history = get_history(self.conn, character_id=DA_CHARACTER_ID)
        fabrication_note = ""
        # Pull the most recent DA structured response from history to find flagged items
        da_prompts = [m for m in da_history if m["role"] == "user" and "flagged_evidence" in m.get("content", "")]
        # Simpler: check player's DA trust — low trust implies fabrication history
        da_trust = get_faction_rep(self.conn, "da_office")
        fabrication_exposed = da_trust < 90 and random.random() < (1 - da_trust / 100)
        if fabrication_exposed:
            fabrication_note = " Fabricated or unsubstantiated evidence was exposed during the trial."
            update_player_reputation(self.conn, delta=-10)
            update_da_trust(self.conn, delta=-10)

        if was_correct and not fabrication_exposed:
            update_player_stats(self.conn, cases_solved_delta=1)
            update_player_reputation(self.conn, delta=10)
            update_player_cash(self.conn, delta=random.randint(150, 300))
        elif was_correct and fabrication_exposed:
            update_player_stats(self.conn, cases_solved_delta=1)
            update_player_reputation(self.conn, delta=3)
            update_player_cash(self.conn, delta=random.randint(75, 150))
        else:
            update_player_reputation(self.conn, delta=-15)
            update_player_stats(self.conn, wrong_arrests_delta=1)

        case_data = json.loads(case["case_data"])

        defendant_name = "the defendant"
        defendant_role = ""
        if arrest:
            def_row = self.conn.execute(
                "SELECT name, role FROM npcs WHERE id=?", (arrest["npc_id"],)
            ).fetchone()
            if def_row:
                defendant_name = def_row["name"]
                defendant_role = def_row["role"] or ""

        victim = case_data.get("victim", {})
        judge_context = (
            f"Presiding judge: {judge_name}."
            + (f" Character: {judge_traits}." if judge_traits else "")
        )
        prompt = (
            f"Case: {case['title']}\n"
            f"Victim: {victim.get('name', 'unknown')}, cause of death: {victim.get('cause_of_death', 'unknown')}.\n"
            f"THE DEFENDANT ON TRIAL IS: {defendant_name} ({defendant_role}). "
            f"Use this name — do not substitute any other character from the case.\n\n"
            f"{judge_context}\n"
            f"The defendant ({defendant_name}) was {'the actual killer' if was_correct else 'innocent'}."
            f"{fabrication_note}{org_protection_note}{bribe_note} "
            "Generate a trial verdict with absurdist noir courtroom drama. "
            "The judge's character should flavor the narration and their conduct during the trial. "
            "If fabricated evidence was exposed, the judge mentions it acidly. "
            "If org protection influenced the outcome, the clerk notes it with weary resignation. "
            'Return JSON: {"outcome": "guilty"|"not_guilty", '
            '"summary": "string (2-3 sentences of dramatic courtroom narration)"}'
        )
        return self.llm.query_structured(CLERK_SYSTEM_PROMPT, [], prompt)
