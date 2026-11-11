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
from typing import Any, Dict

from fixpilot.schemas.execution import ExecutionResult
from fixpilot.diagnostics import PARSER_REGISTRY

logger = logging.getLogger("fixpilot.verifier")


class VerificationError(Exception):
    """Raised when verification encounters an error."""
    pass


class Verifier:
    """Verifier agent that compares test results before and after patch application."""

    def _get_parser(self, config: Dict[str, Any]):
        """Get the appropriate diagnostic parser for the language/framework."""
        language = config.get("language", config.get("FIXPILOT_LANGUAGE", "python"))
        test_framework = config.get("test_framework", config.get("FIXPILOT_TEST_FRAMEWORK", ""))

        if language and test_framework:
            parser = PARSER_REGISTRY.get_parser(language, test_framework)
            if parser:
                return parser

        # Fallback to pytest parser
        from fixpilot.diagnostics.pytest_parser import PytestParser
        return PytestParser()

    def _parse_failures(self, stdout: str, stderr: str, config: Dict[str, Any]):
        """Parse test failures using the appropriate parser."""
        parser = self._get_parser(config)
        return parser.parse(stdout, stderr)

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

        # Parse test results using appropriate parser
        post_failures = self._parse_failures(post_patch_result.stdout, post_patch_result.stderr, config)
        baseline_failures = self._parse_failures(
            baseline_result.stdout, baseline_result.stderr, config
        )

        # Get sets of test names
        post_test_names = {f.failing_test for f in post_failures if f.failing_test}
        baseline_test_names = {f.failing_test for f in baseline_failures if f.failing_test}

        # Criterion 2: Previously failing tests now pass
        # Tests that were in baseline but not in post_patch are now passing
        previously_failing_now_passing = baseline_test_names - post_test_names

        # Criterion 3: No new failures relative to baseline
        # New failures = tests failing in post_patch that weren't in baseline
        new_failures = post_test_names - baseline_test_names

        # The strongest possible evidence: the whole suite passed after the
        # repair. This is checked first because a parser may be unable to
        # extract individual test names from the output.
        if post_patch_result.exit_code == 0:
            return {
                "status": "success",
                "evidence": (
                    "All tests pass after the repair (exit code 0). "
                    "Previously failing tests: {0}".format(
                        len(previously_failing_now_passing)
                        or len(baseline_test_names)
                    )
                ),
                "new_failures": [],
                "previously_failing_now_passing": list(previously_failing_now_passing),
            }

        # The test suite could not even be executed (collection error, usage
        # error, internal error, ...). This is NOT a regression: the tests
        # never ran, so nothing can be compared. It usually means the patch
        # itself broke the file (for example a wrong indentation).
        if post_patch_result.exit_code != 1:
            return {
                "status": "stop",
                "failure_kind": "suite_not_executed",
                "evidence": (
                    "The test suite could not be executed after the patch "
                    "(exit code {0}). The patch itself is the likely cause - "
                    "the tests never ran, so no comparison is possible.".format(
                        post_patch_result.exit_code
                    )
                ),
                "new_failures": [],
                "previously_failing_now_passing": [],
            }

        # Decision logic
        if new_failures:
            # Has new failures - check if they're acceptable
            # Check config for acceptable new failures
            acceptable_new = set(config.get("acceptable_new_failures", []) or [])

            # If there are new failures not in the acceptable list, it's a regression
            unacceptable_new = new_failures - acceptable_new

            if unacceptable_new:
                return {
                    "status": "regression",
                    "failure_kind": "new_failures",
                    "evidence": "New failures introduced: {0}. Regression detected - repair introduced new issues.".format(
                        ', '.join(sorted(unacceptable_new))
                    ),
                    "new_failures": list(unacceptable_new),
                    "previously_failing_now_passing": list(previously_failing_now_passing),
                }

            # The new failures are acceptable. The repair is only successful
            # when the originally failing tests now pass as well.
            if previously_failing_now_passing or not baseline_test_names:
                return {
                    "status": "success",
                    "evidence": (
                        "Original tests now pass. New failures are acceptable: "
                        "{0}".format(', '.join(sorted(new_failures)))
                    ),
                    "new_failures": list(new_failures),
                    "previously_failing_now_passing": list(previously_failing_now_passing),
                }

            return {
                "status": "stop",
                "evidence": (
                    "The originally failing tests still fail. New failures "
                    "({0}) are acceptable but no progress was made.".format(
                        ', '.join(sorted(new_failures))
                    )
                ),
                "new_failures": list(new_failures),
                "previously_failing_now_passing": list(previously_failing_now_passing),
            }

        # Criterion 2 check: Were the original failing tests resolved?
        remaining_failing = baseline_test_names - previously_failing_now_passing

        if previously_failing_now_passing and not remaining_failing:
            # The originally failing tests now pass, and no new failures
            return {
                "status": "success",
                "evidence": "Originally failing tests now pass: {0}. No new failures introduced.".format(
                    ', '.join(sorted(previously_failing_now_passing))
                ),
                "new_failures": [],
                "previously_failing_now_passing": list(previously_failing_now_passing),
            }

        # Partial progress: some originally failing tests now pass while
        # others still fail, and no new failures were introduced. There is
        # new evidence to work with, so a bounded retry is worthwhile.
        if previously_failing_now_passing and not new_failures:
            return {
                "status": "partial",
                "failure_kind": "partial_progress",
                "evidence": (
                    "Partial progress: {0} now pass, {1} still failing. "
                    "No new failures introduced - retrying with updated diagnostics.".format(
                        len(previously_failing_now_passing), len(remaining_failing)
                    )
                ),
                "new_failures": [],
                "previously_failing_now_passing": list(previously_failing_now_passing),
            }

        return {
            "status": "stop",
            "evidence": f"Repair not verified. Original tests still failing: {len(remaining_failing)}, New failures: {len(new_failures)}",
            "new_failures": list(new_failures) if new_failures else [],
            "previously_failing_now_passing": list(previously_failing_now_passing),
        }