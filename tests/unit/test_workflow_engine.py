"""Tests for the FixPilot workflow engine.

Acceptance criteria of the "fix stale repair context and retry loop" and
"fix workflow status and result handling" tasks:

* attempt 2 receives updated files and diagnostics from attempt 1
* attempt 3 receives the latest state from attempt 2
* identical patches are not applied twice
* the retry limit is respected
* a successful verification terminates the repair attempts immediately
* the final status always reflects the real outcome
"""

import json
from pathlib import Path

import pytest

from fixpilot.schemas.execution import ExecutionResult, RunStatus
from fixpilot.storage.database import Storage
from fixpilot.workflow.engine import WorkflowEngine

from conftest import FakeLLMProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAILING_OUTPUT = (
    "=================================== FAILURES ===================================\n"
    "_______________________________ test_add ______________________________\n"
    "tests/test_calculator.py:9: in test_add\n"
    "    assert add(1, 2) == 3\n"
    "E       assert -1 == 3\n"
    "=========================== short test summary info ============================\n"
    "FAILED tests/test_calculator.py::test_add - assert -1 == 3\n"
)

PARTIAL_OUTPUT = (
    "=========================== short test summary info ============================\n"
    "FAILED tests/test_calculator.py::test_add - assert -1 == 3\n"
    "FAILED tests/test_calculator.py::test_sub - assert 5 == 1\n"
)

PASSING_OUTPUT = "============================= 2 passed in 0.01s ==============================\n"

INVESTIGATION_JSON = json.dumps(
    {
        "summary": "add() uses the wrong operator",
        "root_cause_hypotheses": [
            {
                "explanation": "add() subtracts instead of adding",
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
    "+    return a - b  # unchanged behaviour\n"
)

SECOND_PATCH = (
    "--- a/calculator.py\n"
    "+++ b/calculator.py\n"
    "@@ -1,2 +1,2 @@\n"
    " def add(a, b):\n"
    "-    return a + b\n"
    "+    return a + b  # repaired in attempt 2\n"
)

TRAVERSAL_PATCH = (
    "--- a/../outside.py\n"
    "+++ b/../outside.py\n"
    "@@ -1,1 +1,1 @@\n"
    "-old\n"
    "+new\n"
)


class ScriptedExecutor:
    """An executor that returns a scripted list of results."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []
        self.workspace_snapshots = []

    def run_tests(self, test_command, workspace_path, language=None, build_command=None):
        index = min(len(self.calls), len(self.results) - 1)
        self.calls.append(list(test_command))
        try:
            self.workspace_snapshots.append(
                (workspace_path / "calculator.py").read_text(encoding="utf-8")
            )
        except OSError:
            self.workspace_snapshots.append("")
        return self.results[index]


def _result(exit_code=1, stdout=FAILING_OUTPUT, stderr="", timed_out=False):
    return ExecutionResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        duration=0.1,
        sandbox_id="scripted",
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A tiny project with a real (buggy) source file."""
    root = tmp_path / "project"
    (root / "tests").mkdir(parents=True)
    (root / "calculator.py").write_text(
        "def add(a, b):\n    return a - b\n", encoding="utf-8"
    )
    (root / "tests" / "test_calculator.py").write_text(
        "from calculator import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )
    return root


def _engine(tmp_path: Path, executor, llm, **extra_config):
    config = {
        "FIXPILOT_DB_PATH": str(tmp_path / "fixpilot.sqlite3"),
        "FIXPILOT_REPORTS_DIR": str(tmp_path / "reports"),
        "language": "python",
        "test_framework": "pytest",
        "test_command": "python -m pytest -q",
        "FIXPILOT_APPROVAL_REQUIRED": False,
        "FIXPILOT_MAX_RETRIES": 2,
    }
    config.update(extra_config)
    storage = Storage(config["FIXPILOT_DB_PATH"], reports_dir=config["FIXPILOT_REPORTS_DIR"])
    engine = WorkflowEngine(config=config, storage=storage, llm_provider=llm, executor=executor)
    return engine, storage


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSuccessfulRun:
    def test_baseline_pass_is_success(self, project, tmp_path):
        executor = ScriptedExecutor([_result(exit_code=0, stdout=PASSING_OUTPUT)])
        engine, storage = _engine(tmp_path, executor, FakeLLMProvider())
        result = engine.execute(project, auto_approve=True)
        assert result["status"] == RunStatus.SUCCESS
        assert storage.get_run(result["run_id"])["status"] == "SUCCESS"

    def test_repair_is_verified_as_success(self, project, tmp_path):
        executor = ScriptedExecutor(
            [_result(exit_code=1), _result(exit_code=0, stdout=PASSING_OUTPUT)]
        )
        llm = FakeLLMProvider([INVESTIGATION_JSON, GOOD_PATCH])
        engine, storage = _engine(tmp_path, executor, llm)
        result = engine.execute(project, auto_approve=True)
        assert result["status"] == RunStatus.SUCCESS
        assert result["attempts"] == 1

        run = storage.get_run(result["run_id"])
        assert run["final_test_status"] == "PASS"
        assert run["final_test_exit_code"] == 0
        assert run["attempt_count"] == 1
        assert run["baseline_exit_code"] == 1

        attempts = storage.get_run_attempts(result["run_id"])
        assert len(attempts) == 1
        assert attempts[0]["test_status"] == "PASS"
        assert attempts[0]["verification_status"] == "SUCCESS"

    def test_original_repository_is_never_modified(self, project, tmp_path):
        executor = ScriptedExecutor(
            [_result(exit_code=1), _result(exit_code=0, stdout=PASSING_OUTPUT)]
        )
        llm = FakeLLMProvider([INVESTIGATION_JSON, GOOD_PATCH])
        engine, _ = _engine(tmp_path, executor, llm)
        engine.execute(project, auto_approve=True)
        assert (project / "calculator.py").read_text(encoding="utf-8") == (
            "def add(a, b):\n    return a - b\n"
        )


class TestFailedRuns:
    def test_repair_generation_failure(self, project, tmp_path):
        executor = ScriptedExecutor([_result(exit_code=1)])
        engine, storage = _engine(tmp_path, executor, FakeLLMProvider([INVESTIGATION_JSON]))
        result = engine.execute(project, auto_approve=True)
        assert result["status"] == RunStatus.REPAIR_FAILED
        assert "LLM" in result["reason"]
        run = storage.get_run(result["run_id"])
        assert run["status"] == "REPAIR_FAILED"
        assert run["error_summary"]

    def test_missing_llm_provider_fails_cleanly(self, project, tmp_path):
        executor = ScriptedExecutor([_result(exit_code=1)])
        config = {
            "FIXPILOT_DB_PATH": str(tmp_path / "fixpilot.sqlite3"),
            "FIXPILOT_REPORTS_DIR": str(tmp_path / "reports"),
            "language": "python",
            "test_framework": "pytest",
            "FIXPILOT_APPROVAL_REQUIRED": False,
        }
        storage = Storage(config["FIXPILOT_DB_PATH"], reports_dir=config["FIXPILOT_REPORTS_DIR"])
        engine = WorkflowEngine(config=config, storage=storage, llm_provider=None,
                                executor=executor)
        result = engine.execute(project, auto_approve=True)
        assert result["status"] == RunStatus.REPAIR_FAILED

    def test_execution_failure(self, project, tmp_path):
        executor = ScriptedExecutor(
            [_result(exit_code=-1, stdout="", stderr="command not found")]
        )
        engine, _ = _engine(tmp_path, executor, FakeLLMProvider())
        result = engine.execute(project, auto_approve=True)
        assert result["status"] == RunStatus.EXECUTION_FAILED

    def test_baseline_timeout(self, project, tmp_path):
        executor = ScriptedExecutor([_result(exit_code=-1, timed_out=True)])
        engine, _ = _engine(tmp_path, executor, FakeLLMProvider())
        result = engine.execute(project, auto_approve=True)
        assert result["status"] == RunStatus.TIMEOUT

    def test_verification_failure_is_not_success(self, project, tmp_path):
        executor = ScriptedExecutor(
            [_result(exit_code=1), _result(exit_code=1, stdout=FAILING_OUTPUT)]
        )
        llm = FakeLLMProvider([INVESTIGATION_JSON, USELESS_PATCH])
        engine, storage = _engine(tmp_path, executor, llm)
        result = engine.execute(project, auto_approve=True)
        assert result["status"] != RunStatus.SUCCESS
        assert result["status"] == RunStatus.FAILED
        assert storage.get_run(result["run_id"])["status"] == "FAILED"

    def test_invalid_patch_is_rejected(self, project, tmp_path):
        executor = ScriptedExecutor([_result(exit_code=1)])
        llm = FakeLLMProvider([INVESTIGATION_JSON, TRAVERSAL_PATCH])
        engine, storage = _engine(tmp_path, executor, llm)
        result = engine.execute(project, auto_approve=True)
        assert result["status"] == RunStatus.PATCH_INVALID
        attempts = storage.get_run_attempts(result["run_id"])
        assert any(a["test_status"] == "INVALID_PATCH" for a in attempts)
        # The workspace (and the original project) stay untouched.
        assert (project / "calculator.py").read_text(encoding="utf-8") == (
            "def add(a, b):\n    return a - b\n"
        )


class TestRetryLoop:
    def test_second_attempt_sees_updated_state(self, project, tmp_path):
        """Attempt 2 must run against the files and diagnostics of attempt 1."""
        executor = ScriptedExecutor(
            [
                _result(exit_code=1, stdout=PARTIAL_OUTPUT),
                _result(exit_code=1, stdout=FAILING_OUTPUT),
                _result(exit_code=0, stdout=PASSING_OUTPUT),
            ]
        )
        llm = FakeLLMProvider(
            [INVESTIGATION_JSON, GOOD_PATCH, INVESTIGATION_JSON, SECOND_PATCH]
        )
        engine, _ = _engine(tmp_path, executor, llm, FIXPILOT_MAX_RETRIES=3)
        result = engine.execute(project, auto_approve=True)
        assert result["status"] == RunStatus.SUCCESS
        assert result["attempts"] == 2

        # The repairer saw the file content that the first attempt changed.
        repair_prompts = [
            p for p in llm.prompts if "FixPilot Repairer" in p
        ]
        assert len(repair_prompts) == 2
        assert "return a + b" in repair_prompts[1]

        # Attempt 1 saw both failing tests, attempt 2 only the remaining one
        # - the diagnostics are refreshed after every failed verification.
        assert "test_sub" in repair_prompts[0]
        assert "test_sub" not in repair_prompts[1]
        assert "CURRENTLY FAILING TEST: tests/test_calculator.py::test_add" in (
            repair_prompts[1]
        )

    def test_identical_patch_is_not_applied_twice(self, project, tmp_path):
        executor = ScriptedExecutor(
            [
                _result(exit_code=1, stdout=PARTIAL_OUTPUT),
                _result(exit_code=1, stdout=FAILING_OUTPUT),
            ]
        )
        llm = FakeLLMProvider([INVESTIGATION_JSON, USELESS_PATCH])
        engine, storage = _engine(tmp_path, executor, llm, FIXPILOT_MAX_RETRIES=3)
        result = engine.execute(project, auto_approve=True)
        assert result["status"] == RunStatus.FAILED
        assert "repeated" in result["reason"].lower()
        attempts = storage.get_run_attempts(result["run_id"])
        assert any(a["test_status"] == "REPEATED_PATCH" for a in attempts)
        # The test command ran only twice (baseline + first attempt).
        assert len(executor.calls) == 2

    def test_retry_limit_is_respected(self, project, tmp_path):
        executor = ScriptedExecutor(
            [
                _result(exit_code=1, stdout=PARTIAL_OUTPUT),
                _result(exit_code=1, stdout=FAILING_OUTPUT),
                _result(exit_code=1, stdout=FAILING_OUTPUT),
            ]
        )
        llm = FakeLLMProvider(
            [INVESTIGATION_JSON, USELESS_PATCH, INVESTIGATION_JSON, USELESS_PATCH]
        )
        engine, storage = _engine(tmp_path, executor, llm, FIXPILOT_MAX_RETRIES=2)
        result = engine.execute(project, auto_approve=True)
        assert result["status"] == RunStatus.FAILED
        assert result["attempts"] == 2
        assert len(storage.get_run_attempts(result["run_id"])) == 2

    def test_successful_verification_stops_immediately(self, project, tmp_path):
        executor = ScriptedExecutor(
            [_result(exit_code=1), _result(exit_code=0, stdout=PASSING_OUTPUT)]
        )
        llm = FakeLLMProvider([INVESTIGATION_JSON, GOOD_PATCH])
        engine, _ = _engine(tmp_path, executor, llm, FIXPILOT_MAX_RETRIES=5)
        result = engine.execute(project, auto_approve=True)
        assert result["status"] == RunStatus.SUCCESS
        assert result["attempts"] == 1
        # baseline + one verification run only
        assert len(executor.calls) == 2


class TestApprovalGate:
    def test_user_rejection(self, project, tmp_path, monkeypatch):
        executor = ScriptedExecutor(
            [_result(exit_code=1), _result(exit_code=0, stdout=PASSING_OUTPUT)]
        )
        llm = FakeLLMProvider([INVESTIGATION_JSON, GOOD_PATCH])
        engine, storage = _engine(
            tmp_path, executor, llm, FIXPILOT_APPROVAL_REQUIRED=True
        )
        monkeypatch.setattr("builtins.input", lambda *args: "n")
        result = engine.execute(project, auto_approve=False)
        assert result["status"] == RunStatus.REJECTED
        attempts = storage.get_run_attempts(result["run_id"])
        assert attempts[0]["approval_status"] == "REJECTED"

    def test_closed_stdin_is_a_rejection(self, project, tmp_path, monkeypatch):
        executor = ScriptedExecutor(
            [_result(exit_code=1), _result(exit_code=0, stdout=PASSING_OUTPUT)]
        )
        llm = FakeLLMProvider([INVESTIGATION_JSON, GOOD_PATCH])
        engine, _ = _engine(tmp_path, executor, llm, FIXPILOT_APPROVAL_REQUIRED=True)

        def _raise_eof(*args):
            raise EOFError

        monkeypatch.setattr("builtins.input", _raise_eof)
        result = engine.execute(project, auto_approve=False)
        assert result["status"] == RunStatus.REJECTED


class TestCancellation:
    def test_keyboard_interrupt_marks_run_cancelled(self, project, tmp_path, monkeypatch):
        executor = ScriptedExecutor([_result(exit_code=1)])
        llm = FakeLLMProvider([INVESTIGATION_JSON])

        def _interrupt(*args, **kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr(
            "fixpilot.workflow.engine.WorkflowEngine._run_pipeline", _interrupt
        )
        engine, storage = _engine(tmp_path, executor, llm)
        result = engine.execute(project, auto_approve=True)
        assert result["status"] == RunStatus.CANCELLED
        assert storage.get_run(result["run_id"])["status"] == "CANCELLED"


class TestContextFallback:
    """The repairer must never work without any source code."""

    def test_empty_plan_falls_back_to_the_diagnostic_files(self, project, tmp_path):
        """An investigation without a hypothesis must not leave the plan empty."""
        empty_investigation = json.dumps(
            {
                "summary": "no idea",
                "root_cause_hypotheses": [],
                "evidence": [],
                "affected_files": [],
                "missing_information": [],
                "recommended_next_action": "plan_repair",
                "confidence": "low",
                "limitations": [],
            }
        )
        executor = ScriptedExecutor(
            [_result(exit_code=1), _result(exit_code=0, stdout=PASSING_OUTPUT)]
        )
        llm = FakeLLMProvider([empty_investigation, GOOD_PATCH])
        engine, _ = _engine(tmp_path, executor, llm)
        engine.execute(project, auto_approve=True)

        # The repairer received the real source file even though the
        # investigation produced no hypothesis.
        repair_prompts = [p for p in llm.prompts if "FixPilot Repairer" in p]
        assert repair_prompts
        assert "calculator.py" in repair_prompts[0]
        assert "def add(a, b)" in repair_prompts[0]

    def test_investigation_without_hypothesis_falls_back_to_diagnostics(
        self, project, tmp_path
    ):
        """The investigator keeps a diagnostic-derived hypothesis."""
        from fixpilot.agents.investigator import Investigator

        empty_investigation = json.dumps(
            {"summary": "no idea", "root_cause_hypotheses": [], "affected_files": []}
        )
        investigator = Investigator(FakeLLMProvider([empty_investigation]))
        diagnostics = {
            "test_output": FAILING_OUTPUT,
            "stderr": "",
            "traceback": "",
            "failing_test": "tests/test_calculator.py::test_add",
            "parsed_failures": [],
        }
        result = investigator.investigate(diagnostics, {"language": "python"}, {})
        assert result.root_cause_hypotheses


class TestReporting:
    def test_no_tests_is_not_a_success(self, project, tmp_path):
        """A project without tests must not be reported as a verified success."""
        executor = ScriptedExecutor(
            [
                _result(
                    exit_code=5,
                    stdout="no tests ran in 0.01s\n",
                )
            ]
        )
        engine, storage = _engine(tmp_path, executor, FakeLLMProvider())
        result = engine.execute(project, auto_approve=True)
        assert result["status"] == RunStatus.NO_TESTS
        assert result["status"] != RunStatus.SUCCESS
        assert storage.get_run(result["run_id"])["status"] == "NO_TESTS"

    def test_report_is_generated_for_failed_runs(self, project, tmp_path):
        executor = ScriptedExecutor([_result(exit_code=1)])
        engine, storage = _engine(tmp_path, executor, FakeLLMProvider([INVESTIGATION_JSON]))
        result = engine.execute(project, auto_approve=True)
        assert result["status"] == RunStatus.REPAIR_FAILED
        report = storage.export_report(result["run_id"])
        assert report is not None
        assert "REPAIR_FAILED" in report

    def test_final_test_results_are_persisted(self, project, tmp_path):
        executor = ScriptedExecutor(
            [_result(exit_code=1), _result(exit_code=0, stdout=PASSING_OUTPUT)]
        )
        llm = FakeLLMProvider([INVESTIGATION_JSON, GOOD_PATCH])
        engine, storage = _engine(tmp_path, executor, llm)
        result = engine.execute(project, auto_approve=True)
        run = storage.get_run(result["run_id"])
        assert run["final_test_status"] == "PASS"
        assert "passed" in (run["final_test_output"] or "")
