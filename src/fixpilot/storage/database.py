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
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fixpilot.schemas.state import FixPilotState
from fixpilot.schemas.repair_plan import RepairPlan
from fixpilot.schemas.patch import PatchResult


class StorageError(Exception):
    """Raised when a storage operation fails."""
    pass


class Database:
    """SQLite database for FixPilot run history persistence."""

    def __init__(self, db_path: str = "artifacts/fixpilot.sqlite3"):
        self.db_path = db_path
        self._ensure_dirs()
        self._conn = None
        self._connect()

    def _ensure_dirs(self):
        """Ensure the directory for the database file exists."""
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

    def _connect(self):
        """Establish a connection to the SQLite database."""
        try:
            self._conn = sqlite3.connect(self.db_path)
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
                error_summary TEXT
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

        self._conn.commit()

    def create_run(self, run_id: str, config: Dict[str, Any]) -> str:
        """Create a new run record.

        Args:
            run_id: Unique run identifier.
            config: FixPilot configuration.

        Returns:
            The run_id that was created.
        """
        now = os.popen("date -u +%Y-%m-%dT%H:%M:%SZ").read().strip()
        try:
            self._conn.execute(
                """
                INSERT INTO runs (
                    run_id, target_display_path, started_at, status, mode,
                    model_name, error_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    config.get("target_path", ""),
                    now,
                    "PENDING",
                    config.get("mode", "safe"),
                    config.get("FIXPILOT_MODEL", ""),
                    "",
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
        now = os.popen("date -u +%Y-%m-%dT%H:%M:%SZ").read().strip() or finished_at
        self._conn.execute(
            """
            UPDATE runs
            SET status = ?, finished_at = ?, final_exit_code = ?, error_summary = ?
            WHERE run_id = ?
            """,
            (status, now, exit_code, error_summary, run_id),
        )
        self._conn.commit()

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
        now = os.popen("date -u +%Y-%m-%dT%H:%M:%SZ").read().strip()
        patch_summary = patch.patch_summary if patch else ""
        patch_path = patch.patch if patch else ""

        try:
            self._conn.execute(
                """
                INSERT INTO attempts (
                    attempt_id, run_id, attempt_number, root_cause_summary,
                    patch_summary, patch_path, approval_status, test_status,
                    verification_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    run_id,
                    attempt_number,
                    patch.root_cause_summary if patch else "",
                    patch_summary,
                    patch_path,
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
        verification_status: str = None
    ):
        """Update an attempt's test and verification status.

        Args:
            attempt_id: The attempt identifier.
            test_status: The test result status.
            verification_status: The verification result status.
        """
        updates = []
        params = []

        if test_status is not None:
            updates.append("test_status = ?")
            params.append(test_status)
        if verification_status is not None:
            updates.append("verification_status = ?")
            params.append(verification_status)

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

        # Generate Markdown report
        report_lines = [
            f"# FixPilot AI Repair Report",
            f"**Run ID:** {run.get('run_id', 'N/A')}",
            f"**Version:** 0.1.0",
            "",
            "## Run Metadata",
            f"- **Target:** {run.get('target_display_path', 'N/A')}",
            f"- **Status:** {run.get('status', 'N/A').upper()}",
            f"- **Start:** {run.get('started_at', 'N/A')}",
            f"- **Finish:** {run.get('finished_at', 'N/A')}",
            f"- **Mode:** {run.get('mode', 'N/A')}",
            f"- **Model:** {run.get('model_name', 'N/A')}",
            f"- **Baseline Exit Code:** {run.get('baseline_exit_code', 'N/A')}",
            f"- **Final Exit Code:** {run.get('final_exit_code', 'N/A')}",
            f"- **Retry Count:** {run.get('retry_count', 'N/A')}",
            "",
            "## Attempt History",
        ]

        for attempt in attempts:
            report_lines.append(
                f"### Attempt {attempt.get('attempt_number', 'N/A')}"
            )
            report_lines.append(f"- **Status:** {attempt.get('verification_status', 'N/A').upper()}")
            report_lines.append(f"- **Test Status:** {attempt.get('test_status', 'N/A')}")
            report_lines.append(f"- **Approval:** {attempt.get('approval_status', 'N/A')}")
            report_lines.append(f"- **Patch Summary:** {attempt.get('patch_summary', 'N/A')}")
            report_lines.append(f"- **Created:** {attempt.get('created_at', 'N/A')}")
            report_lines.append("")

        report_lines.extend([
            "## Limitations",
            "* LLM diagnosis may be wrong or incomplete",
            "* Passing tests do not guarantee correctness",
            "* Docker isolation is not a perfect security guarantee",
            "* First release supports Python projects only",
            "",
            "---\n*Report generated by FixPilot AI*"
        ])

        return "\n".join(report_lines)

    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None