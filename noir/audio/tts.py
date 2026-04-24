import numpy as np
from scipy.signal import butter, sosfilt

_SR = 24000
_pipeline = None


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
    n_bursts = max(1, int(len(audio) * 0.002))
    if len(audio) <= 10:
        return result
    positions = rng.integers(0, len(audio) - 10, size=n_bursts)
    peak = np.max(np.abs(audio))
    scale = min(0.15, max(0.05, peak * 0.3)) if peak > 0 else 0.15
    for pos in positions:
        burst = rng.standard_normal(10).astype(np.float32) * scale
        result[pos : pos + 10] += burst
    return result


def apply_voice_filter(audio: np.ndarray, sr: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    audio = _bandpass_filter(audio, sr)
    audio = _soft_compress(audio)
    audio = _add_crackle(audio, rng)
    return audio


def apply_ambient_filter(audio: np.ndarray, sr: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    audio = _bandpass_filter(audio, sr)
    audio = _add_crackle(audio, rng)
    return audio


def generate_audio(text: str, voice_id: str) -> np.ndarray:
    global _pipeline
    try:
        from kokoro import KPipeline
    except ImportError:
        raise RuntimeError("kokoro not installed — run: pip install 'noir-detective[audio]'")
    if _pipeline is None:
        _pipeline = KPipeline(lang_code="a")
    chunks = []
    for _, _, audio in _pipeline(text, voice=voice_id, speed=0.92):
        if audio is not None:
            chunks.append(np.asarray(audio, dtype=np.float32))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks)


def speak_blocking(text: str, voice_id: str) -> None:
    import sounddevice as sd
    audio = generate_audio(text, voice_id)
    if len(audio) == 0:
        return
    audio = apply_voice_filter(audio, _SR)
    sd.play(audio, samplerate=_SR)
    sd.wait()
