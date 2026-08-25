"""Generic Facebook Marketplace Venezuela products through the existing Apify client."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from bera_price_tracker.application.facebook_products import (
    FacebookPriceDecision,
    FacebookProductSearchMetrics,
    FacebookProductSearchResult,
    FacebookRejectionReason,
    classify_explicit_facebook_price,
)
from bera_price_tracker.application.facebook_venezuela_price import (
    normalize_facebook_venezuela_price,
)
from bera_price_tracker.domain import Listing, MarketplaceSource, SearchQuery
from bera_price_tracker.infrastructure.providers.apify import (
    ApifyFacebookListing,
    ApifyFacebookMarketplaceClient,
    location_is_out_of_scope,
)

type FacebookProductClock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _required_text(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _safe_currency(value: str | None) -> str:
    if not isinstance(value, str):
        return "UNKNOWN"
    normalized = value.strip().upper()
    if len(normalized) == 3 and normalized.isascii() and normalized.isalpha():
        return normalized
    return "UNKNOWN"


@dataclass(slots=True)
class FacebookMarketplaceProductSearch:
    """Map one Apify run into generic priced listings without H0019 classification."""

    client: ApifyFacebookMarketplaceClient
    clock: FacebookProductClock = _utc_now

    def search(self, query: str, city: str, limit: int) -> FacebookProductSearchResult:
        response = self.client.fetch(keyword=query, city=city, limit=limit)
        reasons: list[FacebookRejectionReason] = [
            FacebookRejectionReason.SOURCE_ERROR for _ in range(response.source_errors)
        ]
        prepared: dict[str, ApifyFacebookListing] = {}

        invalid_price = 0
        free_price = 0
        out_of_scope_location = 0
        missing_product_id = 0
        empty_title = 0
        duplicate_product_id = 0
        source_error = response.source_errors

        for record in response.records:
            title = _required_text(record.title)
            if title is None:
                empty_title += 1
                reasons.append(FacebookRejectionReason.EMPTY_TITLE)
                continue
            if location_is_out_of_scope(record.location, city):
                out_of_scope_location += 1
                reasons.append(FacebookRejectionReason.OUT_OF_SCOPE_LOCATION)
                continue
            price_decision = classify_explicit_facebook_price(record.price, record.formatted_price)
            if price_decision is FacebookPriceDecision.FREE_PRICE:
                free_price += 1
                reasons.append(FacebookRejectionReason.FREE_PRICE)
                continue
            if price_decision is FacebookPriceDecision.INVALID_PRICE:
                invalid_price += 1
                reasons.append(FacebookRejectionReason.INVALID_PRICE)
                continue
            product_id = _required_text(record.product_id)
            if product_id is None:
                missing_product_id += 1
                reasons.append(FacebookRejectionReason.MISSING_PRODUCT_ID)
                continue
            if product_id in prepared:
                duplicate_product_id += 1
                reasons.append(FacebookRejectionReason.DUPLICATE_PRODUCT_ID)
            prepared[product_id] = record

        collected_at = self.clock()
        search_query = SearchQuery(query)
        listings: list[Listing] = []
        for product_id, record in prepared.items():
            title = _required_text(record.title)
            url = _required_text(record.url)
            if title is None or url is None or record.price is None:
                source_error += 1
                reasons.append(FacebookRejectionReason.SOURCE_ERROR)
                continue
            try:
                currency = _safe_currency(record.currency)
                normalized = normalize_facebook_venezuela_price(
                    record.price,
                    currency,
                    _required_text(record.formatted_price),
                )
                listings.append(
                    Listing(
                        source=MarketplaceSource.FACEBOOK_MARKETPLACE,
                        external_id=product_id,
                        title=title,
                        price=record.price,
                        currency=currency,
                        formatted_amount=_required_text(record.formatted_price),
                        location=_required_text(record.location),
                        url=url,
                        query=search_query,
                        collected_at=collected_at,
                        usd_amount=normalized.usd_amount,
                        usd_normalization_status=normalized.normalization_status.value,
                        usd_evidence=normalized.evidence,
                    )
                )
            except (TypeError, ValueError):
                source_error += 1
                reasons.append(FacebookRejectionReason.SOURCE_ERROR)

        metrics = FacebookProductSearchMetrics(
            fetched=response.fetched,
            invalid_price=invalid_price,
            free_price=free_price,
            out_of_scope_location=out_of_scope_location,
            missing_product_id=missing_product_id,
            empty_title=empty_title,
            duplicate_product_id=duplicate_product_id,
            source_error=source_error,
            usable=len(listings),
        )
        return FacebookProductSearchResult(
            listings=tuple(listings),
            metrics=metrics,
            rejection_reasons=tuple(reasons),
        )


__all__ = ["FacebookMarketplaceProductSearch"]
