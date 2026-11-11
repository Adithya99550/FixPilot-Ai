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

# Source extensions FixPilot understands across the supported languages.
SOURCE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
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


def scan_project_detailed(project_path: Path, config: dict) -> dict:
    """Scan a project and return a structured inventory.

    Args:
        project_path: Root directory of the project to scan.
        config: Configuration dictionary (size limits, test command).

    Returns:
        Dict with keys: target, source_files, test_files, config_files,
        total_lines, test_command, error.
    """
    project_root = Path(project_path).resolve()

    result = {
        "target": str(project_root),
        "source_files": [],
        "test_files": [],
        "config_files": [],
        "total_lines": 0,
        "test_command": "",
        "error": None,
    }

    if not project_root.is_dir():
        result["error"] = f"'{project_path}' is not a valid directory."
        return result

    max_context_bytes = config.get("max_context_bytes", 1000000)
    max_file_bytes = config.get("max_file_bytes", 200000)

    total_lines = 0

    try:
        for entry in sorted(project_root.iterdir()):
            if is_excluded_path(entry, project_root):
                continue
            if entry.is_file():
                total_lines += _collect_file(
                    entry, project_root, result, max_file_bytes
                )
            elif entry.is_dir():
                total_lines += _walk_directory(
                    entry, project_root, result, max_context_bytes
                )
    except PermissionError:
        result["error"] = f"Permission denied scanning '{project_path}'."
        return result

    result["total_lines"] = total_lines
    result["test_command"] = _detect_test_command(project_root, config)
    return result


def _collect_file(entry: Path, project_root: Path, result: dict, max_bytes: int) -> int:
    """Classify a single file into the result buckets. Returns lines counted."""
    if _should_skip_file(entry):
        return 0

    try:
        suffix = entry.suffix.lower()
        # Always use POSIX style separators so the reported paths are
        # identical on Windows, Linux and macOS (they are also the paths
        # used inside unified diffs and repair plans).
        rel_path = entry.relative_to(project_root).as_posix()

        if suffix in SOURCE_EXTENSIONS:
            lines = _count_file_lines(entry, max_bytes)
            if lines < 0:
                return 0
            entry_info = {"path": rel_path, "lines": lines}
            if _is_test_file_path(rel_path):
                result["test_files"].append(entry_info)
            else:
                result["source_files"].append(entry_info)
            return lines

        if suffix in {".toml", ".cfg", ".ini"}:
            result["config_files"].append(rel_path)
        elif _is_python_metadata(entry):
            result["config_files"].append(rel_path)
    except (OSError, UnicodeDecodeError):
        return 0

    return 0


def _walk_directory(
    dir_path: Path,
    project_root: Path,
    result: dict,
    max_context_bytes: int,
) -> int:
    """Recursively scan a subdirectory. Returns lines counted."""
    total_lines = 0
    try:
        entries = sorted(dir_path.iterdir())
    except PermissionError:
        return 0

    for entry in entries:
        if is_excluded_path(entry, project_root):
            continue
        if entry.is_file():
            total_lines += _collect_file(
                entry, project_root, result, max_context_bytes
            )
        elif entry.is_dir():
            if not entry.name.startswith(".") or entry.name == ".git":
                total_lines += _walk_directory(
                    entry, project_root, result, max_context_bytes
                )
    return total_lines


def scan_project(project_path: Path, config: dict) -> str:
    """Scan a project and return a human readable inventory summary."""
    data = scan_project_detailed(project_path, config)

    if data["error"]:
        return f"Error: {data['error']}"

    python_files = data["source_files"] + data["test_files"]
    test_files = data["test_files"]
    source_files = data["source_files"]
    config_files = data["config_files"]
    total_lines = data["total_lines"]
    test_command = data["test_command"]

    summary = (
        f"FixPilot AI Project Scan\n"
        f"=====================\n\n"
        f"Target: {data['target']}\n\n"
        f"Source files scanned: {len(python_files)}\n"
        f"  - Source: {len(source_files)}\n"
        f"  - Test: {len(test_files)}\n\n"
    )

    if test_files:
        summary += "Test files found:\n"
        for f in test_files[:20]:
            summary += f"  - {f['path']}\n"
        summary += "\n"

    if source_files:
        summary += "Source files (first 20):\n"
        for f in source_files[:20]:
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
    """Check if a relative path is a test file (multi-language)."""
    path = Path(rel_path)
    name = path.name.lower()
    suffix = path.suffix.lower()
    parts = [p.lower() for p in path.parts]

    # Python: test_*.py / *_test.py
    if suffix == ".py":
        return name.startswith("test_") or name.endswith("_test.py")

    # JavaScript / TypeScript: *.test.js, *.spec.ts, ...
    if suffix in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}:
        stem = name[: -len(suffix)] if name.endswith(suffix) else name
        if ".test." in stem or ".spec." in stem:
            return True
        return name.startswith("test_") or name.endswith((".test.js", ".spec.js"))

    # Go: *_test.go
    if suffix == ".go":
        return name.endswith("_test.go")

    # Rust: anything under a tests/ directory
    if suffix == ".rs":
        return "tests" in parts

    # Java: *Test.java, *Tests.java, *TestCase.java, *IT.java
    if suffix == ".java":
        base = name[: -len(suffix)]
        return base.endswith(("test", "tests", "testcase", "it"))

    return False


def _count_file_lines(path: Path, max_bytes: int) -> int:
    """Count lines in a source file, respecting size limits.

    Returns -1 when the file exceeds the limit (and is therefore skipped).
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(max_bytes + 1)
            if len(content) > max_bytes:
                return -1
            return content.count("\n") + 1
    except (OSError, UnicodeDecodeError):
        return 0


def _count_python_file_lines(path: Path, max_bytes: int) -> int:
    """Count lines in a Python file, respecting size limits."""
    return _count_file_lines(path, max_bytes)


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
