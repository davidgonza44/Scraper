"""Manual Alibaba product-detail refresh. Separate from keyword search.

Currency:
    A) explicit ISO-4217 (three ASCII letters) from ``currency``.
    B) else valid ``pricePerUnitUSD`` values → USD, evidence
       ``xtracto_pricePerUnitUSD``.
    C) otherwise unavailable → INVALID_PRICE.

    Never infer USD from ``$``, ``priceFormatted``, or ``${0}``. No FX.

Tracking price (history snapshot amount):
    The published price of the ladder tier that covers ``minOrderQuantity``.
    Not the midpoint of all tiers. That midpoint remains discovery-only
    (``alibaba_representative_price``) and is not persisted here.

Range:
    ``price_min`` / ``price_max`` stay the min/max of valid tier amounts
    in the chosen currency evidence. ``price_display`` stays as published.

Without ladder:
    One unambiguous Decimal plus explicit ISO currency. Otherwise INVALID_PRICE.

Identity:
    Persist a snapshot only when returned ``productId`` equals
    ``Listing.external_id``. No title or supplier matching.

Idempotency:
    The collection query is ``alibaba-refresh:{operation_id}``. A second
    execute with the same operation_id does not call the provider and does
    not insert snapshots. Later operations use a new id and may snapshot
    an unchanged price.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Protocol
from urllib.parse import urlsplit

from bera_price_tracker.application.alibaba_tracking import (
    FOLLOW_SOURCE,
    REFRESH_QUERY_PREFIX,
    AlibabaFollowError,
    AlibabaFollowObservation,
    AlibabaTrackedProduct,
    AlibabaTrackingRepository,
    alibaba_listing_key,
    history_from_repository,
    is_canonical_tracking_observation,
    listing_from_observation,
    tracked_product_from_repository,
)
from bera_price_tracker.application.ports import MarketplaceSourceUnavailable
from bera_price_tracker.domain import (
    CollectionBatch,
    Listing,
    ListingKey,
    PriceObservation,
    SearchQuery,
)

type CollectionClock = Callable[[], datetime]

MAX_ALIBABA_REFRESH_BATCH = 50
ALLOWED_PRODUCT_HOSTS = frozenset({"alibaba.com", "www.alibaba.com"})
_NUMBER = r"(\d+(?:\.\d+)?)"

BATCH_TOO_LARGE = "No se pueden actualizar más de 50 productos en una sola operación."
EMPTY_SELECTION = "Selecciona al menos un producto para actualizar."
MISSING_OPERATION = "Falta el identificador de la operación."
ISO_CURRENCY_REQUIRED = "La moneda debe ser un código ISO de tres letras."
CURRENCY_EVIDENCE_ISO = "iso"
CURRENCY_EVIDENCE_XTRACTO_USD = "xtracto_pricePerUnitUSD"
_UNBOUNDED_MAX = 10**12


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AlibabaRefreshError(ValueError):
    """Local validation failure before a refresh batch is sent."""


class ProductRefreshStatus(StrEnum):
    """Per-product outcome of one manual refresh operation."""

    UPDATED = "UPDATED"
    UNCHANGED = "UNCHANGED"
    NOT_FOUND = "NOT_FOUND"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    INVALID_PRICE = "INVALID_PRICE"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True, kw_only=True)
class TrackedAlibabaProduct:
    """Public identity sent to the product-detail provider."""

    product_id: str
    product_url: str


@dataclass(frozen=True, slots=True, kw_only=True)
class LadderTier:
    """One documented xtracto quantity-price tier."""

    min_quantity: int | None
    max_quantity: int | None
    price: Decimal | None
    price_formatted: str | None
    price_usd: Decimal | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ProductRefreshRecord:
    """Tolerant public xtracto fields. Never includes raw Actor items."""

    product_id: str | None
    product_url: str | None
    price_formatted: str | None
    currency: str | None
    ladder_prices: tuple[LadderTier, ...]
    min_order_quantity: int | None
    scraped_at: datetime | None


@dataclass(frozen=True, slots=True)
class ProductRefreshBatch:
    """One provider response for one Actor run."""

    records: tuple[ProductRefreshRecord, ...]


@dataclass(frozen=True, slots=True)
class NormalizedRefreshPrice:
    """Tracking price plus published range. Midpoint is not the snapshot amount."""

    tracking_price: Decimal
    price_min: Decimal
    price_max: Decimal
    currency: str
    price_display: str | None
    currency_evidence: str
    selected_min_quantity: int | None = None
    selected_max_quantity: int | None = None
    representative: Decimal | None = None


@dataclass(frozen=True, slots=True)
class AlibabaRefreshItemResult:
    """Outcome for one requested tracked product."""

    product_id: str
    status: ProductRefreshStatus
    message: str = ""


@dataclass(frozen=True, slots=True)
class AlibabaRefreshSummary:
    """Counts shown after a manual refresh."""

    requested: int
    updated: int
    unchanged: int
    not_found: int
    identity_mismatch: int
    invalid_price: int
    failed: int
    predicted_runs: int
    items: tuple[AlibabaRefreshItemResult, ...]
    tracked: tuple[AlibabaTrackedProduct, ...]


class AlibabaProductRefreshProvider(Protocol):
    """Product-detail refresh. Must not reuse keyword search."""

    def refresh_products(
        self,
        products: Sequence[TrackedAlibabaProduct],
    ) -> ProductRefreshBatch:
        """Refresh the given product URLs in one batch."""

        ...


def refresh_operation_query(operation_id: str) -> SearchQuery:
    normalized = operation_id.strip() if isinstance(operation_id, str) else ""
    if not normalized:
        raise AlibabaRefreshError(MISSING_OPERATION)
    return SearchQuery(f"{REFRESH_QUERY_PREFIX}{normalized}")


def is_alibaba_product_detail_url(value: object) -> bool:
    """Return whether value is an https Alibaba product-detail URL."""

    if not isinstance(value, str):
        return False
    normalized = value.strip()
    if not normalized:
        return False
    parsed = urlsplit(normalized)
    if parsed.scheme.lower() not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").casefold()
    if host not in ALLOWED_PRODUCT_HOSTS:
        return False
    return "/product-detail/" in parsed.path


def _optional_text(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        text = str(value).strip()
        return text or None
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _parse_decimal(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, int):
        parsed = Decimal(value)
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


def _explicit_iso_currency(value: object) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    currency = text.upper()
    if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
        return None
    return currency


def _decimals_from_display(display: str) -> list[Decimal]:
    import re

    compact = display.replace(",", "")
    values: list[Decimal] = []
    for match in re.finditer(_NUMBER, compact):
        parsed = _parse_decimal(match.group(1))
        if parsed is not None:
            values.append(parsed)
    return values


def _tier_amount(tier: LadderTier, *, use_usd: bool) -> Decimal | None:
    return _parse_decimal(tier.price_usd if use_usd else tier.price)


def _tier_covers(tier: LadderTier, quantity: int) -> bool:
    if tier.min_quantity is None and tier.max_quantity is None:
        return False
    if tier.min_quantity is not None and quantity < tier.min_quantity:
        return False
    return not (tier.max_quantity is not None and quantity > tier.max_quantity)


def select_moq_tier(
    tiers: Sequence[LadderTier],
    min_order_quantity: int | None,
    *,
    use_usd: bool,
) -> LadderTier | None:
    """Return the tier that covers the published MOQ. Not the first array item."""

    priced = [tier for tier in tiers if _tier_amount(tier, use_usd=use_usd) is not None]
    if not priced:
        return None
    if min_order_quantity is not None and min_order_quantity > 0:
        moq = min_order_quantity
    else:
        mins = [tier.min_quantity for tier in priced if tier.min_quantity is not None]
        if not mins:
            return None
        moq = min(mins)
    covering = [tier for tier in priced if _tier_covers(tier, moq)]
    if not covering:
        return None
    covering.sort(
        key=lambda tier: (
            -(tier.min_quantity if tier.min_quantity is not None else 0),
            tier.max_quantity if tier.max_quantity is not None else _UNBOUNDED_MAX,
        )
    )
    return covering[0]


def _resolve_refresh_currency(
    record: ProductRefreshRecord,
) -> tuple[str, str, bool] | None:
    iso = _explicit_iso_currency(record.currency)
    if iso is not None:
        return iso, CURRENCY_EVIDENCE_ISO, False
    if any(_tier_amount(tier, use_usd=True) is not None for tier in record.ladder_prices):
        return "USD", CURRENCY_EVIDENCE_XTRACTO_USD, True
    return None


def normalize_refresh_price(record: ProductRefreshRecord) -> NormalizedRefreshPrice | None:
    """Derive tracking price and published range. Returns None when unusable."""

    resolved = _resolve_refresh_currency(record)
    if resolved is None:
        return None
    currency, evidence, use_usd = resolved
    ladder_values = [
        amount
        for tier in record.ladder_prices
        if (amount := _tier_amount(tier, use_usd=use_usd)) is not None
    ]
    selected: LadderTier | None = None
    tracking: Decimal | None = None
    if ladder_values:
        selected = select_moq_tier(record.ladder_prices, record.min_order_quantity, use_usd=use_usd)
        if selected is None:
            return None
        tracking = _tier_amount(selected, use_usd=use_usd)
        if tracking is None:
            return None
        price_min = min(ladder_values)
        price_max = max(ladder_values)
    else:
        if evidence != CURRENCY_EVIDENCE_ISO:
            return None
        display = record.price_formatted or ""
        numbers = _decimals_from_display(display)
        if len(numbers) != 1:
            return None
        tracking = numbers[0]
        price_min = tracking
        price_max = tracking
    midpoint = (price_min + price_max) / Decimal("2")
    return NormalizedRefreshPrice(
        tracking_price=tracking,
        price_min=price_min,
        price_max=price_max,
        currency=currency,
        price_display=_optional_text(record.price_formatted),
        currency_evidence=evidence,
        selected_min_quantity=None if selected is None else selected.min_quantity,
        selected_max_quantity=None if selected is None else selected.max_quantity,
        representative=midpoint,
    )


def _count(items: Sequence[AlibabaRefreshItemResult], status: ProductRefreshStatus) -> int:
    return sum(1 for item in items if item.status is status)


def summary_from_items(
    items: Sequence[AlibabaRefreshItemResult],
    tracked: Sequence[AlibabaTrackedProduct] = (),
) -> AlibabaRefreshSummary:
    return AlibabaRefreshSummary(
        requested=len(items),
        updated=_count(items, ProductRefreshStatus.UPDATED),
        unchanged=_count(items, ProductRefreshStatus.UNCHANGED),
        not_found=_count(items, ProductRefreshStatus.NOT_FOUND),
        identity_mismatch=_count(items, ProductRefreshStatus.IDENTITY_MISMATCH),
        invalid_price=_count(items, ProductRefreshStatus.INVALID_PRICE),
        failed=_count(items, ProductRefreshStatus.FAILED),
        predicted_runs=1 if items else 0,
        items=tuple(items),
        tracked=tuple(tracked),
    )


def _last_canonical_observation(tracked: AlibabaTrackedProduct) -> PriceObservation | None:
    """Latest canonical tracking observation, or None when only provisional
    discovery observations exist (the incoming refresh establishes the baseline)."""

    for observation in reversed(tracked.history):
        if is_canonical_tracking_observation(observation):
            return observation
    return None


def _last_representative(tracked: AlibabaTrackedProduct) -> Decimal | None:
    observation = _last_canonical_observation(tracked)
    return None if observation is None else observation.price


def _last_currency(tracked: AlibabaTrackedProduct) -> str | None:
    observation = _last_canonical_observation(tracked)
    return None if observation is None else observation.currency


def _operation_already_recorded(
    repository: AlibabaTrackingRepository,
    keys: Sequence[ListingKey],
    operation_query: SearchQuery,
) -> bool:
    for key in keys:
        history = history_from_repository(repository, key)
        if history is None:
            continue
        if any(item.query == operation_query for item in history.observations):
            return True
    return False


def _replay_item(
    repository: AlibabaTrackingRepository,
    product_id: str,
    operation_query: SearchQuery,
) -> AlibabaRefreshItemResult:
    try:
        key = alibaba_listing_key(product_id)
    except AlibabaFollowError as error:
        return AlibabaRefreshItemResult(
            product_id=product_id,
            status=ProductRefreshStatus.FAILED,
            message=str(error),
        )
    history = history_from_repository(repository, key)
    if history is None:
        return AlibabaRefreshItemResult(
            product_id=product_id, status=ProductRefreshStatus.NOT_FOUND
        )
    matches = [
        index for index, item in enumerate(history.observations) if item.query == operation_query
    ]
    if not matches:
        return AlibabaRefreshItemResult(
            product_id=product_id, status=ProductRefreshStatus.NOT_FOUND
        )
    index = matches[-1]
    current = history.observations[index].price
    previous_canonical = [
        observation.price
        for observation in history.observations[:index]
        if is_canonical_tracking_observation(observation)
    ]
    if not previous_canonical or current != previous_canonical[-1]:
        status = ProductRefreshStatus.UPDATED
    else:
        status = ProductRefreshStatus.UNCHANGED
    return AlibabaRefreshItemResult(product_id=product_id, status=status)


def _associate_record(
    requested: TrackedAlibabaProduct,
    remaining: list[ProductRefreshRecord],
    *,
    singleton_fallback: bool,
) -> ProductRefreshRecord | None:
    for index, record in enumerate(remaining):
        if record.product_id == requested.product_id:
            return remaining.pop(index)
    for index, record in enumerate(remaining):
        if record.product_url and record.product_url == requested.product_url:
            return remaining.pop(index)
    if singleton_fallback and len(remaining) == 1:
        return remaining.pop(0)
    return None


def _item_status_for_record(
    requested: TrackedAlibabaProduct,
    tracked: AlibabaTrackedProduct,
    record: ProductRefreshRecord,
) -> tuple[ProductRefreshStatus, NormalizedRefreshPrice | None, str]:
    if record.product_id != requested.product_id:
        return ProductRefreshStatus.IDENTITY_MISMATCH, None, ""
    normalized = normalize_refresh_price(record)
    if normalized is None:
        return ProductRefreshStatus.INVALID_PRICE, None, ISO_CURRENCY_REQUIRED
    last_currency = _last_currency(tracked)
    if last_currency is not None and last_currency != normalized.currency:
        return ProductRefreshStatus.INVALID_PRICE, None, "currency mismatch"
    last_price = _last_representative(tracked)
    if last_price is not None and last_price == normalized.tracking_price:
        return ProductRefreshStatus.UNCHANGED, normalized, normalized.currency_evidence
    return ProductRefreshStatus.UPDATED, normalized, normalized.currency_evidence


@dataclass(frozen=True, slots=True)
class RefreshTrackedAlibabaProducts:
    """Refresh selected active Alibaba listings via product-detail URLs."""

    repository: AlibabaTrackingRepository
    provider: AlibabaProductRefreshProvider
    clock: CollectionClock = _utc_now

    def execute(
        self,
        product_ids: Sequence[str],
        *,
        operation_id: str,
    ) -> AlibabaRefreshSummary:
        if not isinstance(product_ids, Sequence) or isinstance(product_ids, (str, bytes)):
            raise TypeError("product_ids must be a sequence of text identifiers")
        requested_ids = [
            item.strip() for item in product_ids if isinstance(item, str) and item.strip()
        ]
        if not requested_ids:
            raise AlibabaRefreshError(EMPTY_SELECTION)
        if len(requested_ids) > MAX_ALIBABA_REFRESH_BATCH:
            raise AlibabaRefreshError(BATCH_TOO_LARGE)
        operation_query = refresh_operation_query(operation_id)

        keys: list[ListingKey] = []
        for product_id in requested_ids:
            try:
                keys.append(alibaba_listing_key(product_id))
            except AlibabaFollowError:
                keys.append(ListingKey(source=FOLLOW_SOURCE, external_id=product_id))

        if _operation_already_recorded(self.repository, keys, operation_query):
            replayed_items = [
                _replay_item(self.repository, product_id, operation_query)
                for product_id in requested_ids
            ]
            replayed_tracked = tuple(
                product
                for product in (
                    tracked_product_from_repository(self.repository, key) for key in keys
                )
                if product is not None
            )
            return summary_from_items(replayed_items, replayed_tracked)

        items: list[AlibabaRefreshItemResult] = []
        to_refresh: list[tuple[TrackedAlibabaProduct, AlibabaTrackedProduct]] = []
        for product_id, key in zip(requested_ids, keys, strict=True):
            tracked_product = tracked_product_from_repository(self.repository, key)
            if tracked_product is None:
                items.append(
                    AlibabaRefreshItemResult(
                        product_id=product_id,
                        status=ProductRefreshStatus.FAILED,
                        message="Producto no encontrado.",
                    )
                )
                continue
            if not tracked_product.is_active:
                items.append(
                    AlibabaRefreshItemResult(
                        product_id=product_id,
                        status=ProductRefreshStatus.FAILED,
                        message="Producto inactivo.",
                    )
                )
                continue
            if not is_alibaba_product_detail_url(tracked_product.url):
                items.append(
                    AlibabaRefreshItemResult(
                        product_id=product_id,
                        status=ProductRefreshStatus.FAILED,
                        message="URL de producto inválida.",
                    )
                )
                continue
            to_refresh.append(
                (
                    TrackedAlibabaProduct(
                        product_id=tracked_product.product_id,
                        product_url=tracked_product.url,
                    ),
                    tracked_product,
                )
            )

        persistable: list[tuple[AlibabaFollowObservation, ProductRefreshStatus]] = []
        if to_refresh:
            try:
                batch = self.provider.refresh_products([item[0] for item in to_refresh])
            except MarketplaceSourceUnavailable as error:
                for requested, _tracked in to_refresh:
                    items.append(
                        AlibabaRefreshItemResult(
                            product_id=requested.product_id,
                            status=ProductRefreshStatus.FAILED,
                            message=str(error) or "Alibaba source is unavailable",
                        )
                    )
                return summary_from_items(items)
            remaining = list(batch.records)
            for index, (requested, tracked_product) in enumerate(to_refresh):
                leftover_requests = len(to_refresh) - index
                record = _associate_record(
                    requested,
                    remaining,
                    singleton_fallback=leftover_requests == 1,
                )
                if record is None:
                    items.append(
                        AlibabaRefreshItemResult(
                            product_id=requested.product_id,
                            status=ProductRefreshStatus.NOT_FOUND,
                        )
                    )
                    continue
                status, normalized, message = _item_status_for_record(
                    requested, tracked_product, record
                )
                items.append(
                    AlibabaRefreshItemResult(
                        product_id=requested.product_id,
                        status=status,
                        message=message,
                    )
                )
                if normalized is None or status not in {
                    ProductRefreshStatus.UPDATED,
                    ProductRefreshStatus.UNCHANGED,
                }:
                    continue
                persistable.append(
                    (
                        AlibabaFollowObservation(
                            product_id=tracked_product.product_id,
                            title=tracked_product.title,
                            url=tracked_product.url,
                            representative_price=normalized.tracking_price,
                            currency=normalized.currency,
                            query=operation_query.text,
                            price_display=normalized.price_display,
                            min_price=normalized.price_min,
                            max_price=normalized.price_max,
                            supplier_name=tracked_product.supplier_name,
                        ),
                        status,
                    )
                )

        collected_at = self.clock()
        listings: list[Listing] = []
        if persistable:
            for observation, _status in persistable:
                listings.append(listing_from_observation(observation, collected_at))
            self.repository.record_collection(
                CollectionBatch.from_listings(
                    source=FOLLOW_SOURCE,
                    query=operation_query,
                    collected_at=collected_at,
                    listings=tuple(listings),
                )
            )

        tracked_after = tuple(
            product
            for product in (tracked_product_from_repository(self.repository, key) for key in keys)
            if product is not None
        )
        return summary_from_items(items, tracked_after)


__all__ = [
    "ALLOWED_PRODUCT_HOSTS",
    "BATCH_TOO_LARGE",
    "CURRENCY_EVIDENCE_ISO",
    "CURRENCY_EVIDENCE_XTRACTO_USD",
    "EMPTY_SELECTION",
    "ISO_CURRENCY_REQUIRED",
    "MAX_ALIBABA_REFRESH_BATCH",
    "MISSING_OPERATION",
    "REFRESH_QUERY_PREFIX",
    "AlibabaProductRefreshProvider",
    "AlibabaRefreshError",
    "AlibabaRefreshItemResult",
    "AlibabaRefreshSummary",
    "LadderTier",
    "NormalizedRefreshPrice",
    "ProductRefreshBatch",
    "ProductRefreshRecord",
    "ProductRefreshStatus",
    "RefreshTrackedAlibabaProducts",
    "TrackedAlibabaProduct",
    "is_alibaba_product_detail_url",
    "normalize_refresh_price",
    "refresh_operation_query",
    "select_moq_tier",
    "summary_from_items",
]
