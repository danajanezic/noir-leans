#!/usr/bin/env python3
"""One-time script to generate seeded locations for Noirleans.

Usage:
    python3 scripts/generate_locations.py

Writes noir/data/seeded_locations.json. Review the output before committing.
Generates in batches of 10 to avoid LLM timeout on large outputs.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from noir.llm.ollama import OllamaBackend

OUTPUT = Path(__file__).parent.parent / "noir" / "data" / "seeded_locations.json"

SYSTEM = "You are a world-builder for a 1935 Noirleans noir detective game. Return only valid JSON."

BATCH_PROMPT = """Generate exactly {n} distinct, period-accurate locations in Noirleans (fictional 1935 New Orleans).
Focus on: {focus}
Each should feel like it belongs in a corrupt, jazz-soaked, Depression-era detective story.
Reflect 1935 racial geography — some are primarily Black establishments, some are white-only, some are mixed-race.
Names should be specific and evocative, not generic.

Return a JSON object: {{"locations": [
  {{"name": "string (specific evocative name)", "description": "string (1-2 sentences)", "type": "bar|club|office|warehouse|church|hotel|restaurant|dock|gambling|political|residence|market|transport|other"}}
]}}
Return exactly {n} entries."""

BATCHES = [
    (10, "bars and jazz clubs"),
    (10, "speakeasies, gambling dens, and brothels (euphemistically named)"),
    (10, "offices, warehouses, and docks"),
    (10, "union halls, newspaper offices, and political offices"),
    (10, "churches, hotels, and restaurants"),
    (10, "pharmacies, diners, and markets"),
    (10, "pawn shops, funeral homes, and tenements"),
    (10, "precinct holding rooms, transport hubs, and other city establishments"),
    (10, "Black-owned establishments: clubs, barbershops, funeral homes, churches"),
    (10, "mixed-race or liminal spaces: gambling dens, dockside bars, flophouses, brothels"),
]

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
llm = OllamaBackend(timeout=300)
all_locations = []

for i, (n, focus) in enumerate(BATCHES):
    print(f"Generating batch {i+1}/{len(BATCHES)} ({n} locations: {focus})...", file=sys.stderr)
    prompt = BATCH_PROMPT.format(n=n, focus=focus)
    try:
        result = llm.query_structured(SYSTEM, [], prompt)
        batch = result.get("locations", [])
        # Filter out any non-dict entries (model occasionally returns strings)
        batch = [loc for loc in batch if isinstance(loc, dict) and "name" in loc and "description" in loc]
        print(f"  Got {len(batch)} locations.", file=sys.stderr)
        all_locations.extend(batch)
    except Exception as e:
        print(f"  Batch {i+1} failed: {e}", file=sys.stderr)

print(f"Total generated: {len(all_locations)} locations.", file=sys.stderr)
OUTPUT.write_text(json.dumps(all_locations, indent=2))
print(f"Written to {OUTPUT}", file=sys.stderr)
