"""Labels: a person's own reading of a call, made without looking at Baitreel's.

Labels are the answer key that ``baitreel eval`` scores the tool against.
They hold two things, both as times in the call:

- **flags**: where a Field Guide tactic appears, and which one, and
- **personal details**: stretches of audio that should be bleeped.

Labels come from three places: the labeling page (``baitreel label``), a
label track exported from Audacity, or, for the scripted demo call only, the
answer key written into the script.

Label files hold times and tactic ids, never the words that were said, so a
label file contains no personal details even though it marks where they are.

    ~/Baitreel/baits/<bait-id>/labels/<labeler>.json
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from . import demo, workspace
from .fieldguide import Tactic
from .models import Bait, Segment, Transcript

DetailKind = Literal["name", "number", "address", "online", "date", "other"]
DETAIL_KINDS: tuple[str, ...] = DetailKind.__args__
LabelSource = Literal["page", "audacity", "demo-script"]
DEMO_LABELER = "demo script"


class TacticLabel(BaseModel):
    """A stretch of the call where a person heard a tactic."""

    tactic: str
    start: float
    end: float


class DetailMark(BaseModel):
    """A stretch of the call that a person says must be bleeped."""

    start: float
    end: float
    kind: DetailKind = "other"


class Labels(BaseModel):
    """One person's labels for one call."""

    bait_id: str
    labeler: str
    source: LabelSource = "page"
    # Only finished labels are scored. Half-labeled calls would make every
    # flag after the stopping point look like a false alarm.
    finished: bool = False
    # True if Baitreel had already spotted flags for this call when labeling
    # began. If the labeler looked at them, these labels are not blind.
    tool_ran_first: bool = False
    transcript_model: str = ""
    created_at: datetime
    updated_at: datetime
    flags: list[TacticLabel] = Field(default_factory=list)
    details: list[DetailMark] = Field(default_factory=list)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "labeler"


def folder(bait_id: str) -> Path:
    return workspace.bait_dir(bait_id) / "labels"


def path_for(bait_id: str, labeler: str) -> Path:
    return folder(bait_id) / f"{slug(labeler)}.json"


def load_all(bait_id: str) -> list[Labels]:
    """Every labeler's labels for one bait, oldest first."""
    found = [workspace.load(p, Labels) for p in sorted(folder(bait_id).glob("*.json"))]
    return sorted(found, key=lambda labels: labels.created_at)


def save(labels: Labels) -> Path:
    labels.flags.sort(key=lambda f: (f.start, f.tactic))
    labels.details.sort(key=lambda d: d.start)
    return workspace.save(path_for(labels.bait_id, labels.labeler), labels)


def tool_has_run(bait_id: str) -> bool:
    """Has Baitreel spotted flags for this bait yet?"""
    here = workspace.bait_dir(bait_id)
    return (here / "flags.json").exists() or any((here / "runs").glob("*.json"))


def open_labels(
    bait_id: str, labeler: str, transcript: Transcript, source: LabelSource = "page"
) -> Labels:
    """Load this labeler's labels for a bait, or start new ones."""
    path = path_for(bait_id, labeler)
    if path.exists():
        return workspace.load(path, Labels)
    now = datetime.now(UTC)
    return Labels(
        bait_id=bait_id,
        labeler=labeler.strip(),
        source=source,
        tool_ran_first=tool_has_run(bait_id),
        transcript_model=transcript.model,
        created_at=now,
        updated_at=now,
    )


# --- Audacity label tracks --------------------------------------------------

# Label text that means "this is a personal detail". Add a kind after a colon
# or a space, for example "pii:name" or "personal number".
DETAIL_WORDS = {"pii", "personal", "personal detail", "detail", "redact", "bleep", "private"}


class LabelTrackError(ValueError):
    pass


def _plain(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def resolve_tactic(text: str, guide: dict[str, Tactic]) -> str | None:
    """Accept a tactic id, its name, or its name without "The": "the-hush", "The Hush", "hush"."""
    wanted = _plain(text)
    for tactic in guide.values():
        names = {_plain(tactic.id), _plain(tactic.name)}
        names |= {name.removeprefix("the ") for name in names}
        if wanted in names:
            return tactic.id
    return None


def _detail_kind(text: str) -> str | None:
    """The kind of a personal-detail label, "other" if none is given, or None if not a detail."""
    plain = _plain(text)
    for word in sorted(DETAIL_WORDS, key=len, reverse=True):
        if plain == word or plain.startswith(word + " "):
            rest = plain.removeprefix(word).strip()
            if not rest:
                return "other"
            if rest in {"email", "web", "website", "url", "online"}:
                return "online"
            if rest in DETAIL_KINDS:
                return rest
            raise LabelTrackError(
                f"{text!r}: unknown kind of personal detail. Use one of: {', '.join(DETAIL_KINDS)}"
            )
    return None


def _line_around(moment: float, segments: list[Segment]) -> tuple[float, float]:
    """The transcript line heard at a moment, so a point label can be scored like a span."""
    for segment in segments:
        if segment.start - 0.3 <= moment <= segment.end + 0.3:
            return segment.start, segment.end
    return max(moment - 1.0, 0.0), moment + 1.0


def read_label_track(
    text: str, guide: dict[str, Tactic], transcript: Transcript
) -> tuple[list[TacticLabel], list[DetailMark]]:
    """Read a label track exported from Audacity (File > Export > Export Labels).

    Each line is ``start<TAB>end<TAB>label``. A label is a tactic (its id or
    name) or a personal detail ("pii", optionally with a kind such as
    "pii:name"). A tactic label may be a single point in time; it then covers
    the transcript line heard at that moment. A personal detail must be a
    region, so its length can be checked against the bleeps.
    """
    flags: list[TacticLabel] = []
    details: list[DetailMark] = []
    errors: list[str] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip() or raw.startswith("\\"):  # "\" lines hold frequency ranges
            continue
        parts = raw.split("\t")
        try:
            start, end = float(parts[0]), float(parts[1])
        except (IndexError, ValueError):
            errors.append(f"line {number}: expected start, end and label separated by tabs")
            continue
        label = parts[2].strip() if len(parts) > 2 else ""
        start, end = min(start, end), max(start, end)
        try:
            kind = _detail_kind(label)
        except LabelTrackError as error:
            errors.append(f"line {number}: {error}")
            continue
        if kind is not None:
            if end - start < 0.05:
                errors.append(
                    f"line {number}: a personal detail needs a region, not a point. "
                    "Select the words in Audacity before adding the label."
                )
                continue
            details.append(DetailMark(start=start, end=end, kind=kind))
            continue
        tactic = resolve_tactic(label, guide)
        if tactic is None:
            errors.append(
                f"line {number}: {label!r} is not a Field Guide tactic or a personal detail"
            )
            continue
        if end - start < 0.05:
            start, end = _line_around(start, transcript.segments)
        flags.append(TacticLabel(tactic=tactic, start=start, end=end))
    if errors:
        raise LabelTrackError("The label track has problems:\n  " + "\n  ".join(errors))
    return flags, details


# --- The demo answer key ----------------------------------------------------

NUMBER_WORDS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}  # fmt: skip


def _squash(text: str) -> str:
    """Letters and digits only, with number words as digits: "Five-5, 0" -> "550"."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return "".join(NUMBER_WORDS.get(word, word) for word in words)


def _find_words(phrase: str, segments: list[Segment], start: float, end: float):
    """The shortest run of transcript words within a time window that spells ``phrase``."""
    wanted = _squash(phrase)
    words = [
        w for s in segments for w in s.words if start - 0.5 <= (w.start + w.end) / 2 <= end + 0.5
    ]
    for i in range(len(words)):
        built = ""
        for j in range(i, len(words)):
            built += _squash(words[j].text)
            if built == wanted:
                return words[i].start, words[j].end
            if not wanted.startswith(built):
                break
    return None


def demo_answer_key(bait: Bait, transcript: Transcript) -> tuple[Labels | None, list[str]]:
    """Labels for the scripted demo call, taken from the script itself.

    Returns the labels and a list of problems: personal details from the
    script that could not be found in the transcript, so were left out.
    """
    timings = demo.load_timings(Path(bait.source_path))
    script = demo.load_script()
    if bait.kind != "scripted-demo" or timings is None or len(timings) != len(script.turns):
        return None, []
    labels = open_labels(bait.id, DEMO_LABELER, transcript, source="demo-script")
    labels.flags, labels.details, problems = [], [], []
    labels.finished = True
    labels.tool_ran_first = False  # the script was written before any tool ran
    for turn, timing in zip(script.turns, timings, strict=True):
        if turn.tactic:
            labels.flags.append(TacticLabel(tactic=turn.tactic, start=timing.start, end=timing.end))
        for phrase in turn.personal:
            found = _find_words(phrase, transcript.segments, timing.start, timing.end)
            if found:
                kind = "number" if any(c.isdigit() for c in phrase) else "name"
                labels.details.append(DetailMark(start=found[0], end=found[1], kind=kind))
            else:
                problems.append(f"could not find {phrase!r} in the transcript")
    labels.updated_at = datetime.now(UTC)
    return labels, problems
