"""Session commands: log-session, show-history, delete-record, and helpers."""

import json
from datetime import datetime
from typing import Annotated, Optional

import typer

from bar_scheduler.api import (
    delete_session as api_delete_session,
    get_history as api_get_history,
    log_session as api_log_session,
    get_exercise_info,
    get_training_status,
    get_load_data,
    training_max_from_baseline,
    get_plan_cache_entry,
    get_profile,
    list_exercises,
    HistoryNotFoundError,
    ProfileNotFoundError,
    SessionNotFoundError,
    ValidationError,
    parse_compact_sets,
    parse_sets_string,
)
from bar_scheduler.api.types import SessionInput, SessionType, SetInput
from cli_bar import views
from cli_bar.app import OVERPERFORMANCE_REP_THRESHOLD, ExerciseOption, app, effective_data_dir
from cli_bar.i18n import t


def _interactive_sets() -> str:
    """
    Prompt the user to enter sets one by one.

    Accepts compact plan format on the first entry (before any sets have been entered):
        5x4 +0.5kg / 240s   → expands to 4 sets of 5 reps, +0.5 kg, 240 s rest
        4, 3x8 / 60s         → 1 set of 4 + 3 sets of 8, 60 s rest

    Also accepts per-set formats:
        8@0/180   canonical
        8 0 180   space-separated
        8         bare reps, bodyweight, 180 s rest
    """
    views.console.print()
    views.console.print(t("sets.enter_header"))
    views.console.print(t("sets.compact_hint"))
    views.console.print(t("sets.per_set_hint"))
    views.console.print(t("sets.rest_hint"))
    views.console.print(t("sets.done_hint"))

    parts: list[str] = []
    set_num = 1
    while True:
        raw = views.console.input(t("sets.set_prompt", num=set_num)).strip()
        if not raw:
            if parts:
                break
            views.print_warning(t("sets.at_least_one"))
            continue
        if not raw[0].isdigit():
            views.print_error(t("sets.invalid_format"))
            continue

        # When no sets have been entered yet, check for compact plan format.
        if not parts:
            compact = parse_compact_sets(raw)
            if compact is not None and len(compact) > 1:
                w = compact[0][1]
                r = compact[0][2]
                w_str = f" +{w:.1f} kg" if w > 0 else " (bodyweight)"
                views.console.print(
                    t(
                        "sets.compact_preview",
                        count=len(compact),
                        weight_str=w_str,
                        rest=r,
                    )
                )
                for i, entry in enumerate(compact, 1):
                    views.console.print(
                        t("sets.compact_set_line", num=i, reps=entry[0])
                    )
                confirm = views.console.input(t("sets.compact_accept")).strip().lower()
                if confirm in ("", "y", "yes"):
                    return raw  # parse_sets_string will expand it
                views.console.print()
                views.print_info(t("sets.enter_individually"))
                continue

        # Per-set validation -- re-prompt on error instead of crashing later
        try:
            parse_sets_string(raw)
        except ValidationError as e:
            views.print_error(str(e))
            continue
        parts.append(raw)
        set_num += 1

    return ", ".join(parts)


def _menu_delete_record(exercise_id: str) -> None:
    """Interactive delete-session helper called from the main menu."""
    try:
        sessions = api_get_history(effective_data_dir(), exercise_id)
    except (ProfileNotFoundError, HistoryNotFoundError) as e:
        views.print_error(str(e))
        return

    if not sessions:
        views.print_info(t("error.no_sessions_in_history"))
        return

    views.print_history(sessions)

    while True:
        raw = views.console.input(t("log.delete_prompt")).strip()
        if not raw:
            views.print_info(t("log.cancelled"))
            return
        try:
            record_id = int(raw)
        except ValueError:
            views.print_error(t("error.enter_number"))
            continue

        if record_id < 1 or record_id > len(sessions):
            views.print_error(t("error.record_id_range", max_id=len(sessions)))
            continue

        target = sessions[record_id - 1]
        if views.confirm_action(
            t(
                "log.delete_confirm",
                date=target["date"],
                session_type=target["session_type"],
            )
        ):
            api_delete_session(effective_data_dir(), exercise_id, record_id)
            views.print_success(
                t(
                    "log.deleted_session",
                    record_id=record_id,
                    date=target["date"],
                    session_type=target["session_type"],
                )
            )
        else:
            views.print_info(t("log.cancelled"))
        return


@app.command("log-session")
def log_session(
    date: Annotated[
        Optional[str],
        typer.Option("--date", "-d", help="Session date (YYYY-MM-DD, default: today)"),
    ] = None,
    bodyweight_kg: Annotated[
        Optional[float],
        typer.Option("--bodyweight-kg", "-w", help="Bodyweight in kg"),
    ] = None,
    grip: Annotated[
        Optional[str],
        typer.Option("--grip", "-g", help="Grip type: pronated | supinated | neutral"),
    ] = None,
    session_type: Annotated[
        Optional[str],
        typer.Option(
            "--session-type", "-t", help="Session type: S | H | E | T | M (max test)"
        ),
    ] = None,
    sets: Annotated[
        Optional[str],
        typer.Option("--sets", "-s", help="Sets: reps@+kg/rest,... e.g. 8@0/180,6@0"),
    ] = None,
    notes: Annotated[
        Optional[str],
        typer.Option("--notes", "-n", help="Session notes"),
    ] = None,
    rir: Annotated[
        Optional[int],
        typer.Option("--rir", help="Reps in reserve on last set (0=failure, 5=easy)"),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output as JSON for machine processing"),
    ] = False,
    exercise_id: ExerciseOption = "pull_up",
) -> None:
    """
    Log a completed training session.

    Run without options for interactive step-by-step entry.
    Or supply all options for one-liner use:

      bar-scheduler log-session --date 2026-02-18 --bodyweight-kg 82 \\
        --grip pronated --session-type S --sets "8@0/180,6@0/120,6@0"
    """
    # Determine interactive mode from CLI args before any I/O
    was_interactive = sets is None

    # If fully interactive and no explicit exercise given, ask which exercise to log.
    # Only offer exercises that have already been initialised (history exists).
    if was_interactive and exercise_id == "pull_up":
        active_ex: list[tuple[str, dict]] = []
        for ex in list_exercises():
            try:
                if api_get_history(effective_data_dir(), ex["id"]):
                    active_ex.append((ex["id"], ex))
            except HistoryNotFoundError:
                pass
        if len(active_ex) > 1:
            ex_options = "  ".join(
                f"[{i+1}] {ex['display_name']}" for i, (_, ex) in enumerate(active_ex)
            )
            views.console.print(t("log.exercise_prompt", options=ex_options))
            ex_map: dict[str, str] = {}
            for i, (eid, _) in enumerate(active_ex, 1):
                ex_map[str(i)] = eid
                ex_map[eid] = eid
            while True:
                raw_ex = views.console.input(t("log.exercise_input")).strip() or "1"
                if raw_ex in ex_map:
                    exercise_id = ex_map[raw_ex]
                    break
                views.print_error(t("log.exercise_input_error", count=len(active_ex)))
        elif len(active_ex) == 1:
            exercise_id = active_ex[0][
                0
            ]  # only one exercise initialised -- use silently

    exercise = get_exercise_info(exercise_id)

    try:
        api_get_history(effective_data_dir(), exercise_id)
    except (ProfileNotFoundError, HistoryNotFoundError) as e:
        views.print_error(str(e))
        views.print_info(t("error.run_init_first"))
        raise typer.Exit(1)

    # Normalize CLI-provided session_type shortcuts (M→TEST, lowercase aliases)
    if session_type is not None:
        _norm: dict[str, str] = {
            "m": SessionType.TEST,
            "M": SessionType.TEST,
            "s": SessionType.S,
            "h": SessionType.H,
            "e": SessionType.E,
            "t": SessionType.T,
            "S": SessionType.S,
            "H": SessionType.H,
            "E": SessionType.E,
            "T": SessionType.T,
            "TEST": SessionType.TEST,
        }
        session_type = _norm.get(session_type, session_type)

    # -- Interactive prompts for missing values ------------------------------

    # Date
    if date is None:
        default_date = datetime.now().strftime("%Y-%m-%d")
        raw = views.console.input(t("log.date_prompt", default=default_date)).strip()
        date = raw if raw else default_date

    # Bodyweight
    if bodyweight_kg is None:
        saved_bw: float | None = None
        try:
            profile_dict = get_profile(effective_data_dir())
            saved_bw = profile_dict.get("current_bodyweight_kg")
        except Exception:
            pass
        bw_hint = f" [{saved_bw:.1f}]" if saved_bw else ""
        while True:
            raw = views.console.input(t("log.bodyweight_prompt", hint=bw_hint)).strip()
            if not raw and saved_bw:
                bodyweight_kg = saved_bw
                break
            try:
                bodyweight_kg = float(raw)
                if bodyweight_kg <= 0:
                    raise ValueError
                break
            except ValueError:
                views.print_error(t("error.positive_number"))

    # Session type
    if session_type is None:
        views.console.print(t("log.session_type_header"))
        valid_types: dict[str, str] = {
            "s": SessionType.S,
            "h": SessionType.H,
            "e": SessionType.E,
            "t": SessionType.T,
            "m": SessionType.TEST,
            "S": SessionType.S,
            "H": SessionType.H,
            "E": SessionType.E,
            "T": SessionType.T,
            "M": SessionType.TEST,
            "TEST": SessionType.TEST,
        }
        while True:
            raw = views.console.input(t("log.session_type_prompt")).strip() or "S"
            session_type = valid_types.get(raw.upper(), valid_types.get(raw))
            if session_type:
                break
            views.print_error(t("log.session_type_error"))

    # Grip / variant -- show exercise-specific options (skipped for dip: always standard)
    if grip is None:
        if exercise["id"] == "dip":
            grip = exercise[
                "primary_variant"
            ]  # always "standard" -- no anatomical choice
        else:
            variants = exercise["variants"]
            hint = "  ".join(f"[{i+1}] {v}" for i, v in enumerate(variants))
            views.console.print(t("log.variant_header", hint=hint))
            grip_map: dict[str, str] = {}
            for i, v in enumerate(variants, 1):
                grip_map[str(i)] = v
                grip_map[v] = v
            while True:
                raw = views.console.input(t("log.variant_prompt")).strip() or "1"
                grip = grip_map.get(raw.lower())
                if grip:
                    break
                views.print_error(t("log.variant_error", count=len(variants)))

    # Sets
    if sets is None:
        sets = _interactive_sets()

    # RIR (Reps In Reserve)
    rir_value: int | None = rir
    if rir is None and was_interactive:
        views.console.print()
        raw_rir = views.console.input(t("log.rir_prompt")).strip()
        if raw_rir:
            try:
                rir_value = max(0, min(10, int(raw_rir)))
            except ValueError:
                pass

    # Notes
    if notes is None and was_interactive:
        views.console.print()
        raw_notes = views.console.input(t("log.notes_prompt")).strip()
        notes = raw_notes if raw_notes else None

    # -- Validate all inputs -------------------------------------------------

    if grip not in exercise["variants"]:
        views.print_error(
            t("log.variant_must_be", variants=", ".join(exercise["variants"]))
        )
        raise typer.Exit(1)

    if session_type not in (SessionType.S, SessionType.H, SessionType.E, SessionType.T, SessionType.TEST):
        views.print_error(t("log.session_type_must_be"))
        raise typer.Exit(1)

    if bodyweight_kg <= 0:
        views.print_error(t("error.bodyweight_positive"))
        raise typer.Exit(1)

    try:
        parsed_sets = parse_sets_string(sets)
    except ValidationError as e:
        views.print_error(f"Invalid sets format: {e}")
        raise typer.Exit(1)

    # -- Build and save session ----------------------------------------------

    completed_sets = [
        SetInput(
            reps=reps,
            added_weight_kg=weight,
            rest_seconds_before=rest,
            rir_reported=rir_value,
        )
        for reps, weight, rest in parsed_sets
    ]

    # Populate planned_sets from plan cache if a matching prescription exists.
    planned_sets: list[dict] = []
    cache_entry = get_plan_cache_entry(effective_data_dir(), exercise_id, date, session_type)
    if cache_entry:
        n = cache_entry.get("sets", 0)
        tr = cache_entry.get("reps", 0)
        wt = cache_entry.get("weight", 0.0)
        rs = cache_entry.get("rest", 180)
        planned_sets = [
            {
                "target_reps": tr,
                "actual_reps": None,
                "rest_seconds_before": rs,
                "added_weight_kg": wt,
            }
            for _ in range(n)
        ]

    try:
        api_log_session(
            effective_data_dir(),
            exercise_id,
            SessionInput(
                date=date,
                bodyweight_kg=bodyweight_kg,
                grip=grip,
                session_type=session_type,
                exercise_id=exercise_id,
                completed_sets=completed_sets,
                planned_sets=planned_sets,
                notes=notes,
            ),
        )
    except ValidationError as e:
        views.print_error(f"Invalid session data: {e}")
        raise typer.Exit(1)

    total_reps = sum(s["actual_reps"] for s in completed_sets if s.get("actual_reps"))
    max_reps_bw = max(
        (
            s["actual_reps"]
            for s in completed_sets
            if s.get("actual_reps") and s["added_weight_kg"] == 0
        ),
        default=0,
    )
    max_reps_weighted = max(
        (
            round(s["actual_reps"] * (1 + s["added_weight_kg"] / bodyweight_kg))
            for s in completed_sets
            if s.get("actual_reps") and s["added_weight_kg"] > 0
        ),
        default=0,
    )
    max_reps = max(max_reps_bw, max_reps_weighted)

    # Overperformance / personal best detection
    new_personal_best = False
    new_tm: int | None = None
    if session_type != SessionType.TEST and max_reps > 0:
        try:
            train_status = get_training_status(effective_data_dir(), exercise_id)
            tm = train_status["training_max"]
            test_max = train_status.get("latest_test_max") or 0

            if max_reps > test_max:
                api_log_session(
                    effective_data_dir(),
                    exercise_id,
                    SessionInput(
                        date=date,
                        bodyweight_kg=bodyweight_kg,
                        grip=exercise["primary_variant"],
                        session_type=SessionType.TEST,
                        exercise_id=exercise_id,
                        planned_sets=[{"target_reps": max_reps}],
                        completed_sets=[
                            SetInput(
                                reps=max_reps,
                                added_weight_kg=0.0,
                                rest_seconds_before=180,
                                rir_reported=0,
                            )
                        ],
                        notes="Auto-logged from session personal best",
                    ),
                )
                new_tm = training_max_from_baseline(max_reps)
                new_personal_best = True
                if not json_out:
                    est_note = (
                        t("log.bw_equivalent_note")
                        if max_reps_weighted > max_reps_bw
                        else ""
                    )
                    views.console.print()
                    views.print_success(
                        t(
                            "log.new_personal_best",
                            max_reps=max_reps,
                            note=est_note,
                            new_tm=new_tm,
                        )
                    )
            elif max_reps >= tm + OVERPERFORMANCE_REP_THRESHOLD and not json_out:
                views.console.print()
                views.print_warning(
                    t(
                        "log.overperformance_warning",
                        max_reps=max_reps,
                        tm=tm,
                        delta=max_reps - tm,
                    )
                )
                views.print_info(t("log.overperformance_hint"))
        except Exception:
            pass

    if json_out:
        print(
            json.dumps(
                {
                    "date": date,
                    "session_type": session_type,
                    "grip": grip,
                    "bodyweight_kg": bodyweight_kg,
                    "total_reps": total_reps,
                    "max_reps_bodyweight": max_reps_bw,
                    "max_reps_equivalent": max_reps,
                    "new_personal_best": new_personal_best,
                    "new_tm": new_tm,
                    "sets": [
                        {
                            "reps": s["actual_reps"],
                            "weight_kg": s["added_weight_kg"],
                            "rest_s": s["rest_seconds_before"],
                        }
                        for s in completed_sets
                    ],
                },
                indent=2,
            )
        )
        return

    views.console.print()
    views.print_success(t("log.logged_session", session_type=session_type, date=date))
    views.print_info(t("log.total_reps", total=total_reps))
    if max_reps_bw > 0:
        views.print_info(t("log.max_bodyweight", max_reps=max_reps_bw))
    if max_reps_weighted > max_reps_bw:
        views.print_info(t("log.max_bw_equivalent", max_reps=max_reps_weighted))


@app.command("show-history")
def show_history(
    limit: Annotated[
        Optional[int],
        typer.Option("--limit", "-l", help="Limit number of sessions to show"),
    ] = None,
    json_out: Annotated[
        bool,
        typer.Option("--json", "-j", help="Output as JSON for machine processing"),
    ] = False,
    exercise_id: ExerciseOption = "pull_up",
) -> None:
    """
    Display training history as a table.
    """
    try:
        sessions = api_get_history(effective_data_dir(), exercise_id)
    except (ProfileNotFoundError, HistoryNotFoundError) as e:
        views.print_error(str(e))
        views.print_info(t("error.run_init_first"))
        raise typer.Exit(1)

    if limit is not None:
        sessions = sessions[-limit:]

    if json_out:
        output = []
        for s in sessions:
            cs = s.get("completed_sets", [])
            total_reps = sum(st["actual_reps"] for st in cs if st.get("actual_reps"))
            max_reps = max(
                (st["actual_reps"] for st in cs if st.get("actual_reps")), default=0
            )
            rests = [
                st["rest_seconds_before"] for st in cs if st.get("rest_seconds_before")
            ]
            avg_rest_s = round(sum(rests) / len(rests)) if rests else 0
            output.append(
                {
                    "date": s["date"],
                    "session_type": s["session_type"],
                    "grip": s["grip"],
                    "bodyweight_kg": s["bodyweight_kg"],
                    "total_reps": total_reps,
                    "max_reps": max_reps,
                    "avg_rest_s": avg_rest_s,
                    "sets": [
                        {
                            "reps": st["actual_reps"],
                            "weight_kg": st["added_weight_kg"],
                            "rest_s": st["rest_seconds_before"],
                        }
                        for st in cs
                        if st.get("actual_reps") is not None
                    ],
                }
            )
        print(json.dumps(output, indent=2))
        return

    load_map: dict[tuple[str, str], float] | None = None
    try:
        load_data = get_load_data(effective_data_dir(), exercise_id)
        load_map = {
            (entry["date"], entry["session_type"]): entry["load"]
            for entry in load_data.get("history", [])
        }
    except Exception:
        pass

    views.print_history(sessions, load_map=load_map)


@app.command("delete-record")
def delete_record(
    record_id: Annotated[
        int,
        typer.Argument(help="Session ID to delete (see # column in show-history)"),
    ],
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Skip confirmation prompt"),
    ] = False,
    exercise_id: ExerciseOption = "pull_up",
) -> None:
    """
    Remove a session by its ID.

    Use 'show-history' to see session IDs in the # column.
    """
    try:
        sessions = api_get_history(effective_data_dir(), exercise_id)
    except (ProfileNotFoundError, HistoryNotFoundError) as e:
        views.print_error(str(e))
        raise typer.Exit(1)

    if not sessions:
        views.print_error(t("error.no_sessions_in_history"))
        raise typer.Exit(1)

    if record_id < 1 or record_id > len(sessions):
        views.print_error(t("error.record_id_range", max_id=len(sessions)))
        raise typer.Exit(1)

    target = sessions[record_id - 1]
    views.console.print(
        f"Session to delete: [bold]{target['date']}[/bold] ({target['session_type']})"
    )

    if not force and not views.confirm_action(t("log.delete_confirm_bare")):
        views.print_info(t("log.cancelled"))
        raise typer.Exit(0)

    try:
        api_delete_session(effective_data_dir(), exercise_id, record_id)
    except SessionNotFoundError as e:
        views.print_error(str(e))
        raise typer.Exit(1)

    views.print_success(
        t(
            "log.deleted_session",
            record_id=record_id,
            date=target["date"],
            session_type=target["session_type"],
        )
    )
