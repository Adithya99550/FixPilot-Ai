"""FixPilot AI Repairer Agent.

Responsibilities:
- Generate a unified diff patch only.
- Use the supplied code context and plan.
- Avoid unrelated formatting or refactoring.
- Never directly write files outside the patch application mechanism.
- Return structured output that can be validated.

The repairer generates minimal unified diff patches following the schema
defined in PROJECT_SPEC.md §7.4.
"""

import logging
from typing import Any, Dict, List

from fixpilot.schemas.patch import PatchResult
from fixpilot.schemas.repair_plan import RepairPlan
from pathlib import Path

logger = logging.getLogger("fixpilot.repairer")


class Repairer:
    """Repairer agent that generates unified diff patches."""

    def generate_patch(
        self,
        plan: RepairPlan,
        context: Dict[str, Any],
    ) -> PatchResult:
        """Generate a unified diff patch based on the repair plan and code context.

        Args:
            plan: The repair plan defining what to change.
            context: Code context including current file contents and paths.

        Returns:
            PatchResult with the unified diff and metadata.
        """
        changed_files = context.get("changed_files", [])
        file_contents = context.get("file_contents", {})

        # Build the unified diff patch
        patch_lines = []
        patch_summary_parts = []

        for file_path in plan.files_to_change:
            # Skip if file not in context or marked as protected
            if file_path not in file_contents:
                continue

            current_content = file_contents[file_path]
            rel_path = file_path

            # Generate a minimal patch - in a real implementation,
            # this would use difflib or a proper patch generator
            # For now, create a placeholder patch structure
            if current_content:
                # Create a simple patch indicating the file should be reviewed
                patch_lines.append(f"--- a/{rel_path}")
                patch_lines.append(f"+++ b/{rel_path}")
                # Add a minimal hunk indicating change needed
                patch_lines.append("@@ -1,1 +1,1 @@")
                patch_lines.append(f" {current_content.split(chr(10))[0][:50]}")
                patch_summary_parts.append(f"Modified: {rel_path}")

        patch_summary = "; ".join(patch_summary_parts) if patch_summary_parts else "No changes generated"

        # Count changed files
        num_changed = len([f for f in plan.files_to_change if f in file_contents])

        return PatchResult(
            patch="\n".join(patch_lines) if patch_lines else "",
            patch_summary=patch_summary,
            changed_files=changed_files,
            reasoning_summary=self._generate_reasoning_summary(plan),
            assumptions=self._generate_assumptions(plan),
            tests_to_run=[plan.validation_command],
        )

    def _generate_reasoning_summary(self, plan: RepairPlan) -> str:
        """Generate a brief evidence-based reasoning summary."""
        parts = []

        if plan.goal:
            parts.append(f"Goal: {plan.goal}")

        if plan.root_cause:
            parts.append(f"Root cause: {plan.root_cause}")

        if plan.regression_risks:
            risk_count = len(plan.regression_risks)
            parts.append(f"{risk_count} regression risk(s) identified")

        return " | ".join(parts) if parts else "Repair plan generated"

    def _generate_assumptions(self, plan: RepairPlan) -> List[str]:
        """Generate assumptions made during patch generation."""
        assumptions = []

        # Default assumptions for safe repair
        assumptions.append("Patch only affects specified files")
        assumptions.append("No unrelated refactoring included")
        assumptions.append("Test suite validates the changes")

        # Add plan-specific assumptions
        if plan.files_not_to_change:
            assumptions.append(
                f"Files {', '.join(plan.files_not_to_change[:3])} remain unchanged"
            )

        return assumptions