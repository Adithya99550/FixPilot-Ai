"""FixPilot AI execution schema."""

from pydantic import BaseModel, Field


class ExecutionResult(BaseModel):
    """Structured execution result."""
    exit_code: int = Field(default=0, description="Process exit code")
    stdout: str = Field(default="", description="Standard output")
    stderr: str = Field(default="", description="Standard error")
    timed_out: bool = Field(default=False, description="Whether execution timed out")
    duration: float = Field(default=0.0, description="Execution duration in seconds")
    sandbox_id: str = Field(default="", description="Sandbox execution ID")