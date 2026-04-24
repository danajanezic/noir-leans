#!/usr/bin/env python3
"""Generate synthetic CC0 ambient audio clips for noir-leans.

Run once: python scripts/gen_ambient.py
Clips are written to noir/data/audio/ambient/ and gitignored.
Replace with higher-quality recordings from freesound.org (CC0) if desired.
"""
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt, lfilter

OUT = Path(__file__).parent.parent / "noir" / "data" / "audio" / "ambient"
OUT.mkdir(parents=True, exist_ok=True)

SR = 24000
DURATION = 20


def pink_noise(n: int) -> np.ndarray:
    white = np.random.randn(n).astype(np.float32)
    b = [0.049922035, -0.095993537, 0.050612699, -0.004408786]
    a = [1, -2.494956002, 2.017265875, -0.522189400]
    return lfilter(b, a, white).astype(np.float32)


def normalize(audio: np.ndarray, peak: float = 0.4) -> np.ndarray:
    return (audio / (np.max(np.abs(audio)) + 1e-8) * peak).astype(np.float32)


def bandpass(audio: np.ndarray, low: float, high: float) -> np.ndarray:
    sos = butter(2, [low, high], btype="bandpass", fs=SR, output="sos")
    return sosfilt(sos, audio).astype(np.float32)


def gen_rain() -> np.ndarray:
    n = SR * DURATION
    rain = pink_noise(n)
    rain = bandpass(rain, 400, 8000)  # high-passed so the base sounds like steady rain hiss
    rng = np.random.default_rng(42)
    drop_len = SR // 20  # ~50ms per drop
    env = np.exp(-np.linspace(0, 8, drop_len)).astype(np.float32)  # sharp attack, fast decay
    for _ in range(80):
        pos = rng.integers(0, n - drop_len)
        drop = rng.standard_normal(drop_len).astype(np.float32) * env * 0.4
        rain[pos : pos + drop_len] += drop
    return normalize(rain, 0.35)


def gen_jazz() -> np.ndarray:
    n = SR * DURATION
    t = np.linspace(0, DURATION, n, dtype=np.float32)
    freqs = [261.6, 329.6, 392.0, 493.9, 523.2]  # Cmaj7 + octave C
    audio = np.zeros(n, dtype=np.float32)
    for i, f in enumerate(freqs):
        wave = np.sin(2 * np.pi * f * t)
        wave *= 0.6 + 0.4 * np.sin(2 * np.pi * (4.5 + i * 0.3) * t)
        audio += wave * 0.12
    audio += np.random.randn(n).astype(np.float32) * 0.008
    return normalize(bandpass(audio, 150, 4000), 0.3)


def gen_typewriters() -> np.ndarray:
    n = SR * DURATION
    base = np.zeros(n, dtype=np.float32)
    rng = np.random.default_rng(7)
    for _ in range(100):
        pos = rng.integers(0, n - 60)
        base[pos : pos + 60] += (rng.standard_normal(60) * 0.6).astype(np.float32)
    clatter = bandpass(base, 600, 5000)
    murmur = pink_noise(n) * 0.04
    return normalize(clatter + murmur, 0.35)


def gen_courthouse() -> np.ndarray:
    n = SR * DURATION
    base = pink_noise(n) * 0.1
    rng = np.random.default_rng(99)
    for _ in range(6):
        pos = rng.integers(0, n - SR // 3)
        length = SR // 3
        echo = np.exp(-np.linspace(0, 4, length)) * rng.standard_normal(length).astype(np.float32)
        base[pos : pos + length] += echo * 0.3
    return normalize(bandpass(base, 100, 3000), 0.25)


def gen_water() -> np.ndarray:
    n = SR * DURATION
    pink = pink_noise(n)
    rumble = bandpass(pink, 50, 500)
    rng = np.random.default_rng(13)
    for _ in range(10):
        pos = rng.integers(0, n - SR // 2)
        length = SR // 2
        slap = np.exp(-np.linspace(0, 5, length)) * rng.standard_normal(length).astype(np.float32)
        rumble[pos : pos + length] += slap * 0.25
    return normalize(rumble, 0.35)


clips = {
    "street_rain.wav": gen_rain,
    "apartment_rain.wav": gen_rain,
    "city_night.wav": gen_rain,
    "speakeasy_jazz.wav": gen_jazz,
    "police_station.wav": gen_typewriters,
    "courthouse.wav": gen_courthouse,
    "docks.wav": gen_water,
}

print("Generating synthetic ambient clips...")
for filename, fn in clips.items():
    path = OUT / filename
    audio = fn()
    sf.write(str(path), audio, SR)
    print(f"  {filename}  ({len(audio) // SR}s)")
print(f"\nWritten to {OUT}")
print("Replace with CC0 recordings from freesound.org for higher quality.")
