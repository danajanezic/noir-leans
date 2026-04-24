from dataclasses import dataclass
from typing import Callable


@dataclass
class SpeechItem:
    text: str
    voice_id: str


class SpeechQueueWorker:
    def __init__(self, speak_fn: Callable[[str, str], None]) -> None:
        self._speak_fn = speak_fn

    def enqueue(self, item: SpeechItem) -> None:
        pass

    def flush(self) -> None:
        pass

    def shutdown(self) -> None:
        pass
