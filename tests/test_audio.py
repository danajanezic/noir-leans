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
