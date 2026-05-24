"""Generate interval clips as in-memory WAV (pure tone or simple piano-like)."""

from __future__ import annotations

import io
import math
import random
import wave
from typing import Literal

import numpy as np

IntervalKind = Literal["p4", "p5"]
PlayStyle = Literal["melodic", "harmonic"]
ToneStyle = Literal["pure", "piano"]

SAMPLE_RATE = 44_100
RATIO = {"p4": 4 / 3, "p5": 3 / 2}
LABEL = {"p4": "纯四度", "p5": "纯五度"}

# Child-friendly root range (~C4–G4)
ROOT_HZ_RANGE = (261.63, 392.00)


def _envelope(n: int, attack: float = 0.02, release: float = 0.15) -> np.ndarray:
    t = np.linspace(0, 1, n, dtype=np.float32)
    att = int(n * attack)
    rel = int(n * release)
    env = np.ones(n, dtype=np.float32)
    if att > 0:
        env[:att] = np.linspace(0, 1, att, dtype=np.float32)
    if rel > 0:
        env[-rel:] = np.linspace(1, 0, rel, dtype=np.float32)
    return env


def _tone(
    freq: float,
    duration: float,
    *,
    style: ToneStyle = "pure",
    amplitude: float = 0.35,
) -> np.ndarray:
    n = int(SAMPLE_RATE * duration)
    t = np.linspace(0, duration, n, endpoint=False, dtype=np.float32)
    phase = 2 * math.pi * freq * t
    if style == "pure":
        wave_arr = np.sin(phase)
    else:
        # Lightweight "piano": fundamental + gentle harmonics
        wave_arr = (
            0.62 * np.sin(phase)
            + 0.22 * np.sin(2 * phase)
            + 0.10 * np.sin(3 * phase)
            + 0.06 * np.sin(4 * phase)
        )
    return (amplitude * wave_arr * _envelope(n)).astype(np.float32)


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(SAMPLE_RATE * seconds), dtype=np.float32)


def build_interval_audio(
    interval: IntervalKind,
    *,
    root_hz: float | None = None,
    play_style: PlayStyle = "melodic",
    tone_style: ToneStyle = "pure",
    note_duration: float = 0.85,
    gap: float = 0.12,
) -> tuple[bytes, float, IntervalKind]:
    """Return WAV bytes, root frequency, and interval kind."""
    if root_hz is None:
        root_hz = random.uniform(*ROOT_HZ_RANGE)
    upper_hz = root_hz * RATIO[interval]

    if play_style == "melodic":
        parts = [
            _tone(root_hz, note_duration, style=tone_style),
            _silence(gap),
            _tone(upper_hz, note_duration, style=tone_style),
        ]
    else:
        n = int(SAMPLE_RATE * note_duration * 1.35)
        t = np.linspace(0, note_duration * 1.35, n, endpoint=False, dtype=np.float32)
        p1 = 2 * math.pi * root_hz * t
        p2 = 2 * math.pi * upper_hz * t
        if tone_style == "pure":
            mixed = 0.30 * np.sin(p1) + 0.30 * np.sin(p2)
        else:
            mixed = 0.20 * (np.sin(p1) + np.sin(2 * p1) + np.sin(p2) + np.sin(2 * p2))
        parts = [(0.40 * mixed * _envelope(n)).astype(np.float32)]

    audio = np.concatenate(parts)
    peak = np.max(np.abs(audio)) or 1.0
    audio = (0.92 * audio / peak).astype(np.float32)
    return _to_wav_bytes(audio), root_hz, interval


def _to_wav_bytes(samples: np.ndarray) -> bytes:
    pcm = np.clip(samples, -1.0, 1.0)
    pcm16 = (pcm * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()


def random_challenge(
    *,
    play_style: PlayStyle = "melodic",
    tone_style: ToneStyle = "pure",
) -> tuple[bytes, IntervalKind, float]:
    interval = random.choice(["p4", "p5"])
    wav, root, kind = build_interval_audio(
        interval, play_style=play_style, tone_style=tone_style
    )
    return wav, kind, root
