"""Published-price statistics for one Mercado Libre currency. Decimal only; no FX."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from bera_price_tracker.application.alibaba_statistics import (
    alibaba_percentile,
    alibaba_trimmed_mean,
)

_MINIMUM_CALCULATION_PRECISION = 50
_DISPLAY_CENTS = Decimal("0.01")
_TWO = Decimal("2")
_ONE_POINT_FIVE = Decimal("1.5")
_P25 = Decimal("0.25")
_P75 = Decimal("0.75")
UNAVAILABLE_DISPLAY = "unavailable"


@dataclass(frozen=True, slots=True)
class MercadoLibrePriceStatistics:
    """Comparable aggregates for one explicit currency."""

    total_listings: int
    priced_listings: int
    currency: str | None
    minimum: Decimal | None
    maximum: Decimal | None
    average: Decimal | None
    median: Decimal | None
    p25: Decimal | None
    p75: Decimal | None
    iqr: Decimal | None
    trimmed_mean: Decimal | None
    lower_fence: Decimal | None
    upper_fence: Decimal | None
    outlier_count: int


def _empty_statistics(total: int, currency: str | None = None) -> MercadoLibrePriceStatistics:
    return MercadoLibrePriceStatistics(
        total_listings=total,
        priced_listings=0,
        currency=currency,
        minimum=None,
        maximum=None,
        average=None,
        median=None,
        p25=None,
        p75=None,
        iqr=None,
        trimmed_mean=None,
        lower_fence=None,
        upper_fence=None,
        outlier_count=0,
    )


def _calculation_context(prices: list[Decimal]) -> Context:
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


def explicit_currency(listing: object) -> str | None:
    """Return a listing's explicit ISO currency. Never infer from ``$`` or country."""

    raw = getattr(listing, "currency", None)
    if not isinstance(raw, str):
        return None
    normalized = raw.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        return None
    return normalized


def listing_price(listing: object) -> Decimal | None:
    value = getattr(listing, "price", None)
    if isinstance(value, bool) or not isinstance(value, Decimal):
        return None
    if not value.is_finite() or value <= Decimal("0"):
        return None
    return value


def is_price_outlier(
    price: Decimal,
    lower_fence: Decimal | None,
    upper_fence: Decimal | None,
) -> bool:
    if lower_fence is None or upper_fence is None:
        return False
    return price < lower_fence or price > upper_fence


def calculate_mercadolibre_price_statistics(
    listings: Sequence[object],
    *,
    currency: str,
) -> MercadoLibrePriceStatistics:
    """Aggregate published prices for one explicit currency. Other currencies are excluded."""

    if not isinstance(currency, str) or not currency.strip():
        raise ValueError("currency must not be blank")
    wanted = currency.strip().upper()
    total = len(listings)
    values: list[Decimal] = []
    for listing in listings:
        if explicit_currency(listing) != wanted:
            continue
        price = listing_price(listing)
        if price is None:
            continue
        values.append(price)
    if not values:
        return _empty_statistics(total, wanted)

    ordered = sorted(values)
    count = len(values)
    middle = count // 2
    with localcontext(_calculation_context(values)):
        average = sum(values, Decimal("0")) / Decimal(count)
        if count % 2:
            median = ordered[middle]
        else:
            median = (ordered[middle - 1] + ordered[middle]) / _TWO
        p25 = alibaba_percentile(ordered, _P25)
        p75 = alibaba_percentile(ordered, _P75)
        iqr = p75 - p25
        trimmed_mean = alibaba_trimmed_mean(ordered)
        lower_fence = p25 - (_ONE_POINT_FIVE * iqr)
        upper_fence = p75 + (_ONE_POINT_FIVE * iqr)

    outlier_count = sum(1 for price in values if is_price_outlier(price, lower_fence, upper_fence))
    return MercadoLibrePriceStatistics(
        total_listings=total,
        priced_listings=count,
        currency=wanted,
        minimum=ordered[0],
        maximum=ordered[-1],
        average=average,
        median=median,
        p25=p25,
        p75=p75,
        iqr=iqr,
        trimmed_mean=trimmed_mean,
        lower_fence=lower_fence,
        upper_fence=upper_fence,
        outlier_count=outlier_count,
    )


def format_mercadolibre_money(value: Decimal | None, currency: str | None) -> str:
    if value is None or currency is None:
        return UNAVAILABLE_DISPLAY
    quantized = value.quantize(_DISPLAY_CENTS, rounding=ROUND_HALF_EVEN)
    return f"{quantized} {currency}"


def format_mercadolibre_typical_range(
    p25: Decimal | None, p75: Decimal | None, currency: str | None
) -> str:
    if p25 is None or p75 is None or currency is None:
        return UNAVAILABLE_DISPLAY
    return (
        f"{format_mercadolibre_money(p25, currency)} – {format_mercadolibre_money(p75, currency)}"
    )


def available_currencies(listings: Sequence[object]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for listing in listings:
        code = explicit_currency(listing)
        if code is None or listing_price(listing) is None or code in seen:
            continue
        seen.add(code)
        ordered.append(code)
    return tuple(ordered)


def dominant_currency(listings: Sequence[object]) -> str | None:
    counts: dict[str, int] = {}
    for listing in listings:
        code = explicit_currency(listing)
        if code is None or listing_price(listing) is None:
            continue
        counts[code] = counts.get(code, 0) + 1
    if not counts:
        return None
    return max(sorted(counts), key=lambda code: (counts[code], code == "USD", code))


__all__ = [
    "UNAVAILABLE_DISPLAY",
    "MercadoLibrePriceStatistics",
    "available_currencies",
    "calculate_mercadolibre_price_statistics",
    "dominant_currency",
    "explicit_currency",
    "format_mercadolibre_money",
    "format_mercadolibre_typical_range",
    "is_price_outlier",
    "listing_price",
]
