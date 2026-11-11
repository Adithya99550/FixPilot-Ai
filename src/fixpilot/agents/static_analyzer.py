"""FixPilot AI Static Analyzer Agent.

Performs LLM-powered static bug scanning on source files without requiring failing tests.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from fixpilot.llm.provider import BaseLLMProvider
from fixpilot.schemas.audit import AuditFinding, AuditResult


class StaticAnalyzer:
    """LLM-powered static bug scanner."""

    def __init__(self, llm_provider: Optional[BaseLLMProvider] = None):
        self.llm_provider = llm_provider

    def audit(self, project_path: Path, config: Dict[str, Any] = None) -> AuditResult:
        """Scan project source files for potential bugs without failing tests.

        Args:
            project_path: Path to the project root.
            config: Configuration dictionary.

        Returns:
            AuditResult containing all discovered findings.
        """
        project_path = Path(project_path).resolve()
        audit_id = f"audit_{uuid.uuid4().hex[:12]}"

        # Collect source files
        source_files = {}
        exclude_dirs = {".git", ".venv", "venv", "__pycache__", "node_modules", "target", "build", "dist", ".pytest_cache"}

        for file_path in project_path.rglob("*"):
            if file_path.is_file() and not any(part in exclude_dirs for part in file_path.parts):
                if file_path.suffix.lower() in {".py", ".js", ".ts", ".go", ".rs", ".java"}:
                    rel_path = str(file_path.relative_to(project_path))
                    try:
                        content = file_path.read_text(encoding="utf-8", errors="replace")
                        # Truncate very large files for prompt context
                        if len(content) > 15000:
                            content = content[:15000] + "\n... [truncated]"
                        source_files[rel_path] = content
                    except Exception:
                        pass

        if not source_files:
            return AuditResult(
                audit_id=audit_id,
                target_path=str(project_path),
                scanned_files_count=0,
                findings=[],
                summary="No scannable source files found in project."
            )

        # If LLM provider is available, use it for intelligent static analysis
        if self.llm_provider:
            findings = self._llm_audit(source_files, project_path)
        else:
            # Fallback rule-based heuristic static analysis
            findings = self._heuristic_audit(source_files)

        summary = f"Scanned {len(source_files)} file(s). Found {len(findings)} potential bug(s) or vulnerability/issues."

        return AuditResult(
            audit_id=audit_id,
            target_path=str(project_path),
            scanned_files_count=len(source_files),
            findings=findings,
            summary=summary,
        )

    def _llm_audit(self, source_files: Dict[str, str], project_path: Path) -> List[AuditFinding]:
        """Use LLM to perform deep static analysis across files."""
        files_snippet = ""
        for path, content in list(source_files.items())[:20]:  # limit context
            files_snippet += f"\n--- FILE: {path} ---\n{content}\n"

        prompt = f"""You are an expert static analysis and code security bug scanner.
Analyze the following source files for potential bugs, security vulnerabilities, logic errors, null pointer dereferences, resource leaks, or unhandled exceptions without requiring a failing test.

Source Files:
{files_snippet}

Return a JSON object matching this schema:
{{
  "findings": [
    {{
      "file_path": "string",
      "line_number": int or null,
      "severity": "HIGH" or "MEDIUM" or "LOW",
      "category": "NullPointer" or "ResourceLeak" or "LogicBug" or "Security" or "Memory" or "TypeSafety" or "ExceptionHandling",
      "title": "string",
      "description": "string",
      "suggestion": "string"
    }}
  ],
  "summary": "string"
}}
"""
        try:
            if self.llm_provider.supports_structured_output:
                res = self.llm_provider.generate_structured(prompt, dict)
                raw_findings = res.get("findings", []) if isinstance(res, dict) else []
            else:
                raw_text = self.llm_provider.generate(prompt)
                # Extract JSON
                start = raw_text.find("{")
                end = raw_text.rfind("}")
                if start != -1 and end != -1:
                    data = json.loads(raw_text[start:end+1])
                    raw_findings = data.get("findings", [])
                else:
                    raw_findings = []

            findings = []
            for rf in raw_findings:
                findings.append(AuditFinding(
                    file_path=rf.get("file_path", "unknown"),
                    line_number=rf.get("line_number"),
                    severity=rf.get("severity", "MEDIUM"),
                    category=rf.get("category", "LogicBug"),
                    title=rf.get("title", "Potential Bug"),
                    description=rf.get("description", ""),
                    suggestion=rf.get("suggestion", "")
                ))
            return findings
        except Exception:
            return self._heuristic_audit(source_files)

    def _heuristic_audit(self, source_files: Dict[str, str]) -> List[AuditFinding]:
        """Perform heuristic static code checks when LLM is offline."""
        findings = []
        for path, content in source_files.items():
            lines = content.splitlines()
            for idx, line in enumerate(lines, 1):
                lower = line.lower()
                # Check for bare except
                if "except:" in line or "except Exception:" in line and "raise" not in line:
                    findings.append(AuditFinding(
                        file_path=path,
                        line_number=idx,
                        severity="LOW",
                        category="ExceptionHandling",
                        title="Bare or broad exception catch",
                        description="Catching broad exceptions without re-raising can swallow critical errors.",
                        suggestion="Catch specific exception types or log the exception."
                    ))
                # Check for hardcoded secrets / keys
                if any(k in lower for k in ["api_key =", "secret =", "password =", "token ="]):
                    if "os.getenv" not in line and "config" not in lower and "env" not in lower:
                        findings.append(AuditFinding(
                            file_path=path,
                            line_number=idx,
                            severity="HIGH",
                            category="Security",
                            title="Potential hardcoded secret",
                            description="Hardcoded API key or credential detected in source code.",
                            suggestion="Use environment variables or configuration files for secrets."
                        ))
                # Check for TODO / FIXME
                if "todo" in lower or "fixme" in lower:
                    findings.append(AuditFinding(
                        file_path=path,
                        line_number=idx,
                        severity="LOW",
                        category="LogicBug",
                        title="Unresolved TODO/FIXME comment",
                        description=line.strip(),
                        suggestion="Resolve the TODO/FIXME item."
                    ))
        return findings
