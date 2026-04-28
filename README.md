# Noir-Leans

A terminal-based detective RPG set in Noirleans, Louisiana — 1935. The Depression is on. Everyone is broke. Someone is always dead.

You are a detective navigating a city riddled with corrupt institutions, rival crime families, union politics, and moral ambiguity. Cases are procedurally generated. NPCs have secrets, schedules, and psychology. Every conversation is live dialogue powered by Claude.

---

## Features

**Investigation**
- Procedurally generated mystery cases drawn from archetypes (Chandler, Hammett, Christie, Chinatown, and more)
- NPC interrogation with psychology-driven responses — guilt, pressure tolerance, revelation arcs
- Evidence collection and LLM-evaluated admissibility
- Arrest, prosecution, and trial system with dynamic judges

**World**
- 100 seeded locations across Noirleans with faction control and neighborhood adjacency
- NPCs with daily schedules and appointment system — who's where depends on the time
- Two rival crime families, a corrupt police department, unions, the church, the press, and more
- Game time advances as you travel and investigate

**Partner**
- A persistent companion with an affection score, relationship memory, and a dark past
- Narrates arrivals, offers strategy, and reacts to how you handle cases
- Emotional-arc summaries only — never hallucinates plot facts into her memory

**Jobs & Factions**
- Side jobs from factions (surveillance, debt collection, skip trace, and more)
- Faction reputation system with opposition mechanics and escalation
- Player inventory: camera, film, lockpicks, revolver, ammo, bribe envelopes, disguise kit
- Earn cash, spend it at Treme Pawn & Loan

**Presentation**
- Thunderstorm title sequence with terminal text effects
- Rain effect during travel animation
- Typewriter dialogue, Rich panels, atmospheric location displays

---

## Requirements

- Python 3.11+
- The [`claude` CLI](https://claude.ai/code) installed and authenticated (used for all LLM calls)

---

## Installation

```bash
pip install -e "."
```

**Optional: audio (Kokoro TTS, per-NPC voices)**
```bash
pip install -e ".[audio]"
```

**Optional: semantic memory (sentence-transformer embeddings)**
```bash
pip install -e ".[memory]"
```

**Dev tools (pytest, hot-reload)**
```bash
pip install -e ".[dev]"
```

---

## Running

```bash
# Start the game
python main.py

# Reset save data and start fresh
python main.py --reset

# Hot-reload on code changes (requires jurigged)
python main.py --dev
```

---

## Configuration

On first run, a config file is created at `~/.noir_detective/config.json`:

```json
{
  "backend": "claude_cli",
  "dialogue_model": "sonnet",
  "structured_model": "sonnet"
}
```

To use a local Ollama model instead:

```json
{
  "backend": "ollama",
  "model": "qwen2.5:14b",
  "host": "http://localhost:11434"
}
```

Save data lives at `~/.noir_detective/game.db`.

---

## Commands

In-game commands are natural language. The parser understands things like:

```
go to rossi's
talk to the barkeep
examine the envelope
arrest hortense delacroix
```

Slash commands for game systems:

| Command | Description |
|---|---|
| `/case` or `/job` | Show active case or job |
| `/leads` | List current leads |
| `/evidence` | Show collected evidence |
| `/suspects` | Review suspect dossier |
| `/location` | Re-display current location |
| `/locations` | List all known locations |
| `/map` | ASCII map with faction control |
| `/classifieds` | Browse available jobs |
| `/items` | Check inventory |
| `/use <item> <action>` | Use an item |
| `/done` | Submit case for completion |
| `/dropjob` | Abandon active job |
| `/rep` | Faction reputation |
| `/status` | Player stats and alignment |
| `/wait` | Advance time |
| `/help` | Full command list |

---

## Architecture

```
main.py                  Entry point
noir/
  game.py                Game loop, command dispatch, all handlers
  parser.py              Rule-based intent parsing
  world.py               NPC location resolution
  llm/                   LLM backends (Claude CLI, Ollama, Mock)
  characters/            Agent base class, NPC, Companion
  mystery/               Case generation and validation
  cases/                 Evidence, arrest, trial logic
  jobs/                  Job generation, faction system
  persistence/           SQLite schema, migrations, repository
  memory/                Semantic embedding worker (optional)
  audio/                 Kokoro TTS (optional)
  onboarding/            New game quiz and partner generation
  display.py             All terminal rendering
```

All LLM interaction goes through `LLMBackend` — the game shells out to the `claude` CLI via subprocess rather than using the SDK directly. Structured calls use `--output-format json` with automatic retry on parse failure.

---

## Testing

```bash
pytest
```

Tests use an in-memory SQLite database and `MockLLMBackend` — no LLM calls, no disk state. 529 tests.

```bash
pytest tests/test_step.py          # single file
pytest tests/test_step.py::test_name  # single test
```

---

## Setting

Noirleans, six weeks after the assassination of Governor Howie Short. Two crime families divide the city. The police are on someone's payroll. The unions are the only integrated institutions in town. The church keeps its own counsel.

It is not a clean city. You are not a clean detective. Do what you can with what you have.
