"""`baitreel eval` from labels to report, on a small made-up call."""

from datetime import UTC, datetime

from baitreel import evaluate, labels, report, workspace
from baitreel.labels import DetailMark, TacticLabel
from tests.conftest import make_transcript

LINES = (
    "Hello this is Officer Daniel Hart from the fraud department.",  # 0: the badge
    "Oh hello dear, let me turn down the radio.",  # 1
    "Do not tell anyone about this call, not even your family.",  # 2: the hush
    "My grandson Tobias lives nearby.",  # 3: a name the tool may miss
    "Go and buy four gift cards and read me the numbers on the back.",  # 4: gift cards
    "Call me back on 4 1 5 5 5 5 0 1 4 2.",  # 5: a number
)


def _setup(home, bait, finished=True):
    bait = bait.model_copy(update={"kind": "real"})
    folder = workspace.bait_dir(bait.id)
    workspace.save(folder / "bait.json", bait)
    transcript = make_transcript(*LINES)
    workspace.save(folder / "transcript.json", transcript)
    seg = transcript.segments
    mine = labels.open_labels(bait.id, "Sam Tester", transcript)
    mine.finished = finished
    mine.flags = [
        TacticLabel(tactic="the-badge", start=seg[0].start, end=seg[0].end),
        TacticLabel(tactic="the-hush", start=seg[2].start, end=seg[2].end),
        TacticLabel(tactic="the-gift-card-detour", start=seg[4].start, end=seg[4].end),
    ]
    words = {w.text.strip(".,"): w for s in seg for w in s.words}
    mine.details = [
        DetailMark(start=words["Daniel"].start, end=words["Hart"].end, kind="name"),
        DetailMark(start=words["Tobias"].start, end=words["Tobias"].end, kind="name"),
        DetailMark(start=seg[5].words[3].start, end=seg[5].words[-1].end, kind="number"),
    ]
    labels.save(mine)
    return bait, transcript


def test_unfinished_labels_are_not_scored(home, bait):
    bait, _ = _setup(home, bait, finished=False)
    reason = evaluate.gather(bait, models=[])
    assert isinstance(reason, str) and "finished" in reason


def test_scores_the_keyword_spotter_and_redaction(home, bait):
    bait, _ = _setup(home, bait)
    call = evaluate.gather(bait, models=[])
    assert not isinstance(call, str)
    result = evaluate.evaluate([call])

    (keywords,) = result.systems
    assert keywords.name == "keywords" and keywords.kind == "tool"
    assert keywords.overall.reference == 3
    assert keywords.overall.recall == 1.0  # the keyword cues cover all three scripted lines
    assert keywords.kappa is not None

    red = result.redaction.overall
    assert red.marked == 3
    assert red.covered + red.partly + red.missed == 3
    assert result.calls[0].reference == "Labeler A"  # people are not named in the report
    assert result.calls[0].blind


def test_the_report_never_contains_personal_details(home, bait):
    bait, _ = _setup(home, bait)
    call = evaluate.gather(bait, models=[])
    result = evaluate.evaluate([call])
    # Force a disagreement that quotes the line with the name and the number.
    result.examples.append(
        evaluate.Example(
            system=result.systems[0].key, call=1, at=0.0, tactic="the-badge", kind="missed",
            quote=evaluate._masked_quote(call, evaluate.Span("x", 0.0, 999.0),
                                         call.reference.details),
        )
    )  # fmt: skip
    path = report.write(result, home / "eval")
    page = path.read_text()
    for secret in ("Daniel", "Hart", "Tobias", "4 1 5", "Sam Tester", bait.title):
        assert secret not in page, secret
    assert (home / "eval" / "charts" / "spotters.svg").exists()
    assert (home / "eval" / "charts" / "redaction.svg").exists()
    assert "Labeler A" in page


def test_runs_are_reused_until_the_lines_change(home, bait):
    bait, _ = _setup(home, bait)
    first = evaluate.gather(bait, models=[]).runs
    again = evaluate.gather(bait, models=[]).runs
    assert [r.id for r in first] == [r.id for r in again]
    assert first[0].created_at == again[0].created_at


def test_a_second_labeler_is_scored_as_the_human_ceiling(home, bait):
    bait, transcript = _setup(home, bait)
    other = labels.open_labels(bait.id, "Alex", transcript)
    other.created_at = datetime.now(UTC)
    other.finished = True
    other.flags = [TacticLabel(tactic="the-hush", start=transcript.segments[2].start,
                               end=transcript.segments[2].end)]  # fmt: skip
    labels.save(other)
    result = evaluate.evaluate([evaluate.gather(bait, models=[])])
    human = next(s for s in result.systems if s.kind == "human")
    assert (human.overall.precision, human.overall.recall) == (1.0, 1 / 3)
    assert result.systems[0].kind == "human"  # people are listed first
