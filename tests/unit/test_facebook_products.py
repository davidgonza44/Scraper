"""Offline generic Facebook Marketplace product-search tests."""

from __future__ import annotations

from dataclasses import dataclass, replace
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
    FacebookStatisticsBasis,
    calculate_facebook_statistics,
    calculate_facebook_statistics_by_currency,
    calculate_facebook_venezuela_usd_statistics,
)
from bera_price_tracker.application.facebook_venezuela_price import (
    normalize_facebook_venezuela_price,
)
from bera_price_tracker.application.ports import FacebookMarketplaceProductSearchProvider
from bera_price_tracker.domain import Listing, MarketplaceSource, SearchQuery
from bera_price_tracker.domain.money import (
    DOLLAR_SYMBOL_EVIDENCE,
    FACEBOOK_VENEZUELA_EVIDENCE,
    NormalizationStatus,
    NormalizedPrice,
)
from bera_price_tracker.infrastructure.providers import (
    facebook_products as facebook_product_provider,
)
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


def test_real_smoke_vef_fixture_preserves_source_and_adds_policy_usd() -> None:
    observed = (
        (Decimal("25"), "VEF25"),
        (Decimal("4"), "VEF4"),
        (Decimal("15"), "VEF15"),
        (Decimal("5"), "VEF5"),
        (Decimal("10"), "VEF10"),
    )
    result, fake = _search(
        *(
            _record(
                product_id=f"real-{index}",
                price=amount,
                currency="VEF",
                formatted_price=formatted,
            )
            for index, (amount, formatted) in enumerate(observed)
        )
    )

    assert fake.calls == [("wireless mouse", "caracas", 5)]
    assert result.metrics == FacebookProductSearchMetrics(fetched=5, usable=5)
    assert len(result.listings) == 5
    for listing, (amount, formatted) in zip(result.listings, observed, strict=True):
        assert listing.price == amount
        assert listing.currency == "VEF"
        assert listing.formatted_amount == formatted
        assert listing.usd_amount == amount.quantize(Decimal("0.01"))
        assert listing.usd_amount == listing.price.quantize(Decimal("0.01"))
        assert listing.usd_normalization_status == NormalizationStatus.NORMALIZED.value
        assert listing.usd_evidence == (FACEBOOK_VENEZUELA_EVIDENCE,)
        assert listing.usd_exchange_rate is None
        assert listing.usd_exchange_rate_source is None
        assert listing.usd_exchange_rate_at is None


def test_valid_price_delegates_to_existing_facebook_venezuela_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Decimal | None, str | None, str | None]] = []
    existing_policy = normalize_facebook_venezuela_price

    def policy_spy(
        amount: Decimal | None,
        currency: str | None,
        formatted_amount: str | None = None,
    ) -> NormalizedPrice:
        calls.append((amount, currency, formatted_amount))
        return existing_policy(amount, currency, formatted_amount)

    monkeypatch.setattr(
        facebook_product_provider,
        "normalize_facebook_venezuela_price",
        policy_spy,
    )
    result, _ = _search(_record(price=Decimal("25"), currency="VEF", formatted_price="VEF25"))

    assert calls == [(Decimal("25"), "VEF", "VEF25")]
    assert result.listings[0].usd_amount == Decimal("25.00")


@pytest.mark.parametrize(
    ("record", "decision"),
    [
        (
            _record(price=Decimal("10"), currency="VEF", formatted_price="Free"),
            FacebookPriceDecision.FREE_PRICE,
        ),
        (
            _record(price=Decimal("0"), currency="VEF", formatted_price="VEF0"),
            FacebookPriceDecision.INVALID_PRICE,
        ),
        (
            _record(price=None, currency="VEF", formatted_price="VEF25"),
            FacebookPriceDecision.INVALID_PRICE,
        ),
        (
            _record(price=Decimal("-1"), currency="VEF", formatted_price="VEF-1"),
            FacebookPriceDecision.INVALID_PRICE,
        ),
        (
            _record(price=Decimal("NaN"), currency="VEF", formatted_price="VEFNaN"),
            FacebookPriceDecision.INVALID_PRICE,
        ),
        (
            _record(
                price=Decimal("Infinity"),
                currency="VEF",
                formatted_price="VEFInfinity",
            ),
            FacebookPriceDecision.INVALID_PRICE,
        ),
    ],
)
def test_priced_only_rejects_before_facebook_venezuela_normalization(
    monkeypatch: pytest.MonkeyPatch,
    record: ApifyFacebookListing,
    decision: FacebookPriceDecision,
) -> None:
    def unexpected_normalization(*args: object, **kwargs: object) -> None:
        raise AssertionError("normalizer must not receive rejected prices")

    monkeypatch.setattr(
        facebook_product_provider,
        "normalize_facebook_venezuela_price",
        unexpected_normalization,
    )
    result, _ = _search(record)

    assert result.listings == ()
    assert result.metrics.usable == 0
    assert result.metrics.free_price == int(decision is FacebookPriceDecision.FREE_PRICE)
    assert result.metrics.invalid_price == int(decision is FacebookPriceDecision.INVALID_PRICE)
    assert result.rejection_reasons == (FacebookRejectionReason(decision.value),)


def test_conflicting_provider_fields_fail_closed_with_free_precedence() -> None:
    result, _ = _search(
        _record(product_id="a", price=Decimal("10"), formatted_price="Free"),
        _record(product_id="b", price=None, formatted_price="$10"),
    )
    assert result.listings == ()
    assert result.metrics.free_price == 1
    assert result.metrics.invalid_price == 1


def test_dollar_symbol_uses_existing_facebook_policy_without_rewriting_source() -> None:
    result, _ = _search(_record(price=Decimal("15"), currency=None, formatted_price="$15"))
    assert len(result.listings) == 1
    listing = result.listings[0]
    assert listing.price == Decimal("15")
    assert listing.currency == "UNKNOWN"
    assert listing.formatted_amount == "$15"
    assert listing.usd_amount == Decimal("15.00")
    assert listing.usd_normalization_status == NormalizationStatus.DOLLAR_SYMBOL.value
    assert listing.usd_evidence == (DOLLAR_SYMBOL_EVIDENCE, FACEBOOK_VENEZUELA_EVIDENCE)
    assert listing.usd_exchange_rate is None
    assert listing.usd_exchange_rate_source is None
    assert listing.usd_exchange_rate_at is None


def test_explicit_usd_stays_source_usd_and_already_usd() -> None:
    result, _ = _search(_record(price=Decimal("15"), currency="USD", formatted_price="USD15"))
    listing = result.listings[0]
    assert listing.price == Decimal("15")
    assert listing.currency == "USD"
    assert listing.formatted_amount == "USD15"
    assert listing.usd_amount == Decimal("15.00")
    assert listing.usd_normalization_status == NormalizationStatus.ALREADY_USD.value
    assert listing.usd_evidence == ("explicit_iso_usd",)
    assert FACEBOOK_VENEZUELA_EVIDENCE not in listing.usd_evidence
    assert listing.usd_exchange_rate is None


def test_unknown_without_dollar_stays_unsupported_and_has_no_usd() -> None:
    result, _ = _search(_record(price=Decimal("15"), currency=None, formatted_price="15"))
    listing = result.listings[0]
    assert listing.price == Decimal("15")
    assert listing.currency == "UNKNOWN"
    assert listing.usd_amount is None
    assert listing.usd_normalization_status == NormalizationStatus.UNSUPPORTED_CURRENCY.value
    assert listing.usd_evidence == ("unknown_currency",)


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
    assert all(item.basis is FacebookStatisticsBasis.SOURCE_CURRENCY for item in stats)
    assert stats[0].median == Decimal("12.5")
    assert stats[1].median == Decimal("500")


def test_real_vef_fixture_builds_separate_normalized_usd_benchmark() -> None:
    values = (
        (Decimal("25"), "VEF25"),
        (Decimal("4"), "VEF4"),
        (Decimal("15"), "VEF15"),
        (Decimal("5"), "VEF5"),
        (Decimal("10"), "VEF10"),
    )
    result, _ = _search(
        *(
            _record(
                product_id=f"stats-{index}",
                price=amount,
                currency="VEF",
                formatted_price=formatted,
            )
            for index, (amount, formatted) in enumerate(values)
        )
    )

    assert calculate_facebook_statistics_by_currency(result.listings) == ()
    normalized = calculate_facebook_venezuela_usd_statistics(result.listings)
    assert normalized is not None
    assert normalized.basis is FacebookStatisticsBasis.FACEBOOK_VENEZUELA_NORMALIZED_USD
    assert normalized.currency == "USD"
    assert normalized.source_currencies == ("VEF",)
    assert normalized.normalization_statuses == (NormalizationStatus.NORMALIZED.value,)
    assert normalized.evidence == (FACEBOOK_VENEZUELA_EVIDENCE,)
    assert normalized.priced_listings == 5
    assert normalized.minimum == Decimal("4.00")
    assert normalized.average == Decimal("11.80")
    assert normalized.median == Decimal("10.00")
    assert normalized.maximum == Decimal("25.00")
    assert normalized.p25 == Decimal("5.00")
    assert normalized.p75 == Decimal("15.00")
    assert normalized.iqr == Decimal("10.00")
    assert calculate_facebook_statistics(result.listings) == (normalized,)


def test_normalized_vef_benchmark_rejects_mismatch_or_any_fx_metadata() -> None:
    result, _ = _search(
        _record(
            product_id="vef",
            price=Decimal("10"),
            currency="VEF",
            formatted_price="VEF10",
        )
    )
    listing = result.listings[0]
    corrupted = (
        replace(listing, usd_amount=Decimal("999.00")),
        replace(listing, usd_exchange_rate=Decimal("1")),
        replace(listing, usd_exchange_rate_source="fixture-fx"),
        replace(listing, usd_exchange_rate_at=COLLECTED_AT),
    )

    for candidate in corrupted:
        assert calculate_facebook_venezuela_usd_statistics((candidate,)) is None


def test_statistics_keep_explicit_usd_separate_and_unknown_out() -> None:
    result, _ = _search(
        _record(
            product_id="vef",
            price=Decimal("10"),
            currency="VEF",
            formatted_price="VEF10",
        ),
        _record(
            product_id="dollar",
            price=Decimal("15"),
            currency=None,
            formatted_price="$15",
        ),
        _record(
            product_id="unknown",
            price=Decimal("20"),
            currency=None,
            formatted_price="20",
        ),
        _record(
            product_id="usd",
            price=Decimal("25"),
            currency="USD",
            formatted_price="USD25",
        ),
    )

    normalized, source_usd = calculate_facebook_statistics(result.listings)
    assert normalized.basis is FacebookStatisticsBasis.FACEBOOK_VENEZUELA_NORMALIZED_USD
    assert normalized.priced_listings == 1
    assert normalized.minimum == Decimal("10.00")
    assert source_usd.basis is FacebookStatisticsBasis.SOURCE_CURRENCY
    assert source_usd.source_currencies == ("USD",)
    assert source_usd.normalization_statuses == (NormalizationStatus.ALREADY_USD.value,)
    assert source_usd.priced_listings == 1
    assert source_usd.minimum == Decimal("25")


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


def test_mapped_dollar_symbol_keeps_unknown_source_and_uses_contextual_usd() -> None:
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
    listing = result.listings[0]
    assert listing.currency == "UNKNOWN"
    assert listing.usd_amount == Decimal("15.00")
    assert listing.usd_normalization_status == NormalizationStatus.DOLLAR_SYMBOL.value
    assert listing.usd_evidence == (DOLLAR_SYMBOL_EVIDENCE, FACEBOOK_VENEZUELA_EVIDENCE)


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
