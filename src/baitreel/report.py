"""Turn an ``Evaluation`` into a report: one HTML page, its charts as SVG files, and scores.json.

The page has no scripts and loads nothing from the internet, so it opens
anywhere and prints cleanly. Each chart is also saved as its own SVG file,
ready to drop into a class report, and every chart has a table beside it
with the same numbers.

Nothing in the report names a call or a labeler. Calls are numbered, people
are "Labeler A", and quotes are masked.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from .evaluate import Evaluation, Example, Score, SystemResult
from .fieldguide import guide
from .scoring import COVERED

# Colors, as CSS variables with the light value as a fallback. Inside the page
# the variables switch for dark mode; a standalone SVG file uses the fallback.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
STATUS = {"covered": "#0ca30c", "partly": "#fab219", "missed": "#d03b3b"}
INK, MUTED, GRID, AXIS = "#0b0b0b", "#898781", "#e1e0d9", "#c3c2b7"
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def _var(name: str, fallback: str) -> str:
    return f"var(--{name}, {fallback})"


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{value * 100:.0f}%"


def _num(value: float | None, places: int = 2) -> str:
    return "–" if value is None else f"{value:.{places}f}"


def _clock(seconds: float) -> str:
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def _pace(seconds: float | None, minutes: float) -> str:
    """Spotting time per minute of audio."""
    if seconds is None or not minutes:
        return "–"
    each = seconds / minutes
    return "under 1 s" if each < 1 else f"{each:.0f} s"


def _label(system: SystemResult) -> str:
    if system.kind == "human":
        return system.name
    what = "prompt" if system.name.startswith("local/") else "rules"
    return f"{system.name} ({what} {system.version})"


# --- Charts ---------------------------------------------------------------------


def _svg(width: int, height: int, title: str, body: list[str]) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img" aria-label="{escape(title)}" '
        f"font-family='{FONT}' font-size=\"13\">"
        f"<title>{escape(title)}</title>" + "".join(body) + "</svg>"
    )


def _bar(x: float, y: float, length: float, thickness: float, color: str, tip: str) -> str:
    """A horizontal bar, square at the baseline with a 4px rounded end."""
    if length <= 0:
        return f"<g><title>{escape(tip)}</title></g>"
    r = min(4.0, length, thickness / 2)
    path = (
        f"M{x:.1f},{y:.1f} h{length - r:.1f} a{r},{r} 0 0 1 {r},{r} "
        f"v{thickness - 2 * r:.1f} a{r},{r} 0 0 1 -{r},{r} h-{length - r:.1f} z"
    )
    return f'<path d="{path}" fill="{color}"><title>{escape(tip)}</title></path>'


def _legend(items: list[tuple[str, str]], x: float, y: float) -> list[str]:
    out, cursor = [], x
    for name, color in items:
        out.append(f'<rect x="{cursor:.0f}" y="{y - 9:.0f}" width="10" height="10" rx="2" '
                   f'fill="{color}"/>')  # fmt: skip
        out.append(
            f'<text x="{cursor + 15:.0f}" y="{y:.0f}" fill="{_var("ink-2", INK)}">'
            f"{escape(name)}</text>"
        )
        cursor += 30 + 7.2 * len(name)
    return out


def _axis(left: float, top: float, plot: float, bottom: float) -> list[str]:
    """Hairline gridlines at 0, 25, 50, 75 and 100 percent."""
    out = []
    for step in range(5):
        x = left + plot * step / 4
        color = _var("axis", AXIS) if step == 0 else _var("grid", GRID)
        out.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{bottom}" '
                   f'stroke="{color}" stroke-width="1"/>')  # fmt: skip
        out.append(f'<text x="{x:.1f}" y="{bottom + 16}" text-anchor="middle" '
                   f'fill="{_var("muted", MUTED)}">{step * 25}%</text>')  # fmt: skip
    return out


def grouped_bars(title: str, rows: list[tuple[str, list[float | None]]], series: list[str]) -> str:
    """Horizontal bars: one group per row, one bar per series, on a 0–100% scale."""
    series = series[: len(SERIES)]
    left, plot, bar, gap = 250, 440, 12, 2
    group = len(series) * (bar + gap) + 14
    top = 44
    height = top + group * len(rows) + 30
    body = _legend([(s, _var(f"s{i + 1}", SERIES[i])) for i, s in enumerate(series)], left, 18)
    body += _axis(left, top - 6, plot, height - 30)
    for r, (name, values) in enumerate(rows):
        y0 = top + r * group
        body.append(f'<text x="{left - 10}" y="{y0 + group / 2 - 4:.1f}" text-anchor="end" '
                    f'fill="{_var("ink", INK)}">{escape(name)}</text>')  # fmt: skip
        for i, value in enumerate(values[: len(series)]):
            y = y0 + i * (bar + gap)
            tip = f"{name}, {series[i]}: {_pct(value)}"
            if value is None:
                body.append(f'<text x="{left + 4}" y="{y + bar - 2}" font-size="11" '
                            f'fill="{_var("muted", MUTED)}">none to score</text>')  # fmt: skip
                continue
            body.append(_bar(left, y, plot * value, bar, _var(f"s{i + 1}", SERIES[i]), tip))
            if len(rows) * len(series) <= 12:
                body.append(f'<text x="{left + plot * value + 6:.1f}" y="{y + bar - 2}" '
                            f'font-size="11" fill="{_var("ink-2", INK)}">{_pct(value)}</text>')  # fmt: skip
    return _svg(left + plot + 50, height, title, body)


def stacked_counts(title: str, rows: list[tuple[str, dict[str, int]]]) -> str:
    """One bar per row, split into covered, partly covered and missed, as shares of the row."""
    left, plot, bar, step = 130, 480, 20, 34
    top = 44
    height = top + step * len(rows) + 30
    names = {"covered": "Covered", "partly": "Partly covered", "missed": "Missed"}
    body = _legend([(names[k], _var(k, c)) for k, c in STATUS.items()], left, 18)
    body += _axis(left, top - 6, plot, height - 30)
    for r, (name, counts) in enumerate(rows):
        y = top + r * step
        total = sum(counts.get(key, 0) for key in STATUS)
        body.append(f'<text x="{left - 10}" y="{y + bar - 5}" text-anchor="end" '
                    f'fill="{_var("ink", INK)}">{escape(name)} ({total})</text>')  # fmt: skip
        x = left
        for key, color in STATUS.items():
            share = counts.get(key, 0) / total if total else 0.0
            width = plot * share
            if width <= 0:
                continue
            tip = f"{name}: {counts[key]} of {total} {names[key].lower()}"
            body.append(f'<rect x="{x:.1f}" y="{y}" width="{max(width - 2, 1):.1f}" '
                        f'height="{bar}" rx="2" fill="{_var(key, color)}">'
                        f"<title>{escape(tip)}</title></rect>")  # fmt: skip
            if width > 34:
                ink = "#0b0b0b" if key == "partly" else "#ffffff"
                body.append(f'<text x="{x + 8:.1f}" y="{y + bar - 6}" fill="{ink}" '
                            f'font-size="12">{counts[key]}</text>')  # fmt: skip
            x += width
    return _svg(left + plot + 30, height, title, body)


# --- The page -------------------------------------------------------------------

CSS = """
:root { color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --ring: rgba(11,11,11,0.10);
  --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --s4: #eda100;
  --covered: #0ca30c; --partly: #fab219; --missed: #d03b3b; --good-text: #006300; }
@media (prefers-color-scheme: dark) { :root { color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7;
  --grid: #2c2c2a; --axis: #383835; --ring: rgba(255,255,255,0.10);
  --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500; --good-text: #0ca30c; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink);
  font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 920px; margin: 0 auto; padding: 40px 16px 80px; }
h1 { font-size: 30px; margin: 0 0 4px; letter-spacing: -0.01em; }
h2 { font-size: 21px; margin: 48px 0 8px; }
h3 { font-size: 16px; margin: 24px 0 8px; }
p, li { color: var(--ink-2); max-width: 68ch; }
.meta { color: var(--muted); margin: 0 0 24px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }
.tile { background: var(--surface); border: 1px solid var(--ring); border-radius: 10px;
  padding: 14px 16px; }
.tile .label { color: var(--ink-2); font-size: 14px; }
.tile .value { font-size: 30px; font-weight: 600; font-variant-numeric: tabular-nums; }
.tile .note { color: var(--muted); font-size: 13px; }
figure { margin: 16px 0; background: var(--surface); border: 1px solid var(--ring);
  border-radius: 10px; padding: 16px; overflow-x: auto; }
figure svg { max-width: 100%; height: auto; }
figcaption { color: var(--muted); font-size: 13px; margin-top: 6px; }
.table { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 14px; margin: 8px 0;
  font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 6px 10px 6px 0; border-bottom: 1px solid var(--grid);
  vertical-align: top; }
th { color: var(--ink-2); font-weight: 600; }
td.n, th.n { text-align: right; }
.quote { font-style: italic; }
.callout { border-left: 3px solid var(--axis); padding: 4px 0 4px 12px; color: var(--ink-2); }
@media print { body { background: white; } main { padding-top: 0; } figure { break-inside: avoid; } }
"""


def _table(headers: list[str], rows: list[list[str]], numeric: set[int] | None = None) -> str:
    numeric = numeric or set()
    head = "".join(
        f"<th{' class=n' if i in numeric else ''}>{escape(h)}</th>" for i, h in enumerate(headers)
    )
    body = "".join(
        "<tr>"
        + "".join(f"<td{' class=n' if i in numeric else ''}>{c}</td>" for i, c in enumerate(row))
        + "</tr>"
        for row in rows
    )
    return f'<div class="table"><table><tr>{head}</tr>{body}</table></div>'


def _tile(label: str, value: str, note: str) -> str:
    return (
        f'<div class="tile"><div class="label">{escape(label)}</div>'
        f'<div class="value">{escape(value)}</div><div class="note">{escape(note)}</div></div>'
    )


def _figure(svg: str, caption: str) -> str:
    return f"<figure>{svg}<figcaption>{escape(caption)}</figcaption></figure>"


def _score_cells(score: Score) -> list[str]:
    return [_pct(score.precision), _pct(score.recall), _pct(score.f1)]


def build(evaluation: Evaluation) -> tuple[str, dict[str, str]]:
    """Return the report page and its charts, as {file name: svg}."""
    cards = guide()
    tools = [s for s in evaluation.systems if s.kind == "tool"]
    people = [s for s in evaluation.systems if s.kind == "human"]
    charts: dict[str, str] = {}
    minutes = sum(c.minutes for c in evaluation.calls)
    out: list[str] = []

    out.append("<h1>Baitreel: second opinion</h1>")
    out.append(
        f'<p class="meta">{len(evaluation.calls)} call(s), {minutes:.0f} minutes of audio. '
        f"Generated {evaluation.generated_at:%B %-d, %Y} by Baitreel "
        f"{escape(evaluation.baitreel_version)}. Field Guide: {evaluation.guide_cards} "
        f"tactics, {evaluation.guide_reviewed} reviewed.</p>"
    )
    out.append(
        "<p>How well does Baitreel spot scam tactics and hide personal details? Each call was "
        "labeled by a person (or, for the scripted demo, by the script's own answer key) "
        "without looking at Baitreel's answers. Baitreel's answers are scored against those "
        "labels. Method and definitions are at the end.</p>"
    )
    for note in evaluation.notes:
        out.append(f'<p class="callout">{escape(note)}</p>')

    best = tools[0] if tools else None
    red = evaluation.redaction.overall
    tiles = []
    if best:
        tiles.append(_tile("Best spotter F1", _pct(best.overall.f1), _label(best)))
        tiles.append(_tile("Agreement with the labels", _num(best.kappa),
                           "Cohen's kappa, same spotter"))  # fmt: skip
    if people:
        tiles.append(
            _tile("Person vs person", _num(people[0].kappa), "kappa: the realistic ceiling")
        )
    tiles.append(_tile(
        "Redaction recall", _pct(red.recall),
        f"{red.covered} of {red.marked} hand-marked details fully bleeped",
    ))  # fmt: skip
    out.append(f'<div class="tiles">{"".join(tiles)}</div>')

    # Flags, overall.
    out.append("<h2>Spotting tactics</h2>")
    if not evaluation.systems:
        out.append("<p>No spotter has been scored yet.</p>")
    else:
        shown = evaluation.systems[: len(SERIES) * 2]
        charts["spotters.svg"] = grouped_bars(
            "Precision, recall and F1 for each spotter",
            [
                (_label(s)[:38], [s.overall.precision, s.overall.recall, s.overall.f1])
                for s in shown
            ],
            ["Precision", "Recall", "F1"],
        )
        out.append(_figure(
            charts["spotters.svg"],
            "Precision: how many flags were right. Recall: how many labeled moments were found. "
            "F1 balances the two.",
        ))  # fmt: skip
        rows = []
        for s in evaluation.systems:
            pace = _pace(s.seconds, s.minutes)
            rows.append([
                escape(_label(s)), str(s.calls), str(s.overall.spotted), str(s.overall.reference),
                *_score_cells(s.overall), _num(s.kappa), _pct(s.agreement), pace,
            ])  # fmt: skip
        out.append(_table(
            ["Spotter", "Calls", "Flags", "Labeled", "Precision", "Recall", "F1", "Kappa",
             "Lines agreed", "Time per audio minute"],
            rows, numeric=set(range(1, 10)),
        ))  # fmt: skip

        # By tactic.
        out.append("<h2>By tactic</h2>")
        compared = evaluation.systems[: len(SERIES)]
        tactic_ids = [t for t in cards if any(t in s.by_tactic for s in compared)]
        if tactic_ids:
            charts["tactics.svg"] = grouped_bars(
                "F1 for each tactic",
                [
                    (
                        cards[t].name,
                        [s.by_tactic[t].f1 if t in s.by_tactic else None for s in compared],
                    )
                    for t in tactic_ids
                ],  # fmt: skip
                [_label(s)[:34] for s in compared],
            )
            note = "" if len(evaluation.systems) <= len(SERIES) else (
                f" The chart shows the first {len(SERIES)} spotters; the table has all of them."
            )  # fmt: skip
            out.append(_figure(charts["tactics.svg"], "F1 per tactic. Hover a bar for the value."
                               + note))  # fmt: skip
        rows = []
        for t in tactic_ids:
            row = [escape(cards[t].name)]
            for s in evaluation.systems:
                score = s.by_tactic.get(t)
                row.append(
                    "–" if score is None
                    else f"{_pct(score.f1)} <span style='color:var(--muted)'>"
                    f"({score.correct}/{score.spotted} right, {score.found}/{score.reference} "
                    "found)</span>"
                )  # fmt: skip
            rows.append(row)
        out.append(_table(["Tactic", *[_label(s) for s in evaluation.systems]], rows))

    # Redaction.
    out.append("<h2>Hiding personal details</h2>")
    if not red.marked:
        out.append(
            "<p>No personal details have been marked by hand yet, so redaction cannot be "
            "scored. Mark them on the labeling page.</p>"
        )
    else:
        kinds = [(k.capitalize(), v) for k, v in evaluation.redaction.by_kind.items()]
        charts["redaction.svg"] = stacked_counts(
            "Hand-marked personal details, by how much of each was bleeped",
            [("All", red.model_dump())] + [(k, v.model_dump()) for k, v in kinds],
        )
        out.append(_figure(
            charts["redaction.svg"],
            f"Covered means bleeps hid at least {COVERED:.0%} of the detail. "
            "Partly covered still lets part of it be heard.",
        ))  # fmt: skip
        out.append(_table(
            ["Kind", "Marked", "Covered", "Partly", "Missed", "Recall"],
            [[escape(k), str(v.marked), str(v.covered), str(v.partly), str(v.missed),
              _pct(v.recall)] for k, v in [("All", red), *kinds]],
            numeric={1, 2, 3, 4, 5},
        ))  # fmt: skip
        out.append(
            f"<p>Baitreel also bleeped {evaluation.redaction.unmarked_bleeps} of its "
            f"{evaluation.redaction.bleeps} stretches where nobody marked a detail. It is built "
            "to err that way: a needless bleep costs a word, a missed one can expose a person.</p>"
        )

    # Calls.
    out.append("<h2>The calls</h2>")
    out.append(_table(
        ["Call", "Kind", "Minutes", "Lines", "Labeled by", "Blind", "Flags", "Details",
         "Second labelers", "Redaction"],
        [[str(c.number), "scripted demo" if c.kind == "scripted-demo" else "real",
          f"{c.minutes:.1f}", str(c.lines), escape(c.reference), "yes" if c.blind else "maybe not",
          str(c.flags_marked), str(c.details_marked), str(c.second_labelers),
          escape(c.redaction_from)] for c in evaluation.calls],
        numeric={2, 3, 6, 7, 8},
    ))  # fmt: skip
    if any(not c.blind for c in evaluation.calls):
        out.append(
            "<p>“Maybe not” means Baitreel had already spotted flags for that call when "
            "labeling began. If the labeler looked at them, the labels are not blind and the "
            "scores may be too kind.</p>"
        )

    # Examples.
    if evaluation.examples:
        out.append("<h2>Where they disagreed</h2>")
        out.append(
            "<p>A sample of missed moments and false alarms, to show what goes wrong. Personal "
            "details are masked, both Baitreel's redactions and every detail marked by hand. "
            "Read these before sharing the report.</p>"
        )
        for s in evaluation.systems:
            mine = [e for e in evaluation.examples if e.system == s.key]
            if mine:
                out.append(f"<h3>{escape(_label(s))}</h3>")
                out.append(_table(["Call", "At", "What", "Tactic", "Heard"],
                                  [_example_row(e, cards) for e in mine]))  # fmt: skip

    out.append("<h2>Method</h2>")
    out.append(
        "<ul>"
        "<li><b>Correct flag:</b> a flag from the spotter that overlaps a labeled moment of the "
        "same tactic. <b>Found:</b> a labeled moment that any flag of the same tactic overlaps. "
        "Precision is correct flags over all flags; recall is found moments over labeled "
        "moments. A moment split across two transcript lines is not counted against the "
        "spotter twice.</li>"
        "<li><b>Kappa</b> compares the two sides line by line. Each transcript line gets the "
        "tactic that covers most of it, or none, and Cohen's kappa corrects the share of lines "
        "agreed on for agreement expected by chance. 1 is perfect, 0 is chance. One published "
        "benchmark of scam-call labeling found two people agreeing at about 0.69.</li>"
        f"<li><b>Redaction recall</b> is the share of hand-marked personal details that bleeps "
        f"cover at least {COVERED:.0%} of. Partly covered details count as misses.</li>"
        "<li>Scores pool every call a spotter read. Spotters are named by model and by a "
        "fingerprint of their prompt or rules, so a changed prompt is scored as a new "
        "version.</li>"
        "<li>Limits: the tool sees only the transcript, so a labeled moment the speech model "
        "garbled is hard for any spotter. A few calls are a small sample, so treat differences "
        "of a few points as noise.</li>"
        "</ul>"
    )
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Baitreel evaluation</title><style>{CSS}</style></head>"
        f"<body><main>{''.join(out)}</main></body></html>"
    )
    return page, charts


def _example_row(example: Example, cards) -> list[str]:
    name = cards[example.tactic].name if example.tactic in cards else example.tactic
    what = "Missed" if example.kind == "missed" else "False alarm"
    return [
        str(example.call), _clock(example.at), what, escape(name),
        f'<span class="quote">“{escape(example.quote)}”</span>',
    ]  # fmt: skip


def write(evaluation: Evaluation, folder: Path) -> Path:
    """Write report.html, scores.json and charts/*.svg. Returns the page's path."""
    page, charts = build(evaluation)
    (folder / "charts").mkdir(parents=True, exist_ok=True)
    for old in (folder / "charts").glob("*.svg"):
        old.unlink()
    for name, svg in charts.items():
        (folder / "charts" / name).write_text(svg + "\n", encoding="utf-8")
    (folder / "scores.json").write_text(evaluation.model_dump_json(indent=2) + "\n")
    path = folder / "report.html"
    path.write_text(page, encoding="utf-8")
    return path
