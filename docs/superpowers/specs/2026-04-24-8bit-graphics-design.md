# 8-bit Terminal Graphics — Design Spec

**Date:** 2026-04-24  
**Status:** Approved

---

## Overview

Add dynamically generated 8-bit pixel art to the terminal game. The LLM generates sprites as structured JSON (palette + pixel grid); a renderer converts them to terminal output using Unicode half-block characters and ANSI truecolor. Sprites are cached in SQLite to avoid redundant LLM calls. Art appears at two sizes: compact character portraits and larger scene banners.

---

## Architecture

Three new components:

### `noir/display/pixel_art.py` — Renderer
- Accepts a `Sprite` dataclass: `width`, `height`, `palette: list[str]` (hex), `pixels: list[list[int]]`
- Renders using `▀`/`▄` half-block characters + ANSI truecolor escape codes
- Two pixel rows collapse into one terminal row
- Portrait size: 16×16 pixels → 8 terminal rows
- Scene size: 48×24 pixels → 12 terminal rows, centered
- Exposes `show_portrait(sprite)` and `show_scene(sprite)` — both integrated into `noir/display.py`

### `noir/llm/sprite_gen.py` — Generator
- Calls the structured model (haiku) with a prompt describing the subject and requesting a noir-palette 8-bit sprite
- Portrait prompt requests 16×16; scene prompt requests 48×24
- JSON schema enforces `palette` (up to 16 hex strings) and `pixels` (2D array of ints 0–15)
- Returns a validated `Sprite` or `None` on failure
- 3-second timeout; any failure silently skips art — game never stalls

### Sprite Cache (SQLite)
- New `sprites` table: `(key TEXT PRIMARY KEY, palette TEXT, pixels TEXT, created_at TEXT)`
- Cache key: `sha256(description + size_tag)` where `size_tag` is `"portrait"` or `"scene"`
- On cache hit: render directly, no LLM call
- Managed via `noir/persistence/repository.py`

---

## LLM Prompt

The prompt uses few-shot examples to anchor style and output format.

```
Draw an 8-bit pixel art sprite in the style of a 1935 noir detective game.
Subject: {description}
Return a JSON object with:
  - "palette": array of up to 16 hex color strings (dark, moody noir palette)
  - "pixels": 2D array of integers 0–15 indexing the palette
Size: {width}×{height}

Here are reference examples of good output:
{examples}
```

Validation: dimensions must match declared size; all pixel values must be valid palette indices. Invalid output → `None` → silent skip.

---

## Reference Examples

Fixed example sprites ship with the game as JSON files in `noir/data/sprites/examples/`. They are loaded at startup and injected into every sprite generation prompt.

**Bootstrap process (one-time, pre-ship):**
1. Build the renderer first so output is visible in the terminal.
2. Run a standalone script (`scripts/gen_example_sprites.py`) that generates candidate sprites for a small set of archetypal subjects (e.g., a hard-boiled detective, a femme fatale, a rain-soaked alley, a smoky bar).
3. Iterate on the prompt and review rendered output until quality is acceptable.
4. Promote the best results to `noir/data/sprites/examples/` as static JSON files.

Examples are separated by size: `examples/portrait/` and `examples/scene/`. The generator loads 1–2 examples of the matching size for each prompt. Examples are never regenerated at runtime.

---

## Display Integration

### Character portrait (compact)
- **Trigger:** start of every NPC conversation
- **Where:** `show_conversation_header()` in `noir/display.py`
- **Data:** NPC description (already available at conversation start)
- **Render:** `show_portrait(sprite)` above the existing header rule

### Scene banner (larger)
- **Trigger:** player arrives at a new location OR opens a case
- **Where:** location arrival in `noir/world.py`; case opening in `noir/cases/manager.py`
- **Data:** location description or case description
- **Render:** `show_scene(sprite)` before the existing narrative text

Both calls are synchronous but time-bounded (3s). On timeout or error: silent no-op.

---

## Error Handling

- Sprite generation failure (LLM error, schema violation, timeout): silent skip, no art shown
- Cache read/write failure: log warning, continue without cache
- Terminal without truecolor support: renderer detects via `$COLORTERM` env var; falls back to 256-color approximation

---

## Testing

- Unit test renderer with a fixed `Sprite` fixture — assert correct ANSI output
- Unit test cache: hit returns cached sprite without calling LLM
- Unit test validation: malformed LLM output returns `None`
- Integration: no new end-to-end tests required; existing game loop tests are unaffected
