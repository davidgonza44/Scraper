"""Apify Alibaba acquisition client. Isolated from Facebook Marketplace."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Protocol, cast
from urllib.parse import quote_plus

from bera_price_tracker.application import MarketplaceSourceUnavailable
from bera_price_tracker.application.alibaba_statistics import explicit_alibaba_currency
from bera_price_tracker.application.provider_acquisition import ProviderAcquisitionMetrics
from bera_price_tracker.application.services import validate_alibaba_search
from bera_price_tracker.domain.alibaba import AlibabaProduct
from bera_price_tracker.infrastructure.providers.apify import (
    ApifyClientConfiguration,
    ApifyConfigurationError,
)

DEFAULT_ALIBABA_ACTOR = "scraper-engine/alibaba-scraper"
_TOKEN_ENV = "BERA_TRACKER_APIFY_API_TOKEN"
_NUMBER = re.compile(r"(\d+(?:\.\d+)?)")
_ISO_CURRENCY = re.compile(r"\b([A-Z]{3})\b")


class _ActorClient(Protocol):
    def call(self, *, run_input: dict[str, object]) -> dict[str, object] | None: ...


class _DatasetPage(Protocol):
    items: list[object]


class _DatasetClient(Protocol):
    def list_items(self, *, limit: int) -> _DatasetPage: ...


class _ApifyClientLike(Protocol):
    def actor(self, actor_id: str) -> _ActorClient: ...

    def dataset(self, dataset_id: str) -> _DatasetClient: ...


ClientFactory = Callable[[str], _ApifyClientLike]


def build_alibaba_search_url(query: str) -> str:
    """Build the single trade/search URL required by this Actor schema."""

    encoded = quote_plus(query)
    return (
        f"https://www.alibaba.com/trade/search?fsb=y&IndexArea=product_en&keywords={encoded}&page=1"
    )


def build_alibaba_run_input(*, query: str, limit: int) -> dict[str, object]:
    """Actor input using only documented fields: urls + maxItems."""

    return {
        "urls": [build_alibaba_search_url(query)],
        "maxItems": limit,
    }


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


def _decimal_from_text(value: str) -> Decimal | None:
    try:
        price = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    if not price.is_finite() or price <= Decimal("0"):
        return None
    return price


def parse_alibaba_price(
    raw: object,
) -> tuple[str | None, Decimal | None, Decimal | None, str | None]:
    display = _scalar_text(raw)
    if display is None:
        return None, None, None, None
    compact = display.replace(",", "")
    numbers: list[Decimal] = []
    for match in _NUMBER.finditer(compact):
        parsed = _decimal_from_text(match.group(1))
        if parsed is not None:
            numbers.append(parsed)
    min_price = numbers[0] if numbers else None
    max_price = numbers[1] if len(numbers) >= 2 else min_price
    currency = None
    currency_match = _ISO_CURRENCY.search(display)
    if currency_match is not None:
        currency = explicit_alibaba_currency(currency_match.group(1))
    return display, min_price, max_price, currency


def map_alibaba_item(raw: object) -> AlibabaProduct | None:
    """Map one Actor dataset item. Title-less rows are skipped."""

    if not isinstance(raw, Mapping):
        return None
    record = cast(Mapping[str, object], raw)
    title = _scalar_text(record.get("title"))
    if title is None:
        return None
    price_display, min_price, max_price, currency = parse_alibaba_price(record.get("price"))
    explicit = explicit_alibaba_currency(record.get("currency"))
    if explicit is not None:
        currency = explicit
    return AlibabaProduct(
        title=title,
        product_id=_scalar_text(record.get("productId")),
        product_url=_scalar_text(record.get("productUrl")),
        price_display=price_display,
        min_price=min_price,
        max_price=max_price,
        currency=currency,
        moq=_scalar_text(record.get("moq")),
        supplier_name=_scalar_text(record.get("companyName")),
        supplier_country=_scalar_text(record.get("countryCode")),
        image_url=_scalar_text(record.get("mainImage")),
        gold_supplier_years=_scalar_text(record.get("goldSupplierYears")),
        supplier_service_score=_scalar_text(record.get("supplierServiceScore")),
        review_count=_scalar_text(record.get("reviewCount")),
        review_score=_scalar_text(record.get("reviewScore")),
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


@dataclass(frozen=True, slots=True)
class ApifyAlibabaClient:
    """Run scraper-engine/alibaba-scraper once and map public product fields."""

    _api_token: str | None = field(default=None, repr=False)
    actor_id: str = DEFAULT_ALIBABA_ACTOR
    client_factory: ClientFactory | None = field(default=None, repr=False)
    last_metrics: ProviderAcquisitionMetrics | None = field(
        default=None, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        actor = self.actor_id.strip() if isinstance(self.actor_id, str) else ""
        if not actor:
            raise ApifyConfigurationError("alibaba actor id must not be blank")
        object.__setattr__(self, "actor_id", actor)
        object.__setattr__(
            self, "_api_token", None if self._api_token is None else self._api_token.strip() or None
        )

    def search(self, query: str, limit: int) -> list[AlibabaProduct]:
        normalized_query, normalized_limit = validate_alibaba_search(query, limit)
        configuration = ApifyClientConfiguration.from_value(self._api_token)
        token = configuration.require_api_token()
        run_input = build_alibaba_run_input(query=normalized_query, limit=normalized_limit)
        factory = self.client_factory or _default_client_factory
        try:
            client = factory(token)
            run = client.actor(self.actor_id).call(run_input=run_input)
        except ApifyConfigurationError:
            raise
        except MarketplaceSourceUnavailable:
            raise
        except Exception as error:
            raise MarketplaceSourceUnavailable("Alibaba source is unavailable") from error

        if not isinstance(run, Mapping):
            raise MarketplaceSourceUnavailable("Alibaba source is unavailable")
        if _run_status(run) != "SUCCEEDED":
            raise MarketplaceSourceUnavailable("Alibaba source is unavailable")
        dataset_id = _dataset_id(run)
        if dataset_id is None:
            raise MarketplaceSourceUnavailable("Alibaba source is unavailable")

        try:
            page = client.dataset(dataset_id).list_items(limit=normalized_limit)
            raw_items = list(page.items)[:normalized_limit]
        except Exception as error:
            raise MarketplaceSourceUnavailable("Alibaba source is unavailable") from error

        products: list[AlibabaProduct] = []
        for raw_item in raw_items:
            mapped = map_alibaba_item(raw_item)
            if mapped is not None:
                products.append(mapped)
        object.__setattr__(
            self,
            "last_metrics",
            ProviderAcquisitionMetrics(
                requested=normalized_limit,
                fetched=len(raw_items),
                usable=len(products),
            ),
        )
        return products


__all__ = [
    "DEFAULT_ALIBABA_ACTOR",
    "ApifyAlibabaClient",
    "build_alibaba_run_input",
    "build_alibaba_search_url",
    "map_alibaba_item",
    "parse_alibaba_price",
]
