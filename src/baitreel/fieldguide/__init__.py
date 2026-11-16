"""The Field Guide: the catalogue of scam tactics Baitreel can label.

Each tactic is one YAML file in ``tactics/``. The pipeline may only label a
moment with a tactic from this catalogue, and the advice shown to viewers is
copied from the card word for word. Nothing here is written by a model.

To add or improve a tactic, edit a YAML file and run ``baitreel guide --check``.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, field_validator

TACTICS_DIR = Path(__file__).parent / "tactics"

# Words that blame the person instead of the tactic. A card that uses one
# fails validation. See "Tone" in VISION.md.
UNKIND = [
    "fell for", "fall for", "gullible", "stupid", "foolish", "naive", "dumb",
    "sucker", "should have known", "careless", "greedy", "easy target",
]  # fmt: skip

MAX_COUNTER_MOVE_WORDS = 32  # must be readable on screen in a few seconds


class Source(BaseModel):
    title: str
    url: str


class Tactic(BaseModel):
    id: str
    name: str
    plain_label: str
    description: str
    sounds_like: list[str]
    cues: list[str]
    why_it_works: str
    counter_move: str
    source: Source
    status: Literal["draft", "reviewed"] = "draft"

    @field_validator("description", "why_it_works", "counter_move", "plain_label", "name")
    @classmethod
    def _tidy(cls, value: str) -> str:
        return " ".join(value.split())

    def patterns(self) -> list[re.Pattern[str]]:
        return [re.compile(rf"\b(?:{cue})\b", re.IGNORECASE) for cue in self.cues]


def problems(tactic: Tactic, filename: str | None = None) -> list[str]:
    """Return everything wrong with a card. An empty list means it is valid."""
    found: list[str] = []
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", tactic.id):
        found.append("id must be lowercase words joined by hyphens")
    if filename and filename != f"{tactic.id}.yaml":
        found.append(f"file should be named {tactic.id}.yaml")
    if len(tactic.name) > 24:
        found.append("name is longer than 24 characters and will not fit the stamp")
    if len(tactic.plain_label) > 64:
        found.append("plain_label is longer than 64 characters")
    words = len(tactic.counter_move.split())
    if words > MAX_COUNTER_MOVE_WORDS:
        found.append(f"counter_move has {words} words; the limit is {MAX_COUNTER_MOVE_WORDS}")
    if not tactic.source.url.startswith("https://"):
        found.append("source.url must be an https link to the advice this card relies on")
    if not tactic.sounds_like:
        found.append("sounds_like needs at least one example")
    for cue in tactic.cues:
        try:
            re.compile(cue)
        except re.error as error:
            found.append(f"cue {cue!r} is not a valid pattern: {error}")
    everything = " ".join(
        [tactic.name, tactic.plain_label, tactic.description, tactic.why_it_works,
         tactic.counter_move]
    ).lower()  # fmt: skip
    for phrase in UNKIND:
        if phrase in everything:
            found.append(f"uses the phrase {phrase!r}, which blames the person, not the tactic")
    return found


def load_guide(folder: Path | None = None) -> dict[str, Tactic]:
    """Load every card. Raises ValueError if any card is invalid."""
    folder = folder or TACTICS_DIR
    guide: dict[str, Tactic] = {}
    errors: list[str] = []
    for path in sorted(folder.glob("*.yaml")):
        tactic = Tactic.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        errors += [f"{path.name}: {problem}" for problem in problems(tactic, path.name)]
        guide[tactic.id] = tactic
    if errors:
        raise ValueError("Field Guide has problems:\n  " + "\n  ".join(errors))
    return guide


@cache
def guide() -> dict[str, Tactic]:
    return load_guide()
