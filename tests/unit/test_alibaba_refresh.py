"""Offline tests for Alibaba product-detail refresh. No Actor runs."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from bera_price_tracker.application.alibaba_refresh import (
    BATCH_TOO_LARGE,
    CURRENCY_EVIDENCE_ISO,
    CURRENCY_EVIDENCE_XTRACTO_USD,
    MAX_ALIBABA_REFRESH_BATCH,
    AlibabaRefreshError,
    LadderTier,
    ProductRefreshBatch,
    ProductRefreshRecord,
    ProductRefreshStatus,
    RefreshTrackedAlibabaProducts,
    TrackedAlibabaProduct,
    _replay_item,
    is_alibaba_product_detail_url,
    normalize_refresh_price,
    refresh_operation_query,
    select_moq_tier,
)
from bera_price_tracker.application.alibaba_tracking import AlibabaFollowObservation
from bera_price_tracker.application.ports import MarketplaceSourceUnavailable
from bera_price_tracker.composition import ApplicationComposition
from bera_price_tracker.config import (
    DEFAULT_APIFY_ALIBABA_REFRESH_ACTOR,
    DEFAULT_APIFY_ALIBABA_REFRESH_CONCURRENCY,
    DEFAULT_APIFY_ALIBABA_REFRESH_RETRIES,
    Settings,
)
from bera_price_tracker.domain import ListingKey, MarketplaceSource, SearchQuery
from bera_price_tracker.gui import services
from bera_price_tracker.infrastructure.persistence import SQLiteListingRepository
from bera_price_tracker.infrastructure.providers.alibaba_refresh import (
    ApifyAlibabaProductRefreshClient,
    build_alibaba_refresh_run_input,
    map_xtracto_item,
)
from bera_price_tracker.infrastructure.providers.apify import ApifyConfigurationError

BASE = datetime(2026, 8, 23, 15, 0, 0, tzinfo=UTC)
SRC = Path(__file__).resolve().parents[2] / "src"


class FakeAlibabaProductRefreshProvider:
    def __init__(
        self,
        records: Sequence[ProductRefreshRecord] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.records = list(records or [])
        self.error = error
        self.calls: list[list[TrackedAlibabaProduct]] = []

    def refresh_products(self, products: Sequence[TrackedAlibabaProduct]) -> ProductRefreshBatch:
        self.calls.append(list(products))
        if self.error is not None:
            raise self.error
        return ProductRefreshBatch(records=tuple(self.records))


def _settings(tmp_path: Path) -> Settings:
    return replace(Settings.from_env(), database_path=str(tmp_path / "tracker.db"))


def _clock(moment: datetime) -> Callable[[], datetime]:
    return lambda: moment


def _follow_observation(
    *,
    product_id: str = "1600000000000",
    price: Decimal = Decimal("15.25"),
    minimum: Decimal = Decimal("15.25"),
    maximum: Decimal = Decimal("15.25"),
    display: str = "$15.25",
    title: str = "Wireless Mouse",
) -> AlibabaFollowObservation:
    return AlibabaFollowObservation(
        product_id=product_id,
        title=title,
        url=f"https://www.alibaba.com/product-detail/{product_id}.html",
        representative_price=price,
        currency="USD",
        query="wireless mouse",
        price_display=display,
        min_price=minimum,
        max_price=maximum,
        supplier_name="Example Electronics Co., Ltd.",
        supplier_country="CN",
    )


_TIER_BOUNDS = ((1, 49), (50, 199), (200, 999), (1000, None))


def _record(
    *,
    product_id: str = "1600000000000",
    product_url: str | None = None,
    currency: str | None = "USD",
    price_formatted: str | None = "$12.50 - $18.00",
    prices: Sequence[Decimal] | None = None,
    min_order_quantity: int | None = 1,
) -> ProductRefreshRecord:
    if prices is None:
        values = [Decimal("15.25"), Decimal("12.50")]
    else:
        values = list(prices)
    tiers = tuple(
        LadderTier(
            min_quantity=_TIER_BOUNDS[index][0]
            if index < len(_TIER_BOUNDS)
            else 1000 * (index + 1),
            max_quantity=_TIER_BOUNDS[index][1] if index < len(_TIER_BOUNDS) else None,
            price=value,
            price_formatted=None,
        )
        for index, value in enumerate(values)
    )
    return ProductRefreshRecord(
        product_id=product_id,
        product_url=product_url or f"https://www.alibaba.com/product-detail/{product_id}.html",
        price_formatted=price_formatted,
        currency=currency,
        ladder_prices=tiers,
        min_order_quantity=min_order_quantity,
        scraped_at=BASE,
    )


def _observed_xtracto_item(
    *,
    currency: object = "${0}",
    include_usd: bool = True,
    min_order_quantity: int = 1,
    usd_values: Sequence[object] | None = None,
) -> dict[str, object]:
    units = (Decimal("4.3"), Decimal("4"), Decimal("3.8"), Decimal("3.5"))
    usd = list(usd_values) if usd_values is not None else list(units)
    tiers: list[dict[str, object]] = []
    bounds = ((1, 49), (50, 199), (200, 999), (1000, None))
    formatted = ("$4.30", "$4", "$3.80", "$3.50")
    for index, (unit, bound, display) in enumerate(zip(units, bounds, formatted, strict=True)):
        tier: dict[str, object] = {
            "minQty": bound[0],
            "pricePerUnit": unit,
            "pricePerUnitFormatted": display,
        }
        if bound[1] is not None:
            tier["maxQty"] = bound[1]
        if include_usd:
            tier["pricePerUnitUSD"] = usd[index]
        tiers.append(tier)
    return {
        "productId": 1601763520797,
        "url": (
            "https://www.alibaba.com/product-detail/"
            "Fast-Delivery-for-Resellers-Wireless-Game_1601763520797.html"
        ),
        "priceFormatted": "$3.50-4.30",
        "currency": currency,
        "minOrderQuantity": min_order_quantity,
        "ladderPrices": tiers,
    }


def _follow_many(
    composition: ApplicationComposition,
    count: int,
    clock: Callable[[], datetime],
) -> list[str]:
    ids: list[str] = []
    for index in range(count):
        product_id = f"160000000{index:04d}"
        composition.follow_alibaba_price(
            _follow_observation(product_id=product_id),
            clock=clock,
        )
        ids.append(product_id)
    return ids


def test_refresh_input_uses_audited_fields_only() -> None:
    payload = build_alibaba_refresh_run_input(
        ["https://www.alibaba.com/product-detail/1600000000000.html"],
        max_request_retries=1,
        max_concurrency=3,
    )
    assert list(payload.keys()) == ["productUrls", "maxConcurrency", "maxRequestRetries"]
    assert payload["productUrls"] == [
        {"url": "https://www.alibaba.com/product-detail/1600000000000.html"}
    ]
    assert payload["maxRequestRetries"] == 1
    assert payload["maxConcurrency"] == 3


def test_defaults_are_low_retries_and_xtracto() -> None:
    settings = Settings.from_env({})
    assert settings.apify_alibaba_actor == "scraper-engine/alibaba-scraper"
    assert settings.apify_alibaba_refresh_actor == DEFAULT_APIFY_ALIBABA_REFRESH_ACTOR
    assert settings.apify_alibaba_refresh_retries == DEFAULT_APIFY_ALIBABA_REFRESH_RETRIES
    assert settings.apify_alibaba_refresh_concurrency == DEFAULT_APIFY_ALIBABA_REFRESH_CONCURRENCY
    assert settings.apify_alibaba_refresh_retries == 1
    assert settings.apify_alibaba_refresh_concurrency == 3


def test_retry_six_is_rejected() -> None:
    with pytest.raises(ValueError, match="apify_alibaba_refresh_retries"):
        Settings.from_env({"BERA_TRACKER_APIFY_ALIBABA_REFRESH_RETRIES": "6"})


def test_product_detail_url_rejects_other_hosts() -> None:
    assert is_alibaba_product_detail_url(
        "https://www.alibaba.com/product-detail/1600000000000.html"
    )
    assert not is_alibaba_product_detail_url("https://example.com/product-detail/1.html")
    assert not is_alibaba_product_detail_url("https://www.alibaba.com/trade/search?keywords=x")


def test_ladder_midpoint_is_not_tracking_price() -> None:
    normalized = normalize_refresh_price(
        _record(prices=(Decimal("18.00"), Decimal("15.50"), Decimal("12.50")))
    )
    assert normalized is not None
    assert normalized.price_min == Decimal("12.50")
    assert normalized.price_max == Decimal("18.00")
    assert normalized.representative == Decimal("15.25")
    assert normalized.tracking_price == Decimal("18.00")
    assert normalized.tracking_price != normalized.representative
    assert normalized.currency == "USD"
    assert normalized.currency_evidence == CURRENCY_EVIDENCE_ISO


def test_dollar_symbol_is_not_usd() -> None:
    assert normalize_refresh_price(_record(currency="$")) is None


def test_template_currency_alone_is_not_usd() -> None:
    mapped = map_xtracto_item(_observed_xtracto_item(include_usd=False))
    assert mapped is not None
    assert mapped.currency == "${0}"
    assert normalize_refresh_price(mapped) is None


def test_formatted_dollar_alone_is_not_usd() -> None:
    mapped = map_xtracto_item(
        {
            "productId": 1601763520797,
            "priceFormatted": "$4.30",
            "currency": "${0}",
            "ladderPrices": [],
        }
    )
    assert mapped is not None
    assert normalize_refresh_price(mapped) is None


def test_price_per_unit_usd_is_explicit_usd() -> None:
    mapped = map_xtracto_item(_observed_xtracto_item())
    assert mapped is not None
    normalized = normalize_refresh_price(mapped)
    assert normalized is not None
    assert normalized.currency == "USD"
    assert normalized.currency_evidence == CURRENCY_EVIDENCE_XTRACTO_USD
    assert normalized.tracking_price == Decimal("4.3")
    assert normalized.price_min == Decimal("3.5")
    assert normalized.price_max == Decimal("4.3")
    assert normalized.price_display == "$3.50-4.30"
    assert normalized.representative == Decimal("3.9")
    assert normalized.tracking_price != normalized.representative
    assert normalized.selected_min_quantity == 1
    assert normalized.selected_max_quantity == 49
    assert isinstance(normalized.tracking_price, Decimal)


def test_invalid_price_per_unit_usd_is_ignored() -> None:
    mapped = map_xtracto_item(_observed_xtracto_item(usd_values=("abc", -1, 0, None)))
    assert mapped is not None
    assert all(tier.price_usd is None for tier in mapped.ladder_prices)
    assert normalize_refresh_price(mapped) is None


def test_moq_selects_covering_tier() -> None:
    mapped = map_xtracto_item(_observed_xtracto_item(min_order_quantity=200))
    assert mapped is not None
    selected = select_moq_tier(mapped.ladder_prices, 200, use_usd=True)
    assert selected is not None
    assert selected.min_quantity == 200
    normalized = normalize_refresh_price(mapped)
    assert normalized is not None
    assert normalized.tracking_price == Decimal("3.8")
    assert normalized.price_min == Decimal("3.5")
    assert normalized.price_max == Decimal("4.3")


def test_map_xtracto_observed_ladder_keys() -> None:
    mapped = map_xtracto_item(
        {
            "productId": 1601763520797,
            "url": "https://www.alibaba.com/product-detail/Fast-Delivery_1601763520797.html",
            "priceFormatted": "$3.50-4.30",
            "currency": "USD",
            "minOrderQuantity": 1,
            "ladderPrices": [
                {"minQty": 1, "maxQty": 49, "pricePerUnit": 4.3, "pricePerUnitFormatted": "$4.30"},
                {"minQty": 1000, "pricePerUnit": 3.5, "pricePerUnitFormatted": "$3.50"},
            ],
        }
    )
    assert mapped is not None
    assert mapped.product_url is not None
    assert mapped.ladder_prices[0].price == Decimal("4.3")
    assert mapped.ladder_prices[1].price == Decimal("3.5")
    normalized = normalize_refresh_price(mapped)
    assert normalized is not None
    assert normalized.price_min == Decimal("3.5")
    assert normalized.price_max == Decimal("4.3")
    assert normalized.representative == Decimal("3.9")
    assert normalized.tracking_price == Decimal("4.3")
    assert normalized.currency == "USD"
    assert normalized.currency_evidence == CURRENCY_EVIDENCE_ISO


def test_batch_of_one(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    composition = ApplicationComposition(settings=settings)
    composition.follow_alibaba_price(_follow_observation(), clock=_clock(BASE))
    provider = FakeAlibabaProductRefreshProvider([_record(prices=(Decimal("20"), Decimal("10")))])
    summary = composition.refresh_alibaba_products(
        ["1600000000000"],
        operation_id="op-one",
        clock=_clock(BASE + timedelta(hours=1)),
        refresh_provider=provider,
    )
    assert len(provider.calls) == 1
    assert [item.product_url for item in provider.calls[0]] == [
        "https://www.alibaba.com/product-detail/1600000000000.html"
    ]
    assert summary.requested == 1
    assert summary.updated == 1
    assert summary.predicted_runs == 1
    tracked = composition.list_alibaba_tracked()[0]
    assert tracked.product_id == "1600000000000"
    assert tracked.variation.snapshot_count == 2
    assert tracked.variation.last_price == Decimal("20")


def test_batch_of_ten_is_one_provider_call(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    composition = ApplicationComposition(settings=settings)
    ids = _follow_many(composition, 10, _clock(BASE))
    records = [_record(product_id=product_id) for product_id in ids]
    provider = FakeAlibabaProductRefreshProvider(records)
    summary = composition.refresh_alibaba_products(
        ids,
        operation_id="op-ten",
        clock=_clock(BASE + timedelta(hours=1)),
        refresh_provider=provider,
    )
    assert len(provider.calls) == 1
    assert len(provider.calls[0]) == 10
    assert summary.requested == 10
    assert summary.unchanged == 10


def test_batch_of_fifty_is_one_provider_call(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    composition = ApplicationComposition(settings=settings)
    ids = _follow_many(composition, 50, _clock(BASE))
    provider = FakeAlibabaProductRefreshProvider([_record(product_id=item) for item in ids])
    summary = composition.refresh_alibaba_products(
        ids,
        operation_id="op-fifty",
        clock=_clock(BASE + timedelta(hours=1)),
        refresh_provider=provider,
    )
    assert len(provider.calls) == 1
    assert len(provider.calls[0]) == 50
    assert summary.requested == 50


def test_more_than_fifty_is_rejected(tmp_path: Path) -> None:
    composition = ApplicationComposition(settings=_settings(tmp_path))
    provider = FakeAlibabaProductRefreshProvider()
    with pytest.raises(AlibabaRefreshError, match="50"):
        composition.refresh_alibaba_products(
            [f"id-{index}" for index in range(51)],
            operation_id="op-too-many",
            refresh_provider=provider,
        )
    assert provider.calls == []
    assert MAX_ALIBABA_REFRESH_BATCH == 50
    assert "50" in BATCH_TOO_LARGE


def test_inactive_product_is_ignored(tmp_path: Path) -> None:
    composition = ApplicationComposition(settings=_settings(tmp_path))
    composition.follow_alibaba_price(_follow_observation(), clock=_clock(BASE))
    composition.unfollow_alibaba_price("1600000000000")
    provider = FakeAlibabaProductRefreshProvider([_record()])
    summary = composition.refresh_alibaba_products(
        ["1600000000000"],
        operation_id="op-inactive",
        refresh_provider=provider,
    )
    assert provider.calls == []
    assert summary.failed == 1
    with SQLiteListingRepository(_settings(tmp_path).database_path) as repository:
        stored = repository.get_listing(ListingKey(MarketplaceSource.ALIBABA, "1600000000000"))
        assert stored is not None
        assert stored.is_active is False
        assert repository.count_price_snapshots() == 1


def test_identity_mismatch_does_not_persist(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    composition = ApplicationComposition(settings=settings)
    composition.follow_alibaba_price(_follow_observation(), clock=_clock(BASE))
    provider = FakeAlibabaProductRefreshProvider(
        [
            _record(
                product_id="9999999999999",
                product_url="https://www.alibaba.com/product-detail/1600000000000.html",
            )
        ]
    )
    summary = composition.refresh_alibaba_products(
        ["1600000000000"],
        operation_id="op-mismatch",
        clock=_clock(BASE + timedelta(hours=1)),
        refresh_provider=provider,
    )
    assert summary.identity_mismatch == 1
    tracked = composition.list_alibaba_tracked(active_only=False)[0]
    assert tracked.variation.snapshot_count == 1
    assert tracked.product_id == "1600000000000"


def test_not_found(tmp_path: Path) -> None:
    composition = ApplicationComposition(settings=_settings(tmp_path))
    composition.follow_alibaba_price(_follow_observation(), clock=_clock(BASE))
    provider = FakeAlibabaProductRefreshProvider([])
    summary = composition.refresh_alibaba_products(
        ["1600000000000"],
        operation_id="op-missing",
        refresh_provider=provider,
    )
    assert summary.not_found == 1
    assert composition.list_alibaba_tracked()[0].variation.snapshot_count == 1


def test_invalid_price(tmp_path: Path) -> None:
    composition = ApplicationComposition(settings=_settings(tmp_path))
    composition.follow_alibaba_price(_follow_observation(), clock=_clock(BASE))
    provider = FakeAlibabaProductRefreshProvider([_record(currency=None, prices=())])
    summary = composition.refresh_alibaba_products(
        ["1600000000000"],
        operation_id="op-invalid",
        refresh_provider=provider,
    )
    assert summary.invalid_price == 1
    assert composition.list_alibaba_tracked()[0].variation.snapshot_count == 1


def test_currency_mismatch(tmp_path: Path) -> None:
    composition = ApplicationComposition(settings=_settings(tmp_path))
    composition.follow_alibaba_price(_follow_observation(), clock=_clock(BASE))
    provider = FakeAlibabaProductRefreshProvider([_record(currency="EUR")])
    summary = composition.refresh_alibaba_products(
        ["1600000000000"],
        operation_id="op-fx",
        refresh_provider=provider,
    )
    assert summary.invalid_price == 1
    assert composition.list_alibaba_tracked()[0].history[-1].currency == "USD"


def test_provider_failure(tmp_path: Path) -> None:
    composition = ApplicationComposition(settings=_settings(tmp_path))
    composition.follow_alibaba_price(_follow_observation(), clock=_clock(BASE))
    provider = FakeAlibabaProductRefreshProvider(
        error=MarketplaceSourceUnavailable("Alibaba source is unavailable")
    )
    summary = composition.refresh_alibaba_products(
        ["1600000000000"],
        operation_id="op-fail",
        refresh_provider=provider,
    )
    assert summary.failed == 1
    assert composition.list_alibaba_tracked()[0].variation.snapshot_count == 1


def test_partial_success(tmp_path: Path) -> None:
    composition = ApplicationComposition(settings=_settings(tmp_path))
    first = "1600000000001"
    second = "1600000000002"
    third = "1600000000003"
    for product_id in (first, second, third):
        composition.follow_alibaba_price(
            _follow_observation(product_id=product_id), clock=_clock(BASE)
        )
    provider = FakeAlibabaProductRefreshProvider(
        [
            _record(product_id=first, prices=(Decimal("20"), Decimal("10"))),
            _record(product_id=third, currency=None, prices=()),
        ]
    )
    summary = composition.refresh_alibaba_products(
        [first, second, third],
        operation_id="op-partial",
        clock=_clock(BASE + timedelta(hours=2)),
        refresh_provider=provider,
    )
    assert summary.updated == 1
    assert summary.not_found == 1
    assert summary.invalid_price == 1
    rows = {item.product_id: item for item in composition.list_alibaba_tracked()}
    assert rows[first].variation.snapshot_count == 2
    assert rows[second].variation.snapshot_count == 1
    assert rows[third].variation.snapshot_count == 1


def test_observed_run_unchanged_creates_snapshot(tmp_path: Path) -> None:
    composition = ApplicationComposition(settings=_settings(tmp_path))
    composition.follow_alibaba_price(
        _follow_observation(
            product_id="1601763520797",
            price=Decimal("4.30"),
            minimum=Decimal("4.30"),
            maximum=Decimal("4.30"),
            display="$4.30",
            title="Fast Delivery for Resellers Wireless Game Mouse",
        ),
        clock=_clock(BASE),
    )
    mapped = map_xtracto_item(_observed_xtracto_item())
    assert mapped is not None
    provider = FakeAlibabaProductRefreshProvider([mapped])
    summary = composition.refresh_alibaba_products(
        ["1601763520797"],
        operation_id="op-observed",
        clock=_clock(BASE + timedelta(hours=1)),
        refresh_provider=provider,
    )
    assert summary.unchanged == 1
    assert summary.items[0].message == CURRENCY_EVIDENCE_XTRACTO_USD
    tracked = composition.list_alibaba_tracked()[0]
    assert tracked.variation.snapshot_count == 2
    assert tracked.variation.last_price == Decimal("4.30")
    assert tracked.variation.absolute_change == Decimal("0")
    assert tracked.price_min == Decimal("3.5")
    assert tracked.price_max == Decimal("4.3")
    assert tracked.history[-1].price == Decimal("4.30")
    assert tracked.history[-1].currency == "USD"


def test_regression_1601769395876_discovery_midpoint_is_not_compared(tmp_path: Path) -> None:
    """Real pilot case: follow stored the 89.20-108.20 midpoint (98.70) and the
    first xtracto refresh returned the MOQ tier price 108.20. That must establish
    the baseline, never report +9.63%."""

    composition = ApplicationComposition(settings=_settings(tmp_path))
    composition.follow_alibaba_price(
        _follow_observation(
            product_id="1601769395876",
            price=Decimal("98.70"),
            minimum=Decimal("89.20"),
            maximum=Decimal("108.20"),
            display="$89.20 - $108.20",
            title="Custom Brake Pads",
        ),
        clock=_clock(BASE),
    )
    provider = FakeAlibabaProductRefreshProvider(
        [
            _record(
                product_id="1601769395876",
                price_formatted="$89.20 - $108.20",
                prices=(Decimal("108.20"), Decimal("89.20")),
            )
        ]
    )
    summary = composition.refresh_alibaba_products(
        ["1601769395876"],
        operation_id="op-baseline",
        clock=_clock(BASE + timedelta(hours=1)),
        refresh_provider=provider,
    )
    assert summary.updated == 1
    tracked = composition.list_alibaba_tracked()[0]
    assert tracked.variation.snapshot_count == 2
    assert tracked.variation.first_price == Decimal("98.70")
    assert tracked.variation.baseline_price == Decimal("108.20")
    assert tracked.variation.last_price == Decimal("108.20")
    assert tracked.variation.absolute_change is None
    assert tracked.variation.percentage_change is None
    assert tracked.variation.historical_minimum == Decimal("108.20")
    assert tracked.variation.historical_maximum == Decimal("108.20")


def test_second_canonical_refresh_compares_canonical_prices(tmp_path: Path) -> None:
    composition = ApplicationComposition(settings=_settings(tmp_path))
    composition.follow_alibaba_price(
        _follow_observation(
            product_id="1601769395876",
            price=Decimal("98.70"),
            minimum=Decimal("89.20"),
            maximum=Decimal("108.20"),
            display="$89.20 - $108.20",
        ),
        clock=_clock(BASE),
    )
    first_provider = FakeAlibabaProductRefreshProvider(
        [_record(product_id="1601769395876", prices=(Decimal("108.20"), Decimal("89.20")))]
    )
    composition.refresh_alibaba_products(
        ["1601769395876"],
        operation_id="op-first",
        clock=_clock(BASE + timedelta(hours=1)),
        refresh_provider=first_provider,
    )
    second_provider = FakeAlibabaProductRefreshProvider(
        [_record(product_id="1601769395876", prices=(Decimal("105"), Decimal("89.20")))]
    )
    summary = composition.refresh_alibaba_products(
        ["1601769395876"],
        operation_id="op-second",
        clock=_clock(BASE + timedelta(hours=2)),
        refresh_provider=second_provider,
    )
    assert summary.updated == 1
    tracked = composition.list_alibaba_tracked()[0]
    assert tracked.variation.baseline_price == Decimal("108.20")
    assert tracked.variation.last_price == Decimal("105")
    assert tracked.variation.absolute_change == Decimal("-3.20")
    assert tracked.variation.percentage_change is not None
    assert tracked.variation.percentage_change.quantize(Decimal("0.01")) == Decimal("-2.96")
    assert tracked.variation.historical_minimum == Decimal("105")
    assert tracked.variation.historical_maximum == Decimal("108.20")


def test_discovery_representative_price_stays_midpoint() -> None:
    from types import SimpleNamespace

    from bera_price_tracker.application.alibaba_statistics import alibaba_representative_price

    product = SimpleNamespace(min_price=Decimal("3.50"), max_price=Decimal("4.30"))
    assert alibaba_representative_price(product) == Decimal("3.90")
    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "bera_price_tracker"
        / "application"
        / "alibaba_statistics.py"
    ).read_text(encoding="utf-8")
    assert "the midpoint of a published range" in source


def test_unchanged_creates_new_snapshot(tmp_path: Path) -> None:
    composition = ApplicationComposition(settings=_settings(tmp_path))
    composition.follow_alibaba_price(_follow_observation(), clock=_clock(BASE))
    provider = FakeAlibabaProductRefreshProvider([_record()])
    summary = composition.refresh_alibaba_products(
        ["1600000000000"],
        operation_id="op-same",
        clock=_clock(BASE + timedelta(days=1)),
        refresh_provider=provider,
    )
    assert summary.unchanged == 1
    tracked = composition.list_alibaba_tracked()[0]
    assert tracked.variation.snapshot_count == 2
    assert tracked.variation.last_price == Decimal("15.25")
    assert tracked.last_updated == BASE + timedelta(days=1)


def test_operation_idempotency(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    composition = ApplicationComposition(settings=settings)
    composition.follow_alibaba_price(_follow_observation(), clock=_clock(BASE))
    provider = FakeAlibabaProductRefreshProvider([_record(prices=(Decimal("20"), Decimal("10")))])
    first = composition.refresh_alibaba_products(
        ["1600000000000"],
        operation_id="op-once",
        clock=_clock(BASE + timedelta(hours=1)),
        refresh_provider=provider,
    )
    second = composition.refresh_alibaba_products(
        ["1600000000000"],
        operation_id="op-once",
        clock=_clock(BASE + timedelta(hours=2)),
        refresh_provider=provider,
    )
    assert len(provider.calls) == 1
    assert first.updated == 1
    assert second.updated == 1
    tracked = composition.list_alibaba_tracked()[0]
    assert tracked.variation.snapshot_count == 2
    assert tracked.product_id == "1600000000000"


def test_gui_confirmation_and_selection_cap() -> None:
    confirmation = services.alibaba_refresh_confirmation(20)
    assert "20" in confirmation["intro"]
    assert confirmation["selected"] == "20"
    assert confirmation["predicted_runs"] == "1"
    assert "créditos" in confirmation["intro"]
    selected = services.clamp_alibaba_refresh_selection([f"id-{index}" for index in range(80)])
    assert len(selected) == 50


def test_gui_refresh_uses_application_service(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    composition = ApplicationComposition(settings=settings)
    composition.follow_alibaba_price(_follow_observation(), clock=_clock(BASE))
    provider = FakeAlibabaProductRefreshProvider([_record()])
    row = services.refresh_alibaba_tracked(
        ["1600000000000"],
        "op-gui",
        settings=settings,
        clock=_clock(BASE + timedelta(hours=3)),
        composition=composition,
        refresh_provider=provider,
    )
    assert row["requested"] == "1"
    assert row["unchanged"] == "1"
    assert row["predicted_runs"] == "1"


def test_gui_row_shows_baseline_range_and_provenance_tags(tmp_path: Path) -> None:
    """The Seguimiento card separates tracking price, published range, the
    provisional discovery price and the canonical baseline."""

    composition = ApplicationComposition(settings=_settings(tmp_path))
    composition.follow_alibaba_price(
        _follow_observation(
            product_id="1601769395876",
            price=Decimal("98.70"),
            minimum=Decimal("89.20"),
            maximum=Decimal("108.20"),
            display="$89.20 - $108.20",
        ),
        clock=_clock(BASE),
    )
    provider = FakeAlibabaProductRefreshProvider(
        [_record(product_id="1601769395876", prices=(Decimal("108.20"), Decimal("89.20")))]
    )
    composition.refresh_alibaba_products(
        ["1601769395876"],
        operation_id="op-gui-row",
        clock=_clock(BASE + timedelta(hours=1)),
        refresh_provider=provider,
    )
    row = services.tracked_product_to_row(composition.list_alibaba_tracked()[0])
    assert row["last_price"] == "$108.20"
    assert row["published_range"] == "$89.20–$108.20"
    assert row["first_price"] == "$98.70"
    assert row["first_price_tag"] == "Discovery"
    assert row["baseline"] == "$108.20"
    assert row["variation"] == "—"
    history_lines = row["history"].splitlines()
    assert len(history_lines) == 2
    assert history_lines[0].endswith("· Discovery")
    assert history_lines[1].endswith("· Seguimiento")


def test_gui_row_simple_follow_has_no_discovery_tag(tmp_path: Path) -> None:
    composition = ApplicationComposition(settings=_settings(tmp_path))
    composition.follow_alibaba_price(_follow_observation(), clock=_clock(BASE))
    row = services.tracked_product_to_row(composition.list_alibaba_tracked()[0])
    assert row["first_price_tag"] == ""
    assert row["published_range"] == ""
    assert row["baseline"] == "$15.25"
    assert row["variation"] == "—"
    assert "Discovery" not in row["history"]


def test_refresh_does_not_touch_scores_or_facebook() -> None:
    text = (SRC / "bera_price_tracker" / "application" / "alibaba_refresh.py").read_text(
        encoding="utf-8"
    )
    adapter = (
        SRC / "bera_price_tracker" / "infrastructure" / "providers" / "alibaba_refresh.py"
    ).read_text(encoding="utf-8")
    for banned in (
        "opportunity_score",
        "relevance_score",
        "reputation_score",
        "ranking_score",
        "facebook",
        "H0019",
        "chatToken",
        "contactSupplier",
        "trackInfo",
        "supplierHref",
    ):
        assert banned not in text
        assert banned not in adapter


def test_mapper_drops_secrets() -> None:
    mapped = map_xtracto_item(
        {
            "productId": "1600000000000",
            "priceFormatted": "$12.50 - $18.00",
            "currency": "USD",
            "ladderPrices": [{"minQuantity": 2, "price": 18, "priceFormatted": "$18.00"}],
            "minOrderQuantity": 2,
            "scrapedAt": "2026-05-30T04:37:55Z",
            "companyId": "secret-company",
            "chatToken": "secret-chat",
            "contactSupplier": "mailto:hidden@example.com",
            "trackInfo": "secret-track",
        }
    )
    assert mapped is not None
    assert mapped.product_id == "1600000000000"
    dumped = repr(mapped)
    assert "secret-company" not in dumped
    assert "secret-chat" not in dumped
    assert "hidden@example.com" not in dumped


def test_client_uses_one_call_and_default_actor() -> None:
    class _Page:
        def __init__(self, items: list[object]) -> None:
            self.items = items

    class _Dataset:
        def list_items(self, *, limit: int) -> _Page:
            items: list[object] = [
                {
                    "productId": "1600000000000",
                    "priceFormatted": "$12.50 - $18.00",
                    "currency": "USD",
                    "ladderPrices": [{"price": "12.50"}, {"price": "18.00"}],
                }
            ]
            return _Page(items[:limit])

    class _Actor:
        def __init__(self, owner: FakeApify) -> None:
            self.owner = owner

        def call(self, *, run_input: dict[str, object]) -> dict[str, object]:
            self.owner.calls.append(run_input)
            return {"status": "SUCCEEDED", "defaultDatasetId": "ds1"}

    class FakeApify:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []
            self.actor_id = ""

        def actor(self, actor_id: str) -> _Actor:
            self.actor_id = actor_id
            return _Actor(self)

        def dataset(self, dataset_id: str) -> _Dataset:
            self.dataset_id = dataset_id
            return _Dataset()

    fake = FakeApify()
    client = ApifyAlibabaProductRefreshClient(
        _api_token="token",
        client_factory=lambda _token: fake,
    )
    batch = client.refresh_products(
        [
            TrackedAlibabaProduct(
                product_id="1600000000000",
                product_url="https://www.alibaba.com/product-detail/1600000000000.html",
            )
        ]
    )
    assert fake.actor_id == "xtracto/alibaba-product-scraper"
    assert len(fake.calls) == 1
    assert fake.calls[0]["maxRequestRetries"] == 1
    assert fake.calls[0]["maxConcurrency"] == 3
    assert batch.records[0].product_id == "1600000000000"
    assert "token" not in repr(client)


def test_service_uses_repository_not_sqlite_directly() -> None:
    with SQLiteListingRepository(":memory:") as repository:
        follow = RefreshTrackedAlibabaProducts.__dataclass_fields__
        assert "repository" in follow
        from bera_price_tracker.application.alibaba_tracking import FollowAlibabaPrice

        FollowAlibabaPrice(repository=repository, clock=_clock(BASE)).execute(_follow_observation())
        provider = FakeAlibabaProductRefreshProvider([_record()])
        summary = RefreshTrackedAlibabaProducts(
            repository=repository,
            provider=provider,
            clock=_clock(BASE + timedelta(hours=1)),
        ).execute(["1600000000000"], operation_id="op-repo")
        assert summary.unchanged == 1


def test_views_expose_refresh_controls() -> None:
    views = (SRC / "bera_price_tracker" / "gui" / "views.py").read_text(encoding="utf-8")
    assert "Actualizar seleccionados" in views
    assert "Seleccionar todos visibles" in views
    assert "Actor runs previstos: 1" in views
    assert "Actualizar" in views


def test_gui_modules_still_avoid_sqlite() -> None:
    gui = SRC / "bera_price_tracker" / "gui"
    for name in ("state.py", "views.py", "services.py"):
        text = (gui / name).read_text(encoding="utf-8")
        assert "sqlite3" not in text
        assert "SQLiteListingRepository" not in text
        assert "ApifyAlibabaProductRefreshClient" not in text


def test_empty_selection_and_non_sequence_ids_are_rejected(tmp_path: Path) -> None:
    composition = ApplicationComposition(settings=_settings(tmp_path))
    with pytest.raises(AlibabaRefreshError, match="al menos un producto"):
        composition.refresh_alibaba_products([], operation_id="op-empty")
    with SQLiteListingRepository(":memory:") as repository:
        with pytest.raises(TypeError, match="sequence"):
            RefreshTrackedAlibabaProducts(
                repository=repository,
                provider=FakeAlibabaProductRefreshProvider(),
            ).execute("1600000000000", operation_id="op-str")


def test_blank_operation_id_is_rejected() -> None:
    with pytest.raises(AlibabaRefreshError, match="identificador"):
        refresh_operation_query("  ")
    with pytest.raises(AlibabaRefreshError, match="identificador"):
        refresh_operation_query(None)  # type: ignore[arg-type]


def test_product_detail_url_rejects_non_http_and_non_strings() -> None:
    assert is_alibaba_product_detail_url(None) is False
    assert is_alibaba_product_detail_url("  ") is False
    assert is_alibaba_product_detail_url("ftp://www.alibaba.com/product-detail/x.html") is False
    assert is_alibaba_product_detail_url("https://www.alibaba.com/trade/search?x=1") is False
    assert is_alibaba_product_detail_url(
        "https://www.alibaba.com/product-detail/1600000000000.html"
    )


def test_mapper_skips_non_mapping_and_keeps_int_product_id() -> None:
    assert map_xtracto_item("raw") is None
    mapped = map_xtracto_item(
        {
            "productId": 1600000000000,
            "url": "https://www.alibaba.com/product-detail/1600000000000.html",
            "currency": "USD",
            "priceFormatted": "$4.30",
            "ladderPrices": "not-a-list",
            "scrapedAt": "not-a-date",
        }
    )
    assert mapped is not None
    assert mapped.product_id == "1600000000000"
    assert mapped.ladder_prices == ()
    naive = map_xtracto_item(
        {
            "productId": "1600000000000",
            "currency": "USD",
            "scrapedAt": "2026-08-23T15:00:00",
        }
    )
    assert naive is not None
    assert naive.scraped_at is None


def test_malformed_tier_and_string_quantities_are_tolerated() -> None:
    mapped = map_xtracto_item(
        {
            "productId": "1600000000000",
            "currency": "USD",
            "ladderPrices": [
                "skip-me",
                {
                    "minQuantity": "10",
                    "maxQuantity": "49",
                    "price": "4.30",
                    "pricePerUnitUSD": "0",
                },
                {"minQty": 50, "price": Decimal("NaN")},
            ],
        }
    )
    assert mapped is not None
    assert mapped.ladder_prices[0].min_quantity == 10
    assert mapped.ladder_prices[0].max_quantity == 49
    assert mapped.ladder_prices[0].price == Decimal("4.30")
    assert mapped.ladder_prices[0].price_usd is None
    assert mapped.ladder_prices[1].price is None


def test_select_moq_open_ended_and_uncovered_moq() -> None:
    open_ended = LadderTier(
        min_quantity=1000,
        max_quantity=None,
        price=Decimal("3.50"),
        price_formatted=None,
    )
    first = LadderTier(
        min_quantity=1,
        max_quantity=49,
        price=Decimal("4.30"),
        price_formatted=None,
    )
    selected = select_moq_tier((first, open_ended), 1500, use_usd=False)
    assert selected is open_ended
    assert select_moq_tier((first,), 200, use_usd=False) is None
    unpriced = LadderTier(min_quantity=1, max_quantity=10, price=None, price_formatted=None)
    assert select_moq_tier((unpriced,), 1, use_usd=False) is None
    no_mins = LadderTier(
        min_quantity=None, max_quantity=None, price=Decimal("4.30"), price_formatted=None
    )
    assert select_moq_tier((no_mins,), None, use_usd=False) is None


def test_normalize_iso_simple_formatted_price_without_ladder() -> None:
    record = ProductRefreshRecord(
        product_id="1600000000000",
        product_url="https://www.alibaba.com/product-detail/1600000000000.html",
        price_formatted="USD 4.30",
        currency="EUR",
        ladder_prices=(),
        min_order_quantity=None,
        scraped_at=BASE,
    )
    normalized = normalize_refresh_price(record)
    assert normalized is not None
    assert normalized.currency == "EUR"
    assert normalized.currency_evidence == CURRENCY_EVIDENCE_ISO
    assert normalized.tracking_price == Decimal("4.30")
    assert normalized.price_min == normalized.price_max == Decimal("4.30")


def test_normalize_rejects_missing_currency_and_ambiguous_display() -> None:
    missing = ProductRefreshRecord(
        product_id="1600000000000",
        product_url="https://www.alibaba.com/product-detail/x.html",
        price_formatted="$4.30",
        currency="$",
        ladder_prices=(),
        min_order_quantity=1,
        scraped_at=None,
    )
    assert normalize_refresh_price(missing) is None
    ambiguous = ProductRefreshRecord(
        product_id="1600000000000",
        product_url="https://www.alibaba.com/product-detail/x.html",
        price_formatted="$3.50-$4.30",
        currency="USD",
        ladder_prices=(),
        min_order_quantity=1,
        scraped_at=None,
    )
    assert normalize_refresh_price(ambiguous) is None


def test_duplicate_dataset_id_associates_first_match(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    composition = ApplicationComposition(settings=settings)
    composition.follow_alibaba_price(_follow_observation(), clock=_clock(BASE))
    duplicate = _record(product_id="1600000000000", prices=[Decimal("15.25")])
    extra = _record(
        product_id="other",
        product_url="https://www.alibaba.com/product-detail/1600000000000.html",
        prices=[Decimal("99.00")],
    )
    provider = FakeAlibabaProductRefreshProvider([duplicate, extra])
    summary = composition.refresh_alibaba_products(
        ["1600000000000"],
        operation_id="op-dup",
        clock=_clock(BASE + timedelta(hours=1)),
        refresh_provider=provider,
    )
    assert summary.unchanged == 1
    assert provider.calls[0][0].product_id == "1600000000000"


def test_invalid_tracked_url_is_failed_without_provider_call(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    composition = ApplicationComposition(settings=settings)
    bad = AlibabaFollowObservation(
        product_id="1600000000000",
        title="Mouse",
        url="https://example.com/not-alibaba",
        representative_price=Decimal("15.25"),
        currency="USD",
        query="mouse",
        price_display="$15.25",
        min_price=Decimal("15.25"),
        max_price=Decimal("15.25"),
    )
    composition.follow_alibaba_price(bad, clock=_clock(BASE))
    provider = FakeAlibabaProductRefreshProvider([_record()])
    summary = composition.refresh_alibaba_products(
        ["1600000000000"],
        operation_id="op-bad-url",
        clock=_clock(BASE + timedelta(hours=1)),
        refresh_provider=provider,
    )
    assert summary.failed == 1
    assert summary.items[0].status is ProductRefreshStatus.FAILED
    assert provider.calls == []


def test_refresh_client_rejects_blank_actor_and_non_product_sequence() -> None:
    with pytest.raises(ApifyConfigurationError, match="actor id"):
        ApifyAlibabaProductRefreshClient(_api_token="token", actor_id="  ")
    client = ApifyAlibabaProductRefreshClient(
        _api_token="token",
        client_factory=lambda _token: (_ for _ in ()).throw(AssertionError("no call")),
    )
    with pytest.raises(TypeError, match="sequence"):
        client.refresh_products("https://www.alibaba.com/product-detail/x.html")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="TrackedAlibabaProduct"):
        client.refresh_products(["https://www.alibaba.com/product-detail/x.html"])  # type: ignore[list-item]
    empty = client.refresh_products([])
    assert empty.records == ()


class _StatusFakeApify:
    def __init__(
        self,
        run: object,
        items: list[object] | None = None,
        error: Exception | None = None,
        dataset_error: Exception | None = None,
    ) -> None:
        self.run = run
        self.items = items or []
        self.error = error
        self.dataset_error = dataset_error
        self.calls: list[dict[str, object]] = []

    def actor(self, actor_id: str) -> _StatusActor:
        del actor_id
        return _StatusActor(self)

    def dataset(self, dataset_id: str) -> _StatusDataset:
        del dataset_id
        return _StatusDataset(self)


class _StatusActor:
    def __init__(self, owner: _StatusFakeApify) -> None:
        self.owner = owner

    def call(self, *, run_input: dict[str, object]) -> Any:
        self.owner.calls.append(run_input)
        if self.owner.error is not None:
            raise self.owner.error
        return self.owner.run


class _StatusPage:
    def __init__(self, items: list[object]) -> None:
        self.items = items


class _StatusDataset:
    def __init__(self, owner: _StatusFakeApify) -> None:
        self.owner = owner

    def list_items(self, *, limit: int) -> _StatusPage:
        if self.owner.dataset_error is not None:
            raise self.owner.dataset_error
        return _StatusPage(self.owner.items[:limit])


def test_refresh_client_maps_failed_run_and_missing_dataset() -> None:
    product = TrackedAlibabaProduct(
        product_id="1600000000000",
        product_url="https://www.alibaba.com/product-detail/1600000000000.html",
    )
    failed = _StatusFakeApify({"status": "FAILED", "defaultDatasetId": "ds1"})
    with pytest.raises(MarketplaceSourceUnavailable, match="unavailable"):
        ApifyAlibabaProductRefreshClient(
            _api_token="token",
            client_factory=cast(Any, lambda _token: failed),
        ).refresh_products([product])
    missing = _StatusFakeApify({"status": "SUCCEEDED"})
    with pytest.raises(MarketplaceSourceUnavailable, match="unavailable"):
        ApifyAlibabaProductRefreshClient(
            _api_token="token",
            client_factory=cast(Any, lambda _token: missing),
        ).refresh_products([product])
    not_mapping = _StatusFakeApify("SUCCEEDED")
    with pytest.raises(MarketplaceSourceUnavailable, match="unavailable"):
        ApifyAlibabaProductRefreshClient(
            _api_token="token",
            client_factory=cast(Any, lambda _token: not_mapping),
        ).refresh_products([product])
    boom = _StatusFakeApify(
        {"status": "SUCCEEDED", "defaultDatasetId": "ds1"}, error=RuntimeError("net")
    )
    with pytest.raises(MarketplaceSourceUnavailable, match="unavailable"):
        ApifyAlibabaProductRefreshClient(
            _api_token="token",
            client_factory=cast(Any, lambda _token: boom),
        ).refresh_products([product])
    dataset_boom = _StatusFakeApify(
        {"status": "SUCCEEDED", "defaultDatasetId": "ds1"},
        dataset_error=RuntimeError("dataset"),
    )
    with pytest.raises(MarketplaceSourceUnavailable, match="unavailable"):
        ApifyAlibabaProductRefreshClient(
            _api_token="token",
            client_factory=cast(Any, lambda _token: dataset_boom),
        ).refresh_products([product])
    assert failed.calls[0]["productUrls"] == [{"url": product.product_url}]


class _ReplayRepository:
    def get_listing(self, key: ListingKey) -> None:
        del key
        return None

    def get_price_history(self, key: ListingKey) -> list[object]:
        del key
        return []


def test_replay_blank_listing_key_is_failed() -> None:
    result = _replay_item(
        _ReplayRepository(),  # type: ignore[arg-type]
        "   ",
        SearchQuery("alibaba-refresh:op-blank"),
    )
    assert result.status is ProductRefreshStatus.FAILED
    assert "identificador" in result.message


def test_missing_tracked_product_is_failed_without_provider_call(tmp_path: Path) -> None:
    composition = ApplicationComposition(settings=_settings(tmp_path))
    provider = FakeAlibabaProductRefreshProvider([_record()])
    summary = composition.refresh_alibaba_products(
        ["1600999999999"],
        operation_id="op-missing",
        clock=_clock(BASE),
        refresh_provider=provider,
    )
    assert summary.failed == 1
    assert summary.items[0].status is ProductRefreshStatus.FAILED
    assert summary.items[0].message == "Producto no encontrado."
    assert provider.calls == []


def test_replay_not_found_when_peer_was_never_followed(tmp_path: Path) -> None:
    composition = ApplicationComposition(settings=_settings(tmp_path))
    composition.follow_alibaba_price(_follow_observation(), clock=_clock(BASE))
    provider = FakeAlibabaProductRefreshProvider([_record(prices=(Decimal("15.25"),))])
    first = composition.refresh_alibaba_products(
        ["1600000000000"],
        operation_id="op-ghost",
        clock=_clock(BASE + timedelta(hours=1)),
        refresh_provider=provider,
    )
    assert first.unchanged == 1
    replay = composition.refresh_alibaba_products(
        ["1600000000000", "1600000000002"],
        operation_id="op-ghost",
        clock=_clock(BASE + timedelta(hours=2)),
        refresh_provider=provider,
    )
    assert len(provider.calls) == 1
    by_id = {item.product_id: item for item in replay.items}
    assert by_id["1600000000000"].status is ProductRefreshStatus.UNCHANGED
    assert by_id["1600000000002"].status is ProductRefreshStatus.NOT_FOUND


def test_replay_not_found_when_peer_has_no_matching_operation(tmp_path: Path) -> None:
    composition = ApplicationComposition(settings=_settings(tmp_path))
    composition.follow_alibaba_price(_follow_observation(), clock=_clock(BASE))
    composition.follow_alibaba_price(
        _follow_observation(product_id="1600000000002"),
        clock=_clock(BASE),
    )
    provider = FakeAlibabaProductRefreshProvider([_record(prices=(Decimal("15.25"),))])
    composition.refresh_alibaba_products(
        ["1600000000000"],
        operation_id="op-peer",
        clock=_clock(BASE + timedelta(hours=1)),
        refresh_provider=provider,
    )
    replay = composition.refresh_alibaba_products(
        ["1600000000000", "1600000000002"],
        operation_id="op-peer",
        clock=_clock(BASE + timedelta(hours=2)),
        refresh_provider=provider,
    )
    assert len(provider.calls) == 1
    by_id = {item.product_id: item for item in replay.items}
    assert by_id["1600000000000"].status is ProductRefreshStatus.UNCHANGED
    assert by_id["1600000000002"].status is ProductRefreshStatus.NOT_FOUND


def test_replay_unchanged_when_canonical_price_matches(tmp_path: Path) -> None:
    composition = ApplicationComposition(settings=_settings(tmp_path))
    composition.follow_alibaba_price(_follow_observation(), clock=_clock(BASE))
    provider = FakeAlibabaProductRefreshProvider([_record(prices=(Decimal("15.25"),))])
    first = composition.refresh_alibaba_products(
        ["1600000000000"],
        operation_id="op-same-price",
        clock=_clock(BASE + timedelta(hours=1)),
        refresh_provider=provider,
    )
    second = composition.refresh_alibaba_products(
        ["1600000000000"],
        operation_id="op-same-price",
        clock=_clock(BASE + timedelta(hours=2)),
        refresh_provider=provider,
    )
    assert first.unchanged == 1
    assert second.unchanged == 1
    assert len(provider.calls) == 1


def test_url_association_with_mismatched_id_is_identity_mismatch(tmp_path: Path) -> None:
    composition = ApplicationComposition(settings=_settings(tmp_path))
    composition.follow_alibaba_price(_follow_observation(), clock=_clock(BASE))
    url = "https://www.alibaba.com/product-detail/1600000000000.html"
    provider = FakeAlibabaProductRefreshProvider(
        [_record(product_id="not-the-tracked-id", product_url=url, prices=(Decimal("15.25"),))]
    )
    summary = composition.refresh_alibaba_products(
        ["1600000000000"],
        operation_id="op-url-assoc",
        clock=_clock(BASE + timedelta(hours=1)),
        refresh_provider=provider,
    )
    assert summary.identity_mismatch == 1
    assert summary.items[0].status is ProductRefreshStatus.IDENTITY_MISMATCH
    assert provider.calls != []


def test_optional_text_bool_and_int_currency_are_not_iso() -> None:
    bool_record = ProductRefreshRecord(
        product_id="1600000000000",
        product_url="https://www.alibaba.com/product-detail/1600000000000.html",
        price_formatted=True,  # type: ignore[arg-type]
        currency=True,  # type: ignore[arg-type]
        ladder_prices=(),
        min_order_quantity=1,
        scraped_at=None,
    )
    assert normalize_refresh_price(bool_record) is None
    int_currency = ProductRefreshRecord(
        product_id="1600000000000",
        product_url="https://www.alibaba.com/product-detail/1600000000000.html",
        price_formatted="USD 4.30",
        currency=840,  # type: ignore[arg-type]
        ladder_prices=(),
        min_order_quantity=1,
        scraped_at=None,
    )
    assert normalize_refresh_price(int_currency) is None


def test_malformed_nan_infinity_and_invalid_decimals_are_unusable() -> None:
    nan_tier = LadderTier(
        min_quantity=1,
        max_quantity=49,
        price=Decimal("NaN"),
        price_formatted=None,
    )
    inf_tier = LadderTier(
        min_quantity=1,
        max_quantity=49,
        price=Decimal("Infinity"),
        price_formatted=None,
    )
    bool_tier = LadderTier(
        min_quantity=1,
        max_quantity=49,
        price=True,  # type: ignore[arg-type]
        price_formatted=None,
    )
    garbage_tier = LadderTier(
        min_quantity=1,
        max_quantity=49,
        price="not-a-number",  # type: ignore[arg-type]
        price_formatted=None,
    )
    int_tier = LadderTier(
        min_quantity=1,
        max_quantity=49,
        price=4,  # type: ignore[arg-type]
        price_formatted=None,
    )
    usd = "https://www.alibaba.com/product-detail/1600000000000.html"
    for unusable in (nan_tier, inf_tier, bool_tier, garbage_tier):
        record = ProductRefreshRecord(
            product_id="1600000000000",
            product_url=usd,
            price_formatted=None,
            currency="USD",
            ladder_prices=(unusable,),
            min_order_quantity=1,
            scraped_at=None,
        )
        assert normalize_refresh_price(record) is None
    usable = ProductRefreshRecord(
        product_id="1600000000000",
        product_url=usd,
        price_formatted="USD 4.00",
        currency="USD",
        ladder_prices=(int_tier,),
        min_order_quantity=1,
        scraped_at=None,
    )
    normalized = normalize_refresh_price(usable)
    assert normalized is not None
    assert normalized.tracking_price == Decimal("4")


def test_zero_in_formatted_price_is_skipped_and_single_positive_kept() -> None:
    record = ProductRefreshRecord(
        product_id="1600000000000",
        product_url="https://www.alibaba.com/product-detail/1600000000000.html",
        price_formatted="USD 0 4.30",
        currency="USD",
        ladder_prices=(),
        min_order_quantity=1,
        scraped_at=None,
    )
    normalized = normalize_refresh_price(record)
    assert normalized is not None
    assert normalized.tracking_price == Decimal("4.30")
    only_zero = ProductRefreshRecord(
        product_id="1600000000000",
        product_url="https://www.alibaba.com/product-detail/1600000000000.html",
        price_formatted="USD 0",
        currency="USD",
        ladder_prices=(),
        min_order_quantity=1,
        scraped_at=None,
    )
    assert normalize_refresh_price(only_zero) is None


def test_moq_below_all_mins_and_missing_moq_uses_lowest_min() -> None:
    high = LadderTier(
        min_quantity=100,
        max_quantity=200,
        price=Decimal("3.80"),
        price_formatted=None,
    )
    first = LadderTier(
        min_quantity=1,
        max_quantity=49,
        price=Decimal("4.30"),
        price_formatted=None,
    )
    assert select_moq_tier((high,), 1, use_usd=False) is None
    selected = select_moq_tier((high, first), None, use_usd=False)
    assert selected is first
    selected_zero = select_moq_tier((first,), 0, use_usd=False)
    assert selected_zero is first
    uncovered = ProductRefreshRecord(
        product_id="1600000000000",
        product_url="https://www.alibaba.com/product-detail/1600000000000.html",
        price_formatted="$4.30",
        currency="USD",
        ladder_prices=(first,),
        min_order_quantity=5000,
        scraped_at=None,
    )
    assert normalize_refresh_price(uncovered) is None


def test_bytes_product_ids_are_rejected_as_non_sequence(tmp_path: Path) -> None:
    with SQLiteListingRepository(":memory:") as repository:
        with pytest.raises(TypeError, match="sequence"):
            RefreshTrackedAlibabaProducts(
                repository=repository,
                provider=FakeAlibabaProductRefreshProvider(),
            ).execute(b"1600000000000", operation_id="op-bytes")  # type: ignore[arg-type]


def test_refresh_client_bool_optional_text_and_decimal_are_dropped() -> None:
    mapped = map_xtracto_item(
        {
            "productId": True,
            "productUrl": False,
            "currency": True,
            "priceFormatted": True,
            "minOrderQuantity": True,
            "ladderPrices": [
                {
                    "minQuantity": True,
                    "price": True,
                    "pricePerUnitUSD": True,
                },
                {
                    "minQuantity": 10,
                    "price": 4.3,
                    "pricePerUnitUSD": "not-a-number",
                },
            ],
        }
    )
    assert mapped is not None
    assert mapped.product_id is None
    assert mapped.product_url is None
    assert mapped.currency is None
    assert mapped.min_order_quantity is None
    assert mapped.ladder_prices[0].price is None
    assert mapped.ladder_prices[1].price == Decimal("4.3")
    assert mapped.ladder_prices[1].price_usd is None


def test_refresh_client_empty_status_invalid_url_and_error_propagation() -> None:
    product = TrackedAlibabaProduct(
        product_id="1600000000000",
        product_url="https://www.alibaba.com/product-detail/1600000000000.html",
    )
    empty_status = _StatusFakeApify({"status": "  ", "defaultDatasetId": "ds1"})
    with pytest.raises(MarketplaceSourceUnavailable, match="unavailable"):
        ApifyAlibabaProductRefreshClient(
            _api_token="token",
            client_factory=cast(Any, lambda _token: empty_status),
        ).refresh_products([product])
    non_string_status = _StatusFakeApify({"status": 0, "defaultDatasetId": "ds1"})
    with pytest.raises(MarketplaceSourceUnavailable, match="unavailable"):
        ApifyAlibabaProductRefreshClient(
            _api_token="token",
            client_factory=cast(Any, lambda _token: non_string_status),
        ).refresh_products([product])

    def boom_config(_token: str) -> object:
        raise ApifyConfigurationError("refresh token invalid")

    with pytest.raises(ApifyConfigurationError, match="refresh token invalid"):
        ApifyAlibabaProductRefreshClient(
            _api_token="token",
            client_factory=cast(Any, boom_config),
        ).refresh_products([product])

    def boom_unavailable(_token: str) -> object:
        raise MarketplaceSourceUnavailable("Alibaba source is unavailable")

    with pytest.raises(MarketplaceSourceUnavailable, match="unavailable"):
        ApifyAlibabaProductRefreshClient(
            _api_token="token",
            client_factory=cast(Any, boom_unavailable),
        ).refresh_products([product])

    bad_url = TrackedAlibabaProduct(
        product_id="1600000000000",
        product_url="https://example.com/product-detail/1600000000000.html",
    )
    with pytest.raises(ApifyConfigurationError, match="product-detail"):
        ApifyAlibabaProductRefreshClient(
            _api_token="token",
            client_factory=lambda _token: (_ for _ in ()).throw(AssertionError("no call")),
        ).refresh_products([bad_url])

    second = TrackedAlibabaProduct(
        product_id="1600000000001",
        product_url="https://www.alibaba.com/product-detail/1600000000001.html",
    )
    mixed = _StatusFakeApify(
        {"status": "SUCCEEDED", "defaultDatasetId": "ds1"},
        items=["skip", {"productId": "1600000000000", "currency": "USD"}],
    )
    batch = ApifyAlibabaProductRefreshClient(
        _api_token="token",
        client_factory=cast(Any, lambda _token: mixed),
    ).refresh_products([product, second])
    assert len(batch.records) == 1
    assert batch.records[0].product_id == "1600000000000"


def test_gui_refresh_selection_skips_blank_duplicates_and_rejects_bad_counts() -> None:
    assert services.clamp_alibaba_refresh_selection(
        ["  ", "a", "a", "b", 3],  # type: ignore[list-item]
        limit=1,
    ) == ["a"]
    with pytest.raises(ValueError, match="al menos un producto"):
        services.alibaba_refresh_confirmation(0)
    with pytest.raises(ValueError, match="al menos un producto"):
        services.alibaba_refresh_confirmation(True)
    with pytest.raises(ValueError, match="50"):
        services.alibaba_refresh_confirmation(51)


def test_gui_unfollow_and_tracked_row_currency_without_history(tmp_path: Path) -> None:
    from bera_price_tracker.application.alibaba_tracking import (
        AlibabaTrackedProduct,
        AlibabaTrackingVariation,
    )

    settings = _settings(tmp_path)
    composition = ApplicationComposition(settings=settings)
    composition.follow_alibaba_price(_follow_observation(), clock=_clock(BASE))
    row = services.unfollow_alibaba_price(
        "1600000000000",
        settings=settings,
        composition=composition,
    )
    assert row["is_active"] == "0"
    assert row["currency"] == "USD"
    empty = AlibabaTrackedProduct(
        product_id="1600000000001",
        title="Ghost",
        supplier_name=None,
        url="https://www.alibaba.com/product-detail/1600000000001.html",
        is_active=True,
        current_price_display="4.30",
        price_min=None,
        price_max=None,
        last_updated=BASE,
        variation=AlibabaTrackingVariation(
            first_price=Decimal("4.30"),
            last_price=Decimal("4.40"),
            historical_minimum=Decimal("4.30"),
            historical_maximum=Decimal("4.40"),
            snapshot_count=2,
            absolute_change=Decimal("0.10"),
            percentage_change=None,
            baseline_price=Decimal("4.30"),
        ),
        history=(),
    )
    formatted = services.tracked_product_to_row(empty)
    assert formatted["currency"] == ""
    assert formatted["variation"] == "unavailable (unavailable)"
