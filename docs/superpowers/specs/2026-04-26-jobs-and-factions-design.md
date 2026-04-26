# Jobs and Faction System Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a parallel job system to Noirleans where the player can take work from 20 factions, earning faction-specific reputation that gates deeper and more dangerous jobs. Jobs run alongside or between murder cases using the existing `cases` infrastructure extended with a `'job'` case type.

**Architecture:** Extend `cases` table with `faction`, `tier`, `payout` nullable columns and a new `case_type='job'` value. Add a `faction_reputation` table keyed by faction slug. Fold existing `da_trust` player stat into DA's Office faction reputation. Jobs use the existing NPC conversation, location travel, leads, and history systems — no new conversation infrastructure needed. Job generation mixes hand-authored archetypes with LLM-filled specifics.

**Tech Stack:** SQLite (schema migration), Python (repository layer, game.py, new job generator), existing LLM structured-output pattern for NPC job detection.

---

## Factions

### Complete Faction List

| Slug | Display Name | Type | Influence |
|------|-------------|------|-----------|
| `da_office` | DA's Office | government | 8 |
| `nopd` | New Orleans Police Department | government | 7 |
| `parish_govt` | Orleans Parish Government | government | 8 |
| `state_govt` | Louisiana State Government | government | 9 |
| `judiciary` | Orleans Parish Judiciary | government | 7 |
| `shorties` | Shorties | political | 8 |
| `tallboys` | Tallboys | political | 6 |
| `chamber` | Chamber of Commerce | political | 7 |
| `naacp` | NAACP | civic | 5 |
| `rossi` | Rossi Crime Family | crime_family | 8 |
| `castellano` | Castellano Crime Family | crime_family | 6 |
| `ila_231` | ILA Local 231 | union | 5 |
| `colored_longshoremen` | Colored Longshoremen's Association | union | 3 |
| `archdiocese` | Archdiocese of New Orleans | church | 6 |
| `athletic_club` | New Orleans Athletic Club | fraternal | 7 |
| `knights_columbus` | Knights of Columbus | fraternal | 4 |
| `treme_club` | Treme Social Aid and Pleasure Club | fraternal | 3 |
| `bar_association` | Noirleans Bar Association | professional | 5 |
| `press` | The Press | press | 5 |
| `private` | Private Client | none | — |

`private` is not a faction — no reputation tracked, cash-only one-off jobs.

### Faction Opposition Matrix

Working for faction A hurts standing with opposing factions. Rep penalty: **-8 per job completed** for direct oppositions, **-4** for secondary oppositions.

| Faction | Direct Opposition | Secondary Opposition |
|---------|------------------|---------------------|
| Rossi | Castellano | NOPD, DA's Office |
| Castellano | Rossi | NOPD, DA's Office |
| Shorties | Tallboys | — |
| Tallboys | Shorties, NAACP | Treme Social Aid, Colored Longshoremen's |
| Chamber | ILA 231, Colored Longshoremen's | NAACP, Treme Social Aid |
| NOPD | Rossi, Castellano | NAACP, Treme Social Aid |
| DA's Office | Rossi, Castellano | — |
| NAACP | Tallboys, Chamber | NOPD |
| ILA 231 | Chamber | — |
| Colored Longshoremen's | Chamber | — |
| Treme Social Aid | NOPD, Chamber | Tallboys |

All other faction pairs are neutral — working for both simultaneously carries no penalty.

**Note on Shorties ↔ NAACP:** Neutral. The Short machine's populist programs benefited all residents regardless of race; Short deliberately avoided making race political to maintain his coalition. Working for the Shorties does not hurt NAACP standing.

**Note on Tallboys:** The Tallboys coalition includes KKK-affiliated members who lost political power during the Short years and feel entitled to reclaim it. Working for the Tallboys is a direct hit to NAACP standing and secondary hit to Treme Social Aid and Colored Longshoremen's.

---

## Schema Changes

### `cases` table — three new nullable columns

```sql
ALTER TABLE cases ADD COLUMN faction TEXT;
ALTER TABLE cases ADD COLUMN tier INTEGER;
ALTER TABLE cases ADD COLUMN payout INTEGER;
```

`case_type` already exists. Add `'job'` as a valid value alongside `'standard'` and `'partner_dark_past'`.

`case_data` JSON for jobs uses this shape:
```json
{
  "objective": "Find out if Beaumont is meeting with the union organizer",
  "job_archetype": "surveillance",
  "client_npc_name": "name of NPC who hired the detective",
  "target": "person or thing being tracked/found/retrieved",
  "steps": [
    {"id": 1, "description": "Establish Beaumont's evening schedule", "completed": false},
    {"id": 2, "description": "Tail him to the meeting location", "completed": false},
    {"id": 3, "description": "Report back to contact", "completed": false}
  ],
  "resolution_condition": "report_to_client",
  "moral_weight": "low"
}
```

`moral_weight`: `"low"` | `"medium"` | `"high"`. High moral weight jobs trigger partner commentary on completion.

### New `faction_reputation` table

```sql
CREATE TABLE faction_reputation (
    faction TEXT PRIMARY KEY,
    reputation INTEGER NOT NULL DEFAULT 0
);
```

Seeded at startup with all 19 faction slugs at reputation 0. `private` is not seeded (no rep tracked).

### `da_trust` migration

`player.da_trust` is deprecated. On startup, if `da_trust` > 0 and `faction_reputation` row for `da_office` is 0, copy `da_trust` value into `faction_reputation`. All existing `update_da_trust` / `get_da_trust` calls in the codebase route through new `get_faction_rep` / `update_faction_rep` repository functions with `faction='da_office'`.

### New `job_offers` table

```sql
CREATE TABLE job_offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    npc_id INTEGER NOT NULL,
    case_id INTEGER,
    offered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    accepted INTEGER DEFAULT 0,
    FOREIGN KEY (npc_id) REFERENCES npcs(id),
    FOREIGN KEY (case_id) REFERENCES cases(id)
);
```

Stores pending job offers from NPC conversations. `case_id` is set when the player accepts (job case created). `accepted=0` means pending; `accepted=1` means taken; `accepted=-1` means declined.

---

## Tier System

| Tier | Rep Required | Depth | Approx. Time | Payout Range |
|------|-------------|-------|-------------|-------------|
| 1 | 0 | 2–3 conversations, 1–2 locations | ~10 min | $25–$75 |
| 2 | 25 | 3–4 locations, small clue chain, moral choice | ~30 min | $100–$250 |
| 3 | 60 | Multi-session, city consequences | variable | $400–$1000+ |

Rep earned per completed job: +8 (tier 1), +20 (tier 2), +40 (tier 3). Rep lost on failure or betrayal: -10 (tier 1), -20 (tier 2), -40 (tier 3).

Tier 3 jobs have city-level consequences stored as tags in street_reputation or a new `city_state` table (designed separately). Faction power shifts — if the player repeatedly sides with one faction against another, named NPCs change, job availability shifts, and persistent NPCs react.

---

## Job Archetypes

Hand-authored templates. The job generator picks an archetype and fills in NPC names, locations, and specifics using an LLM call.

### Tier 1

| Archetype | Description | Typical Faction |
|-----------|-------------|----------------|
| `skip_trace` | Find a missing person and report their location | Any |
| `message_delivery` | Carry something to someone without being seen or stopped | Crime families, political |
| `surveillance` | Watch a location or person for one game-time period, report back | Any |
| `serve_papers` | Deliver legal notice to an NPC who doesn't want to receive it | DA's Office, Bar Association |
| `cheating_spouse` | Confirm or deny a client's suspicion about their partner | Private |
| `debt_collection` | Recover money owed, using persuasion or pressure | Crime families |

### Tier 2

| Archetype | Description | Typical Faction |
|-----------|-------------|----------------|
| `evidence_retrieval` | Get something incriminating before someone else does | DA's Office, crime families |
| `stolen_property` | Recover an object; choose who gets it back | Private, crime families |
| `witness_protection` | Keep an NPC safe through a conversation chain | DA's Office, NAACP |
| `dig_up_dirt` | Find compromising information on a target; decide what to do with it | Political, press |
| `union_job` | Union-assigned: protect a worker, expose a scab, or document violations | ILA 231, Colored Longshoremen's |
| `shadow_operation` | Tail a target across multiple locations over one game day | NOPD, political |

### Tier 3

| Archetype | Description | Typical Faction |
|-----------|-------------|----------------|
| `faction_power_play` | Actions that shift which faction controls a key city role or location | Any |
| `arc_mission` | Multi-step job evolving over several cases; introduces recurring named NPCs | Any |
| `exposure` | Expose a corrupt figure publicly; consequences ripple through city | Press, NAACP |
| `cover_up` | Bury evidence or silence witnesses to protect a faction's interests | Crime families, political |

---

## How Jobs Surface

### Job Board (`/jobs`)

Lists all available jobs filtered by:
1. Player's faction rep meets tier threshold for that faction
2. Job is not already active

Display format:
```
[Tier 1] Skip Trace — Rossi Crime Family — $50
  Find a man named Vitale who skipped out on a debt. Report back to Sal.

[Tier 2] Dig Up Dirt — The Press — $150
  A city councilman is hiding something. Find out what before the morning edition.
```

Jobs on the board are pre-generated at game start and replenished when the player completes or declines them.

### NPC Offers During Case Work

After any NPC dialogue response, a lightweight LLM structured call checks:
```json
{"job_offered": true|false, "job_type": "string|null", "faction_hint": "string|null"}
```

This reuses the existing bribe-detection pattern. If `job_offered: true`, the game surfaces:
```
[NPC name] has work for you. Interested? (yes/no)
```

If yes: creates a job case, links it to `job_offers`, activates immediately.
If no: stores in `job_offers` with `accepted=-1`.

Any NPC can offer tier 1 jobs regardless of faction rep. Tier 2+ requires:
- NPC has an `organization_id` FK to a faction
- Player's rep with that faction ≥ 25

### Re-visiting Declined Offers

`/jobs --pending` shows offers the player declined. Player can revisit and accept within 3 in-game days of the offer.

---

## Job Resolution

Jobs close when the player completes all steps and reports back to the client NPC. Two paths:

1. **`/done` command** while a job is active — triggers a short conversation with the client NPC confirming completion. LLM judges whether the objective was actually met.
2. **Auto-detect** — if the client NPC's conversation response signals completion ("you did what I asked", "that's all I needed"), the game auto-closes the job.

On resolution:
- Cash payout added to `player.cash`
- Faction rep delta applied to `faction_reputation`
- Opposition faction rep penalties applied
- `law_chaos` and `good_evil` shift based on `moral_weight`
- If `moral_weight='high'`, partner comments in the next available moment

On failure (player abandons, time expires for time-sensitive jobs, or LLM judges objective unmet):
- No payout
- Faction rep penalty
- Client NPC relationship sours

---

## Cross-Faction Tension

When the player holds rep ≥ 40 with two directly opposing factions, a tension event fires on the next location transition. Tension events are NPC confrontations — a faction contact pulls the player aside and makes it clear they've noticed. The player must either:

- Reassure the faction (costs a favor, small rep gain with them)
- Dismiss them (small rep loss with them, no consequence otherwise)
- Make a choice (drop one faction's active jobs, larger rep gain with the other)

Tension events are not instant game-enders — they're narrative pressure. The player can maintain dangerous positions indefinitely, but tension events become more frequent and stakes escalate at rep ≥ 60 with opposing factions.

---

## Repository Functions (new/changed)

```python
# New
def get_faction_rep(conn, faction: str) -> int
def update_faction_rep(conn, faction: str, delta: int) -> int  # returns new value
def get_all_faction_reps(conn) -> dict[str, int]
def seed_faction_reputation(conn) -> None
def create_job(conn, *, faction: str, tier: int, title: str, payout: int, case_data: dict) -> int
def get_active_jobs(conn) -> list[sqlite3.Row]
def get_available_jobs(conn) -> list[sqlite3.Row]  # filtered by faction rep
def create_job_offer(conn, *, npc_id: int) -> int
def accept_job_offer(conn, *, offer_id: int, case_id: int) -> None
def get_pending_job_offers(conn) -> list[sqlite3.Row]
def complete_job(conn, *, case_id: int, payout: int, faction: str, tier: int) -> None
def fail_job(conn, *, case_id: int, faction: str, tier: int) -> None

# Changed
def get_da_trust(conn) -> int          # now calls get_faction_rep(conn, 'da_office')
def update_da_trust(conn, delta: int)  # now calls update_faction_rep(conn, 'da_office', delta)
```

---

## Testing Strategy

All tests are behavioral — they test what the system does, not how it's implemented. No mocking of repository internals.

### Faction reputation tests
- Creating faction rep table seeds all 19 factions at 0
- Completing a job increases rep with that faction
- Completing a job for Rossi decreases rep with Castellano and NOPD
- Working for Shorties does not affect NAACP rep
- Working for Tallboys decreases NAACP rep
- `da_trust` migration: existing da_trust value appears in DA's Office faction rep

### Job lifecycle tests
- Creating a job case stores faction, tier, payout
- `/jobs` shows only jobs the player's rep qualifies for
- Completing all steps and reporting back resolves the job and pays out
- Failing a job applies rep penalty, no payout
- NPC job offer detection creates a pending offer record
- Declining an offer stores it as declined; player can revisit within 3 game-days

### Cross-faction tension tests
- Tension fires when player holds ≥ 40 rep with two directly opposing factions
- Tension does not fire for neutral faction pairs (Shorties + NAACP)
- Tension escalates at ≥ 60 rep

---

## Out of Scope (this spec)

- City-state consequences for tier 3 jobs (designed separately)
- Job board UI beyond `/jobs` text list
- Recurring named NPCs for arc missions (tier 3 archetypes defined here; implementation deferred)
- Voice/audio for job offer moments
