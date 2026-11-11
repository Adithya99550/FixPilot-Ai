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
from typing import Any, Dict, Optional

from fixpilot.schemas.patch import PatchResult
from fixpilot.patching.validator import PatchApplier
from fixpilot.agents.verifier import Verifier

logger = logging.getLogger("fixpilot.retry")


class RetryManager:
    """Manages bounded retry attempts for FixPilot repair attempts."""

    # Default max retries per §6.4
    DEFAULT_MAX_RETRIES = 2

    def __init__(self, config: Dict[str, Any] = None, workspace_path: Any = None):
        self.config = config or {}
        # Accept both the plain key and the environment-style key used by
        # fixpilot.config.get_config().
        self.max_retries = self.config.get(
            "max_retries",
            self.config.get("FIXPILOT_MAX_RETRIES", self.DEFAULT_MAX_RETRIES),
        )
        self.retry_count = 0
        self.workspace_path = workspace_path
        self.verifier = Verifier()
        self.applier = PatchApplier(config)
        self.retry_history = []  # Record of each attempt
        # Hash of every patch that was already tried, so an identical patch
        # is never applied twice.
        self.seen_patch_hashes: Dict[str, int] = {}

    def is_duplicate_patch(self, patch: PatchResult) -> bool:
        """Return True when this exact patch was already tried before."""
        if patch is None or not patch.patch:
            return False
        return PatchApplier.patch_hash(patch.patch) in self.seen_patch_hashes

    def should_retry(
        self, attempt_result: Dict[str, Any], attempt_number: Optional[int] = None
    ) -> bool:
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
            attempt_number: The 1-based number of the attempt that just
                finished. When supplied it is used for the retry budget so
                the budget has a single source of truth (the workflow
                engine owns the attempt loop).

        Returns:
            True if should retry, False otherwise.
        """
        self.retry_count += 1

        status = attempt_result.get("status")
        previously_failing_now_passing = attempt_result.get(
            "previously_failing_now_passing", []
        )

        # Check retry limit. ``max_retries`` is the maximum number of repair
        # *attempts*, so a further attempt is only allowed while the number
        # of attempts already made is below the limit.
        attempts_made = attempt_number if attempt_number is not None else self.retry_count
        if attempts_made >= self.max_retries:
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

        # If status is retry, the repair made partial progress - retry with
        # the updated diagnostics.
        if status == "retry":
            if previously_failing_now_passing:
                logger.info(
                    f"Retrying: {len(previously_failing_now_passing)} "
                    "tests now pass, retrying with updated diagnostics"
                )
                return True
            logger.info("Retry requested but no new evidence, stopping")
            return False

        # Default: don't retry
        logger.info("Stopping retry based on attempt status")
        return False

    def record_attempt(
        self,
        attempt_number: int,
        patch: PatchResult,
        pre_patch_result: Any = None,
        post_patch_result: Any = None,
        investigation: Any = None,
        config: Dict[str, Any] = None,
        verification: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record a retry attempt with its results.

        Args:
            attempt_number: The attempt number (1-indexed).
            patch: The PatchResult from this attempt.
            pre_patch_result: Execution result before patch.
            post_patch_result: Execution result after patch.
            investigation: Investigation result for this attempt.
            config: FixPilot configuration.
            verification: Pre-computed verification result. When supplied the
                verification is not re-run, which avoids double counting.

        Returns:
            Dict with outcome information for should_retry() decision.
        """
        # Run verification unless the caller already did it.
        if verification is None:
            try:
                verification = self.verifier.verify(
                    pre_patch_result,
                    post_patch_result,
                    pre_patch_result,  # In a real flow, would pass baseline result
                    config or self.config,
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
            "patch_hash": PatchApplier.patch_hash(patch.patch) if patch and patch.patch else "",
            "status": verification.get("status", "error"),
            "new_failures": verification.get("new_failures", []),
            "previously_failing_now_passing": verification.get(
                "previously_failing_now_passing", []
            ),
            "evidence": verification.get("evidence", ""),
            "retry_count": self.retry_count,
        }

        if attempt_record["patch_hash"]:
            self.seen_patch_hashes.setdefault(attempt_record["patch_hash"], attempt_number)

        self.retry_history.append(attempt_record)

        return {
            "status": verification.get("status", "error"),
            "new_failures": verification.get("new_failures", []),
            "previously_failing_now_passing": verification.get(
                "previously_failing_now_passing", []
            ),
        }