"""Planning commands: plan, explain, and interactive menu helpers."""

import json
from datetime import datetime
from typing import Annotated, Optional

import typer

from bar_scheduler.api import (
    get_plan as api_get_plan,
    explain_session as api_explain_session,
    refresh_plan as api_refresh_plan,
    log_session as api_log_session,
    get_history as api_get_history,
    get_exercise_info,
    get_load_data,
    training_max_from_baseline,
    get_profile,
    get_current_equipment,
    compute_session_load,
    get_plan_weeks,
    set_plan_weeks,
    check_band_progression,
    get_next_band_step,
    ProfileNotFoundError,
    HistoryNotFoundError,
    ValidationError,
)
from cli_bar import views
from cli_bar.app import ExerciseOption, app, effective_data_dir
from cli_bar.i18n import t


def _prompt_baseline(bodyweight_kg: float, exercise: dict) -> int | None:
    """
    Prompt user to enter their baseline max reps when no history exists.

    Logs a TEST session and returns the rep count, or None if cancelled.
    """
    ex_name = exercise["display_name"]

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
    api_log_session(
        effective_data_dir(),
        exercise["id"],
        {
            "date": today,
            "bodyweight_kg": bodyweight_kg,
            "grip": exercise["primary_variant"],
            "session_type": "TEST",
            "exercise_id": exercise["id"],
            "planned_sets": [{"target_reps": max_reps}],
            "completed_sets": [
                {
                    "actual_reps": max_reps,
                    "rest_seconds_before": 180,
                    "added_weight_kg": 0.0,
                    "rir_reported": 0,
                }
            ],
            "notes": f"Baseline max test ({ex_name}, entered during plan setup)",
        },
    )
    tm = training_max_from_baseline(max_reps)
    views.print_success(t("plan.logged_baseline", reps=max_reps, tm=tm))
    return max_reps


def _menu_explain(exercise_id: str) -> None:
    """Interactive explain helper called from the main menu."""
    views.console.print()
    date_input = views.console.input(t("plan.explain_date_prompt")).strip() or "next"

    try:
        result = api_explain_session(effective_data_dir(), exercise_id, date_input)
    except (ProfileNotFoundError, HistoryNotFoundError) as e:
        views.print_error(str(e))
        return
    except ValueError as e:
        views.print_error(str(e))
        return

    views.console.print()
    views.console.print(result)
    views.console.print()


@app.command()
def plan(
    weeks: Annotated[
        Optional[int],
        typer.Option("--weeks", "-w", help="Number of weeks to show ahead (default: 4)"),
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
    exercise = get_exercise_info(exercise_id)

    try:
        history = api_get_history(effective_data_dir(), exercise_id)
    except (ProfileNotFoundError, HistoryNotFoundError) as e:
        views.print_error(str(e))
        views.print_info(t("error.run_init_first"))
        raise typer.Exit(1)
    except ValidationError as e:
        views.print_error(t("error.invalid_data", error=e))
        raise typer.Exit(1)

    try:
        profile_dict = get_profile(effective_data_dir())
    except ProfileNotFoundError as e:
        views.print_error(str(e))
        views.print_info(t("error.run_init_profile"))
        raise typer.Exit(1)

    if profile_dict is None:
        views.print_error(t("error.run_init_profile"))
        raise typer.Exit(1)

    bw = profile_dict.get("current_bodyweight_kg", 80.0)
    exercise_target = profile_dict.get("exercise_targets", {}).get(exercise_id)

    if not history and baseline_max is None:
        baseline_max = _prompt_baseline(bw, exercise)
        if baseline_max is None:
            raise typer.Exit(0)

    weeks_ahead = weeks or get_plan_weeks(effective_data_dir()) or 4
    if weeks is not None:
        set_plan_weeks(effective_data_dir(), weeks)

    try:
        result = api_get_plan(effective_data_dir(), exercise_id, weeks_ahead=weeks_ahead)
    except (ProfileNotFoundError, HistoryNotFoundError) as e:
        views.print_error(str(e))
        raise typer.Exit(1)
    except ValueError as e:
        views.print_error(str(e))
        raise typer.Exit(1)

    if json_out:
        print(json.dumps(result, indent=2))
        return

    sessions = result["sessions"]
    status = result["status"]
    plan_changes = result["plan_changes"]
    overtraining = result["overtraining"]

    if plan_changes:
        views.console.print(t("plan.updated_header"))
        for c in plan_changes[:5]:
            views.console.print(f"  {c}")
        views.console.print()

    ot_level = overtraining.get("level", 0)
    if ot_level >= 3:
        extra = overtraining["extra_rest_days"]
        desc = overtraining["description"]
        views.console.print(t("overtraining.level3_header", desc=desc))
        views.console.print(t("overtraining.level3_recovery", extra=extra))
        views.console.print(t("overtraining.level3_adjusted", level=ot_level))
        views.console.print(t("overtraining.level3_skip_hint", extra=extra))
        views.console.print()
    elif ot_level == 2:
        desc = overtraining["description"]
        extra = overtraining["extra_rest_days"]
        views.console.print(t("overtraining.level2_header", desc=desc))
        views.console.print(t("overtraining.level2_adjusted"))
        if extra > 0:
            views.console.print(t("overtraining.level2_skip_hint", extra=extra))
        views.console.print()
    elif ot_level == 1:
        desc = overtraining["description"]
        views.console.print(t("overtraining.level1", desc=desc))
        views.console.print()

    # Goal-reached check
    if exercise_target is not None and status.get("latest_test_max") is not None:
        goal_str = f"{exercise_target['reps']} reps"
        if exercise_target.get("weight_kg", 0.0) > 0:
            goal_str += f" @ +{exercise_target['weight_kg']:.1f} kg"
        if status["latest_test_max"] >= exercise_target["reps"]:
            if exercise_target["weight_kg"] == 0.0:
                views.console.print(t("plan.goal_reached", goal=goal_str))
            else:
                test_sessions = [s for s in history if s["session_type"] == "TEST"]
                if test_sessions:
                    last_test = max(test_sessions, key=lambda s: s["date"])
                    best_weight = max(
                        (
                            st["added_weight_kg"]
                            for st in last_test.get("completed_sets", [])
                        ),
                        default=0.0,
                    )
                    if best_weight >= exercise_target["weight_kg"]:
                        views.console.print(t("plan.goal_reached", goal=goal_str))

    equipment_state: dict | None = None
    try:
        equipment_state = get_current_equipment(effective_data_dir(), exercise_id)
    except Exception:
        pass

    band_hint: str | None = None
    if equipment_state:
        try:
            rec_item = equipment_state.get("recommended_item")
            if rec_item and check_band_progression(effective_data_dir(), exercise_id):
                band_hint = get_next_band_step(rec_item, exercise_id)
        except Exception:
            pass

    load_map: dict[tuple[str, str], float] | None = None
    try:
        load_data = get_load_data(effective_data_dir(), exercise_id, weeks_ahead=weeks_ahead)
        load_map = {
            (entry["date"], entry["session_type"]): entry["load"]
            for entry in load_data.get("history", []) + load_data.get("plan", [])
        }
    except Exception:
        pass

    goal_eload: float | None = None
    if exercise_target:
        try:
            goal_eload = compute_session_load(
                effective_data_dir(),
                exercise_id,
                exercise_target["reps"],
                added_weight_kg=exercise_target.get("weight_kg", 0.0),
            )
        except Exception:
            pass

    views.print_unified_plan(
        sessions,
        status,
        exercise_target=exercise_target,
        equipment_state=equipment_state,
        history=history,
        exercise_id=exercise_id,
        bodyweight_kg=bw,
        band_hint=band_hint,
        load_map=load_map,
        goal_eload=goal_eload,
    )


@app.command()
def explain(
    date: Annotated[
        str,
        typer.Argument(
            help="Date to explain (YYYY-MM-DD) or 'next' for the next upcoming session"
        ),
    ],
    weeks: Annotated[
        Optional[int],
        typer.Option("--weeks", "-w", help="Plan horizon in weeks"),
    ] = None,
    exercise_id: ExerciseOption = "pull_up",
) -> None:
    """Show exactly how a planned session's parameters were calculated."""
    weeks_ahead = weeks if weeks is not None else 4

    try:
        result = api_explain_session(effective_data_dir(), exercise_id, date, weeks_ahead=weeks_ahead)
    except (ProfileNotFoundError, HistoryNotFoundError) as e:
        views.print_error(str(e))
        views.print_info(t("error.run_init_profile"))
        raise typer.Exit(1)
    except ValueError as e:
        views.print_error(str(e))
        raise typer.Exit(1)

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
    try:
        result = api_refresh_plan(effective_data_dir(), exercise_id)
    except (ProfileNotFoundError, HistoryNotFoundError) as e:
        views.print_error(str(e))
        views.print_info(t("error.run_init_first"))
        raise typer.Exit(1)

    if json_out:
        print(json.dumps(result, indent=2))
        return

    views.print_success(t("plan.refreshed_to", date=result["plan_start_date"]))
    if result.get("next_session"):
        nxt = result["next_session"]
        views.print_info(
            t(
                "plan.next_is",
                session_type=nxt["session_type"],
                date=nxt["date"],
            )
        )
