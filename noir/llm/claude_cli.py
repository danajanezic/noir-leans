import json
import subprocess
from .base import LLMBackend


class ClaudeCLIBackend(LLMBackend):

    def query(self, system_prompt: str, history: list[dict], user_input: str) -> str:
        parts = [f"[SYSTEM]\n{system_prompt}\n"]
        if history:
            parts.append("[CONVERSATION]")
            for msg in history:
                parts.append(f"{msg['role'].upper()}: {msg['content']}")
        parts.append(f"USER: {user_input}")
        parts.append("ASSISTANT:")
        full_prompt = "\n".join(parts)

        try:
            result = subprocess.run(
                ["claude", "-p", full_prompt],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            self._fatal()

        if result.returncode != 0:
            self._fatal()

        return result.stdout.strip()
