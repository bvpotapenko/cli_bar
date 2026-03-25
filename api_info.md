# bar-scheduler Python Library API

All public operations live in a single module. Every function takes `data_dir: Path` as its first argument -- point different users at different directories for multi-user isolation (e.g. a Telegram bot serving multiple users).

## Import cheat sheet

```python
from pathlib import Path
from bar_scheduler.api import (
    # Exceptions
    ProfileAlreadyExistsError, ProfileNotFoundError, HistoryNotFoundError,
    SessionNotFoundError, ValidationError,
    # Profile & user
    init_profile, get_profile, update_profile,
    update_bodyweight, update_language,
    # Equipment
    update_equipment,
    # Exercises
    list_exercises, get_exercise_info, get_equipment_catalog,
    set_exercise_target, set_exercise_days,
    enable_exercise, disable_exercise, delete_exercise_history,
    # Sessions
    log_session, delete_session, get_history,
    # Planning
    get_plan, refresh_plan, explain_session,
    # Plan configuration
    set_plan_start_date, get_plan_weeks, set_plan_weeks, get_plan_cache_entry,
    # Analysis
    get_training_status, get_onerepmax_data,
    get_volume_data, get_progress_data, get_overtraining_status, get_load_data,
    compute_session_load,
    # Equipment helpers
    get_current_equipment, check_band_progression,
    compute_leff, compute_equipment_adjustment, get_assistance_kg,
    get_next_band_step, get_assist_progression,
    # Utilities
    get_data_dir, training_max_from_baseline,
    # Input parsers
    parse_sets_string, parse_compact_sets,
)
# Input types (optional — for typed session logging)
from bar_scheduler.api.types import SessionType, SetInput, SessionInput
```

Everything you need is in `bar_scheduler.api`.

### Multi-user pattern

```python
data_dir = Path.home() / ".bar-scheduler" / "users" / str(user_id)
```

Pass this `data_dir` to every API call for that user. The directory is created automatically on `init_profile`.

---

## Error contract

| Exception | When raised |
|---|---|
| `ProfileAlreadyExistsError` | `init_profile` called on an already-initialised directory |
| `ProfileNotFoundError` | any function when `profile.json` is missing |
| `HistoryNotFoundError` | exercise functions when the JSONL history file is missing |
| `SessionNotFoundError` | `delete_session` index out of range |
| `ValidationError` | malformed stored data |
| `ValueError` | bad argument -- unknown exercise ID, invalid field value, etc. |

All exceptions carry a human-readable message. Clients can display `str(exc)` directly.

---

## 1. Profile: check & create

```python
# Check whether a profile exists
profile = get_profile(data_dir)   # dict | None
exists = profile is not None

# Create bare profile -- exercises are added separately with enable_exercise()
profile = init_profile(
    data_dir,
    height_cm=180,
    bodyweight_kg=82.0,
    language="en",                # any language code; stored in profile for client use
    rest_preference="normal",     # "short" | "normal" | "long"
)
# returns same dict as get_profile()
```

`get_profile()` returns all profile fields plus `current_bodyweight_kg`. Fields:

| Key | Type | Notes |
|---|---|---|
| `height_cm` | `int` | |
| `exercise_days` | `dict` | `{"pull_up": 3}` — per-exercise training days (1–5) |
| `exercise_targets` | `dict` | `{"pull_up": {"reps": 25, "weight_kg": 0.0}}` |
| `exercises_enabled` | `list` | e.g. `["pull_up", "dip"]` |
| `rest_preference` | `str` | `"short"` \| `"normal"` \| `"long"` |
| `injury_notes` | `str` | free text |
| `language` | `str` | ISO 639-1 |
| `current_bodyweight_kg` | `float` | not in UserProfile; appended by get_profile |

---

## 2. Profile: edit

```python
# Update any subset of fields -- everything else is preserved
profile = update_profile(
    data_dir,
    height_cm=182,
    rest_preference="short",
    injury_notes="sore right shoulder",
)
# returns updated profile dict

update_bodyweight(data_dir, 83.5)

update_language(data_dir, "ru")    # passing "en" removes the key (restores default)
```

`update_profile` is surgical: `plan_start_dates`, `equipment`, and other internal keys
stored in `profile.json` are never touched.

---

## 3. Exercises: list, add, remove, configure

```python
# All registered exercises -- no data_dir needed
exercises = list_exercises()
# each dict: id, display_name, muscle_group, variants, primary_variant,
#            has_variant_rotation, bw_fraction, onerm_includes_bodyweight,
#            session_params, onerm_explanation

# Single exercise by ID (raises ValueError for unknown IDs)
info = get_exercise_info("pull_up")
info["session_params"]["S"]["reps_min"]   # e.g. 4
info["onerm_explanation"]                 # str describing the 1RM formula

# Add / remove
# days_per_week (1–5) is required — sets training frequency for this exercise
enable_exercise(data_dir, "dip", days_per_week=4)  # idempotent; creates JSONL if missing
disable_exercise(data_dir, "dip")                  # no-op if not enabled; history file kept
delete_exercise_history(data_dir, "dip")            # permanently delete the JSONL file

# Per-exercise goal
set_exercise_target(data_dir, "pull_up", reps=25)               # bodyweight-only goal
set_exercise_target(data_dir, "dip", reps=15, weight_kg=20.0)   # weighted goal

# Override per-exercise training frequency after enabling
set_exercise_days(data_dir, "dip", 4)
```

Built-in exercise IDs: `"pull_up"`, `"dip"`, `"bss"`. Any other ID raises `ValueError`.

---

## 4. Equipment: configure & query

```python
# Discover available items for an exercise
catalog = get_equipment_catalog("pull_up")
# → {"BAR_ONLY": {"assistance_kg": 0}, "BAND_LIGHT": {"assistance_kg": 8},
#    "BAND_MEDIUM": {"assistance_kg": 15}, "BAND_HEAVY": {"assistance_kg": 25},
#    "MACHINE_ASSISTED": {"assistance_kg": 0}, "WEIGHT_BELT": {"assistance_kg": 0}}

# Set or update equipment (closes the previous active entry, appends a new one)
# No active_item — the planner auto-selects the right item each session
update_equipment(
    data_dir, "pull_up",
    available_items=["BAR_ONLY", "BAND_MEDIUM", "WEIGHT_BELT"],
    # machine_assistance_kg=None   # required for MACHINE_ASSISTED; kg of assistance
    # elevation_height_cm=None     # required for BSS ELEVATION_SURFACE: 30 | 45 | 60
    # valid_from=None              # ISO date; defaults to today
)

# Read current equipment state (None if never configured)
eq = get_current_equipment(data_dir, "pull_up")
# → {"exercise_id", "recommended_item", "available_items", "machine_assistance_kg",
#    "elevation_height_cm", "assistance_kg", "is_bss_degraded"}
# recommended_item is auto-selected from available_items based on current TM and
# band-progression readiness (WEIGHT_BELT when TM > threshold, else best band/bar)

# Band/load computations (no data_dir -- pure math)
leff = compute_leff(bw_fraction=1.0, bodyweight_kg=82.0,
                    added_weight_kg=10.0, assistance_kg=0.0)  # → 92.0
adj  = compute_equipment_adjustment(old_leff=72.0, new_leff=82.0)
# → {"reps_factor": 0.80, "description": "..."}
kg   = get_assistance_kg("pull_up", "BAND_LIGHT")   # → 8.0

# Band progression
ready = check_band_progression(data_dir, "pull_up", n_sessions=2)  # bool
next_item = get_next_band_step("BAND_MEDIUM", "pull_up")  # → "BAND_LIGHT"
get_assist_progression("pull_up")  # → ["BAND_HEAVY", "BAND_MEDIUM", "BAND_LIGHT", "BAR_ONLY"]
get_assist_progression("bss")      # → []  (BSS has no fixed-assistance progression)
```

Equipment history is preserved (append-only). The previous active entry gets
`valid_until = yesterday` and the new entry starts with `valid_until = None`.

---

## 5. History: read

```python
history = get_history(data_dir, "pull_up")
# → list[dict], sorted by date

for s in history:
    s["date"]           # "YYYY-MM-DD"
    s["session_type"]   # "S" | "H" | "E" | "T" | "TEST"
    s["grip"]           # exercise-specific variant, e.g. "pronated"
    s["exercise_id"]    # "pull_up"
    s["bodyweight_kg"]  # float

    for cs in s["completed_sets"]:
        cs["actual_reps"]          # int
        cs["added_weight_kg"]      # float (0 = bodyweight only)
        cs["rest_seconds_before"]  # int
        cs["rir_reported"]         # int | None

    s["equipment_snapshot"]   # dict | None -- equipment active at log time
    s["notes"]                # str | None
```

Session types: `S` = Strength, `H` = Hypertrophy, `E` = Endurance, `T` = Technique,
`TEST` = max-rep assessment.

---

## 6. History: log & delete

```python
# Log a session -- returns the persisted session dict
result = log_session(data_dir, "pull_up", {
    "date": "2026-03-22",
    "bodyweight_kg": 82.0,
    "grip": "pronated",
    "session_type": "S",
    "exercise_id": "pull_up",
    "completed_sets": [
        {"actual_reps": 5, "rest_seconds_before": 180, "rir_reported": 2},
        {"actual_reps": 4, "rest_seconds_before": 180, "rir_reported": 1},
        {"actual_reps": 3, "rest_seconds_before": 180, "rir_reported": 0},
    ],
})
# equipment_snapshot is auto-attached from the current profile equipment if omitted.
# A session with the same (date, session_type) replaces the existing entry.
# Optional set fields: target_reps (default 0), added_weight_kg (default 0.0),
#                      rir_target (default 2)

# Delete by 1-based index -- matches the "id" field returned by get_plan
delete_session(data_dir, "pull_up", 3)   # raises SessionNotFoundError if out of range
```

---

## 7. Training plan

```python
plan = get_plan(data_dir, "pull_up", weeks_ahead=4)
```

### `plan["status"]`

| Key | Type | Notes |
|---|---|---|
| `training_max` | `int` | `floor(0.9 × latest_test_max)` |
| `latest_test_max` | `int \| None` | best TEST session max |
| `trend_slope_per_week` | `float` | reps/week linear regression |
| `is_plateau` | `bool` | |
| `deload_recommended` | `bool` | |
| `readiness_z_score` | `float` | autoregulation signal |
| `fitness` | `float` | G(t) -- slow-decay fitness impulse |
| `fatigue` | `float` | H(t) -- fast-decay fatigue impulse |

### `plan["sessions"]` -- unified timeline (past + future)

```python
for s in plan["sessions"]:
    s["date"]          # "YYYY-MM-DD"
    s["status"]        # "done" | "next" | "planned" | "missed" | "extra"
    s["type"]          # "S" | "H" | "E" | "T" | "TEST"
    s["grip"]          # variant string
    s["week"]          # int, 1-indexed calendar week
    s["expected_tm"]   # int | None -- projected TM at this session
    s["id"]            # int | None -- 1-based history index (use with delete_session)

    for ps in (s["prescribed_sets"] or []):
        ps["reps"], ps["weight_kg"], ps["rest_s"]

    for a in (s["actual_sets"] or []):
        a["reps"], a["weight_kg"]

    if s["track_b"]:   # between-test max estimates for past non-TEST sessions
        s["track_b"]["fi_est"]     # FI method estimate
        s["track_b"]["nuzzo_est"]  # Nuzzo method estimate
```

### `plan["overtraining"]`

```python
plan["overtraining"]["level"]           # int 0–3 (0 = none, 3 = severe)
plan["overtraining"]["description"]     # str
plan["overtraining"]["extra_rest_days"] # int
```

### `plan["plan_changes"]`

List of human-readable strings describing what changed vs. the last cached plan.
Empty on first call.

### Refresh plan anchor

```python
result = refresh_plan(data_dir, "pull_up")
result["plan_start_date"]   # "YYYY-MM-DD" -- new anchor (today)
result["next_session"]      # {"date": ..., "session_type": ..., "grip": ...} | None
```

Call after a break when unlogged sessions have accumulated in the past.

### Plan configuration

```python
# Persist / recall the plan horizon
set_plan_weeks(data_dir, 6)
weeks = get_plan_weeks(data_dir)   # → 6 | None

# Manually reset the plan anchor (e.g. after a long break)
set_plan_start_date(data_dir, "pull_up", "2026-04-01")

# Pre-populate a session log form with the planned prescription
entry = get_plan_cache_entry(data_dir, "pull_up", "2026-04-03", "S")
# → cached session dict | None
```

---

## 8. Explanation text

```python
text = explain_session(data_dir, "pull_up", "2026-03-24")

# Use "next" to explain the first upcoming session:
text = explain_session(data_dir, "pull_up", "next")
```

`text` is a Rich markup string. Strip markup for plain text (e.g. Telegram):

```python
from rich.text import Text
plain = Text.from_markup(text).plain
```

Fallback logic:
1. Date is a planned session → full breakdown (TM formula, grip rotation, sets, weight, rest)
2. Date is within the horizon but not a training day → rest day message
3. Date is in history → brief session summary

---

## 9. Analysis

```python
# Training status (same shape as plan["status"])
status = get_training_status(data_dir, "pull_up")

# Overtraining severity
ot = get_overtraining_status(data_dir, "pull_up")
ot["level"]            # int 0–3
ot["description"]      # str
ot["extra_rest_days"]  # int

# 1-rep max estimate -- None if no eligible history
onerepmax = get_onerepmax_data(data_dir, "pull_up")
if onerepmax:
    onerepmax["formulas"]             # {"epley": float, "brzycki": float,
                                      #  "lander": float, "lombardi": float, "blended": float}
    onerepmax["recommended_formula"]  # str -- most accurate for this rep count
    onerepmax["best_reps"]            # int
    onerepmax["best_added_weight_kg"] # float
    onerepmax["effective_load_kg"]    # float -- bodyweight × bw_fraction + added
    onerepmax["best_date"]            # "YYYY-MM-DD"

# Weekly rep volume
vol = get_volume_data(data_dir, "pull_up", weeks=4)
for w in vol["weeks"]:
    w["label"]       # "This week" | "Last week" | "2 weeks ago" | …
    w["week_start"]  # "YYYY-MM-DD" (Monday) | None
    w["total_reps"]  # int

# Progress data for plotting (no chart generation -- returns raw data)
progress = get_progress_data(data_dir, "pull_up", trajectory_types="z")
# trajectory_types is a string of letters:
#   "z" -- projected bodyweight reps over time
#   "g" -- projected reps at goal weight
#   "m" -- projected 1RM in added kg

for pt in progress["data_points"]:       # TEST sessions only
    pt["date"], pt["max_reps"]

for pt in (progress["trajectory_z"] or []):
    pt["date"], pt["projected_bw_reps"]

for pt in (progress["trajectory_g"] or []):
    pt["date"], pt["projected_goal_reps"]

for pt in (progress["trajectory_m"] or []):
    pt["date"], pt["projected_1rm_added_kg"]

# Training load for a single hypothetical set -- use with goal reps/weight
# to display how hard a goal session would be relative to history / plan.
load = compute_session_load(data_dir, "dip", reps=12, added_weight_kg=25.0)
# Optional keyword arguments (all have defaults):
#   rir=2            -- reps in reserve (default 2, plan-session neutral effort)
#   bodyweight_kg    -- override session bodyweight; defaults to current profile value
#   grip             -- variant string; defaults to the exercise's primary variant
```

---

## Storage layout

```
~/.bar-scheduler/                      (or any custom data_dir)
  profile.json                         -- profile + bodyweight + equipment history + plan anchors
  pull_up_history.jsonl                -- one JSON line per session
  dip_history.jsonl
  bss_history.jsonl
  pull_up_plan_cache.json              -- last plan snapshot for change diffing
  dip_plan_cache.json
```

```python
get_data_dir()                     # Path("~/.bar-scheduler") -- default single-user path
training_max_from_baseline(12)     # → 10  (floor(baseline × 0.9), min 1)
```

---

## Input parsing

Parse user-typed sets strings — useful for bots and CLIs collecting session data:

```python
# Compact format:  "N×reps"  or  "sets×reps/rest_s"  or  "4×1 3×8/60s"
# Per-set format:  "reps@weight/rest"  or  "reps weight rest"  or  bare "reps"

sets = parse_sets_string("3×5/120s")
# → [(3, 0.0, 120), (3, 0.0, 120), (3, 0.0, 120), (3, 0.0, 120), (3, 0.0, 120)]
#   (5 sets of 3 reps, 120 s rest, 0 kg added weight)

sets = parse_sets_string("5@10/180 4@10/180 3@10")
# → [(5, 10.0, 180), (4, 10.0, 180), (3, 10.0, 0)]

# Returns None if the string is not in compact format:
parse_compact_sets("8")         # → None
parse_compact_sets("3×5/120s")  # → [(3, 0.0, 120), ...]
```

Each tuple is ``(reps: int, added_weight_kg: float, rest_seconds: int)``.
``parse_sets_string`` raises ``ValidationError`` on invalid input.
