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
