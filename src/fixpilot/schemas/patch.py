"""FixPilot AI patch schema."""

import hashlib
from typing import List

from pydantic import BaseModel, Field


def compute_patch_hash(patch: str) -> str:
    """Return a stable hash of a unified diff.

    Trailing whitespace and the final newline are ignored so that two
    semantically identical patches always produce the same hash. The hash is
    used to detect a patch that was already tried (and failed) before.

    Args:
        patch: The unified diff text.

    Returns:
        A hex digest, or an empty string for an empty patch.
    """
    if not patch:
        return ""
    normalized = "\n".join(line.rstrip() for line in patch.strip().splitlines())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class PatchResult(BaseModel):
    """Patch generation and validation result."""
    patch: str = Field(default="", description="Unified diff patch")
    patch_summary: str = Field(default="", description="Patch summary")
    reasoning_summary: str = Field(default="", description="Brief evidence-based reasoning")
    root_cause_summary: str = Field(default="", description="Root cause identification")
    changed_files: list = Field(default_factory=list, description="Changed files")
    assumptions: list = Field(default_factory=list, description="Assumptions")
    tests_to_run: list = Field(default_factory=list, description="Tests to run")
    validation_passed: bool = Field(default=False, description="Whether patch validation passed")
    rejection_reason: str = Field(default="", description="Rejection reason if any")
    approval_status: str = Field(default="pending", description="Approval status")

    @property
    def patch_hash(self) -> str:
        """Stable hash of the patch (empty when there is no patch)."""
        return compute_patch_hash(self.patch)

    @property
    def changed_file_list(self) -> List[str]:
        """The changed files as a list of strings."""
        return [str(f) for f in self.changed_files]
