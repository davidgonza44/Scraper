"""Unit tests for application orchestration."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from bera_price_tracker.application import (
    DEFAULT_INSPECTION_LIMIT,
    MAX_INSPECTION_LIMIT,
    MIN_INSPECTION_LIMIT,
    CollectListings,
    GetListingHistory,
    InspectLatestCollection,
)
from bera_price_tracker.domain import (
    CollectionBatch,
    CollectionRunInspection,
    Listing,
    ListingHistory,
    ListingKey,
    MarketplaceSource,
    ObservedListing,
    PriceObservation,
    SearchQuery,
)


def make_listing(query: SearchQuery) -> Listing:
    return Listing(
        source=MarketplaceSource.MERCADO_LIBRE,
        external_id="MLV-123",
        title="Pastillas BERA",
        price=Decimal("15.00"),
        currency="USD",
        url="https://example.test/MLV-123",
        query=query,
        collected_at=datetime(2026, 8, 21, 12, tzinfo=UTC),
    )


@dataclass(slots=True)
class FakeProvider:
    listings: list[Listing]
    received_queries: list[SearchQuery] = field(default_factory=list)

    @property
    def source(self) -> MarketplaceSource:
        return MarketplaceSource.MERCADO_LIBRE

    def search(self, query: SearchQuery) -> list[Listing]:
        self.received_queries.append(query)
        return self.listings


@dataclass(slots=True)
class FakeRepository:
    batches: list[CollectionBatch] = field(default_factory=list)

    def record_collection(self, batch: CollectionBatch) -> None:
        self.batches.append(batch)


def test_collect_listings_searches_and_records_a_snapshot() -> None:
    query = SearchQuery("pastillas bera")
    listing = make_listing(query)
    provider = FakeProvider([listing])
    repository = FakeRepository()
    service = CollectListings(provider=provider, repository=repository)

    result = service.execute(query)

    assert result == [listing]
    assert provider.received_queries == [query]
    assert repository.batches == [
        CollectionBatch(
            source=listing.source,
            query=query,
            collected_at=listing.collected_at,
            listings=(listing,),
        )
    ]


@dataclass(slots=True)
class CountingBatchRepository:
    batches: list[CollectionBatch] = field(default_factory=list)

    def record_collection(self, batch: CollectionBatch) -> None:
        self.batches.append(batch)


def test_collect_listings_uses_one_repository_batch_operation() -> None:
    query = SearchQuery("pastillas bera")
    first = make_listing(query)
    second = Listing(
        source=MarketplaceSource.MERCADO_LIBRE,
        external_id="MLV-456",
        title="Pastillas BERA BR150",
        price=Decimal("20.00"),
        currency="USD",
        url="https://example.test/MLV-456",
        query=query,
        collected_at=first.collected_at,
    )
    repository = CountingBatchRepository()
    service = CollectListings(
        provider=FakeProvider([first, second]),
        repository=repository,
    )

    assert service.execute(query) == [first, second]

    assert len(repository.batches) == 1
    assert repository.batches[0].listings == (first, second)


def test_collect_listings_uses_injected_clock_for_an_empty_batch() -> None:
    query = SearchQuery("pastillas bera")
    collected_at = datetime(2026, 8, 22, 12, tzinfo=UTC)
    repository = FakeRepository()
    service = CollectListings(
        provider=FakeProvider([]),
        repository=repository,
        clock=lambda: collected_at,
    )

    assert service.execute(query) == []
    assert repository.batches == [
        CollectionBatch(
            source=MarketplaceSource.MERCADO_LIBRE,
            query=query,
            collected_at=collected_at,
            listings=(),
        )
    ]


def test_collect_listings_returns_deduplicated_last_observation() -> None:
    query = SearchQuery("pastillas bera")
    first = make_listing(query)
    last = Listing(
        source=first.source,
        external_id=first.external_id,
        title="Pastillas actualizadas",
        price=Decimal("18.00"),
        currency=first.currency,
        url=first.url,
        query=query,
        collected_at=first.collected_at,
    )
    repository = FakeRepository()
    service = CollectListings(
        provider=FakeProvider([first, last]),
        repository=repository,
    )

    assert service.execute(query) == [last]
    assert repository.batches[0].listings == (last,)


@dataclass(slots=True)
class FakeHistoryRepository:
    result: ListingHistory | None
    received_keys: list[ListingKey] = field(default_factory=list)

    def get_history(self, key: ListingKey) -> ListingHistory | None:
        self.received_keys.append(key)
        return self.result


def test_get_listing_history_delegates_the_exact_key() -> None:
    listing = make_listing(SearchQuery("pastillas bera"))
    history = ListingHistory(
        key=listing.key,
        title=listing.title,
        url=listing.url,
        first_seen_at=listing.collected_at,
        last_seen_at=listing.collected_at,
        observations=(
            PriceObservation(
                price=listing.price,
                currency=listing.currency,
                collected_at=listing.collected_at,
                query=listing.query,
            ),
        ),
    )
    repository = FakeHistoryRepository(history)

    assert GetListingHistory(repository).execute(listing.key) == history
    assert repository.received_keys == [listing.key]


def test_get_listing_history_propagates_not_found() -> None:
    key = ListingKey(MarketplaceSource.MERCADO_LIBRE, "MLV-MISSING")
    repository = FakeHistoryRepository(None)

    assert GetListingHistory(repository).execute(key) is None
    assert repository.received_keys == [key]


@dataclass(slots=True)
class FakeInspectionRepository:
    result: CollectionRunInspection | None
    calls: list[tuple[MarketplaceSource, SearchQuery, int]] = field(default_factory=list)

    def get_latest_run(
        self,
        source: MarketplaceSource,
        query: SearchQuery,
        limit: int,
    ) -> CollectionRunInspection | None:
        self.calls.append((source, query, limit))
        return self.result


def make_inspection(query: SearchQuery) -> CollectionRunInspection:
    source = MarketplaceSource.MERCADO_LIBRE
    return CollectionRunInspection(
        source=source,
        query=query,
        collected_at=datetime(2026, 8, 21, 16, tzinfo=UTC),
        total_listings=1,
        observations=(
            ObservedListing(
                key=ListingKey(source, "MLV-INSPECT"),
                title="Pastillas BERA",
                url="https://example.test/MLV-INSPECT",
                price=Decimal("19.99"),
                currency="VES",
            ),
        ),
    )


def test_inspect_latest_collection_delegates_with_default_limit() -> None:
    query = SearchQuery("pastillas bera")
    inspection = make_inspection(query)
    repository = FakeInspectionRepository(inspection)

    result = InspectLatestCollection(repository).execute(
        MarketplaceSource.MERCADO_LIBRE,
        query,
    )

    assert result is inspection
    assert repository.calls == [(MarketplaceSource.MERCADO_LIBRE, query, DEFAULT_INSPECTION_LIMIT)]


def test_inspect_latest_collection_delegates_custom_limit_and_not_found() -> None:
    query = SearchQuery("no recolectada")
    repository = FakeInspectionRepository(None)

    result = InspectLatestCollection(repository).execute(
        MarketplaceSource.FACEBOOK_MARKETPLACE,
        query,
        limit=50,
    )

    assert result is None
    assert repository.calls == [(MarketplaceSource.FACEBOOK_MARKETPLACE, query, 50)]


@pytest.mark.parametrize("limit", [MIN_INSPECTION_LIMIT - 1, MAX_INSPECTION_LIMIT + 1])
def test_inspect_latest_collection_rejects_out_of_range_limit(limit: int) -> None:
    repository = FakeInspectionRepository(None)

    with pytest.raises(ValueError, match="limit"):
        InspectLatestCollection(repository).execute(
            MarketplaceSource.MERCADO_LIBRE,
            SearchQuery("pastillas bera"),
            limit=limit,
        )

    assert repository.calls == []


def test_inspect_latest_collection_rejects_non_integer_limit() -> None:
    repository = FakeInspectionRepository(None)

    with pytest.raises(TypeError, match="integer"):
        InspectLatestCollection(repository).execute(
            MarketplaceSource.MERCADO_LIBRE,
            SearchQuery("pastillas bera"),
            limit=True,
        )

    assert repository.calls == []
