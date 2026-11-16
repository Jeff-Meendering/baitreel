"""Find personal details in a transcript so they can be bleeped and masked.

Detection is layered, local and deliberately cautious. It prefers to bleep
something harmless over letting a real detail through:

1. **Code runs**: numbers read aloud ("four one five..."), long digit strings
   and things spelled out letter by letter. Covers phone, card, account and
   Social Security numbers, verification codes and spelled names.
2. **Patterns**: email addresses, web addresses, street addresses, and dates
   mentioned near words like "born".
3. **Names**: people's names found three ways: by a small local language
   model (spaCy), by context ("Mrs. ...", "my name is ..."), and by repetition
   (a name found once is redacted everywhere else it is said).

Scammers' details are redacted too. Spoofed phone numbers and "mule" bank
accounts usually belong to other victims.

Known limit: this works on the transcript. If the transcriber mishears a name
as an ordinary word, no rule here will see it. That is why a person must
listen to every clip in full before approving it.
"""

from __future__ import annotations

import re
from functools import cache

from .models import Redaction, RedactionKind, Segment

# Time added around a redacted span, because word timings are approximate.
PAD_BEFORE = 0.12
PAD_AFTER = 0.18

DIGIT_WORDS = {"zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"}
# Count toward a run only when surrounded by stronger evidence.
WEAK = {"a", "i", "o", "oh", "double", "triple", "dash", "hyphen"}
# A lone number followed by one of these is a quantity, not an identifier.
UNITS = {
    "dollar", "dollars", "bucks", "cents", "percent", "second", "seconds", "minute", "minutes",
    "hour", "hours", "day", "days", "week", "weeks", "month", "months", "year", "years",
    "times", "am", "pm", "o'clock", "each", "cards", "digit", "digits",
}  # fmt: skip
# Forms of address that the name finder sometimes mistakes for names.
NOT_NAMES = {
    "ma'am", "maam", "sir", "madam", "officer", "agent", "mister", "mr", "mrs", "ms", "miss",
    "dear", "honey", "grandma", "grandpa", "god", "lord", "jesus",
}  # fmt: skip

TITLES = {
    "mr", "mrs", "ms", "miss", "mister", "dr", "doctor", "officer", "agent", "inspector",
    "detective", "sergeant", "professor", "aunt", "uncle",
}  # fmt: skip
# "This is Daniel", "my name is Daniel Hart". The name part must be capitalized.
INTRODUCTION = re.compile(
    r"\b(?:[Mm]y name is|[Nn]ame is|[Tt]his is|I am|I'm|[Ss]peaking (?:with|to)|[Cc]all me|"
    r"[Nn]amed|[Aa]sk for)\s+([A-Z][a-z']+(?:\s[A-Z][a-z']+){0,2})"
)
# Organizations are not personal details, and naming the one being impersonated
# is part of the lesson. These are never treated as people's names.
ORGANIZATIONS = {
    "amazon", "microsoft", "apple", "google", "paypal", "windows", "medicare", "medicaid",
    "walmart", "target", "norton", "mcafee", "visa", "mastercard", "chase", "citibank",
    "netflix", "facebook", "irs", "fbi", "ftc", "dea", "treasury", "federal", "social",
    "security", "bank", "geek", "squad", "customs", "border", "xfinity", "comcast", "verizon",
}  # fmt: skip

EMAIL = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.]+|\b[\w.]+ at [\w-]+ dot (?:com|net|org|edu|gov)\b", re.I
)
WEB = re.compile(
    r"\b(?:https?://|www\.)\S+"
    r"|\b[\w-]+\.(?:com|net|org|info|xyz|online|site|biz|co|io|us|top|live|support)\b(?:/\S*)?"
    r"|\b[\w-]+ dot (?:com|net|org|info|xyz|online|site|biz|co|io|us)\b",
    re.I,
)
ADDRESS = re.compile(
    r"\b\d{1,6}(?:\s+[A-Za-z][\w.']*){1,4}?\s+"
    r"(?:street|st|avenue|ave|road|rd|drive|dr|lane|ln|boulevard|blvd|court|ct|way|place|pl|"
    r"circle|terrace|highway|hwy)\b\.?",
    re.I,
)
MONTHS = (
    r"(?:january|february|march|april|may|june|july|august|september|october|november|december)"
)
DATE = re.compile(
    rf"\b{MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?|\b\d{{1,2}}/\d{{1,2}}/\d{{2,4}}\b",
    re.I,
)
BIRTH = re.compile(r"\b(born|birth|birthday|date of birth|d\.?o\.?b)\b", re.I)


def _core(text: str) -> str:
    """A word without surrounding punctuation, keeping $ and % as signals."""
    return re.sub(r"^[^\w$%]+|[^\w$%]+$", "", text)


def _classify(text: str) -> tuple[str, int, int]:
    """Return (strength, digits, letters) for one word.

    strength is "strong", "weak" or "" (not part of a code run).
    """
    core = _core(text)
    low = core.lower()
    if not core or core.startswith("$") or core.endswith("%"):
        return "", 0, 0
    if re.fullmatch(r"\d{1,2}:\d{2}", core):  # a time of day
        return "", 0, 0
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", core):  # 1,500 is an amount
        return "", 0, 0
    if re.fullmatch(r"(\w[-.]){2,}\w", core):  # E-D-N-A or 4-7-1-9
        return "strong", sum(c.isdigit() for c in core), sum(c.isalpha() for c in core)
    if any(c.isdigit() for c in core):
        return "strong", sum(c.isdigit() for c in core), 0
    if low in DIGIT_WORDS:
        return "strong", 1, 0
    if low in WEAK:
        return "weak", 1 if low in {"o", "oh"} else 0, 1 if low in {"a", "i"} else 0
    if len(core) == 1 and core.isalpha():
        return "strong", 0, 1
    return "", 0, 0


def _code_runs(segment: Segment) -> list[tuple[int, int, RedactionKind]]:
    """Runs of spoken digits and spelled-out letters."""
    marks = [_classify(w.text) for w in segment.words]
    found: list[tuple[int, int, RedactionKind]] = []
    i = 0
    while i < len(marks):
        if not marks[i][0]:
            i += 1
            continue
        j = i
        while j + 1 < len(marks) and marks[j + 1][0]:
            j += 1
        start_of_run, end_of_run = i, j
        first, last = i, j
        while first <= last and marks[first][0] == "weak":
            first += 1
        while last >= first and marks[last][0] == "weak":
            last -= 1
        i = j + 1
        if first > last:
            continue
        digits = sum(m[1] for m in marks[first : last + 1])
        letters = sum(m[2] for m in marks[first : last + 1])
        count = last - first + 1
        if count == 1:
            core = _core(segment.words[first].text)
            following = (
                _core(segment.words[first + 1].text).lower() if first + 1 < len(marks) else ""
            )
            if following in UNITS:
                continue
            if re.fullmatch(r"(19|20)\d\d", core):  # a year
                continue
        kind: RedactionKind | None = None
        if digits >= 4:
            kind = "number"
        elif digits == 0 and letters >= 3:
            kind = "spelled"
        elif digits + letters >= 4 and count >= 3:
            kind = "number"
        if kind:
            # Once a run qualifies, take the weak words at its edges too: the
            # "A" that ends E-D-N-A, or the "oh" that starts a phone number.
            found.append((start_of_run, end_of_run, kind))
    return found


def _layout(segment: Segment) -> tuple[str, list[tuple[int, int]]]:
    """The segment as one string, plus each word's character span in it."""
    spans: list[tuple[int, int]] = []
    position = 0
    for word in segment.words:
        spans.append((position, position + len(word.text)))
        position += len(word.text) + 1
    return segment.text, spans


def _words_in(spans: list[tuple[int, int]], start: int, end: int) -> tuple[int, int] | None:
    hit = [i for i, (a, b) in enumerate(spans) if a < end and b > start]
    return (hit[0], hit[-1]) if hit else None


@cache
def _name_finder():
    import spacy

    try:
        return spacy.load("en_core_web_sm", disable=["parser", "lemmatizer"])
    except OSError as error:  # pragma: no cover - depends on the install
        raise RuntimeError("The spaCy model en_core_web_sm is missing. Run: uv sync") from error


@cache
def _domain_words() -> frozenset[str]:
    """Words the Field Guide itself uses, such as "gift" and "card".

    The name finder sometimes mistakes a capitalized "Gift" for a person.
    Words that describe scam tactics are never treated as names.
    """
    from .fieldguide import guide

    text = " ".join(
        " ".join([t.name, t.plain_label, t.description, *t.sounds_like]) for t in guide().values()
    )
    return frozenset(re.findall(r"[a-z']+", text.lower()))


def _is_name_word(text: str) -> bool:
    core = _core(text)
    low = core.lower()
    return (
        len(core) >= 2
        and core[0].isupper()
        and core.replace("'", "").replace("-", "").isalpha()
        and low not in NOT_NAMES
        and low not in TITLES
        and low not in ORGANIZATIONS
        and low not in _domain_words()
    )


def _trim(segment: Segment, first: int, last: int) -> tuple[int, int] | None:
    """Drop titles, forms of address and organization names from the edges of a name."""
    while first <= last and not _is_name_word(segment.words[first].text):
        first += 1
    while last >= first and not _is_name_word(segment.words[last].text):
        last -= 1
    return (first, last) if first <= last else None


def _names(segment: Segment, text: str, spans: list[tuple[int, int]], use_model: bool):
    """People's names in one segment, as (first word, last word) pairs."""
    # By context: the capitalized words after a title.
    for i, word in enumerate(segment.words):
        if _core(word.text).lower() in TITLES:
            j = i
            while (
                j + 1 < len(segment.words)
                and j - i < 3
                and _is_name_word(segment.words[j + 1].text)
            ):
                j += 1
                if segment.words[j].text[-1:] in ".?!,":  # the name ends with the sentence
                    break
            if j > i:
                yield i + 1, j
    # By context: "my name is ...", "this is ...".
    hits = [_words_in(spans, m.start(1), m.end(1)) for m in INTRODUCTION.finditer(text)]
    # By the language model.
    if use_model:
        hits += [
            _words_in(spans, entity.start_char, entity.end_char)
            for entity in _name_finder()(text).ents
            if entity.label_ == "PERSON"
        ]
    for hit in hits:
        if hit and (trimmed := _trim(segment, *hit)):
            yield trimmed


def find_redactions(
    segments: list[Segment],
    allow: list[str] | None = None,
    use_names: bool = True,
) -> list[Redaction]:
    """Find every personal detail in the transcript.

    ``allow`` lists words that are safe to keep, such as a scambaiter's
    invented persona name. It is matched word by word, ignoring case.
    ``use_names=False`` skips the spaCy model (the context rules still run).
    """
    allowed = {_core(w).lower() for phrase in (allow or []) for w in phrase.split()}
    found: dict[int, list[tuple[int, int, RedactionKind]]] = {s.id: [] for s in segments}
    known_names: set[str] = set()
    previous_text = ""
    for segment in segments:
        text, spans = _layout(segment)
        here = found[segment.id]
        here.extend(_code_runs(segment))
        for pattern, kind in ((EMAIL, "email"), (WEB, "web"), (ADDRESS, "address")):
            for match in pattern.finditer(text):
                if hit := _words_in(spans, match.start(), match.end()):
                    here.append((*hit, kind))
        if BIRTH.search(text) or BIRTH.search(previous_text):
            for match in DATE.finditer(text):
                if hit := _words_in(spans, match.start(), match.end()):
                    here.append((*hit, "date"))
        for first, last in _names(segment, text, spans, use_names):
            here.append((first, last, "name"))
            known_names.update(
                _core(w.text).lower()
                for w in segment.words[first : last + 1]
                if len(_core(w.text)) >= 3
            )
        previous_text = text

    out: list[Redaction] = []
    for segment in segments:
        here = found[segment.id]
        # By repetition: a name found anywhere is redacted everywhere.
        for i, word in enumerate(segment.words):
            if _core(word.text).lower() in known_names and _is_name_word(word.text):
                here.append((i, i, "name"))

        # Merge overlapping or touching runs, then drop anything allowed.
        merged: list[list] = []
        for first, last, kind in sorted(here):
            if merged and first <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], last)
            else:
                merged.append([first, last, kind])
        for first, last, kind in merged:
            words = segment.words[first : last + 1]
            if allowed and all(_core(w.text).lower() in allowed for w in words):
                continue
            out.append(
                Redaction(
                    segment=segment.id,
                    first_word=first,
                    last_word=last,
                    kind=kind,
                    start=round(max(words[0].start - PAD_BEFORE, 0.0), 3),
                    end=round(words[-1].end + PAD_AFTER, 3),
                    original=" ".join(w.text for w in words),
                )
            )
    return out


def masked_words(segment: Segment, redactions: list[Redaction]) -> list[tuple[str, bool]]:
    """Each word of a segment as (text, redacted). Redacted runs become one placeholder each."""
    mine = {r.first_word: r for r in redactions if r.segment == segment.id}
    out: list[tuple[str, bool]] = []
    i = 0
    while i < len(segment.words):
        if i in mine:
            out.append((f"[{mine[i].kind}]", True))
            i = mine[i].last_word + 1
        else:
            out.append((segment.words[i].text, False))
            i += 1
    return out


def masked_text(segment: Segment, redactions: list[Redaction]) -> str:
    """The segment's text with personal details replaced by placeholders.

    This is the only form of the transcript that is ever shown to a language
    model or written into a clip.
    """
    return " ".join(text for text, _ in masked_words(segment, redactions))
