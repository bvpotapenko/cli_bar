"""
CLI view formatters using Rich for pretty console output.

Handles table formatting and display of training data.
"""

from datetime import datetime

from rich.console import Console
from rich.table import Table

from bar_scheduler.api import (
    get_exercise_info,
    get_equipment_catalog,
    get_assistance_kg,
    compute_leff,
)
from cli_bar.ascii_plot import (
    create_max_reps_plot,
    create_weekly_volume_chart_from_dict,
)
from cli_bar.i18n import t


console = Console()


def _fmt_prescribed_from_dict(
    sets: list[dict], session_type: str, exercise_id: str = ""
) -> str:
    """Format prescribed sets (API dicts with reps/weight_kg/rest_s) as a compact string."""
    if not sets:
        return "(no sets)"
    if session_type == "TEST":
        return "1x max reps"

    from collections import Counter

    reps_list = [s["reps"] for s in sets]
    weight = sets[0]["weight_kg"]
    rest = sets[0]["rest_s"]

    if all(r == reps_list[0] for r in reps_list):
        base = f"{reps_list[0]}x{len(reps_list)}"
    else:
        counts = Counter(reps_list)
        parts_out = []
        for rep_val in sorted(counts.keys(), reverse=True):
            n = counts[rep_val]
            parts_out.append(f"{rep_val}×{n}" if n > 1 else str(rep_val))
        base = ", ".join(parts_out)

    weight_str = f" +{weight:.1f}kg" if weight > 0 else ""
    text = f"{base}{weight_str} / {rest}s"
    if exercise_id == "bss":
        text += " (per leg)"
    elif exercise_id == "incline_db_press":
        text += " (per hand)"
    return text


def _fmt_actual_from_dict(sets: list[dict], session_type: str) -> str:
    """Format completed sets (API dicts with reps/weight_kg/rest_s) as a short string."""
    valid = [s for s in sets if s.get("reps") is not None]
    if not valid:
        return "--"
    if session_type == "TEST":
        max_r = max(s["reps"] for s in valid)
        weight = valid[0].get("weight_kg", 0) or 0
        weight_str = f" @ +{weight:.1f}kg" if weight > 0 else ""
        return f"{max_r} reps (max){weight_str}"

    total = sum(s["reps"] for s in valid)
    reps_str = "+".join(str(s["reps"]) for s in valid)

    weights = [s["weight_kg"] for s in valid]
    weight_str = f" +{weights[0]:.1f}kg" if weights[0] > 0 else ""

    rests = [s["rest_s"] for s in valid]
    if all(r == rests[0] for r in rests):
        rest_str = f"{rests[0]}s"
    else:
        rest_str = ",".join(str(r) for r in rests) + "s"

    return f"{reps_str} = {total}{weight_str} / {rest_str}"


_GRIP_ABBR: dict[str, str] = {
    # pull-up variants
    "pronated": "Pro",
    "neutral": "Neu",
    "supinated": "Sup",
    # dip variants
    "standard": "Std",
    "chest_lean": "CL ",
    "tricep_upright": "TUp",
    # bss variants
    "deficit": "Def",
    "front_foot_elevated": "FFE",
}
_TYPE_DISPLAY: dict[str, str] = {
    "TEST": "TST",
    "S": "Str",
    "H": "Hpy",
    "E": "End",
    "T": "Tec",
}


def _fmt_date_cell(date_str: str, status: str) -> str:
    """Format status icon + date as a single compact cell: '> 02.18(Tue)'."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    date_part = dt.strftime("%m.%d(%a)")
    icon = {"done": "✓", "missed": "--", "next": ">", "planned": " ", "extra": "·"}[
        status
    ]
    return f"{icon} {date_part}"


def _print_equipment_header(
    exercise: dict,
    equipment_state: dict,
    bodyweight_kg: float | None,
    exercise_id: str,
) -> None:
    """Print the equipment info line (and optional BSS-degraded warning)."""
    catalog = get_equipment_catalog(exercise_id)
    active_item = equipment_state.get("recommended_item") or (equipment_state.get("available_items") or [""])[0]
    item_label = catalog.get(active_item, {}).get("label", active_item)
    a_kg = get_assistance_kg(
        exercise_id, active_item, equipment_state.get("machine_assistance_kg")
    )
    if bodyweight_kg and bodyweight_kg > 0:
        leff = compute_leff(exercise["bw_fraction"], bodyweight_kg, 0.0, a_kg)
        console.print(
            t("equipment.status_leff", item=item_label, leff=leff, bw=bodyweight_kg)
        )
    else:
        console.print(t("equipment.status_item", item=item_label))
    if exercise_id == "bss" and "ELEVATION_SURFACE" not in (
        equipment_state.get("available_items") or []
    ):
        console.print(t("equipment.bss_degraded"))


def _emax_cell(
    entry: dict,
    floor_max: int,
    last_tm: int | None,
) -> tuple[str, int | None]:
    """
    Compute the eMax cell value for a timeline entry dict.

    Returns (cell_str, updated_last_tm) -- last_tm is used to suppress
    identical consecutive TM projections in the future portion of the plan.
    """
    actual_sets = entry.get("actual_sets")
    if actual_sets is not None:
        if entry["type"] == "TEST":
            test_max = max(
                (s["reps"] for s in actual_sets if s.get("reps") is not None),
                default=None,
            )
            return (str(test_max) if test_max is not None else "", last_tm)
        elif entry.get("track_b") is not None:
            fi_v = entry["track_b"]["fi_est"]
            nz_v = entry["track_b"]["nuzzo_est"]
            return (f"{fi_v}/{nz_v}", last_tm)
        else:
            return ("", last_tm)
    else:
        # Future planned session -- project from TM
        tm_val = entry.get("expected_tm")
        if tm_val is not None:
            emax_val = max(round(tm_val / 0.90), floor_max)
            cell = str(emax_val) if emax_val != last_tm else ""
            return (cell, emax_val)
        return ("", last_tm)


def _grip_legend_str(entries: list[dict], show_grip: bool) -> str:
    """Return the grip abbreviation legend string (empty string when no grip column)."""
    if not show_grip:
        return ""
    grips_seen: set[str] = set()
    for e in entries:
        if g := e.get("grip"):
            grips_seen.add(g)

    _GRIP_FULL: dict[str, str] = {
        "pronated": "Pronated",
        "neutral": "Neutral",
        "supinated": "Supinated",
        "standard": "Standard",
        "chest_lean": "Chest-lean",
        "tricep_upright": "Tricep-upright",
        "deficit": "Deficit",
        "front_foot_elevated": "Front-foot-elevated",
    }
    grip_parts = [
        f"{_GRIP_ABBR[g].strip()}={_GRIP_FULL[g]}"
        for g in (
            "pronated",
            "neutral",
            "supinated",
            "standard",
            "chest_lean",
            "tricep_upright",
            "deficit",
            "front_foot_elevated",
        )
        if g in grips_seen and g in _GRIP_ABBR
    ]
    return ("  |  Grip: " + "  ".join(grip_parts)) if grip_parts else ""


def _print_band_progression(
    exercise_id: str, band_hint: str | None, equipment_state: dict | None
) -> None:
    """Print a band-progression suggestion if the caller determined one is ready."""
    if not band_hint or not equipment_state:
        return
    try:
        catalog = get_equipment_catalog(exercise_id)
        cur_item = equipment_state.get("recommended_item") or (equipment_state.get("available_items") or [""])[0]
        current_label = catalog.get(cur_item, {}).get("label", cur_item)
        next_label = catalog.get(band_hint, {}).get("label", band_hint)
        console.print()
        console.print(
            t(
                "equipment.band_progression",
                current=current_label,
                next=next_label,
            )
        )
    except Exception:
        pass


def print_unified_plan(
    entries: list[dict],
    status: dict,
    exercise_id: str,
    title: str | None = None,
    exercise_target: dict | None = None,
    equipment_state: dict | None = None,
    history: list[dict] | None = None,
    bodyweight_kg: float | None = None,
    band_hint: str | None = None,
    goal_metrics: dict | None = None,
) -> None:
    """
    Print the full unified timeline: status + single table.

    Args:
        entries: Merged timeline entries
        status: Current training status for header
        title: Table title
        exercise_target: User's goal for this exercise (shown in status block)
        equipment_state: Current equipment state (for header line)
        history: Full session history (for band progression check)
        exercise_id: Exercise being displayed
        bodyweight_kg: Current bodyweight (for Leff calculation in header)
        goal_metrics: get_goal_metrics() result dict (shown next to My Goal)
    """
    if title is None:
        title = t("table.training_log_title")

    exercise = get_exercise_info(exercise_id)
    show_grip = exercise["has_variant_rotation"]

    # Header
    console.print()
    console.print(format_status_display(status, exercise_target=exercise_target, goal_metrics=goal_metrics))
    console.print()

    # Equipment header line
    if equipment_state is not None:
        _print_equipment_header(exercise, equipment_state, bodyweight_kg, exercise_id)

    if not entries:
        console.print(t("table.no_sessions_yet"))
        return

    table = Table(title=title, show_lines=False)

    table.add_column("#", justify="right", style="dim", width=3)  # history ID
    table.add_column("Wk", justify="right", style="dim", width=3)
    table.add_column("Date", style="cyan", width=14, no_wrap=True)  # ✓ MM.DD(Ddd)
    table.add_column("Type", style="magenta", width=5)  # Str/Hpy/End/Tec/TST
    if show_grip:
        table.add_column("Grip", width=5)  # Pro/Neu/Sup/…
    table.add_column("Prescribed", width=22)
    table.add_column("Actual", width=24)
    table.add_column("Vol", justify="right", style="yellow", width=7)
    table.add_column("AvgVol", justify="right", style="yellow", width=8)
    table.add_column("1RM", justify="right", style="yellow", width=7)
    table.add_column(
        "eMax", justify="right", style="bold green", width=6
    )  # past TEST=actual  past train=fi/nz  future=plan projection

    last_wk: int | None = None
    last_tm: int | None = None

    for entry in entries:
        date_cell = _fmt_date_cell(entry["date"], entry["status"])

        # Wk: only show when week number changes
        wk_val = entry["week"] if entry.get("week", 0) > 0 else None
        wk_str = str(wk_val) if wk_val is not None and wk_val != last_wk else ""
        if wk_val is not None:
            last_wk = wk_val

        # eMax column -- (a) past TEST → actual max  (b) past train → fi/nz  (c) future → projection
        floor_max = status.get("latest_test_max") or 0
        tm_str, last_tm = _emax_cell(entry, floor_max, last_tm)

        id_str = str(entry["id"]) if entry.get("id") is not None else ""

        raw_type = entry.get("type", "")
        raw_grip = entry.get("grip", "")

        type_str = _TYPE_DISPLAY.get(raw_type, raw_type[:3] if raw_type else "")
        grip_str = _GRIP_ABBR.get(
            raw_grip, raw_grip[:3].capitalize() if raw_grip else ""
        )

        # prescribed_sets is already resolved by the API (stored prescription
        # for done sessions, generated plan for future ones).
        prescribed_str = _fmt_prescribed_from_dict(
            entry.get("prescribed_sets") or [], raw_type, exercise_id
        )
        actual_sets = entry.get("actual_sets")
        actual_str = (
            _fmt_actual_from_dict(actual_sets, raw_type)
            if actual_sets is not None
            else ""
        )

        # Style for the row
        entry_status = entry["status"]
        if entry_status == "next":
            row_style = "bold"
        elif entry_status == "done":
            row_style = "dim"
        elif entry_status == "missed":
            row_style = "dim red"
        else:
            row_style = None

        sm = entry.get("session_metrics") or {}
        vol_str = f"{sm['volume_session']:.0f}" if sm.get("volume_session") is not None else ""
        avg_vol_str = f"{sm['avg_volume_set']:.0f}" if sm.get("avg_volume_set") is not None else ""
        orm_str = f"{sm['estimated_1rm']:.1f}" if sm.get("estimated_1rm") is not None else ""

        row_cells = [id_str, wk_str, date_cell, type_str]
        if show_grip:
            row_cells.append(grip_str)
        row_cells.extend([prescribed_str, actual_str, vol_str, avg_vol_str, orm_str, tm_str])
        table.add_row(*row_cells, style=row_style)

    console.print(table)

    grip_legend = _grip_legend_str(entries, show_grip)
    console.print(f"[dim]{t('table.type_legend')}{grip_legend}[/dim]")
    console.print(f"[dim]{t('table.prescribed_legend')}[/dim]")

    # Band progression suggestion
    if band_hint is not None:
        _print_band_progression(exercise_id, band_hint, equipment_state)


def format_session_table(sessions: list[dict]) -> Table:
    """
    Create a Rich table displaying session history (API dict format).

    Args:
        sessions: List of session dicts from api.get_history()

    Returns:
        Rich Table object
    """
    table = Table(title=t("table.training_history_title"))

    table.add_column("#", justify="right", style="dim", width=3)
    table.add_column("Date", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Grip", style="green")
    table.add_column("BW(kg)", justify="right")
    table.add_column("Max(BW)", justify="right", style="bold")
    table.add_column("Total reps", justify="right")
    table.add_column("Avg rest(s)", justify="right")
    table.add_column("Vol", justify="right", style="yellow", width=7)
    table.add_column("AvgVol", justify="right", style="yellow", width=8)
    table.add_column("1RM", justify="right", style="yellow", width=7)

    for i, session in enumerate(sessions, 1):
        sets = session.get("completed_sets") or []
        reps = [s["actual_reps"] for s in sets if s.get("actual_reps") is not None]
        rests = [s["rest_seconds_before"] for s in sets if s.get("rest_seconds_before")]
        max_reps = max(reps) if reps else 0
        total = sum(reps)
        avg_rest = sum(rests) / len(rests) if rests else 0
        sm = session.get("session_metrics") or {}
        vol_str = f"{sm['volume_session']:.0f}" if sm.get("volume_session") is not None else "-"
        avg_vol_str = f"{sm['avg_volume_set']:.0f}" if sm.get("avg_volume_set") is not None else "-"
        orm_str = f"{sm['estimated_1rm']:.1f}" if sm.get("estimated_1rm") is not None else "-"

        table.add_row(
            str(i),
            session["date"],
            session["session_type"],
            session["grip"],
            f"{session['bodyweight_kg']:.1f}",
            str(max_reps) if max_reps > 0 else "-",
            str(total),
            f"{avg_rest:.0f}" if avg_rest > 0 else "-",
            vol_str,
            avg_vol_str,
            orm_str,
        )

    return table


def format_status_display(
    status: dict,
    exercise_target: dict | None = None,
    goal_metrics: dict | None = None,
) -> str:
    """
    Format training status dict (from api.get_training_status / api.get_plan) as text block.

    Args:
        status: Status dict with training_max, latest_test_max, trend_slope_per_week, etc.
        exercise_target: User's personal goal for this exercise
        goal_metrics: get_goal_metrics() result dict with estimated_1rm, volume_set

    Returns:
        Formatted string
    """
    lines = [t("status.current_status")]

    if status.get("latest_test_max") is not None:
        lines.append(t("status.cur_max", max_reps=status["latest_test_max"]))
        lines.append(t("status.tr_max", tm=status["training_max"]))
    else:
        lines.append(t("status.tr_max_only", tm=status["training_max"]))

    if exercise_target is not None:
        goal_str = f"{exercise_target['reps']} reps"
        if exercise_target.get("weight_kg", 0.0) > 0:
            goal_str += f" @ +{exercise_target['weight_kg']:.1f} kg"
        if goal_metrics is not None:
            estimated_1rm = goal_metrics.get("estimated_1rm")
            volume_set = goal_metrics.get("volume_set")
            if estimated_1rm is not None and volume_set is not None:
                goal_str += t("status.goal_metrics_suffix", estimated_1rm=estimated_1rm, volume_set=volume_set)
        lines.append(t("status.my_goal", goal=goal_str))

    lines.extend(
        [
            t("status.trend", slope=status["trend_slope_per_week"]),
            t("status.plateau_yes") if status["is_plateau"] else t("status.plateau_no"),
            (
                t("status.deload_yes")
                if status["deload_recommended"]
                else t("status.deload_no")
            ),
            t("status.readiness_z", z=status["readiness_z_score"]),
        ]
    )

    return "\n".join(lines)


def print_history(sessions: list[dict]) -> None:
    """Print session history (API dict format) to console."""
    if not sessions:
        console.print("[yellow]No sessions recorded yet.[/yellow]")
        return

    table = format_session_table(sessions)
    console.print(table)


def print_max_plot(
    data_points: list[dict],
    trajectory_z: list[tuple[datetime, float]] | None = None,
    trajectory_g: list[tuple[datetime, float]] | None = None,
    trajectory_m: list[tuple[datetime, float]] | None = None,
    bw_load_kg: float = 0.0,
    target_weight_kg: float = 0.0,
    exercise_name: str = "Exercise",
    target: int = 30,
    traj_types: frozenset[str] = frozenset(),
) -> None:
    """
    Print ASCII plot of max reps progress.

    Args:
        data_points: List of dicts with "date" and "max_reps" from api.get_progress_data()
        trajectory_z: BW reps trajectory (· dots)
        trajectory_g: Goal-weight reps trajectory (× dots)
        trajectory_m: 1RM added kg trajectory (○ dots, independent right axis)
        bw_load_kg: BW × bw_fraction; used with trajectory_m for right axis
        target_weight_kg: Goal added weight (for legend label)
        exercise_name: Display name shown in the chart title
        target: Target rep count for y-axis scaling
        traj_types: Set of requested trajectory flags (z/g/m); used for legend labels
    """
    plot = create_max_reps_plot(
        data_points,
        trajectory_z=trajectory_z,
        trajectory_g=trajectory_g,
        trajectory_m=trajectory_m,
        bw_load_kg=bw_load_kg,
        target_weight_kg=target_weight_kg,
        exercise_name=exercise_name,
        target=target,
        traj_types=traj_types,
    )
    console.print(plot)


def print_volume_chart(volume_data: dict) -> None:
    """Print weekly volume chart from api.get_volume_data() result."""
    chart = create_weekly_volume_chart_from_dict(volume_data)
    console.print(chart)



def print_success(message: str) -> None:
    """Print a success message."""
    console.print(f"[green]{message}[/green]")


def print_error(message: str) -> None:
    """Print an error message."""
    console.print(f"[red]Error: {message}[/red]")


def print_warning(message: str) -> None:
    """Print a warning message."""
    console.print(f"[yellow]Warning: {message}[/yellow]")


def print_info(message: str) -> None:
    """Print an info message."""
    console.print(f"[blue]{message}[/blue]")


def confirm_action(message: str) -> bool:
    """
    Prompt user for confirmation.

    Args:
        message: Confirmation message

    Returns:
        True if confirmed, False otherwise
    """
    response = console.input(f"{message} [y/N]: ")
    return response.lower() in ("y", "yes")
