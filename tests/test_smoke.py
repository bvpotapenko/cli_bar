"""End-to-end smoke tests for the cli-bar CLI.

All tests run against an isolated tmp directory via --history-path.
The real ~/.bar-scheduler directory is never touched.
"""
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import cli_bar.app as _app_module
from cli_bar.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def reset_override():
    """Reset the data-dir override before and after every test."""
    _app_module._data_dir_override = None
    yield
    _app_module._data_dir_override = None


def cli(*args: str, data_dir: Path, input: str = ""):
    """Invoke the CLI with --history-path pointing at the isolated temp dir."""
    return runner.invoke(app, ["--history-path", str(data_dir), *args], input=input)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def profile(tmp_path):
    """Initialised profile in tmp_path, returns tmp_path."""
    result = cli("profile", "init", "--height-cm", "180", "--bodyweight-kg", "80", data_dir=tmp_path)
    assert result.exit_code == 0, result.output
    return tmp_path


@pytest.fixture
def with_pull_up(profile):
    """Profile + pull_up exercise with baseline, returns data_dir."""
    result = cli(
        "profile", "add-exercise", "pull_up",
        "--target-reps", "20", "--baseline-max", "8",
        data_dir=profile,
        input="\n",  # accept default equipment
    )
    assert result.exit_code == 0, result.output
    return profile


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInit:
    def test_creates_profile_json(self, tmp_path):
        result = cli("profile", "init", "--height-cm", "180", "--bodyweight-kg", "80", data_dir=tmp_path)
        assert result.exit_code == 0, result.output
        assert (tmp_path / "profile.json").exists()

    def test_force_overwrites(self, profile):
        result = cli(
            "profile", "init", "--height-cm", "175", "--bodyweight-kg", "75", "--force",
            data_dir=profile,
        )
        assert result.exit_code == 0, result.output

    def test_real_home_dir_untouched(self, tmp_path):
        from bar_scheduler.api.api import get_data_dir
        cli("profile", "init", "--height-cm", "180", "--bodyweight-kg", "80", data_dir=tmp_path)
        assert tmp_path != get_data_dir()
        assert (tmp_path / "profile.json").exists()


class TestAddExercise:
    def test_creates_history_file(self, profile):
        result = cli(
            "profile", "add-exercise", "pull_up",
            "--target-reps", "20", "--baseline-max", "8",
            data_dir=profile,
            input="\n",
        )
        assert result.exit_code == 0, result.output
        assert (profile / "pull_up_history.jsonl").exists()


class TestPlan:
    def test_json_output_has_sessions(self, with_pull_up):
        result = cli("plan", "--json", data_dir=with_pull_up)
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "sessions" in data
        assert len(data["sessions"]) > 0

    def test_status_json_has_training_max(self, with_pull_up):
        result = cli("status", "--json", data_dir=with_pull_up)
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "training_max" in data
        assert data["training_max"] > 0
