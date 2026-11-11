"""FixPilot AI configuration management.

All security relevant switches default to the *safe* value. In particular:

- ``FIXPILOT_ALLOW_UNSAFE_LOCAL_EXECUTION`` defaults to ``False`` so target
  project code is never executed on the host unless a user explicitly opts in.
- ``FIXPILOT_ALLOW_NETWORK`` defaults to ``False`` so sandboxed test runs are
  always network isolated.
- ``FIXPILOT_ALLOW_FILE_CREATION`` / ``FIXPILOT_ALLOW_FILE_DELETION`` default
  to ``False`` so a patch can only modify files that already exist.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)


def _env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean flag from the environment.

    Only the literal values ``true``/``1``/``yes``/``on`` (case insensitive)
    enable the flag; everything else - including an empty string - keeps the
    safe default.
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        # An unset *or* blank variable keeps the documented default. This
        # matters for fail-safe defaults such as the approval gate: a blank
        # "FIXPILOT_APPROVAL_REQUIRED=" must not silently disable it.
        return default
    return raw.strip().lower() in ("true", "1", "yes", "on")


def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable, falling back on bad input.

    A malformed value must not crash the CLI with a traceback.
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        import warnings

        warnings.warn(
            f"{name}={raw!r} is not a valid integer; using {default} instead.",
            stacklevel=2,
        )
        return default


def get_config() -> dict:
    """Get configuration as dictionary."""
    return {
        "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY", ""),
        "FIXPILOT_MODEL": os.getenv("FIXPILOT_MODEL", "gemini-1.5-flash"),
        "FIXPILOT_LOG_LEVEL": os.getenv("FIXPILOT_LOG_LEVEL", "INFO"),
        "FIXPILOT_DB_PATH": os.getenv("FIXPILOT_DB_PATH", "artifacts/fixpilot.sqlite3"),
        "FIXPILOT_SANDBOX_IMAGE": os.getenv("FIXPILOT_SANDBOX_IMAGE", "fixpilot-sandbox:latest"),
        "FIXPILOT_MAX_RETRIES": _env_int("FIXPILOT_MAX_RETRIES", 2),
        "FIXPILOT_TIMEOUT_SECONDS": _env_int("FIXPILOT_TIMEOUT_SECONDS", 120),
        "FIXPILOT_APPROVAL_REQUIRED": _env_bool("FIXPILOT_APPROVAL_REQUIRED", True),
        "FIXPILOT_ANALYSIS_ONLY": _env_bool("FIXPILOT_ANALYSIS_ONLY", False),
        # PROJECT_SPEC.md §9.3: a sandbox failure must be BLOCKED, never a
        # silent fallback to executing target code on the host. Opt in
        # explicitly (and knowingly) if you want the local runner.
        "FIXPILOT_ALLOW_UNSAFE_LOCAL_EXECUTION": _env_bool(
            "FIXPILOT_ALLOW_UNSAFE_LOCAL_EXECUTION", False
        ),
        # Backwards compatible alias for the previous option name. It means
        # exactly the same thing: allow the target project's code to run
        # directly on this host machine.
        "FIXPILOT_ALLOW_LOCAL_RUNNER": _env_bool("FIXPILOT_ALLOW_LOCAL_RUNNER", False),
        # Network access for sandboxed runs is opt-in and off by default.
        "FIXPILOT_ALLOW_NETWORK": _env_bool("FIXPILOT_ALLOW_NETWORK", False),
        # Dependency installation is a separate, explicitly enabled phase.
        "FIXPILOT_ALLOW_DEPENDENCY_INSTALL": _env_bool(
            "FIXPILOT_ALLOW_DEPENDENCY_INSTALL", False
        ),
        "FIXPILOT_DEPENDENCY_INSTALL_NETWORK": _env_bool(
            "FIXPILOT_DEPENDENCY_INSTALL_NETWORK", False
        ),
        # Patch scope: by default a patch may only modify existing files.
        "FIXPILOT_ALLOW_FILE_CREATION": _env_bool("FIXPILOT_ALLOW_FILE_CREATION", False),
        "FIXPILOT_ALLOW_FILE_DELETION": _env_bool("FIXPILOT_ALLOW_FILE_DELETION", False),
        # Keep the disposable workspace after a run (useful for debugging).
        "FIXPILOT_KEEP_WORKSPACE": _env_bool("FIXPILOT_KEEP_WORKSPACE", False),
        "FIXPILOT_REPORTS_DIR": os.getenv("FIXPILOT_REPORTS_DIR", "reports"),
        "PROJECT_ROOT": str(PROJECT_ROOT),
        # Multi-language support
        "FIXPILOT_LANGUAGE": os.getenv("FIXPILOT_LANGUAGE", ""),
        "FIXPILOT_TEST_FRAMEWORK": os.getenv("FIXPILOT_TEST_FRAMEWORK", ""),
        "FIXPILOT_TEST_COMMAND": os.getenv("FIXPILOT_TEST_COMMAND", ""),
        "FIXPILOT_BUILD_COMMAND": os.getenv("FIXPILOT_BUILD_COMMAND", ""),
        "FIXPILOT_REPO_URL": os.getenv("FIXPILOT_REPO_URL", ""),
        "FIXPILOT_BRANCH": os.getenv("FIXPILOT_BRANCH", ""),
        "FIXPILOT_COMMIT": os.getenv("FIXPILOT_COMMIT", ""),
        "GITHUB_TOKEN": os.getenv("GITHUB_TOKEN", ""),
    }


def is_unsafe_local_execution_allowed(config: dict) -> bool:
    """Return True when the user explicitly allowed running target code locally.

    Both the explicit ``FIXPILOT_ALLOW_UNSAFE_LOCAL_EXECUTION`` flag and the
    legacy ``FIXPILOT_ALLOW_LOCAL_RUNNER`` alias are honoured. Anything else
    (missing config, ``None`` values, non-dict input) keeps execution blocked.
    """
    if not config:
        return False
    return bool(
        config.get("FIXPILOT_ALLOW_UNSAFE_LOCAL_EXECUTION", False)
        or config.get("FIXPILOT_ALLOW_LOCAL_RUNNER", False)
    )
