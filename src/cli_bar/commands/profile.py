"""Profile management commands: init, add-exercise, remove-exercise, update-weight, and interactive menu helpers."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Optional

import typer

from bar_scheduler.api.api import (
    ProfileAlreadyExistsError,
    ProfileNotFoundError,
    HistoryNotFoundError,
    disable_exercise,
    enable_exercise,
    get_profile,
    init_profile,
    list_exercises,
    log_session as api_log_session,
    get_history as api_get_history,
    set_exercise_days,
    set_exercise_target,
    update_bodyweight as api_update_bodyweight,
    update_language as api_update_language,
    update_profile,
    get_exercise_info,
    training_max_from_baseline,
    get_equipment_catalog,
    get_assistance_kg,
    compute_leff,
    compute_equipment_adjustment,
    get_bss_elevation_heights,
    get_current_equipment,
    set_plan_start_date,
    delete_exercise_history,
    update_equipment,
)
from cli_bar import views
from cli_bar.app import ExerciseOption, app, effective_data_dir
from cli_bar.i18n import available_languages, t

profile_app = typer.Typer(
    name="profile",
    help="Profile management: init, language, bodyweight, equipment.",
    no_args_is_help=True,
)


@profile_app.command("init")
def init(
    height_cm: Annotated[
        int,
        typer.Option("--height-cm", "-h", help="Height in centimeters"),
    ],
    sex: Annotated[
        str,
        typer.Option("--sex", "-s", help="Sex (male/female)"),
    ],
    bodyweight_kg: Annotated[
        float,
        typer.Option("--bodyweight-kg", "-w", help="Current bodyweight in kg"),
    ],
    days_per_week: Annotated[
        int,
        typer.Option(
            "--days-per-week", "-d", help="Global default training days per week (1–5)"
        ),
    ] = 3,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Force overwrite without prompting"),
    ] = False,
) -> None:
    """
    Create or update your user profile (physical data only).

    Sets height, sex, global training days per week, and bodyweight.
    Does not set up any exercise. Use 'profile add-exercise <id>' to add an exercise.
    """
    # Validate inputs
    if sex not in ("male", "female"):
        views.print_error(t("error.sex_must_be"))
        raise typer.Exit(1)

    if days_per_week not in (1, 2, 3, 4, 5):
        views.print_error(t("error.days_must_be"))
        raise typer.Exit(1)

    if bodyweight_kg <= 0:
        views.print_error(t("error.bodyweight_positive"))
        raise typer.Exit(1)

    try:
        init_profile(
            effective_data_dir(),
            height_cm=height_cm,
            sex=sex,
            bodyweight_kg=bodyweight_kg,
            exercises=[],
            days_per_week=days_per_week,
        )
        views.print_success(
            t("profile.initialized", path=effective_data_dir() / "profile.json")
        )
    except ProfileAlreadyExistsError:
        if not force:
            views.print_warning(t("profile.already_exists"))
            views.console.print(t("profile.use_force_to_overwrite"))
            raise typer.Exit(0)
        update_profile(
            effective_data_dir(),
            height_cm=height_cm,
            sex=sex,
            preferred_days_per_week=days_per_week,
        )
        api_update_bodyweight(effective_data_dir(), bodyweight_kg)
        views.print_success(t("profile.updated", path=effective_data_dir() / "profile.json"))
    except ValueError as e:
        views.print_error(str(e))
        raise typer.Exit(1)


@profile_app.command("add-exercise")
def add_exercise(
    exercise_id: Annotated[
        str,
        typer.Argument(help="Exercise ID to add (e.g. pull_up, dip, bss)"),
    ],
    days_per_week: Annotated[
        int,
        typer.Option(
            "--days-per-week",
            "-d",
            help="Training days per week for this exercise (1–5)",
        ),
    ] = 3,
    target_reps: Annotated[
        int,
        typer.Option("--target-reps", "-t", help="Target max reps goal"),
    ] = 20,
    target_weight: Annotated[
        float,
        typer.Option("--target-weight", help="Target added weight kg (0 = reps only)"),
    ] = 0.0,
    baseline_max: Annotated[
        Optional[int],
        typer.Option(
            "--baseline-max", "-b", help="Baseline max reps (logs a TEST session)"
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Re-initialise from scratch if exercise already enabled",
        ),
    ] = False,
) -> None:
    """
    Add an exercise to your profile and create its history file.

    Use --force to wipe and re-add an exercise that is already enabled.
    """
    # Validate exercise_id
    try:
        exercise = get_exercise_info(exercise_id)
    except (ValueError, KeyError):
        valid = ", ".join(ex["id"] for ex in list_exercises())
        views.print_error(f"Unknown exercise '{exercise_id}'. Valid: {valid}")
        raise typer.Exit(1)

    if days_per_week not in (1, 2, 3, 4, 5):
        views.print_error(t("error.days_must_be"))
        raise typer.Exit(1)

    if target_reps <= 0:
        views.print_error(t("error.positive_integer"))
        raise typer.Exit(1)

    if target_weight < 0:
        views.print_error(t("error.positive_number"))
        raise typer.Exit(1)

    profile_dict = get_profile(effective_data_dir())
    if profile_dict is None:
        views.print_error(
            t("error.profile_not_found", path=effective_data_dir() / "profile.json")
        )
        views.print_info("Run 'profile init' first to create your profile.")
        raise typer.Exit(1)

    if exercise_id in profile_dict.get("exercises_enabled", []) and not force:
        views.print_error(
            f"Exercise '{exercise_id}' is already enabled. "
            "Use --force to wipe and re-add it."
        )
        raise typer.Exit(1)

    if force and exercise_id in profile_dict.get("exercises_enabled", []):
        disable_exercise(effective_data_dir(), exercise_id)
        _wipe_exercise_equipment(effective_data_dir(), exercise_id)
        _wipe_exercise_plan_start(effective_data_dir(), exercise_id)
        delete_exercise_history(effective_data_dir(), exercise_id)

    enable_exercise(effective_data_dir(), exercise_id)
    set_exercise_target(effective_data_dir(), exercise_id, target_reps, target_weight)
    set_exercise_days(effective_data_dir(), exercise_id, days_per_week)

    bw = profile_dict.get("current_bodyweight_kg", 80.0)

    # Set plan start date (2 days from today)
    today = datetime.now()
    plan_start = (today + timedelta(days=2)).strftime("%Y-%m-%d")
    set_plan_start_date(effective_data_dir(), exercise_id, plan_start)

    # Equipment setup (interactive)
    views.console.print()
    views.console.print(f"[bold]{t('profile.equipment_setup_title')}[/bold]")
    existing_eq = get_current_equipment(effective_data_dir(), exercise_id)
    new_eq = _ask_equipment(exercise_id, existing_eq)
    update_equipment(
        effective_data_dir(),
        exercise_id,
        active_item=new_eq["active_item"],
        available_items=new_eq["available_items"],
        machine_assistance_kg=new_eq.get("machine_assistance_kg"),
        elevation_height_cm=new_eq.get("elevation_height_cm"),
    )

    # Log baseline TEST session if provided
    if baseline_max is not None:
        today_str = today.strftime("%Y-%m-%d")
        api_log_session(
            effective_data_dir(),
            exercise_id,
            {
                "date": today_str,
                "bodyweight_kg": bw,
                "grip": exercise["primary_variant"],
                "session_type": "TEST",
                "exercise_id": exercise_id,
                "planned_sets": [{"target_reps": baseline_max}],
                "completed_sets": [
                    {
                        "actual_reps": baseline_max,
                        "rest_seconds_before": 180,
                        "added_weight_kg": 0.0,
                        "rir_reported": 0,
                    }
                ],
                "notes": "Baseline max test",
            },
        )
        views.print_success(t("profile.logged_baseline", reps=baseline_max))
        tm = training_max_from_baseline(baseline_max)
        views.print_info(t("profile.training_max", tm=tm))

    views.print_success(
        f"Exercise '{exercise['display_name']}' added. "
        f"Target: {target_reps} reps, {days_per_week} days/week."
    )


@profile_app.command("remove-exercise")
def remove_exercise(
    exercise_id: Annotated[
        str,
        typer.Argument(help="Exercise ID to remove (e.g. pull_up, dip, bss)"),
    ],
    delete_history: Annotated[
        bool,
        typer.Option("--delete-history", help="Also delete the exercise history file"),
    ] = False,
) -> None:
    """
    Remove an exercise from your profile.

    Removes from exercises_enabled, clears exercise-specific targets/days/equipment.
    Use --delete-history to also delete the history file.
    """
    profile_dict = get_profile(effective_data_dir())
    if profile_dict is None or exercise_id not in profile_dict.get(
        "exercises_enabled", []
    ):
        views.print_error(f"Exercise '{exercise_id}' is not in your enabled exercises.")
        raise typer.Exit(1)

    disable_exercise(effective_data_dir(), exercise_id)
    _wipe_exercise_equipment(effective_data_dir(), exercise_id)
    _wipe_exercise_plan_start(effective_data_dir(), exercise_id)

    if delete_history:
        delete_exercise_history(effective_data_dir(), exercise_id)
        views.print_info(f"Deleted history for '{exercise_id}'.")

    views.print_success(f"Exercise '{exercise_id}' removed from profile.")


def _wipe_exercise_equipment(data_dir: Path, exercise_id: str) -> None:
    """Remove all equipment entries for exercise_id from profile.json."""
    profile_path = data_dir / "profile.json"
    if not profile_path.exists():
        return
    with open(profile_path, "r") as f:
        data = json.load(f)
    data.get("equipment", {}).pop(exercise_id, None)
    with open(profile_path, "w") as f:
        json.dump(data, f, indent=2)


def _wipe_exercise_plan_start(data_dir: Path, exercise_id: str) -> None:
    """Remove the plan_start_date entry for exercise_id from profile.json."""
    profile_path = data_dir / "profile.json"
    if not profile_path.exists():
        return
    with open(profile_path, "r") as f:
        data = json.load(f)
    data.get("plan_start_dates", {}).pop(exercise_id, None)
    with open(profile_path, "w") as f:
        json.dump(data, f, indent=2)


@profile_app.command("update-weight")
def update_weight(
    bodyweight_kg: Annotated[
        float,
        typer.Argument(help="New bodyweight in kg"),
    ],
) -> None:
    """
    Update current bodyweight in profile.
    """
    if bodyweight_kg <= 0:
        views.print_error(t("error.bodyweight_positive"))
        raise typer.Exit(1)

    try:
        api_update_bodyweight(effective_data_dir(), bodyweight_kg)
        views.print_success(t("profile.updated_bodyweight", value=bodyweight_kg))
    except ProfileNotFoundError:
        views.print_error(
            t("error.profile_not_found", path=effective_data_dir() / "profile.json")
        )
        views.print_info(t("error.run_init_profile"))
        raise typer.Exit(1)
    except ValueError as e:
        views.print_error(str(e))
        raise typer.Exit(1)


def _menu_update_equipment(exercise_id: str) -> None:
    """Interactive equipment update helper -- called from the menu and CLI command."""
    profile_dict = get_profile(effective_data_dir())
    if profile_dict is None:
        views.print_error(
            t("error.profile_not_found", path=effective_data_dir() / "profile.json")
        )
        views.print_info(t("error.run_init_profile"))
        return

    existing = get_current_equipment(effective_data_dir(), exercise_id)
    exercise = get_exercise_info(exercise_id)

    if existing is not None:
        views.console.print()
        a_kg = get_assistance_kg(
            exercise_id, existing["active_item"], existing.get("machine_assistance_kg")
        )
        catalog = get_equipment_catalog(exercise_id)
        item_label = catalog.get(existing["active_item"], {}).get(
            "label", existing["active_item"]
        )
        views.console.print(
            t("equipment.current_header", exercise_name=exercise["display_name"])
        )
        views.console.print(t("equipment.active_item", item=item_label))
        if a_kg > 0:
            views.console.print(t("equipment.assistance_kg", kg=a_kg))
        if existing.get("elevation_height_cm"):
            views.console.print(
                t("equipment.elevation_cm", cm=existing["elevation_height_cm"])
            )

    new_eq = _ask_equipment(exercise_id, existing)

    # Compute Leff change for adjustment note
    if existing is not None:
        bw = profile_dict.get("current_bodyweight_kg", 80.0)
        bw_fraction = exercise["bw_fraction"]
        old_a = get_assistance_kg(
            exercise_id, existing["active_item"], existing.get("machine_assistance_kg")
        )
        new_a = get_assistance_kg(
            exercise_id, new_eq["active_item"], new_eq.get("machine_assistance_kg")
        )
        old_leff = compute_leff(bw_fraction, bw, 0.0, old_a)
        new_leff = compute_leff(bw_fraction, bw, 0.0, new_a)

        adj = compute_equipment_adjustment(old_leff, new_leff)
        if adj["reps_factor"] != 1.0:
            views.console.print()
            views.print_warning(
                t("equipment.change_detected", description=adj["description"])
            )
            views.print_info(t("equipment.change_hint"))

    update_equipment(
        effective_data_dir(),
        exercise_id,
        active_item=new_eq["active_item"],
        available_items=new_eq["available_items"],
        machine_assistance_kg=new_eq.get("machine_assistance_kg"),
        elevation_height_cm=new_eq.get("elevation_height_cm"),
    )
    views.print_success(t("equipment.updated", exercise_name=exercise["display_name"]))


@profile_app.command("update-equipment")
def update_equipment_cmd(
    exercise_id: ExerciseOption = "pull_up",
) -> None:
    """
    Update equipment for an exercise.

    Shows current equipment, asks what changed, and records a new entry in
    the equipment history. If effective load changes ≥ 10%, shows an
    adjustment recommendation for your next session.

    Example:
        bar-scheduler profile update-equipment --exercise pull_up
    """
    _menu_update_equipment(exercise_id)


def _detect_active_exercises() -> list[str]:
    """Return exercise IDs that have non-empty history."""
    active = []
    for ex in list_exercises():
        try:
            if api_get_history(effective_data_dir(), ex["id"]):
                active.append(ex["id"])
        except HistoryNotFoundError:
            pass
    return active


def _ask_days(label: str, default: int) -> int:
    """Prompt for training days/week (1–5) with a given label and default."""
    while True:
        raw = views.console.input(
            t("profile.days_prompt", label=label, default=default)
        ).strip()
        if not raw:
            return default
        try:
            d = int(raw)
            if d in (1, 2, 3, 4, 5):
                return d
        except ValueError:
            pass
        views.print_error(t("error.enter_1_to_5"))


def _ask_equipment(exercise_id: str, existing: dict | None = None) -> dict:
    """
    Interactively prompt for equipment setup for one exercise.

    Shows numbered options from the exercise catalog; supports multi-select
    for 'available' and single-select for 'active'.  For BSS, shows elevation
    height selection if ELEVATION_SURFACE is chosen.

    Returns a dict with keys: active_item, available_items,
    machine_assistance_kg, elevation_height_cm.
    """
    catalog = get_equipment_catalog(exercise_id)
    items = list(catalog.items())  # [(id, info), ...]
    exercise = get_exercise_info(exercise_id)

    views.console.print()
    views.console.print(
        f"[bold]{t('equipment.title', exercise_name=exercise['display_name'])}[/bold]"
    )
    views.console.print(t("equipment.available_hint"))

    # Show numbered list
    for i, (item_id, info) in enumerate(items, 1):
        default_marker = " [dim](default)[/dim]" if i == 1 else ""
        views.console.print(f"  [{i}] {info['label']}{default_marker}")

    # Default: preserve existing available_items or just the first (base) item
    if existing is not None:
        default_avail = existing["available_items"]
        default_avail_str = ",".join(
            str(i + 1)
            for i, (item_id, _) in enumerate(items)
            if item_id in default_avail
        )
    else:
        default_avail_str = "1"

    while True:
        raw = views.console.input(
            t("equipment.available_prompt", default=default_avail_str)
        ).strip()
        selection_str = raw if raw else default_avail_str
        try:
            indices = [int(x.strip()) for x in selection_str.split(",")]
            if all(1 <= idx <= len(items) for idx in indices):
                available_items = [items[idx - 1][0] for idx in indices]
                break
        except ValueError:
            pass
        views.print_error(t("equipment.available_error", count=len(items)))

    # Select active item from available subset.
    # Only ask when items have different effective assistance -- otherwise the
    # choice has no impact on Leff and prompting is confusing.
    def _effective_assistance(item_id: str) -> object:
        a = catalog[item_id].get("assistance_kg")
        return "machine" if a is None else a

    unique_assistance = {_effective_assistance(iid) for iid in available_items}
    need_active_prompt = len(available_items) > 1 and len(unique_assistance) > 1

    if need_active_prompt:
        views.console.print()
        views.console.print(t("equipment.active_hint"))
        for i, item_id in enumerate(available_items, 1):
            info = catalog[item_id]
            views.console.print(f"  [{i}] {info['label']}")

        if existing is not None and existing["active_item"] in available_items:
            default_active_idx = available_items.index(existing["active_item"]) + 1
        else:
            default_active_idx = 1

        while True:
            raw = views.console.input(
                t("equipment.active_prompt", default=default_active_idx)
            ).strip()
            try:
                idx = int(raw) if raw else default_active_idx
                if 1 <= idx <= len(available_items):
                    active_item = available_items[idx - 1]
                    break
            except ValueError:
                pass
            views.print_error(t("equipment.active_error", count=len(available_items)))
    else:
        # All selected items have the same effective load -- no prompt needed.
        if existing is not None and existing["active_item"] in available_items:
            active_item = existing["active_item"]
        else:
            active_item = available_items[0]

    # Machine-assisted: ask for kg
    machine_assistance_kg: float | None = None
    if active_item == "MACHINE_ASSISTED":
        default_machine = existing.get("machine_assistance_kg") if existing else 40.0
        while True:
            raw = views.console.input(
                t("equipment.machine_kg_prompt", default=default_machine)
            ).strip()
            try:
                val = float(raw) if raw else default_machine
                if val >= 0:
                    machine_assistance_kg = val
                    break
            except (TypeError, ValueError):
                pass
            views.print_error(t("equipment.machine_kg_error"))

    # BSS elevation height
    elevation_height_cm: int | None = None
    if exercise_id == "bss" and "ELEVATION_SURFACE" in available_items:
        heights = get_bss_elevation_heights()
        default_elev = (
            existing.get("elevation_height_cm")
            if existing
            else (heights[0] if heights else 45)
        )
        if not default_elev:
            default_elev = heights[0] if heights else 45
        heights_str = "/".join(str(h) for h in heights)
        while True:
            raw = views.console.input(
                t(
                    "equipment.elevation_prompt",
                    options=heights_str,
                    default=default_elev,
                )
            ).strip()
            try:
                val = int(raw) if raw else default_elev
                if val in heights:
                    elevation_height_cm = val
                    break
            except ValueError:
                pass
            views.print_error(t("equipment.elevation_error", options=heights_str))

    # BSS degraded warning (inline: no elevation surface selected)
    if exercise_id == "bss" and "ELEVATION_SURFACE" not in available_items:
        views.console.print()
        views.print_warning(t("equipment.bss_no_elevation"))

    return {
        "active_item": active_item,
        "available_items": available_items,
        "machine_assistance_kg": machine_assistance_kg,
        "elevation_height_cm": elevation_height_cm,
    }


def _menu_init() -> None:
    """Interactive profile setup helper (profile basics only) called from the main menu."""
    profile_dict = get_profile(effective_data_dir())

    views.console.print()
    views.console.print(t("profile.setup_title"))
    views.console.print(f"[dim]{t('profile.setup_hint')}[/dim]")
    views.console.print(f"[dim]{t('profile.keep_value_hint')}[/dim]")
    views.console.print()

    # Height
    default_h = profile_dict.get("height_cm") if profile_dict else None
    while True:
        prompt = (
            t("profile.height_prompt", default=default_h)
            if default_h is not None
            else "Height cm: "
        )
        raw = views.console.input(prompt).strip()
        if not raw and default_h is not None:
            height_cm = default_h
            break
        try:
            height_cm = int(raw)
            if height_cm > 0:
                break
        except ValueError:
            pass
        views.print_error(t("error.positive_integer"))

    # Sex
    default_sex = profile_dict.get("sex") if profile_dict else None
    while True:
        prompt = (
            t("profile.sex_prompt", default=default_sex)
            if default_sex is not None
            else "Sex (male/female): "
        )
        raw = views.console.input(prompt).strip().lower()
        if not raw and default_sex is not None:
            sex = default_sex
            break
        if raw in ("male", "female"):
            sex = raw
            break
        views.print_error(t("error.sex_invalid"))

    # Global days per week (fallback for exercises without per-exercise override)
    default_days = profile_dict.get("preferred_days_per_week", 3) if profile_dict else 3
    global_days = _ask_days("Global training days per week (default)", default_days)

    # Bodyweight
    default_bw = profile_dict.get("current_bodyweight_kg") if profile_dict else None
    while True:
        prompt = (
            t("profile.bodyweight_prompt", default=f"{default_bw:.1f}")
            if default_bw is not None
            else "Bodyweight kg: "
        )
        raw = views.console.input(prompt).strip()
        if not raw and default_bw is not None:
            bodyweight_kg = default_bw
            break
        try:
            bodyweight_kg = float(raw)
            if bodyweight_kg > 0:
                break
        except ValueError:
            pass
        views.print_error(t("error.positive_number"))

    # Language
    langs = available_languages()
    if len(langs) > 1:
        options_str = "/".join(langs)
        default_lang = profile_dict.get("language", "en") if profile_dict else "en"
        while True:
            raw = (
                views.console.input(
                    t(
                        "profile.language_prompt",
                        options=options_str,
                        default=default_lang,
                    )
                )
                .strip()
                .lower()
            )
            if not raw:
                language = default_lang
                break
            if raw in langs:
                language = raw
                break
            views.print_error(t("profile.language_error", options=options_str))
    else:
        language = "en"

    if profile_dict is None:
        init_profile(
            effective_data_dir(),
            height_cm=height_cm,
            sex=sex,
            bodyweight_kg=bodyweight_kg,
            exercises=[],
            days_per_week=global_days,
            language=language,
        )
        views.console.print()
        views.print_success(
            t("profile.profile_saved", path=effective_data_dir() / "profile.json")
        )
    else:
        update_profile(
            effective_data_dir(),
            height_cm=height_cm,
            sex=sex,
            preferred_days_per_week=global_days,
        )
        api_update_bodyweight(effective_data_dir(), bodyweight_kg)
        api_update_language(effective_data_dir(), language)
        views.console.print()
        views.print_success(t("profile.updated", path=effective_data_dir() / "profile.json"))
    views.console.print(
        "[dim]Use 'profile add-exercise <id>' to set up an exercise.[/dim]"
    )


def _menu_add_exercise(exercise_id: str) -> None:
    """Interactive exercise setup helper -- prompts for days, target, equipment."""
    try:
        exercise = get_exercise_info(exercise_id)
    except (ValueError, KeyError):
        valid = ", ".join(ex["id"] for ex in list_exercises())
        views.print_error(f"Unknown exercise '{exercise_id}'. Valid: {valid}")
        return

    profile_dict = get_profile(effective_data_dir())
    if profile_dict is None:
        views.print_error(
            t("error.profile_not_found", path=effective_data_dir() / "profile.json")
        )
        views.print_info("Run 'profile init' first.")
        return

    if exercise_id in profile_dict.get("exercises_enabled", []):
        views.print_warning(f"Exercise '{exercise_id}' is already enabled.")
        raw = views.console.input("Re-configure it? [y/N] ").strip().lower()
        if raw != "y":
            return
        disable_exercise(effective_data_dir(), exercise_id)
        _wipe_exercise_equipment(effective_data_dir(), exercise_id)
        _wipe_exercise_plan_start(effective_data_dir(), exercise_id)
        delete_exercise_history(effective_data_dir(), exercise_id)

    views.console.print()
    views.console.print(f"[bold]Setting up {exercise['display_name']}[/bold]")

    # Days per week
    default_days = profile_dict.get("exercise_days", {}).get(
        exercise_id, profile_dict.get("preferred_days_per_week", 3)
    )
    days = _ask_days(f"Training days/week -- {exercise['display_name']}", default_days)

    # Target reps
    while True:
        raw = views.console.input(
            t(
                "profile.target_reps_prompt",
                exercise_name=exercise["display_name"],
                default=20,
            )
        ).strip()
        if not raw:
            target_reps = 20
            break
        try:
            target_reps = int(raw)
            if target_reps > 0:
                break
        except ValueError:
            pass
        views.print_error(t("error.positive_integer"))

    # Target weight
    while True:
        raw = views.console.input(
            t(
                "profile.target_weight_prompt",
                exercise_name=exercise["display_name"],
                default="0.0",
            )
        ).strip()
        if not raw:
            target_wt = 0.0
            break
        try:
            target_wt = float(raw)
            if target_wt >= 0:
                break
        except ValueError:
            pass
        views.print_error(t("error.positive_number"))

    enable_exercise(effective_data_dir(), exercise_id)
    set_exercise_target(effective_data_dir(), exercise_id, target_reps, target_wt)
    set_exercise_days(effective_data_dir(), exercise_id, days)

    bw = profile_dict.get("current_bodyweight_kg", 80.0)

    today = datetime.now()
    plan_start = (today + timedelta(days=2)).strftime("%Y-%m-%d")
    set_plan_start_date(effective_data_dir(), exercise_id, plan_start)

    # Equipment
    views.console.print()
    views.console.print(f"[bold]{t('profile.equipment_setup_title')}[/bold]")
    existing_eq = get_current_equipment(effective_data_dir(), exercise_id)
    new_eq = _ask_equipment(exercise_id, existing_eq)
    update_equipment(
        effective_data_dir(),
        exercise_id,
        active_item=new_eq["active_item"],
        available_items=new_eq["available_items"],
        machine_assistance_kg=new_eq.get("machine_assistance_kg"),
        elevation_height_cm=new_eq.get("elevation_height_cm"),
    )

    # Baseline
    raw = views.console.input("Baseline max reps (leave blank to skip): ").strip()
    if raw:
        try:
            baseline_max = int(raw)
            if baseline_max > 0:
                today_str = today.strftime("%Y-%m-%d")
                api_log_session(
                    effective_data_dir(),
                    exercise_id,
                    {
                        "date": today_str,
                        "bodyweight_kg": bw,
                        "grip": exercise["primary_variant"],
                        "session_type": "TEST",
                        "exercise_id": exercise_id,
                        "planned_sets": [{"target_reps": baseline_max}],
                        "completed_sets": [
                            {
                                "actual_reps": baseline_max,
                                "rest_seconds_before": 180,
                                "added_weight_kg": 0.0,
                                "rir_reported": 0,
                            }
                        ],
                        "notes": "Baseline max test",
                    },
                )
                views.print_success(t("profile.logged_baseline", reps=baseline_max))
        except ValueError:
            pass

    views.print_success(f"Exercise '{exercise['display_name']}' set up successfully.")


def _menu_update_weight() -> None:
    """Interactive bodyweight update helper called from the main menu."""
    profile_dict = get_profile(effective_data_dir())
    current_bw = profile_dict.get("current_bodyweight_kg") if profile_dict else None
    default_str = f"{current_bw:.1f}" if current_bw is not None else ""

    views.console.print()
    while True:
        raw = views.console.input(
            t("profile.bodyweight_prompt", default=default_str)
        ).strip()
        if not raw and current_bw is not None:
            views.print_info(t("profile.no_change"))
            return
        try:
            bodyweight_kg = float(raw)
            if bodyweight_kg > 0:
                break
        except ValueError:
            pass
        views.print_error(t("error.positive_number"))

    try:
        api_update_bodyweight(effective_data_dir(), bodyweight_kg)
        views.print_success(t("profile.updated_bodyweight", value=bodyweight_kg))
    except Exception as e:
        views.print_error(str(e))


@profile_app.command("update-language")
def update_language_cmd(
    lang: Annotated[str, typer.Argument(help="Language code: en, ru, zh")],
) -> None:
    """Change the display language saved in your profile."""
    langs = available_languages()
    if lang not in langs:
        views.print_error(t("profile.language_error", options="/".join(langs)))
        raise typer.Exit(1)
    try:
        api_update_language(effective_data_dir(), lang)
        views.print_success(t("profile.updated_language", lang=lang))
    except ProfileNotFoundError as e:
        views.print_error(str(e))
        views.print_info(t("error.run_init_profile"))
        raise typer.Exit(1)
    except Exception as e:
        views.print_error(str(e))
        raise typer.Exit(1)


def _menu_update_language() -> None:
    """Interactive language update helper called from the main menu."""
    profile_dict = get_profile(effective_data_dir())
    current_lang = profile_dict.get("language", "en") if profile_dict else "en"
    langs = available_languages()
    options_str = "/".join(langs)

    views.console.print()
    while True:
        raw = (
            views.console.input(
                t("profile.language_prompt", options=options_str, default=current_lang)
            )
            .strip()
            .lower()
        )
        if not raw:
            views.print_info(t("profile.no_change"))
            return
        if raw in langs:
            break
        views.print_error(t("profile.language_error", options=options_str))

    try:
        api_update_language(effective_data_dir(), raw)
        views.print_success(t("profile.updated_language", lang=raw))
    except Exception as e:
        views.print_error(str(e))
