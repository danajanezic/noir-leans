import json
import logging
import re
from abc import ABC, abstractmethod
from typing import NoReturn
from rich.console import Console
from rich.panel import Panel

log = logging.getLogger(__name__)


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text)
    return text.strip()


class LLMBackend(ABC):

    suppress_status: bool = False

    @abstractmethod
    def query(self, system_prompt: str, history: list[dict], user_input: str) -> str: ...

    def _structured_query(self, system_prompt: str, history: list[dict], user_input: str) -> str:
        """Raw text call used by query_structured. Override to use a different model."""
        return self.query(system_prompt, history, user_input)

    def query_structured(self, system_prompt: str, history: list[dict], user_input: str) -> dict:
        response = self._structured_query(system_prompt, history, user_input)
        log.debug("query_structured response (raw): %s", response[:500])
        cleaned = _strip_fences(response)
        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, ValueError) as e:
            log.warning("JSON parse failed (%s), retrying. Cleaned response: %s", e, cleaned[:300])
            retry_prompt = (
                f"Your previous response was not valid JSON. Error: {e}\n"
                f"Previous response: {response}\n\n"
                "Return ONLY valid JSON with no additional text, no markdown fences."
            )
            response = self._structured_query(system_prompt, history, retry_prompt)
            log.debug("retry response (raw): %s", response[:500])
            cleaned = _strip_fences(response)
            try:
                return json.loads(cleaned)
            except (json.JSONDecodeError, ValueError) as e2:
                log.error("JSON parse failed on retry (%s). Cleaned: %s", e2, cleaned[:300])
                self._fatal()

    def _fatal(self) -> NoReturn:
        console = Console()
        console.print(Panel(
            "[bold yellow]Your partner's voice crackles through the static...[/bold yellow]\n\n"
            "Noirleans has been briefly suspended due to an administrative error.\n"
            "Also — and I cannot stress this enough — did you remember to pay your LLM bill?\n"
            "Because that would explain a very great deal about what's happening right now.\n\n"
            "[dim]The universe will resume shortly. Probably.[/dim]",
            title="[red]CRITICAL ERROR[/red]",
            border_style="red",
        ))
        raise SystemExit(1)
