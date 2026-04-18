import json
import logging
import re
import urllib.error
import urllib.request
from rich.console import Console
from .base import LLMBackend

log = logging.getLogger(__name__)
_console = Console()


class OllamaBackend(LLMBackend):

    def __init__(self, *, model: str = "qwen2.5:14b", host: str = "http://localhost:11434"):
        self.model = model
        self.host = host.rstrip("/")

    def _build_messages(self, system_prompt: str, history: list[dict], user_input: str) -> list[dict]:
        messages = [{"role": "system", "content": system_prompt}]
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": user_input})
        return messages

    def _call(self, system_prompt: str, history: list[dict], user_input: str,
              *, json_mode: bool = False) -> str:
        messages = self._build_messages(system_prompt, history, user_input)
        payload: dict = {"model": self.model, "messages": messages, "stream": False}
        if json_mode:
            payload["format"] = "json"

        log.debug("ollama query model=%s json=%s input=%s", self.model, json_mode, user_input[:300])

        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.host}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
        )

        try:
            if self.suppress_status:
                with urllib.request.urlopen(req, timeout=180) as resp:
                    body = json.loads(resp.read())
            else:
                with _console.status("[dim]Thinking...[/dim]", spinner="dots"):
                    with urllib.request.urlopen(req, timeout=180) as resp:
                        body = json.loads(resp.read())
        except urllib.error.URLError as e:
            log.error("ollama connection error: %s", e)
            self._fatal()

        text = body.get("message", {}).get("content", "").strip()
        # strip role echoes and EOS artifacts
        text = re.sub(r'^(USER|ASSISTANT|Human|Assistant)\s*:\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'</?s>|<\|endoftext\|>|<\|end\|>', '', text)
        log.info("ollama response (json=%s): %s", json_mode, text[:500])
        return text

    def query(self, system_prompt: str, history: list[dict], user_input: str) -> str:
        return self._call(system_prompt, history, user_input)

    def _structured_query(self, system_prompt: str, history: list[dict], user_input: str) -> str:
        return self._call(system_prompt, history, user_input, json_mode=True)
