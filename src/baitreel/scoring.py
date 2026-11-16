"""The arithmetic behind ``baitreel eval``. No files, no models: easy to test and to check by hand.

**Flags** are scored per tactic. A spotted flag is *correct* when a reference
flag of the same tactic overlaps it in time. A reference flag is *found* when
any spotted flag of the same tactic overlaps it.

    precision = correct spotted flags / spotted flags
    recall    = found reference flags / reference flags
    F1        = the harmonic mean of the two

Counting both sides separately means a moment the tool splits across two
lines is not punished twice, and one long tool flag cannot claim credit for
a different tactic nearby.

**Agreement** is Cohen's kappa over transcript lines. Each line gets one
label from each side: the tactic whose flag covers most of it, or "none".
Kappa corrects the raw agreement for the agreement expected by chance.

**Redaction** is scored against hand-marked personal details. A detail is
*covered* when bleeps cover at least ``COVERED`` of it, *partly covered*
when they touch it, and *missed* otherwise. Redaction recall counts only
covered details: half a phone number is still a phone number.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

NONE = "none"
MIN_OVERLAP = 0.1  # seconds two flags must share to count as the same moment
COVERED = 0.8  # share of a personal detail the bleeps must cover


@dataclass(frozen=True)
class Span:
    """A tactic (or a personal detail) between two times in the call, in seconds."""

    label: str
    start: float
    end: float

    @property
    def length(self) -> float:
        return max(self.end - self.start, 0.0)


def overlap(a: Span, b: Span) -> float:
    return max(0.0, min(a.end, b.end) - max(a.start, b.start))


def _ratio(top: int, bottom: int) -> float | None:
    return top / bottom if bottom else None


@dataclass
class Tally:
    """Counts for one tactic (or all of them). Add tallies to pool calls together."""

    spotted: int = 0
    correct: int = 0
    reference: int = 0
    found: int = 0

    def __add__(self, other: Tally) -> Tally:
        return Tally(
            self.spotted + other.spotted,
            self.correct + other.correct,
            self.reference + other.reference,
            self.found + other.found,
        )

    @property
    def precision(self) -> float | None:
        return _ratio(self.correct, self.spotted)

    @property
    def recall(self) -> float | None:
        return _ratio(self.found, self.reference)

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None:
            return None
        return 0.0 if p + r == 0 else 2 * p * r / (p + r)


@dataclass
class FlagScore:
    by_tactic: dict[str, Tally]
    false_alarms: list[Span] = field(default_factory=list)  # spotted, matching nothing
    misses: list[Span] = field(default_factory=list)  # reference flags nobody found

    @property
    def overall(self) -> Tally:
        return sum(self.by_tactic.values(), Tally())


def _matches(span: Span, others: Iterable[Span]) -> bool:
    return any(o.label == span.label and overlap(span, o) >= MIN_OVERLAP for o in others)


def score_flags(spotted: Sequence[Span], reference: Sequence[Span]) -> FlagScore:
    tactics = sorted({s.label for s in spotted} | {s.label for s in reference})
    result = FlagScore({t: Tally() for t in tactics})
    for span in spotted:
        tally = result.by_tactic[span.label]
        tally.spotted += 1
        if _matches(span, reference):
            tally.correct += 1
        else:
            result.false_alarms.append(span)
    for span in reference:
        tally = result.by_tactic[span.label]
        tally.reference += 1
        if _matches(span, spotted):
            tally.found += 1
        else:
            result.misses.append(span)
    return result


# --- Agreement ----------------------------------------------------------------


def line_labels(spans: Sequence[Span], lines: Sequence[tuple[float, float]]) -> list[str]:
    """One label per transcript line: the tactic covering most of it, or "none".

    A flag covers a line when they share at least half of the shorter of the
    two, so a short label inside a long line still counts, and a long label
    only brushing a line's edge does not.
    """
    labels: list[str] = []
    for start, end in lines:
        line = Span(NONE, start, end)
        best, best_overlap = NONE, 0.0
        for span in sorted(spans, key=lambda s: s.label):
            shared = overlap(line, span)
            if shared > best_overlap and shared >= 0.5 * min(line.length, span.length):
                best, best_overlap = span.label, shared
        labels.append(best)
    return labels


def observed_agreement(a: Sequence[str], b: Sequence[str]) -> float | None:
    if len(a) != len(b):
        raise ValueError("both sides must label the same lines")
    return _ratio(sum(x == y for x, y in zip(a, b, strict=True)), len(a))


def cohens_kappa(a: Sequence[str], b: Sequence[str]) -> float | None:
    """Cohen's kappa for two raters labeling the same items. None when it is undefined."""
    observed = observed_agreement(a, b)
    if observed is None:
        return None
    n = len(a)
    count_a, count_b = Counter(a), Counter(b)
    expected = sum(count_a[k] * count_b[k] for k in count_a) / (n * n)
    if expected >= 1.0:
        return None  # both sides used one label for everything: nothing to correct for
    return (observed - expected) / (1.0 - expected)


# --- Redaction ----------------------------------------------------------------


def coverage(detail: Span, bleeps: Sequence[Span]) -> float:
    """The share of a personal detail that the bleeps cover, from 0 to 1."""
    if detail.length == 0:
        return 0.0
    pieces = sorted(
        (max(b.start, detail.start), min(b.end, detail.end)) for b in bleeps if overlap(b, detail)
    )
    covered, reach = 0.0, detail.start
    for start, end in pieces:
        start = max(start, reach)
        if end > start:
            covered += end - start
            reach = end
    return min(covered / detail.length, 1.0)


def outcome(share: float) -> str:
    if share >= COVERED:
        return "covered"
    return "partly" if share > 0 else "missed"


@dataclass
class RedactionTally:
    marked: int = 0
    covered: int = 0
    partly: int = 0
    missed: int = 0

    def __add__(self, other: RedactionTally) -> RedactionTally:
        return RedactionTally(
            self.marked + other.marked,
            self.covered + other.covered,
            self.partly + other.partly,
            self.missed + other.missed,
        )

    def add(self, result: str) -> None:
        self.marked += 1
        setattr(self, result, getattr(self, result) + 1)

    @property
    def recall(self) -> float | None:
        return _ratio(self.covered, self.marked)


def unmarked_bleeps(bleeps: Sequence[Span], details: Sequence[Span]) -> int:
    """Bleeps that touch no hand-marked detail. Baitreel errs this way on purpose."""
    return sum(1 for b in bleeps if not any(overlap(b, d) > 0 for d in details))
