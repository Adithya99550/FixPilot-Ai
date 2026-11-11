"""Tests for the FixPilot storage layer."""

from pathlib import Path

import pytest

from fixpilot.schemas.patch import PatchResult
from fixpilot.storage.database import Database, Storage, StorageError


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    return Storage(str(tmp_path / "fixpilot.sqlite3"), reports_dir=str(tmp_path / "reports"))


@pytest.fixture
def patch() -> PatchResult:
    return PatchResult(
        patch="--- a/a.py\n+++ b/a.py\n@@ -1,1 +1,1 @@\n-old\n+new\n",
        patch_summary="A summary",
        root_cause_summary="The root cause",
        approval_status="pending",
    )


class TestRunPersistence:
    def test_run_is_created_and_completed(self, storage: Storage):
        storage.start_run("run_1", {"target_path": "/tmp/project", "mode": "repair"})
        run = storage.get_run("run_1")
        assert run is not None
        assert run["status"] == "PENDING"
        assert run["target_display_path"] == "/tmp/project"

        storage.complete_run("run_1", "SUCCESS", 0, "")
        run = storage.get_run("run_1")
        assert run["status"] == "SUCCESS"
        assert run["finished_at"]
        assert run["final_exit_code"] == 0

    def test_unknown_run_returns_none(self, storage: Storage):
        assert storage.get_run("does_not_exist") is None

    def test_duplicate_run_id_raises(self, storage: Storage):
        storage.start_run("run_dup", {})
        with pytest.raises(StorageError):
            storage.start_run("run_dup", {})

    def test_failed_run_is_persisted_with_the_error(self, storage: Storage):
        storage.start_run("run_fail", {})
        storage.complete_run("run_fail", "FAILED", 1, "something went wrong")
        run = storage.get_run("run_fail")
        assert run["status"] == "FAILED"
        assert run["error_summary"] == "something went wrong"

    def test_final_test_results_are_persisted(self, storage: Storage):
        storage.start_run("run_res", {})
        storage.update_run_results(
            "run_res",
            test_status="PASS",
            test_exit_code=0,
            test_output="2 passed",
            attempt_count=1,
            baseline_exit_code=1,
        )
        run = storage.get_run("run_res")
        assert run["final_test_status"] == "PASS"
        assert run["final_test_exit_code"] == 0
        assert run["final_test_output"] == "2 passed"
        assert run["attempt_count"] == 1
        assert run["baseline_exit_code"] == 1

    def test_list_runs(self, storage: Storage):
        for i in range(3):
            storage.start_run(f"run_{i}", {})
        runs = storage.list_runs()
        assert len(runs) == 3

    def test_list_runs_filtered_by_status(self, storage: Storage):
        storage.start_run("run_a", {})
        storage.complete_run("run_a", "SUCCESS", 0, "")
        storage.start_run("run_b", {})
        storage.complete_run("run_b", "FAILED", 1, "boom")
        assert len(storage.list_runs(status="SUCCESS")) == 1
        assert len(storage.list_runs(status="FAILED")) == 1


class TestAttemptPersistence:
    def test_attempt_is_created_and_updated(self, storage: Storage, patch: PatchResult):
        storage.start_run("run_1", {})
        storage.create_attempt("att_1", "run_1", 1, patch, {})
        attempts = storage.get_run_attempts("run_1")
        assert len(attempts) == 1
        assert attempts[0]["patch_summary"] == "A summary"
        assert attempts[0]["patch_diff"]
        assert attempts[0]["test_status"] == "pending"

        storage.update_attempt("att_1", "PASS", "SUCCESS", "APPROVED")
        attempt = storage.get_run_attempts("run_1")[0]
        assert attempt["test_status"] == "PASS"
        assert attempt["verification_status"] == "SUCCESS"
        assert attempt["approval_status"] == "APPROVED"

    def test_failed_attempt_is_persisted(self, storage: Storage, patch: PatchResult):
        storage.start_run("run_2", {})
        storage.create_attempt("att_2", "run_2", 1, patch, {})
        storage.update_attempt("att_2", "FAIL", "STOP", "REJECTED")
        attempt = storage.get_run_attempts("run_2")[0]
        assert attempt["test_status"] == "FAIL"
        assert attempt["verification_status"] == "STOP"

    def test_attempts_are_ordered(self, storage: Storage, patch: PatchResult):
        storage.start_run("run_3", {})
        for i in (1, 2, 3):
            storage.create_attempt(f"att_{i}", "run_3", i, patch, {})
        attempts = storage.get_run_attempts("run_3")
        assert [a["attempt_number"] for a in attempts] == [1, 2, 3]

    def test_duplicate_attempt_id_raises(self, storage: Storage, patch: PatchResult):
        storage.start_run("run_4", {})
        storage.create_attempt("att_dup", "run_4", 1, patch, {})
        with pytest.raises(StorageError):
            storage.create_attempt("att_dup", "run_4", 1, patch, {})


class TestReports:
    def test_report_is_generated(self, storage: Storage, patch: PatchResult):
        storage.start_run("run_rep", {"target_path": "/tmp/project"})
        storage.complete_run("run_rep", "SUCCESS", 0, "")
        storage.create_attempt("att_rep", "run_rep", 1, patch, {})
        storage.update_attempt("att_rep", "PASS", "SUCCESS", "APPROVED")

        report = storage.export_report("run_rep")
        assert report is not None
        assert "run_rep" in report
        assert "SUCCESS" in report

    def test_report_is_saved_to_disk(self, storage: Storage, tmp_path: Path):
        storage.start_run("run_save", {})
        storage.complete_run("run_save", "SUCCESS", 0, "")
        path = storage.save_report("run_save")
        assert path is not None and path.exists()
        assert "run_save" in path.read_text(encoding="utf-8")

    def test_report_for_unknown_run_is_none(self, storage: Storage):
        assert storage.export_report("nope") is None
        assert storage.save_report("nope") is None


class TestDatabaseErrors:
    def test_invalid_database_path_raises_storage_error(self, tmp_path: Path):
        blocked = tmp_path / "blocked"
        blocked.write_text("not a directory", encoding="utf-8")
        with pytest.raises(StorageError):
            Database(str(blocked / "sub" / "db.sqlite3"))

    def test_corrupted_database_is_handled(self, tmp_path: Path):
        db_file = tmp_path / "broken.sqlite3"
        db_file.write_bytes(b"this is definitely not a sqlite database" * 10)
        with pytest.raises(StorageError):
            Database(str(db_file))

    def test_update_on_unknown_run_does_not_crash(self, storage: Storage):
        # No exception is raised - the run simply does not exist.
        storage.update_run_results("missing", test_status="PASS")
        assert storage.get_run("missing") is None

    def test_close_releases_the_connection(self, storage: Storage):
        storage.db.close()
        assert storage.db._conn is None
