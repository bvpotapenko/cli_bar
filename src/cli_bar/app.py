"""Shared Typer app object, shared option types, and store utility."""

from pathlib import Path
from typing import Annotated, Optional

import typer

from bar_scheduler.io.history_store import HistoryStore, get_default_history_path, get_profile_store

# Overperformance: reps above training max that trigger personal-best detection
OVERPERFORMANCE_REP_THRESHOLD = 2

# Shared --exercise option type used across all commands
ExerciseOption = Annotated[
    str,
    typer.Option("--exercise", "-e", help="Exercise ID: pull_up (default), dip, bss"),
]

# Shared --lang option type: optional language override
LangOption = Annotated[
    Optional[str],
    typer.Option("--lang", "-l", help="Language override (en, ru, zh). Overrides profile setting."),
]

app = typer.Typer(
    name="bar-scheduler",
    help="Evidence-informed strength training planner.",
    no_args_is_help=False,
    invoke_without_command=True,
)


def get_store(history_path: Path | None, exercise_id: str = "pull_up") -> HistoryStore:
    """Get history store from path or default location for the given exercise."""
    if history_path is None:
        history_path = get_default_history_path(exercise_id)
    return HistoryStore(history_path, exercise_id=exercise_id)
