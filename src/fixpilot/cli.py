"""FixPilot AI CLI entry point."""

import argparse
import sys
from pathlib import Path

from fixpilot.config import get_config
from fixpilot.scanner.project_scanner import scan_project
from fixpilot.sandbox.docker_executor import DockerExecutor, DockerUnavailableError
from fixpilot.storage.database import Storage
from fixpilot.workflow.engine import WorkflowEngine

# Version string (avoid circular import with fixpilot.__init__)
__version__ = "0.1.0"


def main():
    """FixPilot CLI main entry."""
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
    parser_run.set_defaults(func=cmd_run)

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


def cmd_scan(args, config):
    """Scan a Python project."""
    project_path = Path(args.path)
    result = scan_project(project_path, config)
    print(result)


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
    storage = Storage(
        config.get("FIXPILOT_DB_PATH", "artifacts/fixpilot.sqlite3"),
        reports_dir=config.get("FIXPILOT_REPORTS_DIR", "reports"),
    )
    report_path = storage.save_report(args.run_id)
    if not report_path:
        print(f"Error: Run '{args.run_id}' not found or could not generate report.")
        return

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
        repo_path = fetcher.clone(url, target=target, branch=branch, commit=commit)
        print(f"Repository cloned successfully to: {repo_path}")
    except CloneError as e:
        print(f"Clone failed: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")


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
        print(f"Loaded project config from fixpilot.toml")
        # CLI args take precedence over toml
        for key, value in toml_config.items():
            if key not in run_config or not run_config[key]:
                run_config[key] = value

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
        result = engine.execute(
            project_path=project_path,
            analysis_only=args.analysis_only,
            auto_approve=getattr(args, "yes", False),
        )
    except DockerUnavailableError as e:
        print("=" * 60)
        print("BLOCKED: Docker sandbox unavailable")
        print("=" * 60)
        print(str(e))
    except Exception as e:
        print(f"Workflow error: {e}")