"""FixPilot AI storage package.

Provides SQLite-based persistence for run history, attempts, and reports.
Exports: Database, Storage, StorageError
"""

from fixpilot.storage.database import Database, Storage, StorageError

__all__ = ["Database", "Storage", "StorageError"]