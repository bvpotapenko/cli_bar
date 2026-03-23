"""
CLI entry point — thin assembler.

Imports all command modules (which registers their commands on `app`),
then attaches the interactive main-menu callback.
"""

import json
import typer

from . import views
from .app import ExerciseOption, LangOption, app
from .commands import analysis, planning, profile, sessions  # noqa: F401 — side-effect: registers commands
app.add_typer(profile.profile_app)
from bar_scheduler.core.exercises.registry import get_exercise
from bar_scheduler.core.i18n import available_languages, set_language, t


def _read_language_from_profile() -> str:
    """
    Read the language setting from profile.json without going through HistoryStore.

    Returns "en" on any failure (missing file, parse error, no language key).
    Intentionally lightweight: called early in main_callback before exercise
    routing is established.
    """
    try:
        from ..io.history_store import get_data_dir
        profile_path = get_data_dir() / "profile.json"
        if profile_path.exists():
            with open(profile_path, encoding="utf-8") as fh:
                data = json.load(fh)
            return str(data.get("language", "en"))
    except Exception:
        pass
    return "en"


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    exercise_id: ExerciseOption = "pull_up",
    lang: LangOption = None,
) -> None:
    """
    Strength training planner. Run without a command for interactive mode.

    Use -e/--exercise to set the default exercise for the whole session:
      bar-scheduler -e dip        opens menu with dip pre-selected
      bar-scheduler -e bss plan   runs the plan command for BSS

    Use --lang to override the display language for this session:
      bar-scheduler --lang ru     Russian interface
      bar-scheduler --lang zh     Chinese interface
    """
    # ── Resolve language: --lang > profile.json > "en" ───────────────────────
    # Must happen before any output (including the early-return path for subcommands)
    resolved_lang = lang if lang else _read_language_from_profile()
    set_language(resolved_lang)

    if ctx.invoked_subcommand is not None:
        return  # A sub-command was given — let it handle things

    # ── Interactive main menu ─────────────────────────────────────────────────
    views.console.print()
    try:
        ex_name = get_exercise(exercise_id).display_name
        header = t("app.tagline_exercise", exercise_name=ex_name)
    except Exception:
        header = t("app.tagline")
    views.console.print(header)
    views.console.print()

    langs = available_languages()
    menu = {
        "1": ("plan",             t("menu.show_plan")),
        "2": ("log-session",      t("menu.log_session")),
        "3": ("show-history",     t("menu.show_history")),
        "4": ("plot-max",         t("menu.plot_max")),
        "5": ("status",           t("menu.status")),
        "6": ("update-weight",    t("menu.update_weight")),
        "7": ("volume",           t("menu.volume")),
        "e": ("explain",          t("menu.explain")),
        "r": ("1rm",              t("menu.onerepmax")),
        "f": ("refresh-plan",     t("menu.refresh_plan")),
        "u": ("update-equipment", t("menu.update_equipment")),
        "l": ("update-language",  t("menu.update_language")),
        "i": ("init",             t("menu.init")),
        "a": ("add-exercise",     t("menu.add_exercise")),
        "d": ("delete-record",    t("menu.delete_record")),
        "h": ("help-adaptation",  t("menu.help_adaptation")),
        "0": ("quit",             t("menu.quit")),
    }

    for key, (_, desc) in menu.items():
        views.console.print(f"  \\[{key}] {desc}")

    # Show available languages as a hint
    if len(langs) > 1:
        views.console.print(f"\n  [dim]--lang {'/'.join(langs)}[/dim]")

    views.console.print()
    choice = views.console.input(t("menu.prompt")).strip() or "1"

    if choice == "0":
        raise typer.Exit(0)

    cmd_map = {k: v[0] for k, v in menu.items()}
    chosen = cmd_map.get(choice)

    if chosen is None:
        views.print_error(t("menu.unknown_choice", choice=choice))
        raise typer.Exit(1)

    if chosen == "plan":
        ctx.invoke(planning.plan, exercise_id=exercise_id)
    elif chosen == "log-session":
        ctx.invoke(sessions.log_session, exercise_id=exercise_id)
    elif chosen == "show-history":
        ctx.invoke(sessions.show_history, exercise_id=exercise_id)
    elif chosen == "plot-max":
        ctx.invoke(analysis.plot_max, exercise_id=exercise_id)
    elif chosen == "status":
        ctx.invoke(analysis.status, exercise_id=exercise_id)
    elif chosen == "update-weight":
        profile._menu_update_weight()
    elif chosen == "volume":
        ctx.invoke(analysis.volume, exercise_id=exercise_id)
    elif chosen == "explain":
        planning._menu_explain(exercise_id)
    elif chosen == "1rm":
        ctx.invoke(analysis.onerepmax, exercise_id=exercise_id)
    elif chosen == "refresh-plan":
        ctx.invoke(planning.refresh_plan, exercise_id=exercise_id)
    elif chosen == "update-equipment":
        profile._menu_update_equipment(exercise_id)
    elif chosen == "update-language":
        profile._menu_update_language()
    elif chosen == "init":
        profile._menu_init()
    elif chosen == "add-exercise":
        profile._menu_add_exercise(exercise_id)
    elif chosen == "delete-record":
        sessions._menu_delete_record(exercise_id)
    elif chosen == "help-adaptation":
        ctx.invoke(analysis.help_adaptation)


if __name__ == "__main__":
    app()
