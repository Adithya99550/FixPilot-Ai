"""Tests for the Docker sandbox executor.

Acceptance criteria of the "remove unsafe Docker host networking" task:

* normal test execution uses network isolation (``--network none``)
* host networking is never enabled implicitly
* network-enabled execution requires explicit configuration
* the docker command is built with the expected safety flags
* containers are cleaned up even when execution fails or times out
"""

import subprocess
from pathlib import Path

import pytest

from fixpilot.sandbox.docker_executor import DockerExecutor, DockerUnavailableError


@pytest.fixture
def executor() -> DockerExecutor:
    return DockerExecutor({"FIXPILOT_TIMEOUT_SECONDS": 5})


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "app.py").write_text("print('hello')\n", encoding="utf-8")
    return ws


class TestNetworkIsolation:
    """The container must never see the host network by default."""

    def test_network_none_by_default(self, executor, workspace: Path):
        cmd = executor.build_run_command(["pytest"], workspace)
        assert "--network" in cmd
        assert cmd[cmd.index("--network") + 1] == "none"

    def test_host_network_is_never_used(self, executor, workspace: Path):
        cmd = executor.build_run_command(["pytest"], workspace)
        assert "host" not in cmd

    def test_network_none_even_for_network_needing_languages(
        self, workspace: Path
    ):
        """A language that usually needs the network (Java/Maven) still gets
        an isolated container for *test* execution."""
        executor = DockerExecutor({})
        cmd = executor.build_run_command(
            ["mvn", "test"], workspace, language="java"
        )
        assert cmd[cmd.index("--network") + 1] == "none"
        assert "host" not in cmd

    def test_explicit_network_is_the_only_way_to_enable_it(
        self, workspace: Path
    ):
        executor = DockerExecutor({"FIXPILOT_ALLOW_NETWORK": True})
        # Even with the flag set, the *test* command keeps the isolated
        # default; the flag alone must not switch the sandbox to the host
        # network.
        cmd = executor.build_run_command(["pytest"], workspace)
        assert cmd[cmd.index("--network") + 1] == "none"

    def test_dependency_install_uses_bridge_not_host(self, workspace: Path):
        executor = DockerExecutor(
            {
                "FIXPILOT_ALLOW_DEPENDENCY_INSTALL": True,
                "FIXPILOT_DEPENDENCY_INSTALL_NETWORK": True,
            }
        )
        cmd = executor.build_run_command(
            ["pip", "install", "-r", "requirements.txt"],
            workspace,
            network="bridge",
        )
        assert cmd[cmd.index("--network") + 1] == "bridge"
        assert "host" not in cmd


class TestCommandConstruction:
    """The docker command must carry the expected safety controls."""

    def test_resource_limits_present(self, executor, workspace: Path):
        cmd = executor.build_run_command(["pytest"], workspace)
        assert cmd[cmd.index("--memory") + 1] == "1g"
        assert cmd[cmd.index("--cpus") + 1] == "1"
        assert cmd[cmd.index("--pids-limit") + 1] == "128"

    def test_runs_as_non_root(self, executor, workspace: Path):
        cmd = executor.build_run_command(["pytest"], workspace)
        assert cmd[cmd.index("--user") + 1] == "nonroot:nonroot"

    def test_capabilities_dropped_and_privileges_removed(self, executor, workspace):
        cmd = executor.build_run_command(["pytest"], workspace)
        assert cmd[cmd.index("--cap-drop") + 1] == "ALL"
        assert "no-new-privileges" in cmd

    def test_privileged_is_never_used(self, executor, workspace: Path):
        cmd = executor.build_run_command(["pytest"], workspace)
        assert "--privileged" not in cmd

    def test_docker_socket_is_never_mounted(self, executor, workspace: Path):
        cmd = executor.build_run_command(["pytest"], workspace)
        assert not any("docker.sock" in part for part in cmd)

    def test_only_the_workspace_is_mounted(self, executor, workspace: Path):
        cmd = executor.build_run_command(["pytest"], workspace)
        mounts = [cmd[i + 1] for i, part in enumerate(cmd) if part == "-v"]
        assert len(mounts) == 1
        assert mounts[0].startswith(str(workspace.resolve()))
        assert mounts[0].endswith(":/project:rw")

    def test_container_is_named_and_removed(self, executor, workspace: Path):
        cmd = executor.build_run_command(["pytest"], workspace)
        assert "--rm" in cmd
        assert cmd[cmd.index("--name") + 1].startswith("fixpilot-sandbox-")

    def test_command_is_a_list_not_a_shell_string(self, executor, workspace: Path):
        cmd = executor.build_run_command(["pytest", "-q"], workspace)
        assert isinstance(cmd, list)
        assert cmd[-2:] == ["pytest", "-q"]


class TestAvailability:
    """Docker availability detection."""

    def test_unavailable_when_binary_missing(self, executor, monkeypatch):
        def _raise(*args, **kwargs):
            raise FileNotFoundError("docker")

        monkeypatch.setattr(subprocess, "run", _raise)
        assert executor.is_available() is False

    def test_unavailable_when_daemon_fails(self, executor, monkeypatch):
        class _Result:
            returncode = 1

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Result())
        assert executor.is_available() is False

    def test_available_when_daemon_responds(self, executor, monkeypatch):
        class _Result:
            returncode = 0

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Result())
        assert executor.is_available() is True

    def test_run_tests_raises_when_docker_missing(self, executor, monkeypatch, workspace):
        monkeypatch.setattr(DockerExecutor, "is_available", lambda self: False)
        with pytest.raises(DockerUnavailableError):
            executor.run_tests(["pytest"], workspace)


class TestExecution:
    """Execution results and cleanup behaviour."""

    def _result(self, returncode=0, stdout=b"", stderr=b""):
        class _Result:
            pass

        r = _Result()
        r.returncode = returncode
        r.stdout = stdout
        r.stderr = stderr
        return r

    def test_successful_run_returns_output(self, executor, monkeypatch, workspace):
        monkeypatch.setattr(DockerExecutor, "is_available", lambda self: True)
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: self._result(0, b"1 passed\n", b""),
        )
        result = executor.run_tests(["pytest"], workspace)
        assert result.exit_code == 0
        assert "1 passed" in result.stdout
        assert result.timed_out is False

    def test_non_zero_exit_is_reported(self, executor, monkeypatch, workspace):
        monkeypatch.setattr(DockerExecutor, "is_available", lambda self: True)
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: self._result(1, b"", b"boom\n"),
        )
        result = executor.run_tests(["pytest"], workspace)
        assert result.exit_code == 1
        assert "boom" in result.stderr

    def test_timeout_is_reported_and_container_removed(
        self, executor, monkeypatch, workspace
    ):
        monkeypatch.setattr(DockerExecutor, "is_available", lambda self: True)
        removed = []

        def _run(cmd, *args, **kwargs):
            if cmd[:2] == ["docker", "rm"]:
                removed.append(cmd[-1])
                return self._result(0)
            raise subprocess.TimeoutExpired(cmd, 5)

        monkeypatch.setattr(subprocess, "run", _run)
        result = executor.run_tests(["pytest"], workspace)
        assert result.timed_out is True
        assert result.exit_code == -1
        # The container is force-removed even after a timeout.
        assert removed

    def test_container_is_removed_after_failure(self, executor, monkeypatch, workspace):
        monkeypatch.setattr(DockerExecutor, "is_available", lambda self: True)
        removed = []

        def _run(cmd, *args, **kwargs):
            if cmd[:2] == ["docker", "rm"]:
                removed.append(cmd[-1])
                return self._result(0)
            return self._result(1, b"", b"failed")

        monkeypatch.setattr(subprocess, "run", _run)
        executor.run_tests(["pytest"], workspace)
        assert removed

    def test_output_is_truncated(self, monkeypatch, workspace):
        executor = DockerExecutor({"max_output_bytes": 100})
        long_output = "x" * 5000
        assert "truncated" in executor._truncate_output(long_output)


class TestDependencyInstall:
    """Dependency installation is a separate, explicitly enabled phase."""

    def test_disabled_by_default(self, executor, workspace: Path):
        with pytest.raises(PermissionError):
            executor.install_dependencies(workspace, ["pip", "install", "-r", "req.txt"])

    def test_requires_docker(self, monkeypatch, workspace: Path):
        executor = DockerExecutor({"FIXPILOT_ALLOW_DEPENDENCY_INSTALL": True})
        monkeypatch.setattr(DockerExecutor, "is_available", lambda self: False)
        with pytest.raises(DockerUnavailableError):
            executor.install_dependencies(workspace, ["pip", "install", "-r", "req.txt"])
