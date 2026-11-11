"""FixPilot AI Patch Validator and Applier.

Responsibilities:
- Parse unified diff patches properly (headers, hunk ranges, line counts).
- Reject absolute paths, traversal (``..``), Windows drive paths, UNC paths,
  null bytes, symlink escapes and files outside the allowed workspace.
- Validate **both** the old (``---``) and the new (``+++``) path of every
  file section of a multi-file patch.
- Reject binary patches, renames, malformed hunks and unsupported headers.
- Validate the *complete* patch before a single file is modified.
- Apply the patch atomically inside the disposable workspace only.
- Roll back to the original workspace state when application fails.

Design notes
------------
The validator and the applier share one single source of truth for path
handling: :func:`normalize_diff_path` and :func:`parse_unified_diff`. Both the
``---`` and ``+++`` headers are validated, and the applier writes exactly the
paths the validator approved.

Following §8.2-8.4 of PROJECT_SPEC.md for path safety and patch validation.
"""

import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fixpilot.schemas.patch import compute_patch_hash

logger = logging.getLogger("fixpilot.patching")

#: Marker used by unified diffs for "this side does not exist".
DEV_NULL = "/dev/null"

#: Strict unified diff hunk header.
#:   @@ -old_start[,old_count] +new_start[,new_count] @@ [section heading]
HUNK_HEADER_RE = re.compile(
    r"^@@\s+-(?P<old_start>\d+)(?:,(?P<old_count>\d+))?\s+"
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))?\s+@@"
)

#: Diff header paths may be followed by a timestamp separated by a tab or by
#: two or more spaces (GNU diff style).
_HEADER_TIMESTAMP_SEPARATORS = ("\t", "  ")


class PatchValidationError(Exception):
    """Raised when a patch fails validation checks."""

    pass


class PatchApplyError(Exception):
    """Raised when a validated patch cannot be applied to the workspace."""

    pass


@dataclass
class Hunk:
    """A single unified diff hunk."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def old_lines(self) -> List[str]:
        return [text for tag, text in self.lines if tag in (" ", "-")]

    @property
    def new_lines(self) -> List[str]:
        return [text for tag, text in self.lines if tag in (" ", "+")]

    @property
    def changed_lines(self) -> int:
        return sum(1 for tag, _ in self.lines if tag in ("+", "-"))


@dataclass
class FilePatch:
    """One file section of a unified diff."""

    old_path: Optional[str]
    new_path: Optional[str]
    hunks: List[Hunk] = field(default_factory=list)

    @property
    def target_path(self) -> str:
        """The path the patch writes to (new path, or old path for deletions)."""
        return self.new_path or self.old_path or ""

    @property
    def is_creation(self) -> bool:
        return self.old_path is None and self.new_path is not None

    @property
    def is_deletion(self) -> bool:
        return self.new_path is None and self.old_path is not None

    @property
    def changed_lines(self) -> int:
        return sum(hunk.changed_lines for hunk in self.hunks)


# ----------------------------------------------------------------------
# Path helpers - shared by the validator and the applier
# ----------------------------------------------------------------------


def normalize_diff_path(raw_path: str) -> Optional[str]:
    """Normalize a diff header path into a workspace-relative POSIX path.

    * ``a/`` and ``b/`` prefixes (the unified diff convention) are removed.
      This is *not* a directory component - ``a/src/app.py`` refers to
      ``src/app.py``.
    * Backslashes are converted to forward slashes so Windows-style paths are
      handled consistently.
    * ``.`` components are dropped, ``..`` components are **kept** so the
      caller can reject them explicitly instead of silently resolving them.

    Args:
        raw_path: The raw path taken from a ``---``/``+++`` header.

    Returns:
        The normalized relative path, or ``None`` for the ``/dev/null``
        marker (which means "this side of the diff does not exist").
    """
    if raw_path is None:
        return None

    path = raw_path.strip()
    if not path:
        return ""

    # Strip a trailing timestamp ("file.py\t2024-01-01 00:00:00" or
    # "file.py 2024-01-01 00:00:00").
    for separator in _HEADER_TIMESTAMP_SEPARATORS:
        if separator in path:
            path = path.split(separator, 1)[0].strip()
            break

    if path == DEV_NULL or path == "dev/null":
        return None

    path = path.replace("\\", "/")

    # Remove the conventional a/ or b/ prefix only when what follows is
    # still a relative path.
    if len(path) > 2 and path[1] == "/" and path[0] in ("a", "b"):
        path = path[2:]

    # Drop "." components but keep ".." so traversal can be rejected.
    parts = [part for part in path.split("/") if part not in ("", ".")]
    return "/".join(parts)


def _is_absolute_path(path: str) -> bool:
    """Return True when the path is absolute (POSIX, Windows drive, or UNC)."""
    if not path:
        return False
    normalized = path.replace("\\", "/")
    if normalized.startswith("/"):
        return True
    # Windows drive letter, e.g. C:/Users or C:\Users
    if re.match(r"^[A-Za-z]:", normalized):
        return True
    # UNC path (\\server\share) - already normalised to //server/share above.
    return False


# ----------------------------------------------------------------------
# Diff parser
# ----------------------------------------------------------------------


def parse_unified_diff(patch_text: str) -> List[FilePatch]:
    """Parse a unified diff into structured file patches.

    Args:
        patch_text: The raw unified diff.

    Returns:
        A list of :class:`FilePatch` objects.

    Raises:
        PatchValidationError: If the diff is malformed or uses an
            unsupported construct (binary patches, renames, bad hunk
            headers, inconsistent hunk line counts, ...).
    """
    if patch_text is None or not patch_text.strip():
        raise PatchValidationError("Patch is empty")

    file_patches: List[FilePatch] = []
    current: Optional[FilePatch] = None
    current_hunk: Optional[Hunk] = None
    pending_old_raw: Optional[str] = None
    pending_old_seen = False

    lines = patch_text.splitlines()
    index = 0

    def _finish_hunk() -> None:
        """Validate the counts of the hunk that just ended."""
        nonlocal current_hunk
        if current_hunk is None:
            return
        old_seen = sum(1 for tag, _ in current_hunk.lines if tag in (" ", "-"))
        new_seen = sum(1 for tag, _ in current_hunk.lines if tag in (" ", "+"))
        if old_seen != current_hunk.old_count or new_seen != current_hunk.new_count:
            raise PatchValidationError(
                "Malformed hunk: header declares -{0},{1} +{2},{3} but the hunk "
                "contains -{4} +{5} lines".format(
                    current_hunk.old_start,
                    current_hunk.old_count,
                    current_hunk.new_start,
                    current_hunk.new_count,
                    old_seen,
                    new_seen,
                )
            )
        current_hunk = None

    while index < len(lines):
        line = lines[index]
        index += 1

        if line.startswith("diff --git "):
            _finish_hunk()
            current = None
            pending_old_raw = None
            pending_old_seen = False
            continue

        if line.startswith("GIT binary patch") or line.startswith("Binary files "):
            raise PatchValidationError(
                "Binary patches are not supported by FixPilot."
            )

        if line.startswith("rename from ") or line.startswith("rename to "):
            raise PatchValidationError(
                "Rename operations are not supported by FixPilot."
            )

        if line.startswith(("index ", "old mode ", "new mode ", "similarity index ",
                           "dissimilarity index ", "new file mode ", "deleted file mode ")):
            # Git extended headers - informational only.
            continue

        if line.startswith("--- "):
            _finish_hunk()
            pending_old_raw = line[4:]
            pending_old_seen = True
            current = None
            continue

        if line.startswith("+++ "):
            if not pending_old_seen:
                raise PatchValidationError(
                    "Malformed diff: '+++' header without a preceding '---' header."
                )
            old_path = normalize_diff_path(pending_old_raw)
            new_path = normalize_diff_path(line[4:])
            pending_old_raw = None
            pending_old_seen = False

            if old_path is None and new_path is None:
                raise PatchValidationError(
                    "Malformed diff: both sides of the file section are empty."
                )
            current = FilePatch(old_path=old_path, new_path=new_path)
            file_patches.append(current)
            continue

        if line.startswith("@@"):
            _finish_hunk()
            match = HUNK_HEADER_RE.match(line)
            if not match:
                raise PatchValidationError(
                    "Malformed hunk header: {0!r}".format(line.strip())
                )
            if current is None:
                raise PatchValidationError(
                    "Malformed diff: hunk appears before any file header."
                )
            old_count = int(match.group("old_count") or 1)
            new_count = int(match.group("new_count") or 1)
            current_hunk = Hunk(
                old_start=int(match.group("old_start")),
                old_count=old_count,
                new_start=int(match.group("new_start")),
                new_count=new_count,
            )
            current.hunks.append(current_hunk)
            continue

        if current_hunk is not None:
            if line.startswith("\\"):
                # "\ No newline at end of file" - informational.
                continue
            if line == "":
                tag, text = " ", ""
            elif line[0] == " ":
                tag, text = " ", line[1:]
            elif line[0] == "+":
                tag, text = "+", line[1:]
            elif line[0] == "-":
                tag, text = "-", line[1:]
            else:
                raise PatchValidationError(
                    "Malformed hunk: unexpected line {0!r}".format(line)
                )
            current_hunk.lines.append((tag, text))
            continue

        # Any other content outside of a hunk is ignored (trailing prose,
        # email signatures, ...).

    _finish_hunk()

    if not file_patches:
        raise PatchValidationError(
            "Patch does not contain any recognizable file headers."
        )

    for file_patch in file_patches:
        if not file_patch.hunks:
            raise PatchValidationError(
                "Malformed diff: file section for {0!r} contains no hunks.".format(
                    file_patch.target_path
                )
            )

    return file_patches


class PatchApplier:
    """Validates and applies unified diff patches in a disposable workspace."""

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

    # Path components that may never be touched by a patch.
    PROTECTED_COMPONENTS = {
        ".env",
        ".git",
        ".fixpilot",
        ".fixpilot_backup",
        "fixpilot.toml",
        "artifacts",
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.max_files_changed = self.config.get(
            "max_files_changed", self.MAX_FILES_CHANGED
        )
        self.max_changed_lines = self.config.get(
            "max_changed_lines", self.MAX_CHANGED_LINES
        )
        # Extra protected paths (e.g. the project's test files) supplied by
        # the repair plan so a repair can never "fix" a test.
        self.protected_paths = set(self.config.get("protected_paths", []) or [])
        # Creating/deleting files is opt-in and disabled by default.
        self.allow_file_creation = bool(
            self.config.get("allow_file_creation", False)
            or self.config.get("FIXPILOT_ALLOW_FILE_CREATION", False)
        )
        self.allow_file_deletion = bool(
            self.config.get("allow_file_deletion", False)
            or self.config.get("FIXPILOT_ALLOW_FILE_DELETION", False)
        )

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_absolute_path(path: str) -> bool:
        """Return True when the path is absolute (POSIX, Windows drive, or UNC)."""
        return _is_absolute_path(path)

    @staticmethod
    def _strip_diff_prefix(path: str) -> str:
        """Strip the conventional ``a/`` or ``b/`` prefix from a diff path."""
        normalized = normalize_diff_path(path)
        return normalized if normalized is not None else path

    @staticmethod
    def _extract_target_paths(patch: str) -> List[str]:
        """Return every file path referenced by the patch (old and new side).

        Both the ``---`` and the ``+++`` header are considered so a patch
        cannot smuggle an unsafe path in through the old side.
        """
        paths: List[str] = []
        try:
            file_patches = parse_unified_diff(patch)
        except PatchValidationError:
            # Fall back to a best-effort scan so error messages can mention
            # the offending path.
            file_patches = []

        for file_patch in file_patches:
            for candidate in (file_patch.old_path, file_patch.new_path):
                if candidate and candidate not in paths:
                    paths.append(candidate)

        if paths:
            return paths

        # Best effort extraction for malformed patches.
        for line in patch.splitlines():
            if line.startswith("--- ") or line.startswith("+++ "):
                raw = line[4:]
                normalized = normalize_diff_path(raw)
                if normalized and normalized not in paths:
                    paths.append(normalized)
        return paths

    @classmethod
    def _is_protected_path(cls, file_path: str) -> bool:
        """Return True when any path component is protected."""
        normalized = file_path.replace("\\", "/")
        parts = [p for p in normalized.split("/") if p]
        for part in parts:
            if part in cls.PROTECTED_COMPONENTS:
                return True
            if part.lower().startswith("dockerfile"):
                return True
        return False

    def _is_protected_by_plan(self, file_path: str) -> bool:
        """Return True when the repair plan forbids touching this path."""
        if not self.protected_paths:
            return False
        normalized = file_path.replace("\\", "/").lstrip("./")
        for protected in self.protected_paths:
            protected_norm = str(protected).replace("\\", "/").lstrip("./")
            if not protected_norm:
                continue
            if normalized == protected_norm or normalized.endswith("/" + protected_norm):
                return True
        return False

    @staticmethod
    def _is_within(target: Path, root: Path) -> bool:
        """Return True when ``target`` resolves inside ``root``."""
        try:
            target.relative_to(root)
            return True
        except ValueError:
            return False

    def _validate_relative_path(self, rel_path: str, label: str) -> Optional[str]:
        """Validate a single workspace-relative path.

        Args:
            rel_path: The normalized relative path.
            label: Human readable description used in error messages.

        Returns:
            ``None`` when the path is safe, otherwise the rejection reason.
        """
        if rel_path is None:
            return None

        if "\x00" in rel_path:
            return "Patch {0} contains a null byte: {1!r}".format(label, rel_path)

        if not rel_path:
            return "Patch {0} contains an empty path".format(label)

        if _is_absolute_path(rel_path):
            return "Patch {0} contains an absolute path: {1}".format(label, rel_path)

        parts = PurePosixPath(rel_path).parts
        if any(part == ".." for part in parts):
            return "Patch {0} contains directory traversal (..): {1}".format(
                label, rel_path
            )

        if self._is_protected_path(rel_path):
            return "Patch {0} targets a protected file: {1}".format(label, rel_path)

        if self._is_protected_by_plan(rel_path):
            return (
                "Patch {0} targets a file the repair plan forbids: {1}".format(
                    label, rel_path
                )
            )

        return None

    def _resolve_in_workspace(self, workspace_root: Path, rel_path: str) -> Path:
        """Resolve a relative path against the workspace root.

        Symlinks are resolved, so a symlink pointing outside the workspace
        resolves to a path outside the workspace and is rejected by the
        caller.
        """
        return (workspace_root / rel_path).resolve()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_patch(self, patch: str, workspace_path: Path) -> Tuple[bool, str]:
        """Validate a unified diff patch for safety and applicability.

        The *complete* patch is validated before any file is touched, so a
        rejected patch can never modify the workspace.

        Args:
            patch: The unified diff patch string.
            workspace_path: Path to the disposable workspace.

        Returns:
            (is_valid, rejection_reason) tuple. The reason is an empty string
            when the patch is valid.
        """
        try:
            self._validate(patch, Path(workspace_path))
        except PatchValidationError as exc:
            return False, str(exc)
        return True, ""

    def _validate(self, patch: str, workspace_path: Path) -> List[FilePatch]:
        """Validate the patch and return the parsed file patches.

        Raises:
            PatchValidationError: With a descriptive reason when the patch is
                rejected.
        """
        if not patch or not patch.strip():
            raise PatchValidationError("Patch is empty")

        file_patches = parse_unified_diff(patch)
        workspace_root = Path(workspace_path).resolve()

        # ---- Path safety (old and new side of every file section) -----
        for file_patch in file_patches:
            for rel_path, label in (
                (file_patch.old_path, "old path"),
                (file_patch.new_path, "new path"),
            ):
                reason = self._validate_relative_path(rel_path, label)
                if reason:
                    raise PatchValidationError(reason)

            # Both sides must resolve inside the disposable workspace.
            for rel_path, label in (
                (file_patch.old_path, "old path"),
                (file_patch.new_path, "new path"),
            ):
                if not rel_path:
                    continue
                target = self._resolve_in_workspace(workspace_root, rel_path)
                if not self._is_within(target, workspace_root):
                    raise PatchValidationError(
                        "Patch {0} targets a file outside the workspace: {1}".format(
                            label, rel_path
                        )
                    )
                # A symlinked parent directory must not escape either.
                parent = target.parent
                if not self._is_within(parent.resolve(), workspace_root):
                    raise PatchValidationError(
                        "Patch {0} resolves through a symlink outside the "
                        "workspace: {1}".format(label, rel_path)
                    )

            # ---- Creation / deletion policy --------------------------
            if file_patch.is_creation and not self.allow_file_creation:
                raise PatchValidationError(
                    "Patch creates a new file ({0}) but file creation is not "
                    "allowed".format(file_patch.target_path)
                )
            if file_patch.is_deletion and not self.allow_file_deletion:
                raise PatchValidationError(
                    "Patch deletes a file ({0}) but file deletion is not "
                    "allowed".format(file_patch.target_path)
                )

            # The target file must already exist for a modification.
            if file_patch.new_path:
                target = self._resolve_in_workspace(
                    workspace_root, file_patch.new_path
                )
                if not target.exists() and not self.allow_file_creation:
                    raise PatchValidationError(
                        "Patch targets a file that does not exist in the "
                        "workspace: {0}".format(file_patch.new_path)
                    )
                if target.exists() and target.is_dir():
                    raise PatchValidationError(
                        "Patch targets a directory: {0}".format(
                            file_patch.new_path
                        )
                    )

        # ---- Limits ----------------------------------------------------
        targets = []
        for file_patch in file_patches:
            target = file_patch.target_path
            if target not in targets:
                targets.append(target)

        if len(targets) > self.max_files_changed:
            raise PatchValidationError(
                "Patch changes {0} files, exceeding the limit of {1}".format(
                    len(targets), self.max_files_changed
                )
            )

        changed_lines = sum(fp.changed_lines for fp in file_patches)
        if changed_lines > self.max_changed_lines:
            raise PatchValidationError(
                "Patch changes {0} lines, exceeding the limit of {1}".format(
                    changed_lines, self.max_changed_lines
                )
            )

        if changed_lines == 0:
            raise PatchValidationError(
                "Patch does not contain any actual changes."
            )

        return file_patches

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------

    def apply_patch(
        self, patch: str, workspace_path: Path, create_backup: bool = True
    ) -> Tuple[bool, str, Optional[Path]]:
        """Apply a validated patch to the disposable workspace.

        The patch is validated first (using exactly the same path
        normalization as :meth:`validate_patch`). All file contents are
        computed in memory before anything is written, and the write phase
        rolls back on the first error, so a failed application never leaves a
        partially modified workspace.

        Args:
            patch: The unified diff patch string.
            workspace_path: Path to the disposable workspace.
            create_backup: Whether to keep a copy of the affected files.

        Returns:
            (success, message, backup_path) tuple.
        """
        backup_path: Optional[Path] = None
        workspace_root = Path(workspace_path).resolve()

        try:
            file_patches = self._validate(patch, workspace_root)
        except PatchValidationError as exc:
            return False, f"Patch validation failed: {exc}", None

        # Snapshot the original state so a failure can be rolled back.
        snapshots: Dict[str, Optional[bytes]] = {}
        try:
            for file_patch in file_patches:
                target_rel = file_patch.target_path
                if target_rel in snapshots:
                    continue
                target = self._resolve_in_workspace(workspace_root, target_rel)
                if target.exists() and target.is_file():
                    snapshots[target_rel] = target.read_bytes()
                else:
                    snapshots[target_rel] = None
        except OSError as exc:
            return False, f"Could not snapshot workspace state: {exc}", None

        if create_backup:
            backup_path = self._write_backup(snapshots, workspace_root)

        # ---- Compute every new content in memory first -----------------
        prepared: List[Tuple[str, Path, Optional[bytes]]] = []
        try:
            for file_patch in file_patches:
                target_rel = file_patch.target_path
                target = self._resolve_in_workspace(workspace_root, target_rel)

                if file_patch.is_deletion:
                    prepared.append((target_rel, target, None))
                    continue

                if not target.exists():
                    content = "\n".join(
                        text
                        for hunk in file_patch.hunks
                        for tag, text in hunk.lines
                        if tag == "+"
                    )
                    payload = (content + "\n").encode("utf-8") if content else b""
                    self._check_result_syntax(target_rel, payload.decode("utf-8"))
                else:
                    existing = target.read_text(encoding="utf-8")
                    updated = self._apply_hunks_to_text(existing, file_patch.hunks)
                    # The result must still be valid source code - a patch
                    # that breaks the syntax is rejected instead of being
                    # written to disk.
                    self._check_result_syntax(target_rel, updated)
                    payload = updated.encode("utf-8")

                prepared.append((target_rel, target, payload))
        except PatchApplyError as exc:
            return (
                False,
                f"Failed to apply patch: {exc} (no files were modified)",
                backup_path,
            )
        except (OSError, UnicodeDecodeError) as exc:
            return (
                False,
                f"Failed to prepare patch content: {exc} (no files were modified)",
                backup_path,
            )

        # ---- Write phase (atomic per file, rolled back on failure) ----
        written: List[str] = []
        try:
            for target_rel, target, payload in prepared:
                if payload is None:
                    # Deletion.
                    if target.exists():
                        target.unlink()
                        written.append(target_rel)
                    continue

                target.parent.mkdir(parents=True, exist_ok=True)
                self._atomic_write(target, payload)
                written.append(target_rel)
        except (OSError, PatchApplyError) as exc:
            self._rollback(workspace_root, snapshots, written)
            return (
                False,
                f"Failed to apply patch: {exc} (workspace rolled back)",
                backup_path,
            )

        return (
            True,
            "Patch applied successfully to {0} file(s): {1}".format(
                len(written), ", ".join(written) or "none"
            ),
            backup_path,
        )

    # ------------------------------------------------------------------
    # Application internals
    # ------------------------------------------------------------------

    @staticmethod
    def _atomic_write(target: Path, payload: bytes) -> None:
        """Write a file atomically via a temporary file in the same folder."""
        tmp_path = target.with_name(target.name + ".fixpilot-tmp")
        try:
            with open(tmp_path, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, target)
        except OSError:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            raise

    def _rollback(
        self,
        workspace_root: Path,
        snapshots: Dict[str, Optional[bytes]],
        written: Sequence[str],
    ) -> None:
        """Restore the original content of every file that was touched."""
        for target_rel in written:
            try:
                target = self._resolve_in_workspace(workspace_root, target_rel)
                original = snapshots.get(target_rel)
                if original is None:
                    if target.exists():
                        target.unlink()
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    self._atomic_write(target, original)
            except OSError as exc:  # pragma: no cover - defensive
                logger.error("Rollback of %s failed: %s", target_rel, exc)

    def _write_backup(
        self,
        snapshots: Dict[str, Optional[bytes]],
        workspace_root: Path,
    ) -> Optional[Path]:
        """Store a copy of the affected files outside the workspace."""
        try:
            backup_dir = Path(tempfile.mkdtemp(prefix="fixpilot_backup_"))
            for target_rel, original in snapshots.items():
                if original is None:
                    continue
                backup_file = backup_dir / target_rel.replace("/", os.sep)
                backup_file.parent.mkdir(parents=True, exist_ok=True)
                backup_file.write_bytes(original)
            return backup_dir
        except OSError as exc:
            logger.warning("Could not create patch backup: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Hunk application
    # ------------------------------------------------------------------

    def _parse_unified_diff(
        self, patch_text: str
    ) -> Dict[str, List[Tuple[Optional[int], List[Tuple[str, str]]]]]:
        """Parse unified diff text into per-file lists of hunks.

        Kept for backwards compatibility; the canonical parser is
        :func:`parse_unified_diff`.
        """
        result: Dict[str, List[Tuple[Optional[int], List[Tuple[str, str]]]]] = {}
        for file_patch in parse_unified_diff(patch_text):
            result[file_patch.target_path] = [
                (hunk.old_start, list(hunk.lines)) for hunk in file_patch.hunks
            ]
        return result

    def _apply_hunks_to_text(
        self,
        text: str,
        hunks: Any,
    ) -> str:
        """Apply a sequence of hunks to source text, honouring line offsets.

        Args:
            text: The original file content.
            hunks: Either a list of :class:`Hunk` objects or the legacy
                ``(old_start, [(tag, text), ...])`` tuples.

        Returns:
            The updated file content.
        """
        normalized: List[Tuple[Optional[int], List[Tuple[str, str]]]] = []
        for hunk in hunks:
            if isinstance(hunk, Hunk):
                normalized.append((hunk.old_start, list(hunk.lines)))
            else:
                normalized.append((hunk[0], list(hunk[1])))

        newline = "\r\n" if "\r\n" in text else "\n"
        trailing_newline = text.endswith("\n")
        lines = text.splitlines()
        shift = 0

        for old_start, hunk_lines in normalized:
            old_lines = [l for tag, l in hunk_lines if tag in (" ", "-")]
            new_lines = [l for tag, l in hunk_lines if tag in (" ", "+")]

            anchor = None
            if old_start is not None:
                anchor = max(old_start - 1 + shift, 0)

            position = self._locate_hunk(lines, old_lines, anchor)
            if position is None:
                # The model's context was imperfect (it dropped or altered a
                # context line). Fall back to locating the *removed* lines
                # alone and replacing only those - the way GNU patch's fuzz
                # works. Lines the diff does not mention are never touched.
                removed = [l for tag, l in hunk_lines if tag == "-"]
                added = [l for tag, l in hunk_lines if tag == "+"]
                fuzz_position = self._find_sequence(lines, removed, anchor)
                if fuzz_position is not None:
                    lines[fuzz_position:fuzz_position + len(removed)] = added
                    shift += len(added) - len(removed)
                    continue
                raise PatchApplyError(
                    f"hunk context not found near line {old_start if old_start else '?'}"
                )

            lines[position:position + len(old_lines)] = new_lines
            shift += len(new_lines) - len(old_lines)

        result = newline.join(lines)
        if trailing_newline:
            result += newline
        return result

    @staticmethod
    def _check_result_syntax(target_rel: str, content: str) -> None:
        """Reject a patch result that would not compile.

        A patch produced by a language model regularly has a context line
        with the wrong indentation. Applying such a patch "successfully"
        rewrites the indentation of the target file and the result is a
        syntactically broken file - which then shows up later as a bogus
        "regression" instead of a patch failure.

        Compiling the result catches that class of bug *before* anything is
        written to disk.

        Args:
            target_rel: The workspace-relative path of the patched file.
            content: The new file content.

        Raises:
            PatchApplyError: If the result is not valid Python.
        """
        if not target_rel.lower().endswith(".py"):
            return
        try:
            compile(content, target_rel, "exec")
        except SyntaxError as exc:
            raise PatchApplyError(
                "the patched file would not compile ({0} at line {1}: {2})".format(
                    exc.msg, exc.lineno, exc.text.strip() if exc.text else "?"
                )
            ) from exc
        except ValueError as exc:  # e.g. source containing null bytes
            raise PatchApplyError(
                f"the patched file is not valid source code ({exc})"
            ) from exc

    @staticmethod
    def _locate_hunk(
        lines: List[str], old_lines: List[str], anchor: Optional[int]
    ) -> Optional[int]:
        """Find the index in ``lines`` where ``old_lines`` should be applied."""
        if not old_lines:
            return anchor if anchor is not None else 0

        # 1. Exact match at (or very near) the declared offset.
        if anchor is not None:
            window = 20
            for offset in range(0, window + 1):
                for candidate in (anchor - offset, anchor + offset):
                    if candidate < 0 or candidate + len(old_lines) > len(lines):
                        continue
                    if lines[candidate:candidate + len(old_lines)] == old_lines:
                        return candidate

        # 2. Exact match anywhere in the file.
        for candidate in range(0, len(lines) - len(old_lines) + 1):
            if lines[candidate:candidate + len(old_lines)] == old_lines:
                return candidate

        # NOTE: a whitespace-insensitive match is deliberately NOT attempted
        # here. Matching "    total += i" against "        total += i" would
        # silently rewrite the indentation of the target file and produce a
        # syntactically broken file (which then shows up as a bogus
        # "regression"). A patch whose context does not match exactly must
        # fail instead - see _apply_hunks_to_text for the safe fuzz fallback.

        return None

    @staticmethod
    def _find_sequence(
        lines: List[str], sequence: List[str], anchor: Optional[int] = None
    ) -> Optional[int]:
        """Find a contiguous run of ``sequence`` inside ``lines``.

        Used for the "fuzz" fallback: when a model emits a hunk whose context
        lines do not match the file exactly, the removed lines themselves are
        still authoritative. If the run occurs more than once and no match is
        close to the declared offset, ``None`` is returned so the caller
        fails instead of guessing.
        """
        if not sequence:
            return None

        matches = [
            index
            for index in range(0, len(lines) - len(sequence) + 1)
            if lines[index:index + len(sequence)] == sequence
        ]

        if not matches:
            return None

        if len(matches) == 1:
            return matches[0]

        if anchor is not None:
            matches.sort(key=lambda index: abs(index - anchor))
            if abs(matches[0] - anchor) <= 20:
                return matches[0]

        # Ambiguous - refuse rather than patch the wrong location.
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def patch_hash(patch: str) -> str:
        """Return a stable hash of a patch, used to detect repeated patches."""
        return compute_patch_hash(patch)
