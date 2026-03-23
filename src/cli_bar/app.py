"""Shared Typer app object and shared option types."""

from pathlib import Path
from typing import Annotated, Optional

import typer

# Overperformance: reps above training max that trigger personal-best detection
OVERPERFORMANCE_REP_THRESHOLD = 2

# Set by --history-path global flag; None means use library default (~/.bar-scheduler)
_data_dir_override: Path | None = None


def effective_data_dir() -> Path:
    """Return the active data directory (override if --history-path was given, else default)."""
    if _data_dir_override is not None:
        return _data_dir_override
    from bar_scheduler.api.api import get_data_dir
    return get_data_dir()


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

# Shared --history-path option type: optional data directory override
HistoryPathOption = Annotated[
    Optional[Path],
    typer.Option(
        "--history-path", "-p",
        help="Override data directory (default: ~/.bar-scheduler). Use for alternative profiles or safe testing.",
    ),
]

app = typer.Typer(
    name="bar-scheduler",
    help="Evidence-informed strength training planner.",
    no_args_is_help=False,
    invoke_without_command=True,
)
