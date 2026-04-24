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

# Voice pools by ethnicity. Each entry is (female_pool, male_pool).
# Pools are tried in order — first match wins. Falls back to _DEFAULT_POOLS.
_ETHNICITY_POOLS: dict[str, tuple[list[str], list[str]]] = {
    "italian": (
        ["if_sara", "af_bella", "af_heart"],
        ["im_nicola", "am_adam", "am_eric"],
    ),
    "french":  (
        ["ff_siwis", "bf_alice", "bf_emma"],
        ["bm_fable", "bm_lewis", "am_liam"],
    ),
    "creole":  (
        ["ff_siwis", "af_nova", "af_river"],
        ["bm_fable", "am_onyx", "am_echo"],
    ),
    "cajun":   (
        ["ff_siwis", "af_sarah", "af_nicole"],
        ["bm_fable", "am_fenrir", "am_adam"],
    ),
    "spanish": (
        ["ef_dora", "af_jessica", "af_kore"],
        ["em_alex", "am_michael", "am_liam"],
    ),
    "cuban":   (
        ["ef_dora", "af_jessica", "af_alloy"],
        ["em_alex", "am_echo", "am_onyx"],
    ),
    "irish":   (
        ["bf_lily", "bf_alice", "af_sarah"],
        ["bm_daniel", "bm_lewis", "am_eric"],
    ),
    "british": (
        ["bf_alice", "bf_emma", "bf_lily", "bf_isabella"],
        ["bm_daniel", "bm_fable", "bm_lewis"],
    ),
    "black":   (
        ["af_nova", "af_river", "af_heart", "af_alloy"],
        ["am_onyx", "am_echo", "am_fenrir", "am_adam"],
    ),
    "white":   (
        ["af_bella", "af_jessica", "af_nicole", "af_sarah", "af_kore",
         "bf_alice", "bf_emma", "bf_lily", "bf_isabella"],
        ["am_adam", "am_eric", "am_liam", "am_michael",
         "bm_daniel", "bm_fable", "bm_lewis"],
    ),
}
# Fallback when ethnicity doesn't match any key above.
_DEFAULT_POOLS: tuple[list[str], list[str]] = (
    ["af_bella", "af_heart", "af_jessica", "af_nicole", "af_sarah",
     "af_alloy", "af_nova", "af_river", "af_kore",
     "bf_alice", "bf_emma", "bf_lily", "bf_isabella",
     "ff_siwis", "if_sara", "ef_dora"],
    ["am_adam", "am_eric", "am_liam", "am_michael", "am_onyx",
     "am_echo", "am_fenrir",
     "bm_daniel", "bm_fable", "bm_lewis",
     "im_nicola", "em_alex"],
)

_ROLE_VOICES: dict[str, str] = {
    "police": "bm_george",
    "detective": "am_michael",
    "district attorney": "bm_lewis",
    "judge": "bm_daniel",
    "magistrate": "bm_daniel",
}


def _pool_for_ethnicity(race: str | None) -> tuple[list[str], list[str]]:
    if not race:
        return _DEFAULT_POOLS
    r = race.lower()
    for key, pools in _ETHNICITY_POOLS.items():
        if key in r:
            return pools
    return _DEFAULT_POOLS


def _pick_voice(name: str, female: bool, race: str | None = None) -> str:
    """Deterministically pick a voice matched to ethnicity using the speaker's name as seed."""
    female_pool, male_pool = _pool_for_ethnicity(race)
    pool = female_pool if female else male_pool
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
