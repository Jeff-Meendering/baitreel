"""The ``baitreel`` command.

baitreel demo                try the whole thing on a scripted demo call
baitreel cut RECORDING       turn a recording into draft clips, then review them
baitreel review BAIT_ID      review drafts that are waiting
baitreel guide               list the Field Guide (``--check`` validates it)
baitreel doctor              check that everything Baitreel needs is installed
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from rich.prompt import Prompt
from rich.table import Table

from . import __version__, demo, intake, pipeline, review, workspace
from .audio import MissingTool
from .fieldguide import load_guide
from .models import Bait
from .spot import local
from .transcribe import DEFAULT_MODEL

app = typer.Typer(
    help="Turn scambaiting call recordings into short videos that teach people to spot scams.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)
console = Console()

SpotterOption = Annotated[
    str,
    typer.Option(help="How to spot tactics: auto, local (a model on this computer) or keywords."),
]
MaxClipsOption = Annotated[int, typer.Option(help="The most clips to draft from one recording.")]


def _fail(message: str) -> typer.Exit:
    console.print(f"[red]{message}[/]")
    return typer.Exit(1)


def _cut(bait: Bait, **options) -> None:
    """Run the pipeline with progress bars, then hand the drafts to a person."""
    console.print(
        f"\n[bold]{bait.title}[/]  [dim]{bait.duration / 60:.1f} minutes, id {bait.id}[/]"
    )
    with Progress(
        TextColumn("{task.description:<30}"),
        BarColumn(bar_width=24),
        TextColumn("[dim]{task.fields[note]}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        tasks: dict[str, int] = {}

        def report(stage: str, done: float, note: str = "") -> None:
            if stage not in tasks:
                tasks[stage] = progress.add_task(stage, total=1.0, note=note)
            progress.update(tasks[stage], completed=done, **({"note": note} if note else {}))

        try:
            result = pipeline.run(bait, report=report, **options)
        except (MissingTool, RuntimeError) as error:
            progress.stop()
            raise _fail(str(error)) from error

    if not result.drafts:
        console.print(
            "\nNo clear tactics were found in this recording, so there is nothing to review.\n"
            f"Working files are in {workspace.bait_dir(bait.id)}"
        )
        return
    console.print(
        f"\n{len(result.flags)} flags spotted, {len(result.drafts)} clips drafted. "
        f"Drafts are in {workspace.bait_dir(bait.id) / 'catches'}"
    )
    kits = review.run(bait, result.drafts, console)
    if kits:
        console.print(f"[green]{len(kits)} publish kit(s) ready[/] in {kits[0].parent}")


@app.command()
def cut(
    recording: Annotated[Path, typer.Argument(help="A call recording on this computer.")],
    credit: Annotated[
        str | None, typer.Option(help="Who made the recording. Shown on every clip.")
    ] = None,
    attest: Annotated[
        str | None,
        typer.Option(help="Your name, confirming you have the right to use this recording."),
    ] = None,
    allow: Annotated[
        list[str] | None,
        typer.Option(help="A word that is safe to leave in, such as a persona's name. Repeatable."),
    ] = None,
    spotter: SpotterOption = "auto",
    max_clips: MaxClipsOption = 4,
    speech_model: Annotated[
        str, typer.Option(help="The faster-whisper model used for transcription.")
    ] = DEFAULT_MODEL,
    speaker_labels: Annotated[
        bool,
        typer.Option(help="Tag caption lines as SCAMMER or SCAMBAITER. Needs the local model."),
    ] = True,
    fresh: Annotated[bool, typer.Option(help="Ignore saved work and start over.")] = False,
) -> None:
    """Turn a recording into draft clips, then review them."""
    if not recording.expanduser().is_file():
        raise _fail(f"No recording at {recording}. Baitreel works on local files only.")
    interactive = sys.stdin.isatty()
    if credit is None:
        if not interactive:
            raise _fail("Say who made the recording with --credit. It is shown on every clip.")
        credit = Prompt.ask("Who made this recording? This credit is shown on every clip")
    if attest is None:
        if not interactive:
            raise _fail("Confirm your right to use the recording with --attest YOUR_NAME.")
        console.print(
            f"\n[bold]Before Baitreel touches this recording:[/]\n  “{intake.RIGHTS_STATEMENT}”"
        )
        attest = Prompt.ask("Type your name to confirm, or press Enter to stop", default="")
        if not attest.strip():
            raise _fail("Stopped. Nothing was processed.")
    try:
        bait = intake.register(recording, credit, attest)
    except (ValueError, MissingTool) as error:
        raise _fail(str(error)) from error
    _cut(
        bait, spotter=spotter, speech_model=speech_model, allow=allow or [],
        max_clips=max_clips, speaker_labels=speaker_labels, fresh=fresh,
    )  # fmt: skip


@app.command(name="demo")
def demo_command(
    spotter: SpotterOption = "auto",
    max_clips: MaxClipsOption = 4,
    fresh: Annotated[bool, typer.Option(help="Ignore saved work and start over.")] = False,
) -> None:
    """Try Baitreel on a scripted demo call. No real recording needed."""
    script = demo.load_script()
    recording = workspace.home() / "demo" / "edna-demo-call.wav"
    try:
        if not recording.exists() or fresh:
            console.print("Reading the demo script aloud with synthetic voices...")
            demo.build(recording, script)
        bait = intake.register(
            recording, script.credit, "Baitreel", kind="scripted-demo", title=script.title
        )
    except (RuntimeError, MissingTool) as error:
        raise _fail(str(error)) from error
    console.print(
        "[dim]This call is scripted and the voices are synthetic. Clips made from it are "
        "labeled as a demo.[/]"
    )
    # Edna and Gerald are the scambaiter's invented persona, so they are safe to
    # leave in. Every other name and number in the script still gets redacted.
    _cut(bait, spotter=spotter, allow=["Edna", "Gerald"], max_clips=max_clips, fresh=fresh)


@app.command(name="review")
def review_command(
    bait_id: Annotated[
        str | None, typer.Argument(help="The bait to review. Omit to list baits.")
    ] = None,
) -> None:
    """Review draft clips that are waiting for a decision."""
    baits = sorted((workspace.home() / "baits").glob("*/bait.json"))
    if bait_id is None:
        if not baits:
            console.print("No baits yet. Try: baitreel demo")
            return
        table = Table("Bait id", "Title", "Drafts", "Keepers", "Thrown back")
        for path in baits:
            bait = workspace.load(path, Bait)
            statuses = [d.status for d in pipeline.load_drafts(bait.id)]
            table.add_row(
                bait.id,
                bait.title,
                *(str(statuses.count(s)) for s in ("draft", "keeper", "throwback")),
            )
        console.print(table)
        return
    path = workspace.bait_dir(bait_id) / "bait.json"
    if not path.exists():
        raise _fail(f"No bait with id {bait_id}. Run `baitreel review` to list them.")
    review.run(workspace.load(path, Bait), pipeline.load_drafts(bait_id), console)


@app.command()
def guide(
    check: Annotated[bool, typer.Option(help="Validate every card and exit.")] = False,
) -> None:
    """List the Field Guide: the tactics Baitreel can label."""
    try:
        cards = load_guide()
    except ValueError as error:
        raise _fail(str(error)) from error
    if check:
        console.print(f"[green]All {len(cards)} Field Guide cards are valid.[/]")
        return
    table = Table("Tactic", "What it looks like", "What to do instead", "Status", show_lines=True)
    for card in cards.values():
        table.add_row(
            f"[bold]{card.name}[/]\n[dim]{card.id}[/]",
            card.plain_label,
            card.counter_move,
            card.status,
        )
    console.print(table)


@app.command()
def doctor() -> None:
    """Check that everything Baitreel needs is installed."""
    table = Table("Check", "Status", "Detail")
    problems = 0

    def row(name: str, ok: bool, detail: str, required: bool = True) -> None:
        nonlocal problems
        problems += 0 if ok or not required else 1
        status = (
            "[green]ok[/]" if ok else ("[red]missing[/]" if required else "[yellow]optional[/]")
        )
        table.add_row(name, status, detail)

    for tool in ("ffmpeg", "ffprobe"):
        found = shutil.which(tool)
        row(tool, bool(found), found or "macOS: brew install ffmpeg")
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            playwright.chromium.launch().close()
        row("Headless browser", True, "Chromium starts")
    except Exception:
        row("Headless browser", False, "Run: uv run playwright install chromium")
    try:
        import spacy

        spacy.load("en_core_web_sm")
        row("Name finder", True, "spaCy en_core_web_sm")
    except Exception:
        row("Name finder", False, "Run: uv sync")
    ready, reason = local.available()
    row(
        "Local model",
        ready,
        reason + ("" if ready else " The keyword spotter is used until then."),
        required=False,
    )
    voice = shutil.which("say") or shutil.which("espeak-ng")
    row("Demo voices", bool(voice), voice or "Needed only for `baitreel demo`", required=False)
    table.add_row("Working folder", "[green]ok[/]", str(workspace.home()))
    console.print(table)
    console.print(f"Baitreel {__version__}")
    if problems:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
