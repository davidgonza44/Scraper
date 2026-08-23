"""Domain models shared by every marketplace adapter."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from urllib.parse import urlsplit

_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


class MarketplaceSource(StrEnum):
    """Supported marketplace identifiers."""

    MERCADO_LIBRE = "mercado_libre"
    FACEBOOK_MARKETPLACE = "facebook_marketplace"
    ALIBABA = "alibaba"


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def _optional_text(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name)


def _price(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError("price must be a Decimal")
    if not value.is_finite():
        raise ValueError("price must be finite")
    if value <= Decimal("0"):
        raise ValueError("price must be greater than zero")
    return value


def _finite_decimal(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return value


_NON_ISO_CURRENCIES = frozenset({"UNKNOWN", "$"})


def _currency(value: str) -> str:
    normalized = _required_text(value, "currency").upper()
    if _CURRENCY_PATTERN.fullmatch(normalized) is not None:
        return normalized
    if normalized in _NON_ISO_CURRENCIES:
        return normalized
    raise ValueError("currency must contain exactly three ASCII letters")


def _url(value: str) -> str:
    normalized = _required_text(value, "url")
    parsed = urlsplit(normalized)
    if parsed.scheme.lower() not in {"http", "https"} or parsed.hostname is None:
        raise ValueError("url must be an absolute HTTP(S) URL")
    return normalized


def _collected_at(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("collected_at must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("collected_at must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """Normalized text used to discover marketplace listings."""

    text: str

    def __post_init__(self) -> None:
        normalized = " ".join(_required_text(self.text, "text").split())
        object.__setattr__(self, "text", normalized)


@dataclass(frozen=True, slots=True)
class ListingKey:
    """Marketplace-independent natural identity for a listing."""

    source: MarketplaceSource
    external_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.source, MarketplaceSource):
            raise TypeError("source must be a MarketplaceSource")
        object.__setattr__(self, "external_id", _required_text(self.external_id, "external_id"))


@dataclass(frozen=True, slots=True, kw_only=True)
class Listing:
    """A normalized listing observed during one marketplace search."""

    source: MarketplaceSource
    external_id: str
    title: str
    price: Decimal
    currency: str
    url: str
    query: SearchQuery
    collected_at: datetime
    seller_name: str | None = None
    location: str | None = None
    product_condition: str | None = None
    formatted_amount: str | None = None
    usd_amount: Decimal | None = None
    usd_normalization_status: str | None = None
    usd_evidence: tuple[str, ...] = ()
    usd_exchange_rate: Decimal | None = None
    usd_exchange_rate_source: str | None = None
    usd_exchange_rate_at: datetime | None = None
    price_min: Decimal | None = None
    price_max: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, MarketplaceSource):
            raise TypeError("source must be a MarketplaceSource")
        if not isinstance(self.query, SearchQuery):
            raise TypeError("query must be a SearchQuery")

        object.__setattr__(self, "external_id", _required_text(self.external_id, "external_id"))
        object.__setattr__(self, "title", _required_text(self.title, "title"))
        object.__setattr__(self, "price", _price(self.price))
        object.__setattr__(self, "currency", _currency(self.currency))
        object.__setattr__(self, "url", _url(self.url))
        object.__setattr__(self, "collected_at", _collected_at(self.collected_at))
        object.__setattr__(self, "seller_name", _optional_text(self.seller_name, "seller_name"))
        object.__setattr__(self, "location", _optional_text(self.location, "location"))
        object.__setattr__(
            self,
            "product_condition",
            _optional_text(self.product_condition, "product_condition"),
        )
        object.__setattr__(
            self,
            "formatted_amount",
            _optional_text(self.formatted_amount, "formatted_amount"),
        )
        usd_amount = self.usd_amount
        if usd_amount is not None:
            usd_amount = _price(usd_amount)
        object.__setattr__(self, "usd_amount", usd_amount)
        object.__setattr__(
            self,
            "usd_normalization_status",
            _optional_text(self.usd_normalization_status, "usd_normalization_status"),
        )
        object.__setattr__(self, "usd_evidence", tuple(self.usd_evidence))
        usd_rate = self.usd_exchange_rate
        if usd_rate is not None:
            usd_rate = _finite_decimal(usd_rate, "usd_exchange_rate")
        object.__setattr__(self, "usd_exchange_rate", usd_rate)
        object.__setattr__(
            self,
            "usd_exchange_rate_source",
            _optional_text(self.usd_exchange_rate_source, "usd_exchange_rate_source"),
        )
        rate_at = self.usd_exchange_rate_at
        if rate_at is not None:
            rate_at = _collected_at(rate_at)
        object.__setattr__(self, "usd_exchange_rate_at", rate_at)
        price_min = self.price_min
        if price_min is not None:
            price_min = _price(price_min)
        price_max = self.price_max
        if price_max is not None:
            price_max = _price(price_max)
        if price_min is not None and price_max is None:
            price_max = price_min
        if price_min is not None and price_max is not None and price_min > price_max:
            raise ValueError("price_min must not exceed price_max")
        object.__setattr__(self, "price_min", price_min)
        object.__setattr__(self, "price_max", price_max)

    @property
    def key(self) -> ListingKey:
        """Return the stable marketplace identity for this listing."""

        return ListingKey(source=self.source, external_id=self.external_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class CollectionBatch:
    """One marketplace search observation persisted as an atomic unit.

    Listing identities are unique inside the batch. If an input contains duplicates,
    the last observation for each ``ListingKey`` wins deterministically.
    """

    source: MarketplaceSource
    query: SearchQuery
    collected_at: datetime
    listings: tuple[Listing, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.source, MarketplaceSource):
            raise TypeError("source must be a MarketplaceSource")
        if not isinstance(self.query, SearchQuery):
            raise TypeError("query must be a SearchQuery")

        collected_at = _collected_at(self.collected_at)
        observations: dict[ListingKey, Listing] = {}
        for listing in self.listings:
            if not isinstance(listing, Listing):
                raise TypeError("listings must contain only Listing instances")
            if listing.source is not self.source:
                raise ValueError("listing source must match collection source")
            if listing.query != self.query:
                raise ValueError("listing query must match collection query")
            if listing.collected_at != collected_at:
                raise ValueError("listing timestamp must match collection timestamp")
            observations[listing.key] = listing

        object.__setattr__(self, "collected_at", collected_at)
        object.__setattr__(self, "listings", tuple(observations.values()))

    @classmethod
    def from_listings(
        cls,
        *,
        source: MarketplaceSource,
        query: SearchQuery,
        collected_at: datetime,
        listings: Iterable[Listing],
    ) -> CollectionBatch:
        """Build a batch from any finite listing iterable."""

        return cls(
            source=source,
            query=query,
            collected_at=collected_at,
            listings=tuple(listings),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class PriceSnapshot:
    """A compact monetary observation linked to a listing."""

    listing_key: ListingKey
    price: Decimal
    currency: str
    collected_at: datetime
    usd_amount: Decimal | None = None
    usd_exchange_rate: Decimal | None = None
    usd_exchange_rate_source: str | None = None
    usd_exchange_rate_at: datetime | None = None
    price_min: Decimal | None = None
    price_max: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.listing_key, ListingKey):
            raise TypeError("listing_key must be a ListingKey")
        object.__setattr__(self, "price", _price(self.price))
        object.__setattr__(self, "currency", _currency(self.currency))
        object.__setattr__(self, "collected_at", _collected_at(self.collected_at))
        usd_amount = self.usd_amount
        if usd_amount is not None:
            usd_amount = _price(usd_amount)
        object.__setattr__(self, "usd_amount", usd_amount)
        usd_rate = self.usd_exchange_rate
        if usd_rate is not None:
            usd_rate = _finite_decimal(usd_rate, "usd_exchange_rate")
        object.__setattr__(self, "usd_exchange_rate", usd_rate)
        object.__setattr__(
            self,
            "usd_exchange_rate_source",
            _optional_text(self.usd_exchange_rate_source, "usd_exchange_rate_source"),
        )
        rate_at = self.usd_exchange_rate_at
        if rate_at is not None:
            rate_at = _collected_at(rate_at)
        object.__setattr__(self, "usd_exchange_rate_at", rate_at)
        price_min = self.price_min
        if price_min is not None:
            price_min = _price(price_min)
        price_max = self.price_max
        if price_max is not None:
            price_max = _price(price_max)
        if price_min is not None and price_max is None:
            price_max = price_min
        if price_min is not None and price_max is not None and price_min > price_max:
            raise ValueError("price_min must not exceed price_max")
        object.__setattr__(self, "price_min", price_min)
        object.__setattr__(self, "price_max", price_max)

    @classmethod
    def from_listing(cls, listing: Listing) -> PriceSnapshot:
        """Build a price observation without copying mutable listing metadata."""

        if not isinstance(listing, Listing):
            raise TypeError("listing must be a Listing")
        return cls(
            listing_key=listing.key,
            price=listing.price,
            currency=listing.currency,
            collected_at=listing.collected_at,
            usd_amount=listing.usd_amount,
            usd_exchange_rate=listing.usd_exchange_rate,
            usd_exchange_rate_source=listing.usd_exchange_rate_source,
            usd_exchange_rate_at=listing.usd_exchange_rate_at,
            price_min=listing.price_min,
            price_max=listing.price_max,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ObservedListing:
    """One listing and its exact price observation from a collection run.

    Listing metadata is current metadata; price and currency belong to the
    inspected historical collection run.
    """

    key: ListingKey
    title: str
    url: str
    price: Decimal
    currency: str
    seller_name: str | None = None
    location: str | None = None
    product_condition: str | None = None
    usd_amount: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.key, ListingKey):
            raise TypeError("key must be a ListingKey")

        object.__setattr__(self, "title", _required_text(self.title, "title"))
        object.__setattr__(self, "url", _url(self.url))
        object.__setattr__(self, "price", _price(self.price))
        object.__setattr__(self, "currency", _currency(self.currency))
        usd_amount = self.usd_amount
        if usd_amount is not None:
            usd_amount = _price(usd_amount)
        object.__setattr__(self, "usd_amount", usd_amount)
        object.__setattr__(self, "seller_name", _optional_text(self.seller_name, "seller_name"))
        object.__setattr__(self, "location", _optional_text(self.location, "location"))
        object.__setattr__(
            self,
            "product_condition",
            _optional_text(self.product_condition, "product_condition"),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CollectionRunInspection:
    """Read model for a limited view of one persisted collection run."""

    source: MarketplaceSource
    query: SearchQuery
    collected_at: datetime
    total_listings: int
    observations: tuple[ObservedListing, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.source, MarketplaceSource):
            raise TypeError("source must be a MarketplaceSource")
        if not isinstance(self.query, SearchQuery):
            raise TypeError("query must be a SearchQuery")
        if not isinstance(self.total_listings, int) or isinstance(self.total_listings, bool):
            raise TypeError("total_listings must be an integer")
        if self.total_listings < 0:
            raise ValueError("total_listings must not be negative")

        observations = tuple(self.observations)
        for observation in observations:
            if not isinstance(observation, ObservedListing):
                raise TypeError("observations must contain only ObservedListing instances")
            if observation.key.source is not self.source:
                raise ValueError("observation source must match collection source")
        if self.total_listings < len(observations):
            raise ValueError("total_listings must not be less than shown observations")

        object.__setattr__(self, "collected_at", _collected_at(self.collected_at))
        object.__setattr__(self, "observations", observations)


@dataclass(frozen=True, slots=True, kw_only=True)
class PriceObservation:
    """One persisted price observation enriched with its discovery query."""

    price: Decimal
    currency: str
    collected_at: datetime
    query: SearchQuery
    usd_amount: Decimal | None = None
    price_min: Decimal | None = None
    price_max: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.query, SearchQuery):
            raise TypeError("query must be a SearchQuery")
        object.__setattr__(self, "price", _price(self.price))
        object.__setattr__(self, "currency", _currency(self.currency))
        object.__setattr__(self, "collected_at", _collected_at(self.collected_at))
        usd_amount = self.usd_amount
        if usd_amount is not None:
            usd_amount = _price(usd_amount)
        object.__setattr__(self, "usd_amount", usd_amount)
        price_min = self.price_min
        if price_min is not None:
            price_min = _price(price_min)
        price_max = self.price_max
        if price_max is not None:
            price_max = _price(price_max)
        if price_min is not None and price_max is None:
            price_max = price_min
        if price_min is not None and price_max is not None and price_min > price_max:
            raise ValueError("price_min must not exceed price_max")
        object.__setattr__(self, "price_min", price_min)
        object.__setattr__(self, "price_max", price_max)


@dataclass(frozen=True, slots=True, kw_only=True)
class ListingHistory:
    """Current listing metadata and its ordered persisted price observations."""

    key: ListingKey
    title: str
    url: str
    first_seen_at: datetime
    last_seen_at: datetime
    observations: tuple[PriceObservation, ...]
    seller_name: str | None = None
    location: str | None = None
    product_condition: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.key, ListingKey):
            raise TypeError("key must be a ListingKey")
        first_seen_at = _collected_at(self.first_seen_at)
        last_seen_at = _collected_at(self.last_seen_at)
        if first_seen_at > last_seen_at:
            raise ValueError("first_seen_at must not be after last_seen_at")
        for observation in self.observations:
            if not isinstance(observation, PriceObservation):
                raise TypeError("observations must contain only PriceObservation instances")

        object.__setattr__(self, "title", _required_text(self.title, "title"))
        object.__setattr__(self, "url", _url(self.url))
        object.__setattr__(self, "seller_name", _optional_text(self.seller_name, "seller_name"))
        object.__setattr__(self, "location", _optional_text(self.location, "location"))
        object.__setattr__(
            self,
            "product_condition",
            _optional_text(self.product_condition, "product_condition"),
        )
        object.__setattr__(self, "first_seen_at", first_seen_at)
        object.__setattr__(self, "last_seen_at", last_seen_at)


@dataclass(frozen=True, slots=True, kw_only=True)
class ListingStatistics:
    """Derived statistics for one listing's persisted price observations."""

    key: ListingKey
    title: str
    current_price: Decimal
    previous_price: Decimal | None
    currency: str
    observation_count: int
    minimum_price: Decimal
    maximum_price: Decimal
    average_price: Decimal
    median_price: Decimal
    absolute_change: Decimal | None
    percentage_change: Decimal | None
    first_observed_at: datetime
    last_observed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.key, ListingKey):
            raise TypeError("key must be a ListingKey")
        if not isinstance(self.observation_count, int) or isinstance(self.observation_count, bool):
            raise TypeError("observation_count must be an integer")
        if self.observation_count <= 0:
            raise ValueError("observation_count must be greater than zero")

        previous_price = self.previous_price
        if previous_price is not None:
            previous_price = _price(previous_price)
        absolute_change = self.absolute_change
        if absolute_change is not None:
            absolute_change = _finite_decimal(absolute_change, "absolute_change")
        percentage_change = self.percentage_change
        if percentage_change is not None:
            percentage_change = _finite_decimal(percentage_change, "percentage_change")

        if self.observation_count == 1:
            if any(
                value is not None for value in (previous_price, absolute_change, percentage_change)
            ):
                raise ValueError("single-observation statistics cannot contain change values")
        elif previous_price is None or absolute_change is None:
            raise ValueError(
                "multi-observation statistics require previous_price and absolute_change"
            )

        minimum_price = _price(self.minimum_price)
        maximum_price = _price(self.maximum_price)
        if minimum_price > maximum_price:
            raise ValueError("minimum_price must not exceed maximum_price")

        first_observed_at = _collected_at(self.first_observed_at)
        last_observed_at = _collected_at(self.last_observed_at)
        if first_observed_at > last_observed_at:
            raise ValueError("first_observed_at must not be after last_observed_at")

        object.__setattr__(self, "title", _required_text(self.title, "title"))
        object.__setattr__(self, "current_price", _price(self.current_price))
        object.__setattr__(self, "previous_price", previous_price)
        object.__setattr__(self, "currency", _currency(self.currency))
        object.__setattr__(self, "minimum_price", minimum_price)
        object.__setattr__(self, "maximum_price", maximum_price)
        object.__setattr__(self, "average_price", _price(self.average_price))
        object.__setattr__(self, "median_price", _price(self.median_price))
        object.__setattr__(self, "absolute_change", absolute_change)
        object.__setattr__(self, "percentage_change", percentage_change)
        object.__setattr__(self, "first_observed_at", first_observed_at)
        object.__setattr__(self, "last_observed_at", last_observed_at)
