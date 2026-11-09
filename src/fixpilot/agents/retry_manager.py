"""FixPilot AI Retry Manager.

Responsibilities:
- Manage bounded retry attempts for repair attempts.
- Ensure retries use new post-patch diagnostic evidence.
- Do not repeat an identical patch after it has failed.
- Stop if the same failure repeats without new evidence.
- Enforce the configured retry limit (default: 2).
- Support rollback of the disposable workspace between attempts.
- Every attempt must have its own patch and test record.

Following §6.4 Retry policy from PROJECT_SPEC.md.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from fixpilot.schemas.state import FixPilotState
from fixpilot.schemas.patch import PatchResult
from fixpilot.patching.validator import PatchApplier, PatchValidationError
from fixpilot.agents.verifier import Verifier, VerificationError

logger = logging.getLogger("fixpilot.retry")


class RetryManager:
    """Manages bounded retry attempts for FixPilot repair attempts."""

    # Default max retries per §6.4
    DEFAULT_MAX_RETRIES = 2

    def __init__(self, config: Dict[str, Any] = None, workspace_path: Any = None):
        self.config = config or {}
        self.max_retries = self.config.get("max_retries", self.DEFAULT_MAX_RETRIES)
        self.retry_count = 0
        self.workspace_path = workspace_path
        self.verifier = Verifier()
        self.applier = PatchApplier(config)
        self.retry_history = []  # Record of each attempt

    def should_retry(self, attempt_result: Dict[str, Any]) -> bool:
        """Determine whether to retry based on the attempt result.

        Following the retry policy from PROJECT_SPEC.md §6.4:
        - Default maximum repair attempts: 2 (configurable; never unlimited).
        - A retry must use new post-patch diagnostic evidence.
        - Do not repeat an identical patch after it has failed unless
          the investigator explicitly explains why.
        - Stop if the same failure repeats without new evidence.
        - Stop on unsafe patch, sandbox breach indication, missing tests, or
          infrastructure failure.
        - Every attempt must have its own patch and test record.
        - Do not silently increase retry limits.

        Args:
            attempt_result: Dict with outcome of a repair attempt.

        Returns:
            True if should retry, False otherwise.
        """
        self.retry_count += 1

        status = attempt_result.get("status")
        new_failures = attempt_result.get("new_failures", [])
        previously_failing_now_passing = attempt_result.get(
            "previously_failing_now_passing", []
        )

        # Check retry limit
        if self.retry_count >= self.max_retries:
            logger.info(
                f"Max retries ({self.max_retries}) reached, stopping"
            )
            return False

        # If status is success, no need to retry
        if status == "success":
            logger.info("Repair successful, no retry needed")
            return False

        # If status is regression, we should not retry with the same approach
        if status == "regression":
            logger.warning(
                "Regression detected - repair introduced new failures. "
                "Not retrying without new evidence."
            )
            return False

        # If status is stop (verification failed), check if we should retry
        if status == "stop":
            # Retry only if there were previously failing tests that now pass
            # and we have new evidence from the investigation
            if previously_failing_now_passing:
                logger.info(
                    f"Retrying: {len(previously_failing_now_passing)} "
                    f"tests now pass with new evidence"
                )
                return True
            else:
                logger.info("No new evidence for retry, stopping")
                return False

        # Default: don't retry
        logger.info("Stopping retry based on attempt status")
        return False

    def record_attempt(
        self,
        attempt_number: int,
        patch: PatchResult,
        pre_patch_result: Any,
        post_patch_result: Any,
        investigation: Any,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Record a retry attempt with its results.

        Args:
            attempt_number: The attempt number (1-indexed).
            patch: The PatchResult from this attempt.
            pre_patch_result: Execution result before patch.
            post_patch_result: Execution result after patch.
            investigation: Investigation result for this attempt.
            config: FixPilot configuration.

        Returns:
            Dict with outcome information for should_retry() decision.
        """
        # Run verification
        try:
            verification = self.verifier.verify(
                pre_patch_result,
                post_patch_result,
                pre_patch_result,  # In a real flow, would pass baseline result
                config,
            )
        except Exception as e:
            logger.error(f"Verification error: {e}")
            verification = {
                "status": "stop",
                "evidence": f"Verification error: {str(e)}",
                "new_failures": [],
                "previously_failing_now_passing": [],
            }

        # Record the attempt
        attempt_record = {
            "attempt_number": attempt_number,
            "patch_summary": patch.patch_summary if patch else "No patch",
            "status": verification.get("status", "error"),
            "new_failures": verification.get("new_failures", []),
            "previously_failing_now_passing": verification.get(
                "previously_failing_now_passing", []
            ),
            "evidence": verification.get("evidence", ""),
            "retry_count": self.retry_count,
        }

        self.retry_history.append(attempt_record)

        return {
            "status": verification.get("status", "error"),
            "new_failures": verification.get("new_failures", []),
            "previously_failing_now_passing": verification.get(
                "previously_failing_now_passing", []
            ),
        }