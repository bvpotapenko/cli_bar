"""Analysis commands: status, volume, plot-max, 1rm."""

import json
from datetime import datetime
from typing import Annotated, Optional

import typer

from bar_scheduler.api import (
    get_training_status as api_status,
    get_volume_data,
    get_progress_data,
    get_onerepmax_data,
    get_ebr_data,
    get_goal_progress,
    get_profile,
    get_exercise_info,
    ProfileNotFoundError,
    HistoryNotFoundError,
)
from cli_bar import views
from cli_bar.app import ExerciseOption, app, effective_data_dir
from cli_bar.i18n import t


def _traj_to_points(
    items: list[dict] | None, value_key: str
) -> list[tuple[datetime, float]] | None:
    """Convert API trajectory dict list to (datetime, float) tuples for ascii_plot."""
    if not items:
        return None
    return [(datetime.strptime(d["date"], "%Y-%m-%d"), d[value_key]) for d in items]


@app.command()
def status(
    json_out: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output as JSON for machine processing"),
    ] = False,
    exercise_id: ExerciseOption = "pull_up",
) -> None:
    """
    Show current training status.
    """
    try:
        status_info = api_status(effective_data_dir(), exercise_id)
    except (ProfileNotFoundError, HistoryNotFoundError) as e:
        views.print_error(str(e))
        views.print_info(t("error.run_init_first"))
        raise typer.Exit(1)

    if json_out:
        print(json.dumps(status_info, indent=2))
        return

    exercise_target: dict | None = None
    goal_progress: dict | None = None
    try:
        profile_dict = get_profile(effective_data_dir())
        if profile_dict:
            exercise_target = profile_dict.get("exercise_targets", {}).get(exercise_id)
            if exercise_target:
                goal_progress = get_goal_progress(effective_data_dir(), exercise_id)
    except Exception:
        pass

    views.console.print()
    views.console.print(views.format_status_display(status_info, exercise_target=exercise_target, goal_progress=goal_progress))
    views.console.print()


@app.command()
def volume(
    weeks: Annotated[
        int,
        typer.Option("--weeks", "-w", help="Number of weeks to show"),
    ] = 4,
    json_out: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output as JSON for machine processing"),
    ] = False,
    exercise_id: ExerciseOption = "pull_up",
) -> None:
    """
    Show weekly volume chart.
    """
    try:
        volume_data = get_volume_data(effective_data_dir(), exercise_id, weeks=weeks)
    except (ProfileNotFoundError, HistoryNotFoundError) as e:
        views.print_error(str(e))
        views.print_info(t("error.run_init_first"))
        raise typer.Exit(1)

    if json_out:
        print(json.dumps(volume_data, indent=2))
        return

    views.print_volume_chart(volume_data)


@app.command("plot-max")
def plot_max(
    json_out: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output as JSON for machine processing"),
    ] = False,
    trajectory: Annotated[
        Optional[str],
        typer.Option(
            "--trajectory",
            "-t",
            help=(
                "Trajectory lines to overlay. Letters: z=BW reps, g=goal reps, "
                "m=added-kg @1RM right axis. Combine: -t zg, -t zmg."
            ),
        ),
    ] = None,
    exercise_id: ExerciseOption = "pull_up",
) -> None:
    """
    Display ASCII plot of max reps progress.

    Use --trajectory with one or more letters to overlay projected lines:
      z  bodyweight max reps (·)
      g  reps at goal weight (×) -- only for weighted goals
      m  1RM right-axis labels in kg
    Examples: -t z, -t zg, -t zmg
    """
    try:
        prog = get_progress_data(
            effective_data_dir(), exercise_id, trajectory_types=trajectory or ""
        )
    except (ProfileNotFoundError, HistoryNotFoundError) as e:
        views.print_error(str(e))
        views.print_info(t("error.run_init_first"))
        raise typer.Exit(1)

    if json_out:
        print(json.dumps(prog, indent=2))
        return

    traj_z = _traj_to_points(prog.get("trajectory_z"), "projected_bw_reps")
    traj_g = _traj_to_points(prog.get("trajectory_g"), "projected_goal_reps")
    traj_m = _traj_to_points(prog.get("trajectory_m"), "projected_1rm_added_kg")

    # Derive display metadata from exercise + profile
    exercise = get_exercise_info(exercise_id)
    bw_load_kg = 0.0
    target_weight_kg = 0.0
    traj_target = 30

    if trajectory:
        profile = get_profile(effective_data_dir())
        if profile:
            bw = profile.get("current_bodyweight_kg", 0.0)
            ex_targets = profile.get("exercise_targets", {})
            ex_target = ex_targets.get(exercise_id)
            if ex_target:
                target_weight_kg = ex_target.get("weight_kg", 0.0)
                traj_target = ex_target.get("reps", 30)
            if "m" in trajectory:
                bw_load_kg = bw * exercise["bw_fraction"]

    traj_types: set[str] = set(trajectory.lower()) if trajectory else set()

    views.print_max_plot(
        prog["data_points"],
        trajectory_z=traj_z,
        trajectory_g=traj_g,
        trajectory_m=traj_m,
        bw_load_kg=bw_load_kg,
        target_weight_kg=target_weight_kg,
        exercise_name=exercise["display_name"],
        target=traj_target,
        traj_types=traj_types,
    )


@app.command("1rm")
def onerepmax(
    json_out: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output as JSON for machine processing"),
    ] = False,
    exercise_id: ExerciseOption = "pull_up",
) -> None:
    """
    Estimate 1-rep max using multiple formulas.

    Scans recent sessions for the best loaded set and computes 1RM via five
    formulas. The best set is selected using the Epley estimate. The most
    accurate formula is highlighted with ★ based on the rep count.

    For pull-ups/dips: total_load = bodyweight × bw_fraction + added_weight.
    For BSS:           total_load = added_weight (external only).
    """
    exercise = get_exercise_info(exercise_id)

    try:
        result = get_onerepmax_data(effective_data_dir(), exercise_id)
    except (ProfileNotFoundError, HistoryNotFoundError) as e:
        views.print_error(str(e))
        views.print_info(t("error.run_init_first"))
        raise typer.Exit(1)

    if result is None:
        views.print_error(t("error.no_1rm_data"))
        raise typer.Exit(1)

    if json_out:
        print(json.dumps(result, indent=2))
        return

    bw = result["bodyweight_kg"]
    added = result["best_added_weight_kg"]
    bw_frac = result["bw_fraction"]
    reps = result["best_reps"]
    rec = result["recommended_formula"]
    if exercise.get("onerm_includes_bodyweight", True):
        load_details = f"{bw:.1f} kg BW × {bw_frac} + {added:.1f} kg added"
    else:
        load_details = f"{added:.1f} kg external load"

    # Determine which formulas to highlight with ★
    if reps <= 10:
        starred = {"brzycki", "lander"}
    elif reps <= 20:
        starred = {"blended"}
    else:
        starred = {"epley"}

    formula_meta = [
        ("epley", "Epley", "general purpose; tends to overestimate at r > 10"),
        ("brzycki", "Brzycki", "most accurate for r ≤ 10"),
        ("lander", "Lander", "most accurate for r ≤ 10"),
        ("lombardi", "Lombardi", "better for r > 10; less reliable at low reps"),
        ("blended", "Blended", "rep-range weighted average (recommended)"),
    ]

    views.console.print()
    views.console.print(
        f"[bold cyan]1RM Estimate -- {exercise['display_name']}[/bold cyan]"
    )
    views.console.print(f"  Bodyweight:  {bw:.1f} kg")
    views.console.print(
        f"  Best set:    {reps} reps @ +{added:.1f} kg added  ({result['best_date']})"
    )
    views.console.print(
        f"  Total load:  {result['effective_load_kg']:.1f} kg  ({load_details})"
    )
    views.console.print()

    sep = "  " + "-" * 62
    views.console.print(f"  {'Formula':<12}{'1RM':>8}    Notes")
    views.console.print(sep)
    fmls = result["formulas"]
    for key, label, note in formula_meta:
        val = fmls.get(key)
        if val is None:
            val_str = "  n/a  "
        else:
            val_str = f"{val:6.1f} kg"
        star = " ★" if key in starred else "  "
        views.console.print(f"  {label:<12}{val_str}{star}  {note}")
    views.console.print(sep)
    views.console.print(
        f"  ★ = most representative for {reps}-rep set  (recommended: {rec})"
    )
    views.console.print()
    onerm_explanation = exercise.get("onerm_explanation", "")
    if onerm_explanation:
        views.console.print(f"  {onerm_explanation}")
    views.console.print()


@app.command("ebr-plot")
def ebr_plot(
    weeks_ahead: Annotated[
        int,
        typer.Option("--weeks", "-w", help="Number of weeks ahead to project EBR"),
    ] = 4,
    json_out: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output raw EBR data as JSON"),
    ] = False,
    exercise_id: ExerciseOption = "pull_up",
) -> None:
    """
    Plot per-session EBR (Equivalent Bodyweight Reps) over time (history + projected plan).

    Shows how session difficulty has grown and where it's heading. If a goal is set,
    a reference line shows how far you are from goal-level EBR.
    """
    try:
        ebr_data = get_ebr_data(effective_data_dir(), exercise_id, weeks_ahead=weeks_ahead)
    except (ProfileNotFoundError, HistoryNotFoundError) as e:
        views.print_error(str(e))
        views.print_info(t("error.run_init_first"))
        raise typer.Exit(1)

    if json_out:
        print(json.dumps(ebr_data, indent=2))
        return

    exercise = get_exercise_info(exercise_id)

    goal_progress: dict | None = None
    goal_description = ""
    try:
        profile = get_profile(effective_data_dir())
        if profile:
            ex_target = profile.get("exercise_targets", {}).get(exercise_id)
            if ex_target:
                goal_progress = get_goal_progress(effective_data_dir(), exercise_id)
                goal_reps = ex_target.get("reps", 0)
                goal_weight_kg = ex_target.get("weight_kg", 0.0)
                goal_description = f"{goal_reps} reps"
                if goal_weight_kg > 0:
                    goal_description += f" @ +{goal_weight_kg:.1f} kg"
    except Exception:
        pass

    views.print_ebr_chart(
        ebr_data,
        exercise_name=exercise["display_name"],
        goal_progress=goal_progress,
        goal_description=goal_description,
    )


# ---------------------------------------------------------------------------
# Adaptation timeline help text (task.md §7)
# ---------------------------------------------------------------------------

_ADAPTATION_GUIDE = """\
HOW THE PLANNER LEARNS FROM YOUR DATA

This planner is adaptive. Here is what it knows at each stage:

┌-----------------┬------------------------------------------------------┐
│ Stage           │ What the model can do                                │
├-----------------┼------------------------------------------------------┤
│ Day 1           │ Generic safe plan from your baseline max.            │
│ (no history)    │ Conservative volume. No weighted work until TM > 9.  │
│                 │ RECOMMENDATION: Just follow the plan and log.        │
├-----------------┼------------------------------------------------------┤
│ Weeks 1–2       │ EWMA max estimate starts tracking.                   │
│ (3–8 sessions)  │ Rest normalization active (short rest gets credit).  │
│                 │ NO autoregulation yet (not enough data).             │
│                 │ RECOMMENDATION: Log rest times accurately.           │
├-----------------┼------------------------------------------------------┤
│ Weeks 3–4       │ AUTOREGULATION ACTIVATES (≥10 sessions).             │
│ (10–16 sessions)│ Plateau detection possible.                          │
│                 │ Rest adaptation kicks in (RIR + drop-off based).     │
│                 │ RECOMMENDATION: Do your first re-test (TEST session).│
├-----------------┼------------------------------------------------------┤
│ Weeks 6–8       │ Individual fatigue profile fitted.                   │
│ (24–32 sessions)│ Set-to-set predictions improve.                      │
│                 │ Deload triggers become reliable.                     │
│                 │ RECOMMENDATION: Trust the deload if recommended.     │
├-----------------┼------------------------------------------------------┤
│ Weeks 12+       │ Full training profile established.                   │
│ (48+ sessions)  │ Long-term fitness adaptation curve accurate.         │
│                 │ Progression rate calibrated to your response.        │
│                 │ RECOMMENDATION: Model is at peak accuracy.           │
└-----------------┴------------------------------------------------------┘

TIPS FOR BEST RESULTS:
• Log every session, including bad ones (RIR=0, incomplete sets = valuable data)
• Log rest times, even approximate
• Do a TEST session every 3–4 weeks (anchors the max estimate)
• Update bodyweight when it changes by ≥1 kg
• Past prescriptions are frozen -- only future sessions adapt
• Different exercises have separate plans and separate adaptation timelines
"""


@app.command("help-adaptation")
def help_adaptation() -> None:
    """
    Explain how the planner adapts over time.

    Shows the adaptation timeline: what the model can predict at each
    stage (day 1, weeks 1–2, weeks 3–4, weeks 6–8, weeks 12+) and
    tips for getting the best results.

    See also: docs/adaptation_guide.md
    """
    views.console.print()
    views.console.print(_ADAPTATION_GUIDE)
