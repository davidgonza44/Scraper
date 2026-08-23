"""Apify product-detail refresh client. Isolated from keyword search."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol, cast

from bera_price_tracker.application.alibaba_refresh import (
    LadderTier,
    ProductRefreshBatch,
    ProductRefreshRecord,
    TrackedAlibabaProduct,
    is_alibaba_product_detail_url,
)
from bera_price_tracker.application.ports import MarketplaceSourceUnavailable
from bera_price_tracker.config import (
    DEFAULT_APIFY_ALIBABA_REFRESH_ACTOR,
    DEFAULT_APIFY_ALIBABA_REFRESH_CONCURRENCY,
    DEFAULT_APIFY_ALIBABA_REFRESH_RETRIES,
)
from bera_price_tracker.infrastructure.providers.apify import (
    ApifyClientConfiguration,
    ApifyConfigurationError,
)


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


def build_alibaba_refresh_run_input(
    product_urls: Sequence[str],
    *,
    max_request_retries: int,
    max_concurrency: int,
) -> dict[str, object]:
    """Actor input using only audited fields: productUrls, retries, concurrency."""

    return {
        "productUrls": [{"url": url} for url in product_urls],
        "maxConcurrency": max_concurrency,
        "maxRequestRetries": max_request_retries,
    }


def _optional_text(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        text = str(value).strip()
        return text or None
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        return None
    return value


def _optional_decimal(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, int):
        parsed = Decimal(value)
    elif isinstance(value, float):
        parsed = Decimal(str(value))
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


def _parse_scraped_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _map_tier(raw: object) -> LadderTier | None:
    if not isinstance(raw, Mapping):
        return None
    record = cast(Mapping[str, object], raw)
    return LadderTier(
        min_quantity=_optional_int(record.get("minQuantity")),
        max_quantity=_optional_int(record.get("maxQuantity")),
        price=_optional_decimal(record.get("price")),
        price_formatted=_optional_text(record.get("priceFormatted")),
    )


def map_xtracto_item(raw: object) -> ProductRefreshRecord | None:
    """Map one public xtracto item. Secrets and raw payloads are dropped."""

    if not isinstance(raw, Mapping):
        return None
    record = cast(Mapping[str, object], raw)
    tiers_raw = record.get("ladderPrices")
    tiers: list[LadderTier] = []
    if isinstance(tiers_raw, Sequence) and not isinstance(tiers_raw, (str, bytes)):
        for item in tiers_raw:
            mapped = _map_tier(item)
            if mapped is not None:
                tiers.append(mapped)
    return ProductRefreshRecord(
        product_id=_optional_text(record.get("productId")),
        product_url=_optional_text(record.get("productUrl")),
        price_formatted=_optional_text(record.get("priceFormatted")),
        currency=_optional_text(record.get("currency")),
        ladder_prices=tuple(tiers),
        min_order_quantity=_optional_int(record.get("minOrderQuantity")),
        scraped_at=_parse_scraped_at(record.get("scrapedAt")),
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
class ApifyAlibabaProductRefreshClient:
    """Run xtracto/alibaba-product-scraper once for a batch of product URLs."""

    _api_token: str | None = field(default=None, repr=False)
    actor_id: str = DEFAULT_APIFY_ALIBABA_REFRESH_ACTOR
    max_request_retries: int = DEFAULT_APIFY_ALIBABA_REFRESH_RETRIES
    max_concurrency: int = DEFAULT_APIFY_ALIBABA_REFRESH_CONCURRENCY
    client_factory: ClientFactory | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        actor = self.actor_id.strip() if isinstance(self.actor_id, str) else ""
        if not actor:
            raise ApifyConfigurationError("alibaba refresh actor id must not be blank")
        object.__setattr__(self, "actor_id", actor)
        object.__setattr__(
            self, "_api_token", None if self._api_token is None else self._api_token.strip() or None
        )

    def refresh_products(self, products: Sequence[TrackedAlibabaProduct]) -> ProductRefreshBatch:
        if not isinstance(products, Sequence) or isinstance(products, (str, bytes)):
            raise TypeError("products must be a sequence of TrackedAlibabaProduct")
        urls: list[str] = []
        for product in products:
            if not isinstance(product, TrackedAlibabaProduct):
                raise TypeError("products must contain TrackedAlibabaProduct instances")
            if not is_alibaba_product_detail_url(product.product_url):
                raise ApifyConfigurationError("refresh URL must be an Alibaba product-detail page")
            urls.append(product.product_url)
        if not urls:
            return ProductRefreshBatch(records=())

        configuration = ApifyClientConfiguration.from_value(self._api_token)
        token = configuration.require_api_token()
        run_input = build_alibaba_refresh_run_input(
            urls,
            max_request_retries=self.max_request_retries,
            max_concurrency=self.max_concurrency,
        )
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
            page = client.dataset(dataset_id).list_items(limit=len(urls))
            raw_items = list(page.items)[: len(urls)]
        except Exception as error:
            raise MarketplaceSourceUnavailable("Alibaba source is unavailable") from error

        records: list[ProductRefreshRecord] = []
        for raw_item in raw_items:
            mapped = map_xtracto_item(raw_item)
            if mapped is not None:
                records.append(mapped)
        return ProductRefreshBatch(records=tuple(records))


__all__ = [
    "ApifyAlibabaProductRefreshClient",
    "build_alibaba_refresh_run_input",
    "map_xtracto_item",
]
