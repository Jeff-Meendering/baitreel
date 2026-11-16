"""The data that flows between pipeline stages.

Every stage reads and writes these models as plain JSON in the bait's working
folder, so any stage can be inspected, re-run or replaced.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Speaker = Literal["scammer", "target", "unknown"]
SourceKind = Literal["real", "scripted-demo"]


# --- Intake -----------------------------------------------------------------


class Rights(BaseModel):
    """A person's statement that they may use this recording."""

    attested_by: str
    statement: str
    attested_at: datetime


class Bait(BaseModel):
    """One recorded call, as registered at intake."""

    id: str
    title: str
    kind: SourceKind
    credit: str
    source_path: str  # where the recording lives on this computer; never exported
    source_name: str
    source_sha256: str
    duration: float
    rights: Rights
    created_at: datetime


# --- Transcript -------------------------------------------------------------


class Word(BaseModel):
    text: str
    start: float
    end: float


class Segment(BaseModel):
    """A stretch of speech, roughly a sentence or two."""

    id: int
    start: float
    end: float
    words: list[Word]
    speaker: Speaker = "unknown"

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


class Transcript(BaseModel):
    model: str
    language: str
    duration: float
    segments: list[Segment]


# --- Redaction --------------------------------------------------------------

RedactionKind = Literal["name", "number", "spelled", "email", "web", "address", "date"]


class Redaction(BaseModel):
    """A run of words in one segment that must not be heard or read."""

    segment: int
    first_word: int
    last_word: int
    kind: RedactionKind
    start: float
    end: float
    # The original words. Kept only in the local working folder so a human can
    # check the redaction. Never copied into a clip, a prompt or a publish kit.
    original: str


# --- Flags ------------------------------------------------------------------


class Flag(BaseModel):
    """A moment where a Field Guide tactic appears."""

    id: str
    tactic: str
    first_segment: int
    last_segment: int
    start: float
    end: float
    quote: str  # redacted text
    cues: list[str] = Field(default_factory=list)  # phrases to highlight
    why: str = ""
    teachability: int = 3  # 1 (weak) to 5 (clear and self-contained)
    spotter: str = ""


class Run(BaseModel):
    """One spotter's answer for one call, saved so it can be reused and compared.

    Saved as ``runs/<id>.json`` in the bait's folder. A run is reused only
    when the spotter, its version and the transcript lines it read are all
    unchanged, so ``baitreel eval`` can line up runs of different models and
    prompt versions on the same call.
    """

    id: str
    spotter: Literal["local", "keywords"]
    model: str = ""  # the local model, such as gemma4:12b; empty for keywords
    version: str  # fingerprint of the prompt (local) or cue patterns (keywords)
    lines: str  # fingerprint of the masked transcript lines the spotter read
    seconds: float  # how long spotting took
    created_at: datetime
    flags: list[Flag]

    @property
    def name(self) -> str:
        """How the run is described to people, such as "local/gemma4:12b"."""
        return f"local/{self.model}" if self.spotter == "local" else self.spotter


# --- Clips ------------------------------------------------------------------


class ClipWord(BaseModel):
    text: str  # already masked if redacted
    start: float  # seconds from the start of the clip
    end: float
    redacted: bool = False
    cue: bool = False


class CaptionCard(BaseModel):
    """A few words shown on screen together."""

    speaker: Speaker = "unknown"
    in_quote: bool = False
    words: list[ClipWord]


class Beat(BaseModel):
    """One phase of the Flag on the Play format."""

    name: Literal["play", "flag", "replay", "counter", "credit"]
    start: float
    end: float


class TacticCard(BaseModel):
    id: str
    name: str
    plain_label: str
    counter_move: str
    source_title: str


class ClipSpec(BaseModel):
    """Everything the stage page needs to draw a clip. Contains no raw personal details."""

    id: str
    bait_id: str
    kind: SourceKind
    credit: str
    call_time: float  # where in the call the clip starts, in seconds
    call_duration: float
    fps: int = 30
    width: int = 1080
    height: int = 1920
    duration: float
    beats: list[Beat]
    cards: list[CaptionCard]  # captions for the play beat
    replay_cards: list[CaptionCard]  # the quote again, re-timed for the replay beat
    tactic: TacticCard
    envelope: list[float] = Field(default_factory=list)  # loudness per frame, 0..1


class Draft(BaseModel):
    """A catch: a clip spec plus the audit trail behind it."""

    spec: ClipSpec
    flag: Flag
    play_start: float  # in call time
    play_end: float
    quote_start: float
    quote_end: float
    redactions: list[Redaction] = Field(default_factory=list)
    card_status: str = "draft"
    status: Literal["draft", "keeper", "throwback"] = "draft"
    stage: str = ""  # fingerprint of the stage page that rendered clip.mp4


class Passport(BaseModel):
    """The approval record that travels with a published clip."""

    baitreel_version: str
    clip_id: str
    clip_sha256: str
    bait_id: str
    source_kind: SourceKind
    source_sha256: str
    credit: str
    rights: Rights
    tactic: str
    field_guide_source: str
    field_guide_card_status: str
    spotter: str
    redactions: dict[str, int]
    approved_by: str
    approved_at: datetime
    statement: str = "A person played this clip in full and approved it for publication."
