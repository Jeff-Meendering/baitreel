"""The local spotter: a language model on this computer, through Ollama.

Nothing leaves the machine. Two guards enforce that:

- the Ollama server must be on this computer (a loopback address), and
- Ollama's cloud-hosted models are refused, because they send the prompt to
  a remote server even though the request goes to localhost.

The model sees only the redacted transcript, and it may only answer with
tactic ids from the Field Guide.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from urllib.parse import urlparse

import httpx

from ..fieldguide import Tactic
from ..models import Flag, Speaker
from . import Line, validate

DEFAULT_MODEL = "gemma4:12b"
CHUNK = 36  # transcript lines per request
OVERLAP = 4
CONTEXT_TOKENS = 8192
TIMEOUT = httpx.Timeout(900.0, connect=5.0)


def model_name() -> str:
    return os.environ.get("BAITREEL_MODEL", DEFAULT_MODEL)


def _host() -> str:
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    if "://" not in host:
        host = f"http://{host}"
    if urlparse(host).hostname not in {"127.0.0.1", "localhost", "::1", "0.0.0.0"}:
        raise RuntimeError(
            f"OLLAMA_HOST points at {host}, which is not this computer. "
            "Baitreel only sends transcripts to a model running locally."
        )
    return host.replace("0.0.0.0", "127.0.0.1").rstrip("/")


def available(model: str | None = None) -> tuple[bool, str]:
    """Is a usable local model ready? Returns (ready, explanation)."""
    name = model or model_name()
    try:
        tags = httpx.get(f"{_host()}/api/tags", timeout=3.0).json().get("models", [])
    except (httpx.HTTPError, ValueError):
        return False, "Ollama is not running. Start it, or install it from ollama.com."
    except RuntimeError as error:
        return False, str(error)
    for tag in tags:
        if tag.get("name") in {name, f"{name}:latest"}:
            if tag.get("remote_host") or tag.get("remote_model") or name.endswith("cloud"):
                return False, f"{name} is a cloud-hosted model. Baitreel only uses local models."
            return True, f"{name} is ready."
    return False, f"The model {name} is not downloaded. Run: ollama pull {name}"


def _ask(system: str, user: str, schema: dict, model: str | None = None) -> dict:
    response = httpx.post(
        f"{_host()}/api/chat",
        timeout=TIMEOUT,
        json={
            "model": model or model_name(),
            "stream": False,
            # Step-by-step "thinking" made a 12B model take over ten minutes per
            # request on a 16 GB laptop. The schema below keeps answers on track.
            "think": False,
            "format": schema,
            "options": {"temperature": 0, "num_ctx": CONTEXT_TOKENS},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
    )
    response.raise_for_status()
    return json.loads(response.json()["message"]["content"])


# --- Flag spotting ------------------------------------------------------------

SYSTEM = """\
You are a careful fraud analyst. You are reading the transcript of a scambaiting \
call: a scammer is talking to a scambaiter (or an anti-scam bot) who is \
pretending to be an ordinary person. Your job is to find the moments where the \
SCAMMER uses a known manipulation tactic, so those moments can be turned into \
short educational clips.

Personal details in the transcript have been replaced by placeholders such as \
[name] and [number]. Speakers are not marked; work out who is speaking from \
what is said."""

TASK = """\
Find each moment in the transcript where the scammer uses one of the tactics above.

Rules:
- Use only the tactic ids listed above. If no tactic clearly fits a line, do not flag it. \
An empty list is a good answer when nothing fits.
- Flag only lines spoken by the scammer, never the person answering the call.
- first_line and last_line are the line numbers that contain the tactic. Use one line, \
or two when the tactic runs across neighbouring lines.
- cue_phrases: one to three short phrases copied EXACTLY, word for word, from those lines. \
Choose the words that do the manipulating.
- why: one plain sentence explaining why this is that tactic.
- teachability, 1 to 5. Give 5 when the tactic is unmistakable and the line would make \
sense to someone who has not heard the rest of the call. Give 1 when it needs a lot of \
context.
- Flag each moment once, with the tactic that fits best. Flag a line twice only if two \
different tactics are both clearly present."""


def _schema(guide: dict[str, Tactic]) -> dict:
    return {
        "type": "object",
        "required": ["flags"],
        "properties": {
            "flags": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["tactic", "first_line", "last_line", "cue_phrases", "why",
                                 "teachability"],
                    "properties": {
                        "tactic": {"type": "string", "enum": sorted(guide)},
                        "first_line": {"type": "integer"},
                        "last_line": {"type": "integer"},
                        "cue_phrases": {"type": "array", "items": {"type": "string"}},
                        "why": {"type": "string"},
                        "teachability": {"type": "integer", "minimum": 1, "maximum": 5},
                    },
                },
            }
        },
    }  # fmt: skip


def _guide_text(guide: dict[str, Tactic]) -> str:
    entries = []
    for tactic in guide.values():
        examples = " / ".join(f'"{example}"' for example in tactic.sounds_like[:3])
        entries.append(
            f"- {tactic.id}: {tactic.plain_label}. {tactic.description} Sounds like: {examples}"
        )
    return "TACTICS\n" + "\n".join(entries)


def build_prompt(lines: list[Line], guide: dict[str, Tactic]) -> str:
    # The transcript goes last. Everything before it is identical for every
    # request, so Ollama reuses its work on that part and only reads the new lines.
    transcript = "\n".join(f"[{line.id}] {line.text}" for line in lines)
    return f"{_guide_text(guide)}\n\n{TASK}\n\nTRANSCRIPT\n{transcript}"


def prompt_version(guide: dict[str, Tactic]) -> str:
    """A short fingerprint of everything that shapes the model's answer except the transcript.

    It changes whenever the instructions, the Field Guide text, the answer
    format or the chunking change, so saved results from an older prompt are
    never mistaken for results from this one. ``baitreel eval`` uses it to
    compare prompt versions side by side.
    """
    parts = [SYSTEM, TASK, _guide_text(guide), json.dumps(_schema(guide), sort_keys=True),
             f"{CHUNK}/{OVERLAP}/{CONTEXT_TOKENS}"]  # fmt: skip
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:8]


def spot(
    lines: list[Line],
    guide: dict[str, Tactic],
    on_progress: Callable[[float], None] | None = None,
    model: str | None = None,
) -> list[Flag]:
    model = model or model_name()
    ready, reason = available(model)
    if not ready:
        raise RuntimeError(reason)
    by_id = {line.id: line for line in lines}
    spotter = f"local/{model}"
    flags: dict[str, Flag] = {}
    starts = list(range(0, max(len(lines), 1), CHUNK - OVERLAP))
    for n, start in enumerate(starts):
        chunk = lines[start : start + CHUNK]
        if not chunk:
            break
        answer = _ask(SYSTEM, build_prompt(chunk, guide), _schema(guide), model)
        in_chunk = {line.id: line for line in chunk}
        for flag in validate(answer.get("flags", []), in_chunk, guide, spotter):
            # Lines in the overlap are seen twice. Keep the more confident reading.
            if flag.id not in flags or flag.teachability > flags[flag.id].teachability:
                flags[flag.id] = flag
        if on_progress:
            on_progress((n + 1) / len(starts))
    return sorted(flags.values(), key=lambda f: by_id[f.first_segment].start)


# --- Speaker labels -----------------------------------------------------------

SPEAKER_TASK = """\
For each numbered line below, say who is speaking:
- "scammer": the caller running the scam.
- "target": the person answering, who is pretending to be an ordinary member of the public.
- "unknown": you cannot tell, or the line contains both people talking.

The scammer gives instructions, makes demands and claims authority. The target \
answers, asks questions, stalls and chats. The lines are in order, and the two \
usually take turns."""


def label_speakers(lines: list[Line]) -> dict[int, Speaker]:
    """Work out who speaks each line of a short stretch of the call."""
    schema = {
        "type": "object",
        "required": ["lines"],
        "properties": {
            "lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["line", "speaker"],
                    "properties": {
                        "line": {"type": "integer"},
                        "speaker": {"type": "string", "enum": ["scammer", "target", "unknown"]},
                    },
                },
            }
        },
    }
    transcript = "\n".join(f"[{line.id}] {line.text}" for line in lines)
    answer = _ask(SYSTEM, f"{SPEAKER_TASK}\n\n{transcript}", schema)
    known = {line.id for line in lines}
    return {
        int(item["line"]): item["speaker"]
        for item in answer.get("lines", [])
        if isinstance(item, dict) and item.get("line") in known
        and item.get("speaker") in {"scammer", "target", "unknown"}
    }  # fmt: skip
