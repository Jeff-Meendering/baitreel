"""Review: a person plays each draft clip and decides whether to keep it.

This is the only path to a publish kit, and it has two deliberate limits:

- It needs a person at a keyboard. There is no flag that approves clips
  automatically, and it refuses to run when input is piped in.
- "Keep" unlocks only after the clip has been opened and enough time has
  passed to play it through. Redaction depends on the transcriber hearing
  names correctly, so a full listen is the last safeguard.
"""

from __future__ import annotations

import platform
import subprocess
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from . import publish, workspace
from .fieldguide import guide
from .models import Bait, Draft


def _open(path: Path) -> None:
    """Open the clip in the system's video player."""
    system = platform.system()
    if system == "Darwin":
        subprocess.run(["open", str(path)], check=False)
    elif system == "Windows":
        subprocess.run(["cmd", "/c", "start", "", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


def _clock(seconds: float) -> str:
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def describe(draft: Draft, number: int, total: int) -> Panel:
    spec = draft.spec
    lines = [
        f"[bold red]{spec.tactic.name}[/]  {spec.tactic.plain_label}",
        f"[dim]{_clock(spec.call_time)} into the call, {spec.duration:.0f} seconds long, "
        f"spotted by {draft.flag.spotter}[/]",
        "",
        f"[italic]“{draft.flag.quote}”[/]",
    ]
    if draft.flag.why:
        lines += ["", f"[dim]Why it was flagged:[/] {draft.flag.why}"]
    lines += ["", f"[green]Counter-move:[/] {spec.tactic.counter_move}"]
    if draft.redactions:
        lines += ["", "[bold]Bleeped and masked in this clip[/] (shown only here, on your screen):"]
        lines += [f"  {r.kind}: {r.original}" for r in draft.redactions]
    else:
        lines += [
            "",
            "[dim]No personal details were found in this clip. Listen for any that were missed.[/]",
        ]
    if draft.card_status != "reviewed":
        lines += [
            "",
            "[yellow]This Field Guide card is a draft that no human reviewer has signed off yet.[/]",
        ]
    return Panel("\n".join(lines), title=f"Catch {number} of {total}: {spec.id}", expand=False)


def run(bait: Bait, drafts: list[Draft], console: Console | None = None) -> list[Path]:
    """Walk a person through the drafts. Returns the folders of the publish kits made."""
    console = console or Console()
    pending = [d for d in drafts if d.status == "draft"]
    if not pending:
        console.print("Nothing left to review for this bait.")
        return []
    if not sys.stdin.isatty():
        console.print(
            "[yellow]Review needs a person at a keyboard, so nothing was approved or exported.[/]\n"
            f"When you are ready, run: [bold]baitreel review {bait.id}[/]"
        )
        return []

    console.print(
        "\nPlay each clip all the way through, with sound, before you decide.\n"
        "Listen for any name, number or address that should not be there.\n"
        "Check the SCAMMER and SCAMBAITER tags too. They are a model's reading of the\n"
        "conversation. If any are wrong, run the cut again with --no-speaker-labels.\n"
    )
    approver = Prompt.ask(
        "Your name or handle, for the approval record", default=bait.rights.attested_by
    )
    kits: list[Path] = []
    for number, draft in enumerate(pending, start=1):
        catch = workspace.catch_dir(bait.id, draft.spec.id)
        console.print(describe(draft, number, len(pending)))
        opened_at: float | None = None
        while True:
            choice = Prompt.ask(
                "[bold]p[/]lay   [bold]k[/]eep   [bold]t[/]hrow back   [bold]s[/]kip for now   [bold]q[/]uit",
                choices=["p", "k", "t", "s", "q"],
                show_choices=False,
            )
            if choice == "p":
                _open(catch / "clip.mp4")
                opened_at = opened_at or time.monotonic()
            elif choice == "k":
                waited = time.monotonic() - opened_at if opened_at else 0.0
                if opened_at is None:
                    console.print(
                        "Play the clip first. Keep unlocks once you have watched it through."
                    )
                elif waited < draft.spec.duration:
                    console.print(
                        f"Keep unlocks after a full play-through "
                        f"({draft.spec.duration - waited:.0f} seconds to go)."
                    )
                else:
                    draft.status = "keeper"
                    workspace.save(catch / "draft.json", draft)
                    kit = publish.publish(bait, draft, guide()[draft.spec.tactic.id], approver)
                    kits.append(kit)
                    console.print(f"[green]Keeper.[/] Publish kit: {kit}\n")
                    break
            elif choice == "t":
                draft.status = "throwback"
                workspace.save(catch / "draft.json", draft)
                console.print("Thrown back.\n")
                break
            elif choice == "s":
                console.print("Skipped. It will be here next time.\n")
                break
            else:
                return kits
    return kits
