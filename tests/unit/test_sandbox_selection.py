"""Tests for the sandbox executor selection policy.

Acceptance criteria of the "fix unsafe local execution fallback" task:

* Docker unavailable + default settings  -> execution is blocked
* Docker unavailable + explicit unsafe option -> local execution allowed
* Docker available -> the Docker executor is used
* There is never a silent fallback to host execution
"""

from pathlib import Path

import pytest

from fixpilot.config import is_unsafe_local_execution_allowed
from fixpilot.sandbox import (
    DockerExecutor,
    DockerUnavailableError,
    LocalExecutor,
    create_executor,
)
from fixpilot.workflow.engine import WorkflowEngine


@pytest.fixture
def docker_unavailable(monkeypatch):
    """Pretend that Docker is not installed / not running."""
    monkeypatch.setattr(DockerExecutor, "is_available", lambda self: False)


@pytest.fixture
def docker_available(monkeypatch):
    """Pretend that the Docker daemon is reachable."""
    monkeypatch.setattr(DockerExecutor, "is_available", lambda self: True)


class TestConfigDefaults:
    """The unsafe options must be disabled by default."""

    def test_local_execution_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("FIXPILOT_ALLOW_UNSAFE_LOCAL_EXECUTION", raising=False)
        monkeypatch.delenv("FIXPILOT_ALLOW_LOCAL_RUNNER", raising=False)
        from fixpilot.config import get_config

        config = get_config()
        assert config["FIXPILOT_ALLOW_UNSAFE_LOCAL_EXECUTION"] is False
        assert is_unsafe_local_execution_allowed(config) is False

    def test_network_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("FIXPILOT_ALLOW_NETWORK", raising=False)
        from fixpilot.config import get_config

        config = get_config()
        assert config["FIXPILOT_ALLOW_NETWORK"] is False
        assert config["FIXPILOT_ALLOW_DEPENDENCY_INSTALL"] is False
        assert config["FIXPILOT_DEPENDENCY_INSTALL_NETWORK"] is False

    def test_file_creation_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("FIXPILOT_ALLOW_FILE_CREATION", raising=False)
        monkeypatch.delenv("FIXPILOT_ALLOW_FILE_DELETION", raising=False)
        from fixpilot.config import get_config

        config = get_config()
        assert config["FIXPILOT_ALLOW_FILE_CREATION"] is False
        assert config["FIXPILOT_ALLOW_FILE_DELETION"] is False

    def test_helper_handles_empty_config(self):
        assert is_unsafe_local_execution_allowed({}) is False
        assert is_unsafe_local_execution_allowed(None) is False

    def test_helper_honours_legacy_alias(self):
        assert is_unsafe_local_execution_allowed(
            {"FIXPILOT_ALLOW_LOCAL_RUNNER": True}
        ) is True


class TestExecutorSelection:
    """The runner is chosen in exactly one place."""

    def test_docker_used_when_available(self, docker_available):
        executor = create_executor({})
        assert isinstance(executor, DockerExecutor)

    def test_blocked_when_docker_unavailable(self, docker_unavailable):
        with pytest.raises(DockerUnavailableError) as exc_info:
            create_executor({})
        assert "Docker" in str(exc_info.value)

    def test_local_allowed_with_explicit_opt_in(self, docker_unavailable):
        executor = create_executor(
            {"FIXPILOT_ALLOW_UNSAFE_LOCAL_EXECUTION": True}
        )
        assert isinstance(executor, LocalExecutor)

    def test_local_allowed_with_legacy_opt_in(self, docker_unavailable):
        executor = create_executor({"FIXPILOT_ALLOW_LOCAL_RUNNER": True})
        assert isinstance(executor, LocalExecutor)

    def test_no_silent_fallback(self, docker_unavailable):
        """The default configuration must never produce a local runner."""
        for config in ({}, {"FIXPILOT_ALLOW_UNSAFE_LOCAL_EXECUTION": False}):
            with pytest.raises(DockerUnavailableError):
                create_executor(config)

    def test_explicit_executor_is_used(self, docker_unavailable):
        sentinel = object()
        assert create_executor({}, executor=sentinel) is sentinel


class TestWorkflowEngineUsesPolicy:
    """The workflow engine must apply the very same policy."""

    def test_engine_blocks_without_docker(self, docker_unavailable, tmp_path: Path):
        with pytest.raises(DockerUnavailableError):
            WorkflowEngine(config={"FIXPILOT_DB_PATH": str(tmp_path / "db.sqlite3")})

    def test_engine_uses_local_runner_when_opted_in(
        self, docker_unavailable, tmp_path: Path
    ):
        engine = WorkflowEngine(
            config={
                "FIXPILOT_DB_PATH": str(tmp_path / "db.sqlite3"),
                "FIXPILOT_ALLOW_UNSAFE_LOCAL_EXECUTION": True,
            }
        )
        assert isinstance(engine.executor, LocalExecutor)

    def test_engine_uses_docker_when_available(self, docker_available, tmp_path: Path):
        engine = WorkflowEngine(
            config={"FIXPILOT_DB_PATH": str(tmp_path / "db.sqlite3")}
        )
        assert isinstance(engine.executor, DockerExecutor)

    def test_engine_never_silently_uses_local_runner(
        self, docker_unavailable, tmp_path: Path
    ):
        """A missing Docker daemon must raise, never fall back silently."""
        with pytest.raises(DockerUnavailableError):
            WorkflowEngine(config={"FIXPILOT_DB_PATH": str(tmp_path / "db.sqlite3")})


class TestLocalExecutorSafety:
    """The local runner must be clearly marked as unsafe."""

    def test_sandbox_id_marks_unsafe_execution(self, tmp_path: Path):
        executor = LocalExecutor({"FIXPILOT_TIMEOUT_SECONDS": 30})
        result = executor.run_tests(
            ["python", "-c", "print('ok')"], tmp_path
        )
        assert result.exit_code == 0
        assert result.sandbox_id == LocalExecutor.SANDBOX_ID
        assert "unsafe" in LocalExecutor.SANDBOX_ID

    def test_timeout_is_enforced(self, tmp_path: Path):
        executor = LocalExecutor({"FIXPILOT_TIMEOUT_SECONDS": 1})
        result = executor.run_tests(
            ["python", "-c", "import time; time.sleep(30)"], tmp_path
        )
        assert result.timed_out is True
        assert result.exit_code == -1

    def test_missing_command_is_reported(self, tmp_path: Path):
        executor = LocalExecutor({"FIXPILOT_TIMEOUT_SECONDS": 5})
        result = executor.run_tests(["definitely-not-a-real-command"], tmp_path)
        assert result.exit_code == -1
        assert result.stderr
