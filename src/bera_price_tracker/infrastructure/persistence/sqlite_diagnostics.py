"""Strictly read-only diagnostics for the configured SQLite database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from bera_price_tracker.application.diagnostics import (
    DatabaseDiagnostic,
    DatabaseDiagnosticsRepository,
    DatabaseState,
)
from bera_price_tracker.infrastructure.persistence.migrations import MIGRATIONS

_DEFAULT_BUSY_TIMEOUT_MS = 5_000
_REQUIRED_TABLES = frozenset(
    {"schema_migrations", "listings", "collection_runs", "price_snapshots"}
)


class SQLiteDatabaseDiagnostics(DatabaseDiagnosticsRepository):
    """Inspect SQLite availability and compatibility without changing the target."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        busy_timeout_ms: int = _DEFAULT_BUSY_TIMEOUT_MS,
    ) -> None:
        if busy_timeout_ms <= 0:
            raise ValueError("busy_timeout_ms must be greater than zero")

        target = str(database_path)
        if not target.strip():
            raise ValueError("database_path must not be blank")

        self._database_path = target
        self._busy_timeout_ms = busy_timeout_ms

    def inspect(self) -> DatabaseDiagnostic:
        """Return a sanitized database diagnostic using a ``mode=ro`` connection."""

        expected_versions = frozenset(migration.version for migration in MIGRATIONS)
        expected_schema_version = max(expected_versions, default=0)
        path = Path(self._database_path).expanduser()
        wal_path = Path(f"{path}-wal")

        try:
            if not path.exists():
                return self._result(
                    exists=False,
                    state=DatabaseState.NOT_INITIALIZED,
                    schema_version=None,
                    expected_schema_version=expected_schema_version,
                    detail="database is not initialized",
                )
            if not path.is_file():
                return self._result(
                    exists=True,
                    state=DatabaseState.ERROR,
                    schema_version=None,
                    expected_schema_version=expected_schema_version,
                    detail="database path is not a file",
                )
            if wal_path.exists():
                return self._result(
                    exists=True,
                    state=DatabaseState.ERROR,
                    schema_version=None,
                    expected_schema_version=expected_schema_version,
                    detail="database has an active write-ahead log; retry when it is idle",
                )
            database_uri = f"{path.resolve().as_uri()}?mode=ro&immutable=1"
        except OSError:
            return self._result(
                exists=True,
                state=DatabaseState.ERROR,
                schema_version=None,
                expected_schema_version=expected_schema_version,
                detail="could not inspect database path",
            )

        try:
            connection = sqlite3.connect(database_uri, uri=True, isolation_level=None)
        except (OSError, sqlite3.Error):
            return self._result(
                exists=True,
                state=DatabaseState.ERROR,
                schema_version=None,
                expected_schema_version=expected_schema_version,
                detail="could not open database in read-only mode",
            )

        close_failed = False
        try:
            result = self._inspect_connection(
                connection,
                expected_versions=expected_versions,
                expected_schema_version=expected_schema_version,
            )
        finally:
            try:
                connection.close()
            except sqlite3.Error:
                close_failed = True
        if close_failed:
            return self._result(
                exists=True,
                state=DatabaseState.ERROR,
                schema_version=result.schema_version,
                expected_schema_version=expected_schema_version,
                detail="could not close database after inspection",
            )
        try:
            if wal_path.exists():
                return self._result(
                    exists=True,
                    state=DatabaseState.ERROR,
                    schema_version=result.schema_version,
                    expected_schema_version=expected_schema_version,
                    detail="database changed during inspection; retry when it is idle",
                )
        except OSError:
            return self._result(
                exists=True,
                state=DatabaseState.ERROR,
                schema_version=result.schema_version,
                expected_schema_version=expected_schema_version,
                detail="could not verify database stability after inspection",
            )
        return result

    def _inspect_connection(
        self,
        connection: sqlite3.Connection,
        *,
        expected_versions: frozenset[int],
        expected_schema_version: int,
    ) -> DatabaseDiagnostic:
        try:
            connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms:d}")
            connection.execute("PRAGMA query_only = ON")
            query_only = connection.execute("PRAGMA query_only").fetchone()
            if query_only is None or int(query_only[0]) != 1:
                return self._result(
                    exists=True,
                    state=DatabaseState.ERROR,
                    schema_version=None,
                    expected_schema_version=expected_schema_version,
                    detail="could not enable SQLite read-only safeguards",
                )
        except (TypeError, ValueError, sqlite3.Error):
            return self._result(
                exists=True,
                state=DatabaseState.ERROR,
                schema_version=None,
                expected_schema_version=expected_schema_version,
                detail="could not enable SQLite read-only safeguards",
            )

        try:
            schema_probe = connection.execute("PRAGMA schema_version").fetchone()
            if schema_probe is None:
                raise sqlite3.DatabaseError("schema probe returned no result")
            table_rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        except sqlite3.Error:
            return self._result(
                exists=True,
                state=DatabaseState.ERROR,
                schema_version=None,
                expected_schema_version=expected_schema_version,
                detail="file is not a readable SQLite database",
            )

        available_tables = {str(row[0]) for row in table_rows}
        missing_tables = _REQUIRED_TABLES - available_tables
        if "schema_migrations" not in available_tables:
            return self._result(
                exists=True,
                state=DatabaseState.INCOMPATIBLE,
                schema_version=None,
                expected_schema_version=expected_schema_version,
                detail=self._missing_tables_detail(missing_tables),
            )

        try:
            version_rows = connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
            applied_versions = frozenset(self._stored_version(row[0]) for row in version_rows)
        except (TypeError, ValueError, sqlite3.Error):
            return self._result(
                exists=True,
                state=DatabaseState.INCOMPATIBLE,
                schema_version=None,
                expected_schema_version=expected_schema_version,
                detail="schema migration metadata is incompatible",
            )

        schema_version = max(applied_versions, default=0)
        if missing_tables:
            return self._result(
                exists=True,
                state=DatabaseState.INCOMPATIBLE,
                schema_version=schema_version,
                expected_schema_version=expected_schema_version,
                detail=self._missing_tables_detail(missing_tables),
            )
        if applied_versions != expected_versions:
            return self._result(
                exists=True,
                state=DatabaseState.INCOMPATIBLE,
                schema_version=schema_version,
                expected_schema_version=expected_schema_version,
                detail="schema migration versions are incompatible",
            )

        return self._result(
            exists=True,
            state=DatabaseState.OK,
            schema_version=schema_version,
            expected_schema_version=expected_schema_version,
            detail=None,
        )

    @staticmethod
    def _stored_version(value: object) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError("stored migration version is invalid")
        return value

    @staticmethod
    def _missing_tables_detail(missing_tables: frozenset[str]) -> str:
        tables = ", ".join(sorted(missing_tables))
        return f"missing required database table(s): {tables}"

    def _result(
        self,
        *,
        exists: bool,
        state: DatabaseState,
        schema_version: int | None,
        expected_schema_version: int,
        detail: str | None,
    ) -> DatabaseDiagnostic:
        return DatabaseDiagnostic(
            path=self._database_path,
            exists=exists,
            state=state,
            schema_version=schema_version,
            expected_schema_version=expected_schema_version,
            detail=detail,
        )
