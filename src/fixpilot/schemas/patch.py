"""FixPilot AI patch schema."""

from pydantic import BaseModel, Field


class PatchResult(BaseModel):
    """Patch generation and validation result."""
    patch: str = Field(default="", description="Unified diff patch")
    patch_summary: str = Field(default="", description="Patch summary")
    changed_files: list = Field(default_factory=list, description="Changed files")
    assumptions: list = Field(default_factory=list, description="Assumptions")
    tests_to_run: list = Field(default_factory=list, description="Tests to run")
    validation_passed: bool = Field(default=False, description="Whether patch validation passed")
    rejection_reason: str = Field(default="", description="Rejection reason if any")