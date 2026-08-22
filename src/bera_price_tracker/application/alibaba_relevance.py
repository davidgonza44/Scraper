"""Relevance score (0-100): how well a listing title matches the user's query.

Deterministic and offline: normalized whole-token coverage plus a bounded
exact-phrase bonus. No AI, no embeddings, no fuzzy matching. Independent from
the opportunity score; the two are never combined.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

TOKEN_COVERAGE_POINTS = Decimal("80")
EXACT_PHRASE_BONUS = 20
MAX_RELEVANCE = 100

RELEVANCE_HIGH = "Muy relevante"
RELEVANCE_GOOD = "Relevante"
RELEVANCE_PARTIAL = "Parcialmente relevante"
RELEVANCE_LOW = "Poco relevante"

_NON_ALPHANUMERIC = re.compile(r"[^0-9a-z]+")
_INTEGER = Decimal("1")


@dataclass(frozen=True, slots=True)
class AlibabaListingRelevance:
    """Query-match summary for one listing."""

    relevance_score: int
    matched_tokens: int
    total_query_tokens: int
    exact_phrase_match: bool


def normalize_tokens(text: object) -> list[str]:
    """Casefold, NFKD, strip diacritics, punctuation to spaces, tokenize."""

    if not isinstance(text, str):
        return []
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    stripped = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return [token for token in _NON_ALPHANUMERIC.split(stripped) if token]


def _unique_in_order(tokens: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            unique.append(token)
    return unique


def _contains_phrase(title_tokens: Sequence[str], query_tokens: Sequence[str]) -> bool:
    """Whole-token contiguous match of the full normalized query."""

    size = len(query_tokens)
    if size == 0 or size > len(title_tokens):
        return False
    phrase = list(query_tokens)
    return any(
        list(title_tokens[start : start + size]) == phrase
        for start in range(len(title_tokens) - size + 1)
    )


def calculate_listing_relevance(query: object, title: object) -> AlibabaListingRelevance:
    """Score one title against the search query. Empty query scores 0 safely."""

    query_tokens = _unique_in_order(normalize_tokens(query))
    total = len(query_tokens)
    if total == 0:
        return AlibabaListingRelevance(
            relevance_score=0,
            matched_tokens=0,
            total_query_tokens=0,
            exact_phrase_match=False,
        )
    title_tokens = normalize_tokens(title)
    title_token_set = set(title_tokens)
    matched = sum(1 for token in query_tokens if token in title_token_set)
    coverage = Decimal(matched) / Decimal(total)
    points = int((coverage * TOKEN_COVERAGE_POINTS).quantize(_INTEGER, rounding=ROUND_HALF_EVEN))
    exact_phrase = _contains_phrase(title_tokens, normalize_tokens(query))
    if exact_phrase:
        points += EXACT_PHRASE_BONUS
    return AlibabaListingRelevance(
        relevance_score=min(MAX_RELEVANCE, points),
        matched_tokens=matched,
        total_query_tokens=total,
        exact_phrase_match=exact_phrase,
    )


def score_alibaba_relevance(
    query: object, products: Sequence[object]
) -> list[AlibabaListingRelevance]:
    """Relevance for every listing, from the title only."""

    return [
        calculate_listing_relevance(query, getattr(product, "title", None)) for product in products
    ]


def relevance_label(score: int) -> str:
    if score >= 80:
        return RELEVANCE_HIGH
    if score >= 60:
        return RELEVANCE_GOOD
    if score >= 30:
        return RELEVANCE_PARTIAL
    return RELEVANCE_LOW


def format_relevance_display(score: int) -> str:
    return f"{score}/100"


__all__ = [
    "EXACT_PHRASE_BONUS",
    "MAX_RELEVANCE",
    "RELEVANCE_GOOD",
    "RELEVANCE_HIGH",
    "RELEVANCE_LOW",
    "RELEVANCE_PARTIAL",
    "TOKEN_COVERAGE_POINTS",
    "AlibabaListingRelevance",
    "calculate_listing_relevance",
    "format_relevance_display",
    "normalize_tokens",
    "relevance_label",
    "score_alibaba_relevance",
]
