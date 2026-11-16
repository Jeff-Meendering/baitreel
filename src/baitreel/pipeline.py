"""The pipeline: recording in, draft clips out.

    transcribe -> redact -> spot flags -> draft clips -> render

Each stage saves its result in the bait's working folder. Running the
pipeline again reuses whatever is already there, so a second run after
changing one option is quick. Nothing here approves or exports a clip: that
takes a person, in ``review.py``.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import draft as drafting
from . import redact, render, spot, workspace
from .fieldguide import guide
from .models import Bait, Draft, Flag, Redaction, Speaker, Transcript
from .spot import Line, local
from .transcribe import DEFAULT_MODEL, transcribe

# Called as report(stage, fraction_done, note). The command line turns these
# into progress bars; tests can ignore them.
Report = Callable[[str, float, str], None]

SPEAKER_WINDOW = 8  # lines of conversation shown to the model before a flag


def _quiet(_stage: str, _done: float, _note: str = "") -> None:
    pass


@dataclass
class Result:
    bait: Bait
    transcript: Transcript
    redactions: list[Redaction]
    flags: list[Flag]
    spotter: str
    drafts: list[Draft]


def lines_for_model(transcript: Transcript, redactions: list[Redaction]) -> list[Line]:
    """The transcript as a model may see it: personal details masked."""
    return [
        Line(s.id, s.start, s.end, redact.masked_text(s, redactions)) for s in transcript.segments
    ]


def run(
    bait: Bait,
    *,
    spotter: str = "auto",
    speech_model: str = DEFAULT_MODEL,
    allow: list[str] | None = None,
    max_clips: int = 4,
    speaker_labels: bool = True,
    fresh: bool = False,
    report: Report = _quiet,
) -> Result:
    folder = workspace.bait_dir(bait.id)
    recording = Path(bait.source_path)
    cards = guide()

    # 1. Transcribe, on this computer.
    path = folder / "transcript.json"
    if path.exists() and not fresh:
        transcript = workspace.load(path, Transcript)
    else:
        report("Transcribing", 0.0, f"speech model {speech_model}, on this computer")
        transcript = transcribe(recording, speech_model, lambda p: report("Transcribing", p, ""))
        workspace.save(path, transcript)
    report("Transcribing", 1.0, f"{len(transcript.segments)} lines")

    # 2. Redact. Cheap, so always recomputed: the allow list may have changed.
    redactions = redact.find_redactions(transcript.segments, allow)
    workspace.save(folder / "redactions.json", redactions)
    report("Redacting", 1.0, f"{len(redactions)} personal details masked")

    # 3. Spot flags. The model only ever sees the masked lines.
    lines = lines_for_model(transcript, redactions)
    if spotter == "auto":
        spotter = "local" if local.available()[0] else "keywords"
    fingerprint = hashlib.sha256(
        "\n".join([spotter, local.model_name(), *(line.text for line in lines)]).encode()
    ).hexdigest()[:16]
    path = folder / f"flags.{spotter}.{fingerprint}.json"
    if path.exists() and not fresh:
        flags = workspace.load(path, list[Flag])
        spotter_name = flags[0].spotter if flags else spotter
    else:
        report("Spotting flags", 0.0, f"spotter: {spotter}")
        flags, spotter_name = spot.run(
            lines, cards, spotter, lambda p: report("Spotting flags", p, "")
        )
        workspace.save(path, flags)
    workspace.save(folder / "flags.json", flags)
    report("Spotting flags", 1.0, f"{len(flags)} flags, spotter: {spotter_name}")

    # 4. Draft clips for the most teachable flags.
    chosen = drafting.choose(flags, max_clips)
    speakers = _speakers(folder, lines, chosen, spotter, fresh, report, speaker_labels)
    drafts = [
        drafting.build(
            bait, transcript, redactions, flag, cards[flag.tactic], n + 1, speakers,
            avoid=frozenset(
                line
                for other in flags
                if other.tactic != flag.tactic
                for line in range(other.first_segment, other.last_segment + 1)
            ),
        )
        for n, flag in enumerate(chosen)
    ]  # fmt: skip

    # Clear out drafts from an earlier run that this run did not choose again.
    # Keepers stay: a person approved those.
    wanted = {item.spec.id for item in drafts}
    for old in load_drafts(bait.id):
        if old.spec.id not in wanted and old.status != "keeper":
            shutil.rmtree(workspace.catch_dir(bait.id, old.spec.id))

    # 5. Render, skipping any clip whose draft has not changed.
    if drafts:
        with render.Renderer() as renderer:
            for n, item in enumerate(drafts):
                catch = workspace.catch_dir(bait.id, item.spec.id)
                label = f"Rendering clip {n + 1} of {len(drafts)}"
                saved = catch / "draft.json"
                if saved.exists() and (catch / "clip.mp4").exists() and not fresh:
                    before = workspace.load(saved, Draft)
                    if _same_picture(before, item):
                        drafts[n] = before  # keeps its keeper or throwback status
                        report(label, 1.0, "unchanged")
                        continue
                render.render_draft(
                    renderer, recording, item, catch, lambda p, label=label: report(label, p, "")
                )
                workspace.save(saved, item)
                report(label, 1.0, item.spec.tactic.name)
    return Result(bait, transcript, redactions, flags, spotter_name, drafts)


def _same_picture(before: Draft, after: Draft) -> bool:
    """Would these two drafts render the same clip?"""
    a = before.spec.model_copy(update={"envelope": []})
    b = after.spec.model_copy(update={"envelope": []})
    return (
        a == b
        and before.redactions == after.redactions
        and before.stage == render.stage_fingerprint()
    )


def _speakers(
    folder: Path,
    lines: list[Line],
    chosen: list[Flag],
    spotter: str,
    fresh: bool,
    report: Report,
    wanted_at_all: bool = True,
) -> dict[int, Speaker]:
    """Ask the local model who is speaking in the lines around each chosen flag."""
    if spotter != "local" or not chosen or not wanted_at_all:
        return {}
    path = folder / "speakers.json"
    known: dict[int, Speaker] = {}
    if path.exists() and not fresh:
        known = {int(k): v for k, v in workspace.load(path, dict[str, Speaker]).items()}
    by_id = {line.id: line for line in lines}
    for n, flag in enumerate(chosen):
        wanted = [
            by_id[i]
            # A wide window: the model labels a line far better when it can
            # see the back-and-forth around it.
            for i in range(flag.first_segment - SPEAKER_WINDOW, flag.last_segment + 3)
            if i in by_id
        ]
        if any(line.id not in known for line in wanted):
            report("Working out who is speaking", n / len(chosen), "")
            known.update(local.label_speakers(wanted))
    path.write_text(json.dumps({str(k): known[k] for k in sorted(known)}, indent=2) + "\n")
    report("Working out who is speaking", 1.0, "")
    return known


def load_drafts(bait_id: str) -> list[Draft]:
    folder = workspace.bait_dir(bait_id) / "catches"
    return [workspace.load(p, Draft) for p in sorted(folder.glob("*/draft.json"))]
