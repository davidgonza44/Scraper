"""Replay the already-succeeded xtracto dataset. Creates zero Actor runs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from decimal import ROUND_HALF_EVEN, Decimal

from bera_price_tracker.application.alibaba_refresh import (
    CURRENCY_EVIDENCE_XTRACTO_USD,
    ProductRefreshBatch,
    ProductRefreshRecord,
    TrackedAlibabaProduct,
    normalize_refresh_price,
)
from bera_price_tracker.application.alibaba_tracking import alibaba_listing_key
from bera_price_tracker.composition import ApplicationComposition
from bera_price_tracker.config import Settings
from bera_price_tracker.domain import MarketplaceSource
from bera_price_tracker.infrastructure.providers.alibaba_refresh import map_xtracto_item

TARGET = "1601763520797"
OPERATION = "xtracto-pilot-OLloASFHbrGhfPtwc"
OBSERVED_ITEM: dict[str, object] = {
    "productId": 1601763520797,
    "url": (
        "https://www.alibaba.com/product-detail/"
        "Fast-Delivery-for-Resellers-Wireless-Game_1601763520797.html"
    ),
    "priceFormatted": "$3.50-4.30",
    "currency": "${0}",
    "minOrderQuantity": 1,
    "ladderPrices": [
        {
            "minQty": 1,
            "maxQty": 49,
            "pricePerUnit": 4.3,
            "pricePerUnitFormatted": "$4.30",
            "pricePerUnitUSD": 4.3,
        },
        {
            "minQty": 50,
            "maxQty": 199,
            "pricePerUnit": 4,
            "pricePerUnitFormatted": "$4",
            "pricePerUnitUSD": 4,
        },
        {
            "minQty": 200,
            "maxQty": 999,
            "pricePerUnit": 3.8,
            "pricePerUnitFormatted": "$3.80",
            "pricePerUnitUSD": 3.8,
        },
        {
            "minQty": 1000,
            "pricePerUnit": 3.5,
            "pricePerUnitFormatted": "$3.50",
            "pricePerUnitUSD": 3.5,
        },
    ],
}


class ReplayProvider:
    def __init__(self, record: ProductRefreshRecord) -> None:
        self.record = record
        self.calls = 0

    def refresh_products(self, products: Sequence[TrackedAlibabaProduct]) -> ProductRefreshBatch:
        del products
        self.calls += 1
        return ProductRefreshBatch(records=(self.record,))


def main() -> int:
    mapped = map_xtracto_item(OBSERVED_ITEM)
    if mapped is None:
        print("CANDIDATE_DATA_UNAVAILABLE")
        return 1
    normalized = normalize_refresh_price(mapped)
    if normalized is None:
        print("INVALID_PRICE")
        return 1
    coincides = all(
        tier.price is not None and tier.price_usd is not None and tier.price == tier.price_usd
        for tier in mapped.ladder_prices
    )
    print(f"identity={mapped.product_id == TARGET}")
    print(f"currency_raw={mapped.currency}")
    print(f"currency_normalized={normalized.currency}")
    print(f"evidence={normalized.currency_evidence}")
    print(f"tracking={normalized.tracking_price}")
    print(f"midpoint={normalized.representative}")
    print(f"price_min={normalized.price_min}")
    print(f"price_max={normalized.price_max}")
    print(f"display={normalized.price_display}")
    print(f"tier={normalized.selected_min_quantity}-{normalized.selected_max_quantity}")
    print(f"unit_equals_usd={coincides}")
    print(f"evidence_ok={normalized.currency_evidence == CURRENCY_EVIDENCE_XTRACTO_USD}")

    settings = replace(Settings.from_env({}), database_path="data/bera_price_tracker.db")
    composition = ApplicationComposition(settings)
    with composition.repository_factory(settings) as repository:
        stored = repository.get_listing(alibaba_listing_key(TARGET))
        history = repository.get_price_history(alibaba_listing_key(TARGET))
        active = repository.list_listing_keys(MarketplaceSource.ALIBABA, active_only=True)
    print(f"pre_active={len(active)}")
    print(f"pre_snapshots={len(history)}")
    print(f"pre_price={history[-1].snapshot.price if history else None}")
    print(f"pre_active_flag={stored.is_active if stored else None}")
    if stored is None or not stored.is_active or len(history) != 1:
        print("precheck=FAIL")
        return 2

    provider = ReplayProvider(mapped)
    summary = composition.refresh_alibaba_products(
        [TARGET],
        operation_id=OPERATION,
        refresh_provider=provider,
    )
    print(f"provider_calls={provider.calls}")
    item = summary.items[0] if summary.items else None
    print(f"status={item.status.value if item else 'NONE'}")
    print(f"message={item.message if item else ''}")
    print(f"unchanged={summary.unchanged}")

    with composition.repository_factory(settings) as repository:
        after = repository.get_price_history(alibaba_listing_key(TARGET))
        stored_after = repository.get_listing(alibaba_listing_key(TARGET))
    if stored_after is None or len(after) < 2:
        print("persist=FAIL")
        return 1
    print(f"post_snapshots={len(after)}")
    print(f"post_price={after[-1].snapshot.price}")
    print(f"post_currency={after[-1].snapshot.currency}")
    print(f"post_min={stored_after.price_min}")
    print(f"post_max={stored_after.price_max}")
    print(f"post_display={stored_after.price_display}")
    print(f"still_active={stored_after.is_active}")
    absolute = after[-1].snapshot.price - after[-2].snapshot.price
    percent = (absolute / after[-2].snapshot.price * Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_EVEN
    )
    print(f"absolute={absolute}")
    print(f"percent={percent}")
    print("actor_runs_new=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
