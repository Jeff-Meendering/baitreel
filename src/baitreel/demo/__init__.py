"""The scripted demo call: a made-up scam call, read aloud by synthetic voices.

It exists so anyone can run the whole pipeline without a real recording. Only
the script (``edna.yaml``) is in the repository. The audio is generated on
your computer and stays there.
"""

from __future__ import annotations

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


class Turn(BaseModel):
    speaker: str
    text: str
    tactic: str | None = None


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
        for number, turn in enumerate(script.turns):
            spoken = Path(folder) / f"{number:02d}.aiff"
            if not shutil.which("say"):
                spoken = spoken.with_suffix(".wav")
            _speak(turn.text, script.voices.get(turn.speaker, "Samantha"), spoken)
            parts += [audio.decode(spoken), audio.silence(GAP)]
        import numpy as np

        clean = audio.write_wav(Path(folder) / "clean.wav", np.concatenate(parts))
        # Narrow the sound to telephone frequencies, like a real call recording.
        subprocess.run(
            [audio.require("ffmpeg"), "-y", "-v", "error", "-i", str(clean),
             "-af", "highpass=f=300,lowpass=f=3400,volume=1.6", str(out)],
            check=True,
        )  # fmt: skip
    return out
