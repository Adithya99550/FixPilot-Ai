"""FixPilot AI Docker sandbox executor.

Responsibilities:
- Run target tests and permitted commands inside Docker.
- Mount only the disposable working copy.
- Use non-root container user where feasible.
- Disable network by default for test execution (never host networking).
- Apply CPU, memory, process, and time limits.
- Avoid privileged containers and host Docker socket mounts.
- Capture output safely and enforce output size limits.
- Return structured execution results.
- Always clean the container up, even on failure or timeout.

Network policy
--------------
``--network host`` is never used. Test execution always runs with
``--network none``. Dependency installation is a *separate*, explicitly enabled
phase that may only use the default bridge network - never the host network.
"""

import logging
import subprocess
import time
import uuid
from pathlib import Path
from typing import List, Optional
from fixpilot.schemas.execution import ExecutionResult

logger = logging.getLogger("fixpilot.sandbox.docker")


class DockerUnavailableError(Exception):
    """Raised when Docker is not available."""

    pass


class DockerExecutor:
    """Execute commands in a Docker sandbox."""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.sandbox_image = self.config.get(
            "FIXPILOT_SANDBOX_IMAGE", "fixpilot-sandbox:latest"
        )
        self.timeout_seconds = int(self.config.get("FIXPILOT_TIMEOUT_SECONDS", 120))
        self.memory_limit = self.config.get("memory_limit", "1g")
        self.cpus = self.config.get("cpus", 1)
        self.pids_limit = self.config.get("pids_limit", 128)
        self.max_output_bytes = self.config.get("max_output_bytes", 2000000)

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True when the Docker daemon is actually reachable."""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=5,
                shell=False,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    # Backwards compatible alias - the CLI and older callers use the private
    # name.
    def _check_docker_available(self) -> bool:
        """Deprecated alias of :meth:`is_available`."""
        return self.is_available()

    def _get_sandbox_image(self, language: str = None) -> str:
        """Get the appropriate sandbox image for the language."""
        # Check if a specific image is configured
        if self.config.get("sandbox_image"):
            return self.config["sandbox_image"]

        # Map languages to their sandbox images. The keys must match the
        # language ids used by fixpilot.languages.registry.
        image_map = {
            "python": "fixpilot-sandbox:python",
            "javascript": "fixpilot-sandbox:node",
            "typescript": "fixpilot-sandbox:node",
            "go": "fixpilot-sandbox:go",
            "rust": "fixpilot-sandbox:rust",
            "java": "fixpilot-sandbox:java",
            "java-maven": "fixpilot-sandbox:java",
            "java-gradle": "fixpilot-sandbox:java",
        }
        # A globally configured image always wins over the per-language map.
        return image_map.get(language, self.sandbox_image)

    # ------------------------------------------------------------------
    # Command construction
    # ------------------------------------------------------------------

    def build_run_command(
        self,
        command: List[str],
        workspace_path: Path,
        language: str = None,
        container_name: str = None,
        network: str = "none",
    ) -> List[str]:
        """Build the ``docker run`` argument list.

        The command is constructed explicitly (never through a shell) so the
        target project cannot inject additional docker arguments.

        Args:
            command: The command to run inside the container.
            workspace_path: The disposable workspace, mounted at ``/project``.
            language: Programming language (selects the sandbox image).
            container_name: Explicit container name (used for cleanup).
            network: Docker network mode. Defaults to ``none`` (isolated).

        Returns:
            The full argument list for ``docker run``.
        """
        sandbox_image = self._get_sandbox_image(language)
        name = container_name or f"fixpilot-sandbox-{uuid.uuid4().hex[:12]}"

        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            # Network isolation: never host networking.
            "--network",
            network,
            # Resource limits.
            "--memory",
            str(self.memory_limit),
            "--cpus",
            str(self.cpus),
            "--pids-limit",
            str(self.pids_limit),
            # Privilege reduction.
            "--user",
            "nonroot:nonroot",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
        ]

        # Mount only the disposable working copy.
        docker_cmd.extend([
            "-v",
            f"{Path(workspace_path).resolve()}:/project:rw",
            "-w",
            "/project",
        ])

        docker_cmd.append(sandbox_image)
        docker_cmd.extend(list(command))
        return docker_cmd

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run_tests(
        self,
        test_command: list,
        workspace_path: Path,
        workdir: Path = None,
        language: str = None,
        build_command: list = None,
    ) -> ExecutionResult:
        """Run tests in a Docker sandbox.

        Args:
            test_command: The test command to execute
            workspace_path: Path to the disposable workspace
            workdir: Working directory within the workspace
            language: Programming language (for selecting sandbox image)
            build_command: Optional build command to run before tests

        Returns:
            ExecutionResult with test output and metadata

        Raises:
            DockerUnavailableError: If Docker is not available on the host
        """
        if not self.is_available():
            raise DockerUnavailableError(
                "Docker is not available on this system. "
                "Sandboxed execution requires Docker. "
                "Install Docker or configure the environment with "
                "valid Docker access to run target code."
            )

        # Run build command first if provided (still network isolated).
        if build_command:
            build_result = self._execute(
                self._as_command(build_command),
                workspace_path,
                language,
                purpose="build",
            )
            if build_result.exit_code != 0 or build_result.timed_out:
                return build_result

        cmd = list(test_command) if test_command else ["python", "-m", "pytest", "-q"]
        return self._execute(cmd, workspace_path, language, purpose="test")

    def install_dependencies(
        self,
        workspace_path: Path,
        install_command: List[str],
        language: str = None,
    ) -> ExecutionResult:
        """Install project dependencies in a controlled container.

        Dependency installation is deliberately separated from test
        execution: it is only performed when explicitly enabled, and it may
        only use the default bridge network - never host networking.

        Args:
            workspace_path: Path to the disposable workspace.
            install_command: Command used to install the dependencies.
            language: Programming language (selects the sandbox image).

        Returns:
            ExecutionResult describing the installation run.

        Raises:
            PermissionError: If dependency installation is not enabled.
        """
        if not self.config.get("FIXPILOT_ALLOW_DEPENDENCY_INSTALL", False):
            raise PermissionError(
                "Dependency installation is disabled. Set "
                "FIXPILOT_ALLOW_DEPENDENCY_INSTALL=true to enable it."
            )

        if not self.is_available():
            raise DockerUnavailableError(
                "Docker is not available on this system; dependency "
                "installation requires the Docker sandbox."
            )

        # Bridge networking is the only network mode a dependency install may
        # use. Host networking is never available.
        network = (
            "bridge"
            if self.config.get("FIXPILOT_DEPENDENCY_INSTALL_NETWORK", False)
            else "none"
        )
        return self._execute(
            self._as_command(install_command),
            workspace_path,
            language,
            purpose="dependency-install",
            network=network,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _as_command(command) -> List[str]:
        """Normalise a command into an argument list.

        Commands containing shell operators are wrapped in ``sh -c`` so they
        behave the way a user would expect, but they are still executed
        without a shell on the host side.
        """
        if isinstance(command, str):
            command_str = command
        else:
            command_str = " ".join(str(part) for part in command)

        if any(op in command_str for op in ("&&", "||", ";", "|", ">", "$")):
            return ["sh", "-c", command_str]
        return command_str.split()

    def _execute(
        self,
        command: List[str],
        workspace_path: Path,
        language: str = None,
        purpose: str = "test",
        network: str = "none",
    ) -> ExecutionResult:
        """Run a command inside the sandbox and always clean up afterwards."""
        container_name = f"fixpilot-sandbox-{uuid.uuid4().hex[:12]}"
        docker_cmd = self.build_run_command(
            command,
            workspace_path,
            language=language,
            container_name=container_name,
            network=network,
        )

        start_time = time.time()
        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                timeout=self.timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            duration = round(time.time() - start_time, 3)
            self._remove_container(container_name)
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=f"Execution timed out after {self.timeout_seconds}s",
                timed_out=True,
                duration=duration,
                sandbox_id=container_name,
            )
        except FileNotFoundError as exc:
            duration = round(time.time() - start_time, 3)
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=f"Docker CLI not found: {exc}",
                timed_out=False,
                duration=duration,
                sandbox_id=container_name,
            )
        except OSError as exc:
            duration = round(time.time() - start_time, 3)
            self._remove_container(container_name)
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=f"Docker execution failed: {exc}",
                timed_out=False,
                duration=duration,
                sandbox_id=container_name,
            )

        duration = round(time.time() - start_time, 3)
        # Belt and braces: the container was started with --rm, so it is
        # normally gone already. Removing it explicitly also covers the case
        # where the daemon died before the cleanup could happen.
        self._remove_container(container_name)

        stdout = self._truncate_output(result.stdout.decode("utf-8", errors="replace"))
        stderr = self._truncate_output(result.stderr.decode("utf-8", errors="replace"))

        # Docker exits with 125 when the container itself could not be run
        # (missing image, bad runtime, ...). That is an infrastructure
        # failure, not a failing test suite.
        if result.returncode == 125:
            return ExecutionResult(
                exit_code=-1,
                stdout=stdout,
                stderr=(
                    f"Sandbox container failed to start (docker exit 125): {stderr}"
                    if stderr
                    else "Sandbox container failed to start (docker exit 125)."
                ),
                timed_out=False,
                duration=duration,
                sandbox_id=container_name,
            )

        return ExecutionResult(
            exit_code=result.returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=False,
            duration=duration,
            sandbox_id=container_name,
        )

    def _remove_container(self, container_name: str) -> None:
        """Force-remove a container, ignoring errors (it may already be gone)."""
        if not container_name:
            return
        try:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True,
                timeout=30,
                shell=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            logger.debug("Container cleanup for %s failed: %s", container_name, exc)

    def _truncate_output(self, output: str) -> str:
        """Truncate output if it exceeds size limits."""
        max_bytes = self.max_output_bytes
        if len(output.encode("utf-8")) > max_bytes:
            truncated = output[:max_bytes]
            return truncated + "\n... [output truncated] ..."
        return output
