"""Flag spotting: find the moments in a call where a Field Guide tactic appears.

A spotter takes the redacted transcript, line by line, and returns flags.
Two spotters ship today:

- ``local``: a language model running on this computer through Ollama.
- ``keywords``: the Field Guide's cue patterns, with no model at all. It is
  the fallback when no model is available, and the baseline that Milestone 2
  measures the model against.

To add another spotter, write a module with a ``spot(lines, guide)`` function
and a ``version`` fingerprint, and add it to ``run`` below. Whatever a model
returns goes through ``validate`` before it becomes a flag.

Every result is saved as a ``Run`` in the bait's ``runs/`` folder, labeled
with the spotter, its version and the lines it read. Runs are reused when
nothing has changed, and ``baitreel eval`` scores them side by side.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .. import workspace
from ..fieldguide import Tactic
from ..models import Flag, Run


@dataclass(frozen=True)
class Line:
    """One transcript segment, with personal details already masked."""

    id: int
    start: float
    end: float
    text: str


def _plain(text: str) -> str:
    return re.sub(r"[^a-z0-9\[\] ]+", "", text.lower().replace("-", " ")).strip()


def cue_matches(tactic: Tactic, text: str) -> list[str]:
    """Phrases in ``text`` that match the tactic's Field Guide cue patterns."""
    found: list[str] = []
    for pattern in tactic.patterns():
        for match in pattern.finditer(text):
            phrase = match.group(0).strip()
            if phrase.lower() not in {f.lower() for f in found}:
                found.append(phrase)
    return found


def validate(
    raw_flags: list[dict],
    lines: dict[int, Line],
    guide: dict[str, Tactic],
    spotter: str,
) -> list[Flag]:
    """Turn a model's answer into flags, discarding anything it made up.

    A flag survives only if its tactic is in the Field Guide and its lines
    exist. Cue phrases survive only if they appear word for word in the quote.
    """
    flags: list[Flag] = []
    for raw in raw_flags:
        tactic = guide.get(str(raw.get("tactic", "")))
        try:
            first, last = int(raw["first_line"]), int(raw.get("last_line", raw["first_line"]))
        except (KeyError, TypeError, ValueError):
            continue
        if tactic is None or first not in lines:
            continue
        last = min(max(last, first), first + 1)  # a quote is one or two lines
        if last not in lines:
            last = first
        quote = " ".join(lines[i].text for i in range(first, last + 1) if i in lines)

        cues = [
            str(phrase).strip()
            for phrase in raw.get("cue_phrases", [])
            if 0 < len(str(phrase).split()) <= 8 and _plain(str(phrase)) in _plain(quote)
        ][:3]
        try:
            teachability = min(max(int(raw.get("teachability", 3)), 1), 5)
        except (TypeError, ValueError):
            teachability = 3
        if not cues:
            cues = cue_matches(tactic, quote)[:3]
            if not cues:
                teachability = max(teachability - 1, 1)

        flags.append(
            Flag(
                id=f"{tactic.id}@{first}",
                tactic=tactic.id,
                first_segment=first,
                last_segment=last,
                start=lines[first].start,
                end=lines[last].end,
                quote=quote,
                cues=cues,
                why=" ".join(str(raw.get("why", "")).split())[:240],
                teachability=teachability,
                spotter=spotter,
            )
        )
    # One flag per tactic per starting line.
    return list({flag.id: flag for flag in flags}.values())


def lines_fingerprint(lines: list[Line]) -> str:
    """A fingerprint of exactly what a spotter reads: line numbers, times and masked text."""
    text = "\n".join(f"{line.id}\t{line.start}\t{line.end}\t{line.text}" for line in lines)
    return hashlib.sha256(text.encode()).hexdigest()[:8]


def run(
    folder: Path,
    lines: list[Line],
    guide: dict[str, Tactic],
    spotter: str = "auto",
    model: str | None = None,
    fresh: bool = False,
    on_progress: Callable[[float], None] | None = None,
) -> Run:
    """Spot flags, or reuse a saved run that read the same lines with the same spotter.

    ``folder`` is the bait's working folder. ``model`` picks the local model
    (default: ``BAITREEL_MODEL``, else gemma4:12b).
    """
    from . import keywords, local

    if spotter == "auto":
        spotter = "local" if local.available(model)[0] else "keywords"
    if spotter == "local":
        model = model or local.model_name()
        version = local.prompt_version(guide)
    elif spotter == "keywords":
        model = ""
        version = keywords.version(guide)
    else:
        raise ValueError(f"Unknown spotter {spotter!r}. Choose auto, local or keywords.")

    seen = lines_fingerprint(lines)
    label = re.sub(r"[^a-z0-9]+", "-", f"{spotter}-{model}".lower()).strip("-")
    path = folder / "runs" / f"{label}-{version}-{seen}.json"
    if path.exists() and not fresh:
        return workspace.load(path, Run)

    began = time.monotonic()
    if spotter == "local":
        flags = local.spot(lines, guide, on_progress=on_progress, model=model)
    else:
        flags = keywords.spot(lines, guide)
    result = Run(
        id=path.stem,
        spotter=spotter,
        model=model,
        version=version,
        lines=seen,
        seconds=round(time.monotonic() - began, 1),
        created_at=datetime.now(UTC),
        flags=flags,
    )
    workspace.save(path, result)
    return result


def saved_runs(folder: Path) -> list[Run]:
    """Every run saved for one bait, oldest first."""
    runs = [workspace.load(p, Run) for p in sorted((folder / "runs").glob("*.json"))]
    return sorted(runs, key=lambda r: r.created_at)
