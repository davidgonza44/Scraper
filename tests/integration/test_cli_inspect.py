"""Offline integration coverage for inspecting the latest persisted collection run."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from bera_price_tracker.application import MarketplaceProvider
from bera_price_tracker.cli import ExitCode, main
from bera_price_tracker.config import Settings
from bera_price_tracker.domain import (
    CollectionBatch,
    Listing,
    MarketplaceSource,
    SearchQuery,
)
from bera_price_tracker.infrastructure.persistence import (
    SQLiteCollectionInspectionRepository,
    SQLiteListingHistoryRepository,
    SQLiteListingRepository,
)

QUERY = SearchQuery("pastillas de freno bera")
OTHER_QUERY = SearchQuery("disco de freno bera")
FIRST_TIME = datetime(2026, 8, 1, 14, tzinfo=UTC)


@dataclass(slots=True)
class ForbiddenProviderFactory:
    """Fail if inspect tries to construct marketplace/HTTP infrastructure."""

    calls: int = 0

    def __call__(self, _: Settings) -> MarketplaceProvider:
        self.calls += 1
        raise AssertionError("inspect must not construct a marketplace provider")


@dataclass(slots=True)
class ForbiddenWriterFactory:
    """Fail if inspect tries to construct the SQLite write adapter."""

    calls: int = 0

    def __call__(self, _: Settings) -> SQLiteListingRepository:
        self.calls += 1
        raise AssertionError("inspect must not construct a write repository")


@dataclass(slots=True)
class ForbiddenHistoryRepositoryFactory:
    """Fail if inspect incorrectly reuses the one-listing history adapter."""

    calls: int = 0

    def __call__(self, _: Settings) -> SQLiteListingHistoryRepository:
        self.calls += 1
        raise AssertionError("inspect must not construct a history repository")


@dataclass(slots=True)
class CapturingInspectionRepositoryFactory:
    repositories: list[SQLiteCollectionInspectionRepository] = field(default_factory=list)

    def __call__(self, settings: Settings) -> SQLiteCollectionInspectionRepository:
        repository = SQLiteCollectionInspectionRepository(settings.database_path)
        self.repositories.append(repository)
        return repository


def _listing(
    *,
    external_id: str,
    title: str,
    price: str,
    query: SearchQuery,
    collected_at: datetime,
    source: MarketplaceSource = MarketplaceSource.MERCADO_LIBRE,
    currency: str = "VES",
    seller_name: str | None = None,
    location: str | None = None,
    product_condition: str | None = None,
) -> Listing:
    return Listing(
        source=source,
        external_id=external_id,
        title=title,
        price=Decimal(price),
        currency=currency,
        url=f"https://example.test/{source.value}/{external_id}",
        query=query,
        collected_at=collected_at,
        seller_name=seller_name,
        location=location,
        product_condition=product_condition,
    )


def _record_batch(
    database_path: Path,
    *,
    query: SearchQuery,
    collected_at: datetime,
    listings: tuple[Listing, ...],
    source: MarketplaceSource = MarketplaceSource.MERCADO_LIBRE,
) -> None:
    with SQLiteListingRepository(database_path) as repository:
        repository.record_collection(
            CollectionBatch(
                source=source,
                query=query,
                collected_at=collected_at,
                listings=listings,
            )
        )


def _configure(monkeypatch: pytest.MonkeyPatch, database_path: Path) -> None:
    monkeypatch.setenv("BERA_TRACKER_DATABASE_PATH", str(database_path))
    monkeypatch.delenv("BERA_TRACKER_MERCADOLIBRE_SITE_ID", raising=False)
    monkeypatch.delenv("BERA_TRACKER_MERCADOLIBRE_ACCESS_TOKEN", raising=False)


def _database_state(database_path: Path) -> tuple[tuple[object, ...], ...]:
    uri = f"{database_path.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        return tuple(
            connection.execute(
                """
                SELECT 'listings', COUNT(*) FROM listings
                UNION ALL
                SELECT 'collection_runs', COUNT(*) FROM collection_runs
                UNION ALL
                SELECT 'price_snapshots', COUNT(*) FROM price_snapshots
                UNION ALL
                SELECT 'schema_migrations', COUNT(*) FROM schema_migrations
                ORDER BY 1
                """
            ).fetchall()
        )


def _offline_factories() -> tuple[
    ForbiddenProviderFactory,
    ForbiddenWriterFactory,
    ForbiddenHistoryRepositoryFactory,
    CapturingInspectionRepositoryFactory,
]:
    return (
        ForbiddenProviderFactory(),
        ForbiddenWriterFactory(),
        ForbiddenHistoryRepositoryFactory(),
        CapturingInspectionRepositoryFactory(),
    )


def test_inspect_default_source_and_limit_are_offline_and_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "inspect.db"
    listings = tuple(
        _listing(
            external_id=f"MLV-LIMIT-{index:02d}",
            title=f"Pastillas BERA {index:02d}",
            price=("19.9900000000000000001" if index == 1 else str(100 + index)),
            query=QUERY,
            collected_at=FIRST_TIME,
            seller_name=("Repuestos BERA" if index == 1 else None),
            location=("Caracas" if index == 1 else None),
            product_condition=("new" if index == 1 else None),
        )
        for index in range(1, 24)
    )
    _record_batch(
        database_path,
        query=QUERY,
        collected_at=FIRST_TIME,
        listings=listings,
    )
    _configure(monkeypatch, database_path)
    provider_factory, writer_factory, history_factory, inspection_factory = _offline_factories()
    state_before = _database_state(database_path)
    bytes_before = database_path.read_bytes()

    exit_code = main(
        ["inspect", QUERY.text],
        provider_factory=provider_factory,
        repository_factory=writer_factory,
        history_repository_factory=history_factory,
        inspection_repository_factory=inspection_factory,
    )

    captured = capsys.readouterr()
    assert exit_code == ExitCode.SUCCESS
    assert provider_factory.calls == 0
    assert writer_factory.calls == 0
    assert history_factory.calls == 0
    assert len(inspection_factory.repositories) == 1
    assert _database_state(database_path) == state_before
    assert database_path.read_bytes() == bytes_before
    assert f"Query: {QUERY.text}" in captured.out
    assert "Source: Mercado Libre" in captured.out
    assert "Collected at: 2026-08-01 14:00:00 UTC" in captured.out
    assert "Listings: 23" in captured.out
    assert "Showing: 20" in captured.out
    assert "ID: MLV-LIMIT-01" in captured.out
    assert "Title: Pastillas BERA 01" in captured.out
    assert "Price: 19.9900000000000000001 VES" in captured.out
    assert "Condition: new" in captured.out
    assert "Seller: Repuestos BERA" in captured.out
    assert "Location: Caracas" in captured.out
    assert "URL: https://example.test/mercado_libre/MLV-LIMIT-01" in captured.out
    assert "ID: MLV-LIMIT-20" in captured.out
    assert "ID: MLV-LIMIT-21" not in captured.out
    assert captured.err == ""


def test_inspect_custom_limit_controls_only_the_presented_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "custom-limit.db"
    listings = tuple(
        _listing(
            external_id=f"MLV-CUSTOM-{index}",
            title=f"Listing {index}",
            price=str(index),
            query=QUERY,
            collected_at=FIRST_TIME,
        )
        for index in range(1, 4)
    )
    _record_batch(
        database_path,
        query=QUERY,
        collected_at=FIRST_TIME,
        listings=listings,
    )
    _configure(monkeypatch, database_path)
    state_before = _database_state(database_path)

    exit_code = main(["inspect", QUERY.text, "--limit", "2"])

    captured = capsys.readouterr()
    assert exit_code == ExitCode.SUCCESS
    assert "Listings: 3" in captured.out
    assert "Showing: 2" in captured.out
    assert "ID: MLV-CUSTOM-1" in captured.out
    assert "ID: MLV-CUSTOM-2" in captured.out
    assert "ID: MLV-CUSTOM-3" not in captured.out
    assert _database_state(database_path) == state_before


@pytest.mark.parametrize("limit", ["0", "201"])
def test_inspect_rejects_limits_outside_one_through_two_hundred(limit: str) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "bera_price_tracker",
            "inspect",
            QUERY.text,
            "--limit",
            limit,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == ExitCode.USAGE_OR_CONFIGURATION
    assert "limit" in completed.stderr.lower()
    assert "Traceback" not in completed.stderr


def test_inspect_explicit_source_does_not_mix_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "sources.db"
    _record_batch(
        database_path,
        query=QUERY,
        collected_at=FIRST_TIME,
        listings=(
            _listing(
                external_id="SHARED-ID",
                title="Mercado Libre listing",
                price="10.00",
                query=QUERY,
                collected_at=FIRST_TIME,
            ),
        ),
    )
    facebook_time = FIRST_TIME + timedelta(hours=1)
    _record_batch(
        database_path,
        source=MarketplaceSource.FACEBOOK_MARKETPLACE,
        query=QUERY,
        collected_at=facebook_time,
        listings=(
            _listing(
                source=MarketplaceSource.FACEBOOK_MARKETPLACE,
                external_id="SHARED-ID",
                title="Facebook listing",
                price="25.50",
                query=QUERY,
                collected_at=facebook_time,
            ),
        ),
    )
    _configure(monkeypatch, database_path)

    exit_code = main(
        ["inspect", QUERY.text, "--source", "facebook_marketplace"],
    )

    captured = capsys.readouterr()
    assert exit_code == ExitCode.SUCCESS
    assert "Source: facebook_marketplace" in captured.out
    assert "Title: Facebook listing" in captured.out
    assert "Price: 25.50 VES" in captured.out
    assert "Mercado Libre listing" not in captured.out
    assert "10.00 VES" not in captured.out


def test_inspect_missing_database_is_controlled_and_does_not_create_anything(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "missing-parent" / "inspect.db"
    _configure(monkeypatch, database_path)
    provider_factory, writer_factory, history_factory, inspection_factory = _offline_factories()

    exit_code = main(
        ["inspect", QUERY.text],
        provider_factory=provider_factory,
        repository_factory=writer_factory,
        history_repository_factory=history_factory,
        inspection_repository_factory=inspection_factory,
    )

    captured = capsys.readouterr()
    assert exit_code == ExitCode.PERSISTENCE_ERROR
    assert provider_factory.calls == 0
    assert writer_factory.calls == 0
    assert history_factory.calls == 0
    assert "database not found" in captured.err
    assert "Traceback" not in captured.err
    assert not database_path.exists()
    assert not database_path.parent.exists()


def test_inspect_unknown_query_is_distinct_from_an_empty_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "unknown-query.db"
    with SQLiteListingRepository(database_path):
        pass
    _configure(monkeypatch, database_path)

    exit_code = main(["inspect", QUERY.text])

    captured = capsys.readouterr()
    assert exit_code == ExitCode.NOT_FOUND
    assert f"No collection found for query: {QUERY.text}" in captured.err
    assert "database not found" not in captured.err
    assert "Traceback" not in captured.err


def test_inspect_empty_latest_run_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "empty.db"
    _record_batch(
        database_path,
        query=QUERY,
        collected_at=FIRST_TIME,
        listings=(),
    )
    _configure(monkeypatch, database_path)

    exit_code = main(["inspect", QUERY.text])

    captured = capsys.readouterr()
    assert exit_code == ExitCode.SUCCESS
    assert f"Query: {QUERY.text}" in captured.out
    assert "Source: Mercado Libre" in captured.out
    assert "Collected at: 2026-08-01 14:00:00 UTC" in captured.out
    assert "Listings: 0" in captured.out
    assert "Showing: 0" in captured.out
    assert "ID:" not in captured.out
    assert captured.err == ""


def test_inspect_selects_exact_latest_run_then_a_later_empty_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "multiple-runs.db"
    run_one_time = FIRST_TIME
    run_two_time = FIRST_TIME + timedelta(days=1)
    run_three_time = FIRST_TIME + timedelta(days=2)
    run_four_time = FIRST_TIME + timedelta(days=3)
    run_one = tuple(
        _listing(
            external_id=f"MLV-RUN1-{index}",
            title=f"Run one {index}",
            price=str(10 + index),
            query=QUERY,
            collected_at=run_one_time,
        )
        for index in range(1, 3)
    )
    run_two = tuple(
        _listing(
            external_id=f"MLV-RUN2-{index}",
            title=f"Run two {index}",
            price=str(20 + index),
            query=QUERY,
            collected_at=run_two_time,
        )
        for index in range(1, 4)
    )
    run_three = (
        _listing(
            external_id="MLV-OTHER-1",
            title="Other query",
            price="99",
            query=OTHER_QUERY,
            collected_at=run_three_time,
        ),
    )
    _record_batch(
        database_path,
        query=QUERY,
        collected_at=run_one_time,
        listings=run_one,
    )
    _record_batch(
        database_path,
        query=QUERY,
        collected_at=run_two_time,
        listings=run_two,
    )
    _record_batch(
        database_path,
        query=OTHER_QUERY,
        collected_at=run_three_time,
        listings=run_three,
    )
    _configure(monkeypatch, database_path)

    first_exit = main(["inspect", QUERY.text])

    first_output = capsys.readouterr()
    assert first_exit == ExitCode.SUCCESS
    assert "Collected at: 2026-08-02 14:00:00 UTC" in first_output.out
    assert "Listings: 3" in first_output.out
    assert "Showing: 3" in first_output.out
    for index in range(1, 4):
        assert f"ID: MLV-RUN2-{index}" in first_output.out
    assert "MLV-RUN1" not in first_output.out
    assert "MLV-OTHER-1" not in first_output.out

    _record_batch(
        database_path,
        query=QUERY,
        collected_at=run_four_time,
        listings=(),
    )

    second_exit = main(["inspect", QUERY.text])

    second_output = capsys.readouterr()
    assert second_exit == ExitCode.SUCCESS
    assert "Collected at: 2026-08-04 14:00:00 UTC" in second_output.out
    assert "Listings: 0" in second_output.out
    assert "Showing: 0" in second_output.out
    assert "MLV-RUN1" not in second_output.out
    assert "MLV-RUN2" not in second_output.out
    assert "MLV-OTHER-1" not in second_output.out


def test_python_module_inspect_reads_sqlite_without_marketplace_configuration(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "module-inspect.db"
    _record_batch(
        database_path,
        query=QUERY,
        collected_at=FIRST_TIME,
        listings=(
            _listing(
                external_id="MLV-MODULE",
                title="Pastillas BERA module",
                price="19.99",
                query=QUERY,
                collected_at=FIRST_TIME,
            ),
        ),
    )
    environment = os.environ.copy()
    environment["BERA_TRACKER_DATABASE_PATH"] = str(database_path)
    environment.pop("BERA_TRACKER_MERCADOLIBRE_SITE_ID", None)
    environment.pop("BERA_TRACKER_MERCADOLIBRE_ACCESS_TOKEN", None)

    completed = subprocess.run(
        [sys.executable, "-m", "bera_price_tracker", "inspect", QUERY.text],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == ExitCode.SUCCESS
    assert "ID: MLV-MODULE" in completed.stdout
    assert "Title: Pastillas BERA module" in completed.stdout
    assert "Price: 19.99 VES" in completed.stdout
    assert "Traceback" not in completed.stderr
    assert "Authorization" not in completed.stderr
