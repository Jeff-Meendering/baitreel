"""Where Baitreel keeps its working files.

Everything lives under one home folder (``~/Baitreel`` unless ``BAITREEL_HOME``
is set), well away from any Git repository, so recordings and transcripts
cannot be committed by accident.

    ~/Baitreel/
      baits/<bait-id>/        working files for one recording
        bait.json             intake record, rights statement and credit
        transcript.json       local transcript with word timings
        redactions.json       personal details found, for human checking
        allow.json            words the person chose to leave unredacted
        flags.json            tactics spotted
        runs/<run-id>.json    every spotter run, kept for comparison
        labels/<labeler>.json hand-made labels, for scoring (times only, no words)
        catches/<clip-id>/    draft.json, audio.wav and clip.mp4 for each draft
      exports/<bait-id>/...   publish kits for approved clips
      eval/                   the latest evaluation report
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, TypeAdapter

T = TypeVar("T")


def home() -> Path:
    return Path(os.environ.get("BAITREEL_HOME", Path.home() / "Baitreel")).expanduser()


def bait_dir(bait_id: str) -> Path:
    return home() / "baits" / bait_id


def catch_dir(bait_id: str, clip_id: str) -> Path:
    return bait_dir(bait_id) / "catches" / clip_id


def export_dir(bait_id: str, clip_id: str) -> Path:
    return home() / "exports" / bait_id / clip_id


def save(path: Path, data: BaseModel | list) -> Path:
    """Write a model, or a list of models, as readable JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, BaseModel):
        text = data.model_dump_json(indent=2)
    else:
        text = TypeAdapter(list[type(data[0])] if data else list).dump_json(data, indent=2).decode()
    path.write_text(text + "\n", encoding="utf-8")
    return path


def load(path: Path, kind: type[T]) -> T:
    return TypeAdapter(kind).validate_json(path.read_text(encoding="utf-8"))
