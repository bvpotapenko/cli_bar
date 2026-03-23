# cli-bar -- Command & Feature Reference

This document covers every command, flag, and UX behaviour provided by the CLI. For the underlying training algorithm (adaptation logic, formulas, plan engine), see the [bar-scheduler library](https://github.com/bvpotapenko/bar-scheduler).

---

## 1. Profile Management (`profile` subcommand group)

| # | Feature | Command / flag |
|---|---------|---------------|
| 1.1 | Create user profile (height, sex, bodyweight, default days/week) | `profile init --height-cm H --sex S --bodyweight-kg W` |
| 1.2 | Re-initialise without wiping exercises | `profile init ... --force` |
| 1.3 | Add an exercise with target, days/week, equipment, optional baseline | `profile add-exercise <id>` |
| 1.4 | Supply baseline max reps non-interactively | `profile add-exercise <id> --baseline-max N` |
| 1.5 | Wipe and re-add an existing exercise | `profile add-exercise <id> --force` |
| 1.6 | Remove exercise from profile | `profile remove-exercise <id>` |
| 1.7 | Also delete the history file on removal | `profile remove-exercise <id> --delete-history` |
| 1.8 | Update current bodyweight | `profile update-weight <kg>` |
| 1.9 | Configure equipment (bands, machine assistance, BSS elevation) | `profile update-equipment` |
| 1.10 | Leff-change warning shown when effective load shifts ≥10% | automatic, shown after equipment update |
| 1.11 | Save display language to profile | `profile update-language <code>` |
| 1.12 | Interactive setup wizard | menu `[i]` (profile) / menu `[a]` (add exercise) |

---

## 2. Session Logging

| # | Feature | Command / flag |
|---|---------|---------------|
| 2.1 | Log a completed session interactively (step-by-step prompts) | `log-session` (no flags) |
| 2.2 | Log a session in one line | `log-session --sets "4x5 +2kg / 240s"` |
| 2.3 | Exercise selection prompt when multiple exercises are configured | interactive log |
| 2.4 | Compact set format: `4x5 +2kg / 240s` expands to individual sets | `--sets` |
| 2.5 | Per-set format: `reps@weight/rest`, `reps weight rest`, or bare `reps` | `--sets` |
| 2.6 | Default rest of 180 s when omitted | automatic |
| 2.7 | Reps-in-reserve capture | `--rir N` or interactive prompt |
| 2.8 | Session notes | `--notes TEXT` or interactive prompt |
| 2.9 | JSON output after logging | `log-session --json` |
| 2.10 | Delete a logged session by display ID | `delete-record N` or menu `[d]` |
| 2.11 | Show session history table | `show-history` |
| 2.12 | Limit history rows | `show-history --limit N` |
| 2.13 | History JSON export | `show-history --json` |

---

## 3. Training Plan

| # | Feature | Command / flag |
|---|---------|---------------|
| 3.1 | Unified past + upcoming plan table | `plan` |
| 3.2 | Configurable plan horizon | `plan --weeks N` |
| 3.3 | Supply baseline max non-interactively | `plan --baseline-max N` |
| 3.4 | Plan change notifications (diff vs last run) | automatic, printed before table |
| 3.5 | Overtraining level warnings (levels 1–3) with rest-day advice | automatic, printed before table |
| 3.6 | Goal-reached notification | automatic, printed before table |
| 3.7 | Plan JSON export | `plan --json` |
| 3.8 | Reset plan anchor to today after a break | `refresh-plan` |
| 3.9 | Refresh JSON output | `refresh-plan --json` |
| 3.10 | Step-by-step session explanation | `explain YYYY-MM-DD` or `explain next` |
| 3.11 | Interactive explain (respects current exercise) | menu `[e]` |

---

## 4. Analysis

| # | Feature | Command / flag |
|---|---------|---------------|
| 4.1 | Current training max, readiness, plateau/deload flags | `status` |
| 4.2 | Status JSON export | `status --json` |
| 4.3 | Weekly rep volume ASCII bar chart | `volume` |
| 4.4 | Volume weeks range | `volume --weeks N` |
| 4.5 | Volume JSON export | `volume --json` |
| 4.6 | ASCII max-reps progress chart | `plot-max` |
| 4.7 | Trajectory overlays: `z` = BW reps, `g` = goal-weight reps, `m` = 1RM added kg | `plot-max -t z/g/m` or `-t zmg` |
| 4.8 | 1RM estimate -- 5 formulas with ★ best-formula marker | `1rm` |
| 4.9 | 1RM JSON export | `1rm --json` |
| 4.10 | Adaptation timeline guide | `help-adaptation` or menu `[h]` |

---

## 5. Multi-Exercise & Language

| # | Feature | Command / flag |
|---|---------|---------------|
| 5.1 | Supported exercises: `pull_up`, `dip`, `bss` | `--exercise / -e` |
| 5.2 | Global `-e` flag sets exercise for the whole session | `cli-bar -e dip` |
| 5.3 | Per-session language override | `--lang en/ru/zh` |
| 5.4 | Persistent language in profile | `profile update-language <code>` |
| 5.5 | Language fallback chain: `--lang` → profile → `en` | automatic |

---

## 6. Interactive Menu

Run `cli-bar` with no arguments. All options work without any flags.

| Key | Action |
|-----|--------|
| `1` | Show training log & plan |
| `2` | Log today's session |
| `3` | Show full history |
| `4` | Progress chart |
| `5` | Current status |
| `6` | Update bodyweight |
| `7` | Weekly volume chart |
| `e` | Explain how a session was planned |
| `r` | Estimate 1-rep max |
| `f` | Reset plan to today (after a break) |
| `u` | Update training equipment |
| `l` | Change display language |
| `i` | Setup / edit profile |
| `a` | Add / reconfigure an exercise |
| `d` | Delete a session by ID |
| `h` | How the planner adapts over time |
| `0` | Quit |

---

*Last updated: 2026-03-23 (0.1.0 -- initial CLI extraction)*
