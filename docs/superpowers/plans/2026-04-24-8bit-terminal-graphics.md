# 8-bit Terminal Graphics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dynamically generate 8-bit pixel art sprites via LLM and render them inline in the terminal — compact portraits when entering NPC conversations, scene banners when arriving at locations or opening cases.

**Architecture:** The LLM generates sprites as a structured JSON payload (palette + pixel grid); a renderer converts this to terminal output using Unicode half-block characters (`▀`) and ANSI color codes. Sprites are cached by description hash in SQLite so the same subject is only generated once. Generation is time-bounded — failures silently skip art and the game continues normally.

**Tech Stack:** Python 3.11+, existing `LLMBackend.query_structured()` (haiku model), `sqlite3`, `concurrent.futures` for timeout, ANSI truecolor/256-color escape codes, Unicode `▀` U+2580

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `noir/pixel_art.py` | Create | `Sprite` dataclass + terminal renderer |
| `noir/llm/sprite_gen.py` | Create | LLM sprite generation + validation + cache integration |
| `noir/persistence/db.py` | Modify | Add `sprites` table to `SCHEMA` and `_MIGRATIONS` |
| `noir/persistence/repository.py` | Modify | `get_sprite_cache` / `save_sprite_cache` functions |
| `noir/display.py` | Modify | `show_portrait()` and `show_scene()` display helpers |
| `noir/game.py` | Modify | Wire portrait at NPC conversation start; scene at arrival and case open |
| `scripts/gen_example_sprites.py` | Create | CLI bootstrap tool to generate + preview + save example sprites |
| `noir/data/sprites/examples/portrait/` | Create dir | Holds hand-promoted portrait example JSON files |
| `noir/data/sprites/examples/scene/` | Create dir | Holds hand-promoted scene example JSON files |
| `tests/test_pixel_art.py` | Create | Renderer unit tests |
| `tests/test_sprite_gen.py` | Create | Generator validation + cache tests |

---

## Task 1: Sprite Dataclass + Terminal Renderer

**Files:**
- Create: `noir/pixel_art.py`
- Create: `tests/test_pixel_art.py`

- [ ] **Step 1.1: Write the failing renderer tests**

Create `tests/test_pixel_art.py`:

```python
import os
import pytest
from noir.pixel_art import Sprite, render_sprite, _hex_to_rgb, _rgb_to_256


class TestHexToRgb:
    def test_black(self):
        assert _hex_to_rgb("#000000") == (0, 0, 0)

    def test_white(self):
        assert _hex_to_rgb("#ffffff") == (255, 255, 255)

    def test_dark_red(self):
        assert _hex_to_rgb("#8b0000") == (139, 0, 0)

    def test_without_hash(self):
        assert _hex_to_rgb("1a0a00") == (26, 10, 0)


class TestRgbTo256:
    def test_black_maps_to_16(self):
        assert _rgb_to_256(0, 0, 0) == 16

    def test_white_maps_to_231(self):
        assert _rgb_to_256(255, 255, 255) == 231

    def test_result_in_range(self):
        for r in range(0, 256, 64):
            for g in range(0, 256, 64):
                for b in range(0, 256, 64):
                    idx = _rgb_to_256(r, g, b)
                    assert 16 <= idx <= 231


class TestRenderSprite:
    def _make_2x2_sprite(self) -> Sprite:
        return Sprite(
            width=2,
            height=2,
            palette=["#000000", "#8b0000"],
            pixels=[[0, 1], [1, 0]],
        )

    def test_render_returns_one_line_per_two_rows(self):
        sprite = self._make_2x2_sprite()
        lines = render_sprite(sprite)
        assert len(lines) == 1  # 2 pixel rows → 1 terminal line

    def test_render_line_contains_half_block_char(self):
        sprite = self._make_2x2_sprite()
        lines = render_sprite(sprite)
        assert "▀" in lines[0]

    def test_render_line_contains_reset(self):
        sprite = self._make_2x2_sprite()
        lines = render_sprite(sprite)
        assert "\033[0m" in lines[0]

    def test_odd_height_pads_bottom_row(self):
        sprite = Sprite(
            width=2,
            height=3,
            palette=["#000000", "#8b0000"],
            pixels=[[0, 1], [1, 0], [0, 0]],
        )
        lines = render_sprite(sprite)
        assert len(lines) == 2  # 3 rows → ceil(3/2) = 2 terminal lines

    def test_render_width_matches_sprite_width(self):
        sprite = Sprite(
            width=4,
            height=2,
            palette=["#000000"],
            pixels=[[0, 0, 0, 0], [0, 0, 0, 0]],
        )
        lines = render_sprite(sprite)
        assert lines[0].count("▀") == 4
```

- [ ] **Step 1.2: Run tests to verify they fail**

```bash
cd /Users/danajanezic/code/noir-leans && python -m pytest tests/test_pixel_art.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'noir.pixel_art'`

- [ ] **Step 1.3: Create `noir/pixel_art.py`**

```python
import math
import os
import shutil
from dataclasses import dataclass


@dataclass
class Sprite:
    width: int
    height: int
    palette: list[str]
    pixels: list[list[int]]


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_256(r: int, g: int, b: int) -> int:
    ri = round(r / 255 * 5)
    gi = round(g / 255 * 5)
    bi = round(b / 255 * 5)
    return 16 + 36 * ri + 6 * gi + bi


def _use_truecolor() -> bool:
    return os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")


def _ansi_fg(r: int, g: int, b: int) -> str:
    if _use_truecolor():
        return f"\033[38;2;{r};{g};{b}m"
    return f"\033[38;5;{_rgb_to_256(r, g, b)}m"


def _ansi_bg(r: int, g: int, b: int) -> str:
    if _use_truecolor():
        return f"\033[48;2;{r};{g};{b}m"
    return f"\033[48;5;{_rgb_to_256(r, g, b)}m"


_RESET = "\033[0m"


def render_sprite(sprite: Sprite) -> list[str]:
    """Return terminal lines — one line per two pixel rows, using ▀ half-block characters."""
    lines = []
    for row_idx in range(0, sprite.height, 2):
        top_row = sprite.pixels[row_idx]
        if row_idx + 1 < sprite.height:
            bot_row = sprite.pixels[row_idx + 1]
        else:
            bot_row = [0] * sprite.width
        parts = []
        for col in range(sprite.width):
            tr, tg, tb = _hex_to_rgb(sprite.palette[top_row[col]])
            br, bg, bb = _hex_to_rgb(sprite.palette[bot_row[col]])
            parts.append(f"{_ansi_fg(tr, tg, tb)}{_ansi_bg(br, bg, bb)}▀")
        lines.append("".join(parts) + _RESET)
    return lines


def _print_sprite_centered(lines: list[str], sprite_width: int) -> None:
    term_width = shutil.get_terminal_size().columns
    pad = max((term_width - sprite_width) // 2, 0)
    prefix = " " * pad
    for line in lines:
        print(prefix + line)
    print()


def show_portrait(sprite: Sprite) -> None:
    """Print a compact character portrait (16×16 px → 8 terminal rows), centered."""
    lines = render_sprite(sprite)
    _print_sprite_centered(lines, sprite.width)


def show_scene(sprite: Sprite) -> None:
    """Print a scene banner (48×24 px → 12 terminal rows), centered."""
    lines = render_sprite(sprite)
    _print_sprite_centered(lines, sprite.width)
```

- [ ] **Step 1.4: Run tests to verify they pass**

```bash
cd /Users/danajanezic/code/noir-leans && python -m pytest tests/test_pixel_art.py -v
```

Expected: all tests PASS

- [ ] **Step 1.5: Commit**

```bash
git add noir/pixel_art.py tests/test_pixel_art.py
git commit -m "feat: Sprite dataclass and terminal half-block renderer"
```

---

## Task 2: DB Sprites Cache Table + Repository Functions

**Files:**
- Modify: `noir/persistence/db.py`
- Modify: `noir/persistence/repository.py`

- [ ] **Step 2.1: Write failing cache tests**

Create `tests/test_sprite_gen.py`:

```python
import json
import pytest
import sqlite3
from noir.pixel_art import Sprite
from noir.persistence.db import create_schema
from noir.persistence.repository import get_sprite_cache, save_sprite_cache


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    create_schema(c)
    yield c
    c.close()


def _sample_sprite() -> Sprite:
    return Sprite(
        width=2,
        height=2,
        palette=["#000000", "#8b0000"],
        pixels=[[0, 1], [1, 0]],
    )


class TestSpriteCache:
    def test_get_returns_none_on_miss(self, conn):
        result = get_sprite_cache(conn, "a detective", "portrait")
        assert result is None

    def test_save_then_get_returns_sprite(self, conn):
        sprite = _sample_sprite()
        save_sprite_cache(conn, "a detective", "portrait", sprite)
        result = get_sprite_cache(conn, "a detective", "portrait")
        assert result is not None
        assert result.palette == sprite.palette
        assert result.pixels == sprite.pixels

    def test_different_descriptions_are_independent(self, conn):
        save_sprite_cache(conn, "a detective", "portrait", _sample_sprite())
        assert get_sprite_cache(conn, "a bartender", "portrait") is None

    def test_different_kinds_are_independent(self, conn):
        save_sprite_cache(conn, "a dim alley", "portrait", _sample_sprite())
        assert get_sprite_cache(conn, "a dim alley", "scene") is None

    def test_save_overwrites_existing(self, conn):
        sprite1 = _sample_sprite()
        sprite2 = Sprite(width=2, height=2, palette=["#ffffff"], pixels=[[0, 0], [0, 0]])
        save_sprite_cache(conn, "a detective", "portrait", sprite1)
        save_sprite_cache(conn, "a detective", "portrait", sprite2)
        result = get_sprite_cache(conn, "a detective", "portrait")
        assert result.palette == ["#ffffff"]
```

- [ ] **Step 2.2: Run tests to verify they fail**

```bash
cd /Users/danajanezic/code/noir-leans && python -m pytest tests/test_sprite_gen.py::TestSpriteCache -v 2>&1 | head -20
```

Expected: `ImportError` for `get_sprite_cache` / `save_sprite_cache`

- [ ] **Step 2.3: Add `sprites` table to `noir/persistence/db.py`**

In `db.py`, add the table to `SCHEMA` (after the last `CREATE TABLE` block, before the final `"""`):

```python
CREATE TABLE IF NOT EXISTS sprites (
    key TEXT PRIMARY KEY,
    palette TEXT NOT NULL,
    pixels TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

Also add a migration at the end of `_MIGRATIONS`:

```python
"CREATE TABLE IF NOT EXISTS sprites (key TEXT PRIMARY KEY, palette TEXT NOT NULL, pixels TEXT NOT NULL, created_at TEXT NOT NULL)",
```

- [ ] **Step 2.4: Add cache functions to `noir/persistence/repository.py`**

Add to the end of `repository.py`:

```python
import hashlib as _hashlib


def _sprite_cache_key(description: str, kind: str) -> str:
    return _hashlib.sha256(f"{description}:{kind}".encode()).hexdigest()


def get_sprite_cache(conn: sqlite3.Connection, description: str, kind: str):
    """Return a cached Sprite or None on miss. Imports Sprite lazily to avoid circular deps."""
    from noir.pixel_art import Sprite
    key = _sprite_cache_key(description, kind)
    row = conn.execute(
        "SELECT palette, pixels FROM sprites WHERE key=?", (key,)
    ).fetchone()
    if row is None:
        return None
    palette = json.loads(row["palette"])
    pixels = json.loads(row["pixels"])
    height = len(pixels)
    width = len(pixels[0]) if pixels else 0
    return Sprite(width=width, height=height, palette=palette, pixels=pixels)


def save_sprite_cache(conn: sqlite3.Connection, description: str, kind: str, sprite) -> None:
    from datetime import datetime, timezone
    key = _sprite_cache_key(description, kind)
    conn.execute(
        "INSERT OR REPLACE INTO sprites (key, palette, pixels, created_at) VALUES (?, ?, ?, ?)",
        (key, json.dumps(sprite.palette), json.dumps(sprite.pixels),
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
```

- [ ] **Step 2.5: Run cache tests to verify they pass**

```bash
cd /Users/danajanezic/code/noir-leans && python -m pytest tests/test_sprite_gen.py::TestSpriteCache -v
```

Expected: all 5 tests PASS

- [ ] **Step 2.6: Commit**

```bash
git add noir/persistence/db.py noir/persistence/repository.py tests/test_sprite_gen.py
git commit -m "feat: sprites cache table and repository functions"
```

---

## Task 3: Sprite Generator

**Files:**
- Create: `noir/llm/sprite_gen.py`
- Modify: `tests/test_sprite_gen.py` (add generator tests)

- [ ] **Step 3.1: Write failing generator tests**

Append to `tests/test_sprite_gen.py`:

```python
import json
from itertools import cycle
from noir.llm.mock import MockLLMBackend
from noir.llm.sprite_gen import generate_sprite, get_or_generate_sprite


def _valid_portrait_response() -> str:
    palette = ["#000000", "#8b0000", "#1a0a00", "#3d0000"]
    pixels = [[i % 4 for i in range(16)] for _ in range(16)]
    return json.dumps({"palette": palette, "pixels": pixels})


def _valid_scene_response() -> str:
    palette = ["#000000", "#1a0a00"]
    pixels = [[i % 2 for i in range(48)] for _ in range(24)]
    return json.dumps({"palette": palette, "pixels": pixels})


class TestGenerateSprite:
    def test_returns_sprite_on_valid_portrait_response(self):
        llm = MockLLMBackend(responses=[_valid_portrait_response()])
        sprite = generate_sprite(llm, "a hard-boiled detective", "portrait")
        assert sprite is not None
        assert sprite.width == 16
        assert sprite.height == 16

    def test_returns_sprite_on_valid_scene_response(self):
        llm = MockLLMBackend(responses=[_valid_scene_response()])
        sprite = generate_sprite(llm, "a rain-soaked alley", "scene")
        assert sprite is not None
        assert sprite.width == 48
        assert sprite.height == 24

    def test_returns_none_on_invalid_json(self):
        llm = MockLLMBackend(responses=["not json at all"])
        sprite = generate_sprite(llm, "a detective", "portrait")
        assert sprite is None

    def test_returns_none_when_pixels_wrong_dimensions(self):
        bad = json.dumps({"palette": ["#000000"], "pixels": [[0] * 8 for _ in range(8)]})
        llm = MockLLMBackend(responses=[bad])
        sprite = generate_sprite(llm, "a detective", "portrait")
        assert sprite is None

    def test_returns_none_when_palette_missing(self):
        bad = json.dumps({"pixels": [[0] * 16 for _ in range(16)]})
        llm = MockLLMBackend(responses=[bad])
        sprite = generate_sprite(llm, "a detective", "portrait")
        assert sprite is None

    def test_returns_none_when_pixel_index_out_of_range(self):
        bad = json.dumps({
            "palette": ["#000000"],
            "pixels": [[5] * 16 for _ in range(16)],  # index 5 > palette length 1
        })
        llm = MockLLMBackend(responses=[bad])
        sprite = generate_sprite(llm, "a detective", "portrait")
        assert sprite is None


class TestGetOrGenerateSprite:
    def test_generates_and_caches_on_miss(self, conn):
        llm = MockLLMBackend(responses=[_valid_portrait_response()])
        sprite = get_or_generate_sprite(llm, conn, "a detective", "portrait")
        assert sprite is not None
        cached = get_sprite_cache(conn, "a detective", "portrait")
        assert cached is not None

    def test_returns_cached_without_llm_call(self, conn):
        from noir.pixel_art import Sprite
        from noir.persistence.repository import save_sprite_cache
        sprite = Sprite(width=16, height=16, palette=["#000000"],
                        pixels=[[0]*16 for _ in range(16)])
        save_sprite_cache(conn, "a detective", "portrait", sprite)
        llm = MockLLMBackend(responses=["should not be called"])
        result = get_or_generate_sprite(llm, conn, "a detective", "portrait")
        assert result is not None
        assert len(llm.calls) == 0  # no LLM call made
```

- [ ] **Step 3.2: Run tests to verify they fail**

```bash
cd /Users/danajanezic/code/noir-leans && python -m pytest tests/test_sprite_gen.py::TestGenerateSprite tests/test_sprite_gen.py::TestGetOrGenerateSprite -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'generate_sprite'`

- [ ] **Step 3.3: Create `noir/data/sprites/examples/` directories**

```bash
mkdir -p /Users/danajanezic/code/noir-leans/noir/data/sprites/examples/portrait
mkdir -p /Users/danajanezic/code/noir-leans/noir/data/sprites/examples/scene
touch /Users/danajanezic/code/noir-leans/noir/data/sprites/examples/portrait/.gitkeep
touch /Users/danajanezic/code/noir-leans/noir/data/sprites/examples/scene/.gitkeep
```

- [ ] **Step 3.4: Create `noir/llm/sprite_gen.py`**

```python
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

log = logging.getLogger(__name__)

_EXAMPLES_DIR = Path(__file__).parent.parent / "data" / "sprites" / "examples"

_PORTRAIT_SIZE = (16, 16)
_SCENE_SIZE = (48, 24)

_SYSTEM_PROMPT = (
    "You are a pixel art engine for a 1935 noir detective game. "
    "Generate an 8-bit style sprite using a dark, moody palette — deep blacks, "
    "muted reds, dirty browns, smoky greys. "
    "Return ONLY a valid JSON object with exactly two keys:\n"
    '  "palette": array of up to 16 hex color strings (e.g. "#1a0a00")\n'
    '  "pixels": 2D array of integers 0–15 indexing the palette, '
    "exactly {h} rows each containing exactly {w} integers\n"
    "No markdown. No explanation. Raw JSON only."
)


def _load_examples(kind: str) -> list[dict]:
    examples_path = _EXAMPLES_DIR / kind
    if not examples_path.exists():
        return []
    results = []
    for f in sorted(examples_path.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            results.append(data)
        except Exception:
            pass
    return results[:2]  # max 2 examples per prompt


def _format_examples(examples: list[dict]) -> str:
    if not examples:
        return ""
    parts = ["\n\nReference examples of correct output:"]
    for ex in examples:
        subject = ex.get("subject", "unknown")
        sprite_data = {k: ex[k] for k in ("palette", "pixels") if k in ex}
        parts.append(f'\nSubject: "{subject}"\n{json.dumps(sprite_data)}')
    return "\n".join(parts)


def _validate(data: dict, width: int, height: int):
    """Return Sprite if data is valid, else None."""
    from noir.pixel_art import Sprite
    if not isinstance(data, dict):
        return None
    palette = data.get("palette")
    pixels = data.get("pixels")
    if not isinstance(palette, list) or not palette:
        return None
    if not isinstance(pixels, list) or len(pixels) != height:
        return None
    for row in pixels:
        if not isinstance(row, list) or len(row) != width:
            return None
        for val in row:
            if not isinstance(val, int) or val < 0 or val >= len(palette):
                return None
    return Sprite(width=width, height=height, palette=palette, pixels=pixels)


def generate_sprite(llm, description: str, kind: str):
    """Generate a Sprite via LLM. Returns None on any failure."""
    w, h = _PORTRAIT_SIZE if kind == "portrait" else _SCENE_SIZE
    system = _SYSTEM_PROMPT.format(w=w, h=h)
    examples = _load_examples(kind)
    example_text = _format_examples(examples)
    prompt = f'Generate a pixel art sprite.\nSubject: "{description}"{example_text}'

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(llm._structured_query, system, [], prompt)
        raw = future.result(timeout=15.0)
    except Exception as e:
        log.warning("sprite generation failed for %r: %s", description[:50], e)
        return None
    finally:
        executor.shutdown(wait=False)

    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        log.warning("sprite JSON parse failed for %r", description[:50])
        return None

    sprite = _validate(data, w, h)
    if sprite is None:
        log.warning("sprite validation failed for %r", description[:50])
    return sprite


def get_or_generate_sprite(llm, conn, description: str, kind: str):
    """Return cached Sprite or generate a new one, caching the result."""
    from noir.persistence.repository import get_sprite_cache, save_sprite_cache
    cached = get_sprite_cache(conn, description, kind)
    if cached is not None:
        return cached
    sprite = generate_sprite(llm, description, kind)
    if sprite is not None:
        try:
            save_sprite_cache(conn, description, kind, sprite)
        except Exception as e:
            log.warning("failed to cache sprite: %s", e)
    return sprite
```

- [ ] **Step 3.5: Run generator tests to verify they pass**

```bash
cd /Users/danajanezic/code/noir-leans && python -m pytest tests/test_sprite_gen.py -v
```

Expected: all tests PASS

- [ ] **Step 3.6: Commit**

```bash
git add noir/llm/sprite_gen.py noir/data/sprites/examples/portrait/.gitkeep noir/data/sprites/examples/scene/.gitkeep tests/test_sprite_gen.py
git commit -m "feat: LLM sprite generator with validation, timeout, and cache integration"
```

---

## Task 4: Display Helpers in `display.py`

**Files:**
- Modify: `noir/display.py`

- [ ] **Step 4.1: Add imports and helper functions to `noir/display.py`**

At the top of `display.py`, add `from noir.pixel_art import Sprite, show_portrait, show_scene` is not needed — instead, re-export them so `game.py` can import them from `noir.display`.

Add to the end of `noir/display.py`:

```python
from noir.pixel_art import Sprite, show_portrait, show_scene  # noqa: F401 — re-exported
```

- [ ] **Step 4.2: Verify the import resolves cleanly**

```bash
cd /Users/danajanezic/code/noir-leans && python -c "from noir.display import show_portrait, show_scene; print('ok')"
```

Expected: `ok`

- [ ] **Step 4.3: Commit**

```bash
git add noir/display.py
git commit -m "feat: re-export show_portrait and show_scene from display module"
```

---

## Task 5: Bootstrap Script

**Files:**
- Create: `scripts/gen_example_sprites.py`

This script generates a sprite for a given subject, renders it in the terminal for review, and optionally saves it as a named example file.

- [ ] **Step 5.1: Create `scripts/gen_example_sprites.py`**

```python
#!/usr/bin/env python3
"""Bootstrap script to generate, preview, and save example sprites.

Usage:
  python scripts/gen_example_sprites.py --subject "a hard-boiled detective in a trenchcoat" --kind portrait
  python scripts/gen_example_sprites.py --subject "a rain-soaked alley" --kind scene --save alley
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from noir.llm.config import load_config
from noir.llm.claude_cli import ClaudeCLIBackend
from noir.llm.sprite_gen import generate_sprite
from noir.pixel_art import show_portrait, show_scene


def main():
    parser = argparse.ArgumentParser(description="Generate and preview an 8-bit sprite.")
    parser.add_argument("--subject", required=True, help="Description of the sprite subject")
    parser.add_argument("--kind", choices=["portrait", "scene"], default="portrait")
    parser.add_argument(
        "--save", metavar="NAME",
        help="Save as example: noir/data/sprites/examples/<kind>/<NAME>.json"
    )
    args = parser.parse_args()

    config = load_config()
    llm = ClaudeCLIBackend(
        dialogue_model=config.get("dialogue_model", "sonnet"),
        structured_model=config.get("structured_model", "haiku"),
    )

    print(f"Generating {args.kind} sprite for: {args.subject!r}")
    sprite = generate_sprite(llm, args.subject, args.kind)

    if sprite is None:
        print("Generation failed — no sprite returned.")
        sys.exit(1)

    print(f"\nSprite: {sprite.width}×{sprite.height}, {len(sprite.palette)} colors\n")
    if args.kind == "portrait":
        show_portrait(sprite)
    else:
        show_scene(sprite)

    if args.save:
        out_dir = Path(__file__).parent.parent / "noir" / "data" / "sprites" / "examples" / args.kind
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{args.save}.json"
        payload = {
            "subject": args.subject,
            "palette": sprite.palette,
            "pixels": sprite.pixels,
        }
        out_path.write_text(json.dumps(payload, indent=2))
        print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5.2: Verify the script is importable**

```bash
cd /Users/danajanezic/code/noir-leans && python scripts/gen_example_sprites.py --help
```

Expected: usage help printed with `--subject`, `--kind`, `--save` options

- [ ] **Step 5.3: Generate example sprites and promote the best ones**

Run these commands and review the rendered output. Re-run until quality is acceptable, then add `--save <name>` to keep the best result.

```bash
# Portrait examples
python scripts/gen_example_sprites.py --subject "a hard-boiled male detective in a trenchcoat and fedora, 1930s noir" --kind portrait
python scripts/gen_example_sprites.py --subject "a femme fatale in a red dress, 1930s noir" --kind portrait
python scripts/gen_example_sprites.py --subject "a corrupt police captain, 1930s noir" --kind portrait

# Scene examples
python scripts/gen_example_sprites.py --subject "a rain-soaked alley at night, 1930s New Orleans" --kind scene
python scripts/gen_example_sprites.py --subject "a smoky jazz bar interior, 1930s noir" --kind scene
```

When you have a good result, save it:

```bash
python scripts/gen_example_sprites.py --subject "a hard-boiled male detective in a trenchcoat and fedora, 1930s noir" --kind portrait --save detective
python scripts/gen_example_sprites.py --subject "a rain-soaked alley at night, 1930s New Orleans" --kind scene --save alley
```

- [ ] **Step 5.4: Commit script and any saved examples**

```bash
git add scripts/gen_example_sprites.py noir/data/sprites/examples/
git commit -m "feat: bootstrap script for generating and saving example sprites"
```

---

## Task 6: Wire Portrait at NPC Conversation Start

**Files:**
- Modify: `noir/game.py`

The portrait call goes just before `show_conversation_header(npc_row["name"])`. There are four call sites in `_talk_to_npc` (lines ~1346, ~1380, ~1386, ~1396) and one for the companion (line ~1883). Add portrait generation to the main NPC path only (not companion — partner gets no portrait for now).

- [ ] **Step 6.1: Add import to `game.py`**

In `game.py`, find the display imports block (line ~13-14):

```python
    show_travel_animation, show_location_rule, travel_status, show_splash, typewrite, show_narrator,
    show_conversation_header, show_conversation_footer, show_evidence, show_partner_aside,
```

Add `show_portrait` to the import:

```python
    show_travel_animation, show_location_rule, travel_status, show_splash, typewrite, show_narrator,
    show_conversation_header, show_conversation_footer, show_evidence, show_partner_aside,
    show_portrait,
```

Also add to the imports block (near the top of game.py, with the other noir imports):

```python
from noir.llm.sprite_gen import get_or_generate_sprite
```

- [ ] **Step 6.2: Add a helper method to the `Game` class**

Find the `Game` class in `game.py`. Add this private method (place it near other display helpers in the class, before `handle_go`):

```python
def _show_npc_portrait(self, npc_row) -> None:
    """Generate (or load from cache) and display a portrait for an NPC. Silent on failure."""
    try:
        description = npc_row.get("physical_description") or npc_row.get("role") or npc_row["name"]
        sprite = get_or_generate_sprite(self.llm, self.conn, description, "portrait")
        if sprite:
            show_portrait(sprite)
    except Exception:
        pass
```

- [ ] **Step 6.3: Wire portrait at each `show_conversation_header` call in `_talk_to_npc`**

In `game.py`, find line ~1346 (first `show_conversation_header(npc_row["name"])` call inside `_talk_to_npc`). Add the portrait call immediately before each of the four NPC conversation header calls:

Before:
```python
        show_conversation_header(npc_row["name"])
        _is_da = "district attorney" in (npc_row["role"] or "").lower()
```

After:
```python
        self._show_npc_portrait(npc_row)
        show_conversation_header(npc_row["name"])
        _is_da = "district attorney" in (npc_row["role"] or "").lower()
```

Do the same for the other three `show_conversation_header(npc_row["name"])` calls in `_talk_to_npc` (lines ~1380, ~1386, ~1396). Each gets `self._show_npc_portrait(npc_row)` inserted immediately before it.

- [ ] **Step 6.4: Smoke test**

```bash
cd /Users/danajanezic/code/noir-leans && python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all existing tests still PASS (portrait generation is not exercised by unit tests — it's integration-only)

- [ ] **Step 6.5: Commit**

```bash
git add noir/game.py
git commit -m "feat: show NPC portrait at conversation start"
```

---

## Task 7: Wire Scene at Location Arrival

**Files:**
- Modify: `noir/game.py`

The scene banner goes after `show_location_rule()` and before the companion arrival narration, in `handle_go`. Location description is in `loc["description"]`.

- [ ] **Step 7.1: Add `show_scene` to the display imports in `game.py`**

Find the same import block from Task 6. Add `show_scene`:

```python
    show_travel_animation, show_location_rule, travel_status, show_splash, typewrite, show_narrator,
    show_conversation_header, show_conversation_footer, show_evidence, show_partner_aside,
    show_portrait, show_scene,
```

- [ ] **Step 7.2: Add a helper method for scene display**

In the `Game` class, add next to `_show_npc_portrait`:

```python
def _show_location_scene(self, loc) -> None:
    """Generate (or load from cache) and display a scene banner for a location. Silent on failure."""
    try:
        description = loc.get("description") or loc.get("name", "")
        sprite = get_or_generate_sprite(self.llm, self.conn, description, "scene")
        if sprite:
            show_scene(sprite)
    except Exception:
        pass
```

- [ ] **Step 7.3: Call scene banner after `show_location_rule()` in `handle_go`**

In `handle_go`, find the two `show_location_rule()` calls (lines ~1177 and ~1183) — one in the companion branch and one in the no-companion branch.

Before (companion branch, lines ~1176-1179):
```python
            show_travel_animation()
            show_location_rule()
            show_location(loc["name"], loc["description"], npc_names,
                          game_time=get_game_time(self.conn), orgs=loc_orgs)
```

After:
```python
            show_travel_animation()
            show_location_rule()
            self._show_location_scene(loc)
            show_location(loc["name"], loc["description"], npc_names,
                          game_time=get_game_time(self.conn), orgs=loc_orgs)
```

Before (no-companion branch, lines ~1182-1185):
```python
            show_travel_animation()
            show_location_rule()
            show_location(loc["name"], loc["description"], npc_names,
                          game_time=get_game_time(self.conn), orgs=loc_orgs)
```

After:
```python
            show_travel_animation()
            show_location_rule()
            self._show_location_scene(loc)
            show_location(loc["name"], loc["description"], npc_names,
                          game_time=get_game_time(self.conn), orgs=loc_orgs)
```

- [ ] **Step 7.4: Run tests**

```bash
cd /Users/danajanezic/code/noir-leans && python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all tests PASS

- [ ] **Step 7.5: Commit**

```bash
git add noir/game.py
git commit -m "feat: show scene banner on location arrival"
```

---

## Task 8: Wire Scene at Case Open

**Files:**
- Modify: `noir/game.py`

The scene banner goes after the case title is printed and before the companion briefing in `start_new_case`. The subject is the case title + victim description.

- [ ] **Step 8.1: Call scene banner in `start_new_case`**

In `game.py`, find `start_new_case` (line ~1068). After the case title/victim block:

Before (lines ~1095-1101):
```python
        console.print(f"\n[bold red]NEW CASE: {case_data['title']}[/bold red]")
        console.print(
            f"[italic]Victim: {case_data['victim']['name']} — "
            f"{case_data['victim']['cause_of_death']}[/italic]\n"
        )

        if self.companion:
```

After:
```python
        console.print(f"\n[bold red]NEW CASE: {case_data['title']}[/bold red]")
        console.print(
            f"[italic]Victim: {case_data['victim']['name']} — "
            f"{case_data['victim']['cause_of_death']}[/italic]\n"
        )

        _case_scene_desc = (
            f"{case_data['title']}. "
            f"Victim: {case_data['victim']['name']}, "
            f"{case_data['victim'].get('cause_of_death', 'cause unknown')}. "
            f"Found at: {case_data['victim'].get('found_at', 'unknown location')}. "
            f"1930s noir detective game scene."
        )
        self._show_location_scene({"description": _case_scene_desc, "name": case_data["title"]})

        if self.companion:
```

- [ ] **Step 8.2: Run tests**

```bash
cd /Users/danajanezic/code/noir-leans && python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all tests PASS

- [ ] **Step 8.3: Commit**

```bash
git add noir/game.py
git commit -m "feat: show scene banner when a new case opens"
```

---

## Self-Review Checklist

| Spec requirement | Task |
|-----------------|------|
| Renderer: palette + pixel grid → ANSI half-blocks | Task 1 |
| Portrait 16×16 → 8 terminal rows | Task 1 `show_portrait` |
| Scene 48×24 → 12 terminal rows, centered | Task 1 `show_scene` |
| LLM generates via structured query (haiku path) | Task 3 `generate_sprite` calls `_structured_query` |
| JSON schema: palette + pixels | Task 3 `_SYSTEM_PROMPT` + `_validate` |
| 15s timeout, silent failure | Task 3 `ThreadPoolExecutor.result(timeout=15.0)` |
| SQLite sprite cache by sha256 key | Task 2 |
| Cache keyed by `description + kind` | Task 2 `_sprite_cache_key` |
| Few-shot examples in prompt | Task 3 `_load_examples` + `_format_examples` |
| Bootstrap script to generate + save examples | Task 5 |
| Portrait shown at NPC conversation start | Task 6 |
| Scene shown on location arrival | Task 7 |
| Scene shown on case open | Task 8 |
| 256-color fallback for non-truecolor terminals | Task 1 `_use_truecolor` / `_rgb_to_256` |
| Unit tests: renderer | Task 1 |
| Unit tests: cache hit/miss | Task 2 |
| Unit tests: validation failures | Task 3 |
