"""Offline tests for Alibaba price-follow persistence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from bera_price_tracker.application.alibaba_tracking import (
    FOLLOW_SOURCE,
    MISSING_PRODUCT_ID,
    REFRESH_QUERY_PREFIX,
    AlibabaFollowError,
    AlibabaFollowObservation,
    FollowAlibabaPrice,
    ListAlibabaTracked,
    RecordAlibabaPriceSnapshot,
    UnfollowAlibabaPrice,
    calculate_alibaba_tracking_variation,
    is_canonical_tracking_observation,
    observation_from_loaded_row,
    percentage_change,
)
from bera_price_tracker.composition import ApplicationComposition
from bera_price_tracker.config import Settings
from bera_price_tracker.domain import (
    CollectionBatch,
    Listing,
    ListingKey,
    MarketplaceSource,
    PriceObservation,
    SearchQuery,
)
from bera_price_tracker.gui import services
from bera_price_tracker.infrastructure.persistence import SQLiteListingRepository

BASE = datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC)
SRC = Path(__file__).resolve().parents[2] / "src"


def _settings(tmp_path: Path) -> Settings:
    return replace(Settings.from_env(), database_path=str(tmp_path / "tracker.db"))


def _observation(
    *,
    product_id: str = "1600000000000",
    price: Decimal = Decimal("1.45"),
    minimum: Decimal = Decimal("1.30"),
    maximum: Decimal = Decimal("1.60"),
    display: str = "$1.30-1.60",
    title: str = "Wireless Mouse",
    query: str = "wireless mouse",
) -> AlibabaFollowObservation:
    return AlibabaFollowObservation(
        product_id=product_id,
        title=title,
        url=f"https://www.alibaba.com/product-detail/{product_id}.html",
        representative_price=price,
        currency="USD",
        query=query,
        price_display=display,
        min_price=minimum,
        max_price=maximum,
        supplier_name="Example Electronics Co., Ltd.",
        supplier_country="CN",
    )


def _clock(moment: datetime) -> Callable[[], datetime]:
    return lambda: moment


def test_follow_saves_listing_and_initial_snapshot(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    composition = ApplicationComposition(settings=settings)
    tracked = composition.follow_alibaba_price(_observation(), clock=_clock(BASE))

    assert tracked.product_id == "1600000000000"
    assert tracked.variation.snapshot_count == 1
    assert tracked.variation.first_price == Decimal("1.45")
    assert tracked.variation.last_price == Decimal("1.45")
    assert tracked.is_active is True
    assert tracked.current_price_display == "$1.30-1.60"
    assert tracked.last_updated == BASE
    assert tracked.last_updated.tzinfo is not None

    with SQLiteListingRepository(settings.database_path) as repository:
        assert repository.count_listings() == 1
        assert repository.count_price_snapshots() == 1
        stored = repository.get_listing(ListingKey(FOLLOW_SOURCE, "1600000000000"))
        assert stored is not None
        assert stored.key.source is MarketplaceSource.ALIBABA
        assert stored.price_min == Decimal("1.30")
        assert stored.price_max == Decimal("1.60")
        assert stored.price_display == "$1.30-1.60"


def test_product_id_is_the_stable_identity() -> None:
    key = ListingKey(MarketplaceSource.ALIBABA, "1600000000000")
    listing = Listing(
        source=MarketplaceSource.ALIBABA,
        external_id="1600000000000",
        title="Wireless Mouse",
        price=Decimal("1.45"),
        currency="USD",
        url="https://www.alibaba.com/product-detail/1600000000000.html",
        query=SearchQuery("wireless mouse"),
        collected_at=BASE,
    )
    assert listing.key == key
    assert listing.external_id == "1600000000000"


def test_follow_without_product_id_is_rejected() -> None:
    with pytest.raises(AlibabaFollowError, match="identificador"):
        observation_from_loaded_row(
            {
                "title": "Mouse",
                "url": "https://www.alibaba.com/product-detail/x.html",
                "representative": "1.45",
            },
            "mouse",
        )


def test_range_uses_representative_for_history_and_keeps_bounds(tmp_path: Path) -> None:
    composition = ApplicationComposition(settings=_settings(tmp_path))
    tracked = composition.follow_alibaba_price(_observation(), clock=_clock(BASE))
    assert tracked.price_min == Decimal("1.30")
    assert tracked.price_max == Decimal("1.60")
    assert tracked.variation.first_price == Decimal("1.45")
    assert tracked.history[0].price == Decimal("1.45")


def test_follow_is_idempotent_when_already_active(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    composition = ApplicationComposition(settings=settings)
    first = composition.follow_alibaba_price(_observation(), clock=_clock(BASE))
    second = composition.follow_alibaba_price(
        _observation(),
        clock=_clock(BASE + timedelta(hours=1)),
    )
    assert first.variation.snapshot_count == 1
    assert second.variation.snapshot_count == 1
    with SQLiteListingRepository(settings.database_path) as repository:
        assert repository.count_listings() == 1
        assert repository.count_price_snapshots() == 1


def test_second_snapshot_updates_variation(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    composition = ApplicationComposition(settings=settings)
    composition.follow_alibaba_price(_observation(), clock=_clock(BASE))
    later = composition.record_alibaba_price_snapshot(
        _observation(price=Decimal("1.60"), minimum=Decimal("1.50"), maximum=Decimal("1.70")),
        clock=_clock(BASE + timedelta(days=1)),
    )
    assert later.variation.snapshot_count == 2
    assert later.variation.first_price == Decimal("1.45")
    assert later.variation.last_price == Decimal("1.60")
    assert later.variation.absolute_change == Decimal("0.15")
    assert later.variation.percentage_change == Decimal("0.15") / Decimal("1.45") * Decimal("100")
    assert later.variation.historical_minimum == Decimal("1.45")
    assert later.variation.historical_maximum == Decimal("1.60")
    assert later.last_updated == BASE + timedelta(days=1)
    assert later.last_updated.tzinfo is not None


def test_percentage_unavailable_when_previous_is_zero() -> None:
    assert percentage_change(Decimal("5"), Decimal("0")) is None
    assert percentage_change(Decimal("5"), Decimal("10")) == Decimal("50")


def test_variation_uses_decimal_not_float() -> None:
    text = (SRC / "bera_price_tracker" / "application" / "alibaba_tracking.py").read_text(
        encoding="utf-8"
    )
    assert "float(" not in text
    assert "Decimal" in text


def test_alibaba_and_facebook_identities_do_not_collide(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    composition = ApplicationComposition(settings=settings)
    composition.follow_alibaba_price(_observation(product_id="1600000000000"), clock=_clock(BASE))
    facebook = Listing(
        source=MarketplaceSource.FACEBOOK_MARKETPLACE,
        external_id="1600000000000",
        title="Facebook listing",
        price=Decimal("19.99"),
        currency="USD",
        url="https://www.facebook.com/marketplace/item/1600000000000",
        query=SearchQuery("mouse"),
        collected_at=BASE,
    )
    with SQLiteListingRepository(settings.database_path) as repository:
        repository.record_collection(
            CollectionBatch.from_listings(
                source=facebook.source,
                query=facebook.query,
                collected_at=facebook.collected_at,
                listings=(facebook,),
            )
        )
        assert repository.count_listings() == 2
        alibaba = repository.get_listing(ListingKey(MarketplaceSource.ALIBABA, "1600000000000"))
        other = repository.get_listing(
            ListingKey(MarketplaceSource.FACEBOOK_MARKETPLACE, "1600000000000")
        )
        assert alibaba is not None and other is not None
        assert alibaba.title == "Wireless Mouse"
        assert other.title == "Facebook listing"


def test_unfollow_preserves_history(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    composition = ApplicationComposition(settings=settings)
    composition.follow_alibaba_price(_observation(), clock=_clock(BASE))
    composition.record_alibaba_price_snapshot(
        _observation(price=Decimal("1.60")),
        clock=_clock(BASE + timedelta(days=1)),
    )
    inactive = composition.unfollow_alibaba_price("1600000000000")
    assert inactive.is_active is False
    assert inactive.variation.snapshot_count == 2
    assert [item.product_id for item in composition.list_alibaba_tracked()] == []
    remaining = composition.list_alibaba_tracked(active_only=False)
    assert len(remaining) == 1
    assert remaining[0].variation.snapshot_count == 2
    with SQLiteListingRepository(settings.database_path) as repository:
        assert repository.count_price_snapshots() == 2
        stored = repository.get_listing(ListingKey(FOLLOW_SOURCE, "1600000000000"))
        assert stored is not None
        assert stored.is_active is False


def test_refollow_after_unfollow_reactivates(tmp_path: Path) -> None:
    composition = ApplicationComposition(settings=_settings(tmp_path))
    composition.follow_alibaba_price(_observation(), clock=_clock(BASE))
    composition.unfollow_alibaba_price("1600000000000")
    again = composition.follow_alibaba_price(
        _observation(price=Decimal("1.70")),
        clock=_clock(BASE + timedelta(days=2)),
    )
    assert again.is_active is True
    assert again.variation.snapshot_count == 2


def test_search_does_not_auto_follow(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    from bera_price_tracker.domain.alibaba import AlibabaProduct

    class FakeSearch:
        def execute(self, query: str, limit: int) -> list[AlibabaProduct]:
            del query, limit
            return [
                AlibabaProduct(
                    title="Wireless Mouse",
                    product_id="1600000000000",
                    product_url="https://www.alibaba.com/product-detail/1600000000000.html",
                    price_display="$1.38",
                    min_price=Decimal("1.38"),
                    max_price=Decimal("1.38"),
                    currency="USD",
                    supplier_name="Example Electronics Co., Ltd.",
                    supplier_country="CN",
                )
            ]

    payload = services.run_alibaba_search(
        "wireless mouse",
        10,
        search_service=FakeSearch(),
    )
    assert payload["results"][0]["product_id"] == "1600000000000"
    with SQLiteListingRepository(settings.database_path) as repository:
        assert repository.count_listings() == 0


def test_gui_follow_goes_through_application_service(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    composition = ApplicationComposition(settings=settings)
    row = services.follow_alibaba_price(
        {
            "product_id": "1600000000000",
            "title": "Wireless Mouse",
            "url": "https://www.alibaba.com/product-detail/1600000000000.html",
            "representative": "1.45",
            "price": "$1.30-1.60",
            "price_min": "1.30",
            "price_max": "1.60",
            "currency": "USD",
            "supplier_name": "Example Electronics Co., Ltd.",
            "supplier_country": "CN",
        },
        "wireless mouse",
        settings=settings,
        clock=_clock(BASE),
        composition=composition,
    )
    assert row["product_id"] == "1600000000000"
    assert row["first_price"] == "$1.45"
    assert "UTC" in row["last_updated"]
    listed = services.list_alibaba_tracked(settings=settings, composition=composition)
    assert [item["product_id"] for item in listed] == ["1600000000000"]


def test_gui_modules_do_not_write_sqlite_directly() -> None:
    gui = SRC / "bera_price_tracker" / "gui"
    for name in ("state.py", "views.py", "analysis.py", "services.py"):
        text = (gui / name).read_text(encoding="utf-8")
        assert "sqlite3" not in text
        assert "SQLiteListingRepository" not in text


def test_tracking_module_has_no_network_imports() -> None:
    text = (SRC / "bera_price_tracker" / "application" / "alibaba_tracking.py").read_text(
        encoding="utf-8"
    )
    for banned in ("requests", "apify", "httpx", "urllib", "socket"):
        assert banned not in text


def test_service_classes_use_repository_not_sqlite() -> None:
    with SQLiteListingRepository(":memory:") as repository:
        follow = FollowAlibabaPrice(repository=repository, clock=_clock(BASE))
        tracked = follow.execute(_observation())
        assert tracked.variation.snapshot_count == 1
        RecordAlibabaPriceSnapshot(
            repository=repository,
            clock=_clock(BASE + timedelta(hours=2)),
        ).execute(_observation(price=Decimal("1.80")))
        UnfollowAlibabaPrice(repository=repository).execute("1600000000000")
        active = ListAlibabaTracked(repository=repository).execute()
        assert active == []
        all_rows = ListAlibabaTracked(repository=repository).execute(active_only=False)
        assert all_rows[0].variation.snapshot_count == 2
        assert all_rows[0].variation.absolute_change == Decimal("0.35")


def test_missing_product_id_constant() -> None:
    assert "identificador" in MISSING_PRODUCT_ID


def _price_observation(
    price: str,
    *,
    query: str = "wireless mouse",
    minimum: str | None = None,
    maximum: str | None = None,
    at: datetime = BASE,
) -> PriceObservation:
    return PriceObservation(
        price=Decimal(price),
        currency="USD",
        collected_at=at,
        query=SearchQuery(query),
        price_min=None if minimum is None else Decimal(minimum),
        price_max=None if maximum is None else Decimal(maximum),
    )


def test_simple_discovery_price_is_canonical() -> None:
    assert is_canonical_tracking_observation(
        _price_observation("4.30", minimum="4.30", maximum="4.30")
    )
    assert is_canonical_tracking_observation(_price_observation("4.30"))


def test_range_discovery_midpoint_is_provisional() -> None:
    provisional = _price_observation("98.70", minimum="89.20", maximum="108.20")
    assert not is_canonical_tracking_observation(provisional)
    variation = calculate_alibaba_tracking_variation([provisional])
    assert variation.baseline_price is None
    assert variation.absolute_change is None
    assert variation.percentage_change is None


def test_refresh_observation_is_canonical_even_with_range() -> None:
    canonical = _price_observation(
        "108.20",
        query=f"{REFRESH_QUERY_PREFIX}op-1",
        minimum="89.20",
        maximum="108.20",
    )
    assert is_canonical_tracking_observation(canonical)


def test_first_canonical_after_provisional_has_no_variation() -> None:
    """Regression 1601769395876: discovery 98.70 + canonical 108.20 must not
    report +9.63%; the canonical observation establishes the baseline."""

    provisional = _price_observation("98.70", minimum="89.20", maximum="108.20")
    canonical = _price_observation(
        "108.20",
        query=f"{REFRESH_QUERY_PREFIX}op-1",
        minimum="89.20",
        maximum="108.20",
        at=BASE + timedelta(hours=1),
    )
    variation = calculate_alibaba_tracking_variation([provisional, canonical])
    assert variation.first_price == Decimal("98.70")
    assert variation.baseline_price == Decimal("108.20")
    assert variation.last_price == Decimal("108.20")
    assert variation.absolute_change is None
    assert variation.percentage_change is None
    assert variation.historical_minimum == Decimal("108.20")
    assert variation.historical_maximum == Decimal("108.20")
    assert variation.snapshot_count == 2


def test_two_canonical_observations_compare_between_themselves() -> None:
    provisional = _price_observation("98.70", minimum="89.20", maximum="108.20")
    first = _price_observation(
        "108.20", query=f"{REFRESH_QUERY_PREFIX}op-1", at=BASE + timedelta(hours=1)
    )
    second = _price_observation(
        "105", query=f"{REFRESH_QUERY_PREFIX}op-2", at=BASE + timedelta(hours=2)
    )
    variation = calculate_alibaba_tracking_variation([provisional, first, second])
    assert variation.baseline_price == Decimal("108.20")
    assert variation.last_price == Decimal("105")
    assert variation.absolute_change == Decimal("-3.20")
    assert variation.percentage_change is not None
    assert variation.percentage_change.quantize(Decimal("0.01")) == Decimal("-2.96")
    assert variation.historical_minimum == Decimal("105")
    assert variation.historical_maximum == Decimal("108.20")


def test_canonical_min_max_ignore_provisional_midpoint() -> None:
    provisional = _price_observation("2.00", minimum="1.00", maximum="3.00")
    first = _price_observation(
        "3.00", query=f"{REFRESH_QUERY_PREFIX}op-1", at=BASE + timedelta(hours=1)
    )
    second = _price_observation(
        "2.80", query=f"{REFRESH_QUERY_PREFIX}op-2", at=BASE + timedelta(hours=2)
    )
    variation = calculate_alibaba_tracking_variation([provisional, first, second])
    assert variation.historical_minimum == Decimal("2.80")
    assert variation.historical_maximum == Decimal("3.00")


def test_provisional_only_history_keeps_midpoint_comparison() -> None:
    """Discovery midpoints share the same semantics, so the legacy comparison
    between them is preserved while no canonical observation exists."""

    first = _price_observation("1.45", minimum="1.30", maximum="1.60")
    second = _price_observation("1.60", minimum="1.50", maximum="1.70", at=BASE + timedelta(days=1))
    variation = calculate_alibaba_tracking_variation([first, second])
    assert variation.baseline_price is None
    assert variation.absolute_change == Decimal("0.15")


def test_simple_follow_price_is_the_baseline(tmp_path: Path) -> None:
    composition = ApplicationComposition(settings=_settings(tmp_path))
    tracked = composition.follow_alibaba_price(
        _observation(
            price=Decimal("4.30"),
            minimum=Decimal("4.30"),
            maximum=Decimal("4.30"),
            display="$4.30",
        ),
        clock=_clock(BASE),
    )
    assert tracked.variation.baseline_price == Decimal("4.30")
    assert tracked.variation.absolute_change is None


def test_range_follow_has_no_baseline_yet(tmp_path: Path) -> None:
    composition = ApplicationComposition(settings=_settings(tmp_path))
    tracked = composition.follow_alibaba_price(_observation(), clock=_clock(BASE))
    assert tracked.variation.baseline_price is None
    assert tracked.variation.first_price == Decimal("1.45")
