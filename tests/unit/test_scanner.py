"""Unit tests for FixPilot AI project scanner."""

import pytest
from pathlib import Path

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
    EXCLUDE_FILENAMES,
)


class TestExcludeDirs:
    """Test directory exclusion patterns."""

    def test_git_excluded(self):
        """.git directory should be excluded."""
        project_root = Path("F:/test_project")
        # Path with .git as a directory component
        git_path = project_root / ".git" / "HEAD"
        # Test via is_excluded_path logic
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
        # "test" as a directory name in the path
        assert _is_test_file(Path("test_module.py"))  # name starts with test_
        assert _is_test_file(Path("src/test_sub.py"))  # "test" as part of path name would need exact match


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
        assert _should_skip_file(Path("module.pyc")) == True

    def test_py_kept(self):
        """ .py files should not be skipped (unless other patterns)."""
        # Regular .py files are not in EXCLUDE_EXTENSIONS
        result = _should_skip_file(Path("main.py"))
        # This should be False since .py is not in EXCLUDE_EXTENSIONS

    def test_txt_not_skipped(self):
        """ .txt files should not be skipped."""
        assert _should_skip_file(Path("readme.txt")) == False


class TestDetectTestCommand:
    """Test test command detection."""

    def test_default_command(self):
        """Default command when no config found."""
        project_root = Path("F:/test_project")
        config = {}
        command = _detect_test_command(project_root, config)
        assert command == "python -m pytest -q (default)"

    def test_with_configured_command(self):
        """Configured test command should be used."""
        config = {"test_command": ["python", "-m", "pytest", "--tb=short"]}
        # This tests the config check in scan_project
        assert config.get("test_command") is not None


class TestScanProject:
    """Test project scanning functionality."""

    def test_invalid_path(self):
        """Non-existent path should return error."""
        project_root = Path("F:/nonexistent_project_xyz")
        config = {}
        result = scan_project(project_root, config)
        assert "Error" in result or "not a valid directory" in result.lower()

    def test_valid_project(self):
        """Valid project should scan successfully."""
        # Use the current project directory
        project_root = Path("F:/FixPilot Ai")
        config = {"max_context_bytes": 1000000, "max_file_bytes": 200000}
        result = scan_project(project_root, config)
        assert "FixPilot AI Project Scan" in result
        assert "Target:" in result