"""Tests for the FixPilot patch applier.

Covers the atomicity / rollback requirements of phase 3:

* invalid patches cannot alter source files
* a failed patch application leaves the workspace in a consistent state
* the original repository remains unchanged by default
"""

from pathlib import Path

import pytest

from fixpilot.patching.validator import PatchApplier


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "calculator.py").write_text(
        "def add(a, b):\n    return a - b\n", encoding="utf-8"
    )
    (ws / "app.py").write_text("value = 1\n", encoding="utf-8")
    return ws


def _diff(path: str, old: str, new: str) -> str:
    return (
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -1,1 +1,1 @@\n"
        f"-{old}\n"
        f"+{new}\n"
    )


class TestApplyPatch:
    def test_apply_patch_in_place(self, temp_workspace: Path):
        diff = (
            "--- a/calculator.py\n"
            "+++ b/calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def add(a, b):\n"
            "-    return a - b\n"
            "+    return a + b\n"
        )

        applier = PatchApplier()
        is_valid, _ = applier.validate_patch(diff, temp_workspace)
        assert is_valid

        success, msg, _ = applier.apply_patch(diff, temp_workspace)
        assert success, msg
        assert "calculator.py" in msg

        result_code = (temp_workspace / "calculator.py").read_text(encoding="utf-8")
        assert "return a + b" in result_code
        assert "return a - b" not in result_code

    def test_apply_multi_file_patch(self, temp_workspace: Path):
        patch = _diff("app.py", "value = 1", "value = 2") + _diff(
            "calculator.py", "def add(a, b):", "def add(a, b, c=0):"
        )
        applier = PatchApplier()
        success, msg, _ = applier.apply_patch(patch, temp_workspace)
        assert success, msg
        assert "value = 2" in (temp_workspace / "app.py").read_text(encoding="utf-8")
        assert "def add(a, b, c=0):" in (
            temp_workspace / "calculator.py"
        ).read_text(encoding="utf-8")

    def test_backup_is_created_outside_the_workspace(self, temp_workspace: Path):
        patch = _diff("app.py", "value = 1", "value = 2")
        applier = PatchApplier()
        success, _, backup_path = applier.apply_patch(
            patch, temp_workspace, create_backup=True
        )
        assert success
        assert backup_path is not None
        assert temp_workspace.resolve() not in backup_path.resolve().parents
        assert (backup_path / "app.py").read_text(encoding="utf-8") == "value = 1\n"


class TestAtomicityAndRollback:
    def test_invalid_patch_does_not_touch_any_file(self, temp_workspace: Path):
        applier = PatchApplier()
        patch = _diff("app.py", "value = 1", "value = 2") + _diff(
            "../outside.py", "old", "new"
        )
        success, message, _ = applier.apply_patch(patch, temp_workspace)
        assert success is False
        assert message
        assert (temp_workspace / "app.py").read_text(encoding="utf-8") == "value = 1\n"

    def test_failed_hunk_leaves_workspace_consistent(self, temp_workspace: Path):
        """A hunk whose context does not exist must not modify anything."""
        applier = PatchApplier()
        patch = (
            "--- a/app.py\n"
            "+++ b/app.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-this line does not exist\n"
            "+replacement\n"
        )
        success, message, _ = applier.apply_patch(patch, temp_workspace)
        assert success is False
        assert message
        assert (temp_workspace / "app.py").read_text(encoding="utf-8") == "value = 1\n"

    def test_failed_multi_file_patch_rolls_back_first_file(self, temp_workspace: Path):
        """When the second file fails, the first file is restored."""
        applier = PatchApplier()
        patch = _diff("app.py", "value = 1", "value = 2") + (
            "--- a/calculator.py\n"
            "+++ b/calculator.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-completely different content\n"
            "+replacement\n"
        )
        success, message, _ = applier.apply_patch(patch, temp_workspace)
        assert success is False
        assert "no files were modified" in message.lower()
        assert (temp_workspace / "app.py").read_text(encoding="utf-8") == "value = 1\n"
        assert (temp_workspace / "calculator.py").read_text(encoding="utf-8") == (
            "def add(a, b):\n    return a - b\n"
        )

    def test_no_temporary_files_are_left_behind(self, temp_workspace: Path):
        applier = PatchApplier()
        patch = _diff("app.py", "value = 1", "value = 2")
        applier.apply_patch(patch, temp_workspace)
        leftovers = [p.name for p in temp_workspace.iterdir() if ".fixpilot-tmp" in p.name]
        assert leftovers == []


class TestValidatorApplierConsistency:
    """The validator and the applier must agree on the target paths."""

    def test_applied_file_is_the_validated_file(self, temp_workspace: Path):
        applier = PatchApplier()
        patch = _diff("pkg/nested.py", "old", "new")
        # The file does not exist -> creation is not allowed by default.
        is_valid, reason = applier.validate_patch(patch, temp_workspace)
        assert is_valid is False
        applied, _, _ = applier.apply_patch(patch, temp_workspace)
        assert applied is False
        assert not (temp_workspace / "pkg" / "nested.py").exists()

    def test_validated_paths_are_applied(self, temp_workspace: Path):
        applier = PatchApplier()
        patch = _diff("app.py", "value = 1", "value = 2")
        is_valid, reason = applier.validate_patch(patch, temp_workspace)
        assert is_valid is True, reason
        applied, _, _ = applier.apply_patch(patch, temp_workspace)
        assert applied is True
        assert (temp_workspace / "app.py").read_text(encoding="utf-8") == "value = 2\n"


class TestIndentationSafety:
    """Regression tests for the bug that made a correct patch look like a
    regression.

    A language model regularly reproduces a context line with the wrong
    indentation. Matching such a context line "approximately" rewrote the
    indentation of the target file and produced a syntactically broken file,
    which later showed up as a bogus "regression" instead of a patch
    failure.
    """

    SOURCE = (
        "def sum_range(n):\n"
        "    total = 0\n"
        "    for i in range(1, n):  # off by one\n"
        "        total += i\n"
        "    return total\n"
    )

    #: The model produced a context line with 4 instead of 8 spaces.
    WRONG_INDENT_CONTEXT = (
        "--- a/sum_range.py\n"
        "+++ b/sum_range.py\n"
        "@@ -2,3 +2,3 @@\n"
        "     total = 0\n"
        "-    for i in range(1, n):  # off by one\n"
        "+    for i in range(1, n + 1):  # off by one\n"
        "     total += i\n"
    )

    def test_wrong_indentation_does_not_corrupt_the_file(self, tmp_path: Path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        (workspace / "sum_range.py").write_text(self.SOURCE, encoding="utf-8")

        applier = PatchApplier()
        success, message, _ = applier.apply_patch(
            self.WRONG_INDENT_CONTEXT, workspace
        )
        assert success, message

        result = (workspace / "sum_range.py").read_text(encoding="utf-8")
        # The change was applied ...
        assert "range(1, n + 1)" in result
        # ... and the indentation of the untouched line is intact.
        assert "        total += i" in result
        # The result is valid Python.
        compile(result, "sum_range.py", "exec")

    def test_patch_that_breaks_the_syntax_is_rejected(self, tmp_path: Path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        (workspace / "sum_range.py").write_text(self.SOURCE, encoding="utf-8")

        corrupting = (
            "--- a/sum_range.py\n"
            "+++ b/sum_range.py\n"
            "@@ -1,4 +1,4 @@\n"
            " def sum_range(n):\n"
            "     total = 0\n"
            "     for i in range(1, n):  # off by one\n"
            "-        total += i\n"
            "+    total += i\n"
        )
        applier = PatchApplier()
        success, message, _ = applier.apply_patch(corrupting, workspace)
        assert success is False
        assert "would not compile" in message
        # The original file is untouched.
        assert (workspace / "sum_range.py").read_text(encoding="utf-8") == self.SOURCE


class TestPatchHash:
    def test_hash_is_stable(self):
        patch = _diff("app.py", "value = 1", "value = 2")
        assert PatchApplier.patch_hash(patch) == PatchApplier.patch_hash(patch)

    def test_hash_differs_for_different_patches(self):
        a = _diff("app.py", "value = 1", "value = 2")
        b = _diff("app.py", "value = 1", "value = 3")
        assert PatchApplier.patch_hash(a) != PatchApplier.patch_hash(b)

    def test_hash_ignores_trailing_whitespace(self):
        a = _diff("app.py", "value = 1", "value = 2")
        b = a + "\n\n"
        assert PatchApplier.patch_hash(a) == PatchApplier.patch_hash(b)
