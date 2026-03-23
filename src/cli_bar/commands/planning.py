"""Planning commands: plan, explain, and interactive menu helpers."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Optional

import typer

from bar_scheduler.core.adaptation import get_training_status, overtraining_severity
from bar_scheduler.core.exercises.registry import get_exercise
from bar_scheduler.core.metrics import training_max_from_baseline
from bar_scheduler.core.models import SessionResult, SetResult
from bar_scheduler.core.planner import explain_plan_entry, generate_plan
from bar_scheduler.io.serializers import ValidationError
from cli_bar import views
from cli_bar.app import ExerciseOption, app, get_store
from bar_scheduler.core.i18n import t


def _resolve_plan_start(store, user_state, default_offset_days: int = 1) -> str:
    """Return plan_start_date from store, or fall back to first history date + offset."""
    plan_start_date = store.get_plan_start_date()
    if plan_start_date is None:
        if user_state.history:
            first_dt = datetime.strptime(user_state.history[0].date, "%Y-%m-%d")
            plan_start_date = (first_dt + timedelta(days=default_offset_days)).strftime("%Y-%m-%d")
        else:
            plan_start_date = (datetime.now() + timedelta(days=default_offset_days)).strftime("%Y-%m-%d")
    return plan_start_date


def _total_weeks(plan_start_date: str, weeks_ahead: int = 4) -> int:
    """Return total plan horizon in weeks, clamped to [2, MAX_PLAN_WEEKS*3]."""
    from bar_scheduler.core.config import MAX_PLAN_WEEKS
    plan_start_dt = datetime.strptime(plan_start_date, "%Y-%m-%d")
    weeks_since_start = max(0, (datetime.now() - plan_start_dt).days // 7)
    return max(2, min(weeks_since_start + weeks_ahead, MAX_PLAN_WEEKS * 3))


def _prompt_baseline(store, bodyweight_kg: float, exercise) -> int | None:
    """
    Prompt user to enter their baseline max reps when no history exists.

    Logs a TEST session and returns the rep count, or None if cancelled.
    """
    ex_name = exercise.display_name  # e.g. "Pull-Up", "Parallel Bar Dip"

    views.console.print()
    views.print_warning(t("plan.no_history", exercise_name=ex_name))
    views.console.print(t("plan.baseline_prompt_intro", exercise_name=ex_name))
    views.console.print(t("plan.baseline_option_1"))
    views.console.print(t("plan.baseline_option_2"))
    views.console.print(t("plan.baseline_option_3"))
    choice = views.console.input(t("plan.baseline_choice_prompt")).strip() or "1"

    if choice == "3":
        return None

    if choice == "2":
        max_reps = 1
    else:
        while True:
            raw = views.console.input(
                t("plan.max_reps_prompt", exercise_name=ex_name)
            ).strip()
            try:
                max_reps = int(raw)
                if max_reps < 1:
                    raise ValueError
                break
            except ValueError:
                views.print_error(t("plan.max_reps_error"))

    today = datetime.now().strftime("%Y-%m-%d")
    test_set = SetResult(
        target_reps=max_reps,
        actual_reps=max_reps,
        rest_seconds_before=180,
        added_weight_kg=0.0,
        rir_target=0,
        rir_reported=0,
    )
    session = SessionResult(
        date=today,
        bodyweight_kg=bodyweight_kg,
        grip=exercise.primary_variant,
        session_type="TEST",
        exercise_id=exercise.exercise_id,
        planned_sets=[test_set],
        completed_sets=[test_set],
        notes=f"Baseline max test ({ex_name}, entered during plan setup)",
    )
    store.append_session(session)
    tm = training_max_from_baseline(max_reps)
    views.print_success(t("plan.logged_baseline", reps=max_reps, tm=tm))
    return max_reps


def _session_snapshot(entry) -> dict:
    """Create a compact plan snapshot dict from a timeline entry (for cache diffing)."""
    p = entry.planned
    if p is None:
        return {}
    first_set = p.sets[0] if p.sets else None
    return {
        "date": p.date,
        "type": p.session_type,
        "sets": len(p.sets),
        "reps": first_set.target_reps if first_set else 0,
        "weight": first_set.added_weight_kg if first_set else 0.0,
        "rest": first_set.rest_seconds_before if first_set else 0,
        "expected_tm": p.expected_tm,
    }


def _diff_plan(old: list[dict], new: list[dict]) -> list[str]:
    """Compare old and new plan snapshots; return human-readable change strings."""
    old_idx = {(s["date"], s["type"]): s for s in old if s}
    new_idx = {(s["date"], s["type"]): s for s in new if s}
    changes: list[str] = []

    for key, snap in new_idx.items():
        if key not in old_idx:
            changes.append(f"New: {snap['date']} {snap['type']}")

    for key, snap in old_idx.items():
        if key not in new_idx:
            changes.append(f"Removed: {snap['date']} {snap['type']}")

    for key in sorted(set(old_idx) & set(new_idx)):
        o, n = old_idx[key], new_idx[key]
        parts: list[str] = []
        if o["sets"] != n["sets"]:
            parts.append(f"{o['sets']}→{n['sets']} sets")
        if o["reps"] != n["reps"]:
            parts.append(f"{o['reps']}→{n['reps']} reps")
        if abs(o.get("weight", 0.0) - n.get("weight", 0.0)) > 0.01:
            parts.append(f"+{o['weight']:.1f}→+{n['weight']:.1f} kg")
        if o["expected_tm"] != n["expected_tm"]:
            parts.append(f"TM {o['expected_tm']}→{n['expected_tm']}")
        if parts:
            changes.append(f"{n['date']} {n['type']}: {', '.join(parts)}")

    return changes


def _menu_explain(exercise_id: str) -> None:
    """Interactive explain helper called from the main menu."""
    exercise = get_exercise(exercise_id)
    store = get_store(None, exercise_id)
    try:
        user_state = store.load_user_state()
    except Exception as e:
        views.print_error(str(e))
        return

    plan_start_date = _resolve_plan_start(store, user_state)
    total_weeks = _total_weeks(plan_start_date)

    views.console.print()
    date_input = views.console.input(t("plan.explain_date_prompt")).strip() or "next"

    # Compute overtraining severity — only applies near-term (see cutoff below)
    ot_severity = overtraining_severity(user_state.history,
                                        user_state.profile.preferred_days_per_week)
    ot_level = ot_severity["level"]
    ot_rest = ot_severity["extra_rest_days"] if ot_level >= 2 else 0

    today_dt = datetime.now()
    ot_cutoff = (today_dt + timedelta(days=max(ot_rest + 14, 14))).strftime("%Y-%m-%d")

    if date_input.lower() == "next":
        try:
            plans = generate_plan(user_state, plan_start_date, exercise,
                                  weeks_ahead=total_weeks,
                                  overtraining_level=ot_level, overtraining_rest_days=ot_rest)
        except ValueError as e:
            views.print_error(str(e))
            return
        today_str = today_dt.strftime("%Y-%m-%d")
        nxt = next((p for p in plans if p.date >= today_str), None)
        if nxt is None:
            views.print_error(t("plan.no_upcoming"))
            return
        date_input = nxt.date

    # Don't apply overtraining shift for dates beyond the near-term recovery window
    if date_input > ot_cutoff:
        ot_level, ot_rest = 0, 0

    result = explain_plan_entry(user_state, plan_start_date, date_input, exercise,
                                weeks_ahead=total_weeks,
                                overtraining_level=ot_level,
                                overtraining_rest_days=ot_rest)
    views.console.print()
    views.console.print(result)
    views.console.print()


@app.command()
def plan(
    weeks: Annotated[
        Optional[int],
        typer.Option("--weeks", "-w", help="Number of weeks to show ahead (default: 4)"),
    ] = None,
    history_path: Annotated[
        Optional[Path],
        typer.Option("--history-path", "-p", help="Path to history JSONL file"),
    ] = None,
    baseline_max: Annotated[
        Optional[int],
        typer.Option("--baseline-max", "-b", help="Baseline max reps (if no history)"),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output as JSON for machine processing"),
    ] = False,
    exercise_id: ExerciseOption = "pull_up",
) -> None:
    """
    Show the full training log: past results + upcoming plan in one view.

    Past sessions show what was planned vs what was actually done.
    Future sessions show what is prescribed next.
    The > marker shows your next session.
    """
    import json

    exercise = get_exercise(exercise_id)
    store = get_store(history_path, exercise_id)

    if not store.exists():
        views.print_error(t("error.history_not_found", path=store.history_path))
        views.print_info(t("error.run_init_first"))
        raise typer.Exit(1)

    try:
        user_state = store.load_user_state()
    except FileNotFoundError as e:
        views.print_error(str(e))
        views.print_info(t("error.run_init_profile"))
        raise typer.Exit(1)
    except ValidationError as e:
        views.print_error(t("error.invalid_data", error=e))
        raise typer.Exit(1)

    if not user_state.history and baseline_max is None:
        baseline_max = _prompt_baseline(store, user_state.current_bodyweight_kg, exercise)
        if baseline_max is None:
            raise typer.Exit(0)
        # Reload state now that the baseline TEST session has been logged
        user_state = store.load_user_state()

    # Determine where the plan started (set by init; fall back to first history date)
    plan_start_date = _resolve_plan_start(store, user_state)

    # Generate plan for enough weeks to cover history + ahead
    if weeks is not None:
        weeks_ahead = weeks
        store.set_plan_weeks(weeks)
    else:
        weeks_ahead = store.get_plan_weeks() or 4
    total_weeks = _total_weeks(plan_start_date, weeks_ahead)

    # Overtraining detection — check before generating plan so level can be passed in
    days_per_week = user_state.profile.preferred_days_per_week
    severity = overtraining_severity(user_state.history, days_per_week)
    overtraining_level = severity["level"]

    try:
        plans = generate_plan(
            user_state, plan_start_date, exercise,
            weeks_ahead=total_weeks, baseline_max=baseline_max,
            overtraining_level=overtraining_level,
        )
    except ValueError as e:
        views.print_error(str(e))
        raise typer.Exit(1)

    training_status = get_training_status(
        user_state.history,
        user_state.current_bodyweight_kg,
        baseline_max,
    )

    # Build unified timeline
    timeline = views.build_timeline(plans, user_state.history)

    # Plan change detection
    old_cache = store.load_plan_cache()
    new_cache = [
        _session_snapshot(e)
        for e in timeline
        if e.status in ("next", "planned") and e.planned is not None
    ]
    plan_changes = _diff_plan(old_cache, new_cache) if old_cache is not None else []
    store.save_plan_cache(new_cache)

    if json_out:
        ff = training_status.fitness_fatigue_state
        sessions_json = []
        for e in timeline:
            # For logged sessions, show the actual type/grip (what was done);
            # for future slots, show the planned type/grip.
            plan_type = e.actual.session_type if e.actual else (e.planned.session_type if e.planned else "")
            plan_grip = e.actual.grip if e.actual else (e.planned.grip if e.planned else "")
            # For logged sessions, prescribed_sets comes from the stored planned_sets
            # in the actual session record (what was planned when the session was logged).
            # This keeps the prescription stable across backward skips — the current plan
            # may generate a different slot at the same date after a shift.
            if e.actual is not None:
                prescribed = [
                    {"reps": ps.target_reps, "weight_kg": ps.added_weight_kg, "rest_s": ps.rest_seconds_before}
                    for ps in e.actual.planned_sets
                ] if e.actual.planned_sets else None
            else:
                prescribed = [
                    {"reps": ps.target_reps, "weight_kg": ps.added_weight_kg, "rest_s": ps.rest_seconds_before}
                    for ps in e.planned.sets
                ] if e.planned else None
            session_obj: dict = {
                "date": e.date,
                "week": e.week_number,
                "type": plan_type,
                "grip": plan_grip,
                "status": e.status,
                "id": e.actual_id,
                "expected_tm": e.planned.expected_tm if e.planned else None,
                "prescribed_sets": prescribed,
                "actual_sets": [
                    {"reps": sr.actual_reps, "weight_kg": sr.added_weight_kg, "rest_s": sr.rest_seconds_before}
                    for sr in e.actual.completed_sets
                    if sr.actual_reps is not None
                ] if e.actual else None,
            }
            sessions_json.append(session_obj)
        print(json.dumps({
            "status": {
                "training_max": training_status.training_max,
                "latest_test_max": training_status.latest_test_max,
                "trend_slope_per_week": round(training_status.trend_slope, 4),
                "is_plateau": training_status.is_plateau,
                "deload_recommended": training_status.deload_recommended,
                "readiness_z_score": round(ff.readiness_z_score(), 4),
            },
            "sessions": sessions_json,
            "plan_changes": plan_changes,
        }, indent=2))
        return

    if plan_changes:
        views.console.print(t("plan.updated_header"))
        for c in plan_changes[:5]:
            views.console.print(f"  {c}")
        views.console.print()

    # Overtraining density warning
    if overtraining_level >= 3:
        extra = severity["extra_rest_days"]
        desc = severity["description"]
        views.console.print(t("overtraining.level3_header", desc=desc))
        views.console.print(t("overtraining.level3_recovery", extra=extra))
        views.console.print(t("overtraining.level3_adjusted", level=overtraining_level))
        views.console.print(t("overtraining.level3_skip_hint", extra=extra))
        views.console.print()
    elif overtraining_level == 2:
        desc = severity["description"]
        extra = severity["extra_rest_days"]
        views.console.print(t("overtraining.level2_header", desc=desc))
        views.console.print(t("overtraining.level2_adjusted"))
        if extra > 0:
            views.console.print(t("overtraining.level2_skip_hint", extra=extra))
        views.console.print()
    elif overtraining_level == 1:
        desc = severity["description"]
        views.console.print(t("overtraining.level1", desc=desc))
        views.console.print()

    # Volume cap warnings — informational only, plan is still executed as-is
    from bar_scheduler.core.config import MAX_DAILY_REPS, MAX_DAILY_SETS
    today_str = datetime.now().strftime("%Y-%m-%d")
    overloaded = [
        p for p in plans
        if p.date >= today_str and p.sets and (
            p.total_reps > MAX_DAILY_REPS or len(p.sets) > MAX_DAILY_SETS
        )
    ]
    if overloaded:
        days_per_week = user_state.profile.preferred_days_per_week
        views.console.print(
            t("volume.ceiling_warning", count=len(overloaded), max_reps=MAX_DAILY_REPS, max_sets=MAX_DAILY_SETS)
        )
        if days_per_week < 6:
            views.console.print(
                t("volume.tip_increase_days", current=days_per_week, next=days_per_week + 1)
            )
        else:
            views.console.print(t("volume.tip_reduce_weekly"))
        views.console.print()

    exercise_target = user_state.profile.target_for_exercise(exercise_id)
    goal_reached = False
    if exercise_target is not None and training_status.latest_test_max is not None and training_status.latest_test_max >= exercise_target.reps:
        if exercise_target.weight_kg == 0.0:
            goal_reached = True
        else:
            # Weight-gated goal: check if the latest TEST session used at least target weight
            test_sessions = [s for s in user_state.history if s.session_type == "TEST"]
            if test_sessions:
                last_test = max(test_sessions, key=lambda s: s.date)
                best_weight = max(
                    (st.added_weight_kg for st in last_test.completed_sets),
                    default=0.0,
                )
                goal_reached = best_weight >= exercise_target.weight_kg
    if goal_reached:
        views.console.print(t("plan.goal_reached", goal=exercise_target))

    # Load equipment state for display
    equipment_state = None
    try:
        equipment_state = store.load_current_equipment(exercise_id)
    except Exception:
        pass

    views.print_unified_plan(
        timeline,
        training_status,
        exercise_target=exercise_target,
        equipment_state=equipment_state,
        history=user_state.history,
        exercise_id=exercise_id,
        bodyweight_kg=user_state.current_bodyweight_kg,
    )


@app.command()
def explain(
    date: Annotated[
        str,
        typer.Argument(
            help="Date to explain (YYYY-MM-DD) or 'next' for the next upcoming session"
        ),
    ],
    history_path: Annotated[
        Optional[Path],
        typer.Option("--history-path", "-p", help="Path to history JSONL file"),
    ] = None,
    weeks: Annotated[
        Optional[int],
        typer.Option("--weeks", "-w", help="Plan horizon in weeks"),
    ] = None,
    exercise_id: ExerciseOption = "pull_up",
) -> None:
    """Show exactly how a planned session's parameters were calculated."""
    exercise = get_exercise(exercise_id)
    store = get_store(history_path, exercise_id)

    try:
        user_state = store.load_user_state()
    except FileNotFoundError as e:
        views.print_error(str(e))
        views.print_info(t("error.run_init_profile"))
        raise typer.Exit(1)
    except ValidationError as e:
        views.print_error(t("error.invalid_data", error=e))
        raise typer.Exit(1)

    plan_start_date = _resolve_plan_start(store, user_state)
    weeks_ahead_val = weeks if weeks is not None else 4
    total_weeks = _total_weeks(plan_start_date, weeks_ahead_val)

    # Compute overtraining severity for shift/notice — only relevant for near-term dates.
    # Overtraining is a current-state condition; by the time the user trains 2+ weeks
    # from now it will have resolved, so far-future explains should not show the notice.
    days_per_week = user_state.profile.preferred_days_per_week
    ot_severity = overtraining_severity(user_state.history, days_per_week)
    ot_level = ot_severity["level"]
    ot_rest = ot_severity["extra_rest_days"] if ot_level >= 2 else 0

    # Cutoff: overtraining only affects sessions within (ot_rest + 14) days from today.
    today_dt = datetime.now()
    ot_cutoff = (today_dt + timedelta(days=max(ot_rest + 14, 14))).strftime("%Y-%m-%d")

    # Resolve "next" → first upcoming planned session date
    if date.lower() == "next":
        try:
            plans = generate_plan(user_state, plan_start_date, exercise,
                                  weeks_ahead=total_weeks,
                                  overtraining_level=ot_level, overtraining_rest_days=ot_rest)
        except ValueError as e:
            views.print_error(str(e))
            raise typer.Exit(1)
        today_str = today_dt.strftime("%Y-%m-%d")
        nxt = next((p for p in plans if p.date >= today_str), None)
        if nxt is None:
            views.print_error(t("plan.no_upcoming"))
            raise typer.Exit(1)
        date = nxt.date

    # Don't apply overtraining shift for dates beyond the near-term recovery window
    if date > ot_cutoff:
        ot_level, ot_rest = 0, 0

    result = explain_plan_entry(user_state, plan_start_date, date, exercise,
                                weeks_ahead=total_weeks,
                                overtraining_level=ot_level, overtraining_rest_days=ot_rest)
    views.console.print()
    views.console.print(result)
    views.console.print()


@app.command("refresh-plan")
def refresh_plan(
    exercise_id: ExerciseOption = "pull_up",
    json_out: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output as JSON for machine processing"),
    ] = False,
) -> None:
    """
    Reset the plan anchor to today.

    Use after a break when unlogged sessions have piled up in the past.
    The plan resumes from today; session-type rotation and grip rotation
    continue from where your history left off. All unlogged days before
    today are implicitly treated as rest.
    """
    import json

    exercise = get_exercise(exercise_id)
    store = get_store(None, exercise_id)

    if not store.exists():
        views.print_error(t("error.history_not_found", path=store.history_path))
        views.print_info(t("error.run_init_first"))
        raise typer.Exit(1)

    try:
        user_state = store.load_user_state()
    except Exception as e:
        views.print_error(str(e))
        raise typer.Exit(1)

    today = datetime.now().strftime("%Y-%m-%d")
    store.set_plan_start_date(today)

    try:
        plans = generate_plan(user_state, today, exercise, weeks_ahead=2)
    except ValueError as e:
        views.print_error(str(e))
        raise typer.Exit(1)

    next_session = next((p for p in plans if p.date >= today), None)

    if json_out:
        print(json.dumps({
            "plan_start_date": today,
            "next_session": {
                "date": next_session.date,
                "session_type": next_session.session_type,
                "grip": next_session.grip,
            } if next_session else None,
        }, indent=2))
        return

    views.print_success(t("plan.refreshed_to", date=today))
    if next_session:
        views.print_info(t("plan.next_is",
                           session_type=next_session.session_type,
                           date=next_session.date))
