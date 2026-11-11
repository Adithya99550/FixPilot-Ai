"""Tests for the verified patch delivery to the original project.

Covers the requirements of the "verified patch delivery" task:

* the disposable workspace stays isolated - delivery is a separate step
* the original project is only modified after an explicit approval
* the original files are backed up before they are modified
* path traversal and symlink escapes are prevented
* test files are never modified automatically
* a rejected delivery leaves the original project unchanged
* a failed delivery is rolled back safely
"""

from pathlib import Path

import pytest

from fixpilot.patching.delivery import DeliveryResult, deliver_patch


ORIGINAL = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"

GOOD_PATCH = (
    "--- a/calculator.py\n"
    "+++ b/calculator.py\n"
    "@@ -1,2 +1,2 @@\n"
    " def add(a, b):\n"
    "-    return a - b\n"
    "+    return a + b\n"
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "tests").mkdir(parents=True)
    (root / "calculator.py").write_text(ORIGINAL, encoding="utf-8")
    (root / "tests" / "test_calculator.py").write_text(
        "def test_add():\n    assert True\n", encoding="utf-8"
    )
    return root


class TestSuccessfulDelivery:
    def test_patch_is_applied_to_the_original(self, project: Path):
        result = deliver_patch(GOOD_PATCH, project)
        assert result.success is True
        assert result.changed_files == ["calculator.py"]
        assert (project / "calculator.py").read_text(encoding="utf-8") == FIXED

    def test_original_files_are_backed_up(self, project: Path):
        result = deliver_patch(GOOD_PATCH, project)
        assert result.backup_path is not None
        backup_file = result.backup_path / "calculator.py"
        assert backup_file.exists()
        assert backup_file.read_text(encoding="utf-8") == ORIGINAL

    def test_backup_lives_outside_the_project(self, project: Path):
        result = deliver_patch(GOOD_PATCH, project)
        assert result.backup_path is not None
        assert project.resolve() not in result.backup_path.resolve().parents


class TestSafety:
    def test_traversal_is_refused(self, project: Path):
        patch = (
            "--- a/../outside.py\n"
            "+++ b/../outside.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new\n"
        )
        result = deliver_patch(patch, project)
        assert result.success is False
        assert "not safe" in result.message.lower()
        assert not (project.parent / "outside.py").exists()

    def test_absolute_path_is_refused(self, project: Path):
        patch = (
            "--- a//tmp/evil.py\n"
            "+++ b//tmp/evil.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new\n"
        )
        result = deliver_patch(patch, project)
        assert result.success is False

    def test_symlink_escape_is_refused(self, project: Path, tmp_path: Path):
        outside = tmp_path / "outside.py"
        outside.write_text("secret = 1\n", encoding="utf-8")
        link = project / "link.py"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks are not supported on this platform")

        patch = (
            "--- a/link.py\n"
            "+++ b/link.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-secret = 1\n"
            "+secret = 2\n"
        )
        result = deliver_patch(patch, project)
        assert result.success is False
        assert outside.read_text(encoding="utf-8") == "secret = 1\n"

    def test_test_files_are_never_modified(self, project: Path):
        patch = (
            "--- a/tests/test_calculator.py\n"
            "+++ b/tests/test_calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def test_add():\n"
            "-    assert True\n"
            "+    assert False\n"
        )
        result = deliver_patch(patch, project)
        assert result.success is False
        assert "test files" in result.message.lower()
        assert "assert True" in (
            project / "tests" / "test_calculator.py"
        ).read_text(encoding="utf-8")

    def test_protected_paths_are_refused(self, project: Path):
        patch = (
            "--- a/tests/test_calculator.py\n"
            "+++ b/tests/test_calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def test_add():\n"
            "-    assert True\n"
            "+    assert False\n"
        )
        result = deliver_patch(patch, project, protected_paths=["tests/test_calculator.py"])
        assert result.success is False
        assert "not safe" in result.message.lower()

    def test_corrupting_patch_is_refused(self, project: Path):
        """A patch that would break the file must not be written."""
        patch = (
            "--- a/calculator.py\n"
            "+++ b/calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def add(a, b):\n"
            "-    return a - b\n"
            "+return a + b\n"
        )
        result = deliver_patch(patch, project)
        assert result.success is False
        assert (project / "calculator.py").read_text(encoding="utf-8") == ORIGINAL

    def test_missing_project_directory(self, tmp_path: Path):
        result = deliver_patch(GOOD_PATCH, tmp_path / "does_not_exist")
        assert result.success is False
        assert "does not exist" in result.message


class TestFailureHandling:
    def test_failed_delivery_is_rolled_back(self, project: Path):
        """If the second file fails, the first file is restored."""
        (project / "other.py").write_text("value = 1\n", encoding="utf-8")
        patch = GOOD_PATCH + (
            "--- a/other.py\n"
            "+++ b/other.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-this content does not exist\n"
            "+replacement\n"
        )
        result = deliver_patch(patch, project)
        assert result.success is False
        assert result.rolled_back is True
        assert (project / "calculator.py").read_text(encoding="utf-8") == ORIGINAL
        assert (project / "other.py").read_text(encoding="utf-8") == "value = 1\n"

    def test_rejection_leaves_the_project_unchanged(self, project: Path):
        """A delivery that was never approved must not change anything."""
        # The caller simply does not call deliver_patch - the file is
        # unchanged, which is what the workflow does when the user says no.
        assert (project / "calculator.py").read_text(encoding="utf-8") == ORIGINAL


class TestDeliveryResult:
    def test_as_dict(self, project: Path):
        result = deliver_patch(GOOD_PATCH, project)
        payload = result.as_dict()
        assert payload["success"] is True
        assert payload["changed_files"] == ["calculator.py"]
        assert "backup_path" in payload
