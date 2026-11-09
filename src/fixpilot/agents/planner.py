"""FixPilot AI Planner Agent.

Responsibilities:
- Convert investigation into a repair plan.
- Define files to change, intended behavior, risks, and validation steps.
- Reject plans that are too broad, unsupported, or unsafe.
- Keep repair scope limited.

The planner analyzes investigation results and produces a structured
repair plan following the schema defined in PROJECT_SPEC.md §7.3.
"""

import logging
from typing import Any, Dict, List

from fixpilot.schemas.repair_plan import RepairPlan
from fixpilot.schemas.investigation import InvestigationResult, RootCauseHypothesis

logger = logging.getLogger("fixpilot.planner")


class Planner:
    """Planner agent that converts investigation into repair plans."""

    def create_plan(
        self,
        investigation: InvestigationResult,
        config: Dict[str, Any],
    ) -> RepairPlan:
        """Create a repair plan from an investigation result.

        Args:
            investigation: The investigation result containing hypotheses and evidence.
            config: FixPilot configuration dictionary.

        Returns:
            RepairPlan with defined repair steps and constraints.
        """
        # Extract the most confident hypothesis or use investigation summary
        hypothesis = investigation.root_cause_hypotheses[0] if investigation.root_cause_hypotheses else None

        # Determine files to change based on investigation evidence
        files_to_change = self._identify_files_to_change(investigation, hypothesis)

        # Files that should NOT be changed (protected paths)
        files_not_to_change = self._identify_protected_files(investigation, config)

        # Build repair steps based on the hypothesis
        steps = self._build_repair_steps(investigation, hypothesis)

        # Determine expected behavior
        expected_behavior = self._determine_expected_behavior(investigation)

        # Identify regression risks
        regression_risks = self._identify_regression_risks(investigation, hypothesis)

        # Build validation command
        validation_command = config.get("test_command", "python -m pytest -q")

        # Build rollback strategy
        rollback_strategy = self._build_rollback_strategy(investigation)

        # Create approval summary
        approval_summary = self._build_approval_summary(investigation)

        return RepairPlan(
            goal=self._determine_goal(investigation),
            root_cause=self._extract_root_cause(investigation, hypothesis),
            steps=steps,
            files_to_change=files_to_change,
            files_not_to_change=files_not_to_change,
            expected_behavior=expected_behavior,
            regression_risks=regression_risks,
            validation_command=validation_command,
            rollback_strategy=rollback_strategy,
            approval_summary=approval_summary,
        )

    def _identify_files_to_change(
        self, investigation: InvestigationResult, hypothesis: RootCauseHypothesis
    ) -> List[str]:
        """Identify which files need to be changed."""
        files = []

        # Use affected_files from investigation if available
        for f in investigation.affected_files:
            if f not in files:
                files.append(f)

        # Add files from hypotheses
        if hypothesis and hypothesis.affected_files:
            for f in hypothesis.affected_files:
                if f not in files:
                    files.append(f)

        return files

    def _identify_protected_files(
        self, investigation: InvestigationResult, config: Dict[str, Any]
    ) -> List[str]:
        """Identify files that should NOT be changed."""
        # Default protected files per spec §8.2
        protected = [
            ".env",
            ".git",
            "fixpilot.toml",
            "Dockerfile.sandbox",
            ".fixpilot",
        ]

        # Add config-specified exclusions
        exclusions = config.get("exclude", [])
        protected.extend(exclusions)

        return protected

    def _build_repair_steps(
        self, investigation: InvestigationResult, hypothesis: RootCauseHypothesis
    ) -> List[str]:
        """Build the list of repair steps."""
        steps = []

        if hypothesis:
            # Add a step to fix the identified issue
            explanation = hypothesis.explanation
            steps.append(
                f"Address the root cause: {explanation}"
            )

            # Add validation step
            steps.append("Run the test suite to verify the fix")

        # Always include a verification step
        steps.append("Verify that all tests pass")

        return steps

    def _determine_expected_behavior(
        self, investigation: InvestigationResult
    ) -> str:
        """Determine the expected behavior after the fix."""
        # Use the investigation summary as a basis
        summary = investigation.summary

        # Try to extract expected behavior from the test context
        # If no specific info, use a generic description
        if "failed" in summary.lower():
            return "All tests pass successfully"
        return summary

    def _identify_regression_risks(
        self, investigation: InvestigationResult, hypothesis: RootCauseHypothesis
    ) -> List[str]:
        """Identify potential regression risks."""
        risks = []

        # Common regression risks for Python projects
        risks.append("May affect other tests using similar patterns")
        risks.append("Change may have unintended side effects on related functionality")

        # Add hypothesis-specific risks
        if hypothesis:
            explanation = hypothesis.explanation.lower()
            if "type" in explanation:
                risks.append("Type change may affect other type-dependent operations")
            if "loop" in explanation or "boundary" in explanation:
                risks.append("Loop boundary change may affect iteration counts")

        return risks

    def _build_rollback_strategy(self, investigation: InvestigationResult) -> str:
        """Build a rollback strategy description."""
        return (
            "Restore the disposable workspace from the pre-patch snapshot. "
            "Never modify the original target repository. "
            "Use git checkout or file backup restoration."
        )

    def _build_approval_summary(self, investigation: InvestigationResult) -> str:
        """Build an approval summary for the patch."""
        summary_parts = []

        if investigation.root_cause_hypotheses:
            h = investigation.root_cause_hypotheses[0]
            summary_parts.append(
                f"Hypothesis: {h.explanation} (confidence: {h.confidence})"
            )

        summary_parts.append(
            f"Recommended action: {investigation.recommended_next_action}"
        )

        return " | ".join(summary_parts) if summary_parts else "No investigation data available"

    def _determine_goal(self, investigation: InvestigationResult) -> str:
        """Determine the repair goal from the investigation."""
        if investigation.root_cause_hypotheses:
            return f"Fix the failing test: {investigation.root_cause_hypotheses[0].explanation}"
        return "Resolve failing tests and restore passing state"

    def _extract_root_cause(
        self, investigation: InvestigationResult, hypothesis: RootCauseHypothesis
    ) -> str:
        """Extract the root cause string."""
        if hypothesis:
            return hypothesis.explanation
        if investigation.root_cause_hypotheses:
            return investigation.root_cause_hypotheses[0].explanation
        return "Unknown - investigation pending"