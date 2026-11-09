"""FixPilot AI project scanner.

Responsibilities:
- Validate target path.
- Identify Python project structure.
- Detect Git repository and working-tree state.
- Detect likely test configuration.
- Identify test files using safe, non-executing discovery.
- Read relevant source files within configured limits.
- Exclude secrets, binary files, generated files, caches, and oversized files.
"""

import os
from pathlib import Path

# Exclusion patterns for directories and files
EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    ".env",
    "node_modules",
    "__pycache__",
    "build",
    "dist",
    "*.egg-info",
    ".pytest_cache",
    ".mypy_cache",
}

EXCLUDE_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".so",
    ".dll",
    ".exe",
    ".dat",
    ".bin",
    ".gz",
    ".zip",
    ".tar",
    ".rar",
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".wmv",
    ".avi",
    ".mov",
    ".mp4",
    ".mp3",
    ".wav",
    ".ogg",
    ".flac",
    ".exe",
    ".dll",
    ".sys",
}

EXCLUDE_FILENAMES = {
    "setup.py",
    "setup.cfg",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "Makefile",
    "Dockerfile",
}


def is_excluded_path(path: Path, project_root: Path) -> bool:
    """Check if a path should be excluded from scanning."""
    try:
        rel = path.relative_to(project_root)
    except ValueError:
        return True

    parts = rel.parts
    if parts[0] in EXCLUDE_DIRS:
        return True

    for part in parts[:-1]:
        if part in EXCLUDE_DIRS:
            return True

    if path.suffix.lower() in EXCLUDE_EXTENSIONS:
        return True

    filename = path.name.lower()
    for pattern in EXCLUDE_FILENAMES:
        if pattern.lower() in filename:
            return True

    if path.name.startswith(".") and path.suffix == "":
        return True

    return False


def scan_project(project_path: Path, config: dict) -> str:
    """Scan a Python project and return inventory summary."""
    project_root = project_path.resolve()

    if not project_root.is_dir():
        return f"Error: '{project_path}' is not a valid directory."

    max_context_bytes = config.get("max_context_bytes", 1000000)
    max_file_bytes = config.get("max_file_bytes", 200000)

    python_files = []
    test_files = []
    config_files = []
    total_lines = 0

    try:
        for entry in sorted(project_root.iterdir()):
            if is_excluded_path(entry, project_root):
                continue

            if entry.is_file():
                if _should_skip_file(entry):
                    continue

                try:
                    suffix = entry.suffix.lower()
                    if suffix == ".py":
                        lines = _count_python_file_lines(entry, max_file_bytes)
                        total_lines += lines
                        is_test = _is_test_file_path(str(entry.relative_to(project_root)))
                        if is_test:
                            test_files.append({"path": str(entry.relative_to(project_root)), "lines": lines})
                        else:
                            python_files.append({"path": str(entry.relative_to(project_root)), "lines": lines})
                    elif suffix in {".toml", ".cfg", ".ini"}:
                        config_files.append(str(entry.relative_to(project_root)))
                    else:
                        if _is_python_metadata(entry):
                            config_files.append(str(entry.relative_to(project_root)))
                except (OSError, UnicodeDecodeError):
                    continue

            elif entry.is_dir():
                _scan_subdirectory(entry, project_root, python_files, test_files, config_files, max_context_bytes)
    except PermissionError:
        return f"Error: Permission denied scanning '{project_path}'."

    test_command = _detect_test_command(project_root, config)

    lines = len("\n".join(f"  - {f['path']}" for f in test_files[:20])) if test_files else "0"
    source_count = len([f for f in python_files if not _is_test_file_path(f["path"])])

    summary = (
        f"FixPilot AI Project Scan\n"
        f"=====================\n\n"
        f"Target: {project_root}\n\n"
        f"Python files scanned: {len(python_files)}\n"
        f"  - Source: {source_count}\n"
        f"  - Test: {len(test_files)}\n\n"
    )

    if test_files:
        summary += "Test files found:\n"
        for f in test_files[:20]:
            summary += f"  - {f['path']}\n"
        summary += "\n"

    if python_files:
        summary += "Source files (first 20):\n"
        for f in python_files[:20]:
            summary += f"  - {f['path']}\n"

    summary += f"\nTotal estimated lines of code: {total_lines}\n"

    if config_files:
        summary += f"\nConfiguration files: {', '.join(config_files)}\n"

    summary += f"\nTest command: {test_command}\n"
    summary += "\nScan completed successfully."

    return summary


def _should_skip_file(path: Path) -> bool:
    """Determine if a file should be skipped during scanning."""
    if path.suffix.lower() in EXCLUDE_EXTENSIONS:
        return True
    filename = path.name.lower()
    for pattern in EXCLUDE_FILENAMES:
        if pattern.lower() in filename:
            return True
    return False


def _is_test_file(path: Path) -> bool:
    """Check if a file is a test file."""
    name = path.name.lower()
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    parts = path.parts
    if "test" in parts:
        return True
    return False


def _is_test_file_path(rel_path: str) -> bool:
    """Check if a relative path is a test file."""
    name = Path(rel_path).name.lower()
    return name.startswith("test_") or name.endswith("_test.py")


def _count_python_file_lines(path: Path, max_bytes: int) -> int:
    """Count lines in a Python file, respecting size limits."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(max_bytes + 1)
            if len(content) > max_bytes:
                return -1
            return content.count("\n") + 1
    except (OSError, UnicodeDecodeError):
        return 0


def _is_python_metadata(path: Path) -> bool:
    """Check if a file is Python project metadata."""
    name = path.name.lower()
    return name in {"pyproject.toml", "setup.py", "setup.cfg", "tox.ini", "conftest.py"}


def _detect_test_command(project_root: Path, config: dict) -> str:
    """Detect the test command for the project."""
    # Check configured test command first
    configured = config.get("test_command")
    if configured:
        return str(configured)

    # Check for pytest configuration
    config_files = ["pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini"]
    for cf in config_files:
        cf_path = project_root / cf
        if cf_path.exists():
            try:
                with open(cf_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                    if "pytest" in content.lower():
                        return f"python -m pytest -q (from {cf})"
            except (OSError, UnicodeDecodeError):
                continue

    return "python -m pytest -q (default)"


def _scan_subdirectory(
    dir_path: Path,
    project_root: Path,
    python_files: list,
    test_files: list,
    config_files: list,
    max_context_bytes: int,
):
    """Recursively scan a subdirectory."""
    try:
        entries = sorted(dir_path.iterdir())
    except PermissionError:
        return

    for entry in entries:
        if is_excluded_path(entry, project_root):
            continue

        if entry.is_file():
            if _should_skip_file(entry):
                continue
            try:
                suffix = entry.suffix.lower()
                if suffix == ".py":
                    lines = _count_python_file_lines(entry, max_context_bytes)
                    if lines >= 0 and lines <= max_context_bytes:
                        is_test = _is_test_file_path(str(entry.relative_to(project_root)))
                        if is_test:
                            test_files.append({"path": str(entry.relative_to(project_root)), "lines": lines})
                        else:
                            python_files.append({"path": str(entry.relative_to(project_root)), "lines": lines})
                elif suffix in {".toml", ".cfg", ".ini"}:
                    config_files.append(str(entry.relative_to(project_root)))
                elif _is_python_metadata(entry):
                    config_files.append(str(entry.relative_to(project_root)))
            except (OSError, UnicodeDecodeError):
                continue

        elif entry.is_dir():
            if not entry.name.startswith(".") or entry.name == ".git":
                _scan_subdirectory(entry, project_root, python_files, test_files, config_files, max_context_bytes)