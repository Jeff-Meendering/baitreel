"""The human gate: nothing is exported without a named person, at a keyboard."""

import io
import json

import pytest
from rich.console import Console

from baitreel import draft, publish, review, workspace
from baitreel.fieldguide import guide
from baitreel.models import Flag
from baitreel.redact import find_redactions

from .conftest import make_transcript

GUIDE = guide()


@pytest.fixture
def catch(home, bait):
    """A rendered-looking draft in the working folder (the video is a stand-in file)."""
    call = make_transcript(
        "Should I call my neighbor Margaret on 555 0142 first",
        "No ma'am do not tell anyone about this call",
    )
    segment = call.segments[1]
    flag = Flag(
        id="the-hush@1", tactic="the-hush", first_segment=1, last_segment=1,
        start=segment.start, end=segment.end, quote=segment.text, spotter="test",
    )  # fmt: skip
    redactions = find_redactions(call.segments, use_names=False)
    item = draft.build(bait, call, redactions, flag, GUIDE["the-hush"], 1)
    folder = workspace.catch_dir(bait.id, item.spec.id)
    folder.mkdir(parents=True)
    (folder / "clip.mp4").write_bytes(b"not really a video")
    workspace.save(folder / "draft.json", item)
    return item


def test_publish_writes_a_complete_kit(home, bait, catch):
    kit = publish.publish(bait, catch, GUIDE["the-hush"], approved_by="Jo Reviewer")
    assert {p.name for p in kit.iterdir()} == {
        "clip.mp4",
        "caption.txt",
        "credits.txt",
        "passport.json",
    }
    passport = json.loads((kit / "passport.json").read_text())
    assert passport["approved_by"] == "Jo Reviewer"
    assert passport["credit"] == "Test Channel"
    assert passport["tactic"] == "the-hush"
    assert passport["redactions"] == {"number": 1}
    assert passport["rights"]["attested_by"] == "Tester"
    caption = (kit / "caption.txt").read_text()
    assert "Recording: Test Channel" in caption
    assert GUIDE["the-hush"].counter_move in caption
    assert "Scripted demo call" in caption  # demo clips say so


def test_a_kit_never_contains_the_redacted_details(home, bait, catch):
    kit = publish.publish(bait, catch, GUIDE["the-hush"], approved_by="Jo Reviewer")
    for name in ("caption.txt", "credits.txt", "passport.json"):
        text = (kit / name).read_text()
        assert "0142" not in text and "555" not in text


def test_publish_refuses_without_a_named_approver(home, bait, catch):
    with pytest.raises(ValueError, match="named person"):
        publish.publish(bait, catch, GUIDE["the-hush"], approved_by="  ")


def test_review_refuses_to_approve_without_a_person_at_a_keyboard(home, bait, catch, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("p\nk\n"))  # piped input, not a keyboard
    output = io.StringIO()
    kits = review.run(bait, [catch], Console(file=output, width=120))
    assert kits == []
    assert "needs a person at a keyboard" in output.getvalue()
    assert not workspace.export_dir(bait.id, catch.spec.id).exists()
    assert catch.status == "draft"


def test_a_rerun_clears_stale_drafts_but_never_keepers(home, bait, catch, monkeypatch):
    """Drafts from an earlier run should not linger in the review queue. Keepers must survive."""
    from baitreel import pipeline

    keeper = catch.model_copy(deep=True)
    keeper.spec.id = "02-the-leash"
    keeper.status = "keeper"
    folder = workspace.catch_dir(bait.id, keeper.spec.id)
    folder.mkdir(parents=True)
    workspace.save(folder / "draft.json", keeper)

    # A run that finds nothing: no transcript lines, so no flags and no drafts.
    workspace.save(
        workspace.bait_dir(bait.id) / "transcript.json",
        make_transcript("hello there").model_copy(update={"segments": []}),
    )
    result = pipeline.run(bait, spotter="keywords")

    assert result.drafts == []
    assert [d.spec.id for d in pipeline.load_drafts(bait.id)] == ["02-the-leash"]
