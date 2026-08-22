"""Configurable ranking that combines relevance and opportunity. Decimal only.

This is a derived view score. It does not replace or mutate opportunity_score
or relevance_score, and it is not a reputation or reliability judgment.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

DEFAULT_RELEVANCE_WEIGHT = 60
PRESET_BALANCED = 50
PRESET_MORE_RELEVANT = 75
PRESET_MORE_OPPORTUNITY = 25
LOW_MATCH_THRESHOLD = 30
LOW_MATCH_BADGE = "Baja coincidencia"
MAX_RANKING = 100
_HUNDRED = Decimal("100")
_INTEGER = Decimal("1")


@dataclass(frozen=True, slots=True)
class AlibabaRanking:
    """Weighted blend of the two existing listing scores."""

    ranking_score: int
    relevance_weight: int
    opportunity_weight: int


def clamp_relevance_weight(value: object) -> int:
    """Keep the slider in 0–100. Invalid input falls back to the default."""

    if isinstance(value, bool):
        return DEFAULT_RELEVANCE_WEIGHT
    if isinstance(value, int):
        return max(0, min(MAX_RANKING, value))
    if isinstance(value, Decimal) and value.is_finite():
        return max(0, min(MAX_RANKING, int(value)))
    return DEFAULT_RELEVANCE_WEIGHT


def calculate_alibaba_ranking(
    opportunity_score: int,
    relevance_score: int,
    relevance_weight: int,
) -> AlibabaRanking:
    """Blend the two scores. ``opportunity_weight`` is always 100 − relevance."""

    relevance_points = max(0, min(MAX_RANKING, int(relevance_score)))
    opportunity_points = max(0, min(MAX_RANKING, int(opportunity_score)))
    weight = clamp_relevance_weight(relevance_weight)
    complement = MAX_RANKING - weight
    relevance_share = Decimal(weight) / _HUNDRED
    opportunity_share = Decimal(complement) / _HUNDRED
    blended = (
        Decimal(relevance_points) * relevance_share
        + Decimal(opportunity_points) * opportunity_share
    )
    score = int(blended.quantize(_INTEGER, rounding=ROUND_HALF_EVEN))
    return AlibabaRanking(
        ranking_score=max(0, min(MAX_RANKING, score)),
        relevance_weight=weight,
        opportunity_weight=complement,
    )


def format_ranking_display(score: int) -> str:
    return f"{score}/100"


def format_ranking_tooltip(relevance_weight: int) -> str:
    weight = clamp_relevance_weight(relevance_weight)
    return f"Ranking = {weight}% relevancia + {MAX_RANKING - weight}% oportunidad"


def is_low_match(relevance_score: int) -> bool:
    return relevance_score < LOW_MATCH_THRESHOLD


__all__ = [
    "DEFAULT_RELEVANCE_WEIGHT",
    "LOW_MATCH_BADGE",
    "LOW_MATCH_THRESHOLD",
    "MAX_RANKING",
    "PRESET_BALANCED",
    "PRESET_MORE_OPPORTUNITY",
    "PRESET_MORE_RELEVANT",
    "AlibabaRanking",
    "calculate_alibaba_ranking",
    "clamp_relevance_weight",
    "format_ranking_display",
    "format_ranking_tooltip",
    "is_low_match",
]
