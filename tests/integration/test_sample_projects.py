"""Tests for the bundled sample projects.

The ``off_by_one`` sample must work from *both* the repository root and its
own directory - the tests import the module under test directly, so the
project directory has to be on ``sys.path`` in both cases.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SAMPLE = REPO_ROOT / "sample_projects" / "off_by_one"


def _failed_tests(output: str):
    """Return the names of the failed tests from a pytest output."""
    return sorted(
        line.split("::")[-1].split(" ")[0].strip()
        for line in output.splitlines()
        if line.startswith("FAILED")
    )


def _run_pytest(cwd: Path, args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args, "-q"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=180,
    )


@pytest.fixture(autouse=True)
def _require_sample():
    if not SAMPLE.is_dir():
        pytest.skip("sample_projects/off_by_one is not present")


class TestOffByOneSample:
    def test_runs_from_the_repository_root(self):
        """python -m pytest sample_projects/off_by_one/tests -v"""
        result = _run_pytest(REPO_ROOT, ["sample_projects/off_by_one/tests"])
        assert "ModuleNotFoundError" not in result.stdout, result.stdout
        assert "ImportError" not in result.stdout, result.stdout
        # The sample is *supposed* to fail: the bug is still in it.
        assert result.returncode == 1
        assert len(_failed_tests(result.stdout)) == 3

    def test_runs_from_its_own_directory(self):
        """cd sample_projects/off_by_one && python -m pytest tests -v"""
        result = _run_pytest(SAMPLE, ["tests"])
        assert "ModuleNotFoundError" not in result.stdout, result.stdout
        assert "ImportError" not in result.stdout, result.stdout
        assert result.returncode == 1
        assert len(_failed_tests(result.stdout)) == 3

    def test_both_invocations_collect_the_same_tests(self):
        from_root = _run_pytest(REPO_ROOT, ["sample_projects/off_by_one/tests"])
        from_own_dir = _run_pytest(SAMPLE, ["tests"])
        assert _failed_tests(from_root.stdout) == _failed_tests(from_own_dir.stdout)
        assert len(_failed_tests(from_root.stdout)) == 3

    def test_the_bug_is_still_present_in_the_sample(self):
        """The sample must stay broken - that is the point of the sample."""
        source = (SAMPLE / "sum_range.py").read_text(encoding="utf-8")
        assert "range(1, n)" in source
        assert "range(1, n + 1)" not in source

    def test_the_fixed_version_passes(self, tmp_path: Path):
        """The fixed source really makes the three tests pass."""
        project = tmp_path / "fixed"
        shutil.copytree(SAMPLE, project, dirs_exist_ok=True)
        for cache in project.rglob("__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)

        source = project / "sum_range.py"
        source.write_text(
            source.read_text(encoding="utf-8").replace(
                "range(1, n)", "range(1, n + 1)"
            ),
            encoding="utf-8",
        )
        result = _run_pytest(project, ["tests"])
        assert result.returncode == 0, result.stdout
        assert "passed" in result.stdout
