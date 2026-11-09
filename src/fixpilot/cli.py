"""FixPilot AI CLI entry point."""

import argparse
import sys
from pathlib import Path

from fixpilot.config import get_config
from fixpilot.scanner.project_scanner import scan_project
from fixpilot.sandbox.docker_executor import DockerExecutor, DockerUnavailableError

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
    parser_scan = subparsers.add_parser("scan", help="Scan a Python project")
    parser_scan.add_argument("path", help="Path to the Python project to scan")
    parser_scan.set_defaults(func=cmd_scan)

    # Run command
    parser_run = subparsers.add_parser("run", help="Run FixPilot repair workflow")
    parser_run.add_argument("path", help="Path to the Python project to repair")
    parser_run.add_argument(
        "--analysis-only",
        action="store_true",
        help="Run in analysis-only mode, no patch application",
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
    print("Run history")
    # TODO: Implement history display


def cmd_show(args, config):
    """Show run details."""
    print(f"Showing run: {args.run_id}")
    # TODO: Implement show detail


def cmd_export(args, config):
    """Export run report."""
    print(f"Exporting run: {args.run_id} as {args.format}")
    # TODO: Implement export


def cmd_run(args, config):
    """Run FixPilot repair workflow."""
    project_path = Path(args.path)

    if not project_path.is_dir():
        print(f"Error: '{args.path}' is not a valid directory.")
        return

    if args.analysis_only:
        print(f"Analysis-only mode for: {args.path}")
        # TODO: Implement analysis-only workflow
        return

    # Initialize Docker executor
    executor = DockerExecutor(config)

    # Check if Docker is available - if not, BLOCKED per spec
    try:
        if not executor._check_docker_available():
            print("=" * 60)
            print("BLOCKED: Docker sandbox unavailable")
            print("=" * 60)
            print(
                "FixPilot requires Docker for sandboxed execution of target code."
            )
            print(
                "Without Docker, target projects cannot be run in isolation,"
            )
            print(
                "and repairs cannot be verified safely. Please install Docker "
                "or configure a suitable sandbox environment."
            )
            print(
                "Refer to the documentation for Docker setup instructions."
            )
            return
    except DockerUnavailableError as e:
        print("=" * 60)
        print("BLOCKED: Docker sandbox unavailable")
        print("=" * 60)
        print(str(e))
        return

    print(f"Running FixPilot on: {args.path}")
    print("=" * 60)
    print("Initializing repair workflow...")
    print("=" * 60)

    # Step 1: Scan project
    print("\n[1/5] Scanning project...")
    scan_result = scan_project(project_path, config)
    print(scan_result)

    # Step 2: Run baseline tests
    print("\n[2/5] Running baseline tests...")
    test_command = config.get("test_command", ["python", "-m", "pytest", "-q"])
    try:
        exec_result = executor.run_tests(
            test_command=test_command,
            workspace_path=project_path,
        )
        print(f"Baseline exit code: {exec_result.exit_code}")
        print(f"Duration: {exec_result.duration:.2f}s")
        if exec_result.timed_out:
            print("WARNING: Baseline tests timed out.")
        elif exec_result.exit_code != 0:
            print(f"Baseline tests failed (exit code: {exec_result.exit_code})")
            print("Stderr preview:")
            print(exec_result.stderr[:500] if exec_result.stderr else "(no stderr)")
        else:
            print("Baseline tests passed - no failing tests detected.")
    except DockerUnavailableError:
        print("BLOCKED: Docker unavailable for test execution.")
        return
    except Exception as e:
        print(f"Error running baseline tests: {e}")
        return

    # TODO: Continue workflow - investigator, planner, repairer, approval, etc.
    print("\n[3/5] Investigation phase - TODO")
    print("[4/5] Planning phase - TODO")
    print("[5/5] Repair phase - TODO")

    print("\nWorkflow incomplete - core stages not yet implemented.")
    print("Use --analysis-only for investigation without patch application.")