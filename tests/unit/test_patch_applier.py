"""Unit tests for PatchApplier hunk application."""

import tempfile
import shutil
from pathlib import Path
import pytest

from fixpilot.patching.validator import PatchApplier


@pytest.fixture
def temp_workspace():
    temp_dir = tempfile.mkdtemp(prefix="fixpilot_patch_test_")
    ws = Path(temp_dir)
    yield ws
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_apply_patch_in_place(temp_workspace):
    # Create target file with code
    target = temp_workspace / "calculator.py"
    target.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

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
    assert success
    assert "calculator.py" in target.name

    result_code = target.read_text(encoding="utf-8")
    assert "return a + b" in result_code
    assert "return a - b" not in result_code

