"""FixPilot AI unsafe local executor.

.. warning::
   This executor runs the **target project's own code** directly on the host
   machine. It exists only as an explicit, opt-in escape hatch for
   environments where Docker is unavailable (for example a laptop without a
   container runtime). It is *never* selected automatically - see
   :func:`fixpilot.sandbox.create_executor`.

Security notes:

- Commands are executed as argument lists (never through a shell), so the
  target project cannot inject extra commands through the command line.
- Every subprocess has a hard timeout, so a hanging test suite cannot block
  FixPilot forever.
- The executor always runs inside the disposable workspace, never in the
  user's original repository.
"""

import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fixpilot.schemas.execution import ExecutionResult

logger = logging.getLogger("fixpilot.sandbox.local")

UNSAFE_LOCAL_EXECUTION_WARNING = (
    "[!] UNSAFE: Docker sandbox unavailable - the target project's code will "
    "execute directly on this host machine (FIXPILOT_ALLOW_UNSAFE_LOCAL_EXECUTION=true).\n"
    "    Only use this for code you trust."
)


class LocalExecutor:
    """Local test executor for trusted code only.

    This is deliberately *not* the default runner. Docker sandboxing is the
    default and preferred execution mode; see
    :func:`fixpilot.sandbox.create_executor`.
    """

    #: Marker used in :class:`~fixpilot.schemas.execution.ExecutionResult`
    #: so reports can show that no sandbox was used.
    SANDBOX_ID = "local-unsafe"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.timeout_seconds = int(self.config.get("FIXPILOT_TIMEOUT_SECONDS", 120))

    def run_tests(
        self,
        test_command: List[str],
        workspace_path: Path,
        language: str = None,
        build_command: List[str] = None,
    ) -> ExecutionResult:
        """Run the build (optional) and test commands inside the workspace.

        Args:
            test_command: Command to execute, given as an argument list.
            workspace_path: The disposable workspace to run in.
            language: Detected language (unused, kept for interface parity).
            build_command: Optional build command executed before the tests.

        Returns:
            An :class:`ExecutionResult` describing the run.
        """
        if build_command:
            build_result = self._run_command(build_command, workspace_path)
            if build_result.exit_code != 0:
                return build_result

        cmd = list(test_command) if test_command else ["python", "-m", "pytest", "-q"]
        return self._run_command(cmd, workspace_path)

    def _run_command(self, cmd: List[str], workspace_path: Path) -> ExecutionResult:
        """Execute a single command with a hard timeout."""
        start_time = time.time()
        try:
            result = subprocess.run(
                list(cmd),
                cwd=str(workspace_path),
                capture_output=True,
                timeout=self.timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            duration = round(time.time() - start_time, 3)
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=f"Local execution timed out after {self.timeout_seconds}s",
                timed_out=True,
                duration=duration,
                sandbox_id=self.SANDBOX_ID,
            )
        except FileNotFoundError as exc:
            duration = round(time.time() - start_time, 3)
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=f"Command not found: {exc}",
                timed_out=False,
                duration=duration,
                sandbox_id=self.SANDBOX_ID,
            )
        except OSError as exc:
            duration = round(time.time() - start_time, 3)
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=f"Local execution failed: {exc}",
                timed_out=False,
                duration=duration,
                sandbox_id=self.SANDBOX_ID,
            )

        duration = round(time.time() - start_time, 3)
        return ExecutionResult(
            exit_code=result.returncode,
            stdout=result.stdout.decode("utf-8", errors="replace"),
            stderr=result.stderr.decode("utf-8", errors="replace"),
            timed_out=False,
            duration=duration,
            sandbox_id=self.SANDBOX_ID,
        )
