"""Offline tests for USD display normalization."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from bera_price_tracker.application import (
    PriceNormalizer,
    normalize_facebook_venezuela_price,
)
from bera_price_tracker.domain import (
    CollectionBatch,
    Listing,
    MarketplaceSource,
    NormalizationStatus,
    SearchQuery,
    format_usd_display,
)
from bera_price_tracker.infrastructure.fx import StubExchangeRateProvider
from bera_price_tracker.infrastructure.persistence import SQLiteListingRepository


def test_explicit_usd_is_already_usd() -> None:
    result = PriceNormalizer().normalize(Decimal("4"), "USD")
    assert result.original_currency == "USD"
    assert result.original_amount == Decimal("4")
    assert result.usd_amount == Decimal("4.00")
    assert result.normalization_status is NormalizationStatus.ALREADY_USD
    assert format_usd_display(result.usd_amount) == "$4.00"
    assert type(result.usd_amount) is Decimal


def test_dollar_symbol_without_iso_is_not_claimed_usd() -> None:
    result = PriceNormalizer().normalize(Decimal("4"), "UNKNOWN", "$4")
    assert result.original_currency == "UNKNOWN"
    assert result.original_amount == Decimal("4")
    assert result.usd_amount == Decimal("4.00")
    assert result.normalization_status is NormalizationStatus.DOLLAR_SYMBOL
    assert "dollar_symbol" in result.evidence
    assert format_usd_display(result.usd_amount) == "$4.00"


def test_ves_uses_injected_rate_not_hardcoded() -> None:
    rate = StubExchangeRateProvider(Decimal("100")).get_rate()
    result = PriceNormalizer().normalize(Decimal("400"), "VES", exchange_rate=rate)
    assert result.original_currency == "VES"
    assert result.original_amount == Decimal("400")
    assert result.usd_amount == Decimal("4.00")
    assert result.normalization_status is NormalizationStatus.NORMALIZED
    assert result.usd_exchange_rate == Decimal("100")
    assert result.usd_exchange_rate_source == "stub"
    assert type(result.usd_amount) is Decimal
    assert type(result.usd_exchange_rate) is Decimal


def test_ves_without_rate_is_missing_rate() -> None:
    result = PriceNormalizer().normalize(Decimal("400"), "VES")
    assert result.usd_amount is None
    assert result.normalization_status is NormalizationStatus.MISSING_RATE
    assert result.original_currency == "VES"


def test_vef5_is_unsupported_outside_facebook_ve() -> None:
    result = PriceNormalizer().normalize(Decimal("5"), "VEF", "VEF5")
    assert result.usd_amount is None
    assert result.normalization_status is NormalizationStatus.UNSUPPORTED_CURRENCY
    assert "unsupported_currency_semantics" in result.evidence
    assert result.original_currency == "VEF"
    assert result.original_formatted == "VEF5"
    assert result.original_amount == Decimal("5")


def test_unknown_without_dollar_is_not_converted() -> None:
    result = PriceNormalizer().normalize(Decimal("4"), "UNKNOWN", "4")
    assert result.usd_amount is None
    assert result.original_currency == "UNKNOWN"


def test_facebook_ve_vef5_displays_same_amount_as_usd() -> None:
    result = normalize_facebook_venezuela_price(Decimal("5"), "VEF", "VEF5")
    assert result.original_amount == Decimal("5")
    assert result.original_currency == "VEF"
    assert result.original_formatted == "VEF5"
    assert result.usd_amount == Decimal("5.00")
    assert result.normalization_status is NormalizationStatus.NORMALIZED
    assert result.evidence == ("facebook_venezuela_price_semantics",)
    assert format_usd_display(result.usd_amount) == "$5.00"
    assert result.usd_exchange_rate is None


def test_facebook_ve_dollar_four_displays_usd() -> None:
    result = normalize_facebook_venezuela_price(Decimal("4"), "UNKNOWN", "$4")
    assert result.original_currency == "UNKNOWN"
    assert result.original_formatted == "$4"
    assert result.usd_amount == Decimal("4.00")
    assert result.normalization_status is NormalizationStatus.DOLLAR_SYMBOL
    assert "facebook_venezuela_price_semantics" in result.evidence
    assert format_usd_display(result.usd_amount) == "$4.00"


def test_facebook_ve_explicit_usd_stays_already_usd() -> None:
    result = normalize_facebook_venezuela_price(Decimal("4"), "USD", "4 USD")
    assert result.original_currency == "USD"
    assert result.usd_amount == Decimal("4.00")
    assert result.normalization_status is NormalizationStatus.ALREADY_USD
    assert "facebook_venezuela_price_semantics" not in result.evidence


def test_facebook_policy_does_not_change_global_vef() -> None:
    other = PriceNormalizer().normalize(Decimal("5"), "VEF", "VEF5")
    assert other.usd_amount is None
    assert other.normalization_status is NormalizationStatus.UNSUPPORTED_CURRENCY


def test_unknown_currency_listing_is_persistable(tmp_path: Path) -> None:
    listing = Listing(
        source=MarketplaceSource.FACEBOOK_MARKETPLACE,
        external_id="fb-4",
        title="Pastillas de Bera sbr 150",
        price=Decimal("4"),
        currency="UNKNOWN",
        url="https://www.facebook.com/marketplace/item/4",
        query=SearchQuery("pastillas sbr"),
        collected_at=datetime(2026, 8, 22, 12, 0, tzinfo=UTC),
        formatted_amount="$4",
        usd_amount=Decimal("4.00"),
        usd_normalization_status="dollar_symbol",
        usd_evidence=("dollar_symbol", "facebook_venezuela_price_semantics"),
    )
    database = tmp_path / "usd.db"
    with SQLiteListingRepository(database) as repository:
        repository.record_collection(
            CollectionBatch.from_listings(
                source=listing.source,
                query=listing.query,
                collected_at=listing.collected_at,
                listings=[listing],
            )
        )
        history = repository.get_price_history(listing.key)
    assert len(history) == 1
    snapshot = history[0].snapshot
    assert snapshot.price == Decimal("4")
    assert snapshot.currency == "UNKNOWN"
    assert snapshot.usd_amount == Decimal("4.00")
