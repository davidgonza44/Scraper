"""Facebook Marketplace acquisition through Apify or Bright Data."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from urllib.parse import urlsplit

from bera_price_tracker.application import (
    ClassificationSource,
    FinalClassification,
    HybridProductClassifier,
    ProductCandidate,
    SanitizedProductCandidate,
    normalize_facebook_venezuela_price,
)
from bera_price_tracker.config import MAX_FACEBOOK_RECORD_LIMIT
from bera_price_tracker.domain import (
    BrakePosition,
    ClassificationDecision,
    Listing,
    MarketplaceSource,
    NormalizedPrice,
    SearchQuery,
    is_h0019_other_application,
)
from bera_price_tracker.infrastructure.providers.apify import (
    ApifyFacebookListing,
    ApifyFacebookMarketplaceClient,
    ApifyFacebookResult,
    location_is_out_of_scope,
)
from bera_price_tracker.infrastructure.providers.bright_data import (
    BrightDataFacebookCandidate,
    BrightDataFacebookMarketplaceClient,
    BrightDataFacebookResult,
)

type FacebookClock = Callable[[], datetime]

MAX_EXPLANATION_TITLE_LENGTH = 120
SOURCE_ERROR_REASON = "source_error: bad_input"
NON_VE_REASON = "non_ve"
INVALID_PRICE_REASON = "invalid_price"
OUT_OF_SCOPE_LOCATION_REASON = "out_of_scope_location"
DUPLICATE_REASON = "duplicate_product_id"


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class FacebookCollectionMetrics:
    """Ephemeral counters for one Facebook provider execution."""

    fetched: int = 0
    source_errors: int = 0
    non_ve: int = 0
    invalid_price: int = 0
    out_of_scope_location: int = 0
    deterministic_relevant: int = 0
    deterministic_irrelevant: int = 0
    ai_requested: int = 0
    ai_relevant: int = 0
    ai_irrelevant: int = 0
    review: int = 0
    duplicates: int = 0
    persisted: int = 0


class FacebookCandidateOutcome(StrEnum):
    """Display-only outcome of one candidate in an explained execution."""

    RELEVANT = "RELEVANT"
    IRRELEVANT = "IRRELEVANT"
    REVIEW = "REVIEW"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True, slots=True, kw_only=True)
class FacebookCandidateExplanation:
    """Sanitized account of why one candidate was accepted or rejected.

    Every field is display-only. Raw provider payloads, descriptions, contact data
    and AI prompts never reach this boundary.
    """

    outcome: FacebookCandidateOutcome
    reason: str
    title: str | None = None
    price: str | None = None
    currency: str | None = None
    classification_source: str | None = None
    product_type: str | None = None
    h0019_match: str | None = None
    bike_models: tuple[str, ...] = ()
    other_compatibility: tuple[str, ...] = ()
    position: str | None = None
    location: str | None = None
    usd_amount: Decimal | None = None
    usd_normalization_status: str | None = None


_OUTCOME_BY_DECISION: dict[ClassificationDecision, FacebookCandidateOutcome] = {
    ClassificationDecision.RELEVANT: FacebookCandidateOutcome.RELEVANT,
    ClassificationDecision.IRRELEVANT: FacebookCandidateOutcome.IRRELEVANT,
    ClassificationDecision.REVIEW: FacebookCandidateOutcome.REVIEW,
}


def _explanation_title(value: str | None) -> str | None:
    if value is None:
        return None
    sanitized = SanitizedProductCandidate(title=value).title
    if not sanitized:
        return None
    return sanitized[:MAX_EXPLANATION_TITLE_LENGTH].rstrip()


def _classification_reason(classification: FinalClassification) -> str:
    rationale = (classification.rationale or "").strip()
    if rationale:
        return rationale
    if classification.reasons:
        return ", ".join(classification.reasons)
    return "no recorded reason"


def _h0019_match(classification: FinalClassification) -> str | None:
    matches = tuple(model.value for model in classification.bike_models) + tuple(
        value for value in classification.other_compatibility if is_h0019_other_application(value)
    )
    return ", ".join(matches) if matches else None


def _source_error_explanation() -> FacebookCandidateExplanation:
    return FacebookCandidateExplanation(
        outcome=FacebookCandidateOutcome.SKIPPED,
        reason=SOURCE_ERROR_REASON,
    )


def _skipped_explanation(
    record: BrightDataFacebookCandidate | ApifyFacebookListing,
    reason: str,
) -> FacebookCandidateExplanation:
    return FacebookCandidateExplanation(
        outcome=FacebookCandidateOutcome.SKIPPED,
        reason=reason,
        title=_explanation_title(record.title),
        location=_explanation_title(record.location),
    )


def _facebook_currency(record: BrightDataFacebookCandidate | ApifyFacebookListing) -> str:
    currency = (record.currency or "").strip().upper()
    return currency or "UNKNOWN"


def _facebook_formatted(record: BrightDataFacebookCandidate | ApifyFacebookListing) -> str | None:
    formatted = getattr(record, "formatted_price", None)
    if isinstance(formatted, str) and formatted.strip():
        return formatted.strip()
    return None


def _apply_facebook_venezuela_price(
    price: Decimal,
    record: BrightDataFacebookCandidate | ApifyFacebookListing,
) -> tuple[str, NormalizedPrice]:
    normalized = normalize_facebook_venezuela_price(
        price,
        _facebook_currency(record),
        _facebook_formatted(record),
    )
    return _facebook_currency(record), normalized


def _classified_explanation(
    record: BrightDataFacebookCandidate | ApifyFacebookListing,
    price: Decimal,
    classification: FinalClassification,
) -> FacebookCandidateExplanation:
    currency = _facebook_currency(record)
    normalized = normalize_facebook_venezuela_price(price, currency, _facebook_formatted(record))
    return FacebookCandidateExplanation(
        outcome=_OUTCOME_BY_DECISION[classification.decision],
        reason=_classification_reason(classification),
        title=_explanation_title(record.title),
        price=str(price),
        currency=currency,
        usd_amount=normalized.usd_amount,
        usd_normalization_status=normalized.normalization_status.value,
        classification_source=classification.classification_source.value,
        product_type=classification.product_type.value,
        h0019_match=_h0019_match(classification),
        bike_models=tuple(model.value for model in classification.bike_models),
        other_compatibility=classification.other_compatibility,
        position=(
            None
            if classification.position is BrakePosition.UNKNOWN
            else classification.position.value
        ),
        location=_explanation_title(record.location),
    )


def _decimal_price(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not price.is_finite() or price <= Decimal("0"):
        return None
    return price


def _required_record_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _has_valid_listing_fields(record: BrightDataFacebookCandidate) -> bool:
    currency = _required_record_text(record.currency)
    url = _required_record_text(record.url)
    if currency is None or len(currency) != 3 or not currency.isascii() or not currency.isalpha():
        return False
    if url is None:
        return False
    parsed = urlsplit(url)
    return (
        parsed.scheme.casefold() in {"http", "https"}
        and parsed.hostname is not None
        and parsed.username is None
        and parsed.password is None
    )


@dataclass(slots=True)
class FacebookMarketplaceProvider:
    """Return only H0019-relevant Facebook Marketplace listings."""

    client: BrightDataFacebookMarketplaceClient | ApifyFacebookMarketplaceClient
    classifier: HybridProductClassifier
    city: str = "caracas"
    record_limit: int = 5
    clock: FacebookClock = _utc_now
    _last_metrics: FacebookCollectionMetrics = field(
        init=False,
        default_factory=FacebookCollectionMetrics,
        repr=False,
    )
    _last_explanations: tuple[FacebookCandidateExplanation, ...] = field(
        init=False,
        default=(),
        repr=False,
    )

    def __post_init__(self) -> None:
        city = " ".join(self.city.strip().split()).casefold()
        if not city:
            raise ValueError("city must not be blank")
        self.city = city
        if isinstance(self.record_limit, bool) or not isinstance(self.record_limit, int):
            raise TypeError("record_limit must be an integer")
        if not 1 <= self.record_limit <= MAX_FACEBOOK_RECORD_LIMIT:
            raise ValueError(f"record_limit must be between 1 and {MAX_FACEBOOK_RECORD_LIMIT}")

    @property
    def source(self) -> MarketplaceSource:
        return MarketplaceSource.FACEBOOK_MARKETPLACE

    @property
    def last_metrics(self) -> FacebookCollectionMetrics:
        """Return counters from the most recent completed search."""

        return self._last_metrics

    @property
    def last_explanations(self) -> tuple[FacebookCandidateExplanation, ...]:
        """Return sanitized per-candidate outcomes from the most recent search."""

        return self._last_explanations

    def search(self, query: SearchQuery) -> list[Listing]:
        """Acquire, classify and normalize one cost-bounded Facebook search."""

        if not isinstance(query, SearchQuery):
            raise TypeError("query must be a SearchQuery")

        response = self.client.fetch(
            keyword=query.text,
            city=self.city,
            limit=self.record_limit,
        )
        if isinstance(response, ApifyFacebookResult):
            return self._search_apify(query, response)
        return self._search_bright_data(query, response)

    def _search_bright_data(
        self,
        query: SearchQuery,
        response: BrightDataFacebookResult,
    ) -> list[Listing]:
        source_errors = response.source_errors
        non_ve = 0
        invalid_price = 0
        duplicates = 0
        prepared: dict[str, tuple[BrightDataFacebookCandidate, Decimal]] = {}
        explanations: list[FacebookCandidateExplanation] = [
            _source_error_explanation() for _ in range(response.source_errors)
        ]

        for record in response.records:
            if record.country_code is None:
                source_errors += 1
                explanations.append(_source_error_explanation())
                continue
            if record.country_code != "VE":
                non_ve += 1
                explanations.append(_skipped_explanation(record, NON_VE_REASON))
                continue
            price = _decimal_price(record.final_price)
            if price is None:
                invalid_price += 1
                explanations.append(_skipped_explanation(record, INVALID_PRICE_REASON))
                continue
            product_id = _required_record_text(record.product_id)
            title = _required_record_text(record.title)
            if product_id is None or title is None or not _has_valid_listing_fields(record):
                source_errors += 1
                explanations.append(_source_error_explanation())
                continue
            if product_id in prepared:
                duplicates += 1
                superseded, _ = prepared[product_id]
                explanations.append(_skipped_explanation(superseded, DUPLICATE_REASON))
            prepared[product_id] = (record, price)

        collected_at = self.clock()
        deterministic_relevant = 0
        deterministic_irrelevant = 0
        ai_requested = 0
        ai_relevant = 0
        ai_irrelevant = 0
        review = 0
        listings: list[Listing] = []

        for product_id, (record, price) in prepared.items():
            classification = self.classifier.classify(
                ProductCandidate(title=record.title or "", description=record.description)
            )
            if classification.classification_source is ClassificationSource.DETERMINISTIC:
                if classification.decision is ClassificationDecision.RELEVANT:
                    deterministic_relevant += 1
                else:
                    deterministic_irrelevant += 1
            else:
                ai_requested += 1
                if classification.decision is ClassificationDecision.RELEVANT:
                    ai_relevant += 1
                elif classification.decision is ClassificationDecision.IRRELEVANT:
                    ai_irrelevant += 1

            if classification.decision is ClassificationDecision.REVIEW:
                review += 1
            elif classification.decision is ClassificationDecision.RELEVANT:
                try:
                    currency, normalized = _apply_facebook_venezuela_price(price, record)
                    listings.append(
                        Listing(
                            source=self.source,
                            external_id=product_id,
                            title=record.title or "",
                            price=price,
                            currency=currency,
                            url=record.url or "",
                            query=query,
                            collected_at=collected_at,
                            location=record.location,
                            product_condition=record.condition,
                            formatted_amount=_facebook_formatted(record),
                            usd_amount=normalized.usd_amount,
                            usd_normalization_status=normalized.normalization_status.value,
                            usd_evidence=normalized.evidence,
                        )
                    )
                except (TypeError, ValueError):
                    source_errors += 1
                    explanations.append(_source_error_explanation())
                    continue
            explanations.append(_classified_explanation(record, price, classification))

        self._last_explanations = tuple(explanations)
        self._last_metrics = FacebookCollectionMetrics(
            fetched=response.fetched,
            source_errors=source_errors,
            non_ve=non_ve,
            invalid_price=invalid_price,
            deterministic_relevant=deterministic_relevant,
            deterministic_irrelevant=deterministic_irrelevant,
            ai_requested=ai_requested,
            ai_relevant=ai_relevant,
            ai_irrelevant=ai_irrelevant,
            review=review,
            duplicates=duplicates,
            persisted=len(listings),
        )
        return listings

    def _search_apify(self, query: SearchQuery, response: ApifyFacebookResult) -> list[Listing]:
        invalid_price = 0
        out_of_scope_location = 0
        duplicates = 0
        prepared: dict[str, tuple[ApifyFacebookListing, Decimal]] = {}
        explanations: list[FacebookCandidateExplanation] = []

        for record in response.records:
            title = _required_record_text(record.title)
            if title is None:
                explanations.append(
                    FacebookCandidateExplanation(
                        outcome=FacebookCandidateOutcome.SKIPPED,
                        reason="empty_title",
                    )
                )
                continue
            if location_is_out_of_scope(record.location, self.city):
                out_of_scope_location += 1
                explanations.append(_skipped_explanation(record, OUT_OF_SCOPE_LOCATION_REASON))
                continue
            if record.price is None:
                invalid_price += 1
                explanations.append(_skipped_explanation(record, INVALID_PRICE_REASON))
                continue
            product_id = _required_record_text(record.product_id)
            if product_id is None:
                explanations.append(_skipped_explanation(record, "missing_product_id"))
                continue
            if product_id in prepared:
                duplicates += 1
                superseded, _ = prepared[product_id]
                explanations.append(_skipped_explanation(superseded, DUPLICATE_REASON))
            prepared[product_id] = (record, record.price)

        collected_at = self.clock()
        deterministic_relevant = 0
        deterministic_irrelevant = 0
        ai_requested = 0
        ai_relevant = 0
        ai_irrelevant = 0
        review = 0
        listings: list[Listing] = []

        for product_id, (record, price) in prepared.items():
            classification = self.classifier.classify(
                ProductCandidate(title=record.title or "", description=record.description)
            )
            if classification.classification_source is ClassificationSource.DETERMINISTIC:
                if classification.decision is ClassificationDecision.RELEVANT:
                    deterministic_relevant += 1
                else:
                    deterministic_irrelevant += 1
            else:
                ai_requested += 1
                if classification.decision is ClassificationDecision.RELEVANT:
                    ai_relevant += 1
                elif classification.decision is ClassificationDecision.IRRELEVANT:
                    ai_irrelevant += 1

            if classification.decision is ClassificationDecision.REVIEW:
                review += 1
            elif classification.decision is ClassificationDecision.RELEVANT:
                currency, normalized = _apply_facebook_venezuela_price(price, record)
                url = _required_record_text(record.url) or ""
                try:
                    listings.append(
                        Listing(
                            source=self.source,
                            external_id=product_id,
                            title=record.title or "",
                            price=price,
                            currency=currency,
                            url=url,
                            query=query,
                            collected_at=collected_at,
                            location=record.location or None,
                            formatted_amount=_facebook_formatted(record),
                            usd_amount=normalized.usd_amount,
                            usd_normalization_status=normalized.normalization_status.value,
                            usd_evidence=normalized.evidence,
                        )
                    )
                except (TypeError, ValueError):
                    explanations.append(_skipped_explanation(record, "invalid_listing"))
                    continue
            explanations.append(_classified_explanation(record, price, classification))

        self._last_explanations = tuple(explanations)
        self._last_metrics = FacebookCollectionMetrics(
            fetched=response.fetched,
            source_errors=0,
            invalid_price=invalid_price,
            out_of_scope_location=out_of_scope_location,
            deterministic_relevant=deterministic_relevant,
            deterministic_irrelevant=deterministic_irrelevant,
            ai_requested=ai_requested,
            ai_relevant=ai_relevant,
            ai_irrelevant=ai_irrelevant,
            review=review,
            duplicates=duplicates,
            persisted=len(listings),
        )
        return listings
