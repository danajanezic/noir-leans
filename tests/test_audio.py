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
    yield
    _audio._voice_registry.clear()
    _audio._no_audio = False


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
    # A bandpassed signal should retain higher amplitude through ambient filter
    # than through voice filter, because ambient skips _soft_compress.
    audio, sr = _white_noise()
    voice_result = apply_voice_filter(audio, sr, seed=0)
    ambient_result = apply_ambient_filter(audio, sr, seed=0)
    # ambient skips compression → its peak must be higher than voice (which is compressed)
    assert np.max(np.abs(ambient_result)) > np.max(np.abs(voice_result))
