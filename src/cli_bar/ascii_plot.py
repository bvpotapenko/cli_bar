"""
ASCII plotting for max reps progress visualization.

Creates terminal-friendly plots showing training progress over time.
"""

from datetime import datetime


def create_max_reps_plot(
    data_points: list[dict],
    width: int = 60,
    height: int = 20,
    target: int = 30,
    trajectory_z: list[tuple[datetime, float]] | None = None,
    trajectory_g: list[tuple[datetime, float]] | None = None,
    trajectory_m: list[tuple[datetime, float]] | None = None,
    bw_load_kg: float = 0.0,
    target_weight_kg: float = 0.0,
    exercise_name: str = "Pull-Up",
    traj_types: frozenset[str] = frozenset(),
) -> str:
    """
    Create an ASCII plot of max reps progress over time.

    Args:
        data_points: List of dicts with "date" (YYYY-MM-DD str) and "max_reps" (int) from TEST sessions
        width: Plot width in characters (expands by 6 when trajectory_m provided for right axis)
        height: Plot height in lines
        target: Target max reps (for y-axis scaling)
        trajectory_z: Projected bodyweight reps; plotted as ·
        trajectory_g: Projected reps at goal weight; plotted as ×
        trajectory_m: Projected 1RM added kg (blended formula); plotted as ○ on right axis
        bw_load_kg: BW × bw_fraction -- used with trajectory_m for right axis
        target_weight_kg: Added weight for goal (used in legend)
        exercise_name: Display name shown in chart title
        traj_types: Set of requested trajectory flags (z/g/m); used for legend labels

    Returns:
        ASCII art string
    """
    if not data_points:
        return "No test sessions recorded yet. Log a TEST session to see progress."

    points: list[tuple[datetime, int]] = []
    for dp in data_points:
        date = datetime.strptime(dp["date"], "%Y-%m-%d")
        if dp["max_reps"] > 0:
            points.append((date, dp["max_reps"]))

    if not points:
        return "No valid test results found."

    # Sort by date
    points.sort(key=lambda x: x[0])

    # Calculate x-axis range -- extend to cover trajectory endpoints
    min_date = points[0][0]
    max_date = points[-1][0]

    for traj in (trajectory_z, trajectory_g, trajectory_m):
        if traj:
            traj_end = traj[-1][0]
            if traj_end > max_date:
                max_date = traj_end

    date_range = (max_date - min_date).days
    if date_range == 0:
        date_range = 1

    min_reps = min(p[1] for p in points)
    max_reps_val = max(p[1] for p in points)

    # Y-axis range -- extend to include target and trajectory_g minimum
    y_min = max(0, min_reps - 2)
    y_max = max(max_reps_val + 2, target)

    if trajectory_g:
        g_positive = [v for _, v in trajectory_g if v > 0]
        if g_positive:
            y_min = max(0, min(y_min, int(min(g_positive)) - 1))

    y_range = y_max - y_min
    if y_range == 0:
        y_range = 1

    # Create the plot grid
    show_right_axis = bool(trajectory_m)
    right_axis_width = 6 if show_right_axis else 0  # "┤123kg" = 6 chars

    # Independent right-axis calibration from m trajectory range
    if show_right_axis:
        m_vals = [v for _, v in trajectory_m]  # type: ignore[union-attr]
        right_y_min = 0.0
        right_y_max = max(m_vals) * 1.1 if m_vals else 1.0
        if right_y_max <= 0:
            right_y_max = 1.0
        right_y_range = right_y_max - right_y_min
    else:
        right_y_min = right_y_max = right_y_range = 0.0
    plot_width = width - 6  # Leave room for left y-axis labels
    plot_height = height - 3  # Leave room for x-axis and title

    # Initialize grid with spaces
    grid = [[" " for _ in range(plot_width)] for _ in range(plot_height)]

    # Convert points to grid coordinates
    plot_points: list[tuple[int, int, int]] = []  # (x, y, reps)
    for date, reps in points:
        days_from_start = (date - min_date).days
        x = (
            int((days_from_start / date_range) * (plot_width - 1))
            if date_range > 0
            else 0
        )
        y = int(((reps - y_min) / y_range) * (plot_height - 1))
        y = plot_height - 1 - y  # Flip y-axis
        plot_points.append((x, y, reps))

    def _grid_pos(traj_date: datetime, traj_val: float) -> tuple[int, int] | None:
        """Convert a trajectory (date, value) to grid (x, y). Returns None if out of range."""
        days_from_start = (traj_date - min_date).days
        if days_from_start < 0:
            return None
        x = (
            int((days_from_start / date_range) * (plot_width - 1))
            if date_range > 0
            else 0
        )
        y_raw = (traj_val - y_min) / y_range
        y = int(plot_height - 1 - y_raw * (plot_height - 1))
        if 0 <= x < plot_width and 0 <= y < plot_height:
            return x, y
        return None

    # Draw trajectory_g (goal-weight reps) as × -- before trajectory_z so z dots take priority
    if trajectory_g:
        for traj_date, traj_val in trajectory_g:
            pos = _grid_pos(traj_date, traj_val)
            if pos:
                x, y = pos
                if grid[y][x] == " ":
                    grid[y][x] = "×"

    # Draw trajectory_z (bodyweight reps) as · -- overwrites × if same cell
    if trajectory_z:
        for traj_date, traj_val in trajectory_z:
            pos = _grid_pos(traj_date, traj_val)
            if pos:
                x, y = pos
                if grid[y][x] in (" ", "×"):  # · takes priority over ×
                    grid[y][x] = "·"

    # Draw trajectory_m (1RM added kg) as ○ -- uses independent right-axis y-coordinate
    if trajectory_m and right_y_range > 0:
        for traj_date, m_val in trajectory_m:
            days_from_start = (traj_date - min_date).days
            if days_from_start < 0:
                continue
            x = (
                int((days_from_start / date_range) * (plot_width - 1))
                if date_range > 0
                else 0
            )
            y_raw = (m_val - right_y_min) / right_y_range
            y = int(plot_height - 1 - y_raw * (plot_height - 1))
            if 0 <= x < plot_width and 0 <= y < plot_height and grid[y][x] == " ":
                grid[y][x] = "○"

    # Draw connecting lines (staircase style: ╭-╯)
    for i in range(len(plot_points) - 1):
        col1, row1, _ = plot_points[i]
        col2, row2, _ = plot_points[i + 1]

        n_rows = abs(row2 - row1)
        if n_rows == 0:
            # Same grid row: pure horizontal segment
            for x in range(col1 + 1, col2):
                if 0 <= x < plot_width and grid[row1][x] == " ":
                    grid[row1][x] = "-"
            continue

        if col1 == col2:
            # Same x column: pure vertical segment
            for r in range(min(row1, row2) + 1, max(row1, row2)):
                if (
                    0 <= col1 < plot_width
                    and 0 <= r < plot_height
                    and grid[r][col1] == " "
                ):
                    grid[r][col1] = "│"
            continue

        row_dir = -1 if row2 < row1 else 1  # -1 = going up (higher value)
        up = row_dir == -1
        corner_exit = "╯" if up else "╮"  # right end of segment, transitions up/down
        corner_entry = "╭" if up else "╰"  # left end of segment, arrives from prev row

        # n_segs horizontal segments, one for each grid row from row1 to row2 (inclusive)
        n_segs = n_rows + 1

        for step in range(n_segs):
            row = row1 + row_dir * step
            pivot_in = col1 + (col2 - col1) * step // n_segs
            pivot_out = col1 + (col2 - col1) * (step + 1) // n_segs

            def _p(x: int, ch: str, r: int = row) -> None:
                if 0 <= x < plot_width and 0 <= r < plot_height and grid[r][x] == " ":
                    grid[r][x] = ch

            if step == 0:
                # First row: ● at col1, draw - rightward then exit corner
                for x in range(col1 + 1, pivot_out):
                    _p(x, "-")
                _p(pivot_out, corner_exit)
            elif step == n_segs - 1:
                # Last row: entry corner then - up to col2-1 (● at col2)
                _p(pivot_in, corner_entry)
                for x in range(pivot_in + 1, col2):
                    _p(x, "-")
            else:
                # Intermediate rows: entry corner, -, exit corner
                _p(pivot_in, corner_entry)
                for x in range(pivot_in + 1, pivot_out):
                    _p(x, "-")
                _p(pivot_out, corner_exit)

    # Draw data points (overwrite any trajectory dots or line chars at data positions)
    for x, y, reps in plot_points:
        if 0 <= x < plot_width and 0 <= y < plot_height:
            grid[y][x] = "●"

    # Build output
    lines = []
    total_width = width + right_axis_width

    # Title
    lines.append(f"Max Reps Progress ({exercise_name})")
    lines.append("-" * total_width)

    # Y-axis labels and plot rows
    for i, row in enumerate(grid):
        # Calculate y value for this row
        y_val = (
            y_max - int((i / (plot_height - 1)) * y_range) if plot_height > 1 else y_max
        )

        # Left y-axis label
        label = f"{y_val:3d} ┤"

        row_str = "".join(row)

        # Add reps labels next to data points
        for x, py, reps in plot_points:
            if py == i and 0 <= x < plot_width:
                label_text = f"({reps})"
                label_pos = x + 2
                if label_pos + len(label_text) < plot_width:
                    row_list = list(row_str)
                    for j, c in enumerate(label_text):
                        if label_pos + j < len(row_list):
                            row_list[label_pos + j] = c
                    row_str = "".join(row_list)
                elif x - len(label_text) - 1 >= 0:
                    left_pos = x - len(label_text) - 1
                    row_list = list(row_str)
                    for j, c in enumerate(label_text):
                        if left_pos + j < len(row_list):
                            row_list[left_pos + j] = c
                    row_str = "".join(row_list)

        # Right axis: independent scale from m trajectory range (high → low, top → bottom)
        right_label = ""
        if show_right_axis and right_y_range > 0:
            m_val_at_row = (
                right_y_max - (i / (plot_height - 1)) * right_y_range
                if plot_height > 1
                else right_y_max
            )
            right_label = f"┤{m_val_at_row:3.0f}kg"

        lines.append(label + row_str + right_label)

    # X-axis separator
    lines.append("-" * total_width)

    # X-axis date labels
    x_labels = "    "
    mid_date = min_date + (max_date - min_date) / 2
    dates_to_show = [
        (0, min_date),
        (plot_width // 2, mid_date),
        (plot_width - 10, max_date),
    ]
    label_line = [" "] * plot_width
    for x_pos, date in dates_to_show:
        date_str = date.strftime("%b %d")
        for i, c in enumerate(date_str):
            if 0 <= x_pos + i < plot_width:
                label_line[x_pos + i] = c
    x_labels += "".join(label_line)
    lines.append(x_labels)

    # Legend
    legend_parts = ["● max reps"]
    if trajectory_z:
        legend_parts.append("· BW reps (z)")
    if trajectory_g:
        if target_weight_kg > 0:
            legend_parts.append(f"× reps @ {target_weight_kg:.1f}kg (g)")
        else:
            legend_parts.append("× BW reps (g)")
    if trajectory_m:
        legend_parts.append("○ 1RM added kg (m)")
    if show_right_axis:
        legend_parts.append("right: added kg (m)")
    if len(legend_parts) > 1:
        lines.append("   ".join(legend_parts))

    return "\n".join(lines)


def create_simple_bar_chart(
    labels: list[str],
    values: list[float],
    width: int = 40,
    title: str = "",
) -> str:
    """
    Create a simple horizontal bar chart.

    Args:
        labels: Labels for each bar
        values: Values for each bar
        width: Maximum bar width
        title: Chart title

    Returns:
        ASCII bar chart string
    """
    if not values:
        return "No data to display."

    max_val = max(values) if values else 1
    max_label_len = max(len(l) for l in labels) if labels else 0

    lines = []

    if title:
        lines.append(title)
        lines.append("-" * (max_label_len + width + 5))

    for label, value in zip(labels, values):
        bar_len = int((value / max_val) * width) if max_val > 0 else 0
        bar = "█" * bar_len
        lines.append(f"{label:>{max_label_len}} │{bar} {value:.1f}")

    return "\n".join(lines)


def create_weekly_volume_chart_from_dict(volume_data: dict) -> str:
    """
    Create a chart showing weekly training volume from pre-computed API data.

    Args:
        volume_data: Dict from api.get_volume_data() with a "weeks" list of
                     {label, total_reps} entries (oldest first).

    Returns:
        ASCII chart string
    """
    weeks_list = volume_data.get("weeks", [])
    if not weeks_list:
        return "No training history."

    labels = [w["label"] for w in weeks_list]
    values = [float(w["total_reps"]) for w in weeks_list]

    return create_simple_bar_chart(labels, values, title="Weekly Volume (Total Reps)")
