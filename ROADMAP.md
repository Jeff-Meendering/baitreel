# Baitreel: Roadmap

This is the build plan for the vision in [VISION.md](VISION.md). It covers the
path to **v0.1.0**, the first demo-ready release, and sketches what comes
after.

Dates assume a class demo around **November 26, 2026**. They are targets, not
promises, and each milestone waits for the previous pull request to be merged.

## How we work

- Every milestone is built on its own branch and arrives as one focused pull
  request into `main`.
- Each pull request explains what it does, how to try it, and the decisions
  and tradeoffs behind it.
- The next milestone starts only after the previous one is merged, branching
  from the updated `main`.
- Every milestone ends with something that runs.
- Call recordings, real transcripts, API keys and other secrets are never
  committed. The `.gitignore` blocks the common cases, and Milestone 1 adds an
  automated check.

## At a glance

| # | Milestone | Target | What you can try when it lands |
|---|---|---|---|
| 0 | Direction | Nov 17 | Read and challenge `VISION.md` and this roadmap |
| 1 | First Catch | Nov 19 | One command turns a recording into finished, redacted, credited clips |
| 2 | Second Opinion | Nov 21 | Label a call blind and get agreement scores against the tool |
| 3 | Cutting Room | Nov 24 | Review, edit and approve clips in a local web app |
| 4 | Polish and v0.1.0 | Nov 26 | A documented, tagged release ready to demo |

The measurement milestone comes before the web app on purpose. Labeling calls
by hand takes the maintainer's time, and it can happen in parallel while the
web app is being built.

## How a recording becomes a clip

```
recording ──▶ transcribe ──▶ redact ──▶ spot flags ──▶ draft clips ──▶ human review ──▶ render ──▶ leak check ──▶ publish kit
  (local)      (local)       (local)    (redacted       (local)        (required)      (local)     (local)        (a folder)
                                         text only)
```

Each stage reads and writes plain JSON files in a per-recording working
folder, so any stage can be inspected, re-run or replaced. The only step that
can leave the computer is flag spotting, and it only ever sees redacted text.

## Stack

| Part | Choice | Why |
|---|---|---|
| Pipeline and command line | Python 3.12, managed with `uv` | The speech and language tooling lives in Python, and `uv` gives contributors a one-command setup |
| Transcription | `faster-whisper`, run locally, with word-level timestamps | Audio stays on the machine. Word timings drive captions and bleeps |
| Personal-detail detection | Pattern rules, plus spaCy to find names | Layered, local and inspectable |
| Flag spotting | A model on the user's own computer through Ollama (Gemma 4 12B by default), with a keyword spotter as fallback and baseline | Nothing leaves the machine. The model is constrained to Field Guide entries. A hosted model can be added later as an opt-in spotter |
| Audio and encoding | `ffmpeg` | The standard tool, called as an external program |
| Clip rendering | The clip is a plain web page (HTML, CSS and JavaScript) captured frame by frame with headless Chromium | The preview a human approves is the same code that renders the export |
| Web app (Milestone 3) | FastAPI serving a small TypeScript front end | A thin layer over the same pipeline the command line uses |

### Tradeoffs worth knowing

- **Web-page rendering is slower than drawing frames natively**, and it adds a
  Chromium download of roughly 150 MB. In exchange, the approved preview and
  the exported file cannot drift apart, and contributors can restyle clips
  with ordinary CSS. If capture proves too slow in Milestone 1, the fallback
  is drawing frames in Python for that milestone and revisiting the renderer
  later.
- **Speaker separation is simple at first.** v0.1.0 labels who is speaking from
  the transcript, with human correction. Acoustic speaker separation comes
  later because the best models need extra accounts and downloads.
- **Everything runs locally, which is slower.** On a 16 GB M1 laptop,
  transcribing and spotting together took about as long as the call itself
  (measured on one short demo call). A hosted model would be faster and
  probably more accurate, and could be added as an opt-in spotter that only
  ever sees redacted text. Milestone 2 gives the numbers to decide that.

---

## Milestone 0: Direction

**Branch:** `docs/vision-and-roadmap`

- `VISION.md` and `ROADMAP.md`.

**Done when:** the maintainer has reviewed and merged the direction.

## Milestone 1: First Catch

**Goal:** a real recording goes in, finished clips come out.

- Project skeleton: package layout, `uv` setup, tests, linting and continuous
  integration.
- A repository check that fails if media files or likely secrets are added.
- A scripted **synthetic demo call**, generated with text-to-speech from a
  script in the repository, so anyone can run the pipeline without a real
  recording. Only the script is committed.
- Intake with a rights attestation and source credit.
- Local transcription with word timings.
- Redaction of personal details in audio (bleeps) and captions (masks).
- **Field Guide v0**: about ten tactics, each with reviewed advice and a
  source.
- Flag spotting against the Field Guide.
- The **Flag on the Play** clip format, rendered as a vertical video with
  captions, stamp, counter-move and credit.
- Approval in the terminal, clip by clip. Nothing is exported unapproved.
- The publish kit: video, caption text, credits and an approval record.

**Try it:** `baitreel cut path/to/recording` and watch the results.

**Done when:** the maintainer has produced clips from a real recording they
have the right to use.

**Not yet:** a web app, batch processing, speaker separation by voice.

### What changed while building it

- **The spotter is local by default.** The maintainer chose a local model
  over a hosted one, so no transcript text leaves the computer at all.
- **Names are found with spaCy and context rules**, not Presidio. The rules
  that matter for phone calls (digits read aloud, spelled-out names) had to
  be written by hand either way, and the result is smaller and easier to read.
- **Lines are split at measured silences.** The speech model's own segments
  ran two speakers together too often.
- **Speaker tags come from the local model reading the text.** They are
  usually right and sometimes wrong, so they can be turned off.
- **The leak check stays in Milestone 3.** For now a full listen is the gate.

## Milestone 2: Second Opinion

**Goal:** know how good the flag spotting and redaction are.

- A blind labeling page: transcript and audio side by side, with a tactic
  picker drawn from the Field Guide. It also accepts label tracks exported
  from Audacity.
- A way to mark personal details by hand, for scoring redaction.
- Scoring: precision, recall and F1 per tactic, Cohen's kappa overall, and
  redaction recall.
- Side-by-side comparison of models and prompt versions.
- A generated report with charts, suitable for the class report.

**Try it:** label one call, run `baitreel eval`, and read the report.

**Done when:** there is a report for at least one real call, and the
maintainer can add more calls without help.

### What changed while building it

- **Label first, then cut.** `baitreel label` can take a recording and only
  transcribe it, so a call can be labeled before Baitreel has spotted
  anything. Labels started after the tool ran are marked "maybe not blind"
  in the report.
- **Matching by overlap, counted from both sides.** A flag is correct if a
  labeled moment of the same tactic overlaps it; a labeled moment is found if
  any such flag overlaps it. One moment split across two lines is not
  punished twice.
- **Kappa is per transcript line**, with "none" as a label, so it measures
  agreement on where tactics are as well as which ones.
- **Redaction counts as caught only when 80% of a detail is bleeped.** Half a
  phone number is still a phone number.
- **Spotter results are saved as runs**, fingerprinted by model, prompt and
  transcript. This also fixed a Milestone 1 bug: changing the prompt used to
  reuse flags from the old prompt.
- **The demo script is its own answer key**, personal details included, so
  `baitreel eval` works straight after `baitreel demo`.
- **The labeling page uses Python's built-in web server**, not FastAPI. It
  is one page with a handful of requests, and Milestone 3 can move it.
- **Not built:** the usefulness numbers from the vision (share of drafts
  kept, review time per hour). They need the review app from Milestone 3.

## Milestone 3: Cutting Room

**Goal:** make review pleasant enough that a creator would choose to use it.

- A local web app that opens in the browser.
- The call timeline with flags planted along it.
- A review queue of catches, with keyboard shortcuts for keep and throw back.
- Editing: trim points, the tactic label, the advice card.
- The Redaction Room: every redaction listed, confirmable and adjustable, with
  a way to add ones the tool missed.
- Approval that unlocks only after the whole clip has been played.
- The leak check on every rendered clip.

**Try it:** `baitreel open` and review a call from start to export.

**Done when:** a full call can be reviewed and exported without touching the
terminal after launch.

## Milestone 4: Polish and v0.1.0

**Goal:** a release worth demonstrating and worth contributing to.

- A large-print export preset for older viewers.
- `CONTRIBUTING.md`, a code of conduct, issue templates and a guide to adding
  a Field Guide entry.
- An architecture overview for new contributors.
- A README with screenshots and a five-minute quick start.
- Evaluation results from Milestone 2 published in the repository.
- Bug fixes from demo rehearsal.
- The **v0.1.0** tag and release notes.

**Done when:** a stranger can clone the repository and produce a clip from the
synthetic demo call by following the README.

---

## After v0.1.0

Roughly in order of how soon they seem worth building. Community interest
should reorder this list.

1. **Night Shift.** Batch processing of a folder of recordings, with a queue
   ranked by teaching value. Ingestion of bot logs and existing transcripts.
2. **The life list.** Per-creator coverage of the Field Guide.
3. **Spot the Flag.** The pause-and-guess clip format.
4. **Speaker separation by voice**, and optional voice disguise for anyone on
   the call who is not the scammer.
5. **More languages.** Many scam calls mix languages. Field Guide entries and
   captions need translation, reviewed by fluent speakers.
6. **A call anatomy card.** A shareable image of the whole call's timeline.
7. **A viewer study.** A small test of whether watching clips improves
   people's ability to spot tactics, which would answer the open question in
   the vision.
8. **The Script Atlas.** An opt-in, redacted shared corpus and script
   fingerprinting. This needs a governance and consent design before any
   code.

## Risks

| Risk | Plan |
|---|---|
| No real recording with clear rights is available in time | Development uses the synthetic call. The maintainer sources a real recording, by their own baiting or with a creator's written permission, before Milestone 1 review |
| Flag spotting is not accurate enough | Human approval is always required. Milestone 2 measures it early enough to adjust prompts and the Field Guide |
| A personal detail slips past redaction | Layered detection, the leak check and a required full listen. Redaction recall is tracked as its own metric |
| Rendering is too slow | Fall back to native frame drawing for Milestone 1 |
| The schedule slips | Milestone 4 polish is trimmed first. Milestones 1 and 2 are protected because the demo and the report depend on them |

## What the maintainer needs to provide

- A real recording with clear rights, for the Milestone 1 review.
- Time to label at least one call by hand for Milestone 2.
- Answers to the open questions in `VISION.md`.
