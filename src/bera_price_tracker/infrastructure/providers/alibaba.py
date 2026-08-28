"""Apify Alibaba acquisition client. Isolated from Facebook Marketplace."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Protocol, cast

from bera_price_tracker.application import MarketplaceSourceUnavailable
from bera_price_tracker.application.alibaba_statistics import explicit_alibaba_currency
from bera_price_tracker.application.provider_acquisition import ProviderAcquisitionMetrics
from bera_price_tracker.application.services import validate_alibaba_search
from bera_price_tracker.config import DEFAULT_APIFY_ALIBABA_ACTOR, normalize_alibaba_search_actor
from bera_price_tracker.domain.alibaba import AlibabaProduct
from bera_price_tracker.infrastructure.providers.apify import (
    ApifyClientConfiguration,
    ApifyConfigurationError,
)

DEFAULT_ALIBABA_ACTOR = DEFAULT_APIFY_ALIBABA_ACTOR
_UNSIGNED_PRICE = re.compile(r"\d+(?:\.\d+)?")
_SCI_TOKEN = re.compile(r"(?<![A-Za-z])[+-]?\d+(?:\.\d+)?[eE][+-]?\d+")
_PLAIN_OR_SCI_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_CURRENCY_NOISE = re.compile(r"(?i)\$|\bUS\b|\b[A-Z]{3}\b")
_ISO_CURRENCY = re.compile(r"\b([A-Z]{3})\b")
MEMO23_ALIBABA_MIN_PRODUCTS_PER_PAGE = 20


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


def alibaba_actor_max_pages(limit: int) -> int:
    """Conservative Actor-internal page budget for one search run.

    memo23/alibaba-scraper documents about 20–48 products per page and defaults
    ``maxPages`` to 1. Using the lower approximate page size lets one Actor run
    paginate far enough to satisfy ``maxItems`` without a second BERA call.
    """

    return max(1, math.ceil(limit / MEMO23_ALIBABA_MIN_PRODUCTS_PER_PAGE))


def build_alibaba_run_input(*, query: str, limit: int) -> dict[str, object]:
    """Actor input using only documented fields: searchTerms, maxPages, maxItems."""

    return {
        "searchTerms": [query],
        "maxPages": alibaba_actor_max_pages(limit),
        "maxItems": limit,
    }


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    return None


def _scalar_text(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return str(value)
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None


def _first_scalar(record: Mapping[str, object], *keys: str) -> str | None:
    for key in keys:
        text = _scalar_text(record.get(key))
        if text is not None:
            return text
    return None


def _decimal_from_text(value: str) -> Decimal | None:
    try:
        price = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    if not price.is_finite() or price <= Decimal("0"):
        return None
    return price


def _positive_decimal(value: Decimal) -> Decimal | None:
    if not value.is_finite() or value <= Decimal("0"):
        return None
    return value


def _decimal_from_numeric_scalar(raw: int | float) -> Decimal | None:
    if isinstance(raw, float) and not math.isfinite(raw):
        return None
    try:
        parsed = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return _positive_decimal(parsed)


def _explicit_display_currency(display: str) -> str | None:
    currency_match = _ISO_CURRENCY.search(display)
    if currency_match is None:
        return None
    return explicit_alibaba_currency(currency_match.group(1))


def _strip_currency_noise(text: str) -> str:
    """Remove currency tokens and whitespace; keep digits, dots, and range hyphens."""

    return re.sub(r"\s+", "", _CURRENCY_NOISE.sub("", text))


def _parse_scientific_price_text(compact: str) -> Decimal | None:
    candidate = _strip_currency_noise(compact)
    if not _PLAIN_OR_SCI_NUMBER.fullmatch(candidate):
        return None
    try:
        parsed = Decimal(candidate)
    except (InvalidOperation, ValueError):
        return None
    return _positive_decimal(parsed)


def _is_negative_price_prefix(compact: str, start: int) -> bool:
    """True when '-' is a minus sign, not a range separator after another number."""

    if start < 1 or compact[start - 1] != "-":
        return False
    if start == 1:
        return True
    previous = compact[start - 2]
    return not (previous.isdigit() or previous == ".")


def parse_alibaba_price(
    raw: object,
) -> tuple[str | None, Decimal | None, Decimal | None, str | None]:
    if isinstance(raw, bool):
        return None, None, None, None
    if isinstance(raw, int) or isinstance(raw, float):
        display = _scalar_text(raw)
        amount = _decimal_from_numeric_scalar(raw)
        if amount is None:
            return display, None, None, None
        return display, amount, amount, None

    display = _scalar_text(raw)
    if display is None:
        return None, None, None, None
    compact = display.replace(",", "")
    currency = _explicit_display_currency(display)
    expression = _strip_currency_noise(compact)
    if _SCI_TOKEN.search(compact) is not None or _SCI_TOKEN.search(expression) is not None:
        amount = _parse_scientific_price_text(compact)
        if amount is None:
            return display, None, None, currency
        return display, amount, amount, currency

    matches = list(_UNSIGNED_PRICE.finditer(expression))
    numbers: list[Decimal] = []
    for match in matches:
        parsed = _decimal_from_text(match.group(0))
        if parsed is None or _is_negative_price_prefix(expression, match.start()):
            return display, None, None, currency
        numbers.append(parsed)
    if len(numbers) == 1:
        return display, numbers[0], numbers[0], currency
    if len(numbers) == 2:
        between = expression[matches[0].end() : matches[1].start()]
        if "-" in between:
            if numbers[0] > numbers[1]:
                return display, None, None, currency
            return display, numbers[0], numbers[1], currency
        return display, None, None, currency
    return display, None, None, currency


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
        moq=_first_scalar(record, "minOrder", "moq"),
        supplier_name=_first_scalar(record, "supplierName", "companyName"),
        supplier_country=_first_scalar(
            record, "supplierCountryCode", "supplierCountry", "countryCode"
        ),
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
    """Run memo23/alibaba-scraper once and map public product fields."""

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
        try:
            actor = normalize_alibaba_search_actor(actor)
        except ValueError as error:
            raise ApifyConfigurationError(str(error)) from error
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
    "map_alibaba_item",
    "parse_alibaba_price",
]
