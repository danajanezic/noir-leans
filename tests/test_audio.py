# tests/test_audio.py
import os
import pytest
import noir.audio as audio


@pytest.fixture(autouse=True)
def reset_audio_state():
    """Reset module-level audio state between tests."""
    import noir.audio as _audio
    _audio._voice_registry.clear()
    _audio._no_audio = False
    _audio._worker = None
    _audio._ambient = None
    yield
    _audio._voice_registry.clear()
    _audio._no_audio = False
    if _audio._worker is not None:
        _audio._worker.shutdown()
        _audio._worker = None
    if _audio._ambient is not None:
        _audio._ambient.stop()
        _audio._ambient = None


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


import numpy as np
from noir.audio.tts import apply_voice_filter, apply_ambient_filter, _fade_edges, _FADE_SAMPLES, make_loop_seamless


def _ones(n: int = 24000) -> np.ndarray:
    return np.ones(n, dtype=np.float32)


def test_fade_edges_silences_start():
    result = _fade_edges(_ones())
    assert result[0] == 0.0
    assert result[_FADE_SAMPLES - 1] == pytest.approx(1.0, abs=0.01)


def test_fade_edges_silences_end():
    result = _fade_edges(_ones())
    assert result[-1] == 0.0
    assert result[-_FADE_SAMPLES] == pytest.approx(1.0, abs=0.01)


def test_fade_edges_preserves_middle():
    audio = _ones()
    result = _fade_edges(audio)
    mid = len(audio) // 2
    assert result[mid] == pytest.approx(1.0)


def test_fade_edges_short_clip_unchanged():
    short = np.ones(10, dtype=np.float32)
    result = _fade_edges(short)
    np.testing.assert_array_equal(result, short)


def test_apply_voice_filter_returns_float32():
    result = apply_voice_filter(_ones(), sr=24000)
    assert result.dtype == np.float32


def test_apply_ambient_filter_returns_float32():
    result = apply_ambient_filter(_ones(), sr=24000)
    assert result.dtype == np.float32


def test_make_loop_seamless_smooths_loop_point():
    # Clip that jumps from 1.0 → -1.0 at the loop point; crossfade should reduce it.
    n = 24000
    audio = np.ones(n, dtype=np.float32)
    audio[n // 2:] = -1.0  # discontinuity in the middle so loop point is bad
    result = make_loop_seamless(audio)
    # The first sample of the looped result should be blended (not the raw head value).
    assert result[0] != audio[0]


def test_make_loop_seamless_shortens_clip():
    audio = _ones(24000)
    result = make_loop_seamless(audio)
    assert len(result) < len(audio)


def test_make_loop_seamless_very_short_clip_unchanged():
    short = np.ones(4, dtype=np.float32)
    result = make_loop_seamless(short)
    np.testing.assert_array_equal(result, short)




import threading
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
        gate.wait(timeout=5.0)
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


def test_speak_enqueues_when_audio_active():
    """Replace SpeechQueueWorker with a fake to verify speak() routes through queue."""
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
