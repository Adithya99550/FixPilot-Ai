"""FixPilot AI Audit schema definitions."""

from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field


class AuditFinding(BaseModel):
    """A single potential bug found during static code audit."""
    file_path: str = Field(..., description="Relative path to the file containing the finding")
    line_number: Optional[int] = Field(None, description="Line number if applicable")
    severity: str = Field(..., description="Severity level: HIGH, MEDIUM, LOW")
    category: str = Field(..., description="Category: NullPointer, ResourceLeak, LogicBug, Security, Memory, TypeSafety, ExceptionHandling")
    title: str = Field(..., description="Short title of the finding")
    description: str = Field(..., description="Detailed explanation of the potential bug")
    suggestion: str = Field(..., description="Recommended fix or remediation")


class AuditResult(BaseModel):
    """Complete result of a static code audit."""
    audit_id: str = Field(..., description="Unique ID for this audit run")
    target_path: str = Field(..., description="Target project path")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="Audit timestamp")
    scanned_files_count: int = Field(..., description="Number of source files scanned")
    findings: List[AuditFinding] = Field(default_factory=list, description="List of findings")
    summary: str = Field(..., description="Overall audit summary")
