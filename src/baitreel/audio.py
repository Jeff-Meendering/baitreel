"""Audio helpers: decoding with ffmpeg, bleeps, the referee whistle and loudness.

Audio is handled as mono float32 NumPy arrays at 48 kHz. Only short windows
are ever decoded (one clip at a time), so memory use stays small even for
hour-long recordings.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np

SR = 48_000


class MissingTool(RuntimeError):
    pass


def require(tool: str) -> str:
    found = shutil.which(tool)
    if not found:
        raise MissingTool(
            f"{tool} is not installed. On macOS: brew install ffmpeg. "
            "On Linux: use your package manager. Then run: baitreel doctor"
        )
    return found


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        [require("ffprobe"), "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return float(json.loads(out.stdout)["format"]["duration"])


def decode(
    path: Path, start: float = 0.0, duration: float | None = None, rate: int = SR
) -> np.ndarray:
    """Decode part of any audio or video file to mono float32 (48 kHz unless told otherwise)."""
    command = [require("ffmpeg"), "-v", "error", "-ss", f"{max(start, 0):.3f}"]
    if duration is not None:
        command += ["-t", f"{duration:.3f}"]
    command += ["-i", str(path), "-vn", "-ac", "1", "-ar", str(rate), "-f", "f32le", "-"]
    raw = subprocess.run(command, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def write_wav(path: Path, samples: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SR)
        out.writeframes(pcm.tobytes())
    return path


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(round(seconds * SR)), dtype=np.float32)


def _fade(samples: np.ndarray, seconds: float = 0.012) -> np.ndarray:
    """Short fade in and out so edits do not click."""
    n = min(int(seconds * SR), len(samples) // 2)
    if n > 0:
        ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
        samples[:n] *= ramp
        samples[-n:] *= ramp[::-1]
    return samples


def tone(freq: float, seconds: float, volume: float = 0.18) -> np.ndarray:
    t = np.arange(int(round(seconds * SR)), dtype=np.float32) / SR
    return _fade((volume * np.sin(2 * np.pi * freq * t)).astype(np.float32))


def bleep(samples: np.ndarray, spans: list[tuple[float, float]]) -> np.ndarray:
    """Replace each (start, end) span, in seconds, with a 1 kHz tone.

    The original audio in the span is discarded, not just covered, so the
    words cannot be recovered from the exported file.
    """
    out = samples.copy()
    for start, end in spans:
        a = max(int(start * SR), 0)
        b = min(int(end * SR), len(out))
        if b > a:
            out[a:b] = tone(1000.0, (b - a) / SR)[: b - a]
    return out


def whistle() -> np.ndarray:
    """A short referee whistle, synthesized so no sound file needs a license."""
    seconds = 0.55
    t = np.arange(int(seconds * SR), dtype=np.float32) / SR
    trill = 0.6 + 0.4 * np.sin(2 * np.pi * 38 * t)  # the rattle of the pea
    body = np.sin(2 * np.pi * 2850 * t) + 0.45 * np.sin(2 * np.pi * 3020 * t)
    return _fade((0.16 * trill * body).astype(np.float32), 0.03)


def normalize(samples: np.ndarray, target: float = 0.45) -> np.ndarray:
    """Bring quiet phone audio up to a comfortable, consistent level."""
    if len(samples) == 0:
        return samples
    loud = float(np.percentile(np.abs(samples), 98))
    if loud < 1e-4:
        return samples
    return np.clip(samples * min(target / loud, 12.0), -0.98, 0.98).astype(np.float32)


def envelope(samples: np.ndarray, fps: int) -> list[float]:
    """Loudness per video frame, scaled 0..1, for the on-screen waveform."""
    hop = SR // fps
    frames = len(samples) // hop
    if frames == 0:
        return []
    rms = np.sqrt(np.mean(samples[: frames * hop].reshape(frames, hop) ** 2, axis=1))
    peak = float(rms.max())
    if peak < 1e-6:
        return [0.0] * frames
    return [round(float(v), 3) for v in np.sqrt(rms / peak)]


def silences(samples: np.ndarray, rate: int, shortest: float = 0.28) -> list[tuple[float, float]]:
    """Stretches of quiet at least ``shortest`` seconds long, as (start, end) in seconds.

    "Quiet" is relative to how loud this recording is, so it works for both
    clean and noisy phone lines.
    """
    hop = rate // 50  # 20 ms
    frames = len(samples) // hop
    if frames == 0:
        return []
    rms = np.sqrt(np.mean(samples[: frames * hop].reshape(frames, hop) ** 2, axis=1))
    quiet = rms < max(float(np.percentile(rms, 95)) * 0.06, 1e-4)
    found: list[tuple[float, float]] = []
    start = None
    for i, is_quiet in enumerate([*quiet, False]):
        if is_quiet and start is None:
            start = i
        elif not is_quiet and start is not None:
            if (i - start) * hop / rate >= shortest:
                found.append((start * hop / rate, i * hop / rate))
            start = None
    return found
