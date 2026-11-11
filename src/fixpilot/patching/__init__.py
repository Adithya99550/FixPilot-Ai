"""FixPilot AI patching package."""

from fixpilot.patching.validator import (
    FilePatch,
    Hunk,
    PatchApplier,
    PatchApplyError,
    PatchValidationError,
    normalize_diff_path,
    parse_unified_diff,
)

__all__ = [
    "PatchApplier",
    "PatchApplyError",
    "PatchValidationError",
    "FilePatch",
    "Hunk",
    "parse_unified_diff",
    "normalize_diff_path",
]
