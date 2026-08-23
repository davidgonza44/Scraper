"""Configurable ranking that combines relevance, opportunity and reputation.

Decimal only. This is a derived view score: it never replaces or mutates
opportunity_score, relevance_score or reputation_score. When the reputation
score is unavailable ("Datos insuficientes") its weight is redistributed
among the available components instead of counting the missing score as 0.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

DEFAULT_RELEVANCE_WEIGHT = 50
DEFAULT_OPPORTUNITY_WEIGHT = 30
DEFAULT_REPUTATION_WEIGHT = 20
LOW_MATCH_THRESHOLD = 30
LOW_MATCH_BADGE = "Baja coincidencia"
MAX_RANKING = 100
REPUTATION_UNAVAILABLE_TEXT = "sin datos suficientes"
WEIGHTS_REDISTRIBUTED_NOTE = "Los pesos se redistribuyeron entre las métricas disponibles."
WEIGHT_RANGE_ERROR = "Cada peso debe estar entre 0 y 100."
WEIGHT_TOTAL_ERROR = "Los pesos deben sumar 100."
_HUNDRED = Decimal("100")
_INTEGER = Decimal("1")
_TENTH = Decimal("0.1")
_ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class RankingWeights:
    """Requested weights (percent points) for the three base scores."""

    relevance: int
    opportunity: int
    reputation: int

    def total(self) -> int:
        return self.relevance + self.opportunity + self.reputation


DEFAULT_WEIGHTS = RankingWeights(
    relevance=DEFAULT_RELEVANCE_WEIGHT,
    opportunity=DEFAULT_OPPORTUNITY_WEIGHT,
    reputation=DEFAULT_REPUTATION_WEIGHT,
)
PRESET_BALANCED = RankingWeights(relevance=40, opportunity=30, reputation=30)
PRESET_MORE_RELEVANT = RankingWeights(relevance=60, opportunity=25, reputation=15)
PRESET_MORE_OPPORTUNITY = RankingWeights(relevance=35, opportunity=45, reputation=20)
PRESET_MORE_REPUTATION = RankingWeights(relevance=35, opportunity=20, reputation=45)


@dataclass(frozen=True, slots=True)
class RankingComponent:
    """One base score with its requested weight and availability."""

    score: int
    weight: int
    available: bool


@dataclass(frozen=True, slots=True)
class AlibabaRanking:
    """Blend of the base scores with the effective (renormalized) weights."""

    ranking_score: int
    relevance_weight_effective: Decimal
    opportunity_weight_effective: Decimal
    reputation_weight_effective: Decimal
    reputation_used: bool


def clamp_weight(value: object, default: int) -> int:
    """Keep one weight in 0–100. Invalid input falls back to ``default``."""

    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return max(0, min(MAX_RANKING, value))
    if isinstance(value, Decimal) and value.is_finite():
        return max(0, min(MAX_RANKING, int(value)))
    return default


def validate_ranking_weights(relevance: int, opportunity: int, reputation: int) -> str:
    """Local validation only. Returns '' when valid, a user message otherwise."""

    for value in (relevance, opportunity, reputation):
        if isinstance(value, bool) or not isinstance(value, int):
            return WEIGHT_RANGE_ERROR
        if value < 0 or value > MAX_RANKING:
            return WEIGHT_RANGE_ERROR
    if relevance + opportunity + reputation != MAX_RANKING:
        return WEIGHT_TOTAL_ERROR
    return ""


def _clamp_score(value: int) -> int:
    return max(0, min(MAX_RANKING, int(value)))


def combine_ranking_components(
    components: Sequence[RankingComponent],
) -> tuple[Decimal, list[Decimal]]:
    """Blend available components, renormalizing weights over the available ones.

    Returns the blended score and the effective weight (percent, one decimal)
    for each component in order. Unavailable components get effective weight 0
    and never contribute: absence is not the same as a score of 0.
    """

    available_weight = sum(
        (Decimal(component.weight) for component in components if component.available),
        _ZERO,
    )
    if available_weight == 0:
        return _ZERO, [_ZERO for _ in components]
    weighted_sum = sum(
        (
            Decimal(_clamp_score(component.score)) * Decimal(component.weight)
            for component in components
            if component.available
        ),
        _ZERO,
    )
    effective: list[Decimal] = []
    for component in components:
        if not component.available:
            effective.append(_ZERO)
            continue
        share = (Decimal(component.weight) / available_weight * _HUNDRED).quantize(
            _TENTH, rounding=ROUND_HALF_EVEN
        )
        effective.append(share)
    return weighted_sum / available_weight, effective


def calculate_alibaba_ranking(
    opportunity_score: int,
    relevance_score: int,
    reputation_score: int | None = None,
    weights: RankingWeights = DEFAULT_WEIGHTS,
) -> AlibabaRanking:
    """Blend the three base scores. ``reputation_score=None`` means unavailable."""

    reputation_used = reputation_score is not None
    components = (
        RankingComponent(score=relevance_score, weight=weights.relevance, available=True),
        RankingComponent(score=opportunity_score, weight=weights.opportunity, available=True),
        RankingComponent(
            score=0 if reputation_score is None else reputation_score,
            weight=weights.reputation,
            available=reputation_used,
        ),
    )
    blended, effective = combine_ranking_components(components)
    score = int(blended.quantize(_INTEGER, rounding=ROUND_HALF_EVEN))
    return AlibabaRanking(
        ranking_score=max(0, min(MAX_RANKING, score)),
        relevance_weight_effective=effective[0],
        opportunity_weight_effective=effective[1],
        reputation_weight_effective=effective[2],
        reputation_used=reputation_used,
    )


def format_ranking_display(score: int) -> str:
    return f"{score}/100"


def _format_percent(value: Decimal) -> str:
    quantized = value.quantize(_TENTH, rounding=ROUND_HALF_EVEN)
    if quantized == quantized.to_integral_value():
        return f"{int(quantized)}%"
    return f"{quantized}%"


def format_ranking_tooltip(ranking: AlibabaRanking) -> str:
    relevance = f"Relevancia: {_format_percent(ranking.relevance_weight_effective)}"
    opportunity = f"Oportunidad: {_format_percent(ranking.opportunity_weight_effective)}"
    if ranking.reputation_used:
        reputation = f"Reputación: {_format_percent(ranking.reputation_weight_effective)}"
        return f"{relevance} · {opportunity} · {reputation}"
    return (
        f"{relevance} · {opportunity} · Reputación: {REPUTATION_UNAVAILABLE_TEXT}. "
        f"{WEIGHTS_REDISTRIBUTED_NOTE}"
    )


def is_low_match(relevance_score: int) -> bool:
    return relevance_score < LOW_MATCH_THRESHOLD


__all__ = [
    "DEFAULT_OPPORTUNITY_WEIGHT",
    "DEFAULT_RELEVANCE_WEIGHT",
    "DEFAULT_REPUTATION_WEIGHT",
    "DEFAULT_WEIGHTS",
    "LOW_MATCH_BADGE",
    "LOW_MATCH_THRESHOLD",
    "MAX_RANKING",
    "PRESET_BALANCED",
    "PRESET_MORE_OPPORTUNITY",
    "PRESET_MORE_RELEVANT",
    "PRESET_MORE_REPUTATION",
    "REPUTATION_UNAVAILABLE_TEXT",
    "WEIGHTS_REDISTRIBUTED_NOTE",
    "WEIGHT_RANGE_ERROR",
    "WEIGHT_TOTAL_ERROR",
    "AlibabaRanking",
    "RankingComponent",
    "RankingWeights",
    "calculate_alibaba_ranking",
    "clamp_weight",
    "combine_ranking_components",
    "format_ranking_display",
    "format_ranking_tooltip",
    "is_low_match",
    "validate_ranking_weights",
]
