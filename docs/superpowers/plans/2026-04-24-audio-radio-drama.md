# Audio Radio Drama Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an async audio system to noir-leans that speaks all game text through Kokoro TTS with a 1930s radio filter, and loops location-appropriate ambient sound.

**Architecture:** A new `noir/audio/` package exposes a thin public API (`init`, `shutdown`, `speak`, `set_location`, `flush`, `register_voice`). `display.py` calls this API after each text output. A background worker thread drains a speech queue so the game never waits on audio. If `--no-audio` is passed or Kokoro isn't installed, every call is a silent no-op.

**Tech Stack:** `kokoro` (TTS), `sounddevice` (playback), `soundfile` (WAV loading), `numpy` + `scipy` (radio filter DSP)

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `noir/audio/__init__.py` | Create | Public API: `init`, `shutdown`, `speak`, `set_location`, `flush`, `register_voice`, `voice_for` |
| `noir/audio/tts.py` | Create | Kokoro wrapper, radio filter functions, `speak_blocking` |
| `noir/audio/ambient.py` | Create | Looping ambient manager with crossfade, location→clip mapping |
| `noir/audio/queue_worker.py` | Create | Background thread draining speech queue |
| `noir/data/audio/ambient/.gitkeep` | Create | Placeholder for ambient WAV files |
| `scripts/gen_ambient.py` | Create | Generate synthetic CC0 ambient clips via numpy/scipy |
| `tests/test_audio.py` | Create | Unit tests (filters, queue, ambient matching, public API) |
| `noir/display.py` | Modify | Add audio calls, minimize text in audio-first mode |
| `noir/game.py` | Modify | `audio.init()` at startup, `register_voice()` per NPC, `audio.flush()` at scene transitions |
| `main.py` | Modify | Pass `--no-audio` flag to `audio.init()`, `audio.shutdown()` in finally |
| `pyproject.toml` | Modify | Add `audio` optional dependency group |
| `.gitignore` | Modify | Ignore `*.wav` in ambient dir |

---

## Task 1: Audio package scaffold with no-op guard

**Files:**
- Create: `noir/audio/__init__.py`
- Create: `noir/audio/tts.py` (stubs only)
- Create: `noir/audio/ambient.py` (stubs only)
- Create: `noir/audio/queue_worker.py` (stubs only)
- Test: `tests/test_audio.py`

- [ ] **Step 1: Write failing tests for no-op public API**

```python
# tests/test_audio.py
import os
import pytest
import noir.audio as audio


def test_init_noop_does_not_crash():
    audio.init(no_audio=True)
    audio.shutdown()


def test_speak_noop_does_not_crash():
    audio.init(no_audio=True)
    audio.speak("hello darkness", "am_adam")
    audio.shutdown()


def test_set_location_noop_does_not_crash():
    audio.init(no_audio=True)
    audio.set_location("The Precinct")
    audio.shutdown()


def test_flush_noop_does_not_crash():
    audio.init(no_audio=True)
    audio.flush()
    audio.shutdown()


def test_register_voice_and_voice_for():
    audio.register_voice("Big Al", "am_michael")
    assert audio.voice_for("Big Al") == "am_michael"


def test_voice_for_unknown_speaker_returns_default():
    result = audio.voice_for("Some Unknown Person")
    assert isinstance(result, str) and len(result) > 0


def test_env_var_forces_noop(monkeypatch):
    monkeypatch.setenv("NOIR_NO_AUDIO", "1")
    audio.init()  # reads env var, goes no-op
    audio.speak("test", "am_adam")  # must not crash
    audio.shutdown()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_audio.py -v
```

Expected: `ModuleNotFoundError: No module named 'noir.audio'`

- [ ] **Step 3: Create stub files**

```python
# noir/audio/__init__.py
import os

_no_audio: bool = False
_voice_registry: dict[str, str] = {}

NARRATOR_VOICE = "bm_george"

_ROLE_VOICES: dict[str, str] = {
    "police": "bm_george",
    "detective": "am_michael",
    "district attorney": "bm_george",
    "judge": "bm_george",
    "magistrate": "bm_george",
}

_GENDER_VOICES: dict[str, str] = {
    "female": "af_bella",
    "woman": "af_bella",
    "male": "am_adam",
    "man": "am_adam",
}


def init(no_audio: bool = False) -> None:
    global _no_audio
    _no_audio = no_audio or os.environ.get("NOIR_NO_AUDIO") == "1"


def shutdown() -> None:
    pass


def speak(text: str, voice_id: str) -> None:
    pass


def set_location(location_type: str) -> None:
    pass


def flush() -> None:
    pass


def register_voice(name: str, voice_id: str) -> None:
    _voice_registry[name.lower()] = voice_id


def voice_for(speaker: str) -> str:
    key = speaker.lower()
    if key in _voice_registry:
        return _voice_registry[key]
    for role_kw, voice in _ROLE_VOICES.items():
        if role_kw in key:
            return voice
    return "am_adam"
```

```python
# noir/audio/tts.py
import numpy as np


def apply_voice_filter(audio: np.ndarray, sr: int, seed: int = 0) -> np.ndarray:
    return audio


def apply_ambient_filter(audio: np.ndarray, sr: int, seed: int = 0) -> np.ndarray:
    return audio


def generate_audio(text: str, voice_id: str) -> np.ndarray:
    return np.zeros(0, dtype=np.float32)


def speak_blocking(text: str, voice_id: str) -> None:
    pass
```

```python
# noir/audio/ambient.py
from pathlib import Path

_AMBIENT_DIR = Path(__file__).parent.parent / "data" / "audio" / "ambient"


def _match_location(location_type: str) -> str:
    return "city_night.wav"


class AmbientManager:
    def __init__(self, ambient_dir: Path = _AMBIENT_DIR) -> None:
        self._dir = ambient_dir

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def set_location(self, location_type: str) -> None:
        pass
```

```python
# noir/audio/queue_worker.py
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
```

- [ ] **Step 4: Create ambient data directory**

```bash
mkdir -p noir/data/audio/ambient
touch noir/data/audio/ambient/.gitkeep
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_audio.py -v
```

Expected: 7 tests pass.

- [ ] **Step 6: Commit**

```bash
git add noir/audio/ noir/data/audio/ tests/test_audio.py
git commit -m "feat: audio package scaffold with no-op public API"
```

---

## Task 2: Radio filter functions

**Files:**
- Modify: `noir/audio/tts.py` (replace stub filters with real implementation)
- Modify: `tests/test_audio.py` (add filter tests)

- [ ] **Step 1: Write failing filter tests**

Add to `tests/test_audio.py`:

```python
import numpy as np
import pytest
from scipy.fft import fft, fftfreq
from noir.audio.tts import (
    apply_voice_filter,
    apply_ambient_filter,
    _bandpass_filter,
    _soft_compress,
    _add_crackle,
)


def _white_noise(n: int = 24000, sr: int = 24000):
    return np.random.default_rng(0).standard_normal(n).astype(np.float32), sr


def _power_at_freq_range(audio: np.ndarray, sr: int, low: float, high: float) -> float:
    freqs = fftfreq(len(audio), 1 / sr)
    spectrum = np.abs(fft(audio))
    mask = (np.abs(freqs) >= low) & (np.abs(freqs) <= high)
    return float(spectrum[mask].mean())


def test_bandpass_attenuates_low_frequencies():
    audio, sr = _white_noise()
    before = _power_at_freq_range(audio, sr, 0, 100)
    after = _power_at_freq_range(_bandpass_filter(audio, sr), sr, 0, 100)
    assert after < before * 0.1


def test_bandpass_attenuates_high_frequencies():
    audio, sr = _white_noise()
    before = _power_at_freq_range(audio, sr, 4000, 8000)
    after = _power_at_freq_range(_bandpass_filter(audio, sr), sr, 4000, 8000)
    assert after < before * 0.1


def test_bandpass_preserves_midrange():
    audio, sr = _white_noise()
    before = _power_at_freq_range(audio, sr, 500, 2000)
    after = _power_at_freq_range(_bandpass_filter(audio, sr), sr, 500, 2000)
    assert after > before * 0.3


def test_soft_compress_limits_peak():
    loud = np.ones(1000, dtype=np.float32) * 2.0
    result = _soft_compress(loud)
    assert np.max(np.abs(result)) < 0.95


def test_voice_filter_adds_crackle_to_silence():
    silent = np.zeros(24000, dtype=np.float32)
    result = _add_crackle(silent, np.random.default_rng(42))
    assert np.any(result != 0.0)


def test_different_seeds_give_different_crackle():
    audio = np.zeros(24000, dtype=np.float32)
    r1 = _add_crackle(audio, np.random.default_rng(0))
    r2 = _add_crackle(audio, np.random.default_rng(1))
    assert not np.array_equal(r1, r2)


def test_voice_filter_applies_all_stages():
    audio, sr = _white_noise()
    result = apply_voice_filter(audio, sr, seed=0)
    # compressed → peak well below original amplitude
    assert np.max(np.abs(result)) < np.max(np.abs(audio))


def test_ambient_filter_no_compression():
    # uniform amplitude → tanh compression would flatten it, but ambient has none
    uniform = np.full(24000, 0.5, dtype=np.float32)
    voice_result = apply_voice_filter(uniform, 24000, seed=0)
    ambient_result = apply_ambient_filter(uniform, 24000, seed=0)
    # ambient should have higher peak than voice (no tanh squash)
    assert np.max(np.abs(ambient_result)) > np.max(np.abs(voice_result))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_audio.py::test_bandpass_attenuates_low_frequencies -v
```

Expected: FAIL — stub filter returns audio unchanged.

- [ ] **Step 3: Implement filter functions in `noir/audio/tts.py`**

Replace the entire contents of `noir/audio/tts.py` with:

```python
import numpy as np
from scipy.signal import butter, sosfilt

_SR = 24000
_pipeline = None


def _bandpass_filter(audio: np.ndarray, sr: int) -> np.ndarray:
    sos = butter(4, [300, 3400], btype="bandpass", fs=sr, output="sos")
    return sosfilt(sos, audio).astype(np.float32)


def _soft_compress(audio: np.ndarray) -> np.ndarray:
    peak = np.max(np.abs(audio))
    if peak < 1e-8:
        return audio
    normalized = audio / peak * 0.8
    return (np.tanh(normalized * 3) / 3).astype(np.float32)


def _add_crackle(audio: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    result = audio.copy()
    n_bursts = max(1, int(len(audio) * 0.002))
    if len(audio) <= 10:
        return result
    positions = rng.integers(0, len(audio) - 10, size=n_bursts)
    for pos in positions:
        burst = rng.standard_normal(10).astype(np.float32) * 0.15
        result[pos : pos + 10] += burst
    return result


def apply_voice_filter(audio: np.ndarray, sr: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    audio = _bandpass_filter(audio, sr)
    audio = _soft_compress(audio)
    audio = _add_crackle(audio, rng)
    return audio


def apply_ambient_filter(audio: np.ndarray, sr: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    audio = _bandpass_filter(audio, sr)
    audio = _add_crackle(audio, rng)
    return audio


def generate_audio(text: str, voice_id: str) -> np.ndarray:
    global _pipeline
    try:
        from kokoro import KPipeline
    except ImportError:
        raise RuntimeError("kokoro not installed — run: pip install 'noir-detective[audio]'")
    if _pipeline is None:
        _pipeline = KPipeline(lang_code="a")
    chunks = []
    for _, _, audio in _pipeline(text, voice=voice_id, speed=0.92):
        if audio is not None:
            chunks.append(np.asarray(audio, dtype=np.float32))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks)


def speak_blocking(text: str, voice_id: str) -> None:
    import sounddevice as sd
    audio = generate_audio(text, voice_id)
    if len(audio) == 0:
        return
    audio = apply_voice_filter(audio, _SR)
    sd.play(audio, samplerate=_SR)
    sd.wait()
```

- [ ] **Step 4: Run tests**

```bash
python3 -m pytest tests/test_audio.py -v -k "bandpass or compress or crackle or filter"
```

Expected: 9 filter tests pass. (The Kokoro tests are not run — they'd need the model.)

- [ ] **Step 5: Commit**

```bash
git add noir/audio/tts.py tests/test_audio.py
git commit -m "feat: radio filter chain (bandpass, compression, crackle)"
```

---

## Task 3: Speech queue worker

**Files:**
- Modify: `noir/audio/queue_worker.py` (replace stub with real implementation)
- Modify: `tests/test_audio.py` (add queue tests)

- [ ] **Step 1: Write failing queue worker tests**

Add to `tests/test_audio.py`:

```python
import threading
import time
from noir.audio.queue_worker import SpeechQueueWorker, SpeechItem


def test_worker_calls_speak_fn_for_enqueued_item():
    calls = []

    def fake_speak(text, voice_id):
        calls.append((text, voice_id))

    worker = SpeechQueueWorker(speak_fn=fake_speak)
    worker.enqueue(SpeechItem(text="hello", voice_id="am_adam"))
    worker.shutdown()
    assert ("hello", "am_adam") in calls


def test_worker_processes_multiple_items_in_order():
    calls = []

    def fake_speak(text, voice_id):
        calls.append(text)

    worker = SpeechQueueWorker(speak_fn=fake_speak)
    for word in ["one", "two", "three"]:
        worker.enqueue(SpeechItem(text=word, voice_id="am_adam"))
    worker.shutdown()
    assert calls == ["one", "two", "three"]


def test_flush_discards_queued_items():
    gate = threading.Event()
    processed = []

    def slow_speak(text, voice_id):
        gate.wait()
        processed.append(text)

    worker = SpeechQueueWorker(speak_fn=slow_speak)
    worker.enqueue(SpeechItem(text="first", voice_id="am_adam"))
    worker.enqueue(SpeechItem(text="second", voice_id="am_adam"))
    worker.enqueue(SpeechItem(text="third", voice_id="am_adam"))
    worker.flush()
    gate.set()
    worker.shutdown()
    assert "second" not in processed
    assert "third" not in processed


def test_flush_items_after_flush_are_processed():
    calls = []

    def fake_speak(text, voice_id):
        calls.append(text)

    worker = SpeechQueueWorker(speak_fn=fake_speak)
    worker.flush()
    worker.enqueue(SpeechItem(text="after_flush", voice_id="am_adam"))
    worker.shutdown()
    assert "after_flush" in calls


def test_worker_continues_after_speak_exception():
    calls = []

    def flaky_speak(text, voice_id):
        if text == "crash":
            raise RuntimeError("device error")
        calls.append(text)

    worker = SpeechQueueWorker(speak_fn=flaky_speak)
    worker.enqueue(SpeechItem(text="crash", voice_id="am_adam"))
    worker.enqueue(SpeechItem(text="recovered", voice_id="am_adam"))
    worker.shutdown()
    assert "recovered" in calls
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_audio.py::test_worker_calls_speak_fn_for_enqueued_item -v
```

Expected: FAIL — stub enqueue does nothing.

- [ ] **Step 3: Implement `queue_worker.py`**

Replace the entire contents of `noir/audio/queue_worker.py` with:

```python
import queue
import threading
from dataclasses import dataclass
from typing import Callable

_FLUSH = object()
_STOP = object()


@dataclass
class SpeechItem:
    text: str
    voice_id: str


class SpeechQueueWorker:
    def __init__(self, speak_fn: Callable[[str, str], None]) -> None:
        self._q: queue.Queue = queue.Queue()
        self._speak_fn = speak_fn
        self._thread = threading.Thread(target=self._run, daemon=True, name="audio-queue")
        self._thread.start()

    def enqueue(self, item: SpeechItem) -> None:
        self._q.put(item)

    def flush(self) -> None:
        self._q.put(_FLUSH)

    def shutdown(self) -> None:
        self._q.put(_STOP)
        self._thread.join(timeout=3.0)

    def _run(self) -> None:
        while True:
            item = self._q.get()
            if item is _STOP:
                break
            if item is _FLUSH:
                while True:
                    try:
                        self._q.get_nowait()
                    except queue.Empty:
                        break
                continue
            try:
                self._speak_fn(item.text, item.voice_id)
            except Exception:
                pass
```

- [ ] **Step 4: Run queue tests**

```bash
python3 -m pytest tests/test_audio.py -v -k "worker or flush"
```

Expected: 5 queue tests pass.

- [ ] **Step 5: Commit**

```bash
git add noir/audio/queue_worker.py tests/test_audio.py
git commit -m "feat: background speech queue worker"
```

---

## Task 4: Ambient manager with location matching

**Files:**
- Modify: `noir/audio/ambient.py` (replace stub with real implementation)
- Modify: `tests/test_audio.py` (add ambient tests)

- [ ] **Step 1: Write failing ambient tests**

Add to `tests/test_audio.py`:

```python
from pathlib import Path
from noir.audio.ambient import _match_location, AmbientManager


def test_match_speakeasy():
    assert _match_location("The Lucky Speakeasy") == "speakeasy_jazz.wav"


def test_match_precinct():
    assert _match_location("The Precinct") == "police_station.wav"


def test_match_docks():
    assert _match_location("Bourbon Street Docks") == "docks.wav"


def test_match_courthouse():
    assert _match_location("The Courthouse") == "courthouse.wav"


def test_match_apartment():
    assert _match_location("Clara's Apartment") == "apartment_rain.wav"


def test_match_street():
    assert _match_location("Rue Bourbon, Rainy Street") == "street_rain.wav"


def test_match_default():
    assert _match_location("Somewhere Unknown") == "city_night.wav"


def test_set_location_missing_file_no_crash(tmp_path):
    manager = AmbientManager(ambient_dir=tmp_path)
    manager.set_location("The Precinct")  # file not present → silent skip


def test_set_location_wrong_dir_no_crash():
    manager = AmbientManager(ambient_dir=Path("/nonexistent/path"))
    manager.set_location("The Speakeasy")  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_audio.py -v -k "match or ambient"
```

Expected: FAIL — stub `_match_location` always returns `"city_night.wav"`.

- [ ] **Step 3: Implement `ambient.py`**

Replace the entire contents of `noir/audio/ambient.py` with:

```python
import threading
import logging
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

_AMBIENT_DIR = Path(__file__).parent.parent / "data" / "audio" / "ambient"

_LOCATION_KEYWORDS: list[tuple[list[str], str]] = [
    (["speakeasy", "bar", "club", "lounge", "jazz"], "speakeasy_jazz.wav"),
    (["precinct", "police", "station"], "police_station.wav"),
    (["courthouse", "court"], "courthouse.wav"),
    (["docks", "wharf", "harbor", "pier"], "docks.wav"),
    (["apartment", "flat", "room", "office"], "apartment_rain.wav"),
    (["street", "alley", "sidewalk", "avenue", "rue"], "street_rain.wav"),
]
_DEFAULT_CLIP = "city_night.wav"


def _match_location(location_type: str) -> str:
    lt = location_type.lower()
    for keywords, clip in _LOCATION_KEYWORDS:
        if any(kw in lt for kw in keywords):
            return clip
    return _DEFAULT_CLIP


class AmbientManager:
    def __init__(self, ambient_dir: Path = _AMBIENT_DIR) -> None:
        self._dir = ambient_dir
        self._audio: np.ndarray | None = None
        self._sr: int = 24000
        self._pos: int = 0
        self._volume: float = 0.0
        self._target_volume: float = 0.35
        self._lock = threading.Lock()
        self._stream = None

    def start(self) -> None:
        try:
            import sounddevice as sd
            self._stream = sd.OutputStream(
                samplerate=self._sr,
                channels=1,
                dtype="float32",
                callback=self._callback,
                blocksize=1024,
            )
            self._stream.start()
        except Exception as e:
            log.warning("ambient stream failed to start: %s", e)

    def stop(self) -> None:
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def set_location(self, location_type: str) -> None:
        clip_name = _match_location(location_type)
        clip_path = self._dir / clip_name
        if not clip_path.exists():
            return
        try:
            import soundfile as sf
            from noir.audio.tts import apply_ambient_filter
            audio, sr = sf.read(str(clip_path), dtype="float32")
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            audio = apply_ambient_filter(audio, sr)
            with self._lock:
                self._audio = audio
                self._sr = sr
                self._pos = 0
                self._target_volume = 0.35
        except Exception as e:
            log.warning("ambient set_location failed for %r: %s", clip_name, e)

    def _callback(self, outdata, frames, time_info, status) -> None:
        with self._lock:
            outdata[:] = 0
            if self._audio is None:
                return
            self._volume += (self._target_volume - self._volume) * 0.05
            chunk = np.zeros(frames, dtype=np.float32)
            n = len(self._audio)
            remaining = n - self._pos
            if remaining >= frames:
                chunk[:] = self._audio[self._pos : self._pos + frames]
                self._pos += frames
            else:
                chunk[:remaining] = self._audio[self._pos :]
                leftover = frames - remaining
                loops = (leftover // n) + 1
                tiled = np.tile(self._audio, loops)
                chunk[remaining:] = tiled[:leftover]
                self._pos = leftover % n
            outdata[:, 0] = chunk * self._volume
```

- [ ] **Step 4: Run ambient tests**

```bash
python3 -m pytest tests/test_audio.py -v -k "match or ambient or location"
```

Expected: 9 ambient tests pass.

- [ ] **Step 5: Commit**

```bash
git add noir/audio/ambient.py tests/test_audio.py
git commit -m "feat: ambient manager with location keyword matching"
```

---

## Task 5: Wire public API

**Files:**
- Modify: `noir/audio/__init__.py` (replace no-op implementations with real wiring)
- Modify: `tests/test_audio.py` (add wiring test with mock speak_fn)

- [ ] **Step 1: Write failing wiring test**

Add to `tests/test_audio.py`:

```python
def test_speak_enqueues_when_audio_active():
    """Replace speak_blocking with a fake to verify speak() routes through queue."""
    import noir.audio as audio
    import noir.audio.queue_worker as qw

    calls = []
    original_worker_class = qw.SpeechQueueWorker

    class FakeWorker:
        def __init__(self, speak_fn):
            self._speak_fn = speak_fn
        def enqueue(self, item):
            calls.append((item.text, item.voice_id))
        def flush(self):
            calls.append(("__flush__", ""))
        def shutdown(self):
            pass

    qw.SpeechQueueWorker = FakeWorker
    try:
        audio.init(no_audio=False)
        audio._no_audio = False  # force active even without kokoro
        audio.speak("test line", "am_adam")
        assert ("test line", "am_adam") in calls
    finally:
        qw.SpeechQueueWorker = original_worker_class
        audio.shutdown()
        audio._no_audio = True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_audio.py::test_speak_enqueues_when_audio_active -v
```

Expected: FAIL — `speak()` is still a no-op stub.

- [ ] **Step 3: Replace `noir/audio/__init__.py` with wired implementation**

```python
# noir/audio/__init__.py
import logging
import os

log = logging.getLogger(__name__)

_no_audio: bool = False
_worker = None
_ambient = None
_voice_registry: dict[str, str] = {}

NARRATOR_VOICE = "bm_george"

_ROLE_VOICES: dict[str, str] = {
    "police": "bm_george",
    "detective": "am_michael",
    "district attorney": "bm_george",
    "judge": "bm_george",
    "magistrate": "bm_george",
}


def init(no_audio: bool = False) -> None:
    global _no_audio, _worker, _ambient
    _no_audio = no_audio or os.environ.get("NOIR_NO_AUDIO") == "1"
    if _no_audio:
        return
    try:
        from noir.audio.tts import speak_blocking
        from noir.audio.queue_worker import SpeechQueueWorker
        from noir.audio.ambient import AmbientManager
        _worker = SpeechQueueWorker(speak_fn=speak_blocking)
        _ambient = AmbientManager()
        _ambient.start()
    except Exception as e:
        log.warning("audio init failed, running silent: %s", e)
        _no_audio = True


def shutdown() -> None:
    global _worker, _ambient
    if _worker is not None:
        _worker.shutdown()
        _worker = None
    if _ambient is not None:
        _ambient.stop()
        _ambient = None


def speak(text: str, voice_id: str) -> None:
    if _no_audio or _worker is None:
        return
    from noir.audio.queue_worker import SpeechItem
    _worker.enqueue(SpeechItem(text=text, voice_id=voice_id))


def set_location(location_type: str) -> None:
    if _no_audio or _ambient is None:
        return
    _ambient.set_location(location_type)


def flush() -> None:
    if _no_audio or _worker is None:
        return
    _worker.flush()


def register_voice(name: str, voice_id: str) -> None:
    _voice_registry[name.lower()] = voice_id


def voice_for(speaker: str) -> str:
    key = speaker.lower()
    if key in _voice_registry:
        return _voice_registry[key]
    for role_kw, voice in _ROLE_VOICES.items():
        if role_kw in key:
            return voice
    return "am_adam"
```

- [ ] **Step 4: Run all audio tests**

```bash
python3 -m pytest tests/test_audio.py -v
```

Expected: all tests pass (the wiring test now passes; NOIR_NO_AUDIO still covers no-op tests).

- [ ] **Step 5: Commit**

```bash
git add noir/audio/__init__.py tests/test_audio.py
git commit -m "feat: wire audio public API to queue worker and ambient manager"
```

---

## Task 6: Display integration

**Files:**
- Modify: `noir/display.py`

The display functions currently print full text. In audio-first mode, we reduce text to speaker names / location names only and enqueue speech.

- [ ] **Step 1: Read the current display functions**

Open `noir/display.py` and locate these functions (line numbers may shift — use grep):
- `show_narrator` (~line 256)
- `show_dialogue` (~line 445)
- `show_partner_aside` (~line 457)
- `show_location` (~line 431)
- `show_travel_animation` (~line 400)
- `start_new_case` / scene transitions call `flush()` — handled in Task 7

- [ ] **Step 2: Modify `show_narrator`**

Find:
```python
def show_narrator(text: str) -> None:
    console.print()
    console.print(f"[dim italic]{escape(text)}[/dim italic]")
    console.print()
```

Replace with:
```python
def show_narrator(text: str) -> None:
    import noir.audio as audio
    audio.speak(text, audio.NARRATOR_VOICE)
```

- [ ] **Step 3: Modify `show_dialogue`**

Find:
```python
def show_dialogue(speaker: str, text: str, delay: float = 0.02) -> None:
    console.print(f"\n[bold cyan]{speaker}:[/bold cyan]")
    console.print(Markdown(text))
    console.print()
```

Replace with:
```python
def show_dialogue(speaker: str, text: str, delay: float = 0.02) -> None:
    import noir.audio as audio
    audio.speak(text, audio.voice_for(speaker))
    console.print(f"\n[bold cyan]{escape(speaker)}[/bold cyan]")
```

- [ ] **Step 4: Modify `show_partner_aside`**

Find:
```python
def show_partner_aside(speaker: str, text: str) -> None:
    console.print(f"\n[dim cyan]{escape(speaker)}:[/dim cyan] [italic]{escape(text)}[/italic]")
```

Replace with:
```python
def show_partner_aside(speaker: str, text: str) -> None:
    import noir.audio as audio
    audio.speak(text, audio.voice_for(speaker))
    console.print(f"\n[dim cyan]{escape(speaker)}:[/dim cyan] [italic](aside)[/italic]")
```

- [ ] **Step 5: Modify `show_location`**

Find:
```python
def show_location(name: str, description: str, npcs_present: list[str],
                  game_time: int | None = None,
                  orgs: list[str] | None = None) -> None:
    npc_text = f"\n\n[dim]Present: {', '.join(npcs_present)}[/dim]" if npcs_present else ""
    org_text = f"\n[dim]Controlled by: {', '.join(orgs)}[/dim]" if orgs else ""
    time_text = f"  [dim]{fmt_game_time(game_time)}[/dim]" if game_time is not None else ""
    console.print(Panel(
        f"[italic]{description}[/italic]{npc_text}{org_text}",
        title=f"[bold yellow]{name}[/bold yellow]{time_text}",
        border_style="yellow",
        box=box.DOUBLE_EDGE,
    ))
```

Replace with:
```python
def show_location(name: str, description: str, npcs_present: list[str],
                  game_time: int | None = None,
                  orgs: list[str] | None = None) -> None:
    import noir.audio as audio
    audio.speak(name, audio.NARRATOR_VOICE)
    audio.set_location(name)
    time_text = f"  [dim]{fmt_game_time(game_time)}[/dim]" if game_time is not None else ""
    npc_text = f"[dim]Present: {', '.join(npcs_present)}[/dim]" if npcs_present else ""
    console.print(Panel(
        npc_text,
        title=f"[bold yellow]{escape(name)}[/bold yellow]{time_text}",
        border_style="yellow",
        box=box.DOUBLE_EDGE,
    ))
```

- [ ] **Step 6: Run existing test suite to confirm nothing broke**

```bash
python3 -m pytest tests/ -v
```

Expected: all tests pass (audio calls are no-ops in tests because `NOIR_NO_AUDIO` is not set but `audio.init()` was never called, so `_worker` is None).

- [ ] **Step 7: Commit**

```bash
git add noir/display.py
git commit -m "feat: display integration — audio calls on narrator/dialogue/location"
```

---

## Task 7: Game and main wiring

**Files:**
- Modify: `noir/game.py`
- Modify: `main.py`

- [ ] **Step 1: Add NPC voice inference helper to `game.py`**

Near the top of `game.py`, after the existing module-level helpers (around line 90), add:

```python
def _infer_npc_voice(system_prompt: str) -> str:
    """Infer Kokoro voice ID from NPC system prompt pronouns."""
    sp = system_prompt.lower()
    female_signals = [" she ", " her ", " herself ", "woman", "lady", "mrs.", "miss "]
    if any(s in sp for s in female_signals):
        return "af_bella"
    return "am_adam"
```

- [ ] **Step 2: Register NPC voice when conversation starts**

In `handle_talk`, find where `npc_row` is confirmed valid and `npc` is loaded (around line 1275):

```python
        npc = NPC.load(
            conn=self.conn,
            llm=self.llm,
            npc_id=npc_row["id"],
            case_id=self.active_case_id,
        )
```

Add the voice registration immediately after `npc = NPC.load(...)`:

```python
        import noir.audio as audio
        audio.register_voice(
            npc_row["name"],
            _infer_npc_voice(npc_row["system_prompt"]),
        )
```

- [ ] **Step 3: Register companion voice at startup**

In `loop()`, find where `self.companion` is set — both paths: `run_onboarding()` returns and sets `self.companion`, and the `else` branch that calls `Companion.load`. After each, the companion name is available via `self.companion.name`.

Find (around line 3806):
```python
        else:
            self.companion = Companion.load(conn=self.conn, llm=self.llm)
            console.print("\n[bold yellow]Welcome back, detective.[/bold yellow]")
```

Add after `self.companion = Companion.load(...)`:
```python
            import noir.audio as audio
            audio.register_voice(self.companion.name, "af_bella")
```

Then find where `run_onboarding()` ends — onboarding sets `self.companion` internally. After `self.run_onboarding()` (around line 3804):
```python
        if not is_returning:
            self.run_onboarding()
```

Add after:
```python
            if self.companion:
                import noir.audio as audio
                audio.register_voice(self.companion.name, "af_bella")
```

- [ ] **Step 4: Add `audio.flush()` at scene transitions**

In `start_new_case` (around line 1068), at the very top of the method body, add:

```python
        import noir.audio as audio
        audio.flush()
```

In `handle_go`, after `show_travel_animation()` calls (around lines 1175 and 1181), add `audio.flush()` before each `show_travel_animation()`:

Find:
```python
            show_travel_animation()
            show_location_rule()
            show_location(loc["name"], ...
```

The first `show_travel_animation()` — add `audio.flush()` before it:
```python
            import noir.audio as audio
            audio.flush()
            show_travel_animation()
```

Do the same for the second `show_travel_animation()` call in `handle_go`.

- [ ] **Step 5: Update `main.py`**

Replace `main.py` with:

```python
import sys
import atexit
try:
    import readline
    from pathlib import Path
    _HIST = Path.home() / ".noir_detective" / "history"
    _HIST.parent.mkdir(parents=True, exist_ok=True)
    if _HIST.exists():
        readline.read_history_file(str(_HIST))
    readline.set_history_length(500)
    atexit.register(readline.write_history_file, str(_HIST))
except ImportError:
    pass
from noir.log import setup_logging
from noir.persistence.db import get_connection
from noir.llm.config import load_config
from noir.llm.base import LLMBackend
from noir.game import Game


def _maybe_enable_hot_reload() -> None:
    if "--dev" not in sys.argv:
        return
    try:
        import jurigged
        jurigged.watch("noir/", logger=lambda *_, **__: None)
        print("[dev] Hot-reload active — save any file in noir/ to patch it live.")
    except ImportError:
        print("[dev] Install jurigged for hot-reload: pip install jurigged")
        sys.exit(1)


def create_backend(config: dict) -> LLMBackend:
    backend = config.get("backend", "claude_cli")
    if backend == "claude_cli":
        from noir.llm.claude_cli import ClaudeCLIBackend
        return ClaudeCLIBackend(
            dialogue_model=config.get("dialogue_model", "sonnet"),
            structured_model=config.get("structured_model", "haiku"),
        )
    if backend == "ollama":
        from noir.llm.ollama import OllamaBackend
        return OllamaBackend(
            model=config.get("model", "qwen2.5:14b"),
            host=config.get("host", "http://localhost:11434"),
        )
    raise ValueError(
        f"Unknown backend '{backend}'. "
        f"Edit ~/.noir_detective/config.json to set a valid backend."
    )


def _maybe_wipe_db() -> None:
    if "--reset" not in sys.argv:
        return
    from noir.persistence.db import DB_PATH
    confirm = input("Wipe the database and start over? This cannot be undone. (yes/no): ").strip().lower()
    if confirm == "yes":
        if DB_PATH.exists():
            DB_PATH.unlink()
        print("Database wiped.")
    else:
        print("Cancelled.")
        sys.exit(0)


def main():
    _maybe_wipe_db()
    _maybe_enable_hot_reload()
    setup_logging()
    config = load_config()
    conn = get_connection()
    llm = create_backend(config)

    import noir.audio as audio
    audio.init(no_audio="--no-audio" in sys.argv)

    game = Game(conn=conn, llm=llm)
    try:
        game.loop()
    finally:
        audio.shutdown()


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run full test suite**

```bash
python3 -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add noir/game.py main.py
git commit -m "feat: wire audio init/shutdown/flush/register_voice into game loop"
```

---

## Task 8: Dependencies and synthetic ambient clips

**Files:**
- Modify: `pyproject.toml`
- Modify: `.gitignore`
- Create: `scripts/gen_ambient.py`

- [ ] **Step 1: Update `pyproject.toml`**

Add an `audio` optional dependency group. Find:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=4.0",
    "jurigged>=0.5",
]
```

Replace with:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=4.0",
    "jurigged>=0.5",
    "scipy>=1.13",
]
audio = [
    "kokoro>=0.9",
    "sounddevice>=0.5",
    "soundfile>=0.13",
    "scipy>=1.13",
]
```

Install audio deps:

```bash
pip install 'noir-detective[audio]'
```

Or directly:

```bash
pip install kokoro sounddevice soundfile scipy
```

- [ ] **Step 2: Update `.gitignore`**

Add to `.gitignore`:

```
# synthetic ambient audio clips (generated locally)
noir/data/audio/ambient/*.wav
```

- [ ] **Step 3: Create `scripts/gen_ambient.py`**

```python
#!/usr/bin/env python3
"""Generate synthetic CC0 ambient audio clips for noir-leans.

Run once: python scripts/gen_ambient.py
Clips are written to noir/data/audio/ambient/ and gitignored.
Replace with higher-quality recordings from freesound.org (CC0) if desired.
"""
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt, lfilter

OUT = Path(__file__).parent.parent / "noir" / "data" / "audio" / "ambient"
OUT.mkdir(parents=True, exist_ok=True)

SR = 24000
DURATION = 20


def pink_noise(n: int) -> np.ndarray:
    white = np.random.randn(n).astype(np.float32)
    b = [0.049922035, -0.095993537, 0.050612699, -0.004408786]
    a = [1, -2.494956002, 2.017265875, -0.522189400]
    return lfilter(b, a, white).astype(np.float32)


def normalize(audio: np.ndarray, peak: float = 0.4) -> np.ndarray:
    return (audio / (np.max(np.abs(audio)) + 1e-8) * peak).astype(np.float32)


def bandpass(audio: np.ndarray, low: float, high: float) -> np.ndarray:
    sos = butter(2, [low, high], btype="bandpass", fs=SR, output="sos")
    return sosfilt(sos, audio).astype(np.float32)


def gen_rain() -> np.ndarray:
    n = SR * DURATION
    rain = pink_noise(n)
    rng = np.random.default_rng(42)
    for _ in range(40):
        pos = rng.integers(0, n - 300)
        rain[pos : pos + 300] += (rng.standard_normal(300) * 0.3).astype(np.float32)
    return normalize(rain, 0.35)


def gen_jazz() -> np.ndarray:
    n = SR * DURATION
    t = np.linspace(0, DURATION, n, dtype=np.float32)
    freqs = [261.6, 329.6, 392.0, 493.9, 523.2]  # Cmaj7 + octave C
    audio = np.zeros(n, dtype=np.float32)
    for i, f in enumerate(freqs):
        wave = np.sin(2 * np.pi * f * t)
        wave *= 0.6 + 0.4 * np.sin(2 * np.pi * (4.5 + i * 0.3) * t)
        audio += wave * 0.12
    audio += np.random.randn(n).astype(np.float32) * 0.008
    return normalize(bandpass(audio, 150, 4000), 0.3)


def gen_typewriters() -> np.ndarray:
    n = SR * DURATION
    base = np.zeros(n, dtype=np.float32)
    rng = np.random.default_rng(7)
    for _ in range(100):
        pos = rng.integers(0, n - 60)
        base[pos : pos + 60] += (rng.standard_normal(60) * 0.6).astype(np.float32)
    clatter = bandpass(base, 600, 5000)
    murmur = pink_noise(n) * 0.04
    return normalize(clatter + murmur, 0.35)


def gen_courthouse() -> np.ndarray:
    n = SR * DURATION
    base = pink_noise(n) * 0.1
    rng = np.random.default_rng(99)
    for _ in range(6):
        pos = rng.integers(0, n - SR // 3)
        length = SR // 3
        echo = np.exp(-np.linspace(0, 4, length)) * rng.standard_normal(length).astype(np.float32)
        base[pos : pos + length] += echo * 0.3
    return normalize(bandpass(base, 100, 3000), 0.25)


def gen_water() -> np.ndarray:
    n = SR * DURATION
    pink = pink_noise(n)
    rumble = bandpass(pink, 50, 500)
    rng = np.random.default_rng(13)
    for _ in range(10):
        pos = rng.integers(0, n - SR // 2)
        length = SR // 2
        slap = np.exp(-np.linspace(0, 5, length)) * rng.standard_normal(length).astype(np.float32)
        rumble[pos : pos + length] += slap * 0.25
    return normalize(rumble, 0.35)


clips = {
    "street_rain.wav": gen_rain,
    "apartment_rain.wav": gen_rain,
    "city_night.wav": gen_rain,
    "speakeasy_jazz.wav": gen_jazz,
    "police_station.wav": gen_typewriters,
    "courthouse.wav": gen_courthouse,
    "docks.wav": gen_water,
}

print("Generating synthetic ambient clips...")
for filename, fn in clips.items():
    path = OUT / filename
    audio = fn()
    sf.write(str(path), audio, SR)
    print(f"  {filename}  ({len(audio) // SR}s)")
print(f"\nWritten to {OUT}")
print("Replace with CC0 recordings from freesound.org for higher quality.")
```

- [ ] **Step 4: Generate the clips**

```bash
python3 scripts/gen_ambient.py
```

Expected output:
```
Generating synthetic ambient clips...
  street_rain.wav  (20s)
  apartment_rain.wav  (20s)
  city_night.wav  (20s)
  speakeasy_jazz.wav  (20s)
  police_station.wav  (20s)
  courthouse.wav  (20s)
  docks.wav  (20s)

Written to noir/data/audio/ambient
Replace with CC0 recordings from freesound.org for higher quality.
```

- [ ] **Step 5: Run full test suite**

```bash
python3 -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore scripts/gen_ambient.py noir/data/audio/ambient/.gitkeep
git commit -m "feat: audio deps, gitignore for wavs, synthetic ambient generator"
```

---

## Self-Review Checklist (for implementer)

After all tasks are complete, verify:

- [ ] `python3 main.py --no-audio` runs silently without touching audio hardware
- [ ] `NOIR_NO_AUDIO=1 python3 -m pytest tests/ -v` — all tests pass
- [ ] `python3 main.py` starts with audio (requires kokoro installed): Kokoro pipeline initializes, ambient starts at The Precinct on first location
- [ ] Dialogue in-game: speaking to an NPC triggers TTS, terminal shows speaker name only
- [ ] Traveling between locations: ambient crossfades to new location type
- [ ] `python3 scripts/gen_ambient.py` produces 7 `.wav` files in `noir/data/audio/ambient/`
