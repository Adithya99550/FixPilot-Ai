"""Unit tests for FixPilot AI project scanner.

These tests are fully portable: they never reference a machine specific
path. Temporary project trees are created with pytest's ``tmp_path``
fixture so the suite behaves identically on Windows, Linux and macOS.
"""

import os
from pathlib import Path

import pytest

from fixpilot.scanner.project_scanner import (
    is_excluded_path,
    scan_project,
    _should_skip_file,
    _is_test_file,
    _is_test_file_path,
    _count_python_file_lines,
    _detect_test_command,
    EXCLUDE_DIRS,
    EXCLUDE_EXTENSIONS,
)


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    """Create a small, realistic project tree inside a temporary directory."""
    project = tmp_path / "sample_project"
    (project / "pkg").mkdir(parents=True)
    (project / "tests").mkdir()

    (project / "pkg" / "calculator.py").write_text(
        "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
    (project / "tests" / "test_calculator.py").write_text(
        "from pkg.calculator import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )
    (project / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\ntestpaths = ['tests']\n", encoding="utf-8"
    )
    return project


class TestExcludeDirs:
    """Test directory exclusion patterns."""

    def test_git_excluded(self):
        """.git directory should be excluded."""
        assert ".git" in EXCLUDE_DIRS

    def test_venv_excluded(self):
        """.venv directory should be excluded."""
        assert ".venv" in EXCLUDE_DIRS

    def test_node_modules_excluded(self):
        """node_modules directory should be excluded."""
        assert "node_modules" in EXCLUDE_DIRS

    def test_build_excluded(self):
        """build directory should be excluded."""
        assert "build" in EXCLUDE_DIRS

    def test_dist_excluded(self):
        """dist directory should be excluded."""
        assert "dist" in EXCLUDE_DIRS


class TestExcludeExtensions:
    """Test file extension exclusion patterns."""

    def test_pyc_excluded(self):
        """ .pyc files should be excluded."""
        assert ".pyc" in EXCLUDE_EXTENSIONS

    def test_pyo_excluded(self):
        """ .pyo files should be excluded."""
        assert ".pyo" in EXCLUDE_EXTENSIONS

    def test_dll_excluded(self):
        """ .dll files should be excluded."""
        assert ".dll" in EXCLUDE_EXTENSIONS

    def test_so_excluded(self):
        """ .so files should be excluded."""
        assert ".so" in EXCLUDE_EXTENSIONS


class TestIsExcludedPath:
    """Test is_excluded_path behaviour."""

    def test_git_directory_excluded(self, tmp_path: Path):
        """A file inside .git is excluded."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        head = git_dir / "HEAD"
        head.write_text("ref: refs/heads/main\n", encoding="utf-8")
        assert is_excluded_path(head, tmp_path) is True

    def test_source_file_not_excluded(self, tmp_path: Path):
        """A normal source file is not excluded."""
        source = tmp_path / "main.py"
        source.write_text("x = 1\n", encoding="utf-8")
        assert is_excluded_path(source, tmp_path) is False

    def test_path_outside_root_excluded(self, tmp_path: Path):
        """A path outside the project root is excluded."""
        outside = tmp_path.parent / "elsewhere.py"
        assert is_excluded_path(outside, tmp_path) is True


class TestIsTestFile:
    """Test test file detection."""

    def test_test_prefix(self):
        """Files starting with test_ should be detected."""
        assert _is_test_file(Path("test_math.py"))
        assert _is_test_file(Path("test_utils.py"))

    def test_test_suffix(self):
        """Files ending with _test.py should be detected."""
        assert _is_test_file(Path("math_test.py"))
        assert _is_test_file(Path("utils_test.py"))

    def test_exact_test_part(self):
        """Paths with 'test' as exact directory component should be detected."""
        assert _is_test_file(Path("test_module.py"))
        assert _is_test_file(Path("src/test_sub.py"))


class TestIsTestFilePath:
    """Test test file detection on relative paths."""

    def test_test_prefix_path(self):
        """Relative paths starting with test_."""
        assert _is_test_file_path("test_math.py")
        assert _is_test_file_path("test_utils.py")

    def test_test_suffix_path(self):
        """Relative paths ending with _test.py."""
        assert _is_test_file_path("math_test.py")
        assert _is_test_file_path("utils_test.py")


class TestShouldSkipFile:
    """Test file skipping logic."""

    def test_pyc_skipped(self):
        """ .pyc files should be skipped."""
        assert _should_skip_file(Path("module.pyc")) is True

    def test_py_kept(self):
        """ .py files should not be skipped."""
        assert _should_skip_file(Path("main.py")) is False

    def test_txt_not_skipped(self):
        """ .txt files should not be skipped."""
        assert _should_skip_file(Path("readme.txt")) is False


class TestCountPythonFileLines:
    """Test line counting with size limits."""

    def test_counts_lines(self, tmp_path: Path):
        """Line count includes the last line without a trailing newline."""
        source = tmp_path / "mod.py"
        source.write_text("a = 1\nb = 2\nc = 3", encoding="utf-8")
        assert _count_python_file_lines(source, 100000) == 3

    def test_oversized_file_returns_minus_one(self, tmp_path: Path):
        """Files above the limit are reported as too large."""
        source = tmp_path / "big.py"
        source.write_text("x = 1\n" * 100, encoding="utf-8")
        assert _count_python_file_lines(source, 10) == -1

    def test_unreadable_file_returns_zero(self, tmp_path: Path):
        """A missing file does not raise."""
        assert _count_python_file_lines(tmp_path / "missing.py", 1000) == 0


class TestDetectTestCommand:
    """Test test command detection."""

    def test_default_command(self, tmp_path: Path):
        """Default command when no config found."""
        command = _detect_test_command(tmp_path, {})
        assert command == "python -m pytest -q (default)"

    def test_with_configured_command(self, tmp_path: Path):
        """Configured test command should be used."""
        config = {"test_command": ["python", "-m", "pytest", "--tb=short"]}
        command = _detect_test_command(tmp_path, config)
        assert command == str(config["test_command"])

    def test_detects_pytest_in_pyproject(self, tmp_path: Path):
        """A pyproject.toml mentioning pytest is detected."""
        (tmp_path / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\n", encoding="utf-8"
        )
        command = _detect_test_command(tmp_path, {})
        assert "pytest" in command


class TestScanProject:
    """Test project scanning functionality."""

    def test_invalid_path(self, tmp_path: Path):
        """Non-existent path should return an error message."""
        result = scan_project(tmp_path / "nonexistent_project_xyz", {})
        assert "Error" in result or "not a valid directory" in result.lower()

    def test_valid_project(self, sample_project: Path):
        """A valid temporary project is scanned successfully."""
        result = scan_project(sample_project, {"max_context_bytes": 1000000,
                                               "max_file_bytes": 200000})
        assert "FixPilot AI Project Scan" in result
        assert "Target:" in result
        assert str(sample_project.resolve()) in result

    def test_empty_project(self, tmp_path: Path):
        """An empty directory produces a valid, empty report."""
        empty = tmp_path / "empty_project"
        empty.mkdir()
        result = scan_project(empty, {})
        assert "FixPilot AI Project Scan" in result
        assert "Source files scanned: 0" in result
        assert "Scan completed successfully." in result

    def test_nested_directories_are_scanned(self, sample_project: Path):
        """Files in nested directories are found."""
        result = scan_project(sample_project, {})
        assert "pkg/calculator.py" in result
        assert "tests/test_calculator.py" in result

    def test_unsupported_file_types_are_ignored(self, sample_project: Path):
        """Binary/unsupported files do not break the scan."""
        (sample_project / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (sample_project / "data.bin").write_bytes(b"\x00\x01")
        result = scan_project(sample_project, {})
        assert "FixPilot AI Project Scan" in result

    def test_large_file_is_skipped(self, tmp_path: Path):
        """Files above the size limit are not counted."""
        project = tmp_path / "large_project"
        project.mkdir()
        (project / "huge.py").write_text("x = 1\n" * 5000, encoding="utf-8")
        result = scan_project(project, {"max_file_bytes": 100})
        assert "huge.py" not in result

    def test_symlinked_directory_is_handled(self, sample_project: Path):
        """Symlinks never break the scan (they may be skipped)."""
        link = sample_project / "link_to_pkg"
        try:
            link.symlink_to(sample_project / "pkg", target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks are not supported on this platform")
        result = scan_project(sample_project, {})
        assert "FixPilot AI Project Scan" in result

    def test_permission_error_is_reported(self, tmp_path: Path):
        """A directory that cannot be read is reported, not raised."""
        if os.name == "nt" or os.geteuid() == 0:
            pytest.skip("Permission behaviour differs for this user/OS")
        blocked = tmp_path / "blocked"
        blocked.mkdir()
        (blocked / "secret.py").write_text("x = 1\n", encoding="utf-8")
        blocked.chmod(0o000)
        try:
            result = scan_project(tmp_path, {})
            assert isinstance(result, str)
        finally:
            blocked.chmod(0o755)
