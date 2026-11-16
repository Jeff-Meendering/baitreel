"""An end-to-end render of a tiny clip. Needs ffmpeg and headless Chromium, so it is marked slow."""

import json
import shutil
import subprocess

import pytest

from baitreel import audio, draft, render
from baitreel.fieldguide import guide
from baitreel.models import Flag
from baitreel.redact import find_redactions

from .conftest import make_transcript

pytestmark = pytest.mark.slow


def chromium_available() -> bool:
    try:
        with render.Renderer():
            return True
    except Exception:
        return False


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not installed")
def test_render_a_short_clip(tmp_path, bait):
    if not chromium_available():
        pytest.skip("headless Chromium is not installed")

    # A stand-in recording: eight seconds of tone is enough to exercise the audio path.
    recording = audio.write_wav(tmp_path / "call.wav", audio.tone(220, 8.0, 0.3))
    call = make_transcript("My number is 555 0142", "Do not tell anyone about this call")
    segment = call.segments[1]
    flag = Flag(
        id="the-hush@1", tactic="the-hush", first_segment=1, last_segment=1,
        start=segment.start, end=segment.end, quote=segment.text,
        cues=["Do not tell anyone"], spotter="test",
    )  # fmt: skip
    item = draft.build(
        bait, call, find_redactions(call.segments, use_names=False), flag, guide()["the-hush"], 1
    )

    with render.Renderer() as renderer:
        video = render.render_draft(renderer, recording, item, tmp_path / "catch")
        still = renderer.still(item, item.spec.beats[1].start + 1.0, tmp_path / "flag.png")

    probe = json.loads(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video)],
            capture_output=True, text=True, check=True,
        ).stdout
    )  # fmt: skip
    kinds = {stream["codec_type"]: stream for stream in probe["streams"]}
    assert kinds["video"]["width"] == 1080 and kinds["video"]["height"] == 1920
    assert "audio" in kinds
    assert float(probe["format"]["duration"]) == pytest.approx(item.spec.duration, abs=0.3)
    assert len(item.spec.envelope) == int(item.spec.duration * item.spec.fps)
    assert still.stat().st_size > 20_000
