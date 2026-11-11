"""FixPilot AI diagnostics schema."""

from pydantic import BaseModel, Field


class DiagnosticEvidence(BaseModel):
    """Structured diagnostic evidence."""
    summary: str = Field(default="", description="Concise problem description")
    exception_type: str = Field(default="", description="Exception type")
    exception_message: str = Field(default="", description="Exception message")
    failing_test: str = Field(default="", description="Failing test identifier")
    traceback: str = Field(default="", description="Full traceback")
    file_references: list = Field(default_factory=list, description="Relevant file paths")
    line_range: tuple = Field(default=(0, 0), description="Line range of failure")
    snippet: str = Field(default="", description="Relevant code snippet")
    redacting: bool = Field(default=False, description="Whether sensitive data was redacted")
    # Multi-language support
    language: str = Field(default="", description="Programming language")
    test_framework: str = Field(default="", description="Test framework")