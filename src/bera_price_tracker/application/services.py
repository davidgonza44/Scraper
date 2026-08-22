"""Use cases that coordinate domain objects and application ports."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from bera_price_tracker.application.ports import (
    AlibabaSearchProvider,
    CollectionInspectionRepository,
    ListingHistoryRepository,
    ListingRepository,
    MarketplaceProvider,
)
from bera_price_tracker.application.statistics import calculate_listing_statistics
from bera_price_tracker.domain import (
    CollectionBatch,
    CollectionRunInspection,
    Listing,
    ListingHistory,
    ListingKey,
    ListingStatistics,
    MarketplaceSource,
    SearchQuery,
)
from bera_price_tracker.domain.alibaba import AlibabaProduct

type CollectionClock = Callable[[], datetime]

DEFAULT_INSPECTION_LIMIT = 20
MIN_INSPECTION_LIMIT = 1
MAX_INSPECTION_LIMIT = 200


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class CollectListings:
    """Collect and atomically record one normalized marketplace search batch."""

    provider: MarketplaceProvider
    repository: ListingRepository
    clock: CollectionClock = _utc_now

    def execute(self, query: SearchQuery) -> list[Listing]:
        listings = self.provider.search(query)
        collected_at = listings[0].collected_at if listings else self.clock()
        batch = CollectionBatch.from_listings(
            source=self.provider.source,
            query=query,
            collected_at=collected_at,
            listings=listings,
        )
        self.repository.record_collection(batch)
        return list(batch.listings)


@dataclass(frozen=True, slots=True)
class GetListingHistory:
    """Read one listing's persisted history without infrastructure knowledge."""

    repository: ListingHistoryRepository

    def execute(self, key: ListingKey) -> ListingHistory | None:
        return self.repository.get_history(key)


@dataclass(frozen=True, slots=True)
class GetListingStatistics:
    """Read one listing's history and derive local statistics from it."""

    repository: ListingHistoryRepository

    def execute(self, key: ListingKey) -> ListingStatistics | None:
        history = self.repository.get_history(key)
        if history is None:
            return None
        return calculate_listing_statistics(history)


@dataclass(frozen=True, slots=True)
class InspectLatestCollection:
    """Read the latest persisted collection run for one source and query."""

    repository: CollectionInspectionRepository

    def execute(
        self,
        source: MarketplaceSource,
        query: SearchQuery,
        *,
        limit: int = DEFAULT_INSPECTION_LIMIT,
    ) -> CollectionRunInspection | None:
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise TypeError("limit must be an integer")
        if not MIN_INSPECTION_LIMIT <= limit <= MAX_INSPECTION_LIMIT:
            raise ValueError(
                f"limit must be between {MIN_INSPECTION_LIMIT} and {MAX_INSPECTION_LIMIT}"
            )
        return self.repository.get_latest_run(source, query, limit)


MIN_ALIBABA_LIMIT = 1
MAX_ALIBABA_LIMIT = 500
ALIBABA_CREDIT_WARNING = "Esta búsqueda puede consumir más créditos de Apify."


def validate_alibaba_search(query: str, limit: int) -> tuple[str, int]:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")
    if not MIN_ALIBABA_LIMIT <= limit <= MAX_ALIBABA_LIMIT:
        raise ValueError(f"limit must be between {MIN_ALIBABA_LIMIT} and {MAX_ALIBABA_LIMIT}")
    return query.strip(), limit


def alibaba_credit_warning(limit: int) -> str | None:
    if isinstance(limit, bool) or not isinstance(limit, int):
        return None
    if limit > 100 and limit <= MAX_ALIBABA_LIMIT:
        return ALIBABA_CREDIT_WARNING
    return None


@dataclass(frozen=True, slots=True)
class SearchAlibabaProducts:
    """Read-only Alibaba search. One execute maps to one provider.search."""

    provider: AlibabaSearchProvider

    def execute(self, query: str, limit: int) -> list[AlibabaProduct]:
        normalized_query, normalized_limit = validate_alibaba_search(query, limit)
        return list(self.provider.search(normalized_query, normalized_limit))
