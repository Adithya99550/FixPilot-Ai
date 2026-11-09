"""FixPilot AI Verifier Agent.

Responsibilities:
- Compare pre-patch and post-patch results.
- Determine whether the original failing tests now pass.
- Detect new failures/regressions.
- Enforce success criteria.
- Decide retry, success, or stop.

Following §6.5 and §6.4 of PROJECT_SPEC.md for verification criteria.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from fixpilot.schemas.execution import ExecutionResult
from fixpilot.schemas.state import FixPilotState
from fixpilot.diagnostics.pytest_parser import parse_pytest_output

logger = logging.getLogger("fixpalot.verifier")


class VerificationError(Exception):
    """Raised when verification encounters an error."""
    pass


class Verifier:
    """Verifier agent that compares test results before and after patch application."""

    def verify(
        self,
        pre_patch_result: ExecutionResult,
        post_patch_result: ExecutionResult,
        baseline_result: ExecutionResult,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Verify whether a repair was successful.

        Following the repair success criteria from PROJECT_SPEC.md §6.5:
        1. The test command completed normally (not timed out or infrastructure-failed).
        2. Previously failing tests pass.
        3. No new test failures are introduced relative to baseline.
        4. The verifier records objective test evidence.
        5. The patch applied successfully to the isolated working copy.

        Args:
            pre_patch_result: Execution result before patch application.
            post_patch_result: Execution result after patch application.
            baseline_result: Execution result from baseline (before any failures).
            config: FixPilot configuration dictionary.

        Returns:
            Dict with verification outcome:
            - status: "success" | "retry" | "stop" | "regression"
            - evidence: Description of verification results
            - new_failures: List of newly failing tests
            - previously_failing_now_passing: List of tests that now pass
        """
        # Check criterion 1: Test command completed normally
        timeout_ok = not pre_patch_result.timed_out and not post_patch_result.timed_out
        infrastructure_ok = pre_patch_result.exit_code != -1 and post_patch_result.exit_code != -1

        if not timeout_ok:
            return {
                "status": "stop",
                "evidence": "Test suite timed out - cannot verify repair",
                "new_failures": [],
                "previously_failing_now_passing": [],
            }

        if not infrastructure_ok:
            return {
                "status": "stop",
                "evidence": "Infrastructure failure detected - cannot verify repair",
                "new_failures": [],
                "previously_failing_now_passing": [],
            }

        # Parse test results
        pre_failures = parse_pytest_output(pre_patch_result.stdout, pre_patch_result.stderr)
        post_failures = parse_pytest_output(post_patch_result.stdout, post_patch_result.stderr)
        baseline_failures = parse_pytest_output(
            baseline_result.stdout, baseline_result.stderr
        )

        # Get sets of test names
        pre_test_names = {f.failing_test for f in pre_failures if f.failing_test}
        post_test_names = {f.failing_test for f in post_failures if f.failing_test}
        baseline_test_names = {f.failing_test for f in baseline_failures if f.failing_test}

        # Criterion 2: Previously failing tests now pass
        # Tests that were in baseline but not in post_patch are now passing
        previously_failing_now_passing = baseline_test_names - post_test_names

        # Criterion 3: No new failures relative to baseline
        # New failures = tests failing in post_patch that weren't in baseline
        new_failures = post_test_names - baseline_test_names

        # Also check for regression: tests that passed baseline but fail post-patch
        # (these are tests that were passing before and now fail)
        regression_tests = pre_test_names - baseline_test_names

        # Decision logic
        if new_failures:
            # Has new failures - check if they're acceptable
            # Check config for acceptable new failures
            acceptable_new = config.get("acceptable_new_failures", [])

            # If there are new failures not in the acceptable list, it's a regression
            unacceptable_new = new_failures - set(acceptable_new) if acceptable_new else new_failures

            if unacceptable_new:
                return {
                    "status": "regression",
                    "evidence": "New failures introduced: {0}. Regression detected - repair introduced new issues.".format(
                        ', '.join(unacceptable_new)
                    ),
                    "new_failures": list(unacceptable_new),
                    "previously_failing_now_passing": list(previously_failing_now_passing),
                }

            # New failures are acceptable, check if original tests still fail
            if not new_failures - set(acceptable_new) if acceptable_new else []:
                # All failures are new, original tests now pass
                return {
                    "status": "success",
                    "evidence": "Original tests now pass. New failures are acceptable.".format(
                        ', '.join(new_failures)
                    ),
                    "new_failures": list(new_failures),
                    "previously_failing_now_passing": list(previously_failing_now_passing),
                }

        # Criterion 2 check: Were the original failing tests resolved?
        original_tests_now_passing = baseline_test_names - post_test_names

        if original_tests_now_passing and not new_failures:
            # The originally failing tests now pass, and no new failures
            return {
                "status": "success",
                "evidence": "Originally failing tests now pass: {0}. No new failures introduced.".format(
                    ', '.join(original_tests_now_passing)
                ),
                "new_failures": [],
                "previously_failing_now_passing": list(original_tests_now_passing),
            }

        # If we get here, the original tests still fail and/or there are new failures
        # that are not acceptable
        remaining_failing_count = len(baseline_test_names - previously_failing_now_passing)
        return {
            "status": "stop",
            "evidence": f"Repair not verified. Original tests still failing: {remaining_failing_count}, New failures: {len(new_failures)}",
            "new_failures": list(new_failures) if new_failures else [],
            "previously_failing_now_passing": list(previously_failing_now_passing),
        }