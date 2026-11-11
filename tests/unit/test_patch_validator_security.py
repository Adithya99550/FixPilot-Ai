"""Security tests for the FixPilot patch validator.

These tests cover the acceptance criteria of the "harden unified diff patch
validation" task:

* absolute paths, Windows drive paths and UNC paths are rejected
* ``../`` traversal is rejected
* symlink escapes are rejected
* a valid nested workspace file is accepted
* an invalid patch can never modify a file
* every file of a multi-file patch is validated
* malformed / unsupported diff headers are rejected
"""

from pathlib import Path

import pytest

from fixpilot.patching.validator import (
    PatchApplier,
    PatchValidationError,
    normalize_diff_path,
    parse_unified_diff,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A disposable workspace with a couple of source files."""
    ws = tmp_path / "workspace"
    (ws / "pkg").mkdir(parents=True)
    (ws / "pkg" / "calculator.py").write_text(
        "def add(a, b):\n    return a - b\n", encoding="utf-8"
    )
    (ws / "app.py").write_text("value = 1\n", encoding="utf-8")
    return ws


def _diff(path: str, body: str = "-old\n+new\n") -> str:
    """Build a minimal, valid unified diff for ``path``."""
    return f"--- a/{path}\n+++ b/{path}\n@@ -1,1 +1,1 @@\n{body}"


class TestNormalizeDiffPath:
    """Path normalisation must be shared by validator and applier."""

    def test_strips_a_prefix(self):
        assert normalize_diff_path("a/src/app.py") == "src/app.py"

    def test_strips_b_prefix(self):
        assert normalize_diff_path("b/src/app.py") == "src/app.py"

    def test_keeps_real_directory_named_a(self):
        """A directory that is literally called ``a`` is preserved."""
        assert normalize_diff_path("a/a/app.py") == "a/app.py"

    def test_dev_null_marker(self):
        assert normalize_diff_path("/dev/null") is None

    def test_strips_timestamp(self):
        assert normalize_diff_path("app.py\t2024-01-01 10:00:00") == "app.py"

    def test_converts_backslashes(self):
        assert normalize_diff_path("src\\app.py") == "src/app.py"


class TestPathTraversalRejected:
    """Unsafe target paths must be rejected."""

    @pytest.mark.parametrize(
        "path",
        [
            "/etc/passwd",
            "/tmp/evil.py",
            "C:/Windows/System32/config",
            "c:\\Windows\\System32\\config",
            "\\\\server\\share\\evil.py",
            "../outside.py",
            "../../etc/passwd",
            "..\\outside.py",
            "pkg/../../outside.py",
            "a/../../../etc/passwd",
        ],
    )
    def test_unsafe_path_rejected(self, workspace: Path, path: str):
        applier = PatchApplier()
        is_valid, reason = applier.validate_patch(_diff(path), workspace)
        assert is_valid is False
        assert reason

    def test_null_byte_rejected(self, workspace: Path):
        applier = PatchApplier()
        is_valid, reason = applier.validate_patch(
            _diff("app.py\x00.txt"), workspace
        )
        assert is_valid is False
        assert "null byte" in reason.lower()

    def test_empty_path_rejected(self, workspace: Path):
        applier = PatchApplier()
        is_valid, reason = applier.validate_patch(
            "--- a/\n+++ b/\n@@ -1,1 +1,1 @@\n-x\n+y\n", workspace
        )
        assert is_valid is False
        assert reason


class TestSymlinkEscape:
    """A symlink must not be used to escape the workspace."""

    def test_symlink_escape_rejected(self, workspace: Path, tmp_path: Path):
        outside = tmp_path / "outside.py"
        outside.write_text("secret = 1\n", encoding="utf-8")
        link = workspace / "link.py"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks are not supported on this platform")

        applier = PatchApplier()
        is_valid, reason = applier.validate_patch(_diff("link.py"), workspace)
        assert is_valid is False
        assert "outside" in reason.lower()

    def test_symlink_in_subdirectory_rejected(self, workspace: Path, tmp_path: Path):
        outside_dir = tmp_path / "outside_dir"
        outside_dir.mkdir()
        (outside_dir / "target.py").write_text("x = 1\n", encoding="utf-8")
        link_dir = workspace / "linked"
        try:
            link_dir.symlink_to(outside_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks are not supported on this platform")

        applier = PatchApplier()
        is_valid, reason = applier.validate_patch(
            _diff("linked/target.py"), workspace
        )
        assert is_valid is False
        assert reason


class TestValidPatchAccepted:
    """Legitimate patches inside the workspace must be accepted."""

    def test_nested_workspace_file_accepted(self, workspace: Path):
        applier = PatchApplier()
        is_valid, reason = applier.validate_patch(
            _diff("pkg/calculator.py"), workspace
        )
        assert is_valid is True, reason

    def test_top_level_file_accepted(self, workspace: Path):
        applier = PatchApplier()
        is_valid, reason = applier.validate_patch(_diff("app.py"), workspace)
        assert is_valid is True, reason

    def test_multi_file_patch_accepted(self, workspace: Path):
        patch = (
            _diff("app.py")
            + _diff("pkg/calculator.py")
        )
        applier = PatchApplier()
        is_valid, reason = applier.validate_patch(patch, workspace)
        assert is_valid is True, reason


class TestInvalidPatchCannotModifyFiles:
    """Validation always happens before a single byte is written."""

    def test_traversal_patch_changes_nothing(self, workspace: Path):
        applier = PatchApplier()
        patch = _diff("../outside.py")
        is_valid, _ = applier.validate_patch(patch, workspace)
        assert is_valid is False

        applied, message, _ = applier.apply_patch(patch, workspace)
        assert applied is False
        assert message

        # The workspace is untouched.
        assert (workspace / "app.py").read_text(encoding="utf-8") == "value = 1\n"
        assert (
            workspace / "pkg" / "calculator.py"
        ).read_text(encoding="utf-8") == "def add(a, b):\n    return a - b\n"

    def test_multi_file_patch_with_one_bad_file_changes_nothing(self, workspace: Path):
        """A patch where only the *second* file is unsafe must be rejected
        entirely - the valid first file must not be modified."""
        applier = PatchApplier()
        patch = _diff("app.py") + _diff("../outside.py")

        is_valid, reason = applier.validate_patch(patch, workspace)
        assert is_valid is False
        assert reason

        applied, message, _ = applier.apply_patch(patch, workspace)
        assert applied is False
        assert (workspace / "app.py").read_text(encoding="utf-8") == "value = 1\n"

    def test_absolute_path_patch_changes_nothing(self, workspace: Path):
        applier = PatchApplier()
        patch = _diff("/tmp/evil.py")
        applied, _, _ = applier.apply_patch(patch, workspace)
        assert applied is False


class TestMalformedPatches:
    """Malformed or unsupported diffs must be rejected."""

    def test_missing_headers(self, workspace: Path):
        applier = PatchApplier()
        is_valid, reason = applier.validate_patch(
            "@@ -1,1 +1,1 @@\n-old\n+new\n", workspace
        )
        assert is_valid is False
        assert "file header" in reason.lower() or "header" in reason.lower()

    def test_new_header_without_old_header(self, workspace: Path):
        applier = PatchApplier()
        is_valid, reason = applier.validate_patch(
            "+++ b/app.py\n@@ -1,1 +1,1 @@\n-old\n+new\n", workspace
        )
        assert is_valid is False
        assert reason

    def test_malformed_hunk_header(self, workspace: Path):
        applier = PatchApplier()
        is_valid, reason = applier.validate_patch(
            "--- a/app.py\n+++ b/app.py\n@@ nonsense @@\n-old\n+new\n", workspace
        )
        assert is_valid is False
        assert "hunk header" in reason.lower()

    def test_hunk_line_count_mismatch(self, workspace: Path):
        applier = PatchApplier()
        is_valid, reason = applier.validate_patch(
            "--- a/app.py\n+++ b/app.py\n@@ -1,5 +1,5 @@\n-old\n+new\n", workspace
        )
        assert is_valid is False
        assert "malformed" in reason.lower()

    def test_binary_patch_rejected(self, workspace: Path):
        applier = PatchApplier()
        is_valid, reason = applier.validate_patch(
            "Binary files a/app.py and b/app.py differ\n", workspace
        )
        assert is_valid is False
        assert "binary" in reason.lower()

    def test_rename_rejected(self, workspace: Path):
        applier = PatchApplier()
        is_valid, reason = applier.validate_patch(
            "diff --git a/app.py b/other.py\n"
            "rename from app.py\nrename to other.py\n"
            "--- a/app.py\n+++ b/other.py\n@@ -1,1 +1,1 @@\n-old\n+new\n",
            workspace,
        )
        assert is_valid is False
        assert "rename" in reason.lower()

    def test_empty_patch_rejected(self, workspace: Path):
        applier = PatchApplier()
        is_valid, reason = applier.validate_patch("", workspace)
        assert is_valid is False
        assert "empty" in reason.lower()

    def test_patch_without_changes_rejected(self, workspace: Path):
        applier = PatchApplier()
        is_valid, reason = applier.validate_patch(
            "--- a/app.py\n+++ b/app.py\n@@ -1,1 +1,1 @@\n value = 1\n", workspace
        )
        assert is_valid is False
        assert "actual changes" in reason.lower()

    def test_parser_raises_on_malformed_diff(self):
        with pytest.raises(PatchValidationError):
            parse_unified_diff("not a diff at all")


class TestCreationAndDeletion:
    """File creation/deletion must be explicitly supported."""

    def test_creation_rejected_by_default(self, workspace: Path):
        applier = PatchApplier()
        is_valid, reason = applier.validate_patch(
            "--- /dev/null\n+++ b/new_file.py\n@@ -0,0 +1,1 @@\n+new = 1\n",
            workspace,
        )
        assert is_valid is False
        assert "creation" in reason.lower()

    def test_creation_allowed_when_configured(self, workspace: Path):
        applier = PatchApplier({"allow_file_creation": True})
        is_valid, reason = applier.validate_patch(
            "--- /dev/null\n+++ b/new_file.py\n@@ -0,0 +1,1 @@\n+new = 1\n",
            workspace,
        )
        assert is_valid is True, reason

    def test_deletion_rejected_by_default(self, workspace: Path):
        applier = PatchApplier()
        is_valid, reason = applier.validate_patch(
            "--- a/app.py\n+++ /dev/null\n@@ -1,1 +0,0 @@\n-value = 1\n", workspace
        )
        assert is_valid is False
        assert "deletion" in reason.lower()

    def test_missing_target_file_rejected(self, workspace: Path):
        applier = PatchApplier()
        is_valid, reason = applier.validate_patch(
            _diff("does_not_exist.py"), workspace
        )
        assert is_valid is False
        assert "does not exist" in reason.lower()


class TestProtectedPaths:
    """Sensitive files must never be patched."""

    @pytest.mark.parametrize(
        "path",
        [".env", ".git/config", "artifacts/fixpilot.sqlite3", "fixpilot.toml"],
    )
    def test_protected_path_rejected(self, workspace: Path, path: str):
        applier = PatchApplier()
        is_valid, reason = applier.validate_patch(_diff(path), workspace)
        assert is_valid is False
        assert "protected" in reason.lower()

    def test_plan_protected_path_rejected(self, workspace: Path):
        applier = PatchApplier({"protected_paths": ["tests/test_app.py"]})
        is_valid, reason = applier.validate_patch(
            _diff("tests/test_app.py"), workspace
        )
        assert is_valid is False
        assert "forbids" in reason.lower()


class TestLimits:
    """The configured patch size limits are enforced."""

    def test_too_many_files_rejected(self, workspace: Path):
        applier = PatchApplier({"max_files_changed": 1})
        patch = _diff("app.py") + _diff("pkg/calculator.py")
        is_valid, reason = applier.validate_patch(patch, workspace)
        assert is_valid is False
        assert "exceeding" in reason.lower()

    def test_too_many_lines_rejected(self, workspace: Path):
        applier = PatchApplier({"max_changed_lines": 1})
        body = "".join(f"-line{i}\n+line{i}\n" for i in range(5))
        patch = f"--- a/app.py\n+++ b/app.py\n@@ -1,5 +1,5 @@\n{body}"
        is_valid, reason = applier.validate_patch(patch, workspace)
        assert is_valid is False
        assert "exceeding" in reason.lower()
