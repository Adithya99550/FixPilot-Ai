"""FixPilot AI Code Review schema definitions."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ReviewIssue(BaseModel, extra="allow"):
    """A single code quality or architectural issue found during review."""
    file_path: str = Field(..., description="Relative path to the file")
    line_number: Optional[int] = Field(None, description="Line number if applicable")
    category: str = Field(..., description="Category: Style, Complexity, Architecture, Duplication, Maintainability, Linting")
    rule_id: str = Field(..., description="Rule or check identifier")
    message: str = Field(..., description="Description of the quality issue")
    suggestion: str = Field(..., description="Recommendation for improvement")


class ReviewResult(BaseModel, extra="allow"):
    """Complete result of a code quality and architecture review."""
    review_id: str = Field(..., description="Unique ID for this review run")
    target_path: str = Field(..., description="Target project path")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), description="Review timestamp")
    scanned_files_count: int = Field(..., description="Number of source files reviewed")
    issues: List[ReviewIssue] = Field(default_factory=list, description="List of identified issues")
    metrics: Dict[str, Any] = Field(default_factory=dict, description="Code metrics (e.g. LOC, complexity)")
    summary: str = Field(..., description="Overall review summary")
