"""FixPilot AI repair plan schema."""

from pydantic import BaseModel, Field


class RepairPlan(BaseModel):
    """Structured repair plan."""
    goal: str = Field(default="", description="Repair goal")
    root_cause: str = Field(default="", description="Root cause identification")
    steps: list = Field(default_factory=list, description="Repair steps")
    files_to_change: list = Field(default_factory=list, description="Files to change (relative paths)")
    files_not_to_change: list = Field(default_factory=list, description="Files not to change")
    expected_behavior: str = Field(default="", description="Expected behavior after fix")
    regression_risks: list = Field(default_factory=list, description="Regression risks")
    validation_command: str = Field(default="python -m pytest -q", description="Validation command")
    rollback_strategy: str = Field(default="", description="Rollback strategy")
    approval_summary: str = Field(default="", description="Approval summary")