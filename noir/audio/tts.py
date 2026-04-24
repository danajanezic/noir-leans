import logging
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt

log = logging.getLogger(__name__)

_SR = 24000
_pipeline = None

_MODEL_DIR = Path.home() / ".cache" / "noir-detective" / "kokoro"
_MODEL_PATH = _MODEL_DIR / "kokoro-v1.0.onnx"
_VOICES_PATH = _MODEL_DIR / "voices-v1.0.bin"


def _bandpass_filter(audio: np.ndarray, sr: int) -> np.ndarray:
    sos = butter(4, [300, 3400], btype="bandpass", fs=sr, output="sos")
    return sosfilt(sos, audio).astype(np.float32)


def _soft_compress(audio: np.ndarray) -> np.ndarray:
    peak = np.max(np.abs(audio))
    if peak < 1e-8:
        return audio
    normalized = audio / peak * 0.8
    return (np.tanh(normalized * 3) * peak / 3).astype(np.float32)


def _add_crackle(audio: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    result = audio.copy()
    # ~2-3 pops per second; 0.002 was 48/s which sounds like digital clipping
    n_bursts = max(1, int(len(audio) / _SR * 3))
    if len(audio) <= 10:
        return result
    positions = rng.integers(0, len(audio) - 10, size=n_bursts)
    for pos in positions:
        burst = rng.standard_normal(10).astype(np.float32) * 0.05
        result[pos : pos + 10] += burst
    return result


def apply_voice_filter(audio: np.ndarray, sr: int, seed: int = 0) -> np.ndarray:
    audio = _bandpass_filter(audio, sr)
    audio = _soft_compress(audio)
    return audio


def apply_ambient_filter(audio: np.ndarray, sr: int, seed: int = 0) -> np.ndarray:
    audio = _bandpass_filter(audio, sr)
    return audio


def generate_audio(text: str, voice_id: str) -> np.ndarray:
    global _pipeline
    try:
        from kokoro_onnx import Kokoro
    except ImportError:
        raise RuntimeError(
            "kokoro-onnx not installed — run: pip install kokoro-onnx"
        )
    if _pipeline is None:
        if not _MODEL_PATH.exists() or not _VOICES_PATH.exists():
            raise RuntimeError(
                f"Kokoro model files not found in {_MODEL_DIR}.\n"
                "Download them:\n"
                "  wget -P ~/.cache/noir-detective/kokoro "
                "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx\n"
                "  wget -P ~/.cache/noir-detective/kokoro "
                "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
            )
        _pipeline = Kokoro(str(_MODEL_PATH), str(_VOICES_PATH))
    samples, _ = _pipeline.create(text, voice=voice_id, speed=0.92, lang="en-us")
    return np.asarray(samples, dtype=np.float32)


def speak_blocking(text: str, voice_id: str) -> None:
    import sounddevice as sd
    audio = generate_audio(text, voice_id)
    if len(audio) == 0:
        return
    audio = apply_voice_filter(audio, _SR)
    peak = np.max(np.abs(audio))
    if peak > 1e-8:
        audio = audio / peak * 0.8
    sd.play(audio, samplerate=_SR)
    sd.wait()
