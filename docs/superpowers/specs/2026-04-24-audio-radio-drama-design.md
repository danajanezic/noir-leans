# Audio Radio Drama Implementation Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform noir-leans into an audio-first experience that sounds like a 1930s radio drama, using Kokoro TTS for voices, a radio filter chain on all audio, and location-appropriate ambient loops.

**Architecture:** A new `noir/audio/` package exposes a thin public API (`speak`, `set_location`, `flush`). `display.py` calls this API after each text output. All audio runs in a background thread — the game never waits on audio. If Kokoro is not installed or `--no-audio` is passed, every audio call is a silent no-op and the game runs exactly as today.

**Tech Stack:** `kokoro` (TTS), `sounddevice` (playback), `soundfile` (ambient clip loading), `numpy` + `scipy` (radio filter DSP)

---

## Architecture

### Package layout

```
noir/audio/
    __init__.py          # public API: speak(), set_location(), flush(), init(), shutdown()
    tts.py               # Kokoro wrapper + radio filter
    ambient.py           # looping ambient manager with crossfade
    queue_worker.py      # background speech queue thread
noir/data/audio/ambient/ # CC0 ambient clip storage (.wav files)
scripts/download_ambient.py  # fetches curated CC0 clips at setup time
```

### Public API (`noir/audio/__init__.py`)

```python
def init(no_audio: bool = False) -> None: ...
def shutdown() -> None: ...
def speak(text: str, voice_id: str) -> None: ...       # enqueues; non-blocking
def set_location(location_type: str) -> None: ...      # triggers ambient crossfade
def flush() -> None: ...                               # clears pending speech queue
```

If `no_audio=True` or `NOIR_NO_AUDIO=1` env var is set, all functions are no-ops.

---

## TTS + Radio Filter (`tts.py`)

Kokoro generates audio as a numpy float32 array at 24 kHz. Every audio item (voice or ambient) passes through a filter chain before playback. The chain differs by type:

### Voice filter chain

1. **Bandpass filter** — `scipy.signal.butter(order=4, [300, 3400], btype='bandpass', fs=24000)` applied via `sosfilt`. Cuts low rumble and high hiss, leaving the telephone/radio frequency range.
2. **Soft compression** — normalize to 80% peak amplitude, then `np.tanh(audio * 3) / 3` for gentle tube-amp saturation. Makes voices sit forward and punch through ambient.
3. **Crackle overlay** — ~2% of samples receive a short noise burst (10-sample gaussian impulse at 15% amplitude). Burst positions are randomly sampled per item, giving each line unique crackle texture.

### Ambient filter chain

Same bandpass filter and crackle overlay as voices. **No compression stage** — ambient stays uncompressed so it sits in the background and never competes with dialogue.

### Kokoro usage

```python
from kokoro import KPipeline

_pipeline = KPipeline(lang_code='a')  # initialized once, reused

def generate_audio(text: str, voice_id: str) -> np.ndarray:
    chunks = []
    for _, _, audio in _pipeline(text, voice=voice_id, speed=0.92):
        chunks.append(audio)
    return np.concatenate(chunks)
```

---

## Voice Mapping

Voice is resolved at enqueue time from speaker name. `display.py` passes the speaker name; the audio layer looks it up.

| Role | Voice ID | Notes |
|---|---|---|
| Narrator | `bm_george` | Deep measured British male — omniscient announcer |
| Partner (female) | `af_bella` | Warm American female |
| Partner (male) | `am_michael` | Steady American male |
| Male NPC (default) | `am_adam` | Rotated by `npc_id % 2` for variety |
| Female NPC (default) | `af_heart` | Alternates with `af_bella` by `npc_id % 2` |
| Authority / police | `bm_george` | Clipped, formal |
| Player | *(silent)* | Player types — their words are not read back |

Unknown speakers fall back to `am_adam` (male) or `af_heart` (female). Voice lookup is a pure dict — easy to extend.

---

## Ambient Sound Manager (`ambient.py`)

Short looping clips (~10–30 seconds, WAV format) stored in `noir/data/audio/ambient/`. The manager runs its own daemon thread.

### Location type → clip mapping

| Location type keywords | Clip file |
|---|---|
| `street`, `alley`, `sidewalk` | `street_rain.wav` |
| `speakeasy`, `bar`, `club`, `lounge` | `speakeasy_jazz.wav` |
| `police`, `station`, `precinct` | `police_station.wav` |
| `courthouse`, `court` | `courthouse.wav` |
| `docks`, `wharf`, `harbor`, `pier` | `docks.wav` |
| `apartment`, `office`, `room`, `flat` | `apartment_rain.wav` |
| *(default)* | `city_night.wav` |

### Behavior

- `set_location(location_type)` — matches type string against keyword table, selects clip, triggers crossfade
- Crossfade: current clip fades out over 1 second (linear volume ramp), new clip fades in
- If the clip file is missing, ambient is silently skipped for that location
- Volume: ambient plays at 35% of voice volume by default

---

## Speech Queue Worker (`queue_worker.py`)

A single `threading.Thread` (daemon) drains a `queue.Queue[SpeechItem]`.

```python
@dataclass
class SpeechItem:
    text: str
    voice_id: str
    is_flush_sentinel: bool = False
```

Worker loop:
1. Dequeue item
2. If flush sentinel: drain remaining queue, continue
3. Generate audio via `tts.generate_audio(text, voice_id)`
4. Apply voice filter chain
5. `sounddevice.play(audio, samplerate=24000); sounddevice.wait()`
6. Next item

`flush()` enqueues a flush sentinel, which causes the worker to discard everything behind it. Called before case start, trial start, and scene transitions.

---

## Display Integration (`display.py`)

Each output function gets one audio call. Text output is minimized in audio-first mode:

| Function | Audio call | Text shown |
|---|---|---|
| `show_narrator(text)` | `speak(text, NARRATOR_VOICE)` | nothing |
| `show_dialogue(speaker, text)` | `speak(text, voice_for(speaker))` | `[Speaker]` only |
| `show_partner_aside(speaker, text)` | `speak(text, voice_for(speaker))` | `(aside)` |
| `show_location(name, ...)` | `speak(name, NARRATOR_VOICE)` + `set_location(type)` | location name + time |
| `show_travel_animation()` | `flush()` + ambient crossfade via `set_location` | animation unchanged |
| `show_location_rule()` | *(silent)* | unchanged |

`voice_for(speaker)` is a module-level lookup that maps speaker names to voice IDs. It's populated at game init from NPC data (gender field) and falls back to role-based defaults.

---

## `scripts/download_ambient.py`

Fetches a curated set of CC0-licensed clips from freesound.org and writes them to `noir/data/audio/ambient/`. Run once at setup. Clips are not committed to the repo (`.gitignore`).

---

## Testing

- All tests set `NOIR_NO_AUDIO=1` — audio calls become no-ops, no hardware required
- `MockAudioQueue` captures `(text, voice_id)` tuples for assertion in unit tests
- `tts.py` filter functions (`apply_voice_filter`, `apply_ambient_filter`) are pure numpy — tested directly with synthetic arrays
- Integration smoke tests (`scripts/test_audio.py`) are developer-run only, not CI

---

## Dependencies

Add to `pyproject.toml`:

```toml
kokoro>=0.9
sounddevice>=0.5
soundfile>=0.13
scipy>=1.13
```

`numpy` is already a transitive dependency of kokoro.

---

## CLI flag

`main.py` passes `--no-audio` to `audio.init(no_audio=True)`. All audio becomes a no-op. Default is audio enabled if kokoro is installed, disabled if not (detected via `importlib.util.find_spec('kokoro')`).
