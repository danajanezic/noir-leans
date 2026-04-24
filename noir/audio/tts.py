import logging
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

_SR = 24000
_pipeline = None

_MODEL_DIR = Path.home() / ".cache" / "noir-detective" / "kokoro"
_MODEL_PATH = _MODEL_DIR / "kokoro-v1.0.onnx"
_VOICES_PATH = _MODEL_DIR / "voices-v1.0.bin"

_FADE_SAMPLES = 256  # ~10ms at 24kHz — eliminates click transients at clip edges
_XFADE_SAMPLES = 2048  # ~85ms crossfade for seamless ambient looping


def _fade_edges(audio: np.ndarray) -> np.ndarray:
    if len(audio) < _FADE_SAMPLES * 2:
        return audio
    result = audio.copy()
    fade = np.linspace(0.0, 1.0, _FADE_SAMPLES, dtype=np.float32)
    result[:_FADE_SAMPLES] *= fade
    result[-_FADE_SAMPLES:] *= fade[::-1]
    return result


def make_loop_seamless(audio: np.ndarray) -> np.ndarray:
    """Crossfade tail into head so the loop point is click-free."""
    n = len(audio)
    xf = min(_XFADE_SAMPLES, n // 4)
    if xf < 2:
        return audio
    result = audio.copy()
    fade_out = np.linspace(1.0, 0.0, xf, dtype=np.float32)
    fade_in = np.linspace(0.0, 1.0, xf, dtype=np.float32)
    # blend tail samples into the head
    result[:xf] = audio[:xf] * fade_in + audio[-xf:] * fade_out
    return result[:-xf]  # trim the blended tail to avoid duplicating it


def apply_voice_filter(audio: np.ndarray, sr: int, seed: int = 0) -> np.ndarray:
    return _fade_edges(audio)


def apply_ambient_filter(audio: np.ndarray, sr: int, seed: int = 0) -> np.ndarray:
    return make_loop_seamless(audio)


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
