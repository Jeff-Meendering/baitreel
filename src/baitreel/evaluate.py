"""``baitreel eval``: score Baitreel's flags and redactions against a person's labels.

For every bait with finished labels it:

1. picks the **reference** labels (the demo script's answer key, or the first
   person who finished labeling the call),
2. redoes redaction with the current code and the allow list the bait was cut
   with, so changes to ``redact.py`` show up in the numbers,
3. makes sure the keyword spotter has run, runs any local models it was asked
   to, and gathers every saved run that read the same transcript lines
   (earlier prompt versions included),
4. scores each run, and any second labeler, against the reference.

The result is an ``Evaluation``: plain numbers that ``report.py`` turns into
a page with charts. Calls are numbered, not named, and quotes are masked, so
the report can be shared.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from . import __version__, demo, redact, spot, workspace
from .fieldguide import guide
from .labels import DetailMark, Labels, demo_answer_key, load_all
from .labels import save as save_labels
from .models import Bait, Redaction, Run, SourceKind, Transcript
from .pipeline import Report, _quiet, lines_for_model
from .scoring import (
    RedactionTally,
    Span,
    Tally,
    cohens_kappa,
    coverage,
    line_labels,
    observed_agreement,
    outcome,
    score_flags,
    unmarked_bleeps,
)

EXAMPLES_PER_SYSTEM = 8  # of each kind: missed flags and false alarms
HUMAN = "Another person"


# --- What gets written to scores.json ----------------------------------------


class Score(BaseModel):
    spotted: int
    correct: int
    reference: int
    found: int
    precision: float | None
    recall: float | None
    f1: float | None

    @classmethod
    def of(cls, tally: Tally) -> Score:
        return cls(
            spotted=tally.spotted, correct=tally.correct, reference=tally.reference,
            found=tally.found, precision=tally.precision, recall=tally.recall, f1=tally.f1,
        )  # fmt: skip


class SystemResult(BaseModel):
    """One spotter version (or a second person), pooled over every call it read."""

    key: str
    name: str  # "keywords", "local/gemma4:12b", or "Another person"
    version: str  # the prompt or rules fingerprint; empty for people
    kind: Literal["tool", "human"]
    calls: int
    minutes: float  # minutes of audio covered
    seconds: float | None  # time spent spotting, for tools
    overall: Score
    by_tactic: dict[str, Score]
    kappa: float | None
    agreement: float | None
    lines: int


class RedactionCounts(BaseModel):
    marked: int = 0
    covered: int = 0
    partly: int = 0
    missed: int = 0
    recall: float | None = None

    @classmethod
    def of(cls, tally: RedactionTally) -> RedactionCounts:
        return cls(**{k: getattr(tally, k) for k in ("marked", "covered", "partly", "missed")},
                   recall=tally.recall)  # fmt: skip


class RedactionResult(BaseModel):
    overall: RedactionCounts
    by_kind: dict[str, RedactionCounts]
    bleeps: int
    unmarked_bleeps: int
    calls: int


class CallInfo(BaseModel):
    number: int
    kind: SourceKind
    minutes: float
    lines: int
    reference: str  # "Labeler A" or "the demo script's answer key"
    blind: bool
    flags_marked: int
    details_marked: int
    second_labelers: int
    redaction_from: Literal["current code", "saved file"]
    redaction: RedactionCounts


class Example(BaseModel):
    system: str
    call: int
    at: float
    tactic: str
    kind: Literal["missed", "false alarm"]
    quote: str  # masked: Baitreel's redactions and every hand-marked detail


class Evaluation(BaseModel):
    generated_at: datetime
    baitreel_version: str
    guide_cards: int
    guide_reviewed: int
    calls: list[CallInfo]
    systems: list[SystemResult]
    redaction: RedactionResult
    examples: list[Example]
    notes: list[str] = Field(default_factory=list)


# --- Gathering one call ---------------------------------------------------------


@dataclass
class Call:
    bait: Bait
    transcript: Transcript
    reference: Labels
    others: list[Labels]
    redactions: list[Redaction]
    redaction_from: Literal["current code", "saved file"]
    runs: list[Run]


def _redactions(bait: Bait, transcript: Transcript) -> tuple[list[Redaction], str]:
    """Redo redaction with today's code, using the allow list the bait was cut with."""
    folder = workspace.bait_dir(bait.id)
    allow_file = folder / "allow.json"
    if allow_file.exists():
        allow = json.loads(allow_file.read_text(encoding="utf-8"))
    elif bait.kind == "scripted-demo":
        allow = demo.ALLOW
    elif (folder / "redactions.json").exists():
        # Cut before the allow list was saved: score what was actually done.
        return workspace.load(folder / "redactions.json", list[Redaction]), "saved file"
    else:
        allow = []
    return redact.find_redactions(transcript.segments, allow), "current code"


def gather(
    bait: Bait,
    models: list[str],
    reference: str | None = None,
    report: Report = _quiet,
) -> Call | str:
    """Everything needed to score one bait, or the reason it cannot be scored yet."""
    folder = workspace.bait_dir(bait.id)
    path = folder / "transcript.json"
    if not path.exists():
        return "it has no transcript yet. Run `baitreel label` on it first."
    transcript = workspace.load(path, Transcript)

    if bait.kind == "scripted-demo":
        key, problems = demo_answer_key(bait, transcript)
        if key:
            save_labels(key)
        for problem in problems:
            report("Note", 1.0, f"demo answer key: {problem}")

    finished = [labels for labels in load_all(bait.id) if labels.finished]
    if not finished:
        return "nobody has finished labeling it. Press Finish on the labeling page when done."
    if reference:
        chosen = [lab for lab in finished if lab.labeler.lower() == reference.lower()]
        if not chosen:
            return f"{reference} has not finished labeling it."
    else:
        chosen = [lab for lab in finished if lab.source == "demo-script"] or finished
    first = chosen[0]
    others = [lab for lab in finished if lab is not first and lab.source != "demo-script"]

    redactions, redaction_from = _redactions(bait, transcript)
    lines = lines_for_model(transcript, redactions)
    cards = guide()
    runs = {r.id: r for r in spot.saved_runs(folder)}
    wanted = [("keywords", None)] + [("local", model) for model in models]
    for spotter, model in wanted:
        label = "Spotting with " + (model or spotter)
        report(label, 0.0, "a local model takes minutes" if model else "")
        result = spot.run(
            folder, lines, cards, spotter, model,
            on_progress=lambda p, label=label: report(label, p, ""),
        )  # fmt: skip
        report(label, 1.0, f"{len(result.flags)} flags")
        runs[result.id] = result
    current = spot.lines_fingerprint(lines)
    usable = sorted((r for r in runs.values() if r.lines == current), key=lambda r: r.created_at)
    return Call(bait, transcript, first, others, redactions, redaction_from, usable)


# --- Scoring --------------------------------------------------------------------


def _flag_spans(labels: Labels) -> list[Span]:
    return [Span(f.tactic, f.start, f.end) for f in labels.flags]


def _run_spans(run: Run) -> list[Span]:
    return [Span(f.tactic, f.start, f.end) for f in run.flags]


def _masked_quote(call: Call, span: Span, marks: list[DetailMark]) -> str:
    """The words heard during a span, with every redaction and hand-marked detail masked."""
    hidden = {(r.segment, i) for r in call.redactions for i in range(r.first_word, r.last_word + 1)}
    words: list[str] = []
    for segment in call.transcript.segments:
        if segment.end <= span.start or segment.start >= span.end:
            continue
        for i, word in enumerate(segment.words):
            touched = any(word.start < m.end and word.end > m.start for m in marks)
            if (segment.id, i) in hidden or touched:
                if not words or words[-1] != "[masked]":
                    words.append("[masked]")
            else:
                words.append(word.text)
    text = " ".join(words)
    return text if len(words) <= 40 else " ".join(words[:40]) + " …"


@dataclass
class _Pool:
    name: str
    version: str
    kind: Literal["tool", "human"]
    tallies: dict[str, Tally]
    left: list[str]
    right: list[str]
    calls: int = 0
    minutes: float = 0.0
    seconds: float | None = None


def evaluate(calls: list[Call], notes: list[str] | None = None) -> Evaluation:
    cards = guide()
    pools: dict[str, _Pool] = {}
    examples: list[Example] = []
    infos: list[CallInfo] = []
    redaction_total = RedactionTally()
    by_kind: dict[str, RedactionTally] = defaultdict(RedactionTally)
    bleeps_total = unmarked_total = 0
    labeler_letters: dict[str, str] = {}

    for number, call in enumerate(calls, start=1):
        minutes = call.bait.duration / 60
        line_times = [(s.start, s.end) for s in call.transcript.segments]
        reference_spans = _flag_spans(call.reference)
        reference_lines = line_labels(reference_spans, line_times)
        marks = [m for labels in [call.reference, *call.others] for m in labels.details]

        sides: list[tuple[str, str, Literal["tool", "human"], list[Span], float | None]] = [
            (run.name, run.version, "tool", _run_spans(run), run.seconds) for run in call.runs
        ]
        sides += [(HUMAN, "", "human", _flag_spans(other), None) for other in call.others]
        for name, version, kind, spans, seconds in sides:
            key = f"{name} · {version}" if version else name
            pool = pools.setdefault(
                key, _Pool(name, version, kind, defaultdict(Tally), [], [], seconds=None)
            )
            scored = score_flags(spans, reference_spans)
            for tactic, tally in scored.by_tactic.items():
                pool.tallies[tactic] = pool.tallies[tactic] + tally
            pool.left += reference_lines
            pool.right += line_labels(spans, line_times)
            pool.calls += 1
            pool.minutes += minutes
            if seconds is not None:
                pool.seconds = (pool.seconds or 0.0) + seconds
            for kind_of, found in (("missed", scored.misses), ("false alarm", scored.false_alarms)):
                for span in found:
                    examples.append(Example(
                        system=key, call=number, at=round(span.start, 1), tactic=span.label,
                        kind=kind_of, quote=_masked_quote(call, span, marks),
                    ))  # fmt: skip

        # Redaction: Baitreel's bleeps against the reference's hand-marked details.
        bleeps = [Span(r.kind, r.start, r.end) for r in call.redactions]
        details = [Span(m.kind, m.start, m.end) for m in call.reference.details]
        here = RedactionTally()
        for detail in details:
            result = outcome(coverage(detail, bleeps))
            here.add(result)
            by_kind[detail.label].add(result)
        redaction_total = redaction_total + here
        bleeps_total += len(bleeps)
        unmarked_total += unmarked_bleeps(bleeps, details)

        if call.reference.source == "demo-script":
            who = "the demo script's answer key"
        else:
            letter = labeler_letters.setdefault(
                call.reference.labeler.lower(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[len(labeler_letters)]
            )
            who = f"Labeler {letter}"
        infos.append(CallInfo(
            number=number, kind=call.bait.kind, minutes=round(minutes, 1),
            lines=len(line_times), reference=who, blind=not call.reference.tool_ran_first,
            flags_marked=len(call.reference.flags), details_marked=len(call.reference.details),
            second_labelers=len(call.others), redaction_from=call.redaction_from,
            redaction=RedactionCounts.of(here),
        ))  # fmt: skip

    systems = []
    for key, pool in pools.items():
        overall = sum(pool.tallies.values(), Tally())
        systems.append(SystemResult(
            key=key, name=pool.name, version=pool.version, kind=pool.kind, calls=pool.calls,
            minutes=round(pool.minutes, 1),
            seconds=round(pool.seconds, 1) if pool.seconds is not None else None,
            overall=Score.of(overall),
            by_tactic={t: Score.of(pool.tallies[t]) for t in cards if t in pool.tallies},
            kappa=cohens_kappa(pool.left, pool.right),
            agreement=observed_agreement(pool.left, pool.right), lines=len(pool.left),
        ))  # fmt: skip
    # People first (the ceiling), then tools from best to worst.
    systems.sort(key=lambda s: (s.kind != "human", -(s.overall.f1 or 0.0), s.key))

    trimmed: list[Example] = []
    for system in systems:
        for kind_of in ("missed", "false alarm"):
            mine = [e for e in examples if e.system == system.key and e.kind == kind_of]
            trimmed += mine[:EXAMPLES_PER_SYSTEM]

    return Evaluation(
        generated_at=datetime.now(UTC),
        baitreel_version=__version__,
        guide_cards=len(cards),
        guide_reviewed=sum(card.status == "reviewed" for card in cards.values()),
        calls=infos,
        systems=systems,
        redaction=RedactionResult(
            overall=RedactionCounts.of(redaction_total),
            by_kind={k: RedactionCounts.of(v) for k, v in sorted(by_kind.items())},
            bleeps=bleeps_total,
            unmarked_bleeps=unmarked_total,
            calls=sum(1 for c in calls if c.reference.details),
        ),
        examples=trimmed,
        notes=list(notes or []),
    )


def labeled_baits() -> list[Bait]:
    """Every bait that has at least one label file, or is the scripted demo."""
    found = []
    for path in sorted((workspace.home() / "baits").glob("*/bait.json")):
        bait = workspace.load(path, Bait)
        has_labels = any((path.parent / "labels").glob("*.json"))
        if has_labels or bait.kind == "scripted-demo":
            found.append(bait)
    return found
