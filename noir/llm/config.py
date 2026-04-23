import json
from pathlib import Path

CONFIG_PATH = Path.home() / ".noir_detective" / "config.json"

DEFAULTS: dict = {
    "backend": "claude_cli",
    "dialogue_model": "sonnet",
    "structured_model": "sonnet",
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                data = json.load(f)
            return {**DEFAULTS, **data}
        except (json.JSONDecodeError, OSError):
            pass
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(DEFAULTS, f, indent=2)
    return dict(DEFAULTS)
