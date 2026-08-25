"""Currency-isolated statistics for generic Facebook Marketplace comparables."""

from __future__ import annotations

from collections.abc import Sequence

from bera_price_tracker.application.mercadolibre_statistics import (
    MercadoLibrePriceStatistics,
    available_currencies,
    calculate_mercadolibre_price_statistics,
)

FacebookPriceStatistics = MercadoLibrePriceStatistics


def calculate_facebook_statistics_by_currency(
    listings: Sequence[object],
) -> tuple[FacebookPriceStatistics, ...]:
    """Aggregate each explicit ISO currency separately; UNKNOWN never enters a group."""

    return tuple(
        calculate_mercadolibre_price_statistics(listings, currency=currency)
        for currency in available_currencies(listings)
    )


__all__ = [
    "FacebookPriceStatistics",
    "calculate_facebook_statistics_by_currency",
]
