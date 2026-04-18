import logging
import re
import subprocess
import sys
from rich.console import Console
from .base import LLMBackend

log = logging.getLogger(__name__)
_console = Console()


class ClaudeCLIBackend(LLMBackend):

    def __init__(self, *, dialogue_model: str = "sonnet", structured_model: str = "haiku"):
        self.dialogue_model = dialogue_model
        self.structured_model = structured_model

    def _call_claude(self, system_prompt: str, history: list[dict],
                     user_input: str, model: str) -> str:
        parts = [f"[SYSTEM]\n{system_prompt}\n"]
        if history:
            parts.append("[CONVERSATION]")
            for msg in history:
                parts.append(f"{msg['role'].upper()}: {msg['content']}")
        parts.append(f"USER: {user_input}")
        parts.append("ASSISTANT:")
        full_prompt = "\n".join(parts)

        log.debug("claude query model=%s input=%s", model, user_input[:300])

        try:
            if self.suppress_status:
                result = subprocess.run(
                    ["claude", "-p", full_prompt, "--model", model],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
            else:
                with _console.status("[dim]Thinking...[/dim]", spinner="dots"):
                    result = subprocess.run(
                        ["claude", "-p", full_prompt, "--model", model],
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            log.error("subprocess error: %s", e)
            self._fatal()
        finally:
            try:
                import termios
                termios.tcflush(sys.stdin, termios.TCIFLUSH)
            except Exception:
                pass

        if result.returncode != 0:
            log.error("claude returned non-zero: %s", result.stderr[:300])
            self._fatal()

        text = result.stdout.strip()
        # strip role label echoes and EOS token artifacts
        text = re.sub(r'^(USER|ASSISTANT|Human|Assistant)\s*:\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'</?s>|<\|endoftext\|>|<\|end\|>', '', text)
        log.debug("claude response: %s", text[:300])
        return text.strip()

    def query(self, system_prompt: str, history: list[dict], user_input: str) -> str:
        return self._call_claude(system_prompt, history, user_input, self.dialogue_model)

    def _structured_query(self, system_prompt: str, history: list[dict], user_input: str) -> str:
        return self._call_claude(system_prompt, history, user_input, self.structured_model)
