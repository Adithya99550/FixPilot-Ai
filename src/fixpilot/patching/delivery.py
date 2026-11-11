"""FixPilot AI verified patch delivery.

After a repair has been *verified* inside the disposable workspace, this
module can deliver the very same patch to the **original** project.

The delivery is deliberately conservative:

* the patch is validated again against the original project with exactly the
  same rules that protected the workspace (no absolute paths, no ``..``, no
  Windows drive letters, no UNC paths, no null bytes, no symlink escape);
* the protected-path list of the repair plan is honoured, so a test file is
  never modified;
* every touched file is backed up before it is written;
* the files are written atomically and rolled back if anything fails;
* nothing happens without an explicit, separate user approval.

The disposable workspace stays the place where the repair is *verified* -
delivery only copies an already proven result into the original project.
"""

import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fixpilot.patching.validator import (
    PatchApplier,
    PatchApplyError,
    PatchValidationError,
)

logger = logging.getLogger("fixpilot.delivery")


class DeliveryError(Exception):
    """Raised when a verified patch cannot be delivered safely."""


@dataclass
class DeliveryResult:
    """Outcome of a delivery attempt."""

    success: bool
    message: str
    changed_files: List[str] = field(default_factory=list)
    backup_path: Optional[Path] = None
    rolled_back: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "changed_files": list(self.changed_files),
            "backup_path": str(self.backup_path) if self.backup_path else None,
            "rolled_back": self.rolled_back,
        }


def _is_test_path(rel_path: str) -> bool:
    """Return True when the path looks like a test file.

    Test files are never modified automatically - a repair that "fixes" a
    test by rewriting it is not a repair.
    """
    normalized = rel_path.replace("\\", "/").lower()
    name = normalized.rsplit("/", 1)[-1]
    if "/tests/" in normalized or "/test/" in normalized or normalized.startswith("tests/"):
        return True
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    if name.endswith(".test.js") or name.endswith(".spec.js"):
        return True
    if name.endswith(".test.ts") or name.endswith(".spec.ts"):
        return True
    if name.endswith("_test.go") or name.endswith("test.java"):
        return True
    return False


def deliver_patch(
    patch: str,
    project_path: Path,
    protected_paths: Optional[List[str]] = None,
    allow_test_files: bool = False,
    create_backup: bool = True,
) -> DeliveryResult:
    """Deliver a verified patch to the original project.

    Args:
        patch: The verified unified diff.
        project_path: The original project directory.
        protected_paths: Paths the repair plan forbids (e.g. test files).
        allow_test_files: Escape hatch - test files are still refused by
            default.
        create_backup: Whether to keep a backup of the touched files.

    Returns:
        A :class:`DeliveryResult`.
    """
    project_root = Path(project_path).resolve()
    if not project_root.is_dir():
        return DeliveryResult(
            success=False,
            message=f"The project directory does not exist: {project_root}",
        )

    config: Dict[str, Any] = {}
    if protected_paths:
        config["protected_paths"] = list(protected_paths)
    applier = PatchApplier(config)

    # 1. Validate the patch against the *original* project with exactly the
    #    same rules that were used for the workspace.
    try:
        file_patches = applier._validate(patch, project_root)
    except PatchValidationError as exc:
        return DeliveryResult(
            success=False,
            message=f"The verified patch is not safe to apply here: {exc}",
        )

    # 2. Refuse to touch test files.
    if not allow_test_files:
        test_files = [
            file_patch.target_path
            for file_patch in file_patches
            if _is_test_path(file_patch.target_path)
        ]
        if test_files:
            return DeliveryResult(
                success=False,
                message=(
                    "The patch touches test files, which FixPilot never "
                    "modifies automatically: {0}".format(", ".join(test_files))
                ),
            )

    # 3. Snapshot the original files so a failure can be rolled back.
    snapshots: Dict[str, Optional[bytes]] = {}
    try:
        for file_patch in file_patches:
            rel = file_patch.target_path
            if rel in snapshots:
                continue
            target = (project_root / rel).resolve()
            if not target.is_relative_to(project_root):
                return DeliveryResult(
                    success=False,
                    message=f"Refusing to modify a file outside the project: {rel}",
                )
            snapshots[rel] = target.read_bytes() if target.is_file() else None
    except OSError as exc:
        return DeliveryResult(
            success=False, message=f"Could not read the original files: {exc}"
        )

    # 4. Back up the original files (outside the project, so the project
    #    stays clean).
    backup_path: Optional[Path] = None
    if create_backup:
        try:
            backup_path = Path(tempfile.mkdtemp(prefix="fixpilot_original_backup_"))
            for rel, original in snapshots.items():
                if original is None:
                    continue
                backup_file = backup_path / rel.replace("/", os.sep)
                backup_file.parent.mkdir(parents=True, exist_ok=True)
                backup_file.write_bytes(original)
        except OSError as exc:
            logger.warning("Could not create the delivery backup: %s", exc)
            backup_path = None

    # 5. Write the files atomically, rolling back on the first error.
    written: List[str] = []
    try:
        for file_patch in file_patches:
            rel = file_patch.target_path
            target = (project_root / rel).resolve()
            if not target.is_relative_to(project_root):
                raise DeliveryError(f"Refusing to modify a file outside the project: {rel}")

            if file_patch.is_deletion:
                if target.exists():
                    target.unlink()
                    written.append(rel)
                continue

            if target.exists():
                existing = target.read_text(encoding="utf-8")
                updated = applier._apply_hunks_to_text(existing, file_patch.hunks)
            else:
                updated = "\n".join(
                    text
                    for hunk in file_patch.hunks
                    for tag, text in hunk.lines
                    if tag == "+"
                )
                if updated:
                    updated += "\n"

            # The result must still be valid source code.
            applier._check_result_syntax(rel, updated)

            target.parent.mkdir(parents=True, exist_ok=True)
            applier._atomic_write(target, updated.encode("utf-8"))
            written.append(rel)
    except (OSError, DeliveryError, PatchValidationError, PatchApplyError) as exc:
        _rollback(project_root, snapshots, written)
        return DeliveryResult(
            success=False,
            message=f"Delivery failed and was rolled back: {exc}",
            changed_files=written,
            backup_path=backup_path,
            rolled_back=True,
        )

    return DeliveryResult(
        success=True,
        message=(
            "The verified patch was applied to the original project "
            "({0} file(s)): {1}".format(len(written), ", ".join(written))
        ),
        changed_files=written,
        backup_path=backup_path,
    )


def _rollback(
    project_root: Path,
    snapshots: Dict[str, Optional[bytes]],
    written: List[str],
) -> None:
    """Restore the original content of every file that was touched."""
    for rel in written:
        try:
            target = (project_root / rel).resolve()
            original = snapshots.get(rel)
            if original is None:
                if target.exists():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(original)
        except OSError as exc:  # pragma: no cover - defensive
            logger.error("Rollback of %s failed: %s", rel, exc)


def copy_backup_to(backup_path: Optional[Path], destination: Path) -> bool:
    """Copy a delivery backup into a user chosen directory.

    Args:
        backup_path: The backup directory created by :func:`deliver_patch`.
        destination: Where the backup should be copied to.

    Returns:
        True when the backup was copied.
    """
    if not backup_path or not backup_path.exists():
        return False
    try:
        destination = Path(destination)
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(backup_path, destination)
        return True
    except OSError as exc:
        logger.warning("Could not copy the backup: %s", exc)
        return False
