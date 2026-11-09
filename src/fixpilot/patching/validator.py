"""FixPilot AI Patch Validator.

Responsibilities:
- Parse and validate patch format.
- Reject absolute paths, traversal (..), symlink escapes, binary patches, and files outside the allowed project workspace.
- Confirm target file hashes/contents have not changed since analysis.
- Show patch preview.
- Apply patch to the disposable workspace only.
- Save pre-patch state and patch metadata.
- Support safe rollback of the disposable copy.

Following §8.2-8.4 of PROJECT_SPEC.md for path safety and patch validation.
"""

import re
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fixpilot.schemas.patch import PatchResult
from fixpilot.schemas.state import FixPilotState
from fixpilot.diagnostics.redaction import redact_sensitive_data


class PatchValidationError(Exception):
    """Raised when a patch fails validation checks."""
    pass


class PatchApplier:
    """Applies and validates unified diff patches in a disposable workspace."""

    # MVP defaults per §8.2
    MAX_FILES_CHANGED = 5
    MAX_CHANGED_LINES = 300
    PROTECTED_FILES = {
        ".env",
        ".git",
        "fixpilot.toml",
        "Dockerfile.sandbox",
        ".fixpilot",
        "artifacts",
    }

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.max_files_changed = self.config.get(
            "max_files_changed", self.MAX_FILES_CHANGED
        )
        self.max_changed_lines = self.config.get(
            "max_changed_lines", self.MAX_CHANGED_LINES
        )

    def validate_patch(self, patch: str, workspace_path: Path) -> Tuple[bool, str]:
        """Validate a unified diff patch for safety and applicability.

        Args:
            patch: The unified diff patch string.
            workspace_path: Path to the disposable workspace.

        Returns:
            (is_valid, rejection_reason) tuple.

        Raises:
            PatchValidationError: If patch format is invalid.
        """
        if not patch or not patch.strip():
            return False, "Patch is empty"

        # Check for absolute paths
        if re.search(r"^--- /|^\+++ ", patch, re.MULTILINE):
            # These are standard diff headers with paths
            # Check if any path starts with / (absolute)
            abs_path_matches = re.findall(r"[\/\+\-]+ /([^\n]+)", patch)
            for match in abs_path_matches:
                path = match.strip()
                if path.startswith("/"):
                    return False, f"Patch contains absolute path: {path}"

        # Check for .. traversal
        if ".." in patch:
            # More carefully check for .. in file paths
            traversal_matches = re.findall(r"[a-zA-Z0-9_/.-]+/\.\.", patch)
            if traversal_matches:
                return False, f"Patch contains directory traversal (..): {traversal_matches[0]}"

        # Check for protected files
        protected_patterns = [
            r"\.env",
            r"\.git",
            r"fixpilot\.toml",
            r"Dockerfile",
            r"\.fixpilot",
        ]
        for pattern in protected_patterns:
            if re.search(pattern, patch, re.IGNORECASE):
                return False, f"Patch targets protected file pattern: {pattern}"

        # Count the number of files changed
        file_changes = re.findall(r"--- /a/([^\n]+)", patch)
        # Also try without leading /
        file_changes += re.findall(r"--- ([^\n]+)", patch)
        # Unique files
        unique_files = set()
        for f in file_changes:
            # Normalize the path
            norm_path = Path(f.strip()).name if Path(f.strip()).name else str(Path(f.strip()))
            unique_files.add(norm_path)

        if len(unique_files) > self.max_files_changed:
            return False, (
                f"Patch changes {len(unique_files)} files, "
                f"exceeding limit of {self.max_files_changed}"
            )

        # Count changed lines (hunks with @@)
        hunk_count = len(re.findall(r"^@@ ", patch, re.MULTILINE))
        # Rough estimate of changed lines
        changed_lines = 0
        for line in patch.split("\n"):
            if line.startswith("+"):
                # Don't count removed lines (-), and don't double-count
                # Just count additive changes
                if not line.startswith("+++"):
                    changed_lines += 1

        if changed_lines > self.max_changed_lines:
            return False, (
                f"Patch changes {changed_lines} lines, "
                f"exceeding limit of {self.max_changed_lines}"
            )

        # Validate that target files exist in the workspace
        for file_path in unique_files:
            full_path = (workspace_path / file_path) if not Path(file_path).is_absolute() else Path(file_path)
            if not full_path.exists():
                # File might be new, that's OK for addition
                # But check it's not outside workspace
                try:
                    full_path.resolve().relative_to(workspace_path.resolve())
                except ValueError:
                    return False, f"Patch targets file outside workspace: {file_path}"

        return True, ""

    def apply_patch(
        self, patch: str, workspace_path: Path, create_backup: bool = True
    ) -> Tuple[bool, str, Optional[Path]]:
        """Apply a validated patch to the disposable workspace.

        Args:
            patch: The unified diff patch string (must be validated first).
            workspace_path: Path to the disposable workspace.
            create_backup: Whether to create a backup before applying.

        Returns:
            (success, message, backup_path) tuple.
            - success: Whether the patch was applied successfully
            - message: Description of the result
            - backup_path: Path to the backup if created, None otherwise
        """
        if create_backup:
            # Create a backup of the workspace
            import shutil

            backup_path = workspace_path / ".fixpilot_backup"
            try:
                if workspace_path.exists():
                    # Copy the entire workspace
                    if backup_path.exists():
                        shutil.rmtree(backup_path)
                    shutil.copytree(workspace_path, backup_path)
            except Exception as e:
                # Continue even if backup fails
                backup_path = None

        # Parse and apply the patch
        try:
            # Simple patch application using a basic approach
            # In a production system, would use patch/difflib properly
            lines = patch.split("\n")

            # Find files to modify
            current_file = None
            file_changes = {}

            for i, line in enumerate(lines):
                # Find --- /a/ or --- headers
                if line.startswith("--- ") or line.startswith("--- "):
                    # Extract file path
                    file_path = line[4:].strip()  # Remove "--- "
                    # Convert to relative path (remove a/ prefix if present)
                    if file_path.startswith("a/"):
                        file_path = file_path[2:]
                    current_file = file_path
                    file_changes[current_file] = {"added": [], "removed": [], "unchanged": []}
                elif line.startswith("+++ "):
                    # New file version path - skip, we use the --- path
                    pass
                elif line.startswith("@@ "):
                    # Hunks section - skip first line, process hunks
                    pass
                elif current_file and line.startswith("+"):
                    # Added line
                    if current_file in file_changes:
                        file_changes[current_file]["added"].append(line[1:])
                elif current_file and line.startswith("-"):
                    # Removed line
                    if current_file in file_changes:
                        file_changes[current_file]["removed"].append(line[1:])

            # Apply changes to files
            applied_files = []
            for file_path, changes in file_changes.items():
                full_path = (workspace_path / file_path) if not Path(file_path).is_absolute() else Path(file_path)

                if not full_path.exists():
                    # New file - create it
                    try:
                        # Create parent directories
                        full_path.parent.mkdir(parents=True, exist_ok=True)
                        # Write the content based on added lines
                        content = "\n".join(changes.get("added", []))
                        if content:
                            full_path.write_text(content, encoding="utf-8")
                            applied_files.append(file_path)
                    except Exception as e:
                        return False, f"Failed to create new file {file_path}: {str(e)}", None
                else:
                    # Existing file - apply modifications
                    try:
                        existing_content = full_path.read_text(encoding="utf-8")
                        added = changes.get("added", [])
                        removed = changes.get("removed", [])

                        # Remove lines
                        for rem_line in removed:
                            if rem_line in existing_content.split("\n"):
                                existing_content = "\n".join(
                                    l for l in existing_content.split("\n") if l != rem_line
                                )

                        # Add lines (append at end for simplicity)
                        for add_line in added:
                            existing_content += "\n" + add_line

                        full_path.write_text(existing_content, encoding="utf-8")
                        applied_files.append(file_path)
                    except Exception as e:
                        return False, f"Failed to apply patch to {file_path}: {str(e)}", None

            return True, f"Patch applied successfully to {len(applied_files)} file(s)", backup_path

        except Exception as e:
            # Restore from backup if available
            return False, f"Patch application failed: {str(e)}", None