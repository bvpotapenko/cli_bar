"""Analysis commands: status, volume, plot-max, 1rm."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Optional

import typer

from bar_scheduler.core.adaptation import get_training_status
from bar_scheduler.core.config import TM_FACTOR, expected_reps_per_week
from bar_scheduler.core.exercises.registry import get_exercise
from bar_scheduler.core.metrics import blended_1rm_added, estimate_1rm, session_max_reps as _max_reps, training_max_from_baseline
from bar_scheduler.io.serializers import ValidationError
from cli_bar import views
from cli_bar.app import ExerciseOption, app, get_store
from bar_scheduler.core.i18n import t


def _build_trajectory(
    test_sessions: list,
    target: int,
) -> list[tuple[datetime, float]]:
    """Compute projected trajectory starting from the latest test session.

    target = goal test-max reps (what the user aims to achieve in a TEST).
    Y-values are estimated test-max reps (tm / TM_FACTOR).
    """
    if not test_sessions:
        return []
    latest = test_sessions[-1]
    start_dt = datetime.strptime(latest.date, "%Y-%m-%d")
    initial_tm = training_max_from_baseline(_max_reps(latest))
    tm_target = int(target * TM_FACTOR)  # TM ceiling corresponding to the goal
    points: list[tuple[datetime, float]] = []
    d, tm_f = start_dt, float(initial_tm)
    while tm_f < tm_target and d <= start_dt + timedelta(weeks=104):
        points.append((d, tm_f / TM_FACTOR))
        tm_f = min(tm_f + expected_reps_per_week(int(tm_f), tm_target), float(tm_target))
        d += timedelta(weeks=1)
    points.append((d, float(target)))   # endpoint = exact goal test-max
    return points


@app.command()
def status(
    history_path: Annotated[
        Optional[Path],
        typer.Option("--history-path", "-p", help="Path to history JSONL file"),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output as JSON for machine processing"),
    ] = False,
    exercise_id: ExerciseOption = "pull_up",
) -> None:
    """
    Show current training status.
    """
    store = get_store(history_path, exercise_id)

    if not store.exists():
        views.print_error(t("error.history_not_found", path=store.history_path))
        views.print_info(t("error.run_init_first"))
        raise typer.Exit(1)

    try:
        user_state = store.load_user_state()
    except (FileNotFoundError, ValidationError) as e:
        views.print_error(str(e))
        raise typer.Exit(1)

    status_info = get_training_status(
        user_state.history,
        user_state.current_bodyweight_kg,
    )

    if json_out:
        ff = status_info.fitness_fatigue_state
        print(json.dumps({
            "training_max": status_info.training_max,
            "latest_test_max": status_info.latest_test_max,
            "trend_slope_per_week": round(status_info.trend_slope, 4),
            "is_plateau": status_info.is_plateau,
            "deload_recommended": status_info.deload_recommended,
            "readiness_z_score": round(ff.readiness_z_score(), 4),
            "fitness": round(ff.fitness, 4),
            "fatigue": round(ff.fatigue, 4),
        }, indent=2))
        return

    views.console.print()
    views.console.print(views.format_status_display(status_info))
    views.console.print()


@app.command()
def volume(
    history_path: Annotated[
        Optional[Path],
        typer.Option("--history-path", "-p", help="Path to history JSONL file"),
    ] = None,
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
    store = get_store(history_path, exercise_id)

    if not store.exists():
        views.print_error(t("error.history_not_found", path=store.history_path))
        views.print_info(t("error.run_init_first"))
        raise typer.Exit(1)

    try:
        sessions = store.load_history()
    except (FileNotFoundError, ValidationError) as e:
        views.print_error(str(e))
        raise typer.Exit(1)

    if json_out:
        weekly: dict[int, int] = {}
        if sessions:
            latest = datetime.strptime(sessions[-1].date, "%Y-%m-%d")
            for s in sessions:
                ago = (latest - datetime.strptime(s.date, "%Y-%m-%d")).days // 7
                if ago < weeks:
                    reps = sum(sr.actual_reps for sr in s.completed_sets if sr.actual_reps is not None)
                    weekly[ago] = weekly.get(ago, 0) + reps
        result = []
        for i in range(weeks - 1, -1, -1):
            label = "This week" if i == 0 else ("Last week" if i == 1 else f"{i} weeks ago")
            result.append({"label": label, "total_reps": weekly.get(i, 0)})
        print(json.dumps({"weeks": result}, indent=2))
        return

    views.print_volume_chart(sessions, weeks)


@app.command("plot-max")
def plot_max(
    history_path: Annotated[
        Optional[Path],
        typer.Option("--history-path", "-p", help="Path to history JSONL file"),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output as JSON for machine processing"),
    ] = False,
    trajectory: Annotated[
        Optional[str],
        typer.Option(
            "--trajectory", "-t",
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
      g  reps at goal weight (×) — only for weighted goals
      m  1RM right-axis labels in kg
    Examples: -t z, -t zg, -t zmg
    """
    from bar_scheduler.core.config import TARGET_MAX_REPS
    from bar_scheduler.core.metrics import get_test_sessions

    store = get_store(history_path, exercise_id)

    if not store.exists():
        views.print_error(t("error.history_not_found", path=store.history_path))
        views.print_info(t("error.run_init_first"))
        raise typer.Exit(1)

    try:
        user_state = store.load_user_state()
    except (FileNotFoundError, ValidationError) as e:
        views.print_error(str(e))
        raise typer.Exit(1)

    sessions = user_state.history
    display_name = get_exercise(exercise_id).display_name

    # Parse requested trajectory types
    traj_types: set[str] = set(trajectory.lower()) if trajectory else set()

    traj_z: list[tuple[datetime, float]] | None = None
    traj_g: list[tuple[datetime, float]] | None = None
    traj_m: list[tuple[datetime, float]] | None = None
    traj_z_json: list[dict] | None = None
    traj_g_json: list[dict] | None = None
    traj_m_json: list[dict] | None = None
    traj_target = TARGET_MAX_REPS
    bw_load_kg = 0.0
    target_weight_kg = 0.0

    if traj_types:
        # Use _bw_load locally for all calculations; bw_load_kg is only
        # set for the right axis when "m" is explicitly requested.
        exercise_def = get_exercise(exercise_id)
        _bw_load = user_state.current_bodyweight_kg * exercise_def.bw_fraction

        try:
            profile = store.load_profile()
            ex_target = profile.target_for_exercise(exercise_id) if profile else None
            if ex_target is not None:
                target_weight_kg = ex_target.weight_kg
                if ex_target.weight_kg > 0:
                    full_load = _bw_load + ex_target.weight_kg
                    one_rm = full_load * (1 + ex_target.reps / 30)
                    traj_target = max(int(round(30 * (one_rm / _bw_load - 1))), 1)
                else:
                    traj_target = ex_target.reps
        except Exception:
            pass

        if "m" in traj_types:
            bw_load_kg = _bw_load  # enables right axis

        # Compute base trajectory whenever any trajectory type needs it
        base_pts: list[tuple[datetime, float]] = []
        if traj_types & {"z", "g", "m"}:
            base_pts = _build_trajectory(get_test_sessions(sessions), traj_target)

        # z trajectory
        if base_pts and "z" in traj_types:
            traj_z = base_pts
            traj_z_json = [
                {"date": pt.strftime("%Y-%m-%d"), "projected_bw_reps": round(val, 2)}
                for pt, val in base_pts
            ]

        # g trajectory derived from base_pts
        if "g" in traj_types and base_pts:
            if target_weight_kg > 0:
                f = _bw_load / (_bw_load + target_weight_kg)
                pts_g = [(d, max(0.0, f * z + 30.0 * (f - 1.0))) for d, z in base_pts]
            else:
                # BW goal: g == z (reps at 0 added weight = BW reps)
                pts_g = list(base_pts)
            traj_g = pts_g
            traj_g_json = [
                {"date": pt.strftime("%Y-%m-%d"), "projected_goal_reps": round(val, 2)}
                for pt, val in pts_g
            ]

        # m trajectory: blended non-linear 1RM estimate → added kg (capped at r=20)
        if "m" in traj_types and base_pts and _bw_load > 0:
            m_pts: list[tuple[datetime, float]] = []
            for d, reps in base_pts:
                r = min(int(round(reps)), 20)  # cap; blended_1rm_added returns None above 20
                added = blended_1rm_added(_bw_load, max(r, 1))
                if added is not None:
                    m_pts.append((d, added))
            traj_m = m_pts or None
            if traj_m:
                traj_m_json = [
                    {"date": pt.strftime("%Y-%m-%d"), "projected_1rm_added_kg": round(val, 2)}
                    for pt, val in traj_m
                ]

    if json_out:
        data_points = [
            {"date": s.date, "max_reps": _max_reps(s)}
            for s in get_test_sessions(sessions)
            if _max_reps(s) > 0
        ]
        print(json.dumps({
            "data_points": data_points,
            "trajectory_z": traj_z_json,
            "trajectory_g": traj_g_json,
            "trajectory_m": traj_m_json,
        }, indent=2))
        return

    views.print_max_plot(
        sessions,
        trajectory_z=traj_z,
        trajectory_g=traj_g,
        trajectory_m=traj_m,
        bw_load_kg=bw_load_kg,
        target_weight_kg=target_weight_kg,
        exercise_name=display_name,
        target=traj_target,
        traj_types=traj_types,
    )


@app.command("1rm")
def onerepmax(
    history_path: Annotated[
        Optional[Path],
        typer.Option("--history-path", "-p", help="Path to history JSONL file"),
    ] = None,
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
    exercise = get_exercise(exercise_id)
    store = get_store(history_path, exercise_id)

    if not store.exists():
        views.print_error(t("error.history_not_found", path=store.history_path))
        views.print_info(t("error.run_init_first"))
        raise typer.Exit(1)

    try:
        user_state = store.load_user_state()
    except (FileNotFoundError, ValidationError) as e:
        views.print_error(str(e))
        raise typer.Exit(1)

    result = estimate_1rm(exercise, user_state.current_bodyweight_kg, user_state.history)

    if result is None:
        views.print_error(t("error.no_1rm_data"))
        raise typer.Exit(1)

    if json_out:
        print(json.dumps(result, indent=2))
        return

    bw = user_state.current_bodyweight_kg
    added = result["best_added_weight_kg"]
    bw_frac = result["bw_fraction"]
    reps = result["best_reps"]
    rec = result["recommended_formula"]
    if exercise.onerm_includes_bodyweight:
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
        ("epley",    "Epley",    "general purpose; tends to overestimate at r > 10"),
        ("brzycki",  "Brzycki",  "most accurate for r ≤ 10"),
        ("lander",   "Lander",   "most accurate for r ≤ 10"),
        ("lombardi", "Lombardi", "better for r > 10; less reliable at low reps"),
        ("blended",  "Blended",  "rep-range weighted average (recommended)"),
    ]

    views.console.print()
    views.console.print(f"[bold cyan]1RM Estimate — {exercise.display_name}[/bold cyan]")
    views.console.print(f"  Bodyweight:  {bw:.1f} kg")
    views.console.print(f"  Best set:    {reps} reps @ +{added:.1f} kg added  ({result['best_date']})")
    views.console.print(f"  Total load:  {result['effective_load_kg']:.1f} kg  ({load_details})")
    views.console.print()

    sep = "  " + "─" * 62
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
    views.console.print(f"  ★ = most representative for {reps}-rep set  (recommended: {rec})")
    views.console.print()
    views.console.print(f"  {exercise.onerm_explanation}")
    views.console.print()


# ---------------------------------------------------------------------------
# Adaptation timeline help text (task.md §7)
# ---------------------------------------------------------------------------

_ADAPTATION_GUIDE = """\
HOW THE PLANNER LEARNS FROM YOUR DATA

This planner is adaptive. Here is what it knows at each stage:

┌─────────────────┬──────────────────────────────────────────────────────┐
│ Stage           │ What the model can do                                │
├─────────────────┼──────────────────────────────────────────────────────┤
│ Day 1           │ Generic safe plan from your baseline max.            │
│ (no history)    │ Conservative volume. No weighted work until TM > 9.  │
│                 │ RECOMMENDATION: Just follow the plan and log.        │
├─────────────────┼──────────────────────────────────────────────────────┤
│ Weeks 1–2       │ EWMA max estimate starts tracking.                   │
│ (3–8 sessions)  │ Rest normalization active (short rest gets credit).  │
│                 │ NO autoregulation yet (not enough data).             │
│                 │ RECOMMENDATION: Log rest times accurately.           │
├─────────────────┼──────────────────────────────────────────────────────┤
│ Weeks 3–4       │ AUTOREGULATION ACTIVATES (≥10 sessions).             │
│ (10–16 sessions)│ Plateau detection possible.                          │
│                 │ Rest adaptation kicks in (RIR + drop-off based).     │
│                 │ RECOMMENDATION: Do your first re-test (TEST session).│
├─────────────────┼──────────────────────────────────────────────────────┤
│ Weeks 6–8       │ Individual fatigue profile fitted.                   │
│ (24–32 sessions)│ Set-to-set predictions improve.                      │
│                 │ Deload triggers become reliable.                     │
│                 │ RECOMMENDATION: Trust the deload if recommended.     │
├─────────────────┼──────────────────────────────────────────────────────┤
│ Weeks 12+       │ Full training profile established.                   │
│ (48+ sessions)  │ Long-term fitness adaptation curve accurate.         │
│                 │ Progression rate calibrated to your response.        │
│                 │ RECOMMENDATION: Model is at peak accuracy.           │
└─────────────────┴──────────────────────────────────────────────────────┘

TIPS FOR BEST RESULTS:
• Log every session, including bad ones (RIR=0, incomplete sets = valuable data)
• Log rest times, even approximate
• Do a TEST session every 3–4 weeks (anchors the max estimate)
• Update bodyweight when it changes by ≥1 kg
• Past prescriptions are frozen — only future sessions adapt
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
