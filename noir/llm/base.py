import json
from abc import ABC, abstractmethod
from rich.console import Console
from rich.panel import Panel


class LLMBackend(ABC):

    @abstractmethod
    def query(self, system_prompt: str, history: list[dict], user_input: str) -> str: ...

    def query_structured(self, system_prompt: str, history: list[dict], user_input: str) -> dict:
        response = self.query(system_prompt, history, user_input)
        try:
            return json.loads(response)
        except (json.JSONDecodeError, ValueError) as e:
            retry_prompt = (
                f"Your previous response was not valid JSON. Error: {e}\n"
                f"Previous response: {response}\n\n"
                "Return ONLY valid JSON with no additional text."
            )
            response = self.query(system_prompt, history, retry_prompt)
            try:
                return json.loads(response)
            except (json.JSONDecodeError, ValueError):
                self._fatal()

    def _fatal(self) -> None:
        console = Console()
        console.print(Panel(
            "[bold yellow]Your partner's voice crackles through the static...[/bold yellow]\n\n"
            "The entire city has been briefly suspended due to an administrative error.\n"
            "Also — and I cannot stress this enough — did you remember to pay your LLM bill?\n"
            "Because that would explain a very great deal about what's happening right now.\n\n"
            "[dim]The universe will resume shortly. Probably.[/dim]",
            title="[red]CRITICAL ERROR[/red]",
            border_style="red",
        ))
        raise SystemExit(1)
