"""Redaction is the privacy promise. These tests pin down what must be caught and what must not."""

import pytest

from baitreel.redact import find_redactions, masked_text

from .conftest import make_line


def redact(text: str, **options) -> str:
    """Redact one line without the spaCy model, so the rules are tested on their own."""
    line = make_line(0, 0.0, text)
    options.setdefault("use_names", False)
    return masked_text(line, find_redactions([line], **options))


@pytest.mark.parametrize(
    "text, expected",
    [
        ("call me on 415-555-0142 tomorrow", "call me on [number] tomorrow"),
        ("the number is four one five five five five zero one four two", "the number is [number]"),
        ("it says 4 7 1 9 2 0 on my phone", "it says [number] on my phone"),
        ("my card ends in 4421 okay", "my card ends in [number] okay"),
        ("oh four seven one nine is the code", "[number] is the code"),
        ("the code is X 7 K 4 9 Q", "the code is [number]"),
        ("that is spelled S M I T H", "that is spelled [spelled]"),
        ("it is E-D-N-A", "it is [spelled]"),
        ("write to edna.p@example.com please", "write to [email] please"),
        ("go to secure-refund.com now", "go to [web] now"),
        ("visit refund help dot com now", "visit refund [web] now"),
        ("I live at 42 Maple Tree Lane in town", "I live at [address] in town"),
        ("I was born on March 3rd 1952 you see", "I was born on [date] you see"),
    ],
)
def test_personal_details_are_masked(text, expected):
    assert redact(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "you owe $1,500 in back taxes",
        "send 1,500 dollars today",
        "buy four gift cards for 500 dollars each",
        "it has been there since 1984",
        "call back before 5:30 today",
        "you have 10 minutes to decide",
        "press one to speak to an agent",
        "I have a cat and I like it",
        "your refund is due by March 3rd",
    ],
)
def test_ordinary_numbers_and_words_are_left_alone(text):
    """Amounts, years, times and deadlines carry the lesson. They are not personal details."""
    assert redact(text) == text


def test_names_are_found_by_context():
    assert (
        redact("am I speaking with Mrs. Edna Pruitt today")
        == "am I speaking with Mrs. [name] today"
    )
    assert redact("hello my name is Daniel Hart okay") == "hello my name is [name] okay"


def test_a_name_found_once_is_masked_everywhere():
    first = make_line(0, 0.0, "her name is Margaret you know")
    second = make_line(1, 5.0, "well Margaret used to work there")
    found = find_redactions([first, second], use_names=False)
    assert masked_text(second, found) == "well [name] used to work there"


def test_organizations_are_not_treated_as_names():
    """Naming who is being impersonated is part of the lesson."""
    assert redact("hello this is Microsoft calling") == "hello this is Microsoft calling"
    assert redact("this is Amazon support") == "this is Amazon support"


def test_allow_list_keeps_persona_names():
    text = "oh yes this is Edna speaking"
    assert redact(text) == "oh yes this is [name] speaking"
    assert redact(text, allow=["Edna"]) == text


def test_redaction_times_cover_the_words_with_padding():
    line = make_line(0, 10.0, "the pin is 4 7 1 9 okay")
    (found,) = find_redactions([line], use_names=False)
    assert found.kind == "number"
    assert found.start < line.words[3].start
    assert found.end > line.words[6].end
    assert found.original == "4 7 1 9"


def test_name_finder_model_catches_a_name_without_context():
    line = make_line(0, 0.0, "Yesterday I had lunch with Margaret Dolan near the park.")
    assert "[name]" in masked_text(line, find_redactions([line], use_names=True))
