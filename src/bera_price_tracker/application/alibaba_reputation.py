"""Supplier reputation score from observed Alibaba supplier signals. Decimal only.

Independent from opportunity, relevance and ranking. Missing evidence is not
treated as poor reputation: unavailable components are omitted and the total
is renormalized over the available weight.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import cast

SERVICE_WEIGHT = Decimal("35")
REVIEW_SCORE_WEIGHT = Decimal("30")
YEARS_WEIGHT = Decimal("20")
REVIEW_COUNT_WEIGHT = Decimal("15")
TOTAL_WEIGHT = SERVICE_WEIGHT + REVIEW_SCORE_WEIGHT + YEARS_WEIGHT + REVIEW_COUNT_WEIGHT
RATING_MAX = Decimal("5")
YEARS_CAP = Decimal("10")
MIN_SIGNALS = 2
MIN_COVERAGE = Decimal("50")
_HUNDRED = Decimal("100")
_INTEGER = Decimal("1")
_TENTH = Decimal("0.1")
_YEAR_NUMBER = re.compile(r"(\d+(?:\.\d+)?)")

LABEL_VERY_SOLID = "Señales muy sólidas"
LABEL_SOLID = "Señales sólidas"
LABEL_MODERATE = "Señales moderadas"
LABEL_LIMITED = "Señales limitadas"
LABEL_INSUFFICIENT = "Datos insuficientes"
COVERAGE_HIGH = "Cobertura alta"
COVERAGE_MEDIUM = "Cobertura media"
COVERAGE_LIMITED = "Cobertura limitada"
UNAVAILABLE_DISPLAY = "—"


@dataclass(frozen=True, slots=True)
class SupplierReputationScore:
    """One listing's supplier-signal score. ``score`` is None when evidence is thin."""

    score: int | None
    label: str
    evidence_coverage: int
    evidence_label: str
    service_value: Decimal | None
    service_points: Decimal | None
    review_score_value: Decimal | None
    review_score_points: Decimal | None
    years: Decimal | None
    years_points: Decimal | None
    review_count: Decimal | None
    review_count_points: Decimal | None
    available_signal_count: int


def _field(source: object, *names: str) -> object:
    for name in names:
        if isinstance(source, Mapping):
            if name in source:
                return cast(Mapping[str, object], source).get(name)
        elif hasattr(source, name):
            return getattr(source, name)
    return None


def parse_rating_0_5(raw: object) -> Decimal | None:
    """Parse a 0–5 rating. Out of range or unreadable values stay unavailable."""

    if isinstance(raw, bool):
        return None
    if isinstance(raw, Decimal):
        value = raw
    elif isinstance(raw, (int, float)):
        value = Decimal(str(raw))
    elif isinstance(raw, str):
        text = raw.strip().replace(",", ".")
        if not text:
            return None
        try:
            value = Decimal(text)
        except InvalidOperation:
            return None
    else:
        return None
    if not value.is_finite() or value < 0 or value > RATING_MAX:
        return None
    return value


def parse_gold_supplier_years(raw: object) -> Decimal | None:
    """Parse ``6 yrs`` / ``1 yr`` conservatively. Does not invent a value."""

    if isinstance(raw, bool):
        return None
    if isinstance(raw, Decimal):
        value = raw
    elif isinstance(raw, int):
        value = Decimal(raw)
    elif isinstance(raw, str):
        match = _YEAR_NUMBER.search(raw)
        if match is None:
            return None
        try:
            value = Decimal(match.group(1))
        except InvalidOperation:
            return None
    else:
        return None
    if not value.is_finite() or value < 0:
        return None
    return value


def parse_review_count(raw: object) -> Decimal | None:
    """Parse a review count. Zero is valid; unreadable text is unavailable."""

    if isinstance(raw, bool):
        return None
    if isinstance(raw, Decimal):
        value = raw
    elif isinstance(raw, (int, float)):
        value = Decimal(str(raw))
    elif isinstance(raw, str):
        text = raw.strip().replace(",", "")
        if not text:
            return None
        try:
            value = Decimal(text)
        except InvalidOperation:
            return None
    else:
        return None
    if not value.is_finite() or value < 0:
        return None
    return value


def review_count_points(count: Decimal) -> Decimal:
    """Bounded evidence from review volume. Quality of ratings is scored separately."""

    if count <= 0:
        return Decimal("0")
    if count <= 9:
        return Decimal("3")
    if count <= 24:
        return Decimal("6")
    if count <= 49:
        return Decimal("9")
    if count <= 99:
        return Decimal("12")
    return Decimal("15")


def _points_from_rating(value: Decimal, weight: Decimal) -> Decimal:
    return (value / RATING_MAX) * weight


def _years_points(years: Decimal) -> Decimal:
    capped = years if years < YEARS_CAP else YEARS_CAP
    return (capped / YEARS_CAP) * YEARS_WEIGHT


def reputation_label(score: int | None) -> str:
    if score is None:
        return LABEL_INSUFFICIENT
    if score >= 85:
        return LABEL_VERY_SOLID
    if score >= 70:
        return LABEL_SOLID
    if score >= 50:
        return LABEL_MODERATE
    return LABEL_LIMITED


def evidence_label(coverage: int) -> str:
    if coverage >= 80:
        return COVERAGE_HIGH
    if coverage >= 60:
        return COVERAGE_MEDIUM
    return COVERAGE_LIMITED


def format_reputation_display(score: int | None) -> str:
    if score is None:
        return UNAVAILABLE_DISPLAY
    return f"{score}/100"


def format_coverage_display(coverage: int) -> str:
    return f"Cobertura de datos: {coverage}%"


def format_component_points(points: Decimal | None, weight: Decimal) -> str:
    if points is None:
        return UNAVAILABLE_DISPLAY
    quantized = points.quantize(_TENTH, rounding=ROUND_HALF_EVEN)
    if quantized == quantized.to_integral_value():
        return f"{int(quantized)}/{int(weight)}"
    return f"{quantized}/{int(weight)}"


def calculate_supplier_reputation(source: object) -> SupplierReputationScore:
    """Score one listing from supplier signals only. Deterministic and offline."""

    service = parse_rating_0_5(_field(source, "supplier_service_score", "supplierServiceScore"))
    review = parse_rating_0_5(_field(source, "review_score", "reviewScore"))
    years = parse_gold_supplier_years(_field(source, "gold_supplier_years", "goldSupplierYears"))
    count = parse_review_count(_field(source, "review_count", "reviewCount"))

    service_points = _points_from_rating(service, SERVICE_WEIGHT) if service is not None else None
    review_points = _points_from_rating(review, REVIEW_SCORE_WEIGHT) if review is not None else None
    years_points = _years_points(years) if years is not None else None
    count_points = review_count_points(count) if count is not None else None

    components: list[tuple[Decimal, Decimal]] = []
    if service_points is not None:
        components.append((SERVICE_WEIGHT, service_points))
    if review_points is not None:
        components.append((REVIEW_SCORE_WEIGHT, review_points))
    if years_points is not None:
        components.append((YEARS_WEIGHT, years_points))
    if count_points is not None:
        components.append((REVIEW_COUNT_WEIGHT, count_points))

    available = sum((weight for weight, _points in components), Decimal("0"))
    earned = sum((points for _weight, points in components), Decimal("0"))
    coverage = (
        int((available / TOTAL_WEIGHT * _HUNDRED).quantize(_INTEGER, rounding=ROUND_HALF_EVEN))
        if TOTAL_WEIGHT
        else 0
    )
    signals = len(components)
    score: int | None = None
    if signals >= MIN_SIGNALS and available >= MIN_COVERAGE and available > 0:
        score = int((earned / available * _HUNDRED).quantize(_INTEGER, rounding=ROUND_HALF_EVEN))
        score = max(0, min(100, score))
    return SupplierReputationScore(
        score=score,
        label=reputation_label(score),
        evidence_coverage=coverage,
        evidence_label=evidence_label(coverage),
        service_value=service,
        service_points=service_points,
        review_score_value=review,
        review_score_points=review_points,
        years=years,
        years_points=years_points,
        review_count=count,
        review_count_points=count_points,
        available_signal_count=signals,
    )


def score_alibaba_reputation(products: list[object]) -> list[SupplierReputationScore]:
    return [calculate_supplier_reputation(product) for product in products]


__all__ = [
    "COVERAGE_HIGH",
    "COVERAGE_LIMITED",
    "COVERAGE_MEDIUM",
    "LABEL_INSUFFICIENT",
    "LABEL_LIMITED",
    "LABEL_MODERATE",
    "LABEL_SOLID",
    "LABEL_VERY_SOLID",
    "REVIEW_COUNT_WEIGHT",
    "REVIEW_SCORE_WEIGHT",
    "SERVICE_WEIGHT",
    "UNAVAILABLE_DISPLAY",
    "YEARS_WEIGHT",
    "SupplierReputationScore",
    "calculate_supplier_reputation",
    "evidence_label",
    "format_component_points",
    "format_coverage_display",
    "format_reputation_display",
    "parse_gold_supplier_years",
    "parse_rating_0_5",
    "parse_review_count",
    "reputation_label",
    "review_count_points",
    "score_alibaba_reputation",
]
