#!/usr/bin/env python3
"""Run a playthrough agent against a Noirleans game DB.

Usage:
    python -m agents.run --persona methodical
    python -m agents.run --persona jailbreak --max-turns 60 --out jailbreak.json
    python -m agents.run --persona intuitive --db /path/to/game.db --out report.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from noir.llm.base import LLMBackend
from noir.llm.config import load_config
from noir.persistence.db import DB_PATH, create_schema
from noir.persistence.repository import get_partner
from noir.step import run_step
from agents.personas import PERSONAS
from agents.playthrough_agent import PlaythroughAgent
from agents.report import write_report


def _create_backend(config: dict) -> "LLMBackend":
    backend = config.get("backend", "claude_cli")
    if backend == "claude_cli":
        from noir.llm.claude_cli import ClaudeCLIBackend
        return ClaudeCLIBackend(
            dialogue_model=config.get("dialogue_model", "sonnet"),
            structured_model=config.get("structured_model", "haiku"),
        )
    if backend == "ollama":
        from noir.llm.ollama import OllamaBackend
        return OllamaBackend(
            model=config.get("model", "qwen2.5:14b"),
            host=config.get("host", "http://localhost:11434"),
        )
    raise ValueError(f"Unknown backend '{backend}'.")


def _ensure_onboarded(conn: sqlite3.Connection, llm) -> None:
    if get_partner(conn):
        return
    print("No partner found — running onboarding with default values...", file=sys.stderr)
    result = run_step(
        {
            "type": "onboard",
            "race": "unspecified",
            "gender": "unspecified",
            "answers": ["A", "B", "C", "A", "B", "D", "A", "A"],
        },
        conn=conn, llm=llm, stdout=sys.stderr,
    )
    if not result.get("ok"):
        print(f"Onboarding failed: {result.get('error')}", file=sys.stderr)
        sys.exit(1)
    print(f"Onboarding complete. Partner: {result['partner']['name']}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a Noirleans playthrough agent")
    parser.add_argument("--persona", required=True, choices=list(PERSONAS),
                        help="Agent persona to use")
    parser.add_argument("--max-turns", type=int, default=40,
                        help="Maximum turns before stopping (default: 40)")
    parser.add_argument("--db", type=str, default=None,
                        help="Path to game DB (default: ~/.noir_detective/game.db)")
    parser.add_argument("--out", type=str, default=None,
                        help="Output path for JSON report")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else DB_PATH
    out_path = args.out or f"report_{args.persona}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    config = load_config()
    llm = _create_backend(config)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    _ensure_onboarded(conn, llm)
    conn.close()

    print(f"Starting {args.persona} agent (max {args.max_turns} turns)...", file=sys.stderr)
    agent = PlaythroughAgent(persona_name=args.persona, llm=llm, db_path=db_path)
    report = agent.run(max_turns=args.max_turns)

    write_report(report, out_path)
    print(f"Report written to {out_path}", file=sys.stderr)
    if report["verdict"] is None:
        print(json.dumps({"ok": False, "reason": "max_turns_reached", "turns": report["turns"]}))
    else:
        print(json.dumps({"ok": True, "verdict": report["verdict"]}))


if __name__ == "__main__":
    main()
