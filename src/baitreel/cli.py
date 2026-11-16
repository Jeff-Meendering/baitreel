"""The ``baitreel`` command.

baitreel demo                try the whole thing on a scripted demo call
baitreel cut RECORDING       turn a recording into draft clips, then review them
baitreel review BAIT_ID      review drafts that are waiting
baitreel label BAIT          label a call by hand, blind, for scoring
baitreel eval                score Baitreel against the labels and write a report
baitreel guide               list the Field Guide (``--check`` validates it)
baitreel doctor              check that everything Baitreel needs is installed
"""

from __future__ import annotations

import shutil
import sys
import webbrowser
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from rich.prompt import Prompt
from rich.table import Table

from . import __version__, demo, evaluate, intake, labels, pipeline, review, workspace
from .audio import MissingTool
from .fieldguide import guide as field_guide
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


@contextmanager
def _progress() -> Iterator[pipeline.Report]:
    """Progress bars for long steps. Yields a report(stage, fraction_done, note) function."""
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
            yield report
        except (MissingTool, RuntimeError) as error:
            progress.stop()
            raise _fail(str(error)) from error


def _heading(bait: Bait) -> None:
    console.print(
        f"\n[bold]{bait.title}[/]  [dim]{bait.duration / 60:.1f} minutes, id {bait.id}[/]"
    )


def _cut(bait: Bait, **options) -> None:
    """Run the pipeline with progress bars, then hand the drafts to a person."""
    _heading(bait)
    with _progress() as report:
        result = pipeline.run(bait, report=report, **options)

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
    bait = _register(recording, credit, attest)
    _cut(
        bait, spotter=spotter, speech_model=speech_model, allow=allow or [],
        max_clips=max_clips, speaker_labels=speaker_labels, fresh=fresh,
    )  # fmt: skip


def _register(recording: Path, credit: str | None, attest: str | None) -> Bait:
    """Intake: ask for the credit and the rights statement if they were not given."""
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
        return intake.register(recording, credit, attest)
    except (ValueError, MissingTool) as error:
        raise _fail(str(error)) from error


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
        if not recording.exists() or not demo.timings_path(recording).exists() or fresh:
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
    _cut(bait, spotter=spotter, allow=demo.ALLOW, max_clips=max_clips, fresh=fresh)


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


def _find_bait(target: str) -> Bait | None:
    path = workspace.bait_dir(target) / "bait.json"
    return workspace.load(path, Bait) if path.exists() else None


@app.command(name="label")
def label_command(
    target: Annotated[
        str,
        typer.Argument(help="A bait id (see `baitreel review`), or a recording on this computer."),
    ],
    labeler: Annotated[
        str | None, typer.Option(help="Your name. Each person's labels are kept separately.")
    ] = None,
    import_labels: Annotated[
        Path | None,
        typer.Option("--import", help="A label track exported from Audacity, instead of the page."),
    ] = None,
    credit: Annotated[
        str | None, typer.Option(help="Who made the recording, for a new recording.")
    ] = None,
    attest: Annotated[
        str | None, typer.Option(help="Your name, confirming your right to use a new recording.")
    ] = None,
    speech_model: Annotated[
        str, typer.Option(help="The faster-whisper model used for transcription.")
    ] = DEFAULT_MODEL,
    port: Annotated[int, typer.Option(help="Port for the labeling page. 0 picks a free one.")] = 0,
    browser: Annotated[bool, typer.Option(help="Open the page in your web browser.")] = True,
) -> None:
    """Label a call by hand, without seeing Baitreel's answers, so it can be scored."""
    bait = _find_bait(target)
    if bait is None:
        if not Path(target).expanduser().is_file():
            raise _fail(f"{target} is neither a bait id nor a recording. Try: baitreel review")
        bait = _register(Path(target), credit, attest)
    _heading(bait)
    with _progress() as report:
        # Transcribe only. Labeling before Baitreel spots anything keeps it blind.
        transcript = pipeline.transcript_for(bait, speech_model, report=report)

    if labeler is None:
        if not sys.stdin.isatty():
            raise _fail("Say who is labeling with --labeler YOUR_NAME.")
        labeler = Prompt.ask("Your name, so your labels are kept apart from anyone else's")
    if not labeler.strip():
        raise _fail("A labeler name is needed.")
    mine = labels.open_labels(bait.id, labeler, transcript)

    if import_labels is not None:
        try:
            text = import_labels.expanduser().read_text(encoding="utf-8")
            mine.flags, mine.details = labels.read_label_track(text, field_guide(), transcript)
        except (OSError, labels.LabelTrackError) as error:
            raise _fail(str(error)) from error
        mine.source, mine.finished = "audacity", True
        path = labels.save(mine)
        console.print(
            f"Imported {len(mine.flags)} tactic labels and {len(mine.details)} personal details "
            f"from Audacity.\nSaved to {path}\nNext: [bold]baitreel eval[/]"
        )
        return

    from .labeling import LabelingServer

    if mine.tool_ran_first:
        console.print(
            "[yellow]Baitreel has already spotted flags for this call.[/] To keep your labels "
            "blind, do not look at its clips or flags until you finish."
        )
    server = LabelingServer(bait, transcript, mine, port=port)
    console.print(
        f"\nThe labeling page is at [bold]{server.url}[/]\n"
        "[dim]It runs only on this computer. Press Finish on the page when you are done, "
        "or Ctrl+C here to stop. Your labels are saved as you go.[/]"
    )
    if browser:
        webbrowser.open(server.url)
    try:
        server.serve()
    except KeyboardInterrupt:
        console.print("\nStopped. Your labels so far are saved.")
        return
    state = "finished" if server.labels.finished else "saved, not finished"
    console.print(
        f"Labels {state}: {len(server.labels.flags)} tactics, "
        f"{len(server.labels.details)} personal details.\nNext: [bold]baitreel eval[/]"
    )


@app.command(name="eval")
def eval_command(
    bait_ids: Annotated[
        list[str] | None, typer.Argument(help="Baits to score. Omit to score every labeled bait.")
    ] = None,
    model: Annotated[
        list[str] | None,
        typer.Option(help="Also run this local model, such as gemma4:12b. Repeatable. Slow."),
    ] = None,
    reference: Annotated[
        str | None,
        typer.Option(help="Whose labels are the answer key. Default: the first to finish."),
    ] = None,
    out: Annotated[Path | None, typer.Option(help="Where to write the report.")] = None,
    browser: Annotated[bool, typer.Option(help="Open the report when it is ready.")] = True,
) -> None:
    """Score Baitreel's flags and redactions against labels made by hand, and write a report."""
    from . import report as reporting

    if bait_ids:
        baits = [_find_bait(b) for b in bait_ids]
        if None in baits:
            missing = [b for b, found in zip(bait_ids, baits, strict=True) if found is None]
            raise _fail(
                f"No bait with id {', '.join(missing)}. Run `baitreel review` to list them."
            )
    else:
        baits = evaluate.labeled_baits()
    if not baits:
        raise _fail("Nothing is labeled yet. Start with: baitreel label BAIT_ID")

    calls: list[evaluate.Call] = []
    notes: list[str] = []
    for bait in baits:
        _heading(bait)
        with _progress() as report:
            found = evaluate.gather(bait, model or [], reference, report)
        if isinstance(found, str):
            console.print(f"[yellow]Skipped:[/] {found}")
        else:
            calls.append(found)
    if not calls:
        raise _fail("No call could be scored yet.")
    for number, call in enumerate(calls, start=1):
        if call.reference.tool_ran_first:
            notes.append(
                f"Call {number} was labeled after Baitreel had already spotted flags in it. "
                "If the labeler saw them, its labels are not blind."
            )

    result = evaluate.evaluate(calls, notes)
    folder = out or workspace.home() / "eval"
    path = reporting.write(result, folder)

    table = Table("Spotter", "Version", "Calls", "Precision", "Recall", "F1", "Kappa")
    for system in result.systems:
        table.add_row(
            system.name, system.version or "–", str(system.calls),
            *(reporting._pct(v) for v in (system.overall.precision, system.overall.recall,
                                          system.overall.f1)),
            reporting._num(system.kappa),
        )  # fmt: skip
    console.print()
    console.print(table)
    red = result.redaction.overall
    console.print(
        f"Redaction recall: [bold]{reporting._pct(red.recall)}[/] "
        f"({red.covered} of {red.marked} hand-marked details fully bleeped, "
        f"{red.partly} partly, {red.missed} missed)"
    )
    console.print(f"\nReport: {path}\nScores: {folder / 'scores.json'}")
    if browser and sys.stdout.isatty():
        webbrowser.open(path.as_uri())


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
