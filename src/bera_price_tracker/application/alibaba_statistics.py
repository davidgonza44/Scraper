"""Read-only Alibaba search-price statistics. Decimal only; no FX conversion."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Context, Decimal, localcontext

_MINIMUM_CALCULATION_PRECISION = 50
_DISPLAY_CENTS = Decimal("0.01")
_TWO = Decimal("2")
_ONE_POINT_FIVE = Decimal("1.5")
_P25 = Decimal("0.25")
_P75 = Decimal("0.75")
_TRIM_FRACTION = Decimal("0.10")
STATS_CURRENCY = "USD"
UNAVAILABLE_DISPLAY = "unavailable"


@dataclass(frozen=True, slots=True)
class AlibabaPriceStatistics:
    """Comparable USD aggregates for one Alibaba search result set."""

    total_products: int
    priced_products: int
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


def _empty_statistics(total: int) -> AlibabaPriceStatistics:
    return AlibabaPriceStatistics(
        total_products=total,
        priced_products=0,
        currency=None,
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


def _as_decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        return None
    if not value.is_finite() or value <= Decimal("0"):
        return None
    return value


def infer_alibaba_currency(product: object) -> str | None:
    """Return an explicit ISO code, or USD when the display uses ``$``."""

    raw = getattr(product, "currency", None)
    if isinstance(raw, str) and raw.strip():
        return raw.strip().upper()
    display = getattr(product, "price_display", None)
    if isinstance(display, str) and "$" in display:
        return STATS_CURRENCY
    return None


def alibaba_price_bounds(product: object) -> tuple[Decimal, Decimal] | None:
    """Return (price_min, price_max). A simple price uses the same value twice."""

    minimum = _as_decimal(getattr(product, "min_price", None))
    if minimum is None:
        return None
    maximum = _as_decimal(getattr(product, "max_price", None))
    if maximum is None:
        maximum = minimum
    return minimum, maximum


def alibaba_representative_price(product: object) -> Decimal | None:
    """Single comparison value: the price, or the midpoint of a published range."""

    bounds = alibaba_price_bounds(product)
    if bounds is None:
        return None
    minimum, maximum = bounds
    if minimum == maximum:
        return minimum
    with localcontext(_calculation_context([minimum, maximum])):
        return (minimum + maximum) / _TWO


def _usable_for_usd_stats(product: object) -> bool:
    if infer_alibaba_currency(product) != STATS_CURRENCY:
        return False
    return alibaba_price_bounds(product) is not None


def alibaba_percentile(ordered: Sequence[Decimal], percentile: Decimal) -> Decimal:
    """Linear-interpolation percentile over an already sorted Decimal series."""

    values = list(ordered)
    count = len(values)
    if count == 0:
        raise ValueError("percentile requires at least one value")
    if count == 1:
        return values[0]
    with localcontext(_calculation_context(values)):
        position = Decimal(count - 1) * percentile
        integral = position.to_integral_value(rounding=ROUND_FLOOR)
        if position == integral:
            return values[int(integral)]
        lower = int(position.to_integral_value(rounding=ROUND_FLOOR))
        upper = int(position.to_integral_value(rounding=ROUND_CEILING))
        fraction = position - Decimal(lower)
        return values[lower] + (values[upper] - values[lower]) * fraction


def alibaba_trimmed_mean(ordered: Sequence[Decimal]) -> Decimal:
    """10% trimmed mean. ``k = floor(n * 0.10)``; never returns an empty mean."""

    values = list(ordered)
    count = len(values)
    if count == 0:
        raise ValueError("trimmed mean requires at least one value")
    with localcontext(_calculation_context(values)):
        trim = (Decimal(count) * _TRIM_FRACTION).to_integral_value(rounding=ROUND_FLOOR)
        start = int(trim)
        stop = count - start
        remaining = values[start:stop] if stop > start else values
        return sum(remaining, Decimal("0")) / Decimal(len(remaining))


def _usable_representatives(
    products: Sequence[object],
) -> tuple[list[Decimal], list[Decimal], list[Decimal]]:
    mins: list[Decimal] = []
    maxes: list[Decimal] = []
    values: list[Decimal] = []
    for product in products:
        if not _usable_for_usd_stats(product):
            continue
        bounds = alibaba_price_bounds(product)
        representative = alibaba_representative_price(product)
        if bounds is None or representative is None:
            continue
        mins.append(bounds[0])
        maxes.append(bounds[1])
        values.append(representative)
    return mins, maxes, values


def calculate_alibaba_price_statistics(products: Sequence[object]) -> AlibabaPriceStatistics:
    """Aggregate published USD search prices. Other currencies are excluded."""

    total = len(products)
    mins, maxes, values = _usable_representatives(products)
    if not values:
        return _empty_statistics(total)

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

    outlier_count = sum(1 for price in values if price < lower_fence or price > upper_fence)
    return AlibabaPriceStatistics(
        total_products=total,
        priced_products=count,
        currency=STATS_CURRENCY,
        minimum=min(mins),
        maximum=max(maxes),
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


def format_alibaba_money(value: Decimal | None) -> str:
    """Render an aggregate as ``$X.XX`` or ``unavailable``."""

    if value is None:
        return UNAVAILABLE_DISPLAY
    quantized = value.quantize(_DISPLAY_CENTS, rounding=ROUND_HALF_EVEN)
    return f"${quantized}"


def format_priced_count(priced: int, total: int) -> str:
    return f"{priced} de {total}"


def format_alibaba_typical_range(p25: Decimal | None, p75: Decimal | None) -> str:
    if p25 is None or p75 is None:
        return UNAVAILABLE_DISPLAY
    return f"{format_alibaba_money(p25)} – {format_alibaba_money(p75)}"


def interpret_alibaba_prices(stats: AlibabaPriceStatistics) -> str:
    """Plain statistical notes. No commercial judgment."""

    parts: list[str] = []
    if stats.priced_products >= 2 and stats.p25 is not None and stats.p75 is not None:
        low = format_alibaba_money(stats.p25)
        high = format_alibaba_money(stats.p75)
        parts.append(f"El 50% central de los precios está entre {low} y {high}.")
    if stats.outlier_count:
        parts.append(
            f"Se detectaron {stats.outlier_count} precios fuera del rango estadístico habitual."
        )
    return " ".join(parts)


__all__ = [
    "STATS_CURRENCY",
    "UNAVAILABLE_DISPLAY",
    "AlibabaPriceStatistics",
    "alibaba_percentile",
    "alibaba_price_bounds",
    "alibaba_representative_price",
    "alibaba_trimmed_mean",
    "calculate_alibaba_price_statistics",
    "format_alibaba_money",
    "format_alibaba_typical_range",
    "format_priced_count",
    "infer_alibaba_currency",
    "interpret_alibaba_prices",
]
