"""Opportunity score (0-100) per Alibaba listing. Deterministic, offline, Decimal only.

This is NOT a reputation or trust score: it only compares the relative price
position, MOQ and information completeness within the current search results.
Real supplier fields (rating, verified, years, reviews, orders) can be added
to :class:`AlibabaListingScore` later, once the Actor provides them.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

from bera_price_tracker.application.alibaba_statistics import (
    STATS_CURRENCY,
    AlibabaPriceStatistics,
    alibaba_price_bounds,
    alibaba_representative_price,
    calculate_alibaba_price_statistics,
    infer_alibaba_currency,
)

PRICE_POINTS = Decimal("45")
MOQ_POINTS = Decimal("25")
INFORMATION_POINTS_PER_FIELD = 4
CLARITY_POINTS_SIMPLE = 10
CLARITY_POINTS_RANGE = 7
CLARITY_POINTS_PARTIAL = 4
LOWER_OUTLIER_PRICE_CAP = 25

LABEL_EXCELLENT = "Excelente oportunidad"
LABEL_GOOD = "Buena oportunidad"
LABEL_MIDDLE = "Intermedia"
LABEL_LOW = "Baja / poco comparable"

OUTLIER_BADGE = "Precio atípico"

_MOQ_NUMBER = re.compile(r"(\d[\d,]*(?:\.\d+)?)")
_MOQ_SCIENTIFIC = re.compile(r"(?<![A-Za-z])[+-]?\d+(?:\.\d+)?[eE][+-]?\d+")
_INFORMATION_FIELDS = ("title", "supplier_name", "product_url", "image_url", "supplier_country")
_HALF = Decimal("0.5")
_INTEGER = Decimal("1")


@dataclass(frozen=True, slots=True)
class AlibabaListingScore:
    """Score breakdown for one listing within a single search result set."""

    total: int
    price_score: int
    moq_score: int
    information_score: int
    price_clarity_score: int
    label: str
    is_price_outlier: bool


def _round_points(value: Decimal) -> int:
    return int(value.quantize(_INTEGER, rounding=ROUND_HALF_EVEN))


def _relative_fraction(value: Decimal, group: Sequence[Decimal]) -> Decimal:
    """Inverse-rank fraction in [0, 1]: 1 for the smallest value of the group.

    Ties share the average of their positions. A group of one has no relative
    position, so it gets a neutral 0.5.
    """

    count = len(group)
    if count <= 1:
        return _HALF
    greater = sum(1 for other in group if other > value)
    equal = sum(1 for other in group if other == value)
    return (Decimal(greater) + Decimal(equal - 1) * _HALF) / Decimal(count - 1)


def extract_moq_quantity(moq: object) -> Decimal | None:
    """First ordinary MOQ quantity, or None. Never invents a value."""

    if not isinstance(moq, str):
        return None
    if _MOQ_SCIENTIFIC.search(moq.replace(" ", "")) is not None:
        return None
    match = _MOQ_NUMBER.search(moq)
    if match is None:
        return None
    prefix = moq[: match.start()].rstrip()
    if prefix.endswith("-"):
        return None
    try:
        quantity = Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None
    if not quantity.is_finite() or quantity <= 0:
        return None
    return quantity


def _usd_representative(product: object) -> Decimal | None:
    if infer_alibaba_currency(product) != STATS_CURRENCY:
        return None
    return alibaba_representative_price(product)


def _price_score(
    representative: Decimal | None,
    usd_values: Sequence[Decimal],
    stats: AlibabaPriceStatistics,
) -> tuple[int, bool]:
    if representative is None:
        return 0, False
    is_lower_outlier = stats.lower_fence is not None and representative < stats.lower_fence
    is_upper_outlier = stats.upper_fence is not None and representative > stats.upper_fence
    points = _round_points(PRICE_POINTS * _relative_fraction(representative, usd_values))
    if is_lower_outlier:
        points = min(points, LOWER_OUTLIER_PRICE_CAP)
    return points, bool(is_lower_outlier or is_upper_outlier)


def _moq_score(quantity: Decimal | None, quantities: Sequence[Decimal]) -> int:
    if quantity is None:
        return 0
    return _round_points(MOQ_POINTS * _relative_fraction(quantity, quantities))


def _information_score(product: object) -> int:
    points = 0
    for field in _INFORMATION_FIELDS:
        value = getattr(product, field, None)
        if isinstance(value, str) and value.strip():
            points += INFORMATION_POINTS_PER_FIELD
    return points


def _price_clarity_score(product: object) -> int:
    bounds = alibaba_price_bounds(product)
    if bounds is None:
        return 0
    if infer_alibaba_currency(product) != STATS_CURRENCY:
        return CLARITY_POINTS_PARTIAL
    minimum, maximum = bounds
    if minimum == maximum:
        return CLARITY_POINTS_SIMPLE
    return CLARITY_POINTS_RANGE


def score_label(total: int) -> str:
    if total >= 85:
        return LABEL_EXCELLENT
    if total >= 70:
        return LABEL_GOOD
    if total >= 50:
        return LABEL_MIDDLE
    return LABEL_LOW


def format_score_display(total: int) -> str:
    return f"{total}/100"


def calculate_listing_score(
    product: object,
    *,
    usd_values: Sequence[Decimal],
    moq_values: Sequence[Decimal],
    stats: AlibabaPriceStatistics,
) -> AlibabaListingScore:
    """Score one listing against the other results of the same search."""

    price_points, is_outlier = _price_score(_usd_representative(product), usd_values, stats)
    moq_points = _moq_score(extract_moq_quantity(getattr(product, "moq", None)), moq_values)
    information_points = _information_score(product)
    clarity_points = _price_clarity_score(product)
    total = max(0, min(100, price_points + moq_points + information_points + clarity_points))
    return AlibabaListingScore(
        total=total,
        price_score=price_points,
        moq_score=moq_points,
        information_score=information_points,
        price_clarity_score=clarity_points,
        label=score_label(total),
        is_price_outlier=is_outlier,
    )


def score_alibaba_listings(
    products: Sequence[object],
    stats: AlibabaPriceStatistics | None = None,
) -> list[AlibabaListingScore]:
    """Score every listing. Reuses the validated statistics; never re-derives them."""

    product_list = list(products)
    statistics = stats if stats is not None else calculate_alibaba_price_statistics(product_list)
    usd_values = [
        value
        for value in (_usd_representative(product) for product in product_list)
        if value is not None
    ]
    moq_values = [
        quantity
        for quantity in (
            extract_moq_quantity(getattr(product, "moq", None)) for product in product_list
        )
        if quantity is not None
    ]
    return [
        calculate_listing_score(
            product, usd_values=usd_values, moq_values=moq_values, stats=statistics
        )
        for product in product_list
    ]


__all__ = [
    "CLARITY_POINTS_PARTIAL",
    "CLARITY_POINTS_RANGE",
    "CLARITY_POINTS_SIMPLE",
    "LABEL_EXCELLENT",
    "LABEL_GOOD",
    "LABEL_LOW",
    "LABEL_MIDDLE",
    "LOWER_OUTLIER_PRICE_CAP",
    "MOQ_POINTS",
    "OUTLIER_BADGE",
    "PRICE_POINTS",
    "AlibabaListingScore",
    "calculate_listing_score",
    "extract_moq_quantity",
    "format_score_display",
    "score_alibaba_listings",
    "score_label",
]
