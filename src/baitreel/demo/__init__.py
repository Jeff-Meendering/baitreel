"""The scripted demo call: a made-up scam call, read aloud by synthetic voices.

It exists so anyone can run the whole pipeline without a real recording. Only
the script (``edna.yaml``) is in the repository. The audio is generated on
your computer and stays there.
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml
from pydantic import BaseModel

from .. import audio

SCRIPT = Path(__file__).parent / "edna.yaml"
GAP = 0.45  # seconds of quiet between turns
# Edna and Gerald are the scambaiter's invented persona, so they are safe to
# leave in. Every other name and number in the script still gets redacted.
ALLOW = ["Edna", "Gerald"]


class Turn(BaseModel):
    speaker: str
    text: str
    tactic: str | None = None
    personal: list[str] = []  # words a careful person would bleep, for the answer key


class Timing(BaseModel):
    """When one turn of the script is heard in the generated audio, in seconds."""

    start: float
    end: float


def timings_path(recording: Path) -> Path:
    """The file beside the demo audio that says when each turn is spoken."""
    return recording.with_suffix(".turns.json")


class Script(BaseModel):
    title: str
    credit: str
    voices: dict[str, str]
    turns: list[Turn]


def load_script(path: Path = SCRIPT) -> Script:
    script = Script.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    for turn in script.turns:
        turn.text = " ".join(turn.text.split())
    return script


def _speak(text: str, voice: str, out: Path) -> None:
    """Read one line aloud into a sound file, with whatever this system offers."""
    if platform.system() == "Darwin" and shutil.which("say"):
        subprocess.run(["say", "-v", voice, "-o", str(out), text], check=True)
    elif shutil.which("espeak-ng"):
        # Linux fallback. One built-in voice per speaker keeps them distinct.
        variant = "en-us+f3" if voice == "Samantha" else "en-gb+m3"
        subprocess.run(["espeak-ng", "-v", variant, "-s", "150", "-w", str(out), text], check=True)
    else:
        raise RuntimeError(
            "The demo needs a text-to-speech voice: the built-in `say` on macOS, "
            "or `espeak-ng` on Linux (for example: sudo apt install espeak-ng)."
        )


def build(out: Path, script: Script | None = None) -> Path:
    """Generate the demo call as a single audio file that sounds like a phone line."""
    script = script or load_script()
    audio.require("ffmpeg")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        parts = [audio.silence(0.4)]
        clock = len(parts[0]) / audio.SR
        timings: list[Timing] = []
        for number, turn in enumerate(script.turns):
            spoken = Path(folder) / f"{number:02d}.aiff"
            if not shutil.which("say"):
                spoken = spoken.with_suffix(".wav")
            _speak(turn.text, script.voices.get(turn.speaker, "Samantha"), spoken)
            voice = audio.decode(spoken)
            timings.append(
                Timing(start=round(clock, 3), end=round(clock + len(voice) / audio.SR, 3))
            )
            clock += (len(voice) + len(audio.silence(GAP))) / audio.SR
            parts += [voice, audio.silence(GAP)]
        import numpy as np

        clean = audio.write_wav(Path(folder) / "clean.wav", np.concatenate(parts))
        # Narrow the sound to telephone frequencies, like a real call recording.
        subprocess.run(
            [audio.require("ffmpeg"), "-y", "-v", "error", "-i", str(clean),
             "-af", "highpass=f=300,lowpass=f=3400,volume=1.6", str(out)],
            check=True,
        )  # fmt: skip
    timings_path(out).write_text(
        json.dumps([t.model_dump() for t in timings], indent=2) + "\n", encoding="utf-8"
    )
    return out


def load_timings(recording: Path) -> list[Timing] | None:
    path = timings_path(recording)
    if not path.exists():
        return None
    return [Timing.model_validate(t) for t in json.loads(path.read_text(encoding="utf-8"))]
