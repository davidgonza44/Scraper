"""Read-only Alibaba search-price statistics. Decimal only; no FX conversion."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import (
    MAX_PREC,
    ROUND_CEILING,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    InvalidOperation,
    localcontext,
)

_MINIMUM_CALCULATION_PRECISION = 50
ALIBABA_DECIMAL_WORK_PRECISION_CAP = 10_000
_DISPLAY_CENTS = Decimal("0.01")
_TWO = Decimal("2")
_ONE_POINT_FIVE = Decimal("1.5")
_P25 = Decimal("0.25")
_P75 = Decimal("0.75")
_TRIM_FRACTION = Decimal("0.10")
STATS_CURRENCY = "USD"
UNAVAILABLE_DISPLAY = "unavailable"
MISSING_CURRENCY_DISPLAY = "moneda no disponible"


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


def _bounded_precision(required: int) -> int | None:
    """Return ``required`` only when it is a safe ``Context.prec`` value.

    ``MAX_PREC`` is only Decimal's legal upper bound. Provider-controlled
    exponents can still request prohibitive coefficient work below that
    limit. ``ALIBABA_DECIMAL_WORK_PRECISION_CAP`` is a deterministic
    computational cap, not a commercial price maximum.
    """

    cap = min(MAX_PREC, ALIBABA_DECIMAL_WORK_PRECISION_CAP)
    if required < 1 or required > cap:
        return None
    return required


def _decimal_context(precision: int) -> Context | None:
    bounded = _bounded_precision(precision)
    if bounded is None:
        return None
    try:
        return Context(prec=bounded, rounding=ROUND_HALF_EVEN)
    except (ValueError, InvalidOperation, OverflowError):
        return None


def _cents_precision(value: Decimal) -> int:
    return max(_MINIMUM_CALCULATION_PRECISION, value.adjusted() + 3)


def _decimal_in_context_range(value: Decimal, context: Context) -> bool:
    """True when ``value`` is a normal in ``context`` (Emin..Emax).

    ``Etiny`` is the subnormal floor. Values below ``Emin`` underflow this
    pipeline rather than participating as a usable price.
    """

    try:
        adjusted = value.adjusted()
    except (ArithmeticError, InvalidOperation, OverflowError, ValueError):
        return False
    return context.Emin <= adjusted <= context.Emax


def _representable_price(value: Decimal) -> bool:
    """Technical representability: work cap, exponent range, and positivity."""

    if not value.is_finite() or value <= Decimal("0"):
        return False
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        return False
    context = _decimal_context(_cents_precision(value))
    if context is None:
        return False
    return _decimal_in_context_range(value, context)


def _calculation_context(prices: list[Decimal]) -> Context | None:
    exponents: list[int] = []
    for price in prices:
        exponent = price.as_tuple().exponent
        if not isinstance(exponent, int):
            raise ValueError("statistics prices must be finite")
        exponents.append(exponent)
    minimum_exponent = min(exponents)
    maximum_adjusted = max(price.adjusted() for price in prices)
    exact_sum_digits = maximum_adjusted - minimum_exponent + 1 + len(str(len(prices)))
    return _decimal_context(max(_MINIMUM_CALCULATION_PRECISION, exact_sum_digits))


def _as_decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, Decimal):
        return None
    if not _representable_price(value):
        return None
    return value


def _quantize_cents(value: Decimal) -> Decimal | None:
    """Quantize to display cents, or None if the coefficient cannot be represented."""

    if not _representable_price(value):
        return None
    context = _decimal_context(_cents_precision(value))
    if context is None:
        return None
    try:
        with localcontext(context):
            return value.quantize(_DISPLAY_CENTS, rounding=ROUND_HALF_EVEN)
    except (InvalidOperation, ValueError, OverflowError):
        return None


def explicit_alibaba_currency(value: object) -> str | None:
    """Return a 3-letter ISO code. ``$`` and other symbols are not currency."""

    if not isinstance(value, str):
        return None
    currency = value.strip().upper()
    if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
        return None
    return currency


def infer_alibaba_currency(product: object) -> str | None:
    """Return an explicit ISO code from the listing. Never infer from ``$``."""

    return explicit_alibaba_currency(getattr(product, "currency", None))


def alibaba_iso_currencies_match(left: object, right: object) -> bool:
    """True only when both values are the same explicit 3-letter ISO code."""

    first = explicit_alibaba_currency(left)
    second = explicit_alibaba_currency(right)
    return first is not None and second is not None and first == second


def alibaba_price_bounds(product: object) -> tuple[Decimal, Decimal] | None:
    """Return (price_min, price_max). A simple price uses the same value twice."""

    minimum = _as_decimal(getattr(product, "min_price", None))
    if minimum is None:
        return None
    raw_maximum = getattr(product, "max_price", None)
    if raw_maximum is None:
        return minimum, minimum
    maximum = _as_decimal(raw_maximum)
    if maximum is None:
        return None
    if minimum > maximum:
        return None
    return minimum, maximum


def alibaba_representative_price(product: object) -> Decimal | None:
    """Single comparison value: the price, or the midpoint of a published range."""

    bounds = alibaba_price_bounds(product)
    if bounds is None:
        return None
    minimum, maximum = bounds
    if minimum == maximum:
        return minimum
    context = _calculation_context([minimum, maximum])
    if context is None:
        return None
    with localcontext(context):
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
    context = _calculation_context(values)
    if context is None:
        raise ValueError("percentile requires representable prices")
    with localcontext(context):
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
    context = _calculation_context(values)
    if context is None:
        raise ValueError("trimmed mean requires representable prices")
    with localcontext(context):
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


def _eligible_for_group_statistics(values: list[Decimal]) -> list[bool]:
    """Keep the largest order-independent subset that shares one Context.

    Individually representable prices can still be group-threatening when their
    combined exponent span exceeds the technical work cap. Prefer ordinary
    magnitudes (smaller per-value cents precision) so a single extreme cannot
    erase valid sibling statistics.
    """

    count = len(values)
    if count == 0:
        return []
    if _calculation_context(values) is not None:
        return [True] * count
    ranked = sorted(
        range(count),
        key=lambda index: (
            _cents_precision(values[index]),
            values[index].adjusted(),
            values[index],
        ),
    )
    chosen: list[Decimal] = []
    selected: set[int] = set()
    for index in ranked:
        trial = chosen + [values[index]]
        if _calculation_context(trial) is not None:
            chosen.append(values[index])
            selected.add(index)
    return [index in selected for index in range(count)]


def calculate_alibaba_price_statistics(products: Sequence[object]) -> AlibabaPriceStatistics:
    """Aggregate published USD search prices. Other currencies are excluded."""

    total = len(products)
    mins, maxes, values = _usable_representatives(products)
    if not values:
        return _empty_statistics(total)
    keep = _eligible_for_group_statistics(values)
    mins = [price for price, eligible in zip(mins, keep, strict=True) if eligible]
    maxes = [price for price, eligible in zip(maxes, keep, strict=True) if eligible]
    values = [price for price, eligible in zip(values, keep, strict=True) if eligible]
    if not values:
        return _empty_statistics(total)

    ordered = sorted(values)
    count = len(values)
    middle = count // 2
    context = _calculation_context(values)
    if context is None:
        return _empty_statistics(total)
    with localcontext(context):
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
    quantized = _quantize_cents(value)
    if quantized is None:
        return UNAVAILABLE_DISPLAY
    return f"${quantized}"


def format_alibaba_currency(value: Decimal | None, currency: object) -> str:
    """Render money without implying USD for another or unknown currency."""

    explicit = explicit_alibaba_currency(currency)
    if value is None or explicit is None:
        return UNAVAILABLE_DISPLAY
    quantized = _quantize_cents(value)
    if quantized is None:
        return UNAVAILABLE_DISPLAY
    if explicit == STATS_CURRENCY:
        return f"${quantized}"
    return f"{explicit} {quantized}"


def format_alibaba_listing_price(
    min_price: object,
    max_price: object,
    currency: object,
) -> str:
    """GUI listing price. ``min``/``max``/ISO are authority; never raw ``$`` text."""

    low = _as_decimal(min_price)
    if low is None:
        return ""
    if max_price is None:
        high = low
    else:
        high = _as_decimal(max_price)
        if high is None:
            return ""
    if high < low:
        return ""
    quantized_low = _quantize_cents(low)
    quantized_high = _quantize_cents(high)
    if quantized_low is None or quantized_high is None:
        return ""
    explicit = explicit_alibaba_currency(currency)
    if explicit is None:
        amount = (
            f"{quantized_low}"
            if quantized_low == quantized_high
            else f"{quantized_low}–{quantized_high}"
        )
        return f"{amount} · {MISSING_CURRENCY_DISPLAY}"
    if quantized_low == quantized_high:
        return format_alibaba_currency(low, explicit)
    if explicit == STATS_CURRENCY:
        return f"{format_alibaba_currency(low, explicit)}–{format_alibaba_currency(high, explicit)}"
    return f"{explicit} {quantized_low}–{quantized_high}"


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
    "MISSING_CURRENCY_DISPLAY",
    "STATS_CURRENCY",
    "UNAVAILABLE_DISPLAY",
    "AlibabaPriceStatistics",
    "alibaba_iso_currencies_match",
    "alibaba_percentile",
    "alibaba_price_bounds",
    "alibaba_representative_price",
    "alibaba_trimmed_mean",
    "calculate_alibaba_price_statistics",
    "explicit_alibaba_currency",
    "format_alibaba_currency",
    "format_alibaba_listing_price",
    "format_alibaba_money",
    "format_alibaba_typical_range",
    "format_priced_count",
    "infer_alibaba_currency",
    "interpret_alibaba_prices",
]
