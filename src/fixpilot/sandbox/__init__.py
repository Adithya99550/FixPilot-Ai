"""FixPilot AI sandbox package.

The sandbox package owns the *execution* boundary of FixPilot:

- :class:`~fixpilot.sandbox.docker_executor.DockerExecutor` - the default and
  preferred runner. Target code executes inside a locked down container.
- :class:`~fixpilot.sandbox.local_executor.LocalExecutor` - an explicit,
  opt-in escape hatch that runs target code directly on the host. It is never
  selected automatically.

:func:`create_executor` is the single place where the runner is chosen, so the
CLI, the dashboard and the workflow engine all share exactly the same policy.
"""

import logging
from typing import Any, Dict, Optional

from fixpilot.config import is_unsafe_local_execution_allowed
from fixpilot.sandbox.docker_executor import DockerExecutor, DockerUnavailableError
from fixpilot.sandbox.local_executor import (
    LocalExecutor,
    UNSAFE_LOCAL_EXECUTION_WARNING,
)

logger = logging.getLogger("fixpilot.sandbox")

__all__ = [
    "DockerExecutor",
    "DockerUnavailableError",
    "LocalExecutor",
    "UNSAFE_LOCAL_EXECUTION_WARNING",
    "create_executor",
]


def create_executor(
    config: Optional[Dict[str, Any]] = None,
    executor: Optional[Any] = None,
):
    """Select the executor used to run the target project's code.

    Policy (identical for the CLI, the dashboard and the workflow engine):

    1. An explicitly supplied ``executor`` is used as-is. This is how tests
       inject a fake runner.
    2. Docker is the default and preferred mode. When the Docker daemon is
       reachable the sandbox executor is returned.
    3. When Docker is unavailable the local runner is used **only** if the
       user explicitly enabled the unsafe option
       (``FIXPILOT_ALLOW_UNSAFE_LOCAL_EXECUTION`` or the legacy
       ``FIXPILOT_ALLOW_LOCAL_RUNNER``).
    4. Otherwise a :class:`DockerUnavailableError` is raised - FixPilot never
       silently falls back to executing untrusted code on the host.

    Args:
        config: FixPilot configuration dictionary.
        executor: Optional pre-built executor (used by tests).

    Returns:
        The executor instance to use.

    Raises:
        DockerUnavailableError: If no sandbox is available and unsafe local
            execution has not been explicitly enabled.
    """
    if executor is not None:
        return executor

    config = config or {}
    docker_exec = DockerExecutor(config)

    if docker_exec.is_available():
        logger.info("Using Docker sandbox executor for target code execution.")
        return docker_exec

    if is_unsafe_local_execution_allowed(config):
        print(UNSAFE_LOCAL_EXECUTION_WARNING)
        logger.warning(
            "Docker sandbox unavailable and unsafe local execution explicitly "
            "enabled - target code will run on this host."
        )
        return LocalExecutor(config)

    raise DockerUnavailableError(
        "Docker sandbox is unavailable and unsafe local execution is not "
        "explicitly enabled (FIXPILOT_ALLOW_UNSAFE_LOCAL_EXECUTION=false). "
        "Refusing to execute target project code on the host. Install/enable "
        "Docker, or explicitly opt in to the unsafe local runner if you trust "
        "the target code."
    )
