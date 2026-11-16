#!/usr/bin/env python3
"""Fail if the repository contains recordings, rendered media or secrets.

Baitreel's rules: call recordings and API keys are never committed. This
check runs in CI on every pull request, and you can run it yourself:

    python3 scripts/check_repo_hygiene.py

It only uses the Python standard library, so it runs before anything is installed.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

MEDIA = {
    ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aiff", ".amr",
    ".mp4", ".mov", ".mkv", ".webm", ".avi",
}  # fmt: skip
SECRET_FILES = re.compile(r"(^|/)\.env(\.(?!example$)[\w.-]+)?$|\.pem$|(^|/)secrets\.")
SECRETS = {
    "Anthropic API key": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    "OpenAI-style API key": re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "Hugging Face token": re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
}
BINARY = {".ttf", ".otf", ".woff", ".woff2", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf"}


def problems(files: list[str], root: Path) -> list[str]:
    found: list[str] = []
    for name in files:
        path = root / name
        suffix = path.suffix.lower()
        if suffix in MEDIA:
            found.append(f"{name}: audio and video files must not be committed")
            continue
        if SECRET_FILES.search(name):
            found.append(f"{name}: files that hold secrets must not be committed")
            continue
        if suffix in BINARY or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in SECRETS.items():
            if pattern.search(text):
                found.append(f"{name}: looks like it contains a {label}")
    return found


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    files = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout.splitlines()  # fmt: skip
    found = problems(files, root)
    for problem in found:
        print(f"  {problem}")
    if found:
        print(f"\n{len(found)} problem(s). Remove these files or secrets before committing.")
        return 1
    print(f"Repository hygiene OK ({len(files)} files checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
