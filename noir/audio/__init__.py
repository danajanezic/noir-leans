import hashlib
import logging
import os
import threading

log = logging.getLogger(__name__)

_no_audio: bool = False
_worker = None
_voice_registry: dict[str, str] = {}
_registry_lock = threading.Lock()

NARRATOR_VOICE = "bm_george"

# English-only voices appropriate for 1935 Noirleans.
# Excluded: am_santa, em_santa (too jolly), non-English prefixes.
_FEMALE_VOICES = [
    "af_bella", "af_heart", "af_jessica", "af_nicole", "af_sarah",
    "af_alloy", "af_nova", "af_river", "af_kore",
    "bf_alice", "bf_emma", "bf_lily", "bf_isabella",
    "ff_siwis",           # French
    "if_sara",            # Italian
    "ef_dora",            # Spanish
]
_MALE_VOICES = [
    "am_adam", "am_eric", "am_liam", "am_michael", "am_onyx",
    "am_echo", "am_fenrir",
    "bm_daniel", "bm_fable", "bm_lewis",
    "im_nicola",          # Italian
    "em_alex",            # Spanish
]

_ROLE_VOICES: dict[str, str] = {
    "police": "bm_george",
    "detective": "am_michael",
    "district attorney": "bm_lewis",
    "judge": "bm_daniel",
    "magistrate": "bm_daniel",
}


def _pick_voice(name: str, female: bool) -> str:
    """Deterministically pick a voice from the pool using the speaker's name as seed."""
    pool = _FEMALE_VOICES if female else _MALE_VOICES
    idx = int(hashlib.md5(name.lower().encode()).hexdigest(), 16) % len(pool)
    return pool[idx]


def init(no_audio: bool = False) -> None:
    global _no_audio, _worker
    _no_audio = no_audio or os.environ.get("NOIR_NO_AUDIO") == "1"
    if _no_audio:
        return
    try:
        from noir.audio.tts import speak_blocking
        from noir.audio.queue_worker import SpeechQueueWorker
        _worker = SpeechQueueWorker(speak_fn=speak_blocking)
    except Exception as e:
        log.warning("audio init failed, running silent: %s", e)
        _no_audio = True


def shutdown() -> None:
    global _worker
    if _worker is not None:
        _worker.shutdown()
        _worker = None
    from noir.audio import tts as _tts
    if _tts._out_stream is not None:
        try:
            _tts._out_stream.stop()
            _tts._out_stream.close()
        except Exception:
            pass
        _tts._out_stream = None


def speak(text: str, voice_id: str) -> None:
    if _no_audio or _worker is None:  # also covers pre-init state
        return
    from noir.audio.queue_worker import SpeechItem  # deferred to keep audio imports lazy
    _worker.enqueue(SpeechItem(text=text, voice_id=voice_id))


def set_location(location_type: str) -> None:
    pass


def flush() -> None:
    if _no_audio or _worker is None:  # also covers pre-init state
        return
    _worker.flush()


def is_audio_active() -> bool:
    """True when audio is initialised and not suppressed — display uses this for text fallback."""
    return not _no_audio and _worker is not None


def register_voice(name: str, voice_id: str) -> None:
    with _registry_lock:
        _voice_registry[name.lower()] = voice_id


def voice_for(speaker: str) -> str:
    key = speaker.lower()
    with _registry_lock:
        if key in _voice_registry:
            return _voice_registry[key]
    for role_kw, voice in _ROLE_VOICES.items():
        if role_kw in key:
            return voice
    return "am_adam"
