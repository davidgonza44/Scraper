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
    MISSING_CURRENCY,
    MISSING_PRICE,
    MISSING_PRODUCT_ID,
    MISSING_TITLE,
    MISSING_URL,
    REFRESH_QUERY_PREFIX,
    UNKNOWN_LISTING,
    AlibabaFollowError,
    AlibabaFollowObservation,
    AlibabaTrackedProduct,
    FollowAlibabaPrice,
    ListAlibabaTracked,
    RecordAlibabaPriceSnapshot,
    UnfollowAlibabaPrice,
    alibaba_listing_key,
    calculate_alibaba_tracking_variation,
    history_from_repository,
    is_canonical_tracking_observation,
    observation_from_loaded_row,
    percentage_change,
    tracked_product_from_repository,
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
from bera_price_tracker.domain.models import PriceSnapshot
from bera_price_tracker.gui import services
from bera_price_tracker.infrastructure.persistence import (
    SQLiteListingRepository,
    StoredListing,
    StoredPriceObservation,
)

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
                "currency": "USD",
            },
            "mouse",
        )


def test_follow_without_currency_is_rejected(tmp_path: Path) -> None:
    row = {
        "product_id": "1600000000000",
        "title": "Mouse",
        "url": "https://www.alibaba.com/product-detail/1600000000000.html",
        "representative": "1.45",
        "price": "$1.45",
    }
    with pytest.raises(AlibabaFollowError, match=MISSING_CURRENCY):
        observation_from_loaded_row(row, "mouse")
    settings = _settings(tmp_path)
    composition = ApplicationComposition(settings=settings)
    with pytest.raises(AlibabaFollowError, match=MISSING_CURRENCY):
        services.follow_alibaba_price(row, "mouse", settings=settings, composition=composition)
    with SQLiteListingRepository(settings.database_path) as repository:
        assert repository.count_listings() == 0
        assert repository.count_price_snapshots() == 0


def test_follow_with_explicit_usd_still_works() -> None:
    observation = observation_from_loaded_row(
        {
            "product_id": "1600000000000",
            "title": "Mouse",
            "url": "https://www.alibaba.com/product-detail/1600000000000.html",
            "representative": "1.45",
            "price": "$1.45",
            "currency": "USD",
        },
        "mouse",
    )
    assert observation.currency == "USD"
    assert observation.representative_price == Decimal("1.45")


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


def test_tracked_price_decrease_renders_as_negative_known_amount() -> None:
    provisional = _price_observation("98.70", minimum="89.20", maximum="108.20")
    first = _price_observation(
        "108.20", query=f"{REFRESH_QUERY_PREFIX}op-1", at=BASE + timedelta(hours=1)
    )
    second = _price_observation(
        "105", query=f"{REFRESH_QUERY_PREFIX}op-2", at=BASE + timedelta(hours=2)
    )
    history = (provisional, first, second)
    variation = calculate_alibaba_tracking_variation(list(history))
    assert variation.absolute_change == Decimal("-3.20")
    tracked = AlibabaTrackedProduct(
        product_id="1600000000000",
        title="Wireless Mouse",
        supplier_name="Example Electronics Co., Ltd.",
        url="https://www.alibaba.com/product-detail/1600000000000.html",
        is_active=True,
        current_price_display="$105.00",
        price_min=Decimal("105"),
        price_max=Decimal("105"),
        last_updated=BASE + timedelta(hours=2),
        variation=variation,
        history=history,
    )
    row = services.tracked_product_to_row(tracked)
    assert row["variation"].startswith("$-3.20")
    assert "unavailable" not in row["variation"]
    assert row["last_price"] == "$105.00"


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


def test_follow_rejects_missing_title_url_and_unusable_price() -> None:
    base = {
        "product_id": "1600000000000",
        "title": "Mouse",
        "url": "https://www.alibaba.com/product-detail/1600000000000.html",
        "representative": "1.45",
        "currency": "USD",
    }
    with pytest.raises(AlibabaFollowError, match=MISSING_TITLE):
        observation_from_loaded_row({**base, "title": "  "}, "mouse")
    with pytest.raises(AlibabaFollowError, match=MISSING_URL):
        observation_from_loaded_row({**base, "url": ""}, "mouse")
    with pytest.raises(AlibabaFollowError, match=MISSING_PRICE):
        observation_from_loaded_row({**base, "representative": "not-a-price"}, "mouse")
    with pytest.raises(AlibabaFollowError, match=MISSING_PRICE):
        observation_from_loaded_row({**base, "representative": "0"}, "mouse")
    with pytest.raises(AlibabaFollowError, match=MISSING_PRICE):
        observation_from_loaded_row({**base, "representative": True}, "mouse")
    with pytest.raises(AlibabaFollowError, match=MISSING_PRICE):
        observation_from_loaded_row({**base, "representative": 145}, "mouse")
    with pytest.raises(AlibabaFollowError, match=MISSING_CURRENCY):
        observation_from_loaded_row({**base, "currency": "$"}, "mouse")
    with pytest.raises(AlibabaFollowError, match=MISSING_PRODUCT_ID):
        alibaba_listing_key("  ")


def test_follow_and_record_reject_non_observation() -> None:
    with pytest.raises(TypeError, match="AlibabaFollowObservation"):
        FollowAlibabaPrice(repository=_EmptyRepo()).execute("obs")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="AlibabaFollowObservation"):
        RecordAlibabaPriceSnapshot(repository=_EmptyRepo()).execute("obs")  # type: ignore[arg-type]


def test_empty_history_and_non_decimal_variation_are_rejected() -> None:
    with pytest.raises(AlibabaFollowError, match="snapshots"):
        calculate_alibaba_tracking_variation([])
    with pytest.raises(TypeError, match="Decimal"):
        percentage_change(0.15, Decimal("1.45"))  # type: ignore[arg-type]


def test_simple_follow_without_display_falls_back_to_last_price(tmp_path: Path) -> None:
    observation = AlibabaFollowObservation(
        product_id="1600000000000",
        title="Wireless Mouse",
        url="https://www.alibaba.com/product-detail/1600000000000.html",
        representative_price=Decimal("4.30"),
        currency="EUR",
        query="wireless mouse",
        price_display=None,
        min_price=Decimal("4.30"),
        max_price=Decimal("4.30"),
    )
    tracked = ApplicationComposition(settings=_settings(tmp_path)).follow_alibaba_price(
        observation,
        clock=_clock(BASE),
    )
    assert tracked.current_price_display == "4.30"
    assert tracked.variation.last_price == Decimal("4.30")
    assert tracked.history[0].currency == "EUR"


def test_repeated_unfollow_keeps_history_and_unknown_id_fails(tmp_path: Path) -> None:
    composition = ApplicationComposition(settings=_settings(tmp_path))
    composition.follow_alibaba_price(_observation(), clock=_clock(BASE))
    first = composition.unfollow_alibaba_price("1600000000000")
    second = composition.unfollow_alibaba_price("1600000000000")
    assert first.is_active is False
    assert second.is_active is False
    assert second.variation.snapshot_count == 1
    with pytest.raises(AlibabaFollowError, match=UNKNOWN_LISTING):
        composition.unfollow_alibaba_price("missing-id")
    with pytest.raises(AlibabaFollowError, match=UNKNOWN_LISTING):
        UnfollowAlibabaPrice(repository=_EmptyRepo()).execute("1600000000000")


def test_persistence_readback_failure_is_fail_closed() -> None:
    repo = _WriteWithoutReadRepo()
    with pytest.raises(AlibabaFollowError, match="guardar"):
        FollowAlibabaPrice(repository=repo, clock=_clock(BASE)).execute(_observation())
    assert repo.wrote is True


def test_persistence_error_propagates_without_silent_follow() -> None:
    repo = _ExplodingWriteRepo()
    with pytest.raises(RuntimeError, match="disk full"):
        FollowAlibabaPrice(repository=repo, clock=_clock(BASE)).execute(_observation())


def test_list_skips_keys_without_snapshots() -> None:
    repo = _KeysWithoutHistoryRepo()
    listed = ListAlibabaTracked(repository=repo).execute(active_only=False)
    assert listed == []
    assert history_from_repository(repo, ListingKey(FOLLOW_SOURCE, "ghost")) is None
    assert tracked_product_from_repository(repo, ListingKey(FOLLOW_SOURCE, "ghost")) is None


def test_unfollow_readback_failure_is_unknown_listing() -> None:
    class _DeactivateWithoutRead(_EmptyRepo):
        def set_listing_active(self, key: ListingKey, active: bool) -> bool:
            del key, active
            return True

    with pytest.raises(AlibabaFollowError, match=UNKNOWN_LISTING):
        UnfollowAlibabaPrice(repository=_DeactivateWithoutRead()).execute("1600000000000")


class _EmptyRepo:
    def record_collection(self, batch: object) -> None:
        del batch

    def get_listing(self, key: ListingKey) -> object | None:
        del key
        return None

    def get_price_history(self, key: ListingKey) -> list[object]:
        del key
        return []

    def set_listing_active(self, key: ListingKey, active: bool) -> bool:
        del key, active
        return False

    def list_listing_keys(
        self, source: MarketplaceSource, *, active_only: bool = False
    ) -> list[ListingKey]:
        del source, active_only
        return []


class _WriteWithoutReadRepo(_EmptyRepo):
    def __init__(self) -> None:
        self.wrote = False

    def record_collection(self, batch: object) -> None:
        del batch
        self.wrote = True


class _ExplodingWriteRepo(_EmptyRepo):
    def record_collection(self, batch: object) -> None:
        del batch
        raise RuntimeError("disk full")


class _KeysWithoutHistoryRepo(_EmptyRepo):
    def list_listing_keys(
        self, source: MarketplaceSource, *, active_only: bool = False
    ) -> list[ListingKey]:
        del source, active_only
        return [ListingKey(FOLLOW_SOURCE, "ghost")]


def test_observation_accepts_decimal_representative() -> None:
    observation = observation_from_loaded_row(
        {
            "product_id": "1600000000000",
            "title": "Mouse",
            "url": "https://www.alibaba.com/product-detail/1600000000000.html",
            "representative": Decimal("1.45"),
            "price_min": Decimal("1.45"),
            "price_max": Decimal("1.45"),
            "currency": "USD",
        },
        "mouse",
    )
    assert observation.representative_price == Decimal("1.45")
    assert observation.min_price == Decimal("1.45")
    assert observation.max_price == Decimal("1.45")


class _ActiveListingWithoutSnapshots(_EmptyRepo):
    def __init__(self) -> None:
        self.wrote = False
        self._history: list[StoredPriceObservation] = []
        self.listing = StoredListing(
            id=1,
            key=ListingKey(FOLLOW_SOURCE, "1600000000000"),
            title="Existing mouse",
            url="https://www.alibaba.com/product-detail/1600000000000.html",
            seller_name=None,
            location=None,
            product_condition=None,
            first_seen_at=BASE,
            last_seen_at=BASE,
            is_active=True,
        )

    def get_listing(self, key: ListingKey) -> StoredListing | None:
        return self.listing if key == self.listing.key else None

    def get_price_history(self, key: ListingKey) -> list[object]:
        del key
        return list(self._history)

    def record_collection(self, batch: object) -> None:
        self.wrote = True
        listing = batch.listings[0]  # type: ignore[attr-defined]
        self._history = [
            StoredPriceObservation(
                collection_run_id=1,
                query=listing.query,
                snapshot=PriceSnapshot(
                    listing_key=listing.key,
                    price=listing.price,
                    currency=listing.currency,
                    collected_at=listing.collected_at,
                    price_min=listing.price_min,
                    price_max=listing.price_max,
                ),
            )
        ]

    def set_listing_active(self, key: ListingKey, active: bool) -> bool:
        del key, active
        return True


def test_active_listing_without_snapshots_records_first_price() -> None:
    repo = _ActiveListingWithoutSnapshots()
    tracked = FollowAlibabaPrice(repository=repo, clock=_clock(BASE)).execute(_observation())
    assert repo.wrote is True
    assert tracked.product_id == "1600000000000"
    assert tracked.variation.snapshot_count == 1
    assert tracked.variation.last_price == Decimal("1.45")
