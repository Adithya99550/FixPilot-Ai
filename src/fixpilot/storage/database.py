"""FixPilot AI storage module.

Responsibilities:
- Implement SQLite schema/migrations.
- Store runs and attempts.
- Provide history/show/export commands.
- Handle database lock and corruption errors gracefully.

Following §11 and §12 of PROJECT_SPEC.md.
"""

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional



class StorageError(Exception):
    """Raised when a storage operation fails."""
    pass


class Database:
    """SQLite database for FixPilot run history persistence."""

    def __init__(self, db_path: str = "artifacts/fixpilot.sqlite3", reports_dir: str = "reports"):
        self.db_path = db_path
        self.reports_dir = Path(reports_dir)
        self._ensure_dirs()
        self._conn = None
        self._connect()

    def _ensure_dirs(self):
        """Ensure the directory for the database file and reports directory exist."""
        try:
            db_dir = Path(self.db_path).parent
            db_dir.mkdir(parents=True, exist_ok=True)
            self.reports_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError(
                f"Failed to create the storage directories for {self.db_path}: {exc}"
            ) from exc

    def _connect(self):
        """Establish a connection to the SQLite database."""
        try:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._create_tables()
        except sqlite3.Error as e:
            raise StorageError(f"Failed to connect to database: {e}")

    def _create_tables(self):
        """Create database tables if they don't exist."""
        cursor = self._conn.cursor()

        # Create runs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                target_display_path TEXT,
                started_at TEXT,
                finished_at TEXT,
                status TEXT,
                mode TEXT,
                baseline_exit_code INTEGER,
                final_exit_code INTEGER,
                retry_count INTEGER,
                model_name TEXT,
                report_path TEXT,
                error_summary TEXT,
                -- Multi-language support
                language TEXT,
                test_framework TEXT,
                test_command TEXT,
                build_command TEXT,
                repo_url TEXT,
                branch TEXT,
                "commit" TEXT
            )
        """)

        # Create attempts table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attempts (
                attempt_id TEXT PRIMARY KEY,
                run_id TEXT,
                attempt_number INTEGER,
                root_cause_summary TEXT,
                patch_summary TEXT,
                patch_path TEXT,
                approval_status TEXT,
                applied_at TEXT,
                test_status TEXT,
                verification_status TEXT,
                created_at TEXT,
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            )
        """)

        # Create events table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                timestamp TEXT,
                stage TEXT,
                level TEXT,
                message TEXT,
                metadata_json TEXT
            )
        """)

        # Migration: store the applied diff separately from the patch path.
        attempt_columns = [
            row[1] for row in cursor.execute("PRAGMA table_info(attempts)").fetchall()
        ]
        if "patch_diff" not in attempt_columns:
            cursor.execute("ALTER TABLE attempts ADD COLUMN patch_diff TEXT")

        # Migration: persist the final test outcome of a run so reports and
        # the dashboard can show what actually happened.
        run_columns = [
            row[1] for row in cursor.execute("PRAGMA table_info(runs)").fetchall()
        ]
        for column, ddl in (
            ("final_test_status", "TEXT"),
            ("final_test_exit_code", "INTEGER"),
            ("final_test_output", "TEXT"),
            ("attempt_count", "INTEGER"),
        ):
            if column not in run_columns:
                cursor.execute(f"ALTER TABLE runs ADD COLUMN {column} {ddl}")

        # Create audits table (static bug scan results)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audits (
                audit_id TEXT PRIMARY KEY,
                target_path TEXT,
                timestamp TEXT,
                scanned_files_count INTEGER,
                findings_json TEXT,
                summary TEXT
            )
        """)

        # Create reviews table (code quality review results)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                review_id TEXT PRIMARY KEY,
                target_path TEXT,
                timestamp TEXT,
                scanned_files_count INTEGER,
                issues_json TEXT,
                metrics_json TEXT,
                summary TEXT
            )
        """)

        self._conn.commit()

    def create_run(self, run_id: str, config: Dict[str, Any]) -> str:
        """Create a new run record.

        Args:
            run_id: Unique run identifier.
            config: FixPilot configuration.

        Returns:
            The run_id that was created.
        """
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            self._conn.execute(
                """
                INSERT INTO runs (
                    run_id, target_display_path, started_at, status, mode,
                    model_name, error_summary,
                    language, test_framework, test_command, build_command,
                    repo_url, branch, "commit"
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    config.get("target_path", ""),
                    now,
                    "PENDING",
                    config.get("mode", "safe"),
                    config.get("FIXPILOT_MODEL", ""),
                    "",
                    config.get("language", config.get("FIXPILOT_LANGUAGE", "")),
                    config.get("test_framework", config.get("FIXPILOT_TEST_FRAMEWORK", "")),
                    config.get("test_command", config.get("FIXPILOT_TEST_COMMAND", "")),
                    config.get("build_command", config.get("FIXPILOT_BUILD_COMMAND", "")),
                    config.get("repo_url", config.get("FIXPILOT_REPO_URL", "")),
                    config.get("branch", config.get("FIXPILOT_BRANCH", "")),
                    config.get("commit", config.get("FIXPILOT_COMMIT", "")),
                ),
            )
            self._conn.commit()
            return run_id
        except sqlite3.IntegrityError:
            raise StorageError(f"Run ID {run_id} already exists")

    def update_run_status(
        self, run_id: str, status: str, finished_at: str = None,
        exit_code: int = None, error_summary: str = None
    ):
        """Update a run's status and final metrics.

        Args:
            run_id: The run identifier.
            status: The new status.
            finished_at: ISO timestamp of completion.
            exit_code: Final exit code.
            error_summary: Summary of any error.
        """
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") or finished_at
        try:
            self._conn.execute(
                """
                UPDATE runs
                SET status = ?, finished_at = ?, final_exit_code = ?, error_summary = ?
                WHERE run_id = ?
                """,
                (status, now, exit_code, error_summary, run_id),
            )
            self._conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to update run {run_id}: {exc}")

    def update_run_results(
        self,
        run_id: str,
        test_status: str = None,
        test_exit_code: int = None,
        test_output: str = None,
        attempt_count: int = None,
        baseline_exit_code: int = None,
        retry_count: int = None,
    ):
        """Persist the final test outcome of a run.

        Args:
            run_id: The run identifier.
            test_status: PASS / FAIL / TIMEOUT / ERROR / NOT_RUN.
            test_exit_code: Exit code of the final test run.
            test_output: (Truncated) output of the final test run.
            attempt_count: Number of repair attempts that were made.
            baseline_exit_code: Exit code of the baseline (pre-repair) run.
            retry_count: Number of retries that were made (attempts - 1).
        """
        updates = []
        params = []

        if test_status is not None:
            updates.append("final_test_status = ?")
            params.append(test_status)
        if test_exit_code is not None:
            updates.append("final_test_exit_code = ?")
            params.append(test_exit_code)
        if test_output is not None:
            updates.append("final_test_output = ?")
            params.append(test_output)
        if attempt_count is not None:
            updates.append("attempt_count = ?")
            params.append(attempt_count)
        if baseline_exit_code is not None:
            updates.append("baseline_exit_code = ?")
            params.append(baseline_exit_code)
        if retry_count is not None:
            updates.append("retry_count = ?")
            params.append(retry_count)

        if not updates:
            return

        params.append(run_id)
        try:
            self._conn.execute(
                f"UPDATE runs SET {', '.join(updates)} WHERE run_id = ?",
                params,
            )
            self._conn.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"Failed to store run results for {run_id}: {exc}")

    def create_attempt(
        self,
        attempt_id: str,
        run_id: str,
        attempt_number: int,
        patch: Any,
        config: Dict[str, Any],
    ) -> str:
        """Create a new attempt record.

        Args:
            attempt_id: Unique attempt identifier.
            run_id: Associated run identifier.
            attempt_number: The attempt number (1-indexed).
            patch: PatchResult object.
            config: FixPilot configuration.

        Returns:
            The attempt_id that was created.
        """
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        patch_summary = patch.patch_summary if patch else ""
        patch_diff = patch.patch if patch else ""

        # Persist the diff as a real artifact so ``patch_path`` points at a
        # file on disk (PROJECT_SPEC §11.1) and the diff survives a restart.
        patch_path = ""
        if patch_diff:
            try:
                artifact_dir = self.reports_dir / "patches"
                artifact_dir.mkdir(parents=True, exist_ok=True)
                artifact = artifact_dir / f"{attempt_id}.patch"
                artifact.write_text(patch_diff, encoding="utf-8")
                patch_path = str(artifact)
            except OSError:
                patch_path = ""

        try:
            self._conn.execute(
                """
                INSERT INTO attempts (
                    attempt_id, run_id, attempt_number, root_cause_summary,
                    patch_summary, patch_path, patch_diff, approval_status,
                    test_status, verification_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    run_id,
                    attempt_number,
                    patch.root_cause_summary if patch else "",
                    patch_summary,
                    patch_path,
                    patch_diff,
                    patch.approval_status if patch else "pending",
                    "pending",
                    "pending",
                    now,
                ),
            )
            self._conn.commit()
            return attempt_id
        except sqlite3.IntegrityError:
            raise StorageError(f"Attempt ID {attempt_id} already exists")

    def update_attempt_status(
        self, attempt_id: str, test_status: str = None,
        verification_status: str = None, approval_status: str = None
    ):
        """Update an attempt's test, verification and approval status.

        Args:
            attempt_id: The attempt identifier.
            test_status: The test result status.
            verification_status: The verification result status.
            approval_status: The approval decision (e.g. APPROVED / REJECTED).
        """
        updates = []
        params = []

        if test_status is not None:
            updates.append("test_status = ?")
            params.append(test_status)
        if verification_status is not None:
            updates.append("verification_status = ?")
            params.append(verification_status)
        if approval_status is not None:
            updates.append("approval_status = ?")
            params.append(approval_status)
        if test_status is not None or verification_status is not None:
            # The attempt reached the point where it was actually executed.
            updates.append("applied_at = ?")
            params.append(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

        if updates:
            params.append(attempt_id)
            self._conn.execute(
                f"UPDATE attempts SET {', '.join(updates)} WHERE attempt_id = ?",
                params,
            )
            self._conn.commit()

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get a run record by ID.

        Args:
            run_id: The run identifier.

        Returns:
            Dict with run data, or None if not found.
        """
        cursor = self._conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        )
        row = cursor.fetchone()
        if row is None:
            return None

        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))

    def get_run_attempts(self, run_id: str) -> List[Dict[str, Any]]:
        """Get all attempts for a run.

        Args:
            run_id: The run identifier.

        Returns:
            List of attempt dicts.
        """
        cursor = self._conn.execute(
            "SELECT * FROM attempts WHERE run_id = ? ORDER BY attempt_number",
            (run_id,),
        )
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def list_runs(self, limit: int = 50, status: str = None) -> List[Dict[str, Any]]:
        """List runs with optional filtering.

        Args:
            limit: Maximum number of runs to return.
            status: Optional status filter.

        Returns:
            List of run dicts.
        """
        query = "SELECT run_id, started_at, status, mode FROM runs"
        params = []

        if status:
            query += " WHERE status = ?"
            params.append(status)

        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)

        cursor = self._conn.execute(query, params)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def export_report(self, run_id: str) -> Optional[str]:
        """Export a Markdown report for a run.

        Args:
            run_id: The run identifier.

        Returns:
            Markdown report content, or None if run not found.
        """
        run = self.get_run(run_id)
        if run is None:
            return None

        attempts = self.get_run_attempts(run_id)

        # Single source of truth for report rendering.
        from fixpilot.reporting.markdown_report import generate_markdown_report

        return generate_markdown_report(run, attempts)

    def save_report_text(self, run_id: str, report: str) -> Optional[Path]:
        """Save a pre-rendered Markdown report for a run.

        Args:
            run_id: The run identifier.
            report: The already-rendered Markdown content.

        Returns:
            Path to the saved report file, or None if the run is unknown.
        """
        if self.get_run(run_id) is None:
            return None
        report_path = self.reports_dir / f"fixpilot_report_{run_id}.md"
        report_path.write_text(report, encoding="utf-8")
        return report_path

    def save_report(self, run_id: str) -> Optional[Path]:
        """Save a Markdown report for a run to the reports directory.

        The path is also stored on the run row so the database can point at
        the generated artifact (PROJECT_SPEC §12.1).

        Args:
            run_id: The run identifier.

        Returns:
            Path to the saved report file, or None if run not found.
        """
        report = self.export_report(run_id)
        if report is None:
            return None

        report_path = self.reports_dir / f"fixpilot_report_{run_id}.md"
        report_path.write_text(report, encoding="utf-8")
        self._set_report_path(run_id, str(report_path))
        return report_path

    def _set_report_path(self, run_id: str, report_path: str) -> None:
        """Store the generated report path on the run row."""
        try:
            self._conn.execute(
                "UPDATE runs SET report_path = ? WHERE run_id = ?",
                (report_path, run_id),
            )
            self._conn.commit()
        except sqlite3.Error:
            pass

    def log_event(
        self,
        run_id: str,
        stage: str,
        message: str = "",
        level: str = "INFO",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append an audit-log entry for a workflow stage.

        The events table is the audit trail of the state machine described in
        PROJECT_SPEC §6.1.

        Args:
            run_id: The run identifier.
            stage: The workflow stage (e.g. "SCAN_PROJECT").
            message: A human readable message.
            level: Severity of the event.
            metadata: Optional structured metadata (JSON encoded).
        """
        try:
            self._conn.execute(
                """
                INSERT INTO events (run_id, timestamp, stage, level, message, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    stage,
                    level,
                    message,
                    json.dumps(metadata) if metadata else None,
                ),
            )
            self._conn.commit()
        except sqlite3.Error:
            pass

    def set_run_toolchain(
        self,
        run_id: str,
        language: str,
        test_framework: str,
        test_command: str = "",
        build_command: str = "",
    ) -> None:
        """Record the detected toolchain on the run row.

        The run row is created before the toolchain is detected, so the
        detected values have to be written back afterwards.
        """
        try:
            self._conn.execute(
                """
                UPDATE runs
                SET language = ?, test_framework = ?, test_command = ?, build_command = ?
                WHERE run_id = ?
                """,
                (language, test_framework, test_command, build_command, run_id),
            )
            self._conn.commit()
        except sqlite3.Error:
            pass

    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def save_audit(self, audit: Any) -> Optional[str]:
        """Persist a static analysis audit result.

        Args:
            audit: An AuditResult model.

        Returns:
            The stored audit id, or None if the audit is invalid.
        """
        if audit is None:
            return None
        try:
            self._conn.execute(
                """
                INSERT INTO audits (
                    audit_id, target_path, timestamp, scanned_files_count,
                    findings_json, summary
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    audit.audit_id,
                    audit.target_path,
                    audit.timestamp,
                    audit.scanned_files_count,
                    json.dumps([f.model_dump() for f in audit.findings]),
                    audit.summary,
                ),
            )
            self._conn.commit()
            return audit.audit_id
        except sqlite3.Error:
            return None

    def save_review(self, review: Any) -> Optional[str]:
        """Persist a code quality review result.

        Args:
            review: A ReviewResult model.

        Returns:
            The stored review id, or None if the review is invalid.
        """
        if review is None:
            return None
        try:
            self._conn.execute(
                """
                INSERT INTO reviews (
                    review_id, target_path, timestamp, scanned_files_count,
                    issues_json, metrics_json, summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review.review_id,
                    review.target_path,
                    review.timestamp,
                    review.scanned_files_count,
                    json.dumps([i.model_dump() for i in review.issues]),
                    json.dumps(review.metrics),
                    review.summary,
                ),
            )
            self._conn.commit()
            return review.review_id
        except sqlite3.Error:
            return None


class Storage:
    """High-level storage operations for FixPilot."""

    def __init__(self, db_path: str = "artifacts/fixpilot.sqlite3", reports_dir: str = "reports"):
        self.db = Database(db_path, reports_dir)

    def start_run(self, run_id: str, config: Dict[str, Any]) -> str:
        return self.db.create_run(run_id, config)

    def complete_run(
        self,
        run_id: str,
        status: str,
        exit_code: int = None,
        error_summary: str = None,
    ):
        # NOTE: update_run_status signature is
        # (run_id, status, finished_at, exit_code, error_summary).
        # Pass by keyword so the exit code cannot land in finished_at.
        self.db.update_run_status(
            run_id,
            status,
            exit_code=exit_code,
            error_summary=error_summary,
        )

    def update_run_results(
        self,
        run_id: str,
        test_status: str = None,
        test_exit_code: int = None,
        test_output: str = None,
        attempt_count: int = None,
        baseline_exit_code: int = None,
        retry_count: int = None,
    ):
        """Persist the final test outcome of a run."""
        self.db.update_run_results(
            run_id,
            test_status=test_status,
            test_exit_code=test_exit_code,
            test_output=test_output,
            attempt_count=attempt_count,
            baseline_exit_code=baseline_exit_code,
            retry_count=retry_count,
        )

    def record_attempt(
        self,
        attempt_id: str,
        run_id: str,
        attempt_number: int,
        patch: Any,
        config: Dict[str, Any],
    ) -> str:
        return self.db.create_attempt(attempt_id, run_id, attempt_number, patch, config)

    create_attempt = record_attempt

    def update_attempt(
        self, attempt_id: str, test_status: str = None,
        verification_status: str = None, approval_status: str = None
    ):
        self.db.update_attempt_status(
            attempt_id, test_status, verification_status, approval_status
        )

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        return self.db.get_run(run_id)

    def get_run_attempts(self, run_id: str) -> List[Dict[str, Any]]:
        return self.db.get_run_attempts(run_id)

    def list_runs(self, limit: int = 50, status: str = None) -> List[Dict[str, Any]]:
        return self.db.list_runs(limit, status)

    def export_report(self, run_id: str) -> Optional[str]:
        return self.db.export_report(run_id)

    def save_report_text(self, run_id: str, report: str) -> Optional[Path]:
        """Save a pre-rendered Markdown report for a run."""
        return self.db.save_report_text(run_id, report)

    def save_report(self, run_id: str) -> Optional[Path]:
        """Save a Markdown report for a run to the reports directory."""
        return self.db.save_report(run_id)

    def save_audit(self, audit: Any) -> Optional[str]:
        """Persist a static analysis audit result."""
        return self.db.save_audit(audit)

    def save_review(self, review: Any) -> Optional[str]:
        """Persist a code quality review result."""
        return self.db.save_review(review)

    def log_event(
        self,
        run_id: str,
        stage: str,
        message: str = "",
        level: str = "INFO",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append an audit-log entry for a workflow stage."""
        self.db.log_event(run_id, stage, message, level, metadata)

    def set_run_toolchain(
        self,
        run_id: str,
        language: str,
        test_framework: str,
        test_command: str = "",
        build_command: str = "",
    ) -> None:
        """Record the detected toolchain on the run row.

        The run row is created before the toolchain is detected, so the
        detected values have to be written back afterwards.
        """
        self.db.set_run_toolchain(
            run_id, language, test_framework, test_command, build_command
        )