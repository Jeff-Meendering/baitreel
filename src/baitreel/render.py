"""Rendering: build a clip's soundtrack, then film the stage page frame by frame.

The picture comes from ``stage/index.html``, a web page that draws the clip
for any moment in time. A headless browser steps through the clip, one frame
at a time, and ffmpeg joins the frames to the soundtrack. Because the page is
the single source of the picture, a preview in a browser and the exported
file cannot disagree.
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable
from pathlib import Path

import numpy as np

from . import audio
from .draft import REPLAY_LEAD
from .models import Draft

STAGE = Path(__file__).parent / "stage" / "index.html"


def stage_fingerprint() -> str:
    """A short hash of the stage page. If the look changes, old renders are out of date."""
    digest = hashlib.sha256()
    for name in ("index.html", "stage.css", "stage.js"):
        digest.update((STAGE.parent / name).read_bytes())
    return digest.hexdigest()[:12]


def soundtrack(recording: Path, draft: Draft) -> np.ndarray:
    """Assemble the clip's audio: play, whistle, replay, then quiet for the reading beats.

    Redacted spans are replaced with a tone before anything else happens, so
    no later step ever handles the original words.
    """
    spec = draft.spec
    beats = {beat.name: beat for beat in spec.beats}
    play = audio.decode(recording, draft.play_start, draft.play_end - draft.play_start)
    play = audio.normalize(play)
    play = audio.bleep(
        play, [(r.start - draft.play_start, r.end - draft.play_start) for r in draft.redactions]
    )
    quote = play[int((draft.quote_start - draft.play_start) * audio.SR) :]

    track = audio.silence(spec.duration)

    def place(samples: np.ndarray, at: float) -> None:
        start = int(at * audio.SR)
        samples = samples[: max(len(track) - start, 0)]
        track[start : start + len(samples)] += samples

    place(play, 0.0)
    place(audio.whistle(), beats["flag"].start + 0.05)
    place(quote, beats["replay"].start + REPLAY_LEAD)
    # Two soft rising notes mark the answer.
    place(audio.tone(660, 0.16, 0.10), beats["counter"].start + 0.05)
    place(audio.tone(880, 0.28, 0.10), beats["counter"].start + 0.22)
    return track


class Renderer:
    """Keeps one headless browser open while several clips are rendered."""

    def __enter__(self) -> Renderer:
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch()
        except Exception as error:
            self._playwright.stop()
            raise RuntimeError(
                "Could not start the headless browser. Run: uv run playwright install chromium"
            ) from error
        return self

    def __exit__(self, *_exc) -> None:
        self._browser.close()
        self._playwright.stop()

    def still(self, draft: Draft, at: float, out: Path) -> Path:
        """Save one frame as a PNG. Handy for tests and thumbnails."""
        page = self._open(draft)
        page.evaluate("t => window.stage.seek(t)", at)
        out.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out))
        page.close()
        return out

    def _open(self, draft: Draft):
        spec = draft.spec
        page = self._browser.new_page(viewport={"width": spec.width, "height": spec.height})
        page.goto(STAGE.as_uri())
        page.evaluate("spec => window.stage.load(spec)", spec.model_dump(mode="json"))
        return page

    def render(
        self,
        draft: Draft,
        wav: Path,
        out: Path,
        on_progress: Callable[[float], None] | None = None,
    ) -> Path:
        spec = draft.spec
        frames = int(round(spec.duration * spec.fps))
        out.parent.mkdir(parents=True, exist_ok=True)
        page = self._open(draft)
        encoder = subprocess.Popen(
            [audio.require("ffmpeg"), "-y", "-v", "error",
             "-f", "image2pipe", "-framerate", str(spec.fps), "-c:v", "mjpeg", "-i", "-",
             "-i", str(wav),
             "-c:v", "libx264", "-preset", "medium", "-crf", "19",
             "-pix_fmt", "yuv420p", "-color_range", "tv",
             "-c:a", "aac", "-b:a", "160k",
             "-movflags", "+faststart", "-shortest", str(out)],
            stdin=subprocess.PIPE, stderr=subprocess.PIPE,
        )  # fmt: skip
        try:
            last_key, picture = None, b""
            for frame in range(frames):
                key = page.evaluate("t => window.stage.seek(t)", frame / spec.fps)
                if key != last_key:  # the picture changed, so take a new screenshot
                    picture = page.screenshot(type="jpeg", quality=93)
                    last_key = key
                encoder.stdin.write(picture)
                if on_progress and frame % 15 == 0:
                    on_progress(frame / frames)
            encoder.stdin.close()
            errors = encoder.stderr.read().decode(errors="replace")
            if encoder.wait() != 0:
                raise RuntimeError(f"ffmpeg could not encode the clip:\n{errors}")
        finally:
            page.close()
            if encoder.poll() is None:
                encoder.kill()
        if on_progress:
            on_progress(1.0)
        return out


def render_draft(
    renderer: Renderer,
    recording: Path,
    draft: Draft,
    folder: Path,
    on_progress: Callable[[float], None] | None = None,
) -> Path:
    """Render one draft into its catch folder. Returns the path of the video."""
    track = soundtrack(recording, draft)
    draft.spec.envelope = audio.envelope(track, draft.spec.fps)
    draft.stage = stage_fingerprint()
    wav = audio.write_wav(folder / "audio.wav", track)
    return renderer.render(draft, wav, folder / "clip.mp4", on_progress)
