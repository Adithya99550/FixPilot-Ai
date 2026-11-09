"""FixPilot AI Docker sandbox executor.

Responsibilities:
- Run target tests and permitted commands inside Docker.
- Mount only the disposable working copy.
- Use non-root container user where feasible.
- Disable network by default.
- Apply CPU, memory, process, and time limits.
- Avoid privileged containers and host Docker socket mounts.
- Capture output safely and enforce output size limits.
- Return structured execution results.
"""

import subprocess
import json
import os
import tempfile
from pathlib import Path
from fixpilot.schemas.execution import ExecutionResult


class DockerUnavailableError(Exception):
    """Raised when Docker is not available."""
    pass


class DockerExecutor:
    """Execute commands in a Docker sandbox."""

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.sandbox_image = self.config.get(
            "FIXPILOT_SANDBOX_IMAGE", "fixpilot-sandbox:latest"
        )
        self.timeout_seconds = self.config.get(
            "FIXPILOT_TIMEOUT_SECONDS", 120
        )
        self.memory_limit = self.config.get("memory_limit", "1g")
        self.cpus = self.config.get("cpus", 1)
        self.pids_limit = self.config.get("pids_limit", 128)
        self.max_output_bytes = self.config.get(
            "max_output_bytes", 2000000
        )

    def _check_docker_available(self) -> bool:
        """Check if Docker is available on the host."""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def run_tests(
        self,
        test_command: list,
        workspace_path: Path,
        workdir: Path = None,
    ) -> ExecutionResult:
        """Run tests in a Docker sandbox.

        Args:
            test_command: The pytest command to execute
            workspace_path: Path to the disposable workspace
            workdir: Working directory within the workspace

        Returns:
            ExecutionResult with test output and metadata

        Raises:
            DockerUnavailableError: If Docker is not available on the host
        """
        if not self._check_docker_available():
            raise DockerUnavailableError(
                "Docker is not available on this system. "
                "Sandboxed execution requires Docker. "
                "Install Docker or configure the environment with "
                "valid Docker access to run target code."
            )

        # Build Docker run command with security controls
        docker_cmd = [
            "docker", "run",
            "--rm",
            "--network", "none",
            "--memory", self.memory_limit,
            "--cpus", str(self.cpus),
            "--pids-limit", str(self.pids_limit),
            "--timeout", str(self.timeout_seconds),
            "--user", "nonroot:nonroot",
        ]

        # Mount the workspace as read-only, with a writable temp dir
        docker_cmd.extend([
            "-v", f"{workspace_path.resolve()}:/project:ro",
        ])

        if workdir:
            # Create a writable working copy
            workdir_path = workspace_path / workdir
            if workdir_path.exists():
                # Copy workspace to a temp writable location
                import shutil
                tmp_workdir = tempfile.mkdtemp(prefix="fixpilot_workspace_")
                shutil.copytree(workspace_path, tmp_workdir)
                docker_cmd.extend([
                    "-v", f"{tmp_workdir}:/workdir:rw",
                ])
                exec_workdir = "/workdir"
            else:
                exec_workdir = "/project"
        else:
            exec_workdir = "/project"

        # Add the sandbox image
        docker_cmd.extend([self.sandbox_image])

        # Add the test command
        cmd = test_command if test_command else ["python", "-m", "pytest", "-q"]

        # Construct the full command to run inside the container
        # Use shell=False and argument array for safety
        container_cmd = ["bash", "-c", " "]  # placeholder

        full_cmd = docker_cmd + [" ".join(cmd)]  # simplified for now

        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                timeout=self.timeout_seconds,
            )
            return ExecutionResult(
                exit_code=result.returncode,
                stdout=self._truncate_output(result.stdout.decode("utf-8", errors="replace")),
                stderr=self._truncate_output(result.stderr.decode("utf-8", errors="replace")),
                timed_out=False,
                duration=self.timeout_seconds,
                sandbox_id="",
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr="Execution timed out after {self.timeout_seconds}s",
                timed_out=True,
                duration=self.timeout_seconds,
                sandbox_id="",
            )
        except Exception as e:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                timed_out=False,
                duration=0,
                sandbox_id="",
            )

    def _truncate_output(self, output: str) -> str:
        """Truncate output if it exceeds size limits."""
        max_bytes = self.max_output_bytes
        if len(output.encode("utf-8")) > max_bytes:
            truncated = output[:max_bytes]
            return truncated + "\n... [output truncated] ..."
        return output