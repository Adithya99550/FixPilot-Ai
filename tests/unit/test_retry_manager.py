"""Tests for the FixPilot retry manager."""


from fixpilot.agents.retry_manager import RetryManager
from fixpilot.schemas.patch import PatchResult


def _patch(text="--- a/a.py\n+++ b/a.py\n@@ -1,1 +1,1 @@\n-old\n+new\n"):
    return PatchResult(patch=text, patch_summary="summary")


class TestShouldRetry:
    def test_success_does_not_retry(self):
        manager = RetryManager({"FIXPILOT_MAX_RETRIES": 3})
        assert manager.should_retry({"status": "success"}) is False

    def test_regression_does_not_retry(self):
        manager = RetryManager({"FIXPILOT_MAX_RETRIES": 3})
        assert manager.should_retry({"status": "regression", "new_failures": ["x"]}) is False

    def test_stop_without_evidence_does_not_retry(self):
        manager = RetryManager({"FIXPILOT_MAX_RETRIES": 3})
        assert manager.should_retry({"status": "stop"}) is False

    def test_stop_with_evidence_retries(self):
        manager = RetryManager({"FIXPILOT_MAX_RETRIES": 3})
        outcome = manager.should_retry(
            {"status": "stop", "previously_failing_now_passing": ["t1"]}
        )
        assert outcome is True

    def test_retry_with_evidence_retries(self):
        manager = RetryManager({"FIXPILOT_MAX_RETRIES": 3})
        outcome = manager.should_retry(
            {"status": "retry", "previously_failing_now_passing": ["t1"]}
        )
        assert outcome is True

    def test_retry_limit_is_enforced(self):
        manager = RetryManager({"FIXPILOT_MAX_RETRIES": 2})
        assert manager.should_retry(
            {"status": "retry", "previously_failing_now_passing": ["t1"]}
        ) is True
        assert manager.should_retry(
            {"status": "retry", "previously_failing_now_passing": ["t1"]}
        ) is False

    def test_max_retries_can_be_configured(self):
        manager = RetryManager({"max_retries": 1})
        assert manager.should_retry(
            {"status": "retry", "previously_failing_now_passing": ["t1"]}
        ) is False


class TestRecordAttempt:
    def test_record_attempt_stores_the_outcome(self):
        manager = RetryManager({"FIXPILOT_MAX_RETRIES": 3})
        manager.record_attempt(
            attempt_number=1,
            patch=_patch(),
            verification={
                "status": "retry",
                "new_failures": [],
                "previously_failing_now_passing": ["t1"],
                "evidence": "partial",
            },
        )
        assert len(manager.retry_history) == 1
        record = manager.retry_history[0]
        assert record["status"] == "retry"
        assert record["patch_hash"]

    def test_duplicate_patches_are_detected(self):
        manager = RetryManager({"FIXPILOT_MAX_RETRIES": 3})
        patch = _patch()
        assert manager.is_duplicate_patch(patch) is False
        manager.record_attempt(
            attempt_number=1,
            patch=patch,
            verification={"status": "retry", "previously_failing_now_passing": ["t"]},
        )
        assert manager.is_duplicate_patch(patch) is True

    def test_different_patches_are_not_duplicates(self):
        manager = RetryManager({"FIXPILOT_MAX_RETRIES": 3})
        manager.record_attempt(
            attempt_number=1,
            patch=_patch(),
            verification={"status": "retry", "previously_failing_now_passing": ["t"]},
        )
        other = _patch("--- a/b.py\n+++ b/b.py\n@@ -1,1 +1,1 @@\n-x\n+y\n")
        assert manager.is_duplicate_patch(other) is False
