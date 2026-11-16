"""Drafting: turn a flag into a clip in the Flag on the Play format.

A clip has five beats:

    play     the scammer's real line, with a little context before it
    flag     freeze, whistle, and a stamp that names the tactic
    replay   the key line again, with the manipulative words highlighted
    counter  what to do instead, copied from the Field Guide card
    credit   whose recording this is

This module only does arithmetic on the transcript. It touches no audio, so
it is fast and easy to test.
"""

from __future__ import annotations

import re

from .fieldguide import Tactic
from .models import (
    Bait,
    Beat,
    CaptionCard,
    ClipSpec,
    ClipWord,
    Draft,
    Flag,
    Redaction,
    Segment,
    Speaker,
    TacticCard,
    Transcript,
)
from .redact import masked_words

MAX_PLAY = 24.0  # seconds of the call before the freeze, context included
MAX_QUOTE = 16.0  # seconds of the key line that gets replayed
MAX_CONTEXT_SEGMENTS = 3
LEAD_IN = 0.15  # breathing room before the first word
TAIL = 0.30  # and after the last
FLAG_HOLD = 2.8
REPLAY_LEAD = 0.5
CREDIT_HOLD = 2.8
CARD_WORDS = 12  # most words shown on screen at once


def choose(flags: list[Flag], max_clips: int) -> list[Flag]:
    """Pick the flags worth drafting: the most teachable, covering different tactics first."""
    ranked = sorted(flags, key=lambda f: (-f.teachability, f.start))
    chosen: list[Flag] = []

    def overlaps(flag: Flag) -> bool:
        return any(flag.start < c.end and c.start < flag.end for c in chosen)

    for flag in ranked:  # first pass: one clip per tactic
        if (
            len(chosen) < max_clips
            and not overlaps(flag)
            and flag.tactic not in {c.tactic for c in chosen}
        ):
            chosen.append(flag)
    for flag in ranked:  # second pass: fill any remaining room
        if len(chosen) < max_clips and flag not in chosen and not overlaps(flag):
            chosen.append(flag)
    return sorted(chosen, key=lambda f: f.start)


def _plain(text: str) -> str:
    return re.sub(r"[^a-z0-9\[\]]+", "", text.lower())


def _mark_cues(words: list[ClipWord], cues: list[str]) -> None:
    """Mark the words that make up each cue phrase, so the stage can highlight them."""
    plain = [_plain(w.text) for w in words]
    for cue in cues:
        target = [p for p in (_plain(part) for part in cue.replace("-", " ").split()) if p]
        if not target:
            continue
        for i in range(len(plain) - len(target) + 1):
            if plain[i : i + len(target)] == target:
                for word in words[i : i + len(target)]:
                    word.cue = True


def _clip_words(segment: Segment, redactions: list[Redaction], offset: float) -> list[ClipWord]:
    """A segment's words with clip-relative timings. Redacted runs become one masked word."""
    mine = {r.first_word: r for r in redactions if r.segment == segment.id}
    out: list[ClipWord] = []
    index = 0
    for text, redacted in masked_words(segment, redactions):
        if redacted:
            run = mine[index]
            first, last = segment.words[run.first_word], segment.words[run.last_word]
            out.append(
                ClipWord(text=run.kind, start=first.start - offset, end=last.end - offset,
                         redacted=True)
            )  # fmt: skip
            index = run.last_word + 1
        else:
            word = segment.words[index]
            out.append(ClipWord(text=text, start=word.start - offset, end=word.end - offset))
            index += 1
    return out


def _cards(words: list[ClipWord], speaker: Speaker, in_quote: bool) -> list[CaptionCard]:
    """Break a segment into cards small enough to read at a glance."""
    cards: list[CaptionCard] = []
    current: list[ClipWord] = []
    for position, word in enumerate(words):
        left = len(words) - position  # never strand one or two words on a card of their own
        if current and left >= 3:
            pause = word.start - current[-1].end
            sentence_end = current[-1].text[-1:] in ".?!"
            if (
                len(current) >= CARD_WORDS
                or (len(current) >= 5 and sentence_end)
                or (len(current) >= 3 and pause > 0.7)
            ):
                cards.append(CaptionCard(speaker=speaker, in_quote=in_quote, words=current))
                current = []
        current.append(word)
    if current:
        cards.append(CaptionCard(speaker=speaker, in_quote=in_quote, words=current))
    return cards


def build(
    bait: Bait,
    transcript: Transcript,
    redactions: list[Redaction],
    flag: Flag,
    tactic: Tactic,
    number: int,
    speakers: dict[int, Speaker] | None = None,
    avoid: frozenset[int] = frozenset(),
) -> Draft:
    """Build the draft clip for one flag.

    ``avoid`` holds the lines flagged for a *different* tactic. The context
    before the quote never reaches back into them, so a viewer asked to spot
    the red flag is not shown two different ones.
    """
    speakers = speakers or {}
    by_id = {s.id: s for s in transcript.segments}
    quote_segments = [by_id[i] for i in range(flag.first_segment, flag.last_segment + 1)]
    if quote_segments[-1].end - quote_segments[0].start > MAX_QUOTE:
        quote_segments = quote_segments[:1]
    quote_start = quote_segments[0].start
    quote_end = min(quote_segments[-1].end, quote_start + MAX_QUOTE)

    # Walk back for context, while it stays short and continuous.
    window = list(quote_segments)
    for _ in range(MAX_CONTEXT_SEGMENTS):
        before = by_id.get(window[0].id - 1)
        if (
            before is None
            or before.id in avoid
            or quote_end - before.start > MAX_PLAY
            or window[0].start - before.end > 4.0
        ):
            break
        window.insert(0, before)

    play_start = max(window[0].start - LEAD_IN, 0.0)
    play_end = min(quote_end + TAIL, transcript.duration)
    play_length = play_end - play_start
    quote_audio_start = max(quote_start - LEAD_IN, play_start)
    quote_length = play_end - quote_audio_start

    counter_words = len(tactic.counter_move.split())
    counter_hold = min(max(2.5 + 0.36 * counter_words, 5.5), 9.5)

    beats: list[Beat] = []
    clock = 0.0
    for name, length in (
        ("play", play_length),
        ("flag", FLAG_HOLD),
        ("replay", REPLAY_LEAD + quote_length),
        ("counter", counter_hold),
        ("credit", CREDIT_HOLD),
    ):
        beats.append(Beat(name=name, start=round(clock, 3), end=round(clock + length, 3)))
        clock += length
    replay_beat = beats[2]

    quote_ids = {s.id for s in quote_segments}
    cards: list[CaptionCard] = []
    replay_cards: list[CaptionCard] = []
    # In the replay the quote starts REPLAY_LEAD after the beat does.
    replay_offset = quote_audio_start - (replay_beat.start + REPLAY_LEAD)
    for segment in window:
        speaker = speakers.get(segment.id, segment.speaker)
        in_quote = segment.id in quote_ids
        words = [w for w in _clip_words(segment, redactions, play_start) if w.start < play_length]
        if in_quote:
            _mark_cues(words, flag.cues)
            again = [
                w.model_copy(update={"start": w.start + play_start - replay_offset,
                                     "end": w.end + play_start - replay_offset})
                for w in words
            ]  # fmt: skip
            replay_cards += _cards(again, speaker, True)
        cards += _cards(words, speaker, in_quote)

    clip_id = f"{number:02d}-{tactic.id}"
    spec = ClipSpec(
        id=clip_id,
        bait_id=bait.id,
        kind=bait.kind,
        credit=bait.credit,
        call_time=round(play_start, 2),
        call_duration=bait.duration,
        duration=round(clock, 3),
        beats=beats,
        cards=cards,
        replay_cards=replay_cards,
        tactic=TacticCard(
            id=tactic.id,
            name=tactic.name,
            plain_label=tactic.plain_label,
            counter_move=tactic.counter_move,
            source_title=tactic.source.title,
        ),
    )
    return Draft(
        spec=spec,
        flag=flag,
        play_start=round(play_start, 3),
        play_end=round(play_end, 3),
        quote_start=round(quote_audio_start, 3),
        quote_end=round(play_end, 3),
        redactions=[r for r in redactions if r.start < play_end and r.end > play_start],
        card_status=tactic.status,
    )
