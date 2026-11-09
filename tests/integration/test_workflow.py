"""Integration tests for FixPilot AI workflow engine and CLI."""

import tempfile
import shutil
from pathlib import Path
import pytest

from fixpilot.workflow.engine import WorkflowEngine, LocalExecutor
from fixpilot.storage.database import Storage
from fixpilot.reporting.markdown_report import generate_markdown_report


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace for integration tests."""
    temp_dir = tempfile.mkdtemp(prefix="fixpilot_test_ws_")
    ws = Path(temp_dir)
    yield ws
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_workflow_no_failure(temp_workspace):
    """Test running workflow on a project where all tests pass."""
    sample_src = Path("sample_projects/no_failure").resolve()
    shutil.copytree(sample_src, temp_workspace, dirs_exist_ok=True)

    db_path = str(temp_workspace / "test.sqlite3")
    storage = Storage(db_path)
    engine = WorkflowEngine(config={"FIXPILOT_DB_PATH": db_path}, storage=storage, executor=LocalExecutor())

    result = engine.execute(temp_workspace, auto_approve=True)
    assert result["status"] == "SUCCESS"

    runs = storage.db.list_runs()
    assert len(runs) >= 1
    assert runs[0]["status"] == "SUCCESS"


def test_workflow_analysis_only(temp_workspace):
    """Test running workflow in analysis-only mode on a project with failures."""
    sample_src = Path("sample_projects/off_by_one").resolve()
    shutil.copytree(sample_src, temp_workspace, dirs_exist_ok=True)

    db_path = str(temp_workspace / "test.sqlite3")
    storage = Storage(db_path)
    engine = WorkflowEngine(config={"FIXPILOT_DB_PATH": db_path}, storage=storage, executor=LocalExecutor())

    result = engine.execute(temp_workspace, analysis_only=True, auto_approve=True)
    assert result["status"] == "SUCCESS"
    assert "investigation" in result
    assert len(result["investigation"].root_cause_hypotheses) > 0


def test_report_generation():
    """Test markdown report generation."""
    run_data = {
        "run_id": "test_run_123",
        "status": "SUCCESS",
        "target_display_path": "/path/to/project",
        "started_at": "2026-11-09T00:00:00Z",
        "finished_at": "2026-11-09T00:01:00Z",
    }
    attempts = [
        {
            "attempt_number": 1,
            "verification_status": "SUCCESS",
            "test_status": "PASS",
            "approval_status": "APPROVED",
            "root_cause_summary": "Off by one error in loop",
            "patch_summary": "Fixed range limit",
        }
    ]
    report = generate_markdown_report(run_data, attempts)
    assert "FixPilot AI Repair Report" in report
    assert "test_run_123" in report
    assert "SUCCESS" in report
    assert "Off by one error in loop" in report

