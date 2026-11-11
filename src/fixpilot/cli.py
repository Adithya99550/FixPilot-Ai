"""FixPilot AI CLI entry point."""

import argparse
import sys
from pathlib import Path

from fixpilot.config import get_config, is_unsafe_local_execution_allowed
from fixpilot.scanner.project_scanner import scan_project
from fixpilot.sandbox.docker_executor import DockerUnavailableError
from fixpilot.storage.database import Storage
from fixpilot.workflow.engine import WorkflowEngine

# Version string (avoid circular import with fixpilot.__init__)
__version__ = "0.1.0"


def _configure_console_encoding() -> None:
    """Force UTF-8 console output.

    Windows consoles default to cp1252, which cannot encode characters such
    as the em dash or the arrow used in the CLI's own messages. Without this
    every command would abort with UnicodeEncodeError, so the streams are
    reconfigured with a lossy-but-never-crashing error handler.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main():
    """FixPilot CLI main entry."""
    _configure_console_encoding()

    parser = argparse.ArgumentParser(
        prog="fixpilot",
        description="FixPilot AI: Autonomous Software Debugging and Self-Healing Agent",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Version command
    parser_version = subparsers.add_parser("version", help="Display FixPilot version")
    parser_version.set_defaults(func=cmd_version)

    # Doctor command
    parser_doctor = subparsers.add_parser("doctor", help="Check environment and configuration")
    parser_doctor.set_defaults(func=cmd_doctor)

    # Scan command
    parser_scan = subparsers.add_parser("scan", help="Scan a project")
    parser_scan.add_argument("path", help="Path to the project to scan")
    parser_scan.set_defaults(func=cmd_scan)

    # Clone command
    parser_clone = subparsers.add_parser("clone", help="Clone a GitHub repository")
    parser_clone.add_argument("url", help="GitHub repository URL (HTTPS or SSH)")
    parser_clone.add_argument(
        "--branch",
        "-b",
        help="Branch to checkout",
    )
    parser_clone.add_argument(
        "--commit",
        "-c",
        help="Commit SHA to checkout",
    )
    parser_clone.add_argument(
        "--target",
        "-t",
        help="Target directory (default: repo name)",
    )
    parser_clone.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Overwrite the target directory if it already exists",
    )
    parser_clone.set_defaults(func=cmd_clone)

    # Run command
    parser_run = subparsers.add_parser("run", help="Run FixPilot repair workflow")
    parser_run.add_argument("path", help="Path to the project to repair (or GitHub URL)")
    parser_run.add_argument(
        "--analysis-only",
        action="store_true",
        help="Run in analysis-only mode, no patch application",
    )
    parser_run.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Auto-approve patches without interactive prompt",
    )
    # Multi-language support
    parser_run.add_argument(
        "--language",
        help="Programming language (python, javascript, typescript, go, rust, java)",
    )
    parser_run.add_argument(
        "--test-framework",
        help="Test framework (pytest, jest, go test, cargo test, junit)",
    )
    parser_run.add_argument(
        "--test-command",
        help="Test command to run (overrides auto-detection)",
    )
    parser_run.add_argument(
        "--build-command",
        help="Build command to run before tests",
    )
    parser_run.add_argument(
        "--repo-url",
        help="GitHub repository URL",
    )
    parser_run.add_argument(
        "--branch",
        help="Git branch to checkout",
    )
    parser_run.add_argument(
        "--commit",
        help="Git commit SHA to checkout",
    )
    parser_run.add_argument(
        "--allow-unsafe-local-execution",
        action="store_true",
        help=(
            "UNSAFE: allow the target project's code to run directly on this "
            "host when the Docker sandbox is unavailable. Never use this for "
            "untrusted code."
        ),
    )
    parser_run.set_defaults(func=cmd_run)

    # Audit command - static bug scan (no failing test required)
    parser_audit = subparsers.add_parser(
        "audit", help="Static bug scan of a project (does not require failing tests)"
    )
    parser_audit.add_argument("path", help="Path to the project to audit")
    parser_audit.set_defaults(func=cmd_audit)

    # Review command - code quality review
    parser_review = subparsers.add_parser(
        "review", help="Code quality and architecture review of a project"
    )
    parser_review.add_argument("path", help="Path to the project to review")
    parser_review.set_defaults(func=cmd_review)

    # History command
    parser_history = subparsers.add_parser("history", help="List run history")
    parser_history.set_defaults(func=cmd_history)

    # Show command
    parser_show = subparsers.add_parser("show", help="Show run details")
    parser_show.add_argument("run_id", help="Run ID to display")
    parser_show.set_defaults(func=cmd_show)

    # Export command
    parser_export = subparsers.add_parser("export", help="Export run report")
    parser_export.add_argument("run_id", help="Run ID to export")
    parser_export.add_argument(
        "--format",
        choices=["markdown"],
        default="markdown",
        help="Export format",
    )
    parser_export.set_defaults(func=cmd_export)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    config = get_config()
    args.func(args, config)


def cmd_version(args, config):
    """Display FixPilot version."""
    print(f"FixPilot AI version {__version__}")


def cmd_doctor(args, config):
    """Check environment and configuration."""
    print("FixPilot Doctor")
    print("=" * 40)
    print(f"Python version: {sys.version}")
    print(f"FixPilot model: {config.get('FIXPILOT_MODEL', 'gemini-1.5-flash')}")
    print(f"Log level: {config.get('FIXPILOT_LOG_LEVEL', 'INFO')}")
    print(f"Approval required: {config.get('FIXPILOT_APPROVAL_REQUIRED', True)}")
    print(f"Max retries: {config.get('FIXPILOT_MAX_RETRIES', 2)}")
    print(f"Timeout seconds: {config.get('FIXPILOT_TIMEOUT_SECONDS', 120)}")
    print(f"Database path: {config.get('FIXPILOT_DB_PATH', 'artifacts/fixpilot.sqlite3')}")

    # Docker check - verify the daemon is actually reachable, not just that
    # the CLI binary exists on PATH.
    docker_available = False
    docker_detail = "not installed"
    try:
        from fixpilot.sandbox.docker_executor import DockerExecutor

        docker_available = DockerExecutor(config)._check_docker_available()
        docker_detail = "daemon reachable" if docker_available else "installed but daemon not running"
    except Exception as e:  # pragma: no cover - defensive
        docker_detail = f"check failed: {e}"

    print(f"Docker available: {docker_available} ({docker_detail})")
    if not docker_available:
        print("  [!] Non-Python languages require Docker sandbox images.")

    # Sandbox policy - the user must be able to see exactly how the target
    # code would be executed.
    unsafe_local = is_unsafe_local_execution_allowed(config)
    print()
    print("Sandbox policy")
    print("-" * 40)
    print(f"Execution mode: {'Docker sandbox' if docker_available else ('UNSAFE local runner' if unsafe_local else 'BLOCKED (no sandbox)')}")
    print(f"Unsafe local execution allowed: {unsafe_local}")
    print(f"Network in sandbox allowed: {config.get('FIXPILOT_ALLOW_NETWORK', False)}")
    print(f"Dependency installation allowed: {config.get('FIXPILOT_ALLOW_DEPENDENCY_INSTALL', False)}")
    print(f"Patch may create files: {config.get('FIXPILOT_ALLOW_FILE_CREATION', False)}")
    print(f"Patch may delete files: {config.get('FIXPILOT_ALLOW_FILE_DELETION', False)}")
    if not docker_available and not unsafe_local:
        print("  [!] A run will be BLOCKED - the target code would have to run on this host.")
    elif not docker_available and unsafe_local:
        print("  [!] UNSAFE: the target code will run directly on this host.")

    print()
    print("Honest Limitations")
    print("-" * 40)
    print("- It cannot fix what isn't tested. No failing test -> it reports 'nothing to repair.'")
    print("- Passing tests don't guarantee correctness - the fix might be wrong even if tests pass.")
    print("- LLM diagnosis can be wrong or incomplete.")
    print("- Non-Python languages need Docker - the sandbox images (fixpilot-sandbox:go,")
    print("  :node, :rust, :java) are mandatory for Go/Rust/Java/JS.")
    print("- Human approval may be required before a patch is applied (unless --yes / auto-approve is set).")
    print()
    print("In short: FixPilot is a test-driven self-healing agent - it fixes failing tests")
    print("in Python, JavaScript, TypeScript, Go, Rust, and Java projects, but it needs")
    print("(a) a failing test to work from and (b) Docker for anything other than Python.")


def cmd_scan(args, config):
    """Scan a Python project."""
    project_path = Path(args.path)
    result = scan_project(project_path, config)
    print(result)


def cmd_audit(args, config):
    """Run a static bug scan over a project."""
    from fixpilot.agents.static_analyzer import StaticAnalyzer
    from fixpilot.llm.provider import GeminiProvider

    project_path = Path(args.path)
    if not project_path.is_dir():
        print(f"Error: '{args.path}' is not a valid directory.")
        return

    provider = None
    api_key = config.get("GEMINI_API_KEY")
    if api_key:
        try:
            provider = GeminiProvider(
                api_key=api_key,
                model=config.get("FIXPILOT_MODEL", "gemini-1.5-flash"),
            )
        except Exception:
            provider = None

    print(f"Static analysis of {project_path.resolve()}")
    result = StaticAnalyzer(provider).audit(project_path, config)

    print(f"\n{result.summary}")
    if result.findings:
        print(f"\n{'Severity':<10} {'Category':<20} {'Location':<32} Title")
        print("-" * 100)
        for finding in result.findings:
            location = f"{finding.file_path}:{finding.line_number or '?'}"
            print(
                f"{finding.severity:<10} {finding.category:<20} {location:<32} {finding.title}"
            )
    else:
        print("\nNo potential bugs found.")

    storage = Storage(config.get("FIXPILOT_DB_PATH", "artifacts/fixpilot.sqlite3"))
    audit_id = storage.save_audit(result)
    if audit_id:
        print(f"\nAudit saved: {audit_id}")


def cmd_review(args, config):
    """Run a code quality review over a project."""
    from fixpilot.agents.code_reviewer import CodeReviewer
    from fixpilot.llm.provider import GeminiProvider

    project_path = Path(args.path)
    if not project_path.is_dir():
        print(f"Error: '{args.path}' is not a valid directory.")
        return

    provider = None
    api_key = config.get("GEMINI_API_KEY")
    if api_key:
        try:
            provider = GeminiProvider(
                api_key=api_key,
                model=config.get("FIXPILOT_MODEL", "gemini-1.5-flash"),
            )
        except Exception:
            provider = None

    print(f"Code review of {project_path.resolve()}")
    result = CodeReviewer(provider).review(project_path, config)

    print(f"\n{result.summary}")
    metrics = result.metrics or {}
    if metrics:
        print(
            f"  files: {metrics.get('total_files', '?')} | "
            f"lines of code: {metrics.get('total_loc', '?')} | "
            f"issues: {metrics.get('issues_count', '?')}"
        )

    if result.issues:
        print(f"\n{'Category':<20} {'Location':<32} Message")
        print("-" * 100)
        for issue in result.issues:
            location = f"{issue.file_path}:{issue.line_number or '?'}"
            print(f"{issue.category:<20} {location:<32} {issue.message}")
    else:
        print("\nNo code quality issues found.")

    storage = Storage(config.get("FIXPILOT_DB_PATH", "artifacts/fixpilot.sqlite3"))
    review_id = storage.save_review(result)
    if review_id:
        print(f"\nReview saved: {review_id}")


def cmd_history(args, config):
    """List run history."""
    storage = Storage(config.get("FIXPILOT_DB_PATH", "artifacts/fixpilot.sqlite3"))
    runs = storage.db.list_runs(limit=25)
    print("\nFixPilot Run History")
    print("=" * 70)
    if not runs:
        print("No recorded runs found.")
        return

    print(f"{'Run ID':<20} {'Status':<12} {'Started':<22} {'Mode'}")
    print("-" * 70)
    for r in runs:
        run_id = r.get("run_id", "N/A")
        status = str(r.get("status", "N/A")).upper()
        started = str(r.get("started_at", "N/A"))[:19]
        mode = r.get("mode", "N/A")
        print(f"{run_id:<20} {status:<12} {started:<22} {mode}")
    print("=" * 70)


def cmd_show(args, config):
    """Show run details."""
    storage = Storage(config.get("FIXPILOT_DB_PATH", "artifacts/fixpilot.sqlite3"))
    run = storage.db.get_run(args.run_id)
    if not run:
        print(f"Error: Run '{args.run_id}' not found.")
        return

    print(f"\nRun Details: {args.run_id}")
    print("=" * 60)
    for k, v in run.items():
        print(f"{k:<24}: {v}")

    attempts = storage.db.get_run_attempts(args.run_id)
    print("\nAttempts:")
    print("-" * 60)
    if not attempts:
        print("No attempts recorded.")
    else:
        for att in attempts:
            num = att.get("attempt_number", 1)
            ver = att.get("verification_status", "N/A")
            test_st = att.get("test_status", "N/A")
            summary = att.get("patch_summary", "N/A")
            print(f"  Attempt {num}: Verification={ver}, Test={test_st}, Patch={summary}")
    print("=" * 60)


def cmd_export(args, config):
    """Export run report."""
    export_format = getattr(args, "format", "markdown")
    if export_format != "markdown":
        print(f"Error: unsupported export format '{export_format}'.")
        sys.exit(2)

    storage = Storage(
        config.get("FIXPILOT_DB_PATH", "artifacts/fixpilot.sqlite3"),
        reports_dir=config.get("FIXPILOT_REPORTS_DIR", "reports"),
    )
    report_path = storage.save_report(args.run_id)
    if not report_path:
        print(f"Error: Run '{args.run_id}' not found or could not generate report.")
        sys.exit(1)

    print(f"Report exported successfully to {report_path.resolve()}")
    print("\n" + report_path.read_text(encoding="utf-8"))


def cmd_clone(args, config):
    """Clone a GitHub repository."""
    from fixpilot.repository.fetcher import GitHubFetcher, CloneError

    url = args.url
    branch = args.branch
    commit = args.commit
    target = args.target

    print(f"Cloning repository: {url}")
    if branch:
        print(f"Branch: {branch}")
    if commit:
        print(f"Commit: {commit}")

    try:
        fetcher = GitHubFetcher(config.get("GITHUB_TOKEN", ""))
        repo_path = fetcher.clone(
            url,
            target=target,
            branch=branch,
            commit=commit,
            force=getattr(args, "force", False),
        )
        print(f"Repository cloned successfully to: {repo_path}")
    except CloneError as e:
        print(f"Clone failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)


def _is_github_url(path: str) -> bool:
    """Check if the path is a GitHub URL."""
    import re
    github_patterns = [
        r"^https://github\.com/[\w-]+/[\w.-]+(\.git)?/?$",
        r"^git@github\.com:[\w-]+/[\w.-]+(\.git)?$",
        r"^https://github\.com/[\w-]+/[\w.-]+/tree/[\w/-]+$",
    ]
    for pattern in github_patterns:
        if re.match(pattern, path):
            return True
    return False


def _load_fixpilot_toml(project_path: Path) -> dict:
    """Load fixpilot.toml configuration from project root."""
    import tomllib
    toml_path = project_path / "fixpilot.toml"
    if toml_path.exists():
        try:
            with open(toml_path, "rb") as f:
                return tomllib.load(f)
        except Exception as e:
            print(f"Warning: Could not parse fixpilot.toml: {e}")
    return {}


def _apply_toml_config(run_config: dict, toml_config: dict) -> dict:
    """Merge a parsed ``fixpilot.toml`` into the run configuration.

    The file uses nested tables (``[project]``, ``[agent]``, ``[sandbox]``,
    ``[storage]``, ``[reporting]``) as described in PROJECT_SPEC.md §20. The
    keys of those tables are mapped onto the flat configuration dictionary
    used by the rest of FixPilot. Values already provided on the command
    line or in the environment win over the file.
    """
    if not toml_config:
        return run_config

    # section -> configuration key names it may set
    section_map = {
        "project": {
            "language": "language",
            "test_framework": "test_framework",
            "test_command": "test_command",
            "build_command": "build_command",
            "exclude": "exclude",
            "max_file_bytes": "max_file_bytes",
            "max_context_bytes": "max_context_bytes",
        },
        "agent": {
            "max_retries": "max_retries",
            "approval_required": "FIXPILOT_APPROVAL_REQUIRED",
            "analysis_only": "FIXPILOT_ANALYSIS_ONLY",
            "max_files_changed": "max_files_changed",
            "max_changed_lines": "max_changed_lines",
        },
        "sandbox": {
            "image": "FIXPILOT_SANDBOX_IMAGE",
            "network": "network",
            "timeout_seconds": "FIXPILOT_TIMEOUT_SECONDS",
            "memory_limit": "memory_limit",
            "cpus": "cpus",
            "pids_limit": "pids_limit",
            "max_output_bytes": "max_output_bytes",
        },
        "storage": {
            "database_path": "FIXPILOT_DB_PATH",
        },
        "reporting": {
            "output_dir": "FIXPILOT_REPORTS_DIR",
            "patch_dir": "patch_dir",
            "redact_absolute_paths": "redact_absolute_paths",
        },
    }

    for section, key_map in section_map.items():
        table = toml_config.get(section)
        if not isinstance(table, dict):
            continue
        for toml_key, config_key in key_map.items():
            if toml_key not in table:
                continue
            value = table[toml_key]
            # Command line / environment values take precedence.
            if run_config.get(config_key):
                continue
            run_config[config_key] = value

    return run_config


def cmd_run(args, config):
    """Run FixPilot repair workflow."""
    project_path = Path(args.path)

    # Merge config with CLI args (CLI args take precedence)
    run_config = dict(config)
    run_config.update({
        "language": getattr(args, "language", "") or config.get("FIXPILOT_LANGUAGE", ""),
        "test_framework": getattr(args, "test_framework", "") or config.get("FIXPILOT_TEST_FRAMEWORK", ""),
        "test_command": getattr(args, "test_command", "") or config.get("FIXPILOT_TEST_COMMAND", ""),
        "build_command": getattr(args, "build_command", "") or config.get("FIXPILOT_BUILD_COMMAND", ""),
        "repo_url": getattr(args, "repo_url", "") or config.get("FIXPILOT_REPO_URL", ""),
        "branch": getattr(args, "branch", "") or config.get("FIXPILOT_BRANCH", ""),
        "commit": getattr(args, "commit", "") or config.get("FIXPILOT_COMMIT", ""),
    })

    # The unsafe local runner has to be requested explicitly, either through
    # the CLI flag or through the environment. It is never enabled by
    # default and never used as a silent fallback.
    if getattr(args, "allow_unsafe_local_execution", False):
        run_config["FIXPILOT_ALLOW_UNSAFE_LOCAL_EXECUTION"] = True
        run_config["FIXPILOT_ALLOW_LOCAL_RUNNER"] = True

    # Handle GitHub URL
    if _is_github_url(args.path):
        from fixpilot.repository.fetcher import GitHubFetcher, CloneError
        print(f"Detected GitHub URL: {args.path}")
        try:
            fetcher = GitHubFetcher(config.get("GITHUB_TOKEN", ""))
            project_path = fetcher.clone(args.path, branch=run_config.get("branch"), commit=run_config.get("commit"))
            run_config["repo_url"] = args.path
            run_config["target_path"] = str(project_path)
            print(f"Cloned to: {project_path}")
        except CloneError as e:
            print(f"Clone failed: {e}")
            return
        except Exception as e:
            print(f"Unexpected error during clone: {e}")
            return

    if not project_path.is_dir():
        print(f"Error: '{args.path}' is not a valid directory or GitHub URL.")
        return

    # Load fixpilot.toml if present
    toml_config = _load_fixpilot_toml(project_path)
    if toml_config:
        print("Loaded project config from fixpilot.toml")
        run_config = _apply_toml_config(run_config, toml_config)

    print("=" * 60)
    print(f"FixPilot AI: Initializing workflow on {project_path.resolve()}")
    if run_config.get("language"):
        print(f"Language: {run_config['language']}")
    if run_config.get("test_framework"):
        print(f"Test Framework: {run_config['test_framework']}")
    if run_config.get("test_command"):
        print(f"Test Command: {run_config['test_command']}")
    if run_config.get("build_command"):
        print(f"Build Command: {run_config['build_command']}")
    print("=" * 60)

    try:
        engine = WorkflowEngine(config=run_config)
        # The analysis-only mode can be requested on the command line, via
        # FIXPILOT_ANALYSIS_ONLY, or through [agent] analysis_only in
        # fixpilot.toml.
        analysis_only = bool(
            getattr(args, "analysis_only", False)
            or run_config.get("FIXPILOT_ANALYSIS_ONLY", False)
        )
        result = engine.execute(
            project_path=project_path,
            analysis_only=analysis_only,
            auto_approve=getattr(args, "yes", False),
        )
    except DockerUnavailableError as e:
        print("=" * 60)
        print("BLOCKED: Docker sandbox unavailable")
        print("=" * 60)
        print(str(e))
        sys.exit(2)
    except Exception as e:
        print(f"Workflow error: {e}")
        sys.exit(1)

    # Exit non-zero when the repair was not verified, so the command can be
    # used in CI. "NO_TESTS" is not a failure either - there was simply
    # nothing to repair - but it is also not a verified success.
    status = str(result.get("status", "")).upper()
    if status and status not in ("SUCCESS", "NO_TESTS"):
        sys.exit(1)