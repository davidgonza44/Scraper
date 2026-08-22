"""Offline diagnostics for the local BERA Price Tracker environment."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from bera_price_tracker.config import Settings, is_valid_mercadolibre_site_id

# Keep this runtime check aligned with ``project.requires-python`` in pyproject.toml.
MINIMUM_PYTHON_VERSION = (3, 12)


class DiagnosticStatus(StrEnum):
    """Overall readiness status reported by the doctor command."""

    READY = "READY"
    INCOMPLETE = "INCOMPLETE"
    ERROR = "ERROR"


class DatabaseState(StrEnum):
    """State of the configured local SQLite database."""

    OK = "OK"
    NOT_INITIALIZED = "NOT_INITIALIZED"
    INCOMPATIBLE = "INCOMPATIBLE"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class DatabaseDiagnostic:
    """Sanitized result of inspecting one SQLite database target."""

    path: str
    exists: bool
    state: DatabaseState
    schema_version: int | None
    expected_schema_version: int
    detail: str | None = None


@runtime_checkable
class DatabaseDiagnosticsRepository(Protocol):
    """Read-only boundary for inspecting the configured SQLite database."""

    def inspect(self) -> DatabaseDiagnostic:
        """Inspect the database without creating, migrating, or modifying it."""

        ...


@dataclass(frozen=True, slots=True)
class DiagnosticReport:
    """Secret-free environment readiness report."""

    python_version: tuple[int, int, int]
    python_compatible: bool
    mercadolibre_site_id: str | None
    mercadolibre_site_id_valid: bool
    access_token_configured: bool
    page_size: int
    max_pages: int
    timeout_seconds: float
    max_retries: int
    mercado_libre_status: DiagnosticStatus
    database: DatabaseDiagnostic
    overall: DiagnosticStatus


@dataclass(frozen=True, slots=True)
class DiagnoseEnvironment:
    """Assess local readiness using validated settings and read-only persistence."""

    repository: DatabaseDiagnosticsRepository
    version_info: tuple[int, int, int] | None = None

    def execute(self, settings: Settings) -> DiagnosticReport:
        """Return a diagnostic report without exposing credentials or using HTTP."""

        python_version = self.version_info or (
            sys.version_info.major,
            sys.version_info.minor,
            sys.version_info.micro,
        )
        python_compatible = python_version[:2] >= MINIMUM_PYTHON_VERSION
        site_id_valid = is_valid_mercadolibre_site_id(settings.mercadolibre_site_id)
        token = settings.mercadolibre_access_token
        access_token_configured = token is not None and bool(token.strip())
        database = self.repository.inspect()
        mercado_libre_status = (
            DiagnosticStatus.READY
            if site_id_valid and access_token_configured
            else DiagnosticStatus.INCOMPLETE
        )

        if database.state in {DatabaseState.INCOMPATIBLE, DatabaseState.ERROR}:
            overall = DiagnosticStatus.ERROR
        elif (
            not python_compatible
            or mercado_libre_status is DiagnosticStatus.INCOMPLETE
            or database.state is DatabaseState.NOT_INITIALIZED
        ):
            overall = DiagnosticStatus.INCOMPLETE
        else:
            overall = DiagnosticStatus.READY

        return DiagnosticReport(
            python_version=python_version,
            python_compatible=python_compatible,
            mercadolibre_site_id=settings.mercadolibre_site_id,
            mercadolibre_site_id_valid=site_id_valid,
            access_token_configured=access_token_configured,
            page_size=settings.mercadolibre_page_size,
            max_pages=settings.mercadolibre_max_pages,
            timeout_seconds=settings.mercadolibre_timeout_seconds,
            max_retries=settings.mercadolibre_max_retries,
            mercado_libre_status=mercado_libre_status,
            database=database,
            overall=overall,
        )
