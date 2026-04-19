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
    # extract content from a fenced block anywhere in the text
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, flags=re.DOTALL)
    if m:
        return m.group(1).strip()
    # strip leading fences if no closing fence
    text = re.sub(r'^```(?:json)?\s*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text)
    # strip any leading prose before the first { or [
    m2 = re.search(r'[{\[]', text)
    if m2:
        text = text[m2.start():]
    return text.strip()


class LLMBackend(ABC):

    suppress_status: bool = False
    status_message: str = "Thinking..."

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
            result = json.loads(cleaned)
            if isinstance(result, dict):
                return result
            raise ValueError(f"Expected JSON object, got {type(result).__name__}")
        except (json.JSONDecodeError, ValueError) as e:
            log.warning("JSON parse failed (%s), retrying. Cleaned response: %s", e, cleaned[:300])
            retry_prompt = (
                f"Your previous response was not valid JSON object. Error: {e}\n"
                f"Previous response: {response}\n\n"
                "Return ONLY a valid JSON object {{...}} with no additional text, no markdown fences."
            )
            response = self._structured_query(system_prompt, history, retry_prompt)
            log.debug("retry response (raw): %s", response[:500])
            cleaned = _strip_fences(response)
            try:
                result = json.loads(cleaned)
                if isinstance(result, dict):
                    return result
                raise ValueError(f"Expected JSON object, got {type(result).__name__}")
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
