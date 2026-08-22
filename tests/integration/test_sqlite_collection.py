"""Offline integration test from the application service to SQLite."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from bera_price_tracker.application import CollectListings
from bera_price_tracker.domain import Listing, MarketplaceSource, SearchQuery
from bera_price_tracker.infrastructure.persistence import SQLiteListingRepository


@dataclass(slots=True)
class FakeMarketplaceProvider:
    listings: list[Listing]

    @property
    def source(self) -> MarketplaceSource:
        return MarketplaceSource.MERCADO_LIBRE

    def search(self, query: SearchQuery) -> list[Listing]:
        assert all(listing.query == query for listing in self.listings)
        return self.listings


def test_collect_listings_persists_one_run_and_exact_prices(tmp_path: Path) -> None:
    query = SearchQuery("pastillas de freno bera")
    collected_at = datetime(2026, 8, 21, 15, tzinfo=UTC)
    listings = [
        Listing(
            source=MarketplaceSource.MERCADO_LIBRE,
            external_id="MLV-1",
            title="Pastillas BERA SBR",
            price=Decimal("19.99"),
            currency="USD",
            url="https://example.test/MLV-1",
            query=query,
            collected_at=collected_at,
        ),
        Listing(
            source=MarketplaceSource.MERCADO_LIBRE,
            external_id="MLV-2",
            title="Pastillas BERA BR150",
            price=Decimal("1250.50"),
            currency="VES",
            url="https://example.test/MLV-2",
            query=query,
            collected_at=collected_at,
        ),
    ]

    with SQLiteListingRepository(tmp_path / "integration.db") as repository:
        service = CollectListings(
            provider=FakeMarketplaceProvider(listings),
            repository=repository,
        )

        assert service.execute(query) == listings
        assert repository.count_listings() == 2
        assert repository.count_collection_runs() == 1
        assert repository.count_price_snapshots() == 2
        assert repository.get_price_history(listings[0].key)[0].snapshot.price == Decimal("19.99")
        assert repository.get_price_history(listings[1].key)[0].snapshot.price == Decimal("1250.50")
