import queue
import threading
from dataclasses import dataclass
from typing import Callable

_STOP = object()


@dataclass
class SpeechItem:
    text: str
    voice_id: str


class SpeechQueueWorker:
    def __init__(self, speak_fn: Callable[[str, str], None]) -> None:
        self._q: queue.Queue = queue.Queue()
        self._speak_fn = speak_fn
        self._lock = threading.Lock()
        self._accept_new_items = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="audio-queue")
        self._thread.start()

    def enqueue(self, item: SpeechItem) -> None:
        with self._lock:
            if self._accept_new_items:
                self._q.put(item)

    def flush(self) -> None:
        with self._lock:
            self._accept_new_items = False
            # Drain the queue
            while True:
                try:
                    self._q.get_nowait()
                except queue.Empty:
                    break
            self._accept_new_items = True

    def shutdown(self) -> None:
        self._q.put(_STOP)
        self._thread.join(timeout=3.0)

    def _run(self) -> None:
        while True:
            item = self._q.get()
            if item is _STOP:
                break
            try:
                self._speak_fn(item.text, item.voice_id)
            except Exception:
                pass
