import numpy as np


def apply_voice_filter(audio: np.ndarray, sr: int, seed: int = 0) -> np.ndarray:
    return audio


def apply_ambient_filter(audio: np.ndarray, sr: int, seed: int = 0) -> np.ndarray:
    return audio


def generate_audio(text: str, voice_id: str) -> np.ndarray:
    return np.zeros(0, dtype=np.float32)


def speak_blocking(text: str, voice_id: str) -> None:
    pass
