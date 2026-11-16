"""Flag spotting: the keyword baseline, and the guard rails around model answers."""

from baitreel import demo
from baitreel.fieldguide import guide
from baitreel.spot import Line, keywords, local, validate

GUIDE = guide()


def test_keyword_spotter_finds_every_scripted_tactic():
    """The demo script names the tactic in each scammer line. That is the answer key."""
    script = demo.load_script()
    lines = [Line(i, i * 10.0, i * 10.0 + 8, turn.text) for i, turn in enumerate(script.turns)]
    found = {(flag.first_segment, flag.tactic) for flag in keywords.spot(lines, GUIDE)}
    for i, turn in enumerate(script.turns):
        if turn.tactic:
            assert (i, turn.tactic) in found, f"missed {turn.tactic} in: {turn.text}"


def test_keyword_spotter_ignores_small_talk():
    lines = [Line(0, 0.0, 3.0, "Hold on, dear, let me turn down the radio.")]
    assert keywords.spot(lines, GUIDE) == []


LINES = {
    4: Line(4, 40.0, 46.0, "Drive to the nearest pharmacy and buy four gift cards."),
    5: Line(5, 46.5, 49.0, "Then read me the numbers on the back."),
}


def test_validate_keeps_a_well_formed_flag():
    raw = [{"tactic": "the-gift-card-detour", "first_line": 4, "last_line": 5,
            "cue_phrases": ["buy four gift cards", "numbers on the back"],
            "why": "Asks for payment by gift card.", "teachability": 5}]  # fmt: skip
    (flag,) = validate(raw, LINES, GUIDE, "test")
    assert (flag.first_segment, flag.last_segment) == (4, 5)
    assert flag.cues == ["buy four gift cards", "numbers on the back"]
    assert flag.start == 40.0 and flag.end == 49.0


def test_validate_drops_invented_tactics_and_lines():
    raw = [
        {"tactic": "the-made-up-tactic", "first_line": 4, "last_line": 4},
        {"tactic": "the-hush", "first_line": 99, "last_line": 99},
        {"tactic": "the-hush"},
        {"tactic": "the-hush", "first_line": "four"},
    ]
    assert validate(raw, LINES, GUIDE, "test") == []


def test_validate_drops_cue_phrases_that_are_not_in_the_quote():
    raw = [{"tactic": "the-gift-card-detour", "first_line": 4, "last_line": 4,
            "cue_phrases": ["send me bitcoin immediately"], "teachability": 5}]  # fmt: skip
    (flag,) = validate(raw, LINES, GUIDE, "test")
    assert "send me bitcoin immediately" not in flag.cues
    assert flag.cues  # replaced by cue words that really are in the line


def test_validate_limits_a_quote_to_two_lines():
    lines = {i: Line(i, i * 5.0, i * 5.0 + 4, "do not tell anyone") for i in range(6)}
    raw = [{"tactic": "the-hush", "first_line": 0, "last_line": 5, "cue_phrases": []}]
    (flag,) = validate(raw, lines, GUIDE, "test")
    assert (flag.first_segment, flag.last_segment) == (0, 1)


def test_local_spotter_refuses_a_server_on_another_machine(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "https://models.example.com")
    ready, reason = local.available()
    assert not ready
    assert "not this computer" in reason


def test_local_spotter_refuses_cloud_hosted_models(monkeypatch):
    monkeypatch.setenv("BAITREEL_MODEL", "glm-5.3:cloud")

    class FakeResponse:
        def json(self):
            return {"models": [{"name": "glm-5.3:cloud", "remote_host": "https://ollama.com"}]}

    monkeypatch.setattr(local.httpx, "get", lambda *args, **kwargs: FakeResponse())
    ready, reason = local.available()
    assert not ready
    assert "cloud" in reason


def test_prompt_shows_the_model_only_masked_text():
    prompt = local.build_prompt([Line(0, 0.0, 2.0, "Her number is [number]")], GUIDE)
    assert "[0] Her number is [number]" in prompt
    assert prompt.rstrip().endswith("[number]")  # the transcript comes last, for caching


def test_a_changed_prompt_is_a_new_version(monkeypatch):
    """Saved runs are keyed by prompt version, so an edited prompt never reuses old flags."""
    before = local.prompt_version(GUIDE)
    monkeypatch.setattr(local, "TASK", local.TASK + "\n- One more rule.")
    assert local.prompt_version(GUIDE) != before


def test_runs_are_saved_and_reused(tmp_path):
    from baitreel import spot

    lines = [Line(0, 0.0, 3.0, "Do not tell anyone about this call.")]
    first = spot.run(tmp_path, lines, GUIDE, "keywords")
    assert first.name == "keywords" and first.flags[0].tactic == "the-hush"
    assert spot.run(tmp_path, lines, GUIDE, "keywords").created_at == first.created_at
    changed = [Line(0, 0.0, 3.0, "Do not tell [name] about this call.")]
    assert spot.run(tmp_path, changed, GUIDE, "keywords").id != first.id
    assert len(spot.saved_runs(tmp_path)) == 2
