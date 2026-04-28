import logging
import re
import subprocess
import sys
import time
from .base import LLMBackend
from ._spinner import BottomRightSpinner

log = logging.getLogger(__name__)

# Prepended to the system prompt for all structured (JSON) calls.
# The superpowers plugin fires in every subprocess session and its brainstorming
# rules override the task, causing prose responses instead of JSON.
# Placing an explicit "no skills" instruction in the system prompt takes precedence
# per the superpowers priority rules ("user instructions — highest priority").
_JSON_SYSTEM_PREAMBLE = (
    "You are an automated JSON API endpoint in a pipeline. "
    "Return ONLY a valid JSON object — raw, unformatted, with no surrounding text. "
    "Do NOT wrap output in markdown code blocks. "
    "Do NOT use ```json or ``` anywhere in your response. "
    "Do not invoke any tools, skills, or workflows. "
    "Do not brainstorm, plan, explore, or ask clarifying questions. "
    "Your entire response must be parseable by json.loads() with no preprocessing."
)


class ClaudeCLIBackend(LLMBackend):

    def __init__(self, *, dialogue_model: str = "sonnet", structured_model: str = "sonnet"):
        self.dialogue_model = dialogue_model
        self.structured_model = structured_model

    def _run_claude(self, prompt: str, model: str, *,
                    json_output: bool = False, system_prompt: str = "") -> str:
        cmd = ["claude", "-p", prompt, "--model", model]
        if system_prompt:
            cmd += ["--system-prompt", system_prompt]
        if json_output:
            cmd += ["--output-format", "json"]

        log.debug("claude query model=%s json=%s input=%s", model, json_output, prompt[:300])
        t0 = time.perf_counter()
        try:
            if self.suppress_status:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            else:
                with BottomRightSpinner(self.status_message):
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
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
            stderr = result.stderr.strip()
            # When --output-format json is used, errors may land in stdout as a JSON envelope.
            detail = stderr
            if not detail:
                import json as _json
                try:
                    envelope = _json.loads(result.stdout)
                    detail = envelope.get("error") or envelope.get("message") or str(envelope)
                except Exception:
                    detail = result.stdout.strip()
            log.error("claude returned non-zero: %s", detail[:300])
            self._fatal(detail[:300])

        if json_output:
            import json as _json
            try:
                envelope = _json.loads(result.stdout)
                text = envelope.get("result", result.stdout).strip()
            except Exception:
                text = result.stdout.strip()
            text = re.sub(r'^```[a-z]*\s*\n?', '', text, flags=re.IGNORECASE)
            text = re.sub(r'\n?```\s*$', '', text)
            text = text.strip()
        else:
            text = result.stdout.strip()

        log.info("LLM call model=%s json=%s elapsed=%.2fs response=%s", model, json_output, elapsed, text[:300])
        return text

    def _call_claude(self, system_prompt: str, history: list[dict],
                     user_input: str, model: str, json_output: bool = False) -> str:
        if json_output:
            parts = []
            if history:
                for msg in history:
                    parts.append(f"{msg['role'].upper()}: {msg['content']}")
            parts.append(f"USER: {user_input}")
            full_prompt = "\n".join(parts)
            effective_system = f"{_JSON_SYSTEM_PREAMBLE}\n\n{system_prompt}"
            return self._run_claude(full_prompt, model, json_output=True,
                                    system_prompt=effective_system)

        parts = [f"[SYSTEM]\n{system_prompt}\n"]
        if history:
            parts.append("[CONVERSATION]")
            for msg in history:
                parts.append(f"{msg['role'].upper()}: {msg['content']}")
        parts.append(f"USER: {user_input}")
        parts.append("ASSISTANT:")
        full_prompt = "\n".join(parts)

        text = self._run_claude(full_prompt, model)

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
