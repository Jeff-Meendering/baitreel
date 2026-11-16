"""Audio helpers and the pause-based line splitter."""

import numpy as np

from baitreel import audio
from baitreel.models import Word
from baitreel.transcribe import into_lines


def voice(seconds: float) -> np.ndarray:
    """Noise standing in for speech."""
    return np.random.default_rng(0).normal(0, 0.2, int(seconds * audio.SR)).astype(np.float32)


def test_bleep_replaces_the_original_sound_completely():
    original = voice(2.0)
    bleeped = audio.bleep(original, [(0.5, 1.0)])
    a, b = int(0.5 * audio.SR), int(1.0 * audio.SR)
    np.testing.assert_array_equal(bleeped[:a], original[:a])
    np.testing.assert_array_equal(bleeped[b:], original[b:])
    # Inside the span nothing of the original remains: it is exactly the tone.
    np.testing.assert_allclose(bleeped[a:b], audio.tone(1000.0, 0.5)[: b - a])
    assert abs(np.corrcoef(bleeped[a:b], original[a:b])[0, 1]) < 0.05


def test_bleep_spans_outside_the_clip_are_ignored():
    original = voice(1.0)
    np.testing.assert_array_equal(audio.bleep(original, [(-2.0, -1.0), (5.0, 6.0)]), original)


def test_silences_are_found_between_speech():
    samples = np.concatenate([voice(1.0), audio.silence(0.6), voice(1.0)])
    (quiet,) = audio.silences(samples, audio.SR)
    assert 0.95 < quiet[0] < 1.1 and 1.5 < quiet[1] < 1.65


def test_envelope_has_one_value_per_frame():
    levels = audio.envelope(voice(2.0), fps=30)
    assert len(levels) == 60
    assert all(0.0 <= level <= 1.0 for level in levels)


def words(*items: tuple[str, float, float]) -> list[Word]:
    return [Word(text=t, start=s, end=e) for t, s, e in items]


def test_a_long_gap_starts_a_new_line():
    lines = into_lines(words(("Hello", 0.0, 0.4), ("there.", 0.5, 0.9), ("Yes?", 2.0, 2.4)))
    assert [line.text for line in lines] == ["Hello there.", "Yes?"]


def test_a_measured_silence_starts_a_new_line_even_when_word_timings_hide_it():
    # The model stretched "there." to end at 1.9, hiding the pause. The audio knows better.
    stretched = words(("Hello", 0.0, 0.4), ("there.", 0.5, 1.9), ("Yes?", 2.0, 2.4))
    assert len(into_lines(stretched)) == 1
    assert len(into_lines(stretched, quiet=[(1.0, 1.9)])) == 2


def test_lines_never_run_too_long():
    many = words(*[(f"w{i}", i * 0.5, i * 0.5 + 0.45) for i in range(80)])
    assert max(line.end - line.start for line in into_lines(many)) <= 15.5
