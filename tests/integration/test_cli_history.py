"""Offline integration coverage for the local history CLI path."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
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
QUERY_ONE = SearchQuery("pastillas de freno bera")
QUERY_TWO = SearchQuery("pastillas bera")
FIRST_TIME = datetime(2026, 8, 1, 14, 0, tzinfo=UTC)
SECOND_TIME = datetime(2026, 8, 10, 14, 0, tzinfo=UTC)
THIRD_TIME = datetime(2026, 8, 20, 14, 0, tzinfo=UTC)


@dataclass(slots=True)
class ForbiddenProviderFactory:
    """Fail immediately if the history path tries to construct HTTP infrastructure."""

    calls: int = 0

    def __call__(self, _: Settings) -> MarketplaceProvider:
        self.calls += 1
        raise AssertionError("history must not construct a marketplace provider")


@dataclass(slots=True)
class CapturingHistoryRepositoryFactory:
    repositories: list[SQLiteListingHistoryRepository] = field(default_factory=list)

    def __call__(self, settings: Settings) -> SQLiteListingHistoryRepository:
        repository = SQLiteListingHistoryRepository(settings.database_path)
        self.repositories.append(repository)
        return repository


def _listing(
    *,
    source: MarketplaceSource = MarketplaceSource.MERCADO_LIBRE,
    external_id: str = EXTERNAL_ID,
    title: str = "Pastillas de freno BERA SBR",
    price: str,
    query: SearchQuery,
    collected_at: datetime,
    seller_name: str | None = "Repuestos BERA",
    location: str | None = "Caracas",
) -> Listing:
    return Listing(
        source=source,
        external_id=external_id,
        title=title,
        price=Decimal(price),
        currency="VES",
        url=f"https://example.test/{source.value}/{external_id}",
        query=query,
        collected_at=collected_at,
        seller_name=seller_name,
        location=location,
        product_condition="new",
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
        _persist(
            repository,
            _listing(price="19.99", query=QUERY_ONE, collected_at=FIRST_TIME),
        )
        _persist(
            repository,
            _listing(price="19.99", query=QUERY_TWO, collected_at=SECOND_TIME),
        )
        _persist(
            repository,
            _listing(price="21.99", query=QUERY_ONE, collected_at=THIRD_TIME),
        )


def _configure_history(monkeypatch: pytest.MonkeyPatch, database_path: Path) -> None:
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


def test_history_cli_reads_three_observations_without_http_or_database_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "history.db"
    _seed_three_observations(database_path)
    _configure_history(monkeypatch, database_path)
    provider_factory = ForbiddenProviderFactory()
    history_factory = CapturingHistoryRepositoryFactory()
    state_before = _database_state(database_path)
    bytes_before = database_path.read_bytes()

    exit_code = main(
        ["history", EXTERNAL_ID],
        provider_factory=provider_factory,
        history_repository_factory=history_factory,
    )

    captured = capsys.readouterr()
    assert exit_code == ExitCode.SUCCESS
    assert provider_factory.calls == 0
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
    assert f"URL: https://example.test/mercado_libre/{EXTERNAL_ID}" in captured.out
    assert "Seller: Repuestos BERA" in captured.out
    assert "Location: Caracas" in captured.out
    assert "First seen: 2026-08-01 14:00:00 UTC" in captured.out
    assert "Last seen: 2026-08-20 14:00:00 UTC" in captured.out
    expected_lines = [
        "2026-08-01 14:00:00 UTC | USD: unavailable | 19.99 VES | pastillas de freno bera",
        "2026-08-10 14:00:00 UTC | USD: unavailable | 19.99 VES | pastillas bera",
        "2026-08-20 14:00:00 UTC | USD: unavailable | 21.99 VES | pastillas de freno bera",
    ]
    positions = [captured.out.index(line) for line in expected_lines]
    assert positions == sorted(positions)
    assert captured.out.count("19.99 VES") == 2
    assert captured.err == ""


def test_history_cli_explicit_source_keeps_equal_external_ids_separate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "sources.db"
    with SQLiteListingRepository(database_path) as repository:
        _persist(
            repository,
            _listing(
                title="Mercado Libre title",
                price="19.99",
                query=QUERY_ONE,
                collected_at=FIRST_TIME,
            ),
        )
        _persist(
            repository,
            _listing(
                source=MarketplaceSource.FACEBOOK_MARKETPLACE,
                title="Facebook title",
                price="25.50",
                query=QUERY_ONE,
                collected_at=FIRST_TIME,
            ),
        )
    _configure_history(monkeypatch, database_path)
    provider_factory = ForbiddenProviderFactory()

    exit_code = main(
        ["history", EXTERNAL_ID, "--source", "facebook_marketplace"],
        provider_factory=provider_factory,
    )

    captured = capsys.readouterr()
    assert exit_code == ExitCode.SUCCESS
    assert provider_factory.calls == 0
    assert "Source: facebook_marketplace" in captured.out
    assert "Title: Facebook title" in captured.out
    assert "25.50 VES" in captured.out
    assert "Mercado Libre title" not in captured.out
    assert "19.99 VES" not in captured.out


def test_history_cli_missing_database_is_controlled_and_does_not_create_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "missing-parent" / "history.db"
    _configure_history(monkeypatch, database_path)
    provider_factory = ForbiddenProviderFactory()

    exit_code = main(
        ["history", "MLV-MISSING"],
        provider_factory=provider_factory,
    )

    captured = capsys.readouterr()
    assert exit_code == ExitCode.PERSISTENCE_ERROR
    assert provider_factory.calls == 0
    assert "database not found" in captured.err
    assert "Traceback" not in captured.err
    assert not database_path.exists()
    assert not database_path.parent.exists()


def test_history_cli_unknown_listing_has_a_distinct_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "not-found.db"
    with SQLiteListingRepository(database_path):
        pass
    _configure_history(monkeypatch, database_path)
    provider_factory = ForbiddenProviderFactory()

    exit_code = main(
        ["history", "MLV999"],
        provider_factory=provider_factory,
    )

    captured = capsys.readouterr()
    assert exit_code == ExitCode.NOT_FOUND
    assert provider_factory.calls == 0
    assert "Listing not found: mercado_libre/MLV999" in captured.err
    assert "database not found" not in captured.err
    assert "Traceback" not in captured.err


def test_python_module_history_reads_sqlite_without_marketplace_configuration(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "module-history.db"
    with SQLiteListingRepository(database_path) as repository:
        _persist(
            repository,
            _listing(price="19.99", query=QUERY_ONE, collected_at=FIRST_TIME),
        )
    environment = os.environ.copy()
    environment["BERA_TRACKER_DATABASE_PATH"] = str(database_path)
    environment.pop("BERA_TRACKER_MERCADOLIBRE_SITE_ID", None)
    environment.pop("BERA_TRACKER_MERCADOLIBRE_ACCESS_TOKEN", None)

    completed = subprocess.run(
        [sys.executable, "-m", "bera_price_tracker", "history", EXTERNAL_ID],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == ExitCode.SUCCESS
    assert f"ID: {EXTERNAL_ID}" in completed.stdout
    assert "19.99 VES" in completed.stdout
    assert "Traceback" not in completed.stderr
    assert "Authorization" not in completed.stderr
