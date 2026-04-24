import threading
import logging
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

_AMBIENT_DIR = Path(__file__).parent.parent / "data" / "audio" / "ambient"

_LOCATION_KEYWORDS: list[tuple[list[str], str]] = [
    (["speakeasy", "bar", "club", "lounge", "jazz"], "speakeasy_jazz.wav"),
    (["precinct", "police", "station"], "police_station.wav"),
    (["courthouse", "court"], "courthouse.wav"),
    (["docks", "wharf", "harbor", "pier"], "docks.wav"),
    (["apartment", "flat", "room", "office"], "apartment_rain.wav"),
    (["street", "alley", "sidewalk", "avenue", "rue"], "street_rain.wav"),
]
_DEFAULT_CLIP = "city_night.wav"


def _match_location(location_type: str) -> str:
    lt = location_type.lower()
    for keywords, clip in _LOCATION_KEYWORDS:
        if any(kw in lt for kw in keywords):
            return clip
    return _DEFAULT_CLIP


class AmbientManager:
    def __init__(self, ambient_dir: Path = _AMBIENT_DIR) -> None:
        self._dir = ambient_dir
        self._audio: np.ndarray | None = None
        self._sr: int = 24000
        self._pos: int = 0
        self._volume: float = 0.0
        self._target_volume: float = 0.35
        self._lock = threading.Lock()
        self._stream = None

    def start(self) -> None:
        try:
            import sounddevice as sd
            self._stream = sd.OutputStream(
                samplerate=self._sr,
                channels=1,
                dtype="float32",
                callback=self._callback,
                blocksize=1024,
            )
            self._stream.start()
        except Exception as e:
            log.warning("ambient stream failed to start: %s", e)

    def stop(self) -> None:
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def set_location(self, location_type: str) -> None:
        clip_name = _match_location(location_type)
        clip_path = self._dir / clip_name
        if not clip_path.exists():
            return
        try:
            import soundfile as sf
            from noir.audio.tts import apply_ambient_filter
            audio, sr = sf.read(str(clip_path), dtype="float32")
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            audio = apply_ambient_filter(audio, sr)
            if len(audio) == 0:
                log.warning("ambient clip %r is empty, skipping", clip_name)
                return
            if sr != self._sr:
                log.warning("ambient clip %r has sr=%d, stream opened at sr=%d; pitch will be wrong", clip_name, sr, self._sr)
            with self._lock:
                self._audio = audio
                self._pos = 0
                self._target_volume = 0.35
        except Exception as e:
            log.warning("ambient set_location failed for %r: %s", clip_name, e)

    def _callback(self, outdata, frames, time_info, status) -> None:
        with self._lock:
            outdata[:] = 0
            if self._audio is None:
                return
            vol_start = self._volume
            vol_end = vol_start + (self._target_volume - vol_start) * 0.05
            self._volume = vol_end
            chunk = np.zeros(frames, dtype=np.float32)
            n = len(self._audio)
            remaining = n - self._pos
            if remaining >= frames:
                chunk[:] = self._audio[self._pos : self._pos + frames]
                self._pos += frames
            else:
                chunk[:remaining] = self._audio[self._pos :]
                leftover = frames - remaining
                loops = (leftover // n) + 1
                tiled = np.tile(self._audio, loops)
                chunk[remaining:] = tiled[:leftover]
                self._pos = leftover % n
            # Per-sample volume ramp eliminates the amplitude step at block boundaries.
            vol_ramp = np.linspace(vol_start, vol_end, frames, dtype=np.float32)
            outdata[:, 0] = chunk * vol_ramp
