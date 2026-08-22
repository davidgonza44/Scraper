"""Pure unit tests for one-listing historical statistics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, Inexact, localcontext

import pytest

from bera_price_tracker.application import (
    EmptyListingHistoryError,
    GetListingStatistics,
    MultipleCurrenciesError,
    calculate_listing_statistics,
)
from bera_price_tracker.domain import (
    ListingHistory,
    ListingKey,
    MarketplaceSource,
    PriceObservation,
    SearchQuery,
)

BASE_TIME = datetime(2026, 8, 1, 14, tzinfo=UTC)
KEY = ListingKey(MarketplaceSource.MERCADO_LIBRE, "MLV-STATS")
QUERY = SearchQuery("pastillas de freno bera")


def make_history(
    prices: list[str],
    *,
    currencies: list[str] | None = None,
    timestamps: list[datetime] | None = None,
) -> ListingHistory:
    selected_currencies = currencies or ["VES"] * len(prices)
    selected_timestamps = timestamps or [
        BASE_TIME + timedelta(days=index) for index in range(len(prices))
    ]
    observations = tuple(
        PriceObservation(
            price=Decimal(price),
            currency=currency,
            collected_at=collected_at,
            query=QUERY,
        )
        for price, currency, collected_at in zip(
            prices, selected_currencies, selected_timestamps, strict=True
        )
    )
    return ListingHistory(
        key=KEY,
        title="Pastillas de freno BERA SBR",
        url="https://example.test/MLV-STATS",
        first_seen_at=BASE_TIME - timedelta(days=30),
        last_seen_at=BASE_TIME + timedelta(days=30),
        observations=observations,
    )


def test_one_observation_has_no_previous_or_change() -> None:
    statistics = calculate_listing_statistics(make_history(["12.50"]))

    assert statistics.key == KEY
    assert statistics.title == "Pastillas de freno BERA SBR"
    assert statistics.current_price == Decimal("12.50")
    assert statistics.previous_price is None
    assert statistics.currency == "VES"
    assert statistics.observation_count == 1
    assert statistics.minimum_price == Decimal("12.50")
    assert statistics.maximum_price == Decimal("12.50")
    assert statistics.average_price == Decimal("12.50")
    assert statistics.median_price == Decimal("12.50")
    assert statistics.absolute_change is None
    assert statistics.percentage_change is None
    assert statistics.first_observed_at == BASE_TIME
    assert statistics.last_observed_at == BASE_TIME


def test_two_observations_calculate_positive_change_and_even_median() -> None:
    statistics = calculate_listing_statistics(make_history(["20", "22"]))

    assert statistics.current_price == Decimal("22")
    assert statistics.previous_price == Decimal("20")
    assert statistics.minimum_price == Decimal("20")
    assert statistics.maximum_price == Decimal("22")
    assert statistics.average_price == Decimal("21")
    assert statistics.median_price == Decimal("21")
    assert statistics.absolute_change == Decimal("2")
    assert statistics.percentage_change == Decimal("10")


def test_three_observations_calculate_odd_median_minimum_maximum_and_count() -> None:
    statistics = calculate_listing_statistics(make_history(["30", "10", "20"]))

    assert statistics.observation_count == 3
    assert statistics.minimum_price == Decimal("10")
    assert statistics.maximum_price == Decimal("30")
    assert statistics.average_price == Decimal("20")
    assert statistics.median_price == Decimal("20")


def test_four_observations_calculate_decimal_average_and_even_median() -> None:
    statistics = calculate_listing_statistics(make_history(["10", "20", "30", "40"]))

    assert statistics.minimum_price == Decimal("10")
    assert statistics.maximum_price == Decimal("40")
    assert statistics.average_price == Decimal("25")
    assert statistics.median_price == Decimal("25")


def test_repeated_latest_price_is_the_real_previous_observation() -> None:
    statistics = calculate_listing_statistics(make_history(["19.99", "21.99", "21.99"]))

    assert statistics.observation_count == 3
    assert statistics.current_price == Decimal("21.99")
    assert statistics.previous_price == Decimal("21.99")
    assert statistics.absolute_change == Decimal("0.00")
    assert statistics.percentage_change == Decimal("0")


def test_price_decrease_has_negative_absolute_and_percentage_change() -> None:
    statistics = calculate_listing_statistics(make_history(["20", "18"]))

    assert statistics.absolute_change == Decimal("-2")
    assert statistics.percentage_change == Decimal("-10")


def test_calculation_sorts_timestamps_and_uses_explicit_decimal_precision() -> None:
    first = BASE_TIME
    second = BASE_TIME + timedelta(days=9)
    third = BASE_TIME + timedelta(days=19)
    history = make_history(
        ["21.99", "19.99", "19.99"],
        timestamps=[third, first, second],
    )
    with localcontext() as outer_context:
        outer_context.prec = 6
        statistics = calculate_listing_statistics(history)
    with localcontext() as expected_context:
        expected_context.prec = 50
        expected_average = Decimal("61.97") / Decimal("3")

    assert statistics.current_price == Decimal("21.99")
    assert statistics.previous_price == Decimal("19.99")
    assert statistics.average_price == expected_average
    assert isinstance(statistics.average_price, Decimal)
    assert isinstance(statistics.percentage_change, Decimal)
    assert statistics.first_observed_at == first
    assert statistics.last_observed_at == third


def test_calculation_does_not_inherit_global_inexact_trap() -> None:
    with localcontext() as outer_context:
        outer_context.traps[Inexact] = True
        statistics = calculate_listing_statistics(make_history(["1", "1", "2"]))

    assert statistics.average_price.is_finite()
    assert statistics.average_price > Decimal("1.333333333333333333333333333333")


def test_calculation_preserves_a_terminating_price_larger_than_fifty_digits() -> None:
    price = Decimal("100000000000000000000000000000000000000000000000001")

    statistics = calculate_listing_statistics(make_history([str(price)]))

    assert statistics.current_price == price
    assert statistics.average_price == price
    assert statistics.median_price == price


def test_multiple_currencies_are_rejected_deterministically() -> None:
    history = make_history(["19.99", "21.99"], currencies=["VES", "USD"])

    with pytest.raises(
        MultipleCurrenciesError,
        match="Cannot calculate statistics across multiple currencies: USD, VES",
    ):
        calculate_listing_statistics(history)


def test_empty_history_is_a_controlled_statistics_error() -> None:
    history = make_history([])

    with pytest.raises(
        EmptyListingHistoryError,
        match="without price observations",
    ):
        calculate_listing_statistics(history)


def test_get_listing_statistics_uses_history_repository_and_propagates_not_found() -> None:
    history = make_history(["19.99", "21.99"])

    class FakeRepository:
        def __init__(self, result: ListingHistory | None) -> None:
            self.result = result
            self.keys: list[ListingKey] = []

        def get_history(self, key: ListingKey) -> ListingHistory | None:
            self.keys.append(key)
            return self.result

    found_repository = FakeRepository(history)
    missing_repository = FakeRepository(None)

    result = GetListingStatistics(found_repository).execute(KEY)

    assert result is not None
    assert result.current_price == Decimal("21.99")
    assert found_repository.keys == [KEY]
    assert GetListingStatistics(missing_repository).execute(KEY) is None
    assert missing_repository.keys == [KEY]
