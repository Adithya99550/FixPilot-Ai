"""FixPilot AI investigation schema."""

from pydantic import BaseModel, Field


class RootCauseHypothesis(BaseModel):
    """A root cause hypothesis with evidence."""
    explanation: str = Field(default="", description="Hypothesis explanation")
    confidence: str = Field(default="low", description="low|medium|high")
    evidence: list = Field(default_factory=list, description="Supporting evidence")
    affected_files: list = Field(default_factory=list, description="Affected file paths")


class InvestigationResult(BaseModel):
    """Structured investigation result."""
    summary: str = Field(default="", description="Problem summary")
    root_cause_hypotheses: list = Field(default_factory=list, description="Root cause hypotheses")
    evidence: list = Field(default_factory=list, description="Evidence references")
    affected_files: list = Field(default_factory=list, description="Affected file paths")
    missing_information: list = Field(default_factory=list, description="Missing information")
    recommended_next_action: str = Field(
        default="inspect_more",
        description="inspect_more|plan_repair|stop",
    )
    limitations: list = Field(default_factory=list, description="Known limitations")
    confidence: str = Field(default="low", description="low|medium|high")