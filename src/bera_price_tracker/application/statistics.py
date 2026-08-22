"""Pure historical statistics for one marketplace listing."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from bera_price_tracker.domain import ListingHistory, ListingStatistics

_MINIMUM_CALCULATION_PRECISION = 50


class StatisticsUnavailableError(RuntimeError):
    """Raised when persisted history cannot produce meaningful statistics."""


class EmptyListingHistoryError(StatisticsUnavailableError):
    """Raised when a known listing has no price observations."""


class MultipleCurrenciesError(StatisticsUnavailableError):
    """Raised rather than silently aggregating amounts in different currencies."""


def _calculation_context(prices: list[Decimal]) -> Context:
    """Return a context large enough for exact aligned sums plus division headroom."""

    exponents: list[int] = []
    for price in prices:
        exponent = price.as_tuple().exponent
        if not isinstance(exponent, int):
            raise ValueError("statistics prices must be finite")
        exponents.append(exponent)
    minimum_exponent = min(exponents)
    maximum_adjusted = max(price.adjusted() for price in prices)
    exact_sum_digits = maximum_adjusted - minimum_exponent + 1 + len(str(len(prices)))
    return Context(
        prec=max(_MINIMUM_CALCULATION_PRECISION, exact_sum_digits),
        rounding=ROUND_HALF_EVEN,
    )


def calculate_listing_statistics(history: ListingHistory) -> ListingStatistics:
    """Derive one listing's statistics using only deterministic ``Decimal`` math.

    Division uses an explicit half-even context with at least 50 significant digits and
    enough additional precision for exact aligned sums. This avoids floats, does not
    inherit process-wide traps, and gives repeating decimal results a stable
    representation.
    """

    if not isinstance(history, ListingHistory):
        raise TypeError("history must be a ListingHistory")

    observations = sorted(history.observations, key=lambda item: item.collected_at)
    if not observations:
        raise EmptyListingHistoryError("Cannot calculate statistics without price observations.")

    currencies = sorted({observation.currency for observation in observations})
    if len(currencies) != 1:
        joined = ", ".join(currencies)
        raise MultipleCurrenciesError(
            f"Cannot calculate statistics across multiple currencies: {joined}"
        )

    prices = [observation.price for observation in observations]
    ordered_prices = sorted(prices)
    count = len(prices)
    middle = count // 2
    current_price = observations[-1].price
    previous_price = observations[-2].price if count > 1 else None

    with localcontext(_calculation_context(prices)):
        average_price = sum(prices, Decimal("0")) / Decimal(count)
        if count % 2:
            median_price = ordered_prices[middle]
        else:
            median_price = (ordered_prices[middle - 1] + ordered_prices[middle]) / Decimal("2")

        absolute_change: Decimal | None = None
        percentage_change: Decimal | None = None
        if previous_price is not None:
            absolute_change = current_price - previous_price
            if previous_price != Decimal("0"):
                percentage_change = (absolute_change / previous_price) * Decimal("100")

    return ListingStatistics(
        key=history.key,
        title=history.title,
        current_price=current_price,
        previous_price=previous_price,
        currency=observations[-1].currency,
        observation_count=count,
        minimum_price=ordered_prices[0],
        maximum_price=ordered_prices[-1],
        average_price=average_price,
        median_price=median_price,
        absolute_change=absolute_change,
        percentage_change=percentage_change,
        first_observed_at=observations[0].collected_at,
        last_observed_at=observations[-1].collected_at,
    )
