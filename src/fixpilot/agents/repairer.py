"""FixPilot AI Repairer Agent.

Responsibilities:
- Generate a unified diff patch **only**.
- Use the supplied code context and plan.
- Avoid unrelated formatting or refactoring.
- Never directly write files outside the patch application mechanism.
- Return structured output that can be validated.

The repairer generates minimal unified diff patches following the schema
defined in PROJECT_SPEC.md §7.4.

.. important::
   The repairer never fabricates a repair. If the configured LLM is missing,
   unreachable, rate limited or returns an unusable response, the repairer
   raises :class:`RepairGenerationError` so the workflow can report an honest
   failure instead of applying a no-op patch.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from fixpilot.schemas.patch import PatchResult
from fixpilot.schemas.repair_plan import RepairPlan
from fixpilot.llm.provider import BaseLLMProvider, LLMProviderError
from fixpilot.patching.validator import PatchValidationError, parse_unified_diff

logger = logging.getLogger("fixpilot.repairer")


class RepairGenerationError(Exception):
    """Raised when a repair patch could not be generated.

    This is a *hard* failure: the workflow must never continue with a
    fabricated or empty patch. ``recoverable`` marks the errors that a
    second attempt with feedback can fix (a malformed diff, an empty
    response).
    """

    def __init__(
        self,
        message: str,
        cause: Optional[BaseException] = None,
        recoverable: bool = False,
    ):
        super().__init__(message)
        self.cause = cause
        self.recoverable = recoverable


class Repairer:
    """Repairer agent that generates unified diff patches."""

    def __init__(self, llm_provider: Optional[BaseLLMProvider] = None):
        """Initialize repairer with optional LLM provider."""
        self.llm_provider = llm_provider

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_patch(
        self,
        plan: RepairPlan,
        context: Dict[str, Any],
    ) -> PatchResult:
        """Generate a unified diff patch based on the repair plan and context.

        Args:
            plan: The repair plan defining what to change.
            context: Code context including current file contents, paths and
                (optionally) the latest test output.

        Returns:
            A :class:`PatchResult` holding a validated unified diff.

        Raises:
            RepairGenerationError: If no LLM is configured, the LLM call
                fails, or the model returns something that is not a usable
                patch.
        """
        changed_files = context.get("changed_files", plan.files_to_change)

        if not self.llm_provider:
            raise RepairGenerationError(
                "No LLM provider is configured, so no repair patch could be "
                "generated. Set GEMINI_API_KEY (or FIXPILOT_MODEL) to enable "
                "patch generation."
            )

        try:
            raw_response = self.llm_provider.generate(self._build_prompt(plan, context))
        except LLMProviderError as exc:
            raise RepairGenerationError(
                self._describe_llm_error(exc), cause=exc
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive
            raise RepairGenerationError(
                f"Unexpected error while generating the repair patch: {exc}",
                cause=exc,
            ) from exc

        patch_text = self._extract_patch_text(raw_response)
        if not patch_text:
            raise RepairGenerationError(
                "The LLM returned an empty response, so no repair patch could "
                "be generated.",
                recoverable=True,
            )

        # Models frequently miscount the lines of a hunk or truncate the
        # header. The body is authoritative, so the header is normalised
        # before the patch is validated.
        patch_text = self._normalize_hunks(patch_text)

        self._validate_generated_patch(patch_text)

        return PatchResult(
            patch=patch_text,
            patch_summary=(
                f"LLM generated repair for "
                f"{', '.join(plan.files_to_change) or 'unknown files'}"
            ),
            changed_files=list(changed_files),
            reasoning_summary=self._generate_reasoning_summary(plan),
            root_cause_summary=str(plan.root_cause),
            assumptions=self._generate_assumptions(plan),
            tests_to_run=[plan.validation_command],
            approval_status="pending",
            validation_passed=True,
        )

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        plan: RepairPlan,
        context: Dict[str, Any],
    ) -> str:
        """Build the LLM prompt for patch generation."""
        file_contents = context.get("file_contents", {})
        language = getattr(plan, "language", "python") or "python"
        test_framework = getattr(plan, "test_framework", "")
        lang_guidance = self._get_language_guidance(language, test_framework)

        prompt = (
            "You are FixPilot Repairer, an expert autonomous debugging agent.\n"
            "Generate a minimal, precise unified diff patch that repairs the "
            "failure without refactoring or modifying unrelated code.\n\n"
            f"GOAL: {plan.goal}\n"
            f"ROOT CAUSE: {plan.root_cause}\n"
            f"LANGUAGE: {language}"
        )

        if test_framework:
            prompt += f"\nTEST FRAMEWORK: {test_framework}"

        prompt += (
            "\nSTEPS:\n" + "\n".join(f"- {s}" for s in plan.steps) + "\n\n"
            f"FILES TO CHANGE: {', '.join(plan.files_to_change)}\n"
            f"FILES NOT TO CHANGE: {', '.join(plan.files_not_to_change)}\n\n"
        )

        # The latest test output is critical context for the repair.
        latest_output = context.get("test_output") or ""
        if latest_output:
            prompt += (
                "LATEST TEST OUTPUT (after the previous repair attempt):\n"
                f"{latest_output[-8000:]}\n\n"
            )

        latest_diagnostics = context.get("diagnostics") or {}
        failing_test = latest_diagnostics.get("failing_test")
        if failing_test:
            prompt += f"CURRENTLY FAILING TEST: {failing_test}\n\n"

        prompt += "SOURCE FILES:\n"
        for fpath, content in file_contents.items():
            prompt += f"--- File: {fpath} ---\n{content}\n\n"

        prompt += (
            "REQUIREMENTS:\n"
            "1. Output ONLY a standard unified diff format (starts with "
            "`--- a/<file>` and `+++ b/<file>`).\n"
            "2. Do not include markdown code block backticks (no ```diff).\n"
            "3. Make the minimal necessary change to fix the failing tests.\n"
            "4. The diff must contain at least one added or removed line.\n"
            "5. Every hunk header must look exactly like "
            "`@@ -<line>,<count> +<line>,<count> @@` and every context line "
            "must be copied *exactly* from the source file - including its "
            "indentation.\n"
        )

        feedback = context.get("feedback")
        if feedback:
            prompt += (
                "\nIMPORTANT: your previous answer could not be used:\n"
                f"{feedback}\n"
                "Produce a corrected, complete unified diff this time.\n"
            )

        if lang_guidance:
            prompt += f"\n{lang_guidance}\n"

        return prompt

    # ------------------------------------------------------------------
    # Response handling
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_patch_text(raw_response: Optional[str]) -> str:
        """Extract the unified diff from a raw LLM response.

        Handles plain diffs, markdown fenced diffs and JSON responses that
        carry the diff in a ``patch``/``diff`` field.
        """
        if not raw_response:
            return ""

        text = raw_response.strip()
        if not text:
            return ""

        # JSON response: {"patch": "..."} / {"diff": "..."}
        if text.startswith("{") or text.startswith("["):
            import json

            try:
                payload = json.loads(text)
            except (ValueError, TypeError):
                payload = None
            if isinstance(payload, dict):
                for key in ("patch", "diff", "unified_diff", "patch_diff"):
                    value = payload.get(key)
                    if isinstance(value, str) and value.strip():
                        return Repairer._strip_code_fences(value)
            elif isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict):
                        for key in ("patch", "diff", "unified_diff", "patch_diff"):
                            value = item.get(key)
                            if isinstance(value, str) and value.strip():
                                return Repairer._strip_code_fences(value)

        return Repairer._strip_code_fences(text)

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """Remove markdown code fences that some models add around diffs."""
        cleaned = re.sub(r"^```(?:diff|patch)?[ \t]*\r?\n?", "", text.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"\r?\n?```[ \t]*$", "", cleaned.strip())
        return cleaned.strip()

    @staticmethod
    def _normalize_hunks(patch_text: str) -> str:
        """Repair hunk headers that are malformed or inconsistent.

        Language models frequently emit a hunk header such as
        ``@@ -37,5 +37,5 @@`` while only including four context lines, or
        truncate the header completely (``@@ -``). The *body* of the hunk is
        the authoritative part - it is what actually gets applied - so the
        header is rewritten to match it.

        A header that cannot be parsed at all is replaced by a synthetic one;
        the applier then locates the hunk by its content, which does not need
        a line number.

        Only the header is touched: the patch content, the file paths and
        therefore every security check stay exactly as the model produced
        them.

        Args:
            patch_text: The raw unified diff.

        Returns:
            The unified diff with consistent hunk headers.
        """
        if not patch_text:
            return patch_text

        lines = patch_text.splitlines()
        result: List[str] = []
        index = 0
        header_re = re.compile(
            r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s*(@@.*)?$"
        )
        body_prefixes = (" ", "+", "-")

        while index < len(lines):
            line = lines[index]
            match = header_re.match(line)
            if not (line.startswith("@@") and match):
                if line.startswith("@@"):
                    # A broken header: try to rescue the hunk below it.
                    rescued = Repairer._rescue_hunk(lines, index)
                    if rescued is None:
                        result.append(line)
                        index += 1
                    else:
                        header, body, index = rescued
                        result.append(header)
                        result.extend(body)
                else:
                    result.append(line)
                    index += 1
                continue

            old_start = int(match.group(1))
            new_start = int(match.group(3))
            section = match.group(5) or ""

            body, index = Repairer._collect_hunk_body(lines, index + 1)

            old_count = sum(1 for entry in body if entry[:1] in (" ", "-"))
            new_count = sum(1 for entry in body if entry[:1] in (" ", "+"))

            result.append(
                "@@ -{0},{1} +{2},{3} {4}".format(
                    old_start,
                    old_count,
                    new_start,
                    new_count,
                    section.strip() or "@@",
                ).rstrip()
            )
            result.extend(body)

        return "\n".join(result)

    @staticmethod
    def _collect_hunk_body(lines: List[str], start: int) -> Tuple[List[str], int]:
        """Collect the body lines of a hunk.

        Args:
            lines: All lines of the diff.
            start: Index of the first body line.

        Returns:
            (body_lines, index_after_the_hunk)
        """
        body: List[str] = []
        cursor = start
        while cursor < len(lines):
            candidate = lines[cursor]
            if candidate.startswith("@@") or candidate.startswith("--- ") \
                    or candidate.startswith("+++ ") or candidate.startswith("diff --git "):
                break
            if candidate.startswith("\\"):
                cursor += 1
                continue
            if candidate == "" or candidate[:1] in (" ", "+", "-"):
                body.append(candidate)
                cursor += 1
                continue
            break
        return body, cursor

    @staticmethod
    def _rescue_hunk(lines: List[str], index: int) -> Optional[Tuple[str, List[str], int]]:
        """Rebuild a hunk whose header is unusable.

        Args:
            lines: All lines of the diff.
            index: Index of the broken header.

        Returns:
            ``(header, body, index_after_the_hunk)`` or None when the lines
            below the header are not a usable hunk.
        """
        body, cursor = Repairer._collect_hunk_body(lines, index + 1)
        meaningful = [entry for entry in body if entry[:1] in (" ", "+", "-")]
        if not meaningful:
            return None

        old_count = sum(1 for entry in body if entry[:1] in (" ", "-"))
        new_count = sum(1 for entry in body if entry[:1] in (" ", "+"))
        header = "@@ -1,{0} +1,{1} @@".format(old_count, new_count)
        return header, body, cursor

    @staticmethod
    def _describe_llm_error(exc: Exception) -> str:
        """Turn a provider error into an actionable message."""
        message = str(exc)
        lowered = message.lower()
        if "429" in message or "rate limit" in lowered or "resource_exhausted" in lowered:
            return (
                "The LLM provider rejected the request because of a rate limit "
                f"or quota: {message}"
            )
        if "timeout" in lowered or "timed out" in lowered:
            return f"The LLM provider timed out while generating the patch: {message}"
        if "api key" in lowered or "unauthenticated" in lowered or "permission" in lowered:
            return f"The LLM provider rejected the credentials: {message}"
        return f"The LLM provider failed while generating the patch: {message}"

    @staticmethod
    def _validate_generated_patch(patch_text: str) -> None:
        """Validate that the generated text is a usable unified diff.

        Raises:
            RepairGenerationError: If the patch is malformed, empty or does
                not contain any actual change.
        """
        try:
            file_patches = parse_unified_diff(patch_text)
        except PatchValidationError as exc:
            raise RepairGenerationError(
                f"The LLM returned a malformed unified diff: {exc}",
                recoverable=True,
            ) from exc

        if not file_patches:
            raise RepairGenerationError(
                "The LLM did not return any file changes.", recoverable=True
            )

        changed_lines = sum(fp.changed_lines for fp in file_patches)
        if changed_lines == 0:
            raise RepairGenerationError(
                "The LLM returned a patch without any actual changes.",
                recoverable=True,
            )

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------

    def _get_language_guidance(self, language: str, test_framework: str) -> str:
        """Get language-specific guidance for patch generation."""
        guidance = {
            "python": (
                "LANGUAGE-SPECIFIC GUIDANCE (Python):\n"
                "- Use 4-space indentation, not tabs\n"
                "- Follow PEP 8 style conventions\n"
                "- Prefer explicit over implicit (e.g., `is not None` vs truthiness)\n"
                "- Use type hints where appropriate\n"
                "- Don't change function signatures unless necessary\n"
                "- Handle exceptions specifically, not bare `except:`"
            ),
            "javascript": (
                "LANGUAGE-SPECIFIC GUIDANCE (JavaScript):\n"
                "- Use 2-space indentation\n"
                "- Prefer `const`/`let` over `var`\n"
                "- Use strict equality (`===`) unless coercion is intentional\n"
                "- Handle async/await properly\n"
                "- Don't modify prototype chains\n"
                "- Preserve module.exports/exports patterns"
            ),
            "typescript": (
                "LANGUAGE-SPECIFIC GUIDANCE (TypeScript):\n"
                "- Use 2-space indentation\n"
                "- Maintain type safety - don't use `any` unless necessary\n"
                "- Preserve interface contracts\n"
                "- Handle generics properly\n"
                "- Don't remove type annotations without reason\n"
                "- Use `readonly` where appropriate"
            ),
            "go": (
                "LANGUAGE-SPECIFIC GUIDANCE (Go):\n"
                "- Use tabs for indentation (gofmt standard)\n"
                "- Follow Go naming conventions (CamelCase for exported, camelCase for unexported)\n"
                "- Handle errors explicitly, don't ignore them\n"
                "- Use `:=` for short declarations inside functions\n"
                "- Don't change public API signatures unless necessary\n"
                "- Prefer `errors.Is`/`errors.As` for error checking"
            ),
            "rust": (
                "LANGUAGE-SPECIFIC GUIDANCE (Rust):\n"
                "- Use 4-space indentation\n"
                "- Follow Rust naming conventions (snake_case for functions/variables, PascalCase for types)\n"
                "- Handle `Result` with `?` operator for error propagation\n"
                "- Don't use `unwrap()` or `expect()` in production code unless panicking is intended\n"
                "- Preserve ownership/borrowing semantics\n"
                "- Use `Option`/`Result` properly"
            ),
            "java": (
                "LANGUAGE-SPECIFIC GUIDANCE (Java):\n"
                "- Use 4-space indentation\n"
                "- Follow Java naming conventions (PascalCase for classes, camelCase for methods/fields)\n"
                "- Handle checked exceptions properly\n"
                "- Don't change public method signatures unless necessary\n"
                "- Use try-with-resources for AutoCloseable\n"
                "- Prefer standard library over third-party where possible"
            ),
        }
        return guidance.get(language, "")

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

        # Add language info
        language = getattr(plan, "language", "python")
        parts.append(f"Language: {language}")

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

        # Language-specific assumptions
        language = getattr(plan, "language", "python")
        if language == "python":
            assumptions.append("Python syntax and type hints preserved")
        elif language in ("javascript", "typescript"):
            assumptions.append("Module exports and async patterns preserved")
        elif language == "go":
            assumptions.append("Go error handling patterns preserved")
        elif language == "rust":
            assumptions.append("Rust ownership/borrowing semantics preserved")
        elif language == "java":
            assumptions.append("Java checked exceptions and public API preserved")

        return assumptions
