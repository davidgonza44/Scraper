"""Offline integration coverage for one-listing statistics in the CLI."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from bera_price_tracker.application import MarketplaceProvider
from bera_price_tracker.cli import ExitCode, main
from bera_price_tracker.config import Settings
from bera_price_tracker.domain import (
    CollectionBatch,
    Listing,
    ListingKey,
    MarketplaceSource,
    SearchQuery,
)
from bera_price_tracker.infrastructure.persistence import (
    PersistenceError,
    SQLiteListingHistoryRepository,
    SQLiteListingRepository,
)

EXTERNAL_ID = "MLV123456789"
QUERY = SearchQuery("pastillas de freno bera")
FIRST_TIME = datetime(2026, 8, 1, 14, tzinfo=UTC)
SECOND_TIME = datetime(2026, 8, 10, 14, tzinfo=UTC)
THIRD_TIME = datetime(2026, 8, 20, 14, tzinfo=UTC)


@dataclass(slots=True)
class ForbiddenProviderFactory:
    calls: int = 0

    def __call__(self, _: Settings) -> MarketplaceProvider:
        self.calls += 1
        raise AssertionError("stats must not construct a marketplace provider")


@dataclass(slots=True)
class ForbiddenWriterFactory:
    calls: int = 0

    def __call__(self, _: Settings) -> SQLiteListingRepository:
        self.calls += 1
        raise AssertionError("stats must not construct a write repository")


@dataclass(slots=True)
class CapturingHistoryRepositoryFactory:
    repositories: list[SQLiteListingHistoryRepository] = field(default_factory=list)

    def __call__(self, settings: Settings) -> SQLiteListingHistoryRepository:
        repository = SQLiteListingHistoryRepository(settings.database_path)
        self.repositories.append(repository)
        return repository


def _listing(
    *,
    price: str,
    collected_at: datetime,
    currency: str = "VES",
    source: MarketplaceSource = MarketplaceSource.MERCADO_LIBRE,
    title: str = "Pastillas de freno BERA SBR",
) -> Listing:
    return Listing(
        source=source,
        external_id=EXTERNAL_ID,
        title=title,
        price=Decimal(price),
        currency=currency,
        url=f"https://example.test/{source.value}/{EXTERNAL_ID}",
        query=QUERY,
        collected_at=collected_at,
    )


def _persist(repository: SQLiteListingRepository, listing: Listing) -> None:
    repository.record_collection(
        CollectionBatch(
            source=listing.source,
            query=listing.query,
            collected_at=listing.collected_at,
            listings=(listing,),
        )
    )


def _seed_three_observations(database_path: Path) -> None:
    with SQLiteListingRepository(database_path) as repository:
        _persist(repository, _listing(price="19.99", collected_at=FIRST_TIME))
        _persist(repository, _listing(price="19.99", collected_at=SECOND_TIME))
        _persist(repository, _listing(price="21.99", collected_at=THIRD_TIME))


def _configure(monkeypatch: pytest.MonkeyPatch, database_path: Path) -> None:
    monkeypatch.setenv("BERA_TRACKER_DATABASE_PATH", str(database_path))
    monkeypatch.delenv("BERA_TRACKER_MERCADOLIBRE_SITE_ID", raising=False)
    monkeypatch.delenv("BERA_TRACKER_MERCADOLIBRE_ACCESS_TOKEN", raising=False)


def _database_state(database_path: Path) -> tuple[tuple[object, ...], ...]:
    uri = f"{database_path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
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
    finally:
        connection.close()


def test_stats_cli_calculates_three_observations_without_http_or_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "stats.db"
    _seed_three_observations(database_path)
    _configure(monkeypatch, database_path)
    provider_factory = ForbiddenProviderFactory()
    writer_factory = ForbiddenWriterFactory()
    history_factory = CapturingHistoryRepositoryFactory()
    state_before = _database_state(database_path)
    bytes_before = database_path.read_bytes()
    with localcontext() as context:
        context.prec = 50
        expected_average = Decimal("61.97") / Decimal("3")

    exit_code = main(
        ["stats", EXTERNAL_ID],
        provider_factory=provider_factory,
        repository_factory=writer_factory,
        history_repository_factory=history_factory,
    )

    captured = capsys.readouterr()
    assert exit_code == ExitCode.SUCCESS
    assert provider_factory.calls == 0
    assert writer_factory.calls == 0
    assert len(history_factory.repositories) == 1
    with pytest.raises(PersistenceError, match="closed"):
        history_factory.repositories[0].get_history(
            ListingKey(MarketplaceSource.MERCADO_LIBRE, EXTERNAL_ID)
        )
    assert _database_state(database_path) == state_before
    assert database_path.read_bytes() == bytes_before
    assert f"ID: {EXTERNAL_ID}" in captured.out
    assert "Source: Mercado Libre" in captured.out
    assert "Title: Pastillas de freno BERA SBR" in captured.out
    assert "Currency: VES" in captured.out
    assert "Current price: 21.99" in captured.out
    assert "Previous price: 19.99" in captured.out
    assert "Change: +2.00 (+10.01%)" in captured.out
    assert "Minimum: 19.99" in captured.out
    assert "Maximum: 21.99" in captured.out
    assert f"Average: {expected_average}" in captured.out
    assert "Median: 19.99" in captured.out
    assert "Observations: 3" in captured.out
    assert "First observation: 2026-08-01 14:00:00 UTC" in captured.out
    assert "Last observation: 2026-08-20 14:00:00 UTC" in captured.out
    assert captured.err == ""


def test_stats_cli_one_observation_has_unavailable_previous_and_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "single.db"
    with SQLiteListingRepository(database_path) as repository:
        _persist(repository, _listing(price="25.50", collected_at=FIRST_TIME))
    _configure(monkeypatch, database_path)

    exit_code = main(["stats", EXTERNAL_ID])

    captured = capsys.readouterr()
    assert exit_code == ExitCode.SUCCESS
    assert "Current price: 25.50" in captured.out
    assert "Previous price: unavailable" in captured.out
    assert "Change: unavailable" in captured.out
    assert "Minimum: 25.50" in captured.out
    assert "Maximum: 25.50" in captured.out
    assert "Average: 25.50" in captured.out
    assert "Median: 25.50" in captured.out
    assert "Observations: 1" in captured.out


def test_stats_cli_explicit_source_keeps_equal_external_ids_separate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "sources.db"
    with SQLiteListingRepository(database_path) as repository:
        _persist(
            repository,
            _listing(
                price="19.99",
                collected_at=FIRST_TIME,
                title="Mercado Libre title",
            ),
        )
        _persist(
            repository,
            _listing(
                price="25.50",
                collected_at=FIRST_TIME,
                source=MarketplaceSource.FACEBOOK_MARKETPLACE,
                title="Facebook title",
            ),
        )
    _configure(monkeypatch, database_path)
    provider_factory = ForbiddenProviderFactory()

    exit_code = main(
        ["stats", EXTERNAL_ID, "--source", "facebook_marketplace"],
        provider_factory=provider_factory,
    )

    captured = capsys.readouterr()
    assert exit_code == ExitCode.SUCCESS
    assert provider_factory.calls == 0
    assert "Source: facebook_marketplace" in captured.out
    assert "Title: Facebook title" in captured.out
    assert "Current price: 25.50" in captured.out
    assert "Mercado Libre title" not in captured.out
    assert "Current price: 19.99" not in captured.out


def test_stats_cli_missing_database_and_listing_have_controlled_distinct_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing_database = tmp_path / "missing-parent" / "stats.db"
    _configure(monkeypatch, missing_database)
    provider_factory = ForbiddenProviderFactory()

    missing_database_exit = main(
        ["stats", "MLV-MISSING"],
        provider_factory=provider_factory,
    )
    missing_database_output = capsys.readouterr()

    assert missing_database_exit == ExitCode.PERSISTENCE_ERROR
    assert "database not found" in missing_database_output.err
    assert "Traceback" not in missing_database_output.err
    assert not missing_database.exists()
    assert not missing_database.parent.exists()

    initialized_database = tmp_path / "initialized.db"
    with SQLiteListingRepository(initialized_database):
        pass
    _configure(monkeypatch, initialized_database)

    missing_listing_exit = main(
        ["stats", "MLV-MISSING"],
        provider_factory=provider_factory,
    )
    missing_listing_output = capsys.readouterr()

    assert missing_listing_exit == ExitCode.NOT_FOUND
    assert "Listing not found: mercado_libre/MLV-MISSING" in missing_listing_output.err
    assert "database not found" not in missing_listing_output.err
    assert "Traceback" not in missing_listing_output.err
    assert provider_factory.calls == 0


def test_stats_cli_rejects_multiple_currencies_as_a_controlled_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "currencies.db"
    with SQLiteListingRepository(database_path) as repository:
        _persist(
            repository,
            _listing(price="19.99", currency="VES", collected_at=FIRST_TIME),
        )
        _persist(
            repository,
            _listing(price="10.00", currency="USD", collected_at=SECOND_TIME),
        )
    _configure(monkeypatch, database_path)
    history_factory = CapturingHistoryRepositoryFactory()

    exit_code = main(
        ["stats", EXTERNAL_ID],
        history_repository_factory=history_factory,
    )

    captured = capsys.readouterr()
    assert exit_code == ExitCode.STATISTICS_UNAVAILABLE
    assert len(history_factory.repositories) == 1
    with pytest.raises(PersistenceError, match="closed"):
        history_factory.repositories[0].get_history(
            ListingKey(MarketplaceSource.MERCADO_LIBRE, EXTERNAL_ID)
        )
    assert "Cannot calculate statistics across multiple currencies: USD, VES" in captured.err
    assert "Traceback" not in captured.err


def test_stats_cli_handles_a_known_listing_without_observations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "empty-history.db"
    with SQLiteListingRepository(database_path):
        pass
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            """
            INSERT INTO listings (
                source, external_id, title, url, first_seen_at, last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                MarketplaceSource.MERCADO_LIBRE.value,
                EXTERNAL_ID,
                "Pastillas sin observaciones",
                f"https://example.test/{EXTERNAL_ID}",
                "2026-08-01T14:00:00.000000Z",
                "2026-08-01T14:00:00.000000Z",
            ),
        )
        connection.commit()
    finally:
        connection.close()
    _configure(monkeypatch, database_path)
    provider_factory = ForbiddenProviderFactory()

    exit_code = main(
        ["stats", EXTERNAL_ID],
        provider_factory=provider_factory,
    )

    captured = capsys.readouterr()
    assert exit_code == ExitCode.STATISTICS_UNAVAILABLE
    assert provider_factory.calls == 0
    assert "Cannot calculate statistics without price observations" in captured.err
    assert "Traceback" not in captured.err


def test_python_module_stats_works_without_marketplace_configuration(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "module-stats.db"
    _seed_three_observations(database_path)
    environment = os.environ.copy()
    environment["BERA_TRACKER_DATABASE_PATH"] = str(database_path)
    environment.pop("BERA_TRACKER_MERCADOLIBRE_SITE_ID", None)
    environment.pop("BERA_TRACKER_MERCADOLIBRE_ACCESS_TOKEN", None)

    completed = subprocess.run(
        [sys.executable, "-m", "bera_price_tracker", "stats", EXTERNAL_ID],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == ExitCode.SUCCESS
    assert "Current price: 21.99" in completed.stdout
    assert "Observations: 3" in completed.stdout
    assert "Traceback" not in completed.stderr
    assert "Authorization" not in completed.stderr
