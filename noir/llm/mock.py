from itertools import cycle
from .base import LLMBackend


class MockLLMBackend(LLMBackend):

    def __init__(self, responses: list[str] | None = None):
        self._responses = cycle(responses or ["mock response"])
        self.last_history: list[dict] = []
        self.calls: list[dict] = []

    def query(self, system_prompt: str, history: list[dict], user_input: str) -> str:
        self.last_history = history
        self.calls.append({
            "system_prompt": system_prompt,
            "history": history,
            "user_input": user_input,
        })
        return next(self._responses)
