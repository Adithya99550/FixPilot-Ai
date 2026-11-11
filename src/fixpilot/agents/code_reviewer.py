"""FixPilot AI Code Reviewer Agent.

Performs code quality review, linting style checks, and architectural analysis.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from fixpilot.llm.provider import BaseLLMProvider
from fixpilot.schemas.review import ReviewIssue, ReviewResult


class CodeReviewer:
    """LLM and heuristic code quality reviewer."""

    def __init__(self, llm_provider: Optional[BaseLLMProvider] = None):
        self.llm_provider = llm_provider

    def review(self, project_path: Path, config: Dict[str, Any] = None) -> ReviewResult:
        """Perform code quality review, linting, style, and architecture analysis.

        Args:
            project_path: Path to the project root.
            config: Configuration dictionary.

        Returns:
            ReviewResult containing issues and code metrics.
        """
        project_path = Path(project_path).resolve()
        review_id = f"rev_{uuid.uuid4().hex[:12]}"

        source_files = {}
        total_loc = 0
        exclude_dirs = {".git", ".venv", "venv", "__pycache__", "node_modules", "target", "build", "dist", ".pytest_cache"}

        for file_path in project_path.rglob("*"):
            if file_path.is_file() and not any(part in exclude_dirs for part in file_path.parts):
                if file_path.suffix.lower() in {".py", ".js", ".ts", ".go", ".rs", ".java"}:
                    rel_path = str(file_path.relative_to(project_path))
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="replace")
                        loc = len(content.splitlines())
                        total_loc += loc
                        if len(content) > 15000:
                            content = content[:15000] + "\n... [truncated]"
                        source_files[rel_path] = content
                    except Exception:
                        pass

        if not source_files:
            return ReviewResult(
                review_id=review_id,
                target_path=str(project_path),
                scanned_files_count=0,
                issues=[],
                metrics={"total_loc": 0},
                summary="No source files found for review."
            )

        if self.llm_provider:
            issues = self._llm_review(source_files, project_path)
        else:
            issues = self._heuristic_review(source_files)

        metrics = {
            "total_loc": total_loc,
            "total_files": len(source_files),
            "issues_count": len(issues),
        }

        summary = f"Reviewed {len(source_files)} file(s) ({total_loc} lines of code). Identified {len(issues)} code quality/architecture issue(s)."

        return ReviewResult(
            review_id=review_id,
            target_path=str(project_path),
            scanned_files_count=len(source_files),
            issues=issues,
            metrics=metrics,
            summary=summary,
        )

    def _llm_review(self, source_files: Dict[str, str], project_path: Path) -> List[ReviewIssue]:
        """Use LLM to perform deep code quality and architecture review."""
        files_snippet = ""
        for path, content in list(source_files.items())[:20]:
            files_snippet += f"\n--- FILE: {path} ---\n{content}\n"

        prompt = f"""You are an expert software architect, code reviewer, and linter.
Review the following source files for code quality, style, maintainability, design patterns, duplication, and architectural improvements.

Source Files:
{files_snippet}

Return a JSON object matching this schema:
{{
  "issues": [
    {{
      "file_path": "string",
      "line_number": int or null,
      "category": "Style" or "Complexity" or "Architecture" or "Duplication" or "Maintainability" or "Linting",
      "rule_id": "string",
      "message": "string",
      "suggestion": "string"
    }}
  ],
  "summary": "string"
}}
"""
        try:
            if self.llm_provider.supports_structured_output:
                res = self.llm_provider.generate_structured(prompt, dict)
                raw_issues = res.get("issues", []) if isinstance(res, dict) else []
            else:
                raw_text = self.llm_provider.generate(prompt)
                start = raw_text.find("{")
                end = raw_text.rfind("}")
                if start != -1 and end != -1:
                    data = json.loads(raw_text[start:end+1])
                    raw_issues = data.get("issues", [])
                else:
                    raw_issues = []

            issues = []
            for ri in raw_issues:
                issues.append(ReviewIssue(
                    file_path=ri.get("file_path", "unknown"),
                    line_number=ri.get("line_number"),
                    category=ri.get("category", "Maintainability"),
                    rule_id=ri.get("rule_id", "GENERAL_001"),
                    message=ri.get("message", ""),
                    suggestion=ri.get("suggestion", "")
                ))
            return issues
        except Exception:
            return self._heuristic_review(source_files)

    def _heuristic_review(self, source_files: Dict[str, str]) -> List[ReviewIssue]:
        """Perform heuristic linting and style checks when LLM is offline."""
        issues = []
        for path, content in source_files.items():
            lines = content.splitlines()
            for idx, line in enumerate(lines, 1):
                # Check line length (PEP 8 guideline: 79-120 chars)
                if len(line) > 120:
                    issues.append(ReviewIssue(
                        file_path=path,
                        line_number=idx,
                        category="Style",
                        rule_id="STYLE_LINE_LENGTH",
                        message=f"Line too long ({len(line)} characters > 120 limit)",
                        suggestion="Break line into multiple lines."
                    ))
                # Check for print statements in production code
                if "print(" in line and "test" not in path.lower():
                    issues.append(ReviewIssue(
                        file_path=path,
                        line_number=idx,
                        category="Maintainability",
                        rule_id="MAINT_PRINT_STATEMENT",
                        message="Use of print() statement instead of proper logging",
                        suggestion="Replace print() with logging module."
                    ))
        return issues
