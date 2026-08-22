"""Apify Facebook Marketplace acquisition client."""

from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Protocol, cast
from urllib.parse import quote

from bera_price_tracker.application import MarketplaceSourceUnavailable

_TOKEN_ENV = "BERA_TRACKER_APIFY_API_TOKEN"
ACTOR_ID = "apify/facebook-marketplace-scraper"
_MAX_LIMIT = 5
_UNAVAILABLE_STATUSES = frozenset({"FAILED", "ABORTED", "TIMED-OUT"})
_LEADING_CURRENCY = re.compile(r"^([A-Za-z]{3})(?=\d|\s|$)")


class ApifyConfigurationError(ValueError):
    """Raised when local Apify configuration or collect input is unusable."""


class _RunClient(Protocol):
    def get(self) -> dict[str, object] | None: ...


class _ActorClient(Protocol):
    def call(
        self, *, run_input: dict[str, object], max_items: int | None = None
    ) -> dict[str, object] | None: ...

    def last_run(self, *, status: str | None = None) -> _RunClient: ...


class _DatasetPage(Protocol):
    items: list[object]


class _DatasetClient(Protocol):
    def list_items(self, *, limit: int) -> _DatasetPage: ...


class _ApifyClientLike(Protocol):
    def actor(self, actor_id: str) -> _ActorClient: ...

    def dataset(self, dataset_id: str) -> _DatasetClient: ...

    def run(self, run_id: str) -> _RunClient: ...


ClientFactory = Callable[[str], _ApifyClientLike]


@dataclass(frozen=True, slots=True)
class ApifyFacebookListing:
    """Internal Facebook listing mapped from one Apify dataset item."""

    product_id: str | None
    title: str | None
    price: Decimal | None
    currency: str | None
    formatted_price: str | None
    location: str | None
    url: str | None
    description: str = ""


@dataclass(frozen=True, slots=True)
class ApifyFacebookResult:
    """Sanitized records from one successful Apify Actor run."""

    records: tuple[ApifyFacebookListing, ...]
    fetched: int
    source_errors: int = 0
    run_status: str = "SUCCEEDED"


@dataclass(frozen=True, slots=True)
class ApifyClientConfiguration:
    """Validated Apify token with a redacted representation."""

    _api_token: str | None = field(default=None, repr=False)

    @classmethod
    def from_value(cls, value: str | None) -> ApifyClientConfiguration:
        api_token = None if value is None else value.strip() or None
        return cls(_api_token=api_token)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> ApifyClientConfiguration:
        values = os.environ if environ is None else environ
        return cls.from_value(values.get(_TOKEN_ENV))

    @property
    def api_token_configured(self) -> bool:
        return self._api_token is not None

    def require_api_token(self) -> str:
        if self._api_token is None:
            raise ApifyConfigurationError(f"{_TOKEN_ENV} is required")
        return self._api_token


def build_start_url(city: str, query: str) -> str:
    """Build the single Marketplace search URL for one city slug and query."""

    slug = _required_city_slug(city)
    encoded_query = quote(query, safe="")
    return f"https://www.facebook.com/marketplace/{slug}/search/?query={encoded_query}"


def build_run_input(*, query: str, city: str, limit: int) -> dict[str, object]:
    """Return Actor input for one start URL and a bounded resultsLimit."""

    return {
        "startUrls": [{"url": build_start_url(city, query)}],
        "resultsLimit": limit,
        "includeListingDetails": False,
    }


def normalize_location_key(value: str) -> str:
    """Fold a location or city for exact, accent-insensitive comparison."""

    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(stripped.casefold().split())


def location_is_out_of_scope(location: str | None, city: str) -> bool:
    """Return True only when a normalizable location does not match ``city``."""

    if location is None:
        return False
    normalized_location = normalize_location_key(location)
    if not normalized_location:
        return False
    return normalized_location != normalize_location_key(city)


def _required_city_slug(city: str) -> str:
    if not isinstance(city, str):
        raise ApifyConfigurationError("city must be text")
    slug = city.strip().casefold()
    if not slug or any(character.isspace() for character in slug):
        raise ApifyConfigurationError("city must be a simple Marketplace slug")
    return slug


def _validate_limit(limit: object) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ApifyConfigurationError("limit must be an integer")
    if not 1 <= limit <= _MAX_LIMIT:
        raise ApifyConfigurationError(f"limit must be between 1 and {_MAX_LIMIT}")
    return limit


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    return None


def _scalar_text(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (str, int)):
        normalized = str(value).strip()
        if normalized:
            return normalized
    return None


def _nested_get(record: Mapping[str, object], *keys: str) -> object:
    current: object = record
    for key in keys:
        mapping = _as_mapping(current)
        if mapping is None:
            return None
        current = mapping.get(key)
    return current


def _price_object(record: Mapping[str, object]) -> Mapping[str, object] | None:
    listing_price = _as_mapping(record.get("listing_price"))
    if listing_price is not None:
        return listing_price
    return _as_mapping(record.get("listingPrice"))


def _price_amount_value(record: Mapping[str, object]) -> object:
    listing_price = _as_mapping(record.get("listing_price"))
    if listing_price is not None and "amount" in listing_price:
        return listing_price.get("amount")
    listing_price_legacy = _as_mapping(record.get("listingPrice"))
    if listing_price_legacy is not None:
        return listing_price_legacy.get("amount")
    return None


def _price_formatted(record: Mapping[str, object]) -> str | None:
    listing_price = _as_mapping(record.get("listing_price"))
    if listing_price is not None:
        formatted = _scalar_text(listing_price.get("formatted_amount"))
        if formatted is not None:
            return formatted
    listing_price_legacy = _as_mapping(record.get("listingPrice"))
    if listing_price_legacy is not None:
        formatted = _scalar_text(listing_price_legacy.get("formatted_amount"))
        if formatted is not None:
            return formatted
        return _scalar_text(listing_price_legacy.get("formatted_amount_zeros_stripped"))
    return None


def _decimal_price(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not price.is_finite() or price <= Decimal("0"):
        return None
    return price


def _currency_from_formatted(formatted: str | None) -> str | None:
    if formatted is None:
        return None
    match = _LEADING_CURRENCY.match(formatted.strip())
    if match is not None:
        return match.group(1).upper()
    return "UNKNOWN"


def _price_currency(price: Mapping[str, object] | None, formatted: str | None) -> str | None:
    if price is not None:
        explicit = _scalar_text(price.get("currency"))
        if explicit is not None:
            return explicit.upper() if explicit.isalpha() and len(explicit) == 3 else explicit
    return _currency_from_formatted(formatted)


def _location_text(record: Mapping[str, object]) -> str | None:
    display_name = _scalar_text(
        _nested_get(record, "location", "reverse_geocode", "city_page", "display_name")
    )
    if display_name is not None:
        return display_name
    city = _scalar_text(_nested_get(record, "location", "reverse_geocode", "city"))
    if city is not None:
        return city
    location_text = record.get("locationText")
    mapped = _as_mapping(location_text)
    if mapped is not None:
        return _scalar_text(mapped.get("text"))
    return _scalar_text(location_text)


def map_apify_item(raw: object) -> ApifyFacebookListing | None:
    """Map one dataset item. Title-less records are skipped by the caller."""

    if not isinstance(raw, Mapping):
        return None
    record = cast(Mapping[str, object], raw)
    price_object = _price_object(record)
    formatted = _price_formatted(record)
    title = _scalar_text(record.get("marketplace_listing_title")) or _scalar_text(
        record.get("listingTitle")
    )
    return ApifyFacebookListing(
        product_id=_scalar_text(record.get("id")),
        title=title,
        price=_decimal_price(_price_amount_value(record)),
        currency=_price_currency(price_object, formatted),
        formatted_price=formatted,
        location=_location_text(record),
        url=_scalar_text(record.get("listingUrl")) or _scalar_text(record.get("itemUrl")),
        description="",
    )


def _run_status(run: Mapping[str, object]) -> str:
    status = run.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    return "UNKNOWN"


def _dataset_id(run: Mapping[str, object]) -> str | None:
    value = run.get("defaultDatasetId")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _default_client_factory(token: str) -> _ApifyClientLike:
    from apify_client import ApifyClient

    return cast(_ApifyClientLike, ApifyClient(token))


class ApifyFacebookMarketplaceClient:
    """Run the Facebook Marketplace Actor once and map allowlisted fields."""

    def __init__(
        self,
        *,
        api_token: str | None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._configuration = ApifyClientConfiguration.from_value(api_token)
        self._client_factory = client_factory or _default_client_factory

    def fetch(self, keyword: str, city: str, limit: int) -> ApifyFacebookResult:
        """Start at most one Actor run and return mapped listings."""

        if not isinstance(keyword, str) or not keyword.strip():
            raise ApifyConfigurationError("keyword must not be blank")
        normalized_limit = _validate_limit(limit)
        token = self._configuration.require_api_token()
        run_input = build_run_input(query=keyword.strip(), city=city, limit=normalized_limit)
        try:
            client = self._client_factory(token)
            run = client.actor(ACTOR_ID).call(run_input=run_input, max_items=normalized_limit)
        except ApifyConfigurationError:
            raise
        except MarketplaceSourceUnavailable:
            raise
        except Exception as error:
            raise MarketplaceSourceUnavailable(
                "Facebook Marketplace source is unavailable"
            ) from error

        if not isinstance(run, Mapping):
            raise MarketplaceSourceUnavailable("Facebook Marketplace source is unavailable")

        status = _run_status(run)
        if status != "SUCCEEDED":
            raise MarketplaceSourceUnavailable("Facebook Marketplace source is unavailable")

        dataset_id = _dataset_id(run)
        if dataset_id is None:
            raise MarketplaceSourceUnavailable("Facebook Marketplace source is unavailable")

        try:
            page = client.dataset(dataset_id).list_items(limit=normalized_limit)
            raw_items = list(page.items)[:normalized_limit]
        except Exception as error:
            raise MarketplaceSourceUnavailable(
                "Facebook Marketplace source is unavailable"
            ) from error

        records: list[ApifyFacebookListing] = []
        for raw_item in raw_items:
            mapped = map_apify_item(raw_item)
            if mapped is not None:
                records.append(mapped)

        return ApifyFacebookResult(
            records=tuple(records),
            fetched=len(raw_items),
            source_errors=0,
            run_status=status,
        )


__all__ = [
    "ACTOR_ID",
    "ApifyClientConfiguration",
    "ApifyConfigurationError",
    "ApifyFacebookListing",
    "ApifyFacebookMarketplaceClient",
    "ApifyFacebookResult",
    "build_run_input",
    "build_start_url",
    "location_is_out_of_scope",
    "map_apify_item",
    "normalize_location_key",
]
