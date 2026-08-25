"""Offline generic Facebook Marketplace product-search tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

import pytest

from bera_price_tracker.application.facebook_products import (
    FacebookPriceDecision,
    FacebookProductSearchMetrics,
    FacebookProductSearchResult,
    FacebookRejectionReason,
    SearchFacebookMarketplaceProducts,
    classify_explicit_facebook_price,
    is_explicitly_priced_listing,
    validate_facebook_product_search,
)
from bera_price_tracker.application.facebook_statistics import (
    calculate_facebook_statistics_by_currency,
)
from bera_price_tracker.application.ports import FacebookMarketplaceProductSearchProvider
from bera_price_tracker.domain import Listing, MarketplaceSource, SearchQuery
from bera_price_tracker.infrastructure.providers.apify import (
    ApifyFacebookListing,
    ApifyFacebookMarketplaceClient,
    ApifyFacebookResult,
    map_apify_item,
)
from bera_price_tracker.infrastructure.providers.facebook_products import (
    FacebookMarketplaceProductSearch,
)

COLLECTED_AT = datetime(2026, 8, 25, 1, 0, tzinfo=UTC)


@dataclass
class FakeFacebookClient:
    result: ApifyFacebookResult
    calls: list[tuple[str, str, int]]

    def fetch(self, keyword: str, city: str, limit: int) -> ApifyFacebookResult:
        self.calls.append((keyword, city, limit))
        return self.result


def _record(
    *,
    product_id: str | None = "1",
    title: str | None = "Wireless mouse",
    price: Decimal | None = Decimal("10"),
    currency: str | None = "USD",
    formatted_price: str | None = "$10",
    location: str | None = "Caracas",
    url: str | None = "https://www.facebook.com/marketplace/item/1",
) -> ApifyFacebookListing:
    return ApifyFacebookListing(
        product_id=product_id,
        title=title,
        price=price,
        currency=currency,
        formatted_price=formatted_price,
        location=location,
        url=url,
    )


def _search(
    *records: ApifyFacebookListing, source_errors: int = 0
) -> tuple[FacebookProductSearchResult, FakeFacebookClient]:
    fake = FakeFacebookClient(
        ApifyFacebookResult(
            records=records,
            fetched=len(records) + source_errors,
            source_errors=source_errors,
        ),
        [],
    )
    provider = FacebookMarketplaceProductSearch(
        cast(ApifyFacebookMarketplaceClient, fake),
        clock=lambda: COLLECTED_AT,
    )
    result = SearchFacebookMarketplaceProducts(
        cast(FacebookMarketplaceProductSearchProvider, provider)
    ).execute("wireless mouse", "caracas", 5)
    return result, fake


@pytest.mark.parametrize(
    ("amount", "formatted", "expected"),
    [
        (Decimal("10"), "$10", FacebookPriceDecision.PRICED),
        (Decimal("0"), "Free", FacebookPriceDecision.FREE_PRICE),
        (None, "Free", FacebookPriceDecision.FREE_PRICE),
        (Decimal("10"), "Free", FacebookPriceDecision.FREE_PRICE),
        (Decimal("10"), "Gratis", FacebookPriceDecision.FREE_PRICE),
        (Decimal("10"), "Gratuito", FacebookPriceDecision.FREE_PRICE),
        (Decimal("10"), "Gratuita", FacebookPriceDecision.FREE_PRICE),
        (Decimal("10"), "Sin costo", FacebookPriceDecision.FREE_PRICE),
        (Decimal("10"), "Envío gratis", FacebookPriceDecision.PRICED),
        (Decimal("-5"), "-5", FacebookPriceDecision.INVALID_PRICE),
        (Decimal("NaN"), "NaN", FacebookPriceDecision.INVALID_PRICE),
        (Decimal("Infinity"), "Infinity", FacebookPriceDecision.INVALID_PRICE),
        (Decimal("10"), "$0.00", FacebookPriceDecision.INVALID_PRICE),
        (None, "$25", FacebookPriceDecision.INVALID_PRICE),
    ],
)
def test_explicit_price_policy(
    amount: Decimal | None,
    formatted: str,
    expected: FacebookPriceDecision,
) -> None:
    assert classify_explicit_facebook_price(amount, formatted) is expected
    assert is_explicitly_priced_listing(amount, formatted) is (
        expected is FacebookPriceDecision.PRICED
    )


def test_mapper_never_reconstructs_amount_from_formatted_text() -> None:
    mapped = map_apify_item(
        {
            "id": "1",
            "marketplace_listing_title": "Pump",
            "listing_price": {"amount": None, "formatted_amount": "$25"},
        }
    )
    assert mapped is not None
    assert mapped.price is None
    assert mapped.currency == "UNKNOWN"


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-5", "0", "0.00", None, ""])
def test_mapper_rejects_non_positive_or_non_finite_amounts(amount: object) -> None:
    mapped = map_apify_item(
        {
            "id": "1",
            "marketplace_listing_title": "Pump",
            "listing_price": {"amount": amount, "formatted_amount": str(amount or "")},
        }
    )
    assert mapped is not None
    assert mapped.price is None


def test_generic_search_filters_before_returning_results() -> None:
    valid = _record(
        product_id="valid",
        title="Free Shipping Wireless Mouse",
        price=Decimal("15"),
        formatted_price="$15",
    )
    free = _record(product_id="free", title="Headphones", price=None, formatted_price="Gratis")
    zero = _record(
        product_id="zero",
        title="Impact wrench",
        price=None,
        formatted_price="$0.00",
    )
    missing = _record(
        product_id="missing",
        title="Clothing",
        price=None,
        formatted_price=None,
    )

    result, fake = _search(valid, free, zero, missing)

    assert fake.calls == [("wireless mouse", "caracas", 5)]
    assert [listing.external_id for listing in result.listings] == ["valid"]
    assert result.listings[0].title == "Free Shipping Wireless Mouse"
    assert result.metrics == FacebookProductSearchMetrics(
        fetched=4,
        usable=1,
        free_price=1,
        invalid_price=2,
    )
    assert result.rejection_reasons.count(FacebookRejectionReason.FREE_PRICE) == 1
    assert result.rejection_reasons.count(FacebookRejectionReason.INVALID_PRICE) == 2


def test_conflicting_provider_fields_fail_closed_with_free_precedence() -> None:
    result, _ = _search(
        _record(product_id="a", price=Decimal("10"), formatted_price="Free"),
        _record(product_id="b", price=None, formatted_price="$10"),
    )
    assert result.listings == ()
    assert result.metrics.free_price == 1
    assert result.metrics.invalid_price == 1


def test_missing_currency_is_unknown_and_never_inferred_from_dollar_symbol() -> None:
    result, _ = _search(_record(price=Decimal("15"), currency=None, formatted_price="$15"))
    assert len(result.listings) == 1
    listing = result.listings[0]
    assert listing.price == Decimal("15")
    assert listing.currency == "UNKNOWN"
    assert listing.usd_amount is None
    assert listing.usd_normalization_status is None


@pytest.mark.parametrize(
    "title",
    [
        "Wireless mouse",
        "Impact wrench",
        "Water pump",
        "Bluetooth headphones",
        "Cotton clothing",
        "Automotive part",
    ],
)
def test_generic_search_has_no_product_specific_filter(title: str) -> None:
    result, _ = _search(_record(title=title))
    assert [listing.title for listing in result.listings] == [title]


def test_rejection_metrics_cover_structural_failures_and_duplicates() -> None:
    result, _ = _search(
        _record(product_id=None),
        _record(product_id="empty", title=" "),
        _record(product_id="outside", location="Valencia"),
        _record(product_id="duplicate", url="https://facebook.com/marketplace/item/first"),
        _record(product_id="duplicate", url="https://facebook.com/marketplace/item/last"),
        _record(product_id="bad-url", url=None),
        source_errors=1,
    )
    assert result.metrics.missing_product_id == 1
    assert result.metrics.empty_title == 1
    assert result.metrics.out_of_scope_location == 1
    assert result.metrics.duplicate_product_id == 1
    assert result.metrics.source_error == 2
    assert result.metrics.usable == 1
    assert result.listings[0].url.endswith("/last")


def test_statistics_are_isolated_by_explicit_currency_and_unknown_is_excluded() -> None:
    query = SearchQuery("pump")

    def listing(external_id: str, price: str, currency: str) -> Listing:
        return Listing(
            source=MarketplaceSource.FACEBOOK_MARKETPLACE,
            external_id=external_id,
            title=f"Pump {external_id}",
            price=Decimal(price),
            currency=currency,
            url=f"https://facebook.com/marketplace/item/{external_id}",
            query=query,
            collected_at=COLLECTED_AT,
        )

    stats = calculate_facebook_statistics_by_currency(
        [
            listing("usd-1", "10", "USD"),
            listing("usd-2", "15", "USD"),
            listing("unknown", "20", "UNKNOWN"),
            listing("ves", "500", "VES"),
        ]
    )
    assert [(item.currency, item.priced_listings) for item in stats] == [
        ("USD", 2),
        ("VES", 1),
    ]
    assert stats[0].median == Decimal("12.5")
    assert stats[1].median == Decimal("500")


def test_validate_facebook_product_search_normalizes_and_rejects_bounds() -> None:
    assert validate_facebook_product_search("  Wireless  Mouse ", "Caracas", 3) == (
        "Wireless Mouse",
        "caracas",
        3,
    )
    with pytest.raises(ValueError, match="query"):
        validate_facebook_product_search(" ", "caracas", 5)
    with pytest.raises(ValueError, match="city"):
        validate_facebook_product_search("mouse", " ", 5)
    with pytest.raises(ValueError, match="limit"):
        validate_facebook_product_search("mouse", "caracas", 0)
    with pytest.raises(ValueError, match="limit"):
        validate_facebook_product_search("mouse", "caracas", 6)
    with pytest.raises(TypeError, match="limit"):
        validate_facebook_product_search("mouse", "caracas", True)


def test_missing_location_is_not_invented_and_is_not_out_of_scope() -> None:
    result, _ = _search(_record(location=None))
    assert len(result.listings) == 1
    assert result.listings[0].location is None
    assert result.metrics.out_of_scope_location == 0


def test_mapped_dollar_symbol_never_becomes_usd() -> None:
    mapped = map_apify_item(
        {
            "id": "1",
            "marketplace_listing_title": "Wireless mouse",
            "listing_price": {"amount": "15", "formatted_amount": "$15"},
            "listingUrl": "https://www.facebook.com/marketplace/item/1",
            "locationText": "Caracas",
        }
    )
    assert mapped is not None
    assert mapped.price == Decimal("15")
    assert mapped.currency == "UNKNOWN"
    result, _ = _search(mapped)
    assert result.listings[0].currency == "UNKNOWN"
    assert result.listings[0].usd_amount is None


def test_invalid_listing_url_after_price_filter_is_source_error() -> None:
    result, _ = _search(_record(url="not-a-url"))
    assert result.listings == ()
    assert result.metrics.source_error == 1
    assert result.rejection_reasons == (FacebookRejectionReason.SOURCE_ERROR,)


def test_default_clock_is_timezone_aware() -> None:
    fake = FakeFacebookClient(
        ApifyFacebookResult(records=(_record(),), fetched=1),
        [],
    )
    provider = FacebookMarketplaceProductSearch(cast(ApifyFacebookMarketplaceClient, fake))
    result = SearchFacebookMarketplaceProducts(
        cast(FacebookMarketplaceProductSearchProvider, provider)
    ).execute("wireless mouse", "caracas", 1)
    assert result.listings[0].collected_at.tzinfo is not None


def test_h0019_provider_contract_remains_specialized() -> None:
    from bera_price_tracker.infrastructure.providers.facebook_marketplace import (
        FacebookMarketplaceProvider,
    )

    assert "classifier" in FacebookMarketplaceProvider.__dataclass_fields__
    assert "classifier" not in FacebookMarketplaceProductSearch.__dataclass_fields__
