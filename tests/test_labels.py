"""Labels: Audacity label tracks, the demo answer key, and label files."""

import pytest

from baitreel import labels
from baitreel.fieldguide import guide
from baitreel.labels import LabelTrackError, read_label_track, resolve_tactic
from tests.conftest import make_transcript

GUIDE = guide()
TRANSCRIPT = make_transcript(
    "Hello this is Officer Daniel Hart.",
    "Do not tell anyone about this call.",
    "My number is 5 5 5 0 1 4 2.",
)


def test_tactics_can_be_named_several_ways():
    for text in ("the-hush", "The Hush", "hush", "  THE HUSH "):
        assert resolve_tactic(text, GUIDE) == "the-hush"
    assert resolve_tactic("the whisper", GUIDE) is None


def test_reads_an_audacity_label_track():
    track = (
        "1.200000\t2.900000\tThe Badge\n"
        "\\\t300.0\t3400.0\n"  # a frequency line, which Audacity writes for spectral selections
        "3.000000\t3.000000\thush\n"  # a point label
        "1.500000\t2.100000\tpii:name\n"
        "6.000000\t8.000000\tpersonal number\n"
    )
    flags, details = read_label_track(track, GUIDE, TRANSCRIPT)
    assert [(f.tactic, f.start, f.end) for f in flags] == [
        ("the-badge", 1.2, 2.9),
        # A point label covers the whole transcript line heard at that moment.
        ("the-hush", TRANSCRIPT.segments[1].start, TRANSCRIPT.segments[1].end),
    ]
    assert [(d.kind, d.start, d.end) for d in details] == [
        ("name", 1.5, 2.1),
        ("number", 6.0, 8.0),
    ]


def test_a_label_track_with_mistakes_is_refused_with_every_problem_listed():
    track = "1.0\t2.0\tThe Whisper\n3.0\t3.0\tpii\nnonsense\n4.0\t5.0\tpii:shoe size\n"
    with pytest.raises(LabelTrackError) as error:
        read_label_track(track, GUIDE, TRANSCRIPT)
    message = str(error.value)
    assert "line 1" in message and "not a Field Guide tactic" in message
    assert "line 2" in message and "needs a region" in message
    assert "line 3" in message
    assert "line 4" in message and "unknown kind" in message


def test_label_files_hold_times_not_words(home):
    mine = labels.open_labels("bait-1", "Sam Tester", TRANSCRIPT)
    mine.details.append(labels.DetailMark(start=1.5, end=2.1, kind="name"))
    mine.flags.append(labels.TacticLabel(tactic="the-badge", start=0.2, end=2.0))
    path = labels.save(mine)
    assert path.name == "sam-tester.json"
    assert "Daniel" not in path.read_text()
    assert labels.load_all("bait-1")[0].details[0].kind == "name"


def test_labels_started_after_the_tool_ran_are_marked_as_maybe_not_blind(home):
    assert not labels.open_labels("bait-2", "Sam", TRANSCRIPT).tool_ran_first
    (home / "baits" / "bait-2").mkdir(parents=True)
    (home / "baits" / "bait-2" / "flags.json").write_text("[]")
    assert labels.open_labels("bait-3", "Sam", TRANSCRIPT).tool_ran_first is False
    assert labels.open_labels("bait-2", "Sam", TRANSCRIPT).tool_ran_first is True


def test_the_demo_answer_key_finds_scripted_details_in_the_transcript():
    segments = make_transcript("Her number is 555-0142.", "It says four 7 1 9 2 0.").segments
    assert labels._find_words("5 5 5 0 1 4 2", segments, 0.0, 99.0) == (
        segments[0].words[3].start,
        segments[0].words[3].end,
    )
    found = labels._find_words("4 7 1 9 2 0", segments, 0.0, 99.0)
    assert found == (segments[1].words[2].start, segments[1].words[-1].end)
    assert labels._find_words("Margaret Dolan", segments, 0.0, 99.0) is None
