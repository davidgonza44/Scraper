"""Deterministic provider-neutral relevance for generic Facebook listings."""

from __future__ import annotations

from collections.abc import Sequence

from bera_price_tracker.application.alibaba_relevance import (
    AlibabaListingRelevance,
    calculate_listing_relevance,
    format_relevance_display,
    relevance_label,
)

FacebookListingRelevance = AlibabaListingRelevance


def score_facebook_relevance(
    query: object,
    listings: Sequence[object],
) -> list[FacebookListingRelevance]:
    """Score already-admitted listings by title, offline and without H0019 knowledge."""

    return [
        calculate_listing_relevance(query, getattr(listing, "title", None)) for listing in listings
    ]


__all__ = [
    "FacebookListingRelevance",
    "calculate_listing_relevance",
    "format_relevance_display",
    "relevance_label",
    "score_facebook_relevance",
]
