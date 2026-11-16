"""The publish kit: what Baitreel hands over once a person approves a clip.

A kit is a folder, not a post. Baitreel has no upload feature and holds no
account credentials, so it cannot publish anything by itself.

    clip.mp4        the video
    caption.txt     suggested post text, including the credit and the advice source
    credits.txt     who made the recording and where the advice comes from
    passport.json   the approval record: who approved it, when, and what was checked
"""

from __future__ import annotations

import hashlib
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from . import __version__, workspace
from .fieldguide import Tactic
from .models import Bait, Draft, Passport

DEMO_NOTE = "Scripted demo call. Not a real recording."


def caption(bait: Bait, tactic: Tactic) -> str:
    lines = [
        f"Red flag: {tactic.name}. {tactic.plain_label}.",
        "",
        tactic.counter_move,
        "",
        f"Recording: {bait.credit}",
        f"Advice: {tactic.source.title} {tactic.source.url}",
        "",
        "#ScamAwareness #Scambaiting",
    ]
    if bait.kind == "scripted-demo":
        lines.insert(0, DEMO_NOTE)
    return "\n".join(lines) + "\n"


def credits(bait: Bait, tactic: Tactic) -> str:
    return (
        f"Recording: {bait.credit}\n"
        f"Used with permission, as stated by {bait.rights.attested_by} "
        f"on {bait.rights.attested_at:%Y-%m-%d}.\n"
        f"Advice: {tactic.source.title}\n{tactic.source.url}\n"
        "Fonts: Atkinson Hyperlegible and Anton (SIL Open Font License), "
        "Special Elite (Apache License 2.0).\n"
        "Made with Baitreel. https://github.com/Jeff-Meendering/baitreel\n"
    )


def publish(bait: Bait, draft: Draft, tactic: Tactic, approved_by: str) -> Path:
    """Write the publish kit for an approved clip. Returns the kit's folder.

    Only ``review.py`` calls this, and only after a person has played the clip
    and chosen to keep it.
    """
    if not approved_by.strip():
        raise ValueError("A clip cannot be published without a named person approving it.")
    video = workspace.catch_dir(bait.id, draft.spec.id) / "clip.mp4"
    kit = workspace.export_dir(bait.id, draft.spec.id)
    kit.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(video, kit / "clip.mp4")
    (kit / "caption.txt").write_text(caption(bait, tactic), encoding="utf-8")
    (kit / "credits.txt").write_text(credits(bait, tactic), encoding="utf-8")
    passport = Passport(
        baitreel_version=__version__,
        clip_id=draft.spec.id,
        clip_sha256=hashlib.sha256(video.read_bytes()).hexdigest(),
        bait_id=bait.id,
        source_kind=bait.kind,
        source_sha256=bait.source_sha256,
        credit=bait.credit,
        rights=bait.rights,
        tactic=tactic.id,
        field_guide_source=tactic.source.url,
        field_guide_card_status=tactic.status,
        spotter=draft.flag.spotter,
        redactions=dict(Counter(r.kind for r in draft.redactions)),
        approved_by=approved_by.strip(),
        approved_at=datetime.now(UTC),
    )
    workspace.save(kit / "passport.json", passport)
    return kit
