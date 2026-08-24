"""Offline integration coverage for the local doctor command."""

from __future__ import annotations

import logging
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from bera_price_tracker.application import (
    DatabaseDiagnosticsRepository,
    MarketplaceProvider,
)
from bera_price_tracker.cli import ExitCode, main
from bera_price_tracker.config import Settings
from bera_price_tracker.infrastructure.persistence import (
    SQLiteCollectionInspectionRepository,
    SQLiteDatabaseDiagnostics,
    SQLiteListingHistoryRepository,
    SQLiteListingRepository,
)
from bera_price_tracker.infrastructure.persistence.migrations import MIGRATIONS

TOKEN = "DOCTOR_TOKEN_PREFIX-never-print-DOCTOR_TOKEN_SUFFIX"
CLIENT_SECRET = "DOCTOR_CLIENT_SECRET-never-print"


@dataclass(slots=True)
class ForbiddenProviderFactory:
    calls: int = 0

    def __call__(self, _: Settings) -> MarketplaceProvider:
        self.calls += 1
        raise AssertionError("doctor must not construct a marketplace provider")


@dataclass(slots=True)
class ForbiddenWriterFactory:
    calls: int = 0

    def __call__(self, _: Settings) -> SQLiteListingRepository:
        self.calls += 1
        raise AssertionError("doctor must not construct a SQLite writer")


@dataclass(slots=True)
class ForbiddenHistoryRepositoryFactory:
    calls: int = 0

    def __call__(self, _: Settings) -> SQLiteListingHistoryRepository:
        self.calls += 1
        raise AssertionError("doctor must not construct a history repository")


@dataclass(slots=True)
class ForbiddenInspectionRepositoryFactory:
    calls: int = 0

    def __call__(self, _: Settings) -> SQLiteCollectionInspectionRepository:
        self.calls += 1
        raise AssertionError("doctor must not construct an inspection repository")


@dataclass(slots=True)
class CapturingDiagnosticsRepositoryFactory:
    repositories: list[SQLiteDatabaseDiagnostics] = field(default_factory=list)

    def __call__(self, settings: Settings) -> DatabaseDiagnosticsRepository:
        repository = SQLiteDatabaseDiagnostics(settings.database_path)
        self.repositories.append(repository)
        return repository


def _initialize_database(database_path: Path) -> None:
    with SQLiteListingRepository(database_path):
        pass


def _configure(
    monkeypatch: pytest.MonkeyPatch,
    database_path: Path,
    *,
    access_token: str | None = TOKEN,
) -> None:
    monkeypatch.setenv("BERA_TRACKER_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("BERA_TRACKER_MERCADOLIBRE_SITE_ID", "mlv")
    monkeypatch.setenv("BERA_TRACKER_MERCADOLIBRE_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("BERA_TRACKER_MERCADOLIBRE_PAGE_SIZE", "25")
    monkeypatch.setenv("BERA_TRACKER_MERCADOLIBRE_MAX_PAGES", "4")
    monkeypatch.setenv("BERA_TRACKER_MERCADOLIBRE_TIMEOUT_SECONDS", "7.5")
    monkeypatch.setenv("BERA_TRACKER_MERCADOLIBRE_MAX_RETRIES", "1")
    monkeypatch.setenv("BERA_TRACKER_DATABASE_PATH", str(database_path))
    if access_token is None:
        monkeypatch.delenv("BERA_TRACKER_MERCADOLIBRE_ACCESS_TOKEN", raising=False)
    else:
        monkeypatch.setenv("BERA_TRACKER_MERCADOLIBRE_ACCESS_TOKEN", access_token)


def test_doctor_ready_is_offline_read_only_and_never_reveals_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    database_path = tmp_path / "ready.db"
    _initialize_database(database_path)
    _configure(monkeypatch, database_path)
    before_bytes = database_path.read_bytes()
    before_files = {path.name for path in tmp_path.iterdir()}
    provider_factory = ForbiddenProviderFactory()
    writer_factory = ForbiddenWriterFactory()
    history_factory = ForbiddenHistoryRepositoryFactory()
    inspection_factory = ForbiddenInspectionRepositoryFactory()
    diagnostics_factory = CapturingDiagnosticsRepositoryFactory()
    caplog.set_level(logging.DEBUG)

    exit_code = main(
        ["doctor"],
        provider_factory=provider_factory,
        repository_factory=writer_factory,
        history_repository_factory=history_factory,
        inspection_repository_factory=inspection_factory,
        diagnostics_repository_factory=diagnostics_factory,
    )

    captured = capsys.readouterr()
    combined_output = captured.out + captured.err + caplog.text
    expected_schema_version = max(migration.version for migration in MIGRATIONS)
    assert exit_code == ExitCode.SUCCESS
    assert provider_factory.calls == 0
    assert writer_factory.calls == 0
    assert history_factory.calls == 0
    assert inspection_factory.calls == 0
    assert len(diagnostics_factory.repositories) == 1
    assert database_path.read_bytes() == before_bytes
    assert {path.name for path in tmp_path.iterdir()} == before_files
    assert "BERA Price Tracker diagnostics" in captured.out
    assert "Python:" in captured.out
    assert f"Version: {sys.version_info.major}.{sys.version_info.minor}." in captured.out
    assert "Mercado Libre:" in captured.out
    assert "Site ID: MLV" in captured.out
    assert "Access token: CONFIGURED" in captured.out
    assert "Page size: 25" in captured.out
    assert "Max pages: 4" in captured.out
    assert "Timeout: 7.5s" in captured.out
    assert "Retries: 1" in captured.out
    assert f"Path: {database_path}" in captured.out
    assert "Exists: yes" in captured.out
    assert f"Schema: OK (version {expected_schema_version})" in captured.out
    assert "Facebook Marketplace:" in captured.out
    assert "Status: NOT CONFIGURED" in captured.out
    assert "Azure Translator:" in captured.out
    assert "Overall: READY" in captured.out
    for secret_fragment in (
        TOKEN,
        "DOCTOR_TOKEN_PREFIX",
        "DOCTOR_TOKEN_SUFFIX",
        CLIENT_SECRET,
        "DOCTOR_CLIENT_SECRET",
        "Authorization",
    ):
        assert secret_fragment not in combined_output


def test_doctor_without_token_is_incomplete_with_a_valid_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "missing-token.db"
    _initialize_database(database_path)
    _configure(monkeypatch, database_path, access_token=None)

    exit_code = main(["doctor"])

    captured = capsys.readouterr()
    assert exit_code == ExitCode.USAGE_OR_CONFIGURATION
    assert "Access token: NOT CONFIGURED" in captured.out
    assert "Schema: OK" in captured.out
    assert "Overall: INCOMPLETE" in captured.out
    assert "Traceback" not in captured.err


def test_doctor_reports_a_missing_database_without_creating_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "missing" / "nested" / "tracker.db"
    _configure(monkeypatch, database_path)

    exit_code = main(["doctor"])

    captured = capsys.readouterr()
    assert exit_code == ExitCode.USAGE_OR_CONFIGURATION
    assert f"Path: {database_path}" in captured.out
    assert "Exists: no" in captured.out
    assert "Schema: NOT INITIALIZED" in captured.out
    assert "Overall: INCOMPLETE" in captured.out
    assert "Traceback" not in captured.err
    assert not database_path.exists()
    assert not database_path.parent.exists()


def test_doctor_reports_an_incompatible_schema_without_modifying_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "incompatible.db"
    _initialize_database(database_path)
    expected_schema_version = max(migration.version for migration in MIGRATIONS)
    incompatible_version = expected_schema_version + 1
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute(
            "UPDATE schema_migrations SET version = ? WHERE version = ?",
            (incompatible_version, expected_schema_version),
        )
        connection.commit()
    _configure(monkeypatch, database_path)
    before_bytes = database_path.read_bytes()
    before_files = {path.name for path in tmp_path.iterdir()}

    exit_code = main(["doctor"])

    captured = capsys.readouterr()
    assert exit_code == ExitCode.PERSISTENCE_ERROR
    assert "Exists: yes" in captured.out
    assert (
        f"Schema: INCOMPATIBLE (expected {expected_schema_version}, found {incompatible_version})"
    ) in captured.out
    assert "Status: ERROR" in captured.out
    assert "Overall: ERROR" in captured.out
    assert "Traceback" not in captured.out + captured.err
    assert database_path.read_bytes() == before_bytes
    assert {path.name for path in tmp_path.iterdir()} == before_files


def test_doctor_reports_a_non_sqlite_file_without_modifying_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "not-sqlite.db"
    original = b"this is not a SQLite database"
    database_path.write_bytes(original)
    _configure(monkeypatch, database_path)

    exit_code = main(["doctor"])

    captured = capsys.readouterr()
    assert exit_code == ExitCode.PERSISTENCE_ERROR
    assert "Exists: yes" in captured.out
    assert "Schema: ERROR" in captured.out
    assert "Status: ERROR" in captured.out
    assert "Overall: ERROR" in captured.out
    assert "Traceback" not in captured.out + captured.err
    assert database_path.read_bytes() == original


def test_python_module_doctor_uses_the_same_offline_command(tmp_path: Path) -> None:
    database_path = tmp_path / "module-doctor.db"
    _initialize_database(database_path)
    environment = os.environ.copy()
    environment.update(
        {
            "BERA_TRACKER_LOG_LEVEL": "INFO",
            "BERA_TRACKER_MERCADOLIBRE_SITE_ID": "MLV",
            "BERA_TRACKER_MERCADOLIBRE_ACCESS_TOKEN": TOKEN,
            "BERA_TRACKER_MERCADOLIBRE_PAGE_SIZE": "25",
            "BERA_TRACKER_MERCADOLIBRE_MAX_PAGES": "4",
            "BERA_TRACKER_MERCADOLIBRE_TIMEOUT_SECONDS": "7.5",
            "BERA_TRACKER_MERCADOLIBRE_MAX_RETRIES": "1",
            "BERA_TRACKER_DATABASE_PATH": str(database_path),
        }
    )

    completed = subprocess.run(
        [sys.executable, "-m", "bera_price_tracker", "doctor"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == ExitCode.SUCCESS
    assert "BERA Price Tracker diagnostics" in completed.stdout
    assert "Access token: CONFIGURED" in completed.stdout
    assert "Overall: READY" in completed.stdout
    assert TOKEN not in completed.stdout
    assert TOKEN not in completed.stderr
    assert "Authorization" not in completed.stdout + completed.stderr


def test_doctor_reports_azure_translator_from_local_config_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "azure-doctor.db"
    _initialize_database(database_path)
    _configure(monkeypatch, database_path)
    monkeypatch.setenv("BERA_TRACKER_AZURE_TRANSLATOR_KEY", TOKEN)

    exit_code = main(["doctor"])

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert exit_code == ExitCode.SUCCESS
    assert "Azure Translator:" in captured.out
    assert "Status: CONFIGURED" in captured.out
    assert TOKEN not in combined
    assert "Ocp-Apim-Subscription-Key" not in combined
