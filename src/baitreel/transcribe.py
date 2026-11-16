"""Local transcription with word-level timings.

The recording is transcribed on this computer with faster-whisper. Audio is
never uploaded anywhere. The first run downloads the speech model once.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from . import audio
from .models import Segment, Transcript, Word

DEFAULT_MODEL = "small.en"
RATE = 16_000  # what the speech model expects


def transcribe(
    recording: Path,
    model_name: str = DEFAULT_MODEL,
    on_progress: Callable[[float], None] | None = None,
) -> Transcript:
    from faster_whisper import WhisperModel  # imported late: it is slow to load

    model = WhisperModel(model_name, device="auto", compute_type="int8")
    # Decoded by ffmpeg, so any format ffmpeg can read works here.
    samples = audio.decode(recording, rate=RATE)
    pieces, info = model.transcribe(
        samples,
        language="en" if model_name.endswith(".en") else None,
        word_timestamps=True,
        vad_filter=True,
        # Carrying context between windows keeps punctuation consistent, which
        # the line and caption splitting rely on.
        condition_on_previous_text=True,
    )

    words: list[Word] = []
    for piece in pieces:
        for w in piece.words or []:
            text = w.word.strip()
            if not text:
                continue
            if text.startswith("-") and words:
                # The model splits "six-digit" into "six" and "-digit". Rejoin them.
                words[-1] = Word(
                    text=words[-1].text + text, start=words[-1].start, end=round(w.end, 3)
                )
            else:
                words.append(Word(text=text, start=round(w.start, 3), end=round(w.end, 3)))
        if on_progress:
            on_progress(min(piece.end / info.duration, 1.0) if info.duration else 1.0)

    return Transcript(
        model=f"faster-whisper/{model_name}",
        language=info.language,
        duration=round(info.duration, 3),
        segments=into_lines(words, audio.silences(samples, RATE)),
    )


PAUSE = 0.55  # a gap this long between word timings starts a new line
LONG_SILENCE = 0.5  # so does a measured silence this long
LONG_LINE = 9.0  # after this many seconds, the next sentence end starts a new line
MAX_LINE = 15.0  # no line runs longer than this


def into_lines(words: list[Word], quiet: list[tuple[float, float]] | None = None) -> list[Segment]:
    """Group words into lines by the pauses between them.

    The speech model's own segments break mid-sentence and often run two
    speakers together. Pauses are a better guide: people usually pause when
    the turn changes, so a line is mostly one person saying one thing.

    ``quiet`` is the list of silences measured in the audio itself. Word
    timings alone tend to hide pauses, because the model stretches words to
    fill them.
    """
    gaps = sorted(((start + end) / 2, end - start) for start, end in quiet or [])

    def silence_between(before: Word, after: Word) -> float:
        """The longest measured silence between two neighbouring words, in seconds."""
        lo, hi = (before.start + before.end) / 2, (after.start + after.end) / 2
        return max((length for centre, length in gaps if lo < centre < hi), default=0.0)

    lines: list[list[Word]] = []
    for word in words:
        if lines:
            current = lines[-1]
            length = current[-1].end - current[0].start
            sentence_end = current[-1].text[-1:] in ".?!"
            silence = silence_between(current[-1], word)
            if not (
                word.start - current[-1].end >= PAUSE
                or silence >= LONG_SILENCE
                or (silence > 0 and sentence_end and length >= 2.5)
                or (length >= LONG_LINE and sentence_end)
                or length >= MAX_LINE
            ):
                current.append(word)
                continue
        lines.append([word])
    return [
        Segment(id=i, start=line[0].start, end=line[-1].end, words=line)
        for i, line in enumerate(lines)
    ]
