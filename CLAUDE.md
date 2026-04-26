# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

**Noir-Leans** is a terminal-based detective RPG set in New Orleans, 1935 (called "Noirleans"). The player is a detective who solves procedurally generated mystery cases, interrogates NPCs, collects evidence, and eventually makes an arrest. A persistent partner character accompanies the player and develops a relationship over time.

The game runs by shelling out to the `claude` CLI for all LLM calls — it does not use the Anthropic SDK directly.

## Commands

```bash
# Run the game
python main.py

# Run with hot-reload (requires jurigged)
python main.py --dev

# Reset the database
python main.py --reset

# Run all tests
pytest

# Run a single test file
pytest tests/test_step.py

# Run a specific test
pytest tests/test_step.py::test_name

# Install dev dependencies
pip install -e ".[dev]"

# Install optional audio (Kokoro TTS)
pip install -e ".[audio]"

# Install optional semantic memory (sentence-transformers)
pip install -e ".[memory]"
```

## Configuration

Config lives at `~/.noir_detective/config.json`. The game creates it on first run with defaults:

```json
{
  "backend": "claude_cli",
  "dialogue_model": "sonnet",
  "structured_model": "sonnet"
}
```

Switch to Ollama by setting `"backend": "ollama"` and optionally `"model"` and `"host"`.

The SQLite database lives at `~/.noir_detective/game.db`. The repo-root `*.db` files are test/scratch databases and should not be committed.

## Architecture

### Entry & Game Loop

`main.py` → `noir/game.py (Game.loop())` is the top-level interactive loop. `Game` owns the SQLite connection, the LLM backend, and all subsystems. Every player command flows through `noir/parser.py` (rule-based → `Intent` enum), then dispatched inside `Game.loop()`.

### LLM Layer (`noir/llm/`)

All LLM interaction goes through `LLMBackend` (abstract, `base.py`). Two real backends exist:
- `ClaudeCLIBackend` — shells out to the `claude` CLI via subprocess. Dialogue calls use plain text prompts; structured calls add `--output-format json` and prepend `_JSON_SYSTEM_PREAMBLE` to suppress skill/tool invocations from superpowers.
- `OllamaBackend` — REST calls to a local Ollama server.

`LLMBackend.query_structured()` wraps any backend call to ensure JSON output, with one automatic retry on parse failure.

`MockLLMBackend` (`mock.py`) is used in all tests — it returns configurable canned responses.

### Characters (`noir/characters/`)

- `Agent` (base) — history management, summary compression, LLM calls.
- `NPC(Agent)` — case NPCs. Psychology-driven responses; revelation stages track how much guilt/secrets an NPC has revealed.
- `Companion(Agent)` — the partner. Has an affection score, relationship notes, and a dark-past mechanic. Summarizes conversations into emotional-only summaries (no factual content).

### Persistence (`noir/persistence/`)

- `db.py` — schema definition, migration runner (`_MIGRATIONS` list), `get_connection()`. The DB lives at `~/.noir_detective/game.db`.
- `repository.py` — all SQL access. No ORM; every function takes a `conn` argument.

Schema migrations are additive `ALTER TABLE` statements in `_MIGRATIONS`. Run `create_schema(conn)` to apply them (safe to call on existing DBs — errors are silently swallowed for already-applied migrations).

### Mystery Generation (`noir/mystery/`)

`MysteryGenerator` generates a complete case (suspects, clues, locations, NPC system prompts) using a single LLM call seeded by a mystery archetype. Archetypes live in `archetypes.json` and are seeded into the DB on startup. The `auditor.py` validates generated mysteries for logical consistency.

### Cases (`noir/cases/`)

`CaseManager` handles evidence collection and admissibility validation, arrests, and trial logic. Evidence admissibility is LLM-evaluated against clues, dossier facts, and conversation history.

### World (`noir/world.py`)

`World` resolves which NPCs are at which locations at the current game time, factoring in NPC schedules and appointments made during conversations.

### Optional Systems

- `noir/audio/` — Kokoro TTS with per-NPC voice assignment by ethnicity/gender. Disabled with `--no-audio`.
- `noir/memory/` — sentence-transformer embeddings for conversation history (semantic retrieval). Disabled with `--no-memory`. Uses a background worker thread.
- `noir/onboarding/` — new-game quiz that sets player race/gender/alignment and generates the partner.

### Testing

Tests use `pytest` with an in-memory SQLite DB (`:memory:`) via the `db` fixture in `conftest.py`, and `MockLLMBackend` for all LLM calls. The `step.py` module (`noir/step.py`) provides a single-turn execution interface used by automated playthrough agents in `agents/`.

## Hard Rules

- **Always do TDD.** Write the test first, watch it fail, then write the minimum implementation to make it pass.
- **Tests must never test implementation.** Test observable behavior and outcomes only — not internal method calls, private state, or how something is done. If a refactor breaks a test without changing behavior, the test was wrong.

## Key Conventions

- All structured LLM calls must return `{"key": value}` JSON — the backend handles retry on parse failure. System prompts for structured calls should end with `Return ONLY valid JSON: {...}`.
- NPC dialogue must never break character (period: 1935), use modern slang, invent phone numbers, or reference other characters by name unless they appear in the provided context.
- The `_CHARACTER_LOCK` constant in `noir/characters/agent.py` is prepended to every NPC/companion system prompt — it encodes all hard character rules.
- `conversation_summaries` stores emotional-arc summaries only (no factual claims, no names) to avoid contaminating the partner's memory with hallucinated plot facts.
