"""Unit tests for secret-free offline environment diagnostics."""

from __future__ import annotations

from dataclasses import fields

import pytest

from bera_price_tracker.application import (
    MINIMUM_PYTHON_VERSION,
    DatabaseDiagnostic,
    DatabaseState,
    DiagnoseEnvironment,
    DiagnosticReport,
    DiagnosticStatus,
)
from bera_price_tracker.config import Settings

_FAKE_TOKEN = "doctor-token-that-must-stay-secret"


class StubDatabaseDiagnosticsRepository:
    def __init__(self, diagnostic: DatabaseDiagnostic) -> None:
        self.diagnostic = diagnostic
        self.inspect_calls = 0

    def inspect(self) -> DatabaseDiagnostic:
        self.inspect_calls += 1
        return self.diagnostic


def _database(state: DatabaseState = DatabaseState.OK) -> DatabaseDiagnostic:
    exists = state is not DatabaseState.NOT_INITIALIZED
    schema_version = 1 if state is DatabaseState.OK else None
    return DatabaseDiagnostic(
        path="data/bera_price_tracker.db",
        exists=exists,
        state=state,
        schema_version=schema_version,
        expected_schema_version=1,
    )


def _settings(
    *,
    site_id: str | None = "MLV",
    access_token: str | None = _FAKE_TOKEN,
) -> Settings:
    return Settings(
        mercadolibre_site_id=site_id,
        mercadolibre_access_token=access_token,
    )


def _diagnose(
    *,
    settings: Settings | None = None,
    database: DatabaseDiagnostic | None = None,
    version: tuple[int, int, int] = (3, 12, 7),
) -> tuple[DiagnosticReport, StubDatabaseDiagnosticsRepository]:
    repository = StubDatabaseDiagnosticsRepository(database or _database())
    report = DiagnoseEnvironment(repository=repository, version_info=version).execute(
        settings or _settings()
    )
    return report, repository


def test_minimum_python_version_matches_project_requirement() -> None:
    assert MINIMUM_PYTHON_VERSION == (3, 12)


def test_ready_report_contains_validated_configuration_values() -> None:
    settings = Settings(
        mercadolibre_site_id="mlv",
        mercadolibre_access_token=_FAKE_TOKEN,
        mercadolibre_page_size=25,
        mercadolibre_max_pages=4,
        mercadolibre_timeout_seconds=7.5,
        mercadolibre_max_retries=1,
    )
    repository = StubDatabaseDiagnosticsRepository(_database())

    report = DiagnoseEnvironment(repository=repository, version_info=(3, 12, 13)).execute(settings)

    assert report.python_version == (3, 12, 13)
    assert report.python_compatible is True
    assert report.mercadolibre_site_id == "MLV"
    assert report.mercadolibre_site_id_valid is True
    assert report.access_token_configured is True
    assert report.page_size == 25
    assert report.max_pages == 4
    assert report.timeout_seconds == 7.5
    assert report.max_retries == 1
    assert report.mercado_libre_status is DiagnosticStatus.READY
    assert report.database.state is DatabaseState.OK
    assert report.overall is DiagnosticStatus.READY
    assert repository.inspect_calls == 1


@pytest.mark.parametrize("version", [(3, 11, 9), (2, 99, 0)])
def test_unsupported_python_is_incomplete(version: tuple[int, int, int]) -> None:
    report, _ = _diagnose(version=version)

    assert report.python_compatible is False
    assert report.overall is DiagnosticStatus.INCOMPLETE


def test_runtime_python_version_is_used_by_default() -> None:
    repository = StubDatabaseDiagnosticsRepository(_database())

    report = DiagnoseEnvironment(repository=repository).execute(_settings())

    assert report.python_version[:2] >= MINIMUM_PYTHON_VERSION
    assert report.python_compatible is True


@pytest.mark.parametrize("access_token", [None, "", "   "])
def test_missing_access_token_is_incomplete(access_token: str | None) -> None:
    report, _ = _diagnose(settings=_settings(access_token=access_token))

    assert report.access_token_configured is False
    assert report.mercado_libre_status is DiagnosticStatus.INCOMPLETE
    assert report.overall is DiagnosticStatus.INCOMPLETE


@pytest.mark.parametrize("site_id", [None, "", "bad site", "MLV!"])
def test_missing_or_invalid_site_id_is_incomplete(site_id: str | None) -> None:
    report, _ = _diagnose(settings=_settings(site_id=site_id))

    assert report.mercadolibre_site_id_valid is False
    assert report.mercado_libre_status is DiagnosticStatus.INCOMPLETE
    assert report.overall is DiagnosticStatus.INCOMPLETE


def test_database_not_initialized_is_incomplete() -> None:
    report, _ = _diagnose(database=_database(DatabaseState.NOT_INITIALIZED))

    assert report.database.exists is False
    assert report.database.state is DatabaseState.NOT_INITIALIZED
    assert report.overall is DiagnosticStatus.INCOMPLETE


@pytest.mark.parametrize("state", [DatabaseState.INCOMPATIBLE, DatabaseState.ERROR])
def test_database_failure_has_error_precedence(state: DatabaseState) -> None:
    report, _ = _diagnose(
        settings=_settings(access_token=None),
        database=_database(state),
        version=(3, 11, 9),
    )

    assert report.database.state is state
    assert report.overall is DiagnosticStatus.ERROR


def test_report_never_contains_credentials() -> None:
    report, _ = _diagnose()

    assert _FAKE_TOKEN not in repr(report)
    assert "client_secret" not in {field.name for field in fields(report)}
    assert "access_token" not in {field.name for field in fields(report)}
    assert report.access_token_configured is True
