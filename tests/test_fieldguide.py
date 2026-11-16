"""The Field Guide is data that reaches viewers, so it is tested like code."""

import pytest

from baitreel.fieldguide import MAX_COUNTER_MOVE_WORDS, load_guide, problems
from baitreel.spot import cue_matches

GUIDE = load_guide()


def test_guide_loads_and_every_card_is_valid():
    assert len(GUIDE) >= 10
    for tactic in GUIDE.values():
        assert problems(tactic) == []


@pytest.mark.parametrize("tactic", GUIDE.values(), ids=lambda t: t.id)
def test_every_card_has_sourced_readable_advice(tactic):
    assert tactic.source.url.startswith("https://")
    assert tactic.source.title
    assert len(tactic.counter_move.split()) <= MAX_COUNTER_MOVE_WORDS


@pytest.mark.parametrize("tactic", GUIDE.values(), ids=lambda t: t.id)
def test_a_cards_own_examples_match_its_cues(tactic):
    """If a card's examples do not trigger its own cue patterns, the keyword spotter is blind to it."""
    matched = [example for example in tactic.sounds_like if cue_matches(tactic, example)]
    assert matched, f"no sounds_like example of {tactic.id} matches any of its cues"


def test_unkind_language_is_rejected():
    card = GUIDE["the-hush"].model_copy(
        update={"why_it_works": "Only gullible people keep secrets from their bank."}
    )
    assert any("gullible" in problem for problem in problems(card))


def test_overlong_advice_is_rejected():
    card = GUIDE["the-hush"].model_copy(update={"counter_move": "word " * 40})
    assert any("counter_move" in problem for problem in problems(card))
