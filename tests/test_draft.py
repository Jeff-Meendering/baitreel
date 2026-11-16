"""Drafting turns a flag into the five beats of a clip."""

import pytest

from baitreel import draft
from baitreel.fieldguide import guide
from baitreel.models import Flag
from baitreel.redact import find_redactions

from .conftest import make_transcript

GUIDE = guide()


def flag(tactic: str, line: int, transcript, cues=(), teachability=4) -> Flag:
    segment = transcript.segments[line]
    return Flag(
        id=f"{tactic}@{line}", tactic=tactic, first_segment=line, last_segment=line,
        start=segment.start, end=segment.end, quote=segment.text, cues=list(cues),
        teachability=teachability, spotter="test",
    )  # fmt: skip


@pytest.fixture
def call():
    return make_transcript(
        "Should I call my neighbor Margaret on 555 0142 first",
        "No ma'am do not tell anyone about this call",
        "Now move your savings into a secure government account",
    )


def test_a_draft_has_five_beats_in_order_with_no_gaps(bait, call):
    item = draft.build(bait, call, [], flag("the-hush", 1, call), GUIDE["the-hush"], 1)
    beats = item.spec.beats
    assert [b.name for b in beats] == ["play", "flag", "replay", "counter", "credit"]
    assert beats[0].start == 0
    for before, after in zip(beats, beats[1:], strict=False):
        assert before.end == after.start
    assert item.spec.duration == beats[-1].end
    assert item.spec.id == "01-the-hush"


def test_context_comes_before_the_quote(bait, call):
    item = draft.build(bait, call, [], flag("the-hush", 1, call), GUIDE["the-hush"], 1)
    shown = " ".join(w.text for card in item.spec.cards for w in card.words)
    assert shown.startswith("Should I call my neighbor")
    assert shown.endswith("about this call")
    quoted = " ".join(w.text for card in item.spec.replay_cards for w in card.words)
    assert quoted == "No ma'am do not tell anyone about this call"


def test_the_spec_never_contains_redacted_words(bait, call):
    """The clip spec is what the stage page receives. Personal details must not be in it."""
    redactions = find_redactions(call.segments, use_names=False)
    assert any(r.kind == "number" for r in redactions)
    item = draft.build(bait, call, redactions, flag("the-hush", 1, call), GUIDE["the-hush"], 1)
    spec_json = item.spec.model_dump_json()
    assert "0142" not in spec_json and "555" not in spec_json
    masked = [w for card in item.spec.cards for w in card.words if w.redacted]
    assert [w.text for w in masked] == ["number"]
    # The audit trail, kept locally for the reviewer, does know what was hidden.
    assert item.redactions[0].original == "555 0142"


def test_cue_words_are_marked_for_the_highlighter(bait, call):
    item = draft.build(
        bait, call, [], flag("the-hush", 1, call, cues=["do not tell anyone"]), GUIDE["the-hush"], 1
    )
    marked = [w.text for card in item.spec.replay_cards for w in card.words if w.cue]
    assert marked == ["do", "not", "tell", "anyone"]


def test_replay_words_line_up_with_the_replayed_audio(bait, call):
    item = draft.build(bait, call, [], flag("the-hush", 1, call), GUIDE["the-hush"], 1)
    replay = next(b for b in item.spec.beats if b.name == "replay")
    first_play = next(w for card in item.spec.cards if card.in_quote for w in card.words)
    first_replay = item.spec.replay_cards[0].words[0]
    # In the play beat the word sits this far after the quote's audio starts...
    offset_in_quote = first_play.start - (item.quote_start - item.play_start)
    # ...and in the replay beat it must sit the same distance after the audio restarts.
    assert first_replay.start == pytest.approx(replay.start + draft.REPLAY_LEAD + offset_in_quote)
    assert replay.start <= first_replay.start <= replay.end


def test_context_stops_at_a_line_flagged_for_another_tactic(bait, call):
    item = draft.build(
        bait, call, [], flag("the-safe-account", 2, call), GUIDE["the-safe-account"], 1,
        avoid=frozenset({1}),
    )  # fmt: skip
    shown = " ".join(w.text for card in item.spec.cards for w in card.words)
    assert shown == "Now move your savings into a secure government account"


def test_choose_prefers_teachable_flags_and_different_tactics(call):
    flags = [
        flag("the-hush", 1, call, teachability=5),
        flag("the-safe-account", 2, call, teachability=3),
        flag("the-hush", 0, call, teachability=4),
    ]
    assert [f.id for f in draft.choose(flags, 2)] == ["the-hush@1", "the-safe-account@2"]
    assert len(draft.choose(flags, 5)) == 3
