"""The arithmetic behind `baitreel eval`, checked against numbers worked out by hand."""

import pytest

from baitreel.scoring import (
    Span,
    Tally,
    cohens_kappa,
    coverage,
    line_labels,
    outcome,
    score_flags,
    unmarked_bleeps,
)


def test_kappa_matches_the_textbook_example():
    # Two readers, 50 items: 20 both yes, 5 yes/no, 10 no/yes, 15 both no.
    # Observed agreement 0.7, chance agreement 0.5, so kappa is 0.4.
    a = ["yes"] * 25 + ["no"] * 25
    b = ["yes"] * 20 + ["no"] * 5 + ["yes"] * 10 + ["no"] * 15
    assert cohens_kappa(a, b) == pytest.approx(0.4)


def test_kappa_is_one_for_perfect_agreement_and_undefined_for_a_single_label():
    assert cohens_kappa(["a", "b", "none"], ["a", "b", "none"]) == pytest.approx(1.0)
    assert cohens_kappa(["none"] * 4, ["none"] * 4) is None
    assert cohens_kappa([], []) is None


def test_a_flag_is_correct_only_with_the_same_tactic_at_the_same_time():
    reference = [Span("the-hush", 10.0, 14.0), Span("the-badge", 30.0, 33.0)]
    spotted = [
        Span("the-hush", 12.0, 16.0),  # right tactic, overlapping: correct
        Span("the-scare", 30.0, 33.0),  # right time, wrong tactic: a false alarm
        Span("the-hush", 50.0, 52.0),  # nothing there: a false alarm
    ]
    score = score_flags(spotted, reference)
    hush, badge = score.by_tactic["the-hush"], score.by_tactic["the-badge"]
    assert (hush.spotted, hush.correct, hush.reference, hush.found) == (2, 1, 1, 1)
    assert hush.precision == 0.5 and hush.recall == 1.0
    assert hush.f1 == pytest.approx(2 / 3)
    assert (badge.reference, badge.found, badge.recall) == (1, 0, 0.0)
    assert badge.precision is None  # nothing spotted, so precision is undefined
    assert [s.label for s in score.misses] == ["the-badge"]
    assert {s.start for s in score.false_alarms} == {30.0, 50.0}


def test_one_moment_split_across_two_lines_is_not_punished_twice():
    reference = [Span("the-leash", 10.0, 20.0)]
    spotted = [Span("the-leash", 10.0, 14.0), Span("the-leash", 14.5, 20.0)]
    overall = score_flags(spotted, reference).overall
    assert (overall.precision, overall.recall) == (1.0, 1.0)


def test_flags_that_only_touch_do_not_match():
    score = score_flags([Span("the-hush", 5.0, 10.0)], [Span("the-hush", 10.0, 12.0)])
    assert score.overall.correct == 0


def test_tallies_pool_across_calls():
    pooled = Tally(2, 1, 3, 2) + Tally(1, 1, 1, 0)
    assert (pooled.precision, pooled.recall) == (2 / 3, 2 / 4)


def test_each_line_gets_the_tactic_that_covers_most_of_it():
    lines = [(0.0, 4.0), (4.5, 9.0), (9.5, 12.0)]
    spans = [
        Span("the-hush", 1.0, 3.5),  # most of line 0
        Span("the-badge", 3.8, 5.0),  # brushes lines 0 and 1, covers neither
        Span("the-scare", 9.6, 10.0),  # a short label inside line 2 still counts
    ]
    assert line_labels(spans, lines) == ["the-hush", "none", "the-scare"]


def test_redaction_coverage_and_outcomes():
    detail = Span("number", 10.0, 12.0)
    assert coverage(detail, [Span("number", 9.9, 12.2)]) == 1.0
    # Two bleeps that overlap each other are not counted twice.
    assert coverage(detail, [Span("n", 10.0, 11.0), Span("n", 10.5, 11.5)]) == pytest.approx(0.75)
    assert outcome(0.9) == "covered"
    assert outcome(0.5) == "partly"  # half a phone number is still a phone number
    assert outcome(0.0) == "missed"


def test_bleeps_with_no_hand_marked_detail_are_counted():
    bleeps = [Span("name", 1.0, 2.0), Span("name", 5.0, 6.0)]
    assert unmarked_bleeps(bleeps, [Span("name", 1.2, 1.8)]) == 1
