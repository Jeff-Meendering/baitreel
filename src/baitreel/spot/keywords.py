"""The keyword spotter: Field Guide cue patterns and nothing else.

It needs no model and always gives the same answer, which makes it a useful
baseline. It cannot tell who is speaking or understand context, so it flags
more false alarms than a language model does.
"""

from __future__ import annotations

from ..fieldguide import Tactic
from ..models import Flag
from . import Line, cue_matches


def spot(lines: list[Line], guide: dict[str, Tactic]) -> list[Flag]:
    flags: list[Flag] = []
    for line in lines:
        for tactic in guide.values():
            cues = cue_matches(tactic, line.text)
            if not cues:
                continue
            flags.append(
                Flag(
                    id=f"{tactic.id}@{line.id}",
                    tactic=tactic.id,
                    first_segment=line.id,
                    last_segment=line.id,
                    start=line.start,
                    end=line.end,
                    quote=line.text,
                    cues=cues[:3],
                    why="Matched Field Guide cue words.",
                    teachability=min(1 + len(cues), 4),
                    spotter="keywords",
                )
            )
    return flags
