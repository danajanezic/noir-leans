#!/usr/bin/env python3
"""Single-turn game entry point for LLM-driven testing.

Usage:
    echo '{"type": "onboard", "race": "Black", "gender": "man", "answers": [...]}' | python3 step.py
    echo '{"type": "command", "input": "/locations"}' | python3 step.py
    echo '{"type": "command", "input": "talk Rex Fontaine: Where were you?"}' | python3 step.py

Output: JSON dict on stdout with at minimum {"ok": bool}.
Game text is written to stderr so it doesn't pollute the JSON output.
"""
import json
import sqlite3
import sys

from noir.persistence.db import create_schema, DB_PATH
from noir.llm.config import load_config
from noir.step import run_step


def _create_backend(config: dict):
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


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        print(json.dumps({"ok": False, "error": "No input provided."}))
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    create_schema(conn)

    llm = _create_backend(load_config())

    result = run_step(raw, conn=conn, llm=llm, stdout=sys.stderr)
    conn.close()

    print(json.dumps(result))


if __name__ == "__main__":
    main()
