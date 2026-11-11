"""Tests for the FixPilot markdown report generator."""

from fixpilot.reporting.markdown_report import generate_markdown_report


def _run(**overrides):
    data = {
        "run_id": "run_test",
        "status": "SUCCESS",
        "target_display_path": "/tmp/project",
        "mode": "repair",
        "model_name": "gemini-1.5-flash",
        "started_at": "2026-01-01T00:00:00Z",
        "finished_at": "2026-01-01T00:01:00Z",
        "error_summary": "",
    }
    data.update(overrides)
    return data


def _attempt(**overrides):
    attempt = {
        "attempt_number": 1,
        "verification_status": "SUCCESS",
        "test_status": "PASS",
        "approval_status": "APPROVED",
        "root_cause_summary": "Off by one",
        "patch_summary": "Fixed the range",
        "patch_diff": "--- a/a.py\n+++ b/a.py\n",
        "created_at": "2026-01-01T00:00:30Z",
    }
    attempt.update(overrides)
    return attempt


class TestReportGeneration:
    def test_report_contains_the_run_metadata(self):
        report = generate_markdown_report(_run(), [_attempt()])
        assert "FixPilot AI Repair Report" in report
        assert "run_test" in report
        assert "SUCCESS" in report
        assert "/tmp/project" in report
        assert "gemini-1.5-flash" in report

    def test_report_lists_the_attempts(self):
        report = generate_markdown_report(
            _run(), [_attempt(), _attempt(attempt_number=2, verification_status="RETRY")]
        )
        assert "Attempt 1" in report
        assert "Attempt 2" in report
        assert "Off by one" in report
        assert "RETRY" in report

    def test_report_without_attempts(self):
        report = generate_markdown_report(_run(), [])
        assert "No attempts were recorded" in report

    def test_report_includes_the_error_summary(self):
        report = generate_markdown_report(_run(status="FAILED", error_summary="boom"), [])
        assert "Error Summary" in report
        assert "boom" in report

    def test_report_includes_the_patch_diff(self):
        report = generate_markdown_report(_run(), [_attempt()])
        assert "Applied Patch Diff" in report
        assert "--- a/a.py" in report

    def test_report_reflects_the_real_status(self):
        """A failed run must not be rendered as a success."""
        report = generate_markdown_report(
            _run(status="REPAIR_FAILED", error_summary="no patch"), []
        )
        assert "REPAIR_FAILED" in report
        assert "**Status:** **SUCCESS**" not in report

    def test_report_contains_the_limitations(self):
        report = generate_markdown_report(_run(), [])
        assert "Honest Limitations" in report

    def test_missing_keys_do_not_crash_the_report(self):
        report = generate_markdown_report({}, [])
        assert "FixPilot AI Repair Report" in report
