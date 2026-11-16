# Baitreel: Vision

**The highlight reel for your baits.**

Baitreel turns scambaiting call recordings into short, clearly labeled videos
that teach everyday people to recognize a scam while it is happening. It runs
on the creator's own computer, a human approves every clip, and it never
posts anything by itself.

This document explains why the project exists, what it is, what makes it
different, and where it deliberately stops. The build plan is in
[ROADMAP.md](ROADMAP.md).

---

## 1. Why this exists

People reported losing about $16 billion to fraud in the United States in
2025, a record. Imposter scams alone accounted for $3.5 billion, nearly triple
the 2020 figure. Losses reported by older adults grew from about $600 million
in 2020 to about $3 billion in 2025, and the FTC estimates the true cost to
older adults could be far higher because most fraud is never reported.
[[1]](#sources) [[2]](#sources)

Meanwhile, the scambaiting community sits on an enormous archive of scams in
action. Human scambaiters keep scammers on the phone for hours. So do the
bots: O2's "Daisy," Apate's fleet of personas, Kitboga's bot army, and bots run
by banks. [[3]](#sources) [[4]](#sources) [[5]](#sources) [[13]](#sources)
Every one of those
calls contains the real thing: a fake fraud department, a gift card demand, a
manufactured deadline, a threat, a "don't tell anyone."

Almost nobody listens to a full call. The teachable moments stay buried.

The idea behind Baitreel comes from **inoculation theory**: show people a
weakened dose of a manipulation tactic, clearly labeled for what it is, and
they resist it better when they meet it for real. Short "prebunking" videos
have been tested at scale and they work, modestly but consistently (see
[Honest limits](#10-honest-limits)). [[6]](#sources)

The scambaiting community has entertained and protected a lot of people.
Baitreel is meant as something given back: a tool that makes their work go
further.

## 2. What already exists, and what is missing

| What exists | What it does well | What is missing |
|---|---|---|
| AI clipping tools (OpusClip, Vizard, Klap, Descript and others) [[7]](#sources) | Cut long talking-head video into captioned shorts, ranked by predicted virality | No understanding of scam tactics, no lesson, no redaction of personal details, weak on audio-only phone calls, and recordings are uploaded to a company's servers |
| Scambaiting channels | Real scammer voices, big audiences, humor | Long-form and built for entertainment. The lesson is implied, and the funny moment is not always the teachable one |
| Anti-scam bots [[3]](#sources) [[4]](#sources) [[5]](#sources) | Waste scammers' time at scale, and in Apate's case gather intelligence | Thousands of hours of recordings that nobody turns into public education |
| Official awareness campaigns | Accurate advice from trusted names | Scripted and acted. Viewers never hear what a real scammer sounds like |
| Research [[8]](#sources) [[9]](#sources) [[10]](#sources) | Maps scam calls into stages and defines tactic taxonomies | Lives in papers, not in tools creators can use |

The gap is the intersection: **real scammer audio, labeled with the tactic,
paired with accurate advice, made safe to publish, in a tool creators control.**
We found nothing that does this.

## 3. What Baitreel is

Baitreel is a local-first "cutting room" for scam calls.

1. You give it a recording you have the right to use.
2. It listens the way a fraud analyst would and plants a **flag** wherever a
   known tactic appears.
3. It drafts a 30–60 second vertical clip around each flag, with captions, a
   named red flag and a "what to do instead" card.
4. It redacts personal details from the audio and the captions.
5. You review, fix, and approve or reject each clip.
6. It exports a **publish kit**: the video, caption text, credits and an
   approval record. You upload it wherever you like.

### Who it is for

- **Scambaiters and channel editors**, who have more footage than time.
- **People who run scambaiting bots**, whose recordings pile up unheard.
- **Viewers**, especially older adults, who need to recognize a scam in the
  moment. They never use Baitreel, but every design decision about the clips
  is made for them.

### How it should feel

Like it was made by someone who loves this community. Fun, a little irreverent
toward scammers, never cruel to the people they target. The vocabulary leans
on the fishing metaphor the community already uses:

| Word | Meaning |
|---|---|
| **Bait** | A recorded call |
| **Flag** | A moment where a tactic appears |
| **Catch** | A draft clip built around a flag |
| **Keeper** | A clip a human approved |
| **Throwback** | A clip a human rejected |

## 4. The core experience

A creator drops in a 47-minute bait before bed. In the morning the call is laid
out as a timeline with flags planted along it: an authority claim at 0:40, a
manufactured deadline at 3:12, "don't hang up" at 9:50, a gift card demand at
31:05. This timeline is the call's anatomy, and it is useful even if no clip
is ever made.

Each flag has a draft clip. The creator plays one. They nudge the start point,
confirm two bleeped phone numbers, swap the advice card for a better fit, and
press **Keep**. The Keep button only unlocks after the clip has been played
all the way through, so nothing is approved unheard.

The export is a folder, not a post.

## 5. The ideas

### 5.1 Flag on the Play: one recognizable clip grammar

Every clip follows the same structure, borrowed from the referee's flag and
the instant replay:

1. **The play.** The scammer's real line, in their real voice.
2. **The flag.** The frame freezes and a stamp names the tactic.
3. **The replay.** The line plays again with the manipulative words
   highlighted.
4. **The counter-move.** One plain sentence on what to do instead.
5. **The credit.** Whose recording this is.

This is the inoculation structure made visible: a warning, a weak dose and a
refutation. A fixed grammar also means a viewer who has seen three clips knows
how to read the fourth, whichever channel published it.

### 5.2 The Field Guide: an open catalogue of tactics

Tactics live in a versioned, human-readable catalogue, like a birdwatcher's
field guide. Each entry has a memorable name, a plain description, what it
sounds like, why it works, and reviewed advice with a cited source:

```yaml
id: gift-card-detour
name: The Gift Card Detour
plain_label: Asks you to pay with gift cards
sounds_like:
  - "Go to the store and buy two gift cards."
  - "Read me the numbers on the back."
why_it_works: Gift cards are fast, hard to trace and nearly impossible to refund.
counter_move: >
  Gift cards are for gifts. No real business or government agency
  will ever ask you to pay with one. Hang up.
source: https://consumer.ftc.gov/articles/avoiding-and-reporting-gift-card-scams
kindness_check: Blames the tactic, never the person.
```

Two things follow from this design.

- **Accuracy is built into the data.** The language model may only choose
  from Field Guide entries. It never writes safety advice freehand, so it
  cannot invent a plausible but wrong instruction.
- **Anyone can contribute without writing code.** Adding or improving a
  tactic is a pull request against a text file, reviewed by a human.

Memorable names ("The Ticking Clock," "The Hush," "The Badge," "The Gift Card
Detour") are a teaching device in their own right. A name is easier to recall
under pressure than a paragraph.

### 5.3 The Redaction Room: privacy by construction

- Transcription happens on the creator's computer. **Audio never leaves the
  machine.**
- Personal details are detected in layers: pattern rules for spoken digits,
  emails and addresses, then named-entity detection for names and places.
- Tactic spotting runs on a **local language model** by default, so nothing
  leaves the machine. If a hosted model is ever added as an option, it will
  only ever be sent the **redacted transcript**.
- Redactions are applied twice: a bleep in the audio and a mask in the
  captions.
- Before export, a **leak check** transcribes the finished clip again and
  scans it. This verifies the output, not the intention.
- **Scammers' details are redacted too.** Spoofed phone numbers and "mule"
  bank accounts usually belong to other victims.

### 5.4 Bold: the Night Shift and the life list

Point Baitreel at a folder of bot recordings and let it work overnight. In the
morning there is a queue of catches ranked by **teaching value** (is the
tactic clear, does the moment stand alone, is it free of personal details),
not by predicted virality.

Creators also keep a **life list**, as birdwatchers do: which tactics from the
Field Guide they have caught on tape, and which they are still looking for. It
turns coverage of the full range of scam tactics into a game the community
already knows how to play.

### 5.5 Bold: Spot the Flag and the Script Atlas

- **Spot the Flag.** A clip variant that pauses before the reveal and asks the
  viewer to name the red flag. Inoculation research distinguishes passive
  viewing from active practice. Whether the active version teaches better
  here is something to test, not assume. The format is also a natural fit
  for comment sections.
- **The Script Atlas.** An opt-in, redacted, shared corpus of tactic snippets.
  Scam calls follow scripts. Fingerprinting those scripts would let a clip say
  "this is the refund-overpayment script" and would let the community notice
  when a new script starts circulating. This is the most ambitious idea here
  and it needs careful governance before any data is shared.

## 6. The promises, and how the design keeps them

| Promise | Mechanism |
|---|---|
| A human approves everything | Baitreel has no upload feature and holds no platform credentials. Export requires an explicit approval, and approval requires playing the whole clip. Each publish kit records who approved it and when. |
| It protects privacy | Local transcription, layered redaction of audio and captions, a leak check on the rendered file, and a default of redacting anything that looks like a personal detail. |
| It respects creators | Local files only. A rights attestation is required per recording and stored with it. The source credit is burned into every clip and written into the publish kit. |
| It is accurate and kind | Advice comes only from reviewed, sourced Field Guide entries. Every entry passes a kindness check: it names the tactic and never blames the person. |

## 7. What Baitreel will not do

- **It will not post.** No scheduling, no platform connections, no auto-upload.
- **It will not download other people's videos.** There is no "paste a link"
  feature. That feature is what would make it easy to process work the user
  has no right to use.
- **It will not chase virality.** There is no virality score.
- **It will not expose anyone.** It is a teaching tool, not a doxxing tool,
  and that includes scammers.
- **It will not generate fake scam calls for publication.** Synthetic calls
  are used only for tests and demos, and are labeled as such.
- **It will not mock victims.** Humor is aimed at the scam.

## 8. Tone and accessibility for viewers

Research on blame matters here. In a survey by AARP and the FINRA Foundation,
53% of Americans held fraud victims culpable, and UK trading standards link
shame to under-reporting. [[11]](#sources) [[12]](#sources) A clip that makes a
viewer feel foolish works against its own purpose.

So every clip speaks about what the scammer did, in the active voice: "the
caller invented a deadline," never "she fell for it." The framing is "this is
designed to work on anyone."

Clips are also designed for older viewers from the start: large high-contrast
captions, no rapid cuts, a steady pace, and one idea per clip. A large-print
export preset targets the platforms and screen sizes older adults use.

## 9. Measuring it

A class report and an honest open-source project both need numbers. Baitreel
includes an evaluation harness:

- A human labels the same call **blind**, using the same Field Guide.
- **Tactic detection** is scored per tactic with precision, recall and F1,
  matching flags by tactic and time overlap, plus Cohen's kappa for overall
  agreement.
- **Redaction** is scored as recall against human-marked personal details.
  This is the safety-critical number.
- **Usefulness** is scored as the share of drafts a human keeps, and the
  review time per hour of recording.
- Where a second human can label the same call, human-to-human agreement gives
  the realistic ceiling. One published benchmark of scam-call labeling
  reports substantial but far from perfect human agreement (kappa of 0.69).
  [[10]](#sources)

Results are written to a report with charts, and the same harness compares
models and prompt versions over time.

## 10. Honest limits

- **The evidence is real but modest.** A study across 12 EU countries with
  about 19,700 participants found that short prebunking videos improved
  people's ability to spot manipulation, with small effects. Videos of about
  50 seconds worked more consistently than 20-second ones. How long the
  effect lasts is unresolved. [[6]](#sources)
- **No scam-specific proof yet.** That research concerns misinformation. We
  found no published test of prebunking videos against phone scams. Baitreel
  must not claim that its clips prevent fraud. Measuring that with viewers is
  future work.
- **Detection makes mistakes.** That is why a human approves every clip and
  why the evaluation harness exists.
- **Redaction depends on transcription.** If the transcriber mishears a name,
  the pattern rules will not see it. The leak check reduces this risk and the
  human listen-through is the final safeguard.
- **Rights cannot be verified by software.** The attestation is an honor
  system, backed by the refusal to download from links.
- **Baits are not real victim calls.** Scammers behave as they would with a
  victim for most of the call, but researchers note the difference.
  [[8]](#sources)

## 11. Open questions

These are waiting on the maintainer. Development proceeds on the stated
default until answered.

| Question | Default |
|---|---|
| Which real recordings are available with clear rights? | Develop against a scripted synthetic call. A real recording is needed to review Milestone 1. |
| Is a hosted language model available, with a small budget? | **Answered:** use a local model. A hosted spotter may be added later as an opt-in. |
| What is the exact demo date and report rubric? | Assume a demo around November 26, 2026. |
| Is English-only acceptable for v0.1.0? | Yes. |
| Does the maintainer bait, run a bot, or know creators who would test? | Unknown. This decides how early bot-folder ingestion matters. |

## Sources

1. FTC, "FTC Data Show People Reported Losing $3.5 Billion to Imposter Scams in 2025." <https://ftc.gov/news-events/news/press-releases/2026/06/ftc-data-show-people-reported-losing-3-point-5-billion-imposter-scams-2025>
2. FTC, *Protecting Older Consumers 2025–2026*. <https://www.ftc.gov/node/338049>
3. Gizmodo, on O2's "Daisy." <https://gizmodo.com/telecom-builds-ai-grandmother-bot-to-talk-to-phone-scammers-and-waste-their-time-2000524579>
4. Cointelegraph Magazine, on Apate. <https://cointelegraph.com/magazine/fake-ai-victims-are-scam-baiting-600000-fraudsters-every-month>
5. Frank on Fraud, on Kitboga's bot army. <https://frankonfraud.beehiiv.com/p/an-ai-bot-army-is-taking-scam-centers-down>
6. Prebunking videos across 12 EU countries, *Communications Psychology*. <https://link.springer.com/article/10.1038/s44271-025-00379-3>
7. Reap, "State of AI Video Clipping 2026" (vendor-written; used for the feature landscape only). <https://reap.video/blog/state-of-ai-video-clipping-2026>
8. Wood et al., "An analysis of scam baiting calls: Identifying and extracting scam stages and scripts." <https://arxiv.org/html/2307.01965v1>
9. Ma et al., "PsyScam: A Benchmark for Psychological Techniques in Real-World Scams." <https://arxiv.org/html/2505.15017v2>
10. "Vishing-Tactics-Bench: Forecasting Exploitation Trajectories in Voice Phishing Calls." <https://arxiv.org/pdf/2609.07151>
11. AARP, "How Shame Could Cost You Money" (summarizing the 2022 AARP and FINRA Foundation report). <https://sisters.aarp.org/work-money/wealth/how-shame-could-cost-you-money/>
12. Friends Against Scams, #NoBlameNoShame. <https://www.friendsagainstscams.org.uk/noblamenoshame-news-article>
13. Frank on Fraud, "Bank Deploys Army of 10,000 AI Bots To Foil Scammers." <https://frankonfraud.com/bank-deploys-army-of-10000-ai-bots-to-foil-scammers/>
