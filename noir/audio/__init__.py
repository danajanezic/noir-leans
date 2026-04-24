import logging
import os
import threading

log = logging.getLogger(__name__)

_no_audio: bool = False
_worker = None
_ambient = None
_voice_registry: dict[str, str] = {}
_registry_lock = threading.Lock()

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
    if _no_audio or _worker is None:  # also covers pre-init state
        return
    from noir.audio.queue_worker import SpeechItem  # deferred to keep audio imports lazy
    _worker.enqueue(SpeechItem(text=text, voice_id=voice_id))


def set_location(location_type: str) -> None:
    if _no_audio or _ambient is None:  # also covers pre-init state
        return
    _ambient.set_location(location_type)


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
