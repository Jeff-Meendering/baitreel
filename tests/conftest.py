"""Shared helpers. Tests never need a real recording: they build small made-up transcripts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from baitreel.models import Bait, Rights, Segment, Transcript, Word


def make_line(line_id: int, start: float, text: str, pace: float = 0.3) -> Segment:
    """A transcript line whose words are evenly spaced, ``pace`` seconds apart."""
    words = [
        Word(
            text=word, start=round(start + i * pace, 3), end=round(start + i * pace + pace * 0.8, 3)
        )
        for i, word in enumerate(text.split())
    ]
    return Segment(id=line_id, start=words[0].start, end=words[-1].end, words=words)


def make_transcript(*texts: str, gap: float = 0.6) -> Transcript:
    """A transcript with one line per text, separated by short pauses."""
    lines: list[Segment] = []
    clock = 0.2
    for text in texts:
        lines.append(make_line(len(lines), clock, text))
        clock = lines[-1].end + gap
    return Transcript(model="test", language="en", duration=clock, segments=lines)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Point Baitreel's working folder at a temporary directory."""
    monkeypatch.setenv("BAITREEL_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


@pytest.fixture
def bait() -> Bait:
    now = datetime(2026, 11, 16, tzinfo=UTC)
    return Bait(
        id="test-bait-12345678",
        title="Test bait",
        kind="scripted-demo",
        credit="Test Channel",
        source_path="/nowhere/test.wav",
        source_name="test.wav",
        source_sha256="0" * 64,
        duration=120.0,
        rights=Rights(attested_by="Tester", statement="Test statement.", attested_at=now),
        created_at=now,
    )
