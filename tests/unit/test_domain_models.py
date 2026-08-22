"""Unit tests for marketplace-independent domain models."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from bera_price_tracker.domain import (
    CollectionBatch,
    CollectionRunInspection,
    Listing,
    ListingKey,
    MarketplaceSource,
    ObservedListing,
    PriceSnapshot,
    SearchQuery,
)


def make_listing(
    *,
    price: Decimal = Decimal("12.50"),
    currency: str = "usd",
    url: str = "https://example.test/listings/MLV-123",
    collected_at: datetime | None = None,
    title: str = "Pastillas de freno BERA",
    seller_name: str | None = "Moto Repuestos",
) -> Listing:
    timestamp = collected_at or datetime(2026, 8, 21, 8, 30, tzinfo=timezone(timedelta(hours=-4)))
    return Listing(
        source=MarketplaceSource.MERCADO_LIBRE,
        external_id=" MLV-123 ",
        title=title,
        price=price,
        currency=currency,
        url=url,
        seller_name=seller_name,
        location="Caracas",
        product_condition="new",
        query=SearchQuery("  pastillas   de freno bera  "),
        collected_at=timestamp,
    )


def test_listing_is_created_with_normalized_values() -> None:
    listing = make_listing()

    assert listing.external_id == "MLV-123"
    assert listing.query.text == "pastillas de freno bera"
    assert listing.currency == "USD"
    assert listing.collected_at == datetime(2026, 8, 21, 12, 30, tzinfo=UTC)
    assert listing.key == ListingKey(MarketplaceSource.MERCADO_LIBRE, "MLV-123")


def test_listing_keeps_money_as_decimal() -> None:
    listing = make_listing(price=Decimal("10.90"))

    assert isinstance(listing.price, Decimal)
    assert listing.price == Decimal("10.90")


def test_listing_rejects_float_price() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        make_listing(price=10.90)  # type: ignore[arg-type]


@pytest.mark.parametrize("price", [Decimal("0"), Decimal("-1"), Decimal("NaN")])
def test_listing_rejects_invalid_decimal_prices(price: Decimal) -> None:
    with pytest.raises(ValueError, match="price"):
        make_listing(price=price)


def test_listing_rejects_invalid_currency() -> None:
    with pytest.raises(ValueError, match="currency"):
        make_listing(currency="US")


def test_listing_rejects_non_http_url() -> None:
    with pytest.raises(ValueError, match="URL"):
        make_listing(url="ftp://example.test/listing")


def test_listing_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        make_listing(collected_at=datetime(2026, 8, 21, 12, 30))


def test_listing_rejects_blank_required_or_optional_text() -> None:
    with pytest.raises(ValueError, match="title"):
        make_listing(title="  ")
    with pytest.raises(ValueError, match="seller_name"):
        make_listing(seller_name="  ")


def test_search_query_and_listing_key_reject_blank_identifiers() -> None:
    with pytest.raises(ValueError, match="text"):
        SearchQuery("  ")
    with pytest.raises(ValueError, match="external_id"):
        ListingKey(MarketplaceSource.MERCADO_LIBRE, "  ")


def test_price_snapshot_contains_only_price_history_fields() -> None:
    listing = make_listing()

    snapshot = PriceSnapshot.from_listing(listing)

    assert snapshot.listing_key == listing.key
    assert snapshot.price == listing.price
    assert snapshot.currency == listing.currency
    assert snapshot.collected_at == listing.collected_at
    assert not hasattr(snapshot, "title")
    assert not hasattr(snapshot, "query")


def test_collection_batch_deduplicates_by_key_with_last_observation_winning() -> None:
    first = make_listing(title="Pastilla vieja", price=Decimal("12.50"))
    last = make_listing(title="Pastilla nueva", price=Decimal("13.75"))

    batch = CollectionBatch.from_listings(
        source=MarketplaceSource.MERCADO_LIBRE,
        query=first.query,
        collected_at=first.collected_at,
        listings=[first, last],
    )

    assert batch.listings == (last,)


def test_collection_batch_accepts_an_empty_observation() -> None:
    collected_at = datetime(2026, 8, 21, 12, 30, tzinfo=UTC)

    batch = CollectionBatch(
        source=MarketplaceSource.MERCADO_LIBRE,
        query=SearchQuery("pastillas bera"),
        collected_at=collected_at,
        listings=(),
    )

    assert batch.collected_at == collected_at
    assert batch.listings == ()


def test_collection_batch_rejects_incoherent_listing_timestamp() -> None:
    listing = make_listing()

    with pytest.raises(ValueError, match="timestamp"):
        CollectionBatch.from_listings(
            source=listing.source,
            query=listing.query,
            collected_at=listing.collected_at + timedelta(seconds=1),
            listings=[listing],
        )


def make_observed_listing(
    *,
    source: MarketplaceSource = MarketplaceSource.MERCADO_LIBRE,
    price: Decimal = Decimal("19.9900"),
    seller_name: str | None = None,
    location: str | None = None,
    product_condition: str | None = None,
) -> ObservedListing:
    return ObservedListing(
        key=ListingKey(source, " MLV-OBSERVED "),
        title=" Pastillas de freno BERA ",
        url="https://example.test/listings/MLV-OBSERVED",
        price=price,
        currency="ves",
        seller_name=seller_name,
        location=location,
        product_condition=product_condition,
    )


def test_observed_listing_is_immutable_and_preserves_exact_decimal() -> None:
    price = Decimal("19.9900")

    observation = make_observed_listing(price=price)

    assert observation.key.external_id == "MLV-OBSERVED"
    assert observation.title == "Pastillas de freno BERA"
    assert observation.price is price
    assert str(observation.price) == "19.9900"
    assert observation.currency == "VES"
    with pytest.raises(FrozenInstanceError):
        observation.price = Decimal("20")  # type: ignore[misc]


def test_observed_listing_supports_absent_optional_metadata() -> None:
    observation = make_observed_listing()

    assert observation.seller_name is None
    assert observation.location is None
    assert observation.product_condition is None


def test_observed_listing_normalizes_present_optional_metadata() -> None:
    observation = make_observed_listing(
        seller_name=" Moto Repuestos ",
        location=" Caracas ",
        product_condition=" new ",
    )

    assert observation.seller_name == "Moto Repuestos"
    assert observation.location == "Caracas"
    assert observation.product_condition == "new"


def test_observed_listing_rejects_float_price() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        make_observed_listing(price=19.99)  # type: ignore[arg-type]


def test_collection_run_inspection_normalizes_timestamp_to_utc() -> None:
    observation = make_observed_listing()
    inspection = CollectionRunInspection(
        source=MarketplaceSource.MERCADO_LIBRE,
        query=SearchQuery("pastillas de freno bera"),
        collected_at=datetime(2026, 8, 21, 12, tzinfo=timezone(timedelta(hours=-4))),
        total_listings=7,
        observations=(observation,),
    )

    assert inspection.collected_at == datetime(2026, 8, 21, 16, tzinfo=UTC)
    assert inspection.total_listings == 7
    assert inspection.observations == (observation,)


def test_collection_run_inspection_accepts_an_empty_run() -> None:
    inspection = CollectionRunInspection(
        source=MarketplaceSource.MERCADO_LIBRE,
        query=SearchQuery("sin resultados"),
        collected_at=datetime(2026, 8, 21, 16, tzinfo=UTC),
        total_listings=0,
        observations=(),
    )

    assert inspection.total_listings == 0
    assert inspection.observations == ()


def test_collection_run_inspection_rejects_total_below_shown_observations() -> None:
    with pytest.raises(ValueError, match="total_listings"):
        CollectionRunInspection(
            source=MarketplaceSource.MERCADO_LIBRE,
            query=SearchQuery("pastillas bera"),
            collected_at=datetime(2026, 8, 21, 16, tzinfo=UTC),
            total_listings=0,
            observations=(make_observed_listing(),),
        )


def test_collection_run_inspection_rejects_an_observation_from_another_source() -> None:
    with pytest.raises(ValueError, match="source"):
        CollectionRunInspection(
            source=MarketplaceSource.MERCADO_LIBRE,
            query=SearchQuery("pastillas bera"),
            collected_at=datetime(2026, 8, 21, 16, tzinfo=UTC),
            total_listings=1,
            observations=(make_observed_listing(source=MarketplaceSource.FACEBOOK_MARKETPLACE),),
        )


def test_collection_run_inspection_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        CollectionRunInspection(
            source=MarketplaceSource.MERCADO_LIBRE,
            query=SearchQuery("pastillas bera"),
            collected_at=datetime(2026, 8, 21, 16),
            total_listings=0,
            observations=(),
        )
