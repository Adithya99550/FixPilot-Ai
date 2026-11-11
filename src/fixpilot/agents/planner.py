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
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fixpilot.schemas.repair_plan import RepairPlan
from fixpilot.schemas.investigation import InvestigationResult, RootCauseHypothesis
from fixpilot.languages import get_language_config

logger = logging.getLogger("fixpilot.planner")


class Planner:
    """Planner agent that converts investigation into repair plans."""

    def create_plan(
        self,
        investigation: InvestigationResult,
        config: Dict[str, Any],
        workspace_path: Optional[Path] = None,
    ) -> RepairPlan:
        """Create a repair plan from an investigation result.

        Args:
            investigation: The investigation result containing hypotheses and evidence.
            config: FixPilot configuration dictionary.
            workspace_path: Optional workspace path to resolve source files.

        Returns:
            RepairPlan with defined repair steps and constraints.
        """
        # Get language and test framework from config
        language = config.get("language", config.get("FIXPILOT_LANGUAGE", "python"))
        test_framework = config.get("test_framework", config.get("FIXPILOT_TEST_FRAMEWORK", ""))

        # Extract the most confident hypothesis or use investigation summary
        hypothesis = investigation.root_cause_hypotheses[0] if investigation.root_cause_hypotheses else None

        # Determine files to change based on investigation evidence
        files_to_change = self._identify_files_to_change(investigation, hypothesis, workspace_path)

        # Files that should NOT be changed (protected paths)
        files_not_to_change = self._identify_protected_files(investigation, config)

        # Build repair steps based on the hypothesis
        steps = self._build_repair_steps(investigation, hypothesis, language)

        # Determine expected behavior
        expected_behavior = self._determine_expected_behavior(investigation)

        # Identify regression risks (language-aware)
        regression_risks = self._identify_regression_risks(investigation, hypothesis, language, test_framework)

        # Build validation command
        validation_command = config.get("test_command", self._get_default_test_command(language, test_framework))

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
            language=language,
            test_framework=test_framework,
        )

    def _get_default_test_command(self, language: str, test_framework: str) -> str:
        """Get default test command for language/framework."""
        defaults = {
            "python": "python -m pytest -q",
            "javascript": "npm test -- --passWithNoTests",
            "typescript": "npm test -- --passWithNoTests",
            "go": "go test ./...",
            "rust": "cargo test",
            "java": "mvn test",
        }
        if test_framework:
            if test_framework == "jest":
                return "npm test -- --passWithNoTests"
            elif test_framework == "mocha":
                return "npm test"
            elif test_framework == "pytest":
                return "python -m pytest -q"
            elif test_framework == "go test":
                return "go test ./..."
            elif test_framework == "cargo test":
                return "cargo test"
            elif test_framework in ("junit", "maven", "gradle"):
                return "mvn test" if test_framework != "gradle" else "gradle test"
        return defaults.get(language, "python -m pytest -q")

    def _identify_files_to_change(
        self,
        investigation: InvestigationResult,
        hypothesis: RootCauseHypothesis,
        workspace_path: Optional[Path] = None,
    ) -> List[str]:
        """Identify which files need to be changed.

        Maps test files to their source counterparts so the repairer
        targets the production code, not the test assertions.
        """
        files = []
        candidate_files = []

        # Use affected_files from investigation if available
        for f in investigation.affected_files:
            if f not in candidate_files:
                candidate_files.append(f)

        # Add files from hypotheses
        if hypothesis and hypothesis.affected_files:
            for f in hypothesis.affected_files:
                if f not in candidate_files:
                    candidate_files.append(f)

        # Map test files to source files
        for f in candidate_files:
            mapped = _map_test_to_source(f, workspace_path)
            if mapped and mapped not in files:
                files.append(mapped)
            elif not _is_test_filename(f) and f not in files:
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

        # Explicitly protect all test files so tests are never modified
        for f in investigation.affected_files:
            if _is_test_filename(f) and f not in protected:
                protected.append(f)

        # Add config-specified exclusions
        exclusions = config.get("exclude", [])
        protected.extend(exclusions)

        return protected

    def _build_repair_steps(
        self, investigation: InvestigationResult, hypothesis: RootCauseHypothesis, language: str
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
        self, investigation: InvestigationResult, hypothesis: RootCauseHypothesis, language: str, test_framework: str
    ) -> List[str]:
        """Identify potential regression risks (language-aware)."""
        risks = []

        # Language-specific common regression risks
        if language == "python":
            risks.append("May affect other tests using similar patterns")
            risks.append("Change may have unintended side effects on related functionality")
        elif language in ("javascript", "typescript"):
            risks.append("May affect other tests using similar async patterns or mocks")
            risks.append("Type changes may affect TypeScript compilation")
            risks.append("Jest snapshot tests may need updating")
        elif language == "go":
            risks.append("May affect other tests sharing test fixtures or helpers")
            risks.append("Interface changes may break implementing types")
        elif language == "rust":
            risks.append("May affect other tests using similar traits or macros")
            risks.append("Borrow checker changes may cascade to dependent code")
        elif language == "java":
            risks.append("May affect other tests using similar test utilities or mocks")
            risks.append("Refactoring may break binary compatibility")
        else:
            risks.append("May affect other tests using similar patterns")
            risks.append("Change may have unintended side effects on related functionality")

        # Add hypothesis-specific risks
        if hypothesis:
            explanation = hypothesis.explanation.lower()
            if "type" in explanation:
                risks.append("Type change may affect other type-dependent operations")
            if "loop" in explanation or "boundary" in explanation:
                risks.append("Loop boundary change may affect iteration counts")
            if "async" in explanation or "await" in explanation:
                risks.append("Async behavior change may affect concurrency")
            if "null" in explanation or "none" in explanation:
                risks.append("Null/None handling change may affect callers")

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


# --- Test-to-source mapping helpers ---

_TEST_FILE_PATTERNS = [
    # (test file regex, source file transformation)
    (re.compile(r"^(.+?)_test\.go$"), r"\1.go"),
    (re.compile(r"^(.+?)_test\.rs$"), r"\1.rs"),
    (re.compile(r"^(.+?)Test\.java$"), r"\1.java"),
    (re.compile(r"^(.+?)\.test\.js$"), r"\1.js"),
    (re.compile(r"^(.+?)\.spec\.js$"), r"\1.js"),
    (re.compile(r"^(.+?)\.test\.ts$"), r"\1.ts"),
    (re.compile(r"^(.+?)\.spec\.ts$"), r"\1.ts"),
    (re.compile(r"^test_(.+?)\.py$"), r"\1.py"),
    (re.compile(r"^(.+?)_test\.py$"), r"\1.py"),
]


def _is_test_filename(path_str: str) -> bool:
    """Check if a path corresponds to a test file."""
    normalized = path_str.replace("\\", "/").lower()
    filename = normalized.rsplit("/", 1)[-1]
    return (
        filename.startswith("test_")
        or filename.endswith("_test.py")
        or filename.endswith(".test.js")
        or filename.endswith(".spec.js")
        or filename.endswith(".test.ts")
        or filename.endswith(".spec.ts")
        or "/test/" in normalized
        or "/tests/" in normalized
        or normalized.startswith("tests/")
        or normalized.startswith("test/")
    )


def _map_test_to_source(test_path: str, workspace_path: Optional[Path] = None) -> Optional[str]:
    """Map a test file path to its likely source file counterpart.

    Returns None if no mapping can be determined.
    """
    if not test_path:
        return None

    normalized = test_path.replace("\\", "/")
    filename = normalized.rsplit("/", 1)[-1]
    source_name = None

    for pattern, replacement in _TEST_FILE_PATTERNS:
        match = pattern.match(filename)
        if match:
            source_name = pattern.sub(replacement, filename)
            break

    if not source_name:
        return None

    # Candidate source locations
    candidates = [source_name, f"src/{source_name}"]
    dir_part = normalized.rsplit("/", 1)[0] if "/" in normalized else ""
    if dir_part and dir_part not in ("tests", "test", "__tests__", "spec", "specs"):
        clean_dir = re.sub(r"^(tests?|__tests__|specs?)/?", "", dir_part)
        if clean_dir:
            candidates.append(f"{clean_dir}/{source_name}")
            candidates.append(f"src/{clean_dir}/{source_name}")

    if workspace_path:
        ws = Path(workspace_path)
        for cand in candidates:
            if (ws / cand).exists():
                return cand

    return candidates[0]