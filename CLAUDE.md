# Notes for AI agents working on Baitreel

This file is read automatically by Claude Code sessions. It holds what a
fresh session needs to pick up a milestone without the history of earlier
chats. Humans are welcome to read it too.

## Start here

1. [VISION.md](VISION.md): what Baitreel is and what it refuses to do.
2. [ROADMAP.md](ROADMAP.md): the milestones. Find the one you were asked to build.
3. [README.md](README.md): how the tool is used and how the code is laid out.

## The four promises

Every change must keep these. If a task seems to need breaking one, stop and
ask the maintainer.

1. **A human approves everything.** Never add a flag, test hook or shortcut
   that approves or exports a clip without a person at a keyboard. Agents do
   not approve clips either. Test `publish.py` directly instead.
2. **It protects privacy.** Personal details never reach a prompt, a clip
   spec, a publish kit, a log or a commit. Transcripts shown to a model go
   through `redact.masked_text` first. Nothing is uploaded.
3. **It respects creators.** Local files only. No downloading from links.
   The credit is on every clip.
4. **It is accurate and kind.** Advice shown to viewers comes word for word
   from a Field Guide card with a source. No model writes advice. Nothing
   blames the people scammers target.

## How work is organized

- Each milestone is built in its own session, from a written brief. If you
  were handed a brief, build exactly that milestone and stop at an open pull
  request. Leave planning the next milestone to the maintainer.
- One milestone per branch and per pull request, into `main`.
- **Wait for the maintainer to merge** the previous pull request before
  starting the next milestone, and branch from the updated `main`. Do not
  merge pull requests yourself unless the maintainer tells you to.
- A pull request description says what it does, how to try it, the
  decisions and tradeoffs, and what was and was not verified. Be plain about
  what you could not check.
- Keep the docs true. If you change behavior, update README, ROADMAP or
  VISION in the same pull request.
- Never commit recordings, real transcripts, rendered media or secrets.
- Field Guide cards stay `status: draft` until the maintainer says a card
  is reviewed.

## Commands

```bash
uv sync                                  # install
uv run playwright install chromium       # once, for rendering
uv run baitreel doctor                   # what is missing?
uv run pytest                            # tests (about 20 seconds)
uv run ruff check . && uv run ruff format --check .
python3 scripts/check_repo_hygiene.py    # no media, no secrets
uv run baitreel guide --check            # validate the Field Guide
```

When you run the pipeline yourself, set `BAITREEL_HOME` to a temporary
folder so you do not write into the maintainer's `~/Baitreel`:

```bash
BAITREEL_HOME=/some/temp/folder uv run baitreel demo < /dev/null
```

With no keyboard attached, the demo drafts and renders clips and then stops
at review, which is the correct behavior. After it, `baitreel eval --no-browser`
scores the demo against the answer key in its script.

## Things learned the hard way

- **The local model is slow.** Gemma 4 12B on the maintainer's 16 GB M1 takes
  about two minutes per request. Never run two model jobs at once. "Thinking"
  must stay off (`"think": False`); with it on, a request took over ten
  minutes.
- **faster-whisper's own audio decoder is broken with the installed PyAV.**
  Audio is decoded with ffmpeg and passed in as an array. Keep it that way.
- **Whisper's segments are not speaker turns.** Lines are rebuilt from word
  timings and measured silences in `transcribe.into_lines`.
- **Changing anything in `stage/` changes every clip.** Renders are
  fingerprinted, so they redo themselves. Check the result by saving stills
  with `Renderer.still` and looking at them.
- **You cannot hear audio.** Check soundtracks by transcribing the rendered
  clip, and say in the pull request that nobody has listened yet.
- **consumer.ftc.gov blocks scripted requests.** Verify Field Guide sources
  by opening the page in a real browser, and quote only what the page says.
- **Redaction errs toward over-bleeping.** Do not loosen a rule to make a
  demo clip nicer. Add a test for anything you change in `redact.py`.

## What the maintainer prefers

- Everything runs locally by default. A hosted model, if ever added, is an
  opt-in spotter that sees only redacted text.
- Docs in plain language that a newcomer can follow.
- Pull requests small enough to review. Say so when one is large, and give
  a reading order.
- Push back when you disagree, with reasons.
