"""Offline tests for Alibaba product-detail refresh. No Actor runs."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

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
    RefreshTrackedAlibabaProducts,
    TrackedAlibabaProduct,
    is_alibaba_product_detail_url,
    normalize_refresh_price,
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
from bera_price_tracker.domain import ListingKey, MarketplaceSource
from bera_price_tracker.gui import services
from bera_price_tracker.infrastructure.persistence import SQLiteListingRepository
from bera_price_tracker.infrastructure.providers.alibaba_refresh import (
    ApifyAlibabaProductRefreshClient,
    build_alibaba_refresh_run_input,
    map_xtracto_item,
)

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
    minimum: Decimal = Decimal("12.50"),
    maximum: Decimal = Decimal("18.00"),
    display: str = "$12.50 - $18.00",
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
