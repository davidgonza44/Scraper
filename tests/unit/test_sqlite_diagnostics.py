"""Tests for strictly read-only SQLite environment diagnostics."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal, Never

import pytest

from bera_price_tracker.application.diagnostics import (
    DatabaseDiagnosticsRepository,
    DatabaseState,
)
from bera_price_tracker.infrastructure.persistence import (
    SQLiteDatabaseDiagnostics,
    SQLiteListingRepository,
    sqlite_diagnostics,
)
from bera_price_tracker.infrastructure.persistence.migrations import MIGRATIONS, Migration

REQUIRED_TABLES = {
    "schema_migrations",
    "listings",
    "collection_runs",
    "price_snapshots",
}


def initialize_database(database_path: Path) -> None:
    with SQLiteListingRepository(database_path):
        pass


def database_tables(database_path: Path) -> set[str]:
    with closing(sqlite3.connect(database_path)) as connection:
        return {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }


def test_valid_database_reports_expected_schema_without_modifying_files(tmp_path: Path) -> None:
    database_path = tmp_path / "tracker.db"
    initialize_database(database_path)
    before_bytes = database_path.read_bytes()
    before_files = {path.name for path in tmp_path.iterdir()}

    diagnostics = SQLiteDatabaseDiagnostics(database_path)
    result = diagnostics.inspect()

    assert isinstance(diagnostics, DatabaseDiagnosticsRepository)
    assert result.path == str(database_path)
    assert result.exists
    assert result.state is DatabaseState.OK
    assert result.schema_version == max(migration.version for migration in MIGRATIONS)
    assert result.expected_schema_version == max(migration.version for migration in MIGRATIONS)
    assert result.detail is None
    assert database_path.read_bytes() == before_bytes
    assert {path.name for path in tmp_path.iterdir()} == before_files
    assert REQUIRED_TABLES <= database_tables(database_path)


def test_active_write_ahead_log_is_not_ignored_or_modified(tmp_path: Path) -> None:
    database_path = tmp_path / "active-wal.db"
    initialize_database(database_path)
    wal_path = Path(f"{database_path}-wal")
    wal_path.write_bytes(b"active-wal-marker")
    before = wal_path.read_bytes()

    result = SQLiteDatabaseDiagnostics(database_path).inspect()

    assert result.state is DatabaseState.ERROR
    assert result.detail == "database has an active write-ahead log; retry when it is idle"
    assert wal_path.read_bytes() == before


def test_missing_database_and_parent_directories_are_not_created(tmp_path: Path) -> None:
    database_path = tmp_path / "missing" / "nested" / "tracker.db"

    result = SQLiteDatabaseDiagnostics(database_path).inspect()

    assert result.state is DatabaseState.NOT_INITIALIZED
    assert not result.exists
    assert result.schema_version is None
    assert result.detail == "database is not initialized"
    assert not database_path.exists()
    assert not database_path.parent.exists()


def test_existing_path_that_is_not_a_file_is_an_error(tmp_path: Path) -> None:
    result = SQLiteDatabaseDiagnostics(tmp_path).inspect()

    assert result.state is DatabaseState.ERROR
    assert result.exists
    assert result.detail == "database path is not a file"


def test_missing_required_table_is_incompatible(tmp_path: Path) -> None:
    database_path = tmp_path / "missing-table.db"
    initialize_database(database_path)
    with closing(sqlite3.connect(database_path)) as connection:
        with connection:
            connection.execute("DROP TABLE listings")

    result = SQLiteDatabaseDiagnostics(database_path).inspect()

    assert result.state is DatabaseState.INCOMPATIBLE
    assert result.schema_version == 2
    assert result.detail is not None
    assert "listings" in result.detail


def test_missing_applied_migration_is_incompatible(tmp_path: Path) -> None:
    database_path = tmp_path / "old-schema.db"
    initialize_database(database_path)
    with closing(sqlite3.connect(database_path)) as connection:
        with connection:
            connection.execute("DELETE FROM schema_migrations")

    result = SQLiteDatabaseDiagnostics(database_path).inspect()

    assert result.state is DatabaseState.INCOMPATIBLE
    assert result.schema_version == 0
    assert result.expected_schema_version == 2
    assert result.detail == "schema migration versions are incompatible"


def test_unknown_applied_migration_is_incompatible(tmp_path: Path) -> None:
    database_path = tmp_path / "future-schema.db"
    initialize_database(database_path)
    with closing(sqlite3.connect(database_path)) as connection:
        with connection:
            connection.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (999, "999_unknown", "2026-08-21T12:00:00.000000Z"),
            )

    result = SQLiteDatabaseDiagnostics(database_path).inspect()

    assert result.state is DatabaseState.INCOMPATIBLE
    assert result.schema_version == 999
    assert result.expected_schema_version == 2


def test_pending_migration_is_reported_but_never_applied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "pending-schema.db"
    initialize_database(database_path)
    marker = Migration(
        version=3,
        name="003_must_not_run_from_doctor",
        statements=("CREATE TABLE forbidden_doctor_migration (id INTEGER)",),
    )
    monkeypatch.setattr(sqlite_diagnostics, "MIGRATIONS", (*MIGRATIONS, marker))

    result = SQLiteDatabaseDiagnostics(database_path).inspect()

    assert result.state is DatabaseState.INCOMPATIBLE
    assert result.schema_version == 2
    assert result.expected_schema_version == 3
    with closing(sqlite3.connect(database_path)) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone() == (2,)
        forbidden = connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'forbidden_doctor_migration'"
        ).fetchone()
    assert forbidden is None


def test_plain_text_file_is_reported_without_raw_sqlite_error(tmp_path: Path) -> None:
    database_path = tmp_path / "not-sqlite.db"
    database_path.write_text("this is not SQLite", encoding="utf-8")

    result = SQLiteDatabaseDiagnostics(database_path).inspect()

    assert result.state is DatabaseState.ERROR
    assert result.exists
    assert result.schema_version is None
    assert result.detail == "file is not a readable SQLite database"
    assert "this is not SQLite" not in result.detail


def test_connection_error_is_controlled_and_does_not_expose_raw_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "denied.db"
    initialize_database(database_path)

    def deny_connection(*args: object, **kwargs: object) -> Never:
        raise sqlite3.OperationalError("permission denied: sensitive raw detail")

    monkeypatch.setattr(
        "bera_price_tracker.infrastructure.persistence.sqlite_diagnostics.sqlite3.connect",
        deny_connection,
    )

    result = SQLiteDatabaseDiagnostics(database_path).inspect()

    assert result.state is DatabaseState.ERROR
    assert result.detail == "could not open database in read-only mode"
    assert "sensitive" not in result.detail


def test_connection_uses_uri_read_only_mode_and_enables_query_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "connection-mode.db"
    initialize_database(database_path)
    real_connect = sqlite3.connect
    received_database = ""
    received_uri = False
    received_isolation_level: str | None = "unset"
    statements: list[str] = []

    def tracked_connect(
        database: str,
        *,
        uri: bool = False,
        isolation_level: Literal["DEFERRED", "EXCLUSIVE", "IMMEDIATE"] | None = None,
    ) -> sqlite3.Connection:
        nonlocal received_database, received_uri, received_isolation_level
        received_database = database
        received_uri = uri
        received_isolation_level = isolation_level
        connection = real_connect(database, uri=uri, isolation_level=isolation_level)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(
        "bera_price_tracker.infrastructure.persistence.sqlite_diagnostics.sqlite3.connect",
        tracked_connect,
    )

    result = SQLiteDatabaseDiagnostics(database_path).inspect()

    assert result.state is DatabaseState.OK
    assert "?mode=ro" in received_database
    assert "immutable=1" in received_database
    assert received_uri is True
    assert received_isolation_level is None
    assert any(statement.upper() == "PRAGMA QUERY_ONLY = ON" for statement in statements)
    assert not any(
        statement.lstrip().upper().startswith(("CREATE ", "INSERT ", "UPDATE ", "DELETE "))
        for statement in statements
    )


def test_extra_application_table_is_compatible(tmp_path: Path) -> None:
    database_path = tmp_path / "extra-table.db"
    initialize_database(database_path)
    with closing(sqlite3.connect(database_path)) as connection:
        with connection:
            connection.execute("CREATE TABLE harmless_extra (id INTEGER PRIMARY KEY)")

    result = SQLiteDatabaseDiagnostics(database_path).inspect()

    assert result.state is DatabaseState.OK
    assert result.schema_version == 2
