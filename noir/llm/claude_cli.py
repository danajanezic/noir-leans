import logging
import re
import subprocess
import sys
import time
from rich.console import Console
from .base import LLMBackend

log = logging.getLogger(__name__)
_console = Console()


class ClaudeCLIBackend(LLMBackend):

    def __init__(self, *, dialogue_model: str = "sonnet", structured_model: str = "haiku"):
        self.dialogue_model = dialogue_model
        self.structured_model = structured_model

    def _run_claude(self, prompt: str, model: str, json_output: bool = False) -> str:
        cmd = ["claude", "-p", prompt, "--model", model]
        if json_output:
            cmd += ["--output-format", "json"]

        log.debug("claude query model=%s json=%s input=%s", model, json_output, prompt[:300])
        t0 = time.perf_counter()
        try:
            if self.suppress_status:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            else:
                with _console.status(f"[dim]{self.status_message}[/dim]", spinner="dots"):
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            log.error("subprocess error: %s", e)
            self._fatal()
        finally:
            try:
                import termios
                termios.tcflush(sys.stdin, termios.TCIFLUSH)
            except Exception:
                pass
        elapsed = time.perf_counter() - t0

        if result.returncode != 0:
            log.error("claude returned non-zero: %s", result.stderr[:300])
            self._fatal()

        if json_output:
            import json as _json
            try:
                envelope = _json.loads(result.stdout)
                text = envelope.get("result", result.stdout).strip()
            except Exception:
                text = result.stdout.strip()
        else:
            text = result.stdout.strip()

        log.info("LLM call model=%s json=%s elapsed=%.2fs response=%s", model, json_output, elapsed, text[:300])
        return text

    def _call_claude(self, system_prompt: str, history: list[dict],
                     user_input: str, model: str, json_output: bool = False) -> str:
        parts = [f"[SYSTEM]\n{system_prompt}\n"]
        if history:
            parts.append("[CONVERSATION]")
            for msg in history:
                parts.append(f"{msg['role'].upper()}: {msg['content']}")
        parts.append(f"USER: {user_input}")
        if not json_output:
            parts.append("ASSISTANT:")
        full_prompt = "\n".join(parts)

        text = self._run_claude(full_prompt, model, json_output=json_output)

        if not json_output:
            text = re.sub(r'^(USER|ASSISTANT|Human|Assistant)\s*:\s*', '', text, flags=re.IGNORECASE)
            text = re.sub(r'</?s>|<\|endoftext\|>|<\|end\|>', '', text)
            text = re.sub(r'^\[(?:[^\[\]]|\[[^\[\]]*\])*\]\s*', '', text)
            text = re.sub(r'\(.*?\)', '', text, flags=re.DOTALL)
            text = re.sub(r'\*.*?\*', '', text, flags=re.DOTALL)
            text = re.sub(r'[ \t]+', ' ', text).strip()

        return text.strip()

    def query(self, system_prompt: str, history: list[dict], user_input: str) -> str:
        return self._call_claude(system_prompt, history, user_input, self.dialogue_model)

    def _structured_query(self, system_prompt: str, history: list[dict], user_input: str) -> str:
        return self._call_claude(system_prompt, history, user_input, self.structured_model, json_output=True)
