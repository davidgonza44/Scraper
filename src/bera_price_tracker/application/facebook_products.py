"""Generic, priced-only Facebook Marketplace Venezuela search contracts."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from bera_price_tracker.application.ports import FacebookMarketplaceProductSearchProvider
from bera_price_tracker.domain import Listing

MIN_FACEBOOK_PRODUCT_LIMIT = 1
MAX_FACEBOOK_PRODUCT_LIMIT = 5

_FREE_PRICE_MARKERS = frozenset({"free", "gratis", "gratuito", "gratuita", "sin costo"})
_ZERO_PRICE = re.compile(
    r"^(?:(?:[A-Z]{3}|BS\.?|[$€£])\s*)?[+-]?0+(?:[.,]0+)?"
    r"(?:\s*(?:[A-Z]{3}|BS\.?))?$",
    re.IGNORECASE,
)


class FacebookPriceDecision(StrEnum):
    """Authoritative admission outcome for one provider price."""

    PRICED = "priced"
    FREE_PRICE = "free_price"
    INVALID_PRICE = "invalid_price"


class FacebookRejectionReason(StrEnum):
    """Deterministic rejection categories exposed as aggregate metrics."""

    INVALID_PRICE = "invalid_price"
    FREE_PRICE = "free_price"
    OUT_OF_SCOPE_LOCATION = "out_of_scope_location"
    MISSING_PRODUCT_ID = "missing_product_id"
    EMPTY_TITLE = "empty_title"
    DUPLICATE_PRODUCT_ID = "duplicate_product_id"
    SOURCE_ERROR = "source_error"


@dataclass(frozen=True, slots=True)
class FacebookProductSearchMetrics:
    """Ephemeral counters from one generic Facebook search."""

    fetched: int = 0
    invalid_price: int = 0
    free_price: int = 0
    out_of_scope_location: int = 0
    missing_product_id: int = 0
    empty_title: int = 0
    duplicate_product_id: int = 0
    source_error: int = 0
    usable: int = 0


@dataclass(frozen=True, slots=True)
class FacebookProductSearchResult:
    """Sanitized priced listings and aggregate rejection evidence."""

    listings: tuple[Listing, ...]
    metrics: FacebookProductSearchMetrics
    rejection_reasons: tuple[FacebookRejectionReason, ...] = ()


def _normalized_price_text(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.strip().split())


def classify_explicit_facebook_price(
    amount: Decimal | None,
    formatted_price: str | None,
) -> FacebookPriceDecision:
    """Admit only finite positive Decimals; fail closed on conflicting price text.

    The formatted field is used only to reject unambiguous free/zero markers. It is
    never parsed to reconstruct a missing numeric amount or infer a currency.
    """

    formatted = _normalized_price_text(formatted_price)
    if formatted in _FREE_PRICE_MARKERS:
        return FacebookPriceDecision.FREE_PRICE
    if formatted and _ZERO_PRICE.fullmatch(formatted):
        return FacebookPriceDecision.INVALID_PRICE
    if (
        isinstance(amount, bool)
        or not isinstance(amount, Decimal)
        or not amount.is_finite()
        or amount <= Decimal("0")
    ):
        return FacebookPriceDecision.INVALID_PRICE
    return FacebookPriceDecision.PRICED


def is_explicitly_priced_listing(
    amount: Decimal | None,
    formatted_price: str | None,
) -> bool:
    """Return whether provider fields consistently prove ``Decimal price > 0``."""

    return classify_explicit_facebook_price(amount, formatted_price) is FacebookPriceDecision.PRICED


def validate_facebook_product_search(query: str, city: str, limit: int) -> tuple[str, str, int]:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be blank")
    if not isinstance(city, str) or not city.strip():
        raise ValueError("city must not be blank")
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")
    if not MIN_FACEBOOK_PRODUCT_LIMIT <= limit <= MAX_FACEBOOK_PRODUCT_LIMIT:
        raise ValueError(
            f"limit must be between {MIN_FACEBOOK_PRODUCT_LIMIT} and {MAX_FACEBOOK_PRODUCT_LIMIT}"
        )
    normalized_query = " ".join(query.strip().split())
    normalized_city = " ".join(city.strip().casefold().split())
    return normalized_query, normalized_city, limit


@dataclass(frozen=True, slots=True)
class SearchFacebookMarketplaceProducts:
    """Read-only generic Facebook search; one execute maps to one Actor run."""

    provider: FacebookMarketplaceProductSearchProvider

    def execute(self, query: str, city: str, limit: int) -> FacebookProductSearchResult:
        normalized_query, normalized_city, normalized_limit = validate_facebook_product_search(
            query, city, limit
        )
        return self.provider.search(normalized_query, normalized_city, normalized_limit)


__all__ = [
    "MAX_FACEBOOK_PRODUCT_LIMIT",
    "MIN_FACEBOOK_PRODUCT_LIMIT",
    "FacebookPriceDecision",
    "FacebookProductSearchMetrics",
    "FacebookProductSearchResult",
    "FacebookRejectionReason",
    "SearchFacebookMarketplaceProducts",
    "classify_explicit_facebook_price",
    "is_explicitly_priced_listing",
    "validate_facebook_product_search",
]
