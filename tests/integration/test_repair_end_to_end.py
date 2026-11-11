"""End-to-end integration tests for the FixPilot repair workflow.

These tests run a *real* pytest suite inside a disposable workspace and
verify that:

* a correct patch is applied and the failing test starts passing
* an incorrect patch does not produce a successful run
* the original project is never modified
* the run and its attempts are persisted in the database
"""

import json
import sys
from pathlib import Path

import pytest

from fixpilot.schemas.execution import RunStatus
from fixpilot.storage.database import Storage
from fixpilot.workflow.engine import LocalExecutor, WorkflowEngine

from conftest import FakeLLMProvider


pytest_command = f"{sys.executable} -m pytest -q"

BROKEN_SOURCE = "def add(a, b):\n    return a - b\n"
FIXED_SOURCE = "def add(a, b):\n    return a + b\n"

TEST_FILE = (
    "from calculator import add\n"
    "\n"
    "\n"
    "def test_add():\n"
    "    assert add(1, 2) == 3\n"
)

INVESTIGATION_JSON = json.dumps(
    {
        "summary": "add() subtracts instead of adding",
        "root_cause_hypotheses": [
            {
                "explanation": "add() uses the wrong operator",
                "confidence": "high",
                "evidence": ["calculator.py:2"],
                "affected_files": ["calculator.py"],
            }
        ],
        "evidence": ["calculator.py:2"],
        "affected_files": ["calculator.py"],
        "missing_information": [],
        "recommended_next_action": "plan_repair",
        "confidence": "high",
        "limitations": [],
    }
)

GOOD_PATCH = (
    "--- a/calculator.py\n"
    "+++ b/calculator.py\n"
    "@@ -1,2 +1,2 @@\n"
    " def add(a, b):\n"
    "-    return a - b\n"
    "+    return a + b\n"
)

USELESS_PATCH = (
    "--- a/calculator.py\n"
    "+++ b/calculator.py\n"
    "@@ -1,2 +1,2 @@\n"
    " def add(a, b):\n"
    "-    return a - b\n"
    "+    return a - b  # still wrong\n"
)


@pytest.fixture
def broken_project(tmp_path: Path) -> Path:
    """A small project whose test really fails."""
    project = tmp_path / "broken_project"
    (project / "tests").mkdir(parents=True)
    (project / "calculator.py").write_text(BROKEN_SOURCE, encoding="utf-8")
    (project / "tests" / "test_calculator.py").write_text(TEST_FILE, encoding="utf-8")
    return project


def _engine(tmp_path: Path, llm):
    config = {
        "FIXPILOT_DB_PATH": str(tmp_path / "fixpilot.sqlite3"),
        "FIXPILOT_REPORTS_DIR": str(tmp_path / "reports"),
        "language": "python",
        "test_framework": "pytest",
        "test_command": pytest_command,
        "FIXPILOT_APPROVAL_REQUIRED": False,
        "FIXPILOT_MAX_RETRIES": 2,
        "FIXPILOT_TIMEOUT_SECONDS": 120,
    }
    storage = Storage(config["FIXPILOT_DB_PATH"], reports_dir=config["FIXPILOT_REPORTS_DIR"])
    engine = WorkflowEngine(
        config=config,
        storage=storage,
        llm_provider=llm,
        executor=LocalExecutor(config),
    )
    return engine, storage


class TestEndToEndRepair:
    def test_successful_repair(self, broken_project, tmp_path):
        """A correct patch turns the failing test into a passing test."""
        llm = FakeLLMProvider([INVESTIGATION_JSON, GOOD_PATCH])
        engine, storage = _engine(tmp_path, llm)
        result = engine.execute(broken_project, auto_approve=True)

        assert result["status"] == RunStatus.SUCCESS, result.get("reason")
        assert result["attempts"] == 1
        assert result["test_exit_code"] == 0

        run = storage.get_run(result["run_id"])
        assert run["status"] == "SUCCESS"
        assert run["final_test_status"] == "PASS"

        attempts = storage.get_run_attempts(result["run_id"])
        assert len(attempts) == 1
        assert attempts[0]["test_status"] == "PASS"
        assert attempts[0]["verification_status"] == "SUCCESS"

        # A report was written.
        assert result["report_path"]
        report = Path(result["report_path"]).read_text(encoding="utf-8")
        assert result["run_id"] in report
        assert "SUCCESS" in report

    def test_original_project_is_untouched(self, broken_project, tmp_path):
        llm = FakeLLMProvider([INVESTIGATION_JSON, GOOD_PATCH])
        engine, _ = _engine(tmp_path, llm)
        engine.execute(broken_project, auto_approve=True)
        assert (broken_project / "calculator.py").read_text(encoding="utf-8") == (
            BROKEN_SOURCE
        )

    def test_failed_repair(self, broken_project, tmp_path):
        """A patch that does not fix the bug must not report success."""
        llm = FakeLLMProvider([INVESTIGATION_JSON, USELESS_PATCH])
        engine, storage = _engine(tmp_path, llm)
        result = engine.execute(broken_project, auto_approve=True)

        assert result["status"] != RunStatus.SUCCESS
        assert result["status"] == RunStatus.FAILED
        assert result["test_exit_code"] != 0

        run = storage.get_run(result["run_id"])
        assert run["status"] == "FAILED"
        assert run["final_test_status"] == "FAIL"

    def test_missing_llm_fails_the_run(self, broken_project, tmp_path):
        """Without an LLM no patch can be generated - and nothing is faked."""
        llm = FakeLLMProvider([INVESTIGATION_JSON])
        engine, storage = _engine(tmp_path, llm)
        result = engine.execute(broken_project, auto_approve=True)

        assert result["status"] == RunStatus.REPAIR_FAILED
        assert storage.get_run(result["run_id"])["status"] == "REPAIR_FAILED"

    def test_analysis_only_mode(self, broken_project, tmp_path):
        llm = FakeLLMProvider([INVESTIGATION_JSON])
        engine, storage = _engine(tmp_path, llm)
        result = engine.execute(broken_project, analysis_only=True)
        assert result["status"] == RunStatus.SUCCESS
        assert "investigation" in result
        assert result["investigation"].root_cause_hypotheses

    def test_project_without_failures(self, tmp_path):
        """A project whose tests pass is reported as 'nothing to repair'."""
        project = tmp_path / "healthy_project"
        (project / "tests").mkdir(parents=True)
        (project / "calculator.py").write_text(FIXED_SOURCE, encoding="utf-8")
        (project / "tests" / "test_calculator.py").write_text(TEST_FILE, encoding="utf-8")

        llm = FakeLLMProvider()
        engine, storage = _engine(tmp_path, llm)
        result = engine.execute(project, auto_approve=True)
        assert result["status"] == RunStatus.SUCCESS
        assert result.get("message") == "All tests pass"
        # No patch was generated at all.
        assert storage.get_run_attempts(result["run_id"]) == []
