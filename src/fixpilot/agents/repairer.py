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
import re
from typing import Any, Dict, List, Optional
from pathlib import Path

from fixpilot.schemas.patch import PatchResult
from fixpilot.schemas.repair_plan import RepairPlan
from fixpilot.llm.provider import BaseLLMProvider, LLMProviderError

logger = logging.getLogger("fixpilot.repairer")


class Repairer:
    """Repairer agent that generates unified diff patches."""

    def __init__(self, llm_provider: Optional[BaseLLMProvider] = None):
        """Initialize repairer with optional LLM provider."""
        self.llm_provider = llm_provider

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
        changed_files = context.get("changed_files", plan.files_to_change)
        file_contents = context.get("file_contents", {})

        if self.llm_provider:
            try:
                patch = self._generate_patch_with_llm(plan, file_contents)
                if patch:
                    return PatchResult(
                        patch=patch,
                        patch_summary=f"LLM generated repair for {', '.join(plan.files_to_change)}",
                        changed_files=changed_files,
                        reasoning_summary=self._generate_reasoning_summary(plan),
                        root_cause_summary=str(plan.root_cause),
                        assumptions=self._generate_assumptions(plan),
                        tests_to_run=[plan.validation_command],
                        approval_status="pending",
                    )
            except Exception as e:
                logger.warning(f"LLM patch generation failed: {e}. Falling back.")

        # Fallback heuristic / minimal patch structure
        patch_lines = []
        patch_summary_parts = []

        for file_path in plan.files_to_change:
            if file_path not in file_contents:
                continue

            current_content = file_contents[file_path]
            rel_path = file_path

            if current_content:
                patch_lines.append(f"--- a/{rel_path}")
                patch_lines.append(f"+++ b/{rel_path}")
                patch_lines.append("@@ -1,1 +1,1 @@")
                first_line = current_content.split("\n")[0][:60]
                patch_lines.append(f" {first_line}")
                patch_summary_parts.append(f"Reviewed: {rel_path}")

        patch_summary = "; ".join(patch_summary_parts) if patch_summary_parts else "No changes generated"

        return PatchResult(
            patch="\n".join(patch_lines) if patch_lines else "",
            patch_summary=patch_summary,
            changed_files=changed_files,
            reasoning_summary=self._generate_reasoning_summary(plan),
            root_cause_summary=str(plan.root_cause),
            assumptions=self._generate_assumptions(plan),
            tests_to_run=[plan.validation_command],
            approval_status="pending",
        )

    def _generate_patch_with_llm(
        self,
        plan: RepairPlan,
        file_contents: Dict[str, str],
    ) -> str:
        """Prompt the LLM to generate a minimal unified diff patch."""
        prompt = (
            "You are FixPilot Repairer, an expert autonomous debugging agent.\n"
            "Generate a minimal, precise unified diff patch that repairs the failure without refactoring or modifying unrelated code.\n\n"
            f"GOAL: {plan.goal}\n"
            f"ROOT CAUSE: {plan.root_cause}\n"
            f"STEPS:\n" + "\n".join(f"- {s}" for s in plan.steps) + "\n\n"
            f"FILES TO CHANGE: {', '.join(plan.files_to_change)}\n"
            f"FILES NOT TO CHANGE: {', '.join(plan.files_not_to_change)}\n\n"
            "SOURCE FILES:\n"
        )

        for fpath, content in file_contents.items():
            prompt += f"--- File: {fpath} ---\n{content}\n\n"

        prompt += (
            "REQUIREMENTS:\n"
            "1. Output ONLY a standard unified diff format (starts with `--- a/<file>` and `+++ b/<file>`).\n"
            "2. Do not include markdown code block backticks (no ```diff).\n"
            "3. Make the minimal necessary change to fix the failing tests.\n"
        )

        raw = self.llm_provider.generate(prompt)

        # Clean markdown code blocks if the LLM wrapped it
        clean = re.sub(r"^```(?:diff)?\s*", "", raw.strip(), flags=re.MULTILINE)
        clean = re.sub(r"\s*```$", "", clean.strip(), flags=re.MULTILINE)
        return clean.strip()

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