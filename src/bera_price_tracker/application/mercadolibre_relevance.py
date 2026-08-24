"""Deterministic Mercado Libre relevance. Reuses Alibaba token coverage; no AI."""

from __future__ import annotations

from collections.abc import Sequence

from bera_price_tracker.application.alibaba_relevance import (
    AlibabaListingRelevance,
    calculate_listing_relevance,
    format_relevance_display,
    relevance_label,
)

MercadoLibreListingRelevance = AlibabaListingRelevance


def score_mercadolibre_relevance(
    query: object, listings: Sequence[object]
) -> list[MercadoLibreListingRelevance]:
    """Score every listing from its title only."""

    return [
        calculate_listing_relevance(query, getattr(listing, "title", None)) for listing in listings
    ]


__all__ = [
    "MercadoLibreListingRelevance",
    "calculate_listing_relevance",
    "format_relevance_display",
    "relevance_label",
    "score_mercadolibre_relevance",
]
