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
import time
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

    def _get_sandbox_image(self, language: str = None) -> str:
        """Get the appropriate sandbox image for the language."""
        # Check if a specific image is configured
        if "sandbox_image" in self.config:
            return self.config["sandbox_image"]

        # Map languages to their sandbox images
        image_map = {
            "python": "fixpilot-sandbox:python",
            "javascript": "fixpilot-sandbox:node",
            "typescript": "fixpilot-sandbox:node",
            "go": "fixpilot-sandbox:go",
            "rust": "fixpilot-sandbox:rust",
            "java": "fixpilot-sandbox:java",
        }
        return image_map.get(language, "fixpilot-sandbox:latest")

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
        if not self._check_docker_available():
            raise DockerUnavailableError(
                "Docker is not available on this system. "
                "Sandboxed execution requires Docker. "
                "Install Docker or configure the environment with "
                "valid Docker access to run target code."
            )

        # Get the appropriate sandbox image for the language
        sandbox_image = self._get_sandbox_image(language)

        # Check if language needs network
        lang_config = None
        if language:
            from fixpilot.languages import get_language_config
            try:
                lang_config = get_language_config(language)
            except Exception:
                pass

        needs_network = False
        if lang_config:
            needs_network = lang_config.needs_network
        elif "FIXPILOT_NEEDS_NETWORK" in self.config:
            needs_network = self.config["FIXPILOT_NEEDS_NETWORK"]

        # Build Docker run command with security controls
        docker_cmd = [
            "docker", "run",
            "--rm",
            "--network", "host" if needs_network else "none",
            "--memory", self.memory_limit,
            "--cpus", str(self.cpus),
            "--pids-limit", str(self.pids_limit),
            "--user", "nonroot:nonroot",
        ]

        # Mount the workspace (read-write for test commands that need it)
        # Some languages (Rust, Go) need write access during test execution
        mount_mode = "rw"
        docker_cmd.extend([
            "-v", f"{workspace_path.resolve()}:/project:{mount_mode}",
            "-w", "/project",
        ])

        # Add the sandbox image
        docker_cmd.append(sandbox_image)

        # Run build command first if provided
        if build_command:
            # If build_command contains shell operators (&&, ||, ;, |), wrap in sh -c
            build_str = " ".join(build_command) if isinstance(build_command, (list, tuple)) else str(build_command)
            if any(op in build_str for op in ("&&", "||", ";", "|", ">", "$")):
                build_cmd_list = ["sh", "-c", build_str]
            else:
                build_cmd_list = build_str.split()
            build_docker_cmd = docker_cmd + build_cmd_list
            start_time = time.time()
            try:
                build_result = subprocess.run(
                    build_docker_cmd,
                    capture_output=True,
                    timeout=self.timeout_seconds,
                )
                build_duration = time.time() - start_time
                if build_result.returncode != 0:
                    return ExecutionResult(
                        exit_code=build_result.returncode,
                        stdout=self._truncate_output(build_result.stdout.decode("utf-8", errors="replace")),
                        stderr=self._truncate_output(build_result.stderr.decode("utf-8", errors="replace")),
                        timed_out=False,
                        duration=round(build_duration, 3),
                        sandbox_id="",
                    )
            except subprocess.TimeoutExpired:
                build_duration = time.time() - start_time
                return ExecutionResult(
                    exit_code=-1,
                    stdout="",
                    stderr=f"Build timed out after {self.timeout_seconds}s",
                    timed_out=True,
                    duration=round(build_duration, 3),
                    sandbox_id="",
                )
            except Exception as e:
                build_duration = time.time() - start_time
                return ExecutionResult(
                    exit_code=-1,
                    stdout="",
                    stderr=str(e),
                    timed_out=False,
                    duration=round(build_duration, 3),
                    sandbox_id="",
                )

        # Run the test command
        cmd = test_command if test_command else ["python", "-m", "pytest", "-q"]
        full_cmd = docker_cmd + list(cmd)

        start_time = time.time()
        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                timeout=self.timeout_seconds,
            )
            duration = time.time() - start_time
            return ExecutionResult(
                exit_code=result.returncode,
                stdout=self._truncate_output(result.stdout.decode("utf-8", errors="replace")),
                stderr=self._truncate_output(result.stderr.decode("utf-8", errors="replace")),
                timed_out=False,
                duration=round(duration, 3),
                sandbox_id="",
            )
        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=f"Execution timed out after {self.timeout_seconds}s",
                timed_out=True,
                duration=round(duration, 3),
                sandbox_id="",
            )
        except Exception as e:
            duration = time.time() - start_time
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
                timed_out=False,
                duration=round(duration, 3),
                sandbox_id="",
            )

    def _truncate_output(self, output: str) -> str:
        """Truncate output if it exceeds size limits."""
        max_bytes = self.max_output_bytes
        if len(output.encode("utf-8")) > max_bytes:
            truncated = output[:max_bytes]
            return truncated + "\n... [output truncated] ..."
        return output