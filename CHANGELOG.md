# Changelog

All notable changes to **cli-bar** are documented here.

## [Unreleased]

### Added

- **`incline_db_press` (Incline Dumbbell Press)** is now a fully supported exercise (`-e incline_db_press`)
- Equipment setup for dumbbell exercises (`incline_db_press`, `bss`) now prompts for available dumbbell weights (kg, comma-separated); stored via `available_weights_kg` so the planner snaps to discrete weights
- Baseline setup for external-load exercises (`bw_fraction = 0`) now prompts for per-hand dumbbell weight and shows the exercise test protocol before the max-reps prompt
- `profile add-exercise` gains `--baseline-weight` option for non-interactive baseline logging with a specific dumbbell weight
- Prescribed plan column shows `(per hand)` label for `incline_db_press` (mirrors `(per leg)` for BSS)

### Changed

- `profile add-exercise` interactive flow uses the exercise's recommended `target_value` as the default target reps (e.g. 15 for `incline_db_press`) instead of a fixed 20
- For external-load exercises, the target weight prompt shows a hint clarifying it is the per-hand dumbbell weight

### Fixed

- `status` command now shows **My Goal** (was only shown in `plan`)
- Re-configuring an already-enabled exercise (via interactive menu "Re-configure it?" or `profile add-exercise --force`) no longer deletes training history. History is now only deleted when explicitly requested via `profile remove-exercise --delete-history`.

### Added

- `profile update-days --exercise <id> --days <n>` — update training days per week for an exercise without touching history or equipment
- `profile update-target --exercise <id> --reps <n> [--weight <kg>]` — update the rep/weight goal for an exercise without touching history or equipment

### Changed

- **My Goal** line in `status` and `plan` now includes estimated load at the goal: e.g. `30 reps [eLoad: 60]`, making it directly comparable to the Load column in the plan table

## [0.1.1] - 2026-03-24

### Changed

- Updated for bar-scheduler 0.4.3 compatibility:
  - `get_next_band_step` now passes `exercise_id` (required by new signature)
  - BSS elevation height prompt removed from equipment setup — no longer tracked by the planner

## [0.1.0] - 2026-03-23

Initial release -- CLI interface extracted from the monolithic bar-scheduler project into its own installable package.

### Added

**Profile management**
- `profile init` -- create or update user profile (height, sex, bodyweight, days/week); `--force` re-initialises without wiping exercises
- `profile add-exercise <id>` -- interactively add and configure an exercise (target, days/week, equipment, optional baseline test); `--force` wipes and re-adds
- `profile remove-exercise <id>` -- remove exercise from profile; `--delete-history` also removes history file
- `profile update-weight <kg>` -- update current bodyweight
- `profile update-equipment` -- configure bands, machine assistance, or BSS elevation with Leff-change notification
- `profile update-language <code>` -- persist display language (en / ru / zh)

**Training plan**
- `plan` -- unified history + upcoming sessions table; `--weeks N`; `--baseline-max N`; `--json`
- `refresh-plan` -- reset plan anchor to today after a break; `--json`
- `explain <DATE|next>` -- step-by-step breakdown of how any session was planned

**Session logging**
- `log-session` -- log a completed session (interactive or one-liner with `--sets`, `--rir`, `--notes`); `--json`
- `show-history` -- session history table; `--limit N`; `--json`
- `delete-record <N>` -- delete a session by ID

**Analysis**
- `status` -- current training max, readiness z-score, plateau/deload flags; `--json`
- `volume` -- weekly rep volume ASCII bar chart; `--weeks N`; `--json`
- `plot-max` -- ASCII max-reps progress chart; `-t z/g/m` trajectory overlays; `--json`
- `1rm` -- 1-rep max estimate (Epley, Brzycki, Lander, Lombardi, Blended) with ★ best-formula marker; `--json`
- `help-adaptation` -- built-in adaptation timeline guide

**UX**
- Interactive menu (run `cli-bar` with no arguments)
- `--exercise / -e` global flag -- sets default exercise for the whole session
- `--lang` flag -- per-session language override; falls back to profile setting, then `en`
- Rich-formatted tables and coloured output throughout
- JSON output mode (`--json`) on most commands for scripting
