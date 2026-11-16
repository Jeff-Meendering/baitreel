"""The blind labeling page: a person labels a call without seeing Baitreel's answers.

``baitreel label`` starts a small web server on this computer and opens the
page in a browser. The page shows the transcript and plays the recording, and
the person marks:

- each moment where a Field Guide tactic appears, and
- every personal detail they hear, so redaction can be scored.

It is blind by construction: the server never sends Baitreel's flags or
redactions to the page, so the transcript shows every word as it was heard.

The server listens only on 127.0.0.1, answers only requests that carry a
random token from its own address, and checks the Host header, so other
websites open in the same browser cannot read the call or change the labels.
Labels are saved after every change.
"""

from __future__ import annotations

import json
import mimetypes
import re
import secrets
import subprocess
import threading
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pydantic import BaseModel, ValidationError

from .. import audio, workspace
from ..fieldguide import guide
from ..labels import DETAIL_KINDS, DetailMark, Labels, TacticLabel
from ..labels import save as save_labels
from ..models import Bait, Transcript

PAGE = Path(__file__).parent / "page"
FONTS = Path(__file__).parent.parent / "stage" / "fonts"
# Formats every mainstream browser plays. Anything else is converted once.
CHUNK = 2 << 20  # bytes sent per open-ended range request
PLAYABLE = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4", ".mp4": "audio/mp4"}


class LabelUpdate(BaseModel):
    """What the page sends after each change."""

    flags: list[TacticLabel]
    details: list[DetailMark]
    finished: bool = False


def playable_audio(bait: Bait) -> tuple[Path, str]:
    """A version of the recording the browser can play, made once if needed."""
    source = Path(bait.source_path)
    if source.suffix.lower() in PLAYABLE:
        return source, PLAYABLE[source.suffix.lower()]
    listen = workspace.bait_dir(bait.id) / "listen.m4a"
    if not listen.exists():
        subprocess.run(
            [audio.require("ffmpeg"), "-y", "-v", "error", "-i", str(source), "-vn", "-ac", "1",
             "-c:a", "aac", "-b:a", "96k", str(listen)],
            check=True,
        )  # fmt: skip
    return listen, "audio/mp4"


def call_data(bait: Bait, transcript: Transcript, labels: Labels) -> dict:
    """Everything the page needs. Deliberately nothing about Baitreel's own flags or bleeps."""
    return {
        "title": bait.title,
        "kind": bait.kind,
        "duration": bait.duration,
        "labeler": labels.labeler,
        "finished": labels.finished,
        "tool_ran_first": labels.tool_ran_first,
        "lines": [
            {
                "id": s.id,
                "start": s.start,
                "end": s.end,
                "words": [{"text": w.text, "start": w.start, "end": w.end} for w in s.words],
            }
            for s in transcript.segments
        ],
        "tactics": [
            {
                "id": t.id,
                "name": t.name,
                "plain_label": t.plain_label,
                "description": t.description,
                "sounds_like": t.sounds_like,
            }
            for t in guide().values()
        ],
        "kinds": list(DETAIL_KINDS),
        "labels": {
            "flags": [f.model_dump() for f in labels.flags],
            "details": [d.model_dump() for d in labels.details],
        },
    }


class LabelingServer:
    """Serve the labeling page for one bait and one labeler until they finish."""

    def __init__(self, bait: Bait, transcript: Transcript, labels: Labels, port: int = 0):
        self.bait, self.transcript, self.labels = bait, transcript, labels
        self.token = secrets.token_urlsafe(16)
        self.finished = threading.Event()
        self.lock = threading.Lock()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self.port = self.httpd.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/{self.token}/"

    def serve(self) -> None:
        """Serve until the person presses Finish (or until ``stop``)."""
        thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        thread.start()
        try:
            while not self.finished.wait(0.25):
                pass
        finally:
            self.stop()

    def stop(self) -> None:
        self.finished.set()
        self.httpd.shutdown()
        self.httpd.server_close()

    def update(self, body: bytes) -> dict:
        update = LabelUpdate.model_validate_json(body)
        cards = guide()
        limit = self.bait.duration + 1.0
        for item in [*update.flags, *update.details]:
            if not (0 <= item.start <= item.end <= limit):
                raise ValueError("a label falls outside the call")
        for flag in update.flags:
            if flag.tactic not in cards:
                raise ValueError(f"{flag.tactic} is not in the Field Guide")
        with self.lock:
            self.labels.flags = update.flags
            self.labels.details = update.details
            self.labels.finished = self.labels.finished or update.finished
            self.labels.updated_at = datetime.now(UTC)
            save_labels(self.labels)
        return {"saved_at": self.labels.updated_at.isoformat(), "finished": self.labels.finished}

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # keep the terminal quiet
                pass

            def _allowed(self) -> str | None:
                """The path after the token, or None if this request is not from our page."""
                host = self.headers.get("Host", "")
                if host not in {f"127.0.0.1:{server.port}", f"localhost:{server.port}"}:
                    return None
                prefix = f"/{server.token}/"
                path = self.path.split("?", 1)[0]
                return path[len(prefix) :] if path.startswith(prefix) else None

            def _send(self, status: int, body: bytes, kind: str, extra: dict | None = None):
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                for key, value in (extra or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _json(self, data: dict, status: int = 200) -> None:
                self._send(status, json.dumps(data).encode(), "application/json")

            def _file(self, path: Path) -> None:
                kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                self._send(200, path.read_bytes(), kind)

            def do_GET(self) -> None:  # noqa: N802
                route = self._allowed()
                if route is None:
                    return self._send(404, b"Not found", "text/plain")
                if route in {"", "index.html"}:
                    return self._file(PAGE / "index.html")
                if route in {"labeler.js", "labeler.css"}:
                    return self._file(PAGE / route)
                font = re.fullmatch(r"fonts/([\w.-]+\.ttf)", route)
                if font and (FONTS / font.group(1)).is_file():
                    return self._file(FONTS / font.group(1))
                if route == "api/call":
                    return self._json(call_data(server.bait, server.transcript, server.labels))
                if route == "audio":
                    return self._audio()
                return self._send(404, b"Not found", "text/plain")

            do_HEAD = do_GET  # noqa: N815

            def do_PUT(self) -> None:  # noqa: N802
                if self._allowed() != "api/labels":
                    return self._send(404, b"Not found", "text/plain")
                if not self.headers.get("Content-Type", "").startswith("application/json"):
                    return self._send(415, b"Expected JSON", "text/plain")
                length = int(self.headers.get("Content-Length", "0"))
                try:
                    return self._json(server.update(self.rfile.read(min(length, 2_000_000))))
                except (ValidationError, ValueError) as error:
                    return self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

            def do_POST(self) -> None:  # noqa: N802
                if self._allowed() != "api/done":
                    return self._send(404, b"Not found", "text/plain")
                self._json({"ok": True})
                threading.Thread(target=server.finished.set, daemon=True).start()

            def _audio(self) -> None:
                """Serve the recording with byte ranges, so the player can seek."""
                path, kind = playable_audio(server.bait)
                size = path.stat().st_size
                start, end = 0, size - 1
                ranged = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
                if ranged and (ranged.group(1) or ranged.group(2)):
                    if ranged.group(1):
                        start = int(ranged.group(1))
                        # An open-ended range gets a chunk; the player asks for more.
                        end = min(int(ranged.group(2) or start + CHUNK - 1), size - 1)
                    else:  # the last N bytes
                        start = max(size - int(ranged.group(2)), 0)
                    if start > end:
                        return self._send(416, b"", kind, {"Content-Range": f"bytes */{size}"})
                with path.open("rb") as handle:
                    handle.seek(start)
                    body = handle.read(end - start + 1)
                headers = {"Accept-Ranges": "bytes"}
                if ranged:
                    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
                self._send(206 if ranged else 200, body, kind, headers)

        return Handler
