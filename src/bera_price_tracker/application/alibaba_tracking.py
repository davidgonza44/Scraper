"""Follow Alibaba prices using existing Listing / snapshot persistence.

The GUI never talks to SQLite. This service records one already-loaded
product as a Listing plus PriceSnapshot. Representative price is the
historical value; published min/max/display stay on the listing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from bera_price_tracker.application.statistics import calculate_listing_statistics
from bera_price_tracker.domain import (
    CollectionBatch,
    Listing,
    ListingHistory,
    ListingKey,
    MarketplaceSource,
    PriceObservation,
    SearchQuery,
)

type CollectionClock = Callable[[], datetime]

FOLLOW_SOURCE = MarketplaceSource.ALIBABA
MISSING_PRODUCT_ID = "Este producto no tiene un identificador estable."
MISSING_PRICE = "Este producto no tiene un precio utilizable."
MISSING_URL = "Este producto no tiene un enlace público."
MISSING_TITLE = "Este producto no tiene título."
UNKNOWN_LISTING = "Este producto no está en el seguimiento."
PERCENT_UNAVAILABLE = "unavailable"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AlibabaFollowError(ValueError):
    """Local validation failure while following an already-loaded product."""


class AlibabaTrackingRepository(Protocol):
    """Write-side persistence used by Alibaba follow. Implemented by SQLite."""

    def record_collection(self, batch: CollectionBatch) -> None: ...

    def get_listing(self, key: ListingKey) -> Any | None: ...

    def get_price_history(self, key: ListingKey) -> Sequence[Any]: ...

    def set_listing_active(self, key: ListingKey, active: bool) -> bool: ...

    def list_listing_keys(
        self,
        source: MarketplaceSource,
        *,
        active_only: bool = False,
    ) -> list[ListingKey]: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class AlibabaFollowObservation:
    """Public fields required to persist one already-loaded Alibaba product."""

    product_id: str
    title: str
    url: str
    representative_price: Decimal
    currency: str
    query: str
    price_display: str | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    supplier_name: str | None = None
    supplier_country: str | None = None


@dataclass(frozen=True, slots=True)
class AlibabaTrackingVariation:
    """Decimal variation derived from persisted representative prices."""

    first_price: Decimal
    last_price: Decimal
    historical_minimum: Decimal
    historical_maximum: Decimal
    snapshot_count: int
    absolute_change: Decimal | None
    percentage_change: Decimal | None


@dataclass(frozen=True, slots=True)
class AlibabaTrackedProduct:
    """Read model for the Seguimiento section."""

    product_id: str
    title: str
    supplier_name: str | None
    url: str
    is_active: bool
    current_price_display: str
    price_min: Decimal | None
    price_max: Decimal | None
    last_updated: datetime
    variation: AlibabaTrackingVariation
    history: tuple[PriceObservation, ...]


def alibaba_listing_key(product_id: str) -> ListingKey:
    normalized = product_id.strip() if isinstance(product_id, str) else ""
    if not normalized:
        raise AlibabaFollowError(MISSING_PRODUCT_ID)
    return ListingKey(source=FOLLOW_SOURCE, external_id=normalized)


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _required_product_id(value: object) -> str:
    text = _optional_text(value)
    if text is None:
        raise AlibabaFollowError(MISSING_PRODUCT_ID)
    return text


def _parse_decimal(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = Decimal(value.strip())
        except InvalidOperation:
            return None
    else:
        return None
    if not parsed.is_finite() or parsed <= Decimal("0"):
        return None
    return parsed


def observation_from_loaded_row(row: Mapping[str, object], query: str) -> AlibabaFollowObservation:
    """Build a follow observation from already-loaded GUI/search fields only."""

    representative = _parse_decimal(row.get("representative"))
    if representative is None:
        raise AlibabaFollowError(MISSING_PRICE)
    title = _optional_text(row.get("title"))
    if title is None:
        raise AlibabaFollowError(MISSING_TITLE)
    url = _optional_text(row.get("url"))
    if url is None:
        raise AlibabaFollowError(MISSING_URL)
    currency = _optional_text(row.get("currency")) or "USD"
    query_text = query.strip() if isinstance(query, str) and query.strip() else "alibaba"
    return AlibabaFollowObservation(
        product_id=_required_product_id(row.get("product_id")),
        title=title,
        url=url,
        representative_price=representative,
        currency=currency,
        query=query_text,
        price_display=_optional_text(row.get("price")) or _optional_text(row.get("price_display")),
        min_price=_parse_decimal(row.get("price_min", row.get("min_price"))),
        max_price=_parse_decimal(row.get("price_max", row.get("max_price"))),
        supplier_name=_optional_text(row.get("supplier_name")),
        supplier_country=_optional_text(row.get("supplier_country")),
    )


def listing_from_observation(
    observation: AlibabaFollowObservation,
    collected_at: datetime,
) -> Listing:
    return Listing(
        source=FOLLOW_SOURCE,
        external_id=observation.product_id,
        title=observation.title,
        price=observation.representative_price,
        currency=observation.currency,
        url=observation.url,
        query=SearchQuery(observation.query),
        collected_at=collected_at,
        seller_name=observation.supplier_name,
        location=observation.supplier_country,
        formatted_amount=observation.price_display,
        price_min=observation.min_price,
        price_max=observation.max_price,
    )


def history_from_repository(
    repository: AlibabaTrackingRepository,
    key: ListingKey,
) -> ListingHistory | None:
    listing = repository.get_listing(key)
    if listing is None:
        return None
    observations = tuple(
        PriceObservation(
            price=item.snapshot.price,
            currency=item.snapshot.currency,
            collected_at=item.snapshot.collected_at,
            query=item.query,
            usd_amount=item.snapshot.usd_amount,
        )
        for item in repository.get_price_history(key)
    )
    return ListingHistory(
        key=listing.key,
        title=listing.title,
        url=listing.url,
        first_seen_at=listing.first_seen_at,
        last_seen_at=listing.last_seen_at,
        observations=observations,
        seller_name=listing.seller_name,
        location=listing.location,
        product_condition=listing.product_condition,
    )


def percentage_change(absolute_change: Decimal, previous_price: Decimal) -> Decimal | None:
    """Return percent change, or None when the previous price is 0."""

    if not isinstance(absolute_change, Decimal) or not isinstance(previous_price, Decimal):
        raise TypeError("variation amounts must be Decimal")
    if previous_price == Decimal("0"):
        return None
    return (absolute_change / previous_price) * Decimal("100")


def calculate_alibaba_tracking_variation(
    observations: Sequence[PriceObservation],
) -> AlibabaTrackingVariation:
    """First/last/min/max/count plus change vs the previous snapshot.

    Percentage is unavailable when there is no previous price or it is 0.
    """

    if not observations:
        raise AlibabaFollowError("No hay snapshots de precio.")
    history = ListingHistory(
        key=ListingKey(source=FOLLOW_SOURCE, external_id="variation"),
        title="variation",
        url="https://www.alibaba.com/product-detail/variation.html",
        first_seen_at=observations[0].collected_at,
        last_seen_at=observations[-1].collected_at,
        observations=tuple(observations),
    )
    stats = calculate_listing_statistics(history)
    previous = stats.previous_price
    percentage = None
    if previous is not None and stats.absolute_change is not None:
        percentage = percentage_change(stats.absolute_change, previous)
    return AlibabaTrackingVariation(
        first_price=observations[0].price,
        last_price=stats.current_price,
        historical_minimum=stats.minimum_price,
        historical_maximum=stats.maximum_price,
        snapshot_count=stats.observation_count,
        absolute_change=stats.absolute_change,
        percentage_change=percentage,
    )


def _current_display(listing: Any, last_price: Decimal) -> str:
    display = getattr(listing, "price_display", None)
    if isinstance(display, str) and display.strip():
        return display
    return str(last_price)


def tracked_product_from_repository(
    repository: AlibabaTrackingRepository,
    key: ListingKey,
) -> AlibabaTrackedProduct | None:
    listing = repository.get_listing(key)
    history = history_from_repository(repository, key)
    if listing is None or history is None or not history.observations:
        return None
    variation = calculate_alibaba_tracking_variation(history.observations)
    return AlibabaTrackedProduct(
        product_id=key.external_id,
        title=listing.title,
        supplier_name=listing.seller_name,
        url=listing.url,
        is_active=listing.is_active,
        current_price_display=_current_display(listing, variation.last_price),
        price_min=listing.price_min,
        price_max=listing.price_max,
        last_updated=history.observations[-1].collected_at,
        variation=variation,
        history=history.observations,
    )


def _record_observation(
    repository: AlibabaTrackingRepository,
    observation: AlibabaFollowObservation,
    collected_at: datetime,
) -> AlibabaTrackedProduct:
    listing = listing_from_observation(observation, collected_at)
    repository.record_collection(
        CollectionBatch.from_listings(
            source=FOLLOW_SOURCE,
            query=listing.query,
            collected_at=collected_at,
            listings=(listing,),
        )
    )
    tracked = tracked_product_from_repository(repository, listing.key)
    if tracked is None:
        raise AlibabaFollowError("No se pudo guardar el seguimiento.")
    return tracked


@dataclass(frozen=True, slots=True)
class FollowAlibabaPrice:
    """Persist one already-loaded Alibaba product and its first snapshot."""

    repository: AlibabaTrackingRepository
    clock: CollectionClock = _utc_now

    def execute(self, observation: AlibabaFollowObservation) -> AlibabaTrackedProduct:
        if not isinstance(observation, AlibabaFollowObservation):
            raise TypeError("observation must be an AlibabaFollowObservation")
        key = alibaba_listing_key(observation.product_id)
        existing = self.repository.get_listing(key)
        if existing is not None and existing.is_active:
            tracked = tracked_product_from_repository(self.repository, key)
            if tracked is not None:
                return tracked
        tracked = _record_observation(self.repository, observation, self.clock())
        self.repository.set_listing_active(key, True)
        refreshed = tracked_product_from_repository(self.repository, key)
        return refreshed if refreshed is not None else tracked


@dataclass(frozen=True, slots=True)
class RecordAlibabaPriceSnapshot:
    """Append a later snapshot. Not used by automatic refresh."""

    repository: AlibabaTrackingRepository
    clock: CollectionClock = _utc_now

    def execute(self, observation: AlibabaFollowObservation) -> AlibabaTrackedProduct:
        if not isinstance(observation, AlibabaFollowObservation):
            raise TypeError("observation must be an AlibabaFollowObservation")
        return _record_observation(self.repository, observation, self.clock())


@dataclass(frozen=True, slots=True)
class UnfollowAlibabaPrice:
    """Deactivate tracking without deleting listing metadata or snapshots."""

    repository: AlibabaTrackingRepository

    def execute(self, product_id: str) -> AlibabaTrackedProduct:
        key = alibaba_listing_key(product_id)
        if not self.repository.set_listing_active(key, False):
            raise AlibabaFollowError(UNKNOWN_LISTING)
        tracked = tracked_product_from_repository(self.repository, key)
        if tracked is None:
            raise AlibabaFollowError(UNKNOWN_LISTING)
        return tracked


@dataclass(frozen=True, slots=True)
class ListAlibabaTracked:
    """Return followed Alibaba products. Inactive rows are omitted by default."""

    repository: AlibabaTrackingRepository

    def execute(self, *, active_only: bool = True) -> list[AlibabaTrackedProduct]:
        products: list[AlibabaTrackedProduct] = []
        for key in self.repository.list_listing_keys(FOLLOW_SOURCE, active_only=active_only):
            tracked = tracked_product_from_repository(self.repository, key)
            if tracked is not None:
                products.append(tracked)
        return products


__all__ = [
    "FOLLOW_SOURCE",
    "MISSING_PRICE",
    "MISSING_PRODUCT_ID",
    "MISSING_TITLE",
    "MISSING_URL",
    "PERCENT_UNAVAILABLE",
    "UNKNOWN_LISTING",
    "AlibabaFollowError",
    "AlibabaFollowObservation",
    "AlibabaTrackedProduct",
    "AlibabaTrackingVariation",
    "FollowAlibabaPrice",
    "ListAlibabaTracked",
    "RecordAlibabaPriceSnapshot",
    "UnfollowAlibabaPrice",
    "alibaba_listing_key",
    "calculate_alibaba_tracking_variation",
    "history_from_repository",
    "listing_from_observation",
    "observation_from_loaded_row",
    "tracked_product_from_repository",
]
