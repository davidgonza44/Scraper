"""Offline behavior of the classified Facebook Marketplace provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from bera_price_tracker.application import (
    AIClassification,
    AIClassifierUnavailableError,
    AIProductClassifier,
    HybridProductClassifier,
    MarketplaceProvider,
    SanitizedProductCandidate,
)
from bera_price_tracker.domain import (
    BeraBikeModel,
    BrakePosition,
    BrandFamily,
    ClassificationDecision,
    MarketplaceSource,
    ProductType,
    SearchQuery,
)
from bera_price_tracker.infrastructure.providers import (
    BrightDataFacebookMarketplaceClient,
    FacebookCandidateOutcome,
    FacebookMarketplaceProvider,
)

COLLECTED_AT = datetime(2026, 8, 21, 18, 0, tzinfo=UTC)


@dataclass(slots=True)
class ScriptedAIClassifier:
    outcomes: list[AIClassification | Exception] = field(default_factory=list)
    calls: list[SanitizedProductCandidate] = field(default_factory=list)

    def classify(self, candidate: SanitizedProductCandidate) -> AIClassification:
        self.calls.append(candidate)
        if len(self.calls) > len(self.outcomes):
            raise AssertionError("AI must not be called for this candidate")
        outcome = self.outcomes[len(self.calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _ai_result(decision: ClassificationDecision) -> AIClassification:
    if decision is ClassificationDecision.RELEVANT:
        return AIClassification(
            decision=decision,
            product_type=ProductType.BRAKE_PAD,
            brand_family=BrandFamily.BERA,
            bike_models=(BeraBikeModel.SBR,),
            other_compatibility=("Matrix",),
            position=BrakePosition.UNKNOWN,
            rationale="Explicit brake-pad evidence.",
        )
    return AIClassification(
        decision=decision,
        product_type=(
            ProductType.OTHER
            if decision is ClassificationDecision.IRRELEVANT
            else ProductType.UNKNOWN
        ),
        brand_family=BrandFamily.UNKNOWN,
        bike_models=(),
        other_compatibility=(),
        position=BrakePosition.UNKNOWN,
        rationale="No sufficient fitment evidence.",
    )


def _provider(
    items: list[dict[str, object]],
    ai_classifier: AIProductClassifier,
) -> tuple[FacebookMarketplaceProvider, httpx.Client]:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=items, request=request)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = BrightDataFacebookMarketplaceClient(
        api_token="test-token",
        base_url="https://api.brightdata.test",
        dataset_id="dataset-1",
        request_timeout_seconds=10.0,
        poll_interval_seconds=5.0,
        poll_timeout_seconds=60.0,
        client=http_client,
    )
    return (
        FacebookMarketplaceProvider(
            client=client,
            classifier=HybridProductClassifier(ai_classifier),
            city="caracas",
            record_limit=5,
            clock=lambda: COLLECTED_AT,
        ),
        http_client,
    )


def _valid_item(product_id: str, title: str, **changes: object) -> dict[str, object]:
    item: dict[str, object] = {
        "product_id": product_id,
        "title": title,
        "final_price": "12.50",
        "currency": "VEF",
        "country_code": "VE",
        "url": f"https://facebook.example/{product_id}",
        "location": "Caracas",
        "condition": "new",
        "description": None,
    }
    item.update(changes)
    return item


def test_provider_filters_and_maps_a_mixed_deterministic_response() -> None:
    ai = ScriptedAIClassifier()
    provider, http_client = _provider(
        [
            _valid_item("FB-1", "Pastillas Honda CG125 ES4"),
            _valid_item("FB-2", "Disco de freno Bera SBR 150"),
            _valid_item("FB-3", "Pastillas Kawasaki KLX125", country_code="CO"),
            _valid_item("FB-4", "Pastillas Suzuki DR125", final_price="NaN"),
            {"error": "Redirect to login page.", "error_code": "bad_input"},
        ],
        ai,
    )
    marketplace_provider: MarketplaceProvider = provider

    try:
        listings = marketplace_provider.search(SearchQuery("pastillas"))
    finally:
        http_client.close()

    assert isinstance(provider, MarketplaceProvider)
    assert provider.source is MarketplaceSource.FACEBOOK_MARKETPLACE
    assert len(listings) == 1
    listing = listings[0]
    assert listing.external_id == "FB-1"
    assert listing.title == "Pastillas Honda CG125 ES4"
    assert listing.price == Decimal("12.50")
    assert listing.currency == "VEF"
    assert listing.url == "https://facebook.example/FB-1"
    assert listing.location == "Caracas"
    assert listing.product_condition == "new"
    assert listing.collected_at == COLLECTED_AT
    assert ai.calls == []
    assert provider.last_metrics.fetched == 5
    assert provider.last_metrics.source_errors == 1
    assert provider.last_metrics.non_ve == 1
    assert provider.last_metrics.invalid_price == 1
    assert provider.last_metrics.deterministic_relevant == 1
    assert provider.last_metrics.deterministic_irrelevant == 1
    assert provider.last_metrics.persisted == 1


def test_description_can_establish_relevance_but_is_not_persisted_in_listing() -> None:
    ai = ScriptedAIClassifier()
    provider, http_client = _provider(
        [
            _valid_item(
                "FB-1",
                "Repuesto para moto",
                description="Pastillas de freno compatibles con Honda CG125 ES4.",
                cookies="must-not-cross-boundary",
                profile_id="private-profile",
            )
        ],
        ai,
    )

    try:
        listing = provider.search(SearchQuery("pastillas"))[0]
    finally:
        http_client.close()

    assert listing.title == "Repuesto para moto"
    assert not hasattr(listing, "description")
    assert not hasattr(listing, "cookies")
    assert ai.calls == []
    assert provider.last_metrics.deterministic_relevant == 1


def test_review_candidates_use_ai_and_only_ai_relevant_becomes_a_listing() -> None:
    ai = ScriptedAIClassifier(
        outcomes=[
            _ai_result(ClassificationDecision.RELEVANT),
            _ai_result(ClassificationDecision.IRRELEVANT),
            _ai_result(ClassificationDecision.REVIEW),
            AIClassifierUnavailableError("offline"),
        ]
    )
    provider, http_client = _provider(
        [_valid_item(f"FB-{index}", "Repuestos Bera SBR") for index in range(1, 5)],
        ai,
    )

    try:
        listings = provider.search(SearchQuery("repuestos"))
    finally:
        http_client.close()

    assert [listing.external_id for listing in listings] == ["FB-1"]
    assert len(ai.calls) == 4
    assert provider.last_metrics.ai_requested == 4
    assert provider.last_metrics.ai_relevant == 1
    assert provider.last_metrics.ai_irrelevant == 1
    assert provider.last_metrics.review == 2
    assert provider.last_metrics.persisted == 1


def test_duplicate_product_id_is_classified_once_and_last_valid_record_wins() -> None:
    ai = ScriptedAIClassifier()
    provider, http_client = _provider(
        [
            _valid_item("FB-1", "Repuestos Bera SBR"),
            _valid_item("FB-1", "Pastillas Bera SBR 150", final_price="15.25"),
        ],
        ai,
    )

    try:
        listings = provider.search(SearchQuery("pastillas"))
    finally:
        http_client.close()

    assert len(listings) == 1
    assert listings[0].title == "Pastillas Bera SBR 150"
    assert listings[0].price == Decimal("15.25")
    assert ai.calls == []
    assert provider.last_metrics.duplicates == 1


def test_all_invalid_price_shapes_are_rejected_without_classification() -> None:
    invalid_values: tuple[object, ...] = (None, True, "NaN", "Infinity", 0, "not-a-price")
    ai = ScriptedAIClassifier()

    for invalid_value in invalid_values:
        provider, http_client = _provider(
            [_valid_item("FB-1", "Pastillas H0019", final_price=invalid_value)],
            ai,
        )
        try:
            assert provider.search(SearchQuery("pastillas")) == []
        finally:
            http_client.close()
        assert provider.last_metrics.invalid_price == 1

    assert ai.calls == []


def test_explanations_report_deterministic_relevant_and_irrelevant_outcomes() -> None:
    ai = ScriptedAIClassifier()
    provider, http_client = _provider(
        [
            _valid_item("FB-1", "Pastillas Honda CG125 ES4"),
            _valid_item("FB-2", "Disco de freno Bera SBR 150"),
        ],
        ai,
    )

    try:
        provider.search(SearchQuery("pastillas"))
    finally:
        http_client.close()

    relevant, irrelevant = provider.last_explanations
    assert relevant.outcome is FacebookCandidateOutcome.RELEVANT
    assert relevant.title == "Pastillas Honda CG125 ES4"
    assert relevant.price == "12.50"
    assert relevant.currency == "VEF"
    assert relevant.classification_source == "deterministic"
    assert relevant.product_type == "brake_pad"
    assert relevant.h0019_match == "CG125 ES4"
    assert "brake_pad_term_found" in relevant.reason
    assert irrelevant.outcome is FacebookCandidateOutcome.IRRELEVANT
    assert irrelevant.product_type == "brake_disc"
    assert irrelevant.bike_models == ("SBR",)
    assert irrelevant.h0019_match == "SBR"
    assert "excluded_product_brake_disc" in irrelevant.reason
    assert ai.calls == []


def test_explanations_distinguish_ai_review_from_ai_failure_review() -> None:
    ai = ScriptedAIClassifier(
        outcomes=[
            _ai_result(ClassificationDecision.REVIEW),
            AIClassifierUnavailableError("offline"),
        ]
    )
    provider, http_client = _provider(
        [
            _valid_item("FB-1", "Repuestos Bera SBR"),
            _valid_item("FB-2", "Repuestos Bera SBR 150"),
        ],
        ai,
    )

    try:
        provider.search(SearchQuery("repuestos"))
    finally:
        http_client.close()

    ai_review, failed_review = provider.last_explanations
    assert ai_review.outcome is FacebookCandidateOutcome.REVIEW
    assert ai_review.classification_source == "ai"
    assert ai_review.product_type == "unknown"
    assert ai_review.reason == "No sufficient fitment evidence."
    assert failed_review.outcome is FacebookCandidateOutcome.REVIEW
    assert failed_review.classification_source == "ai_unavailable"
    assert "ai_unavailable" in failed_review.reason


def test_explanations_report_skipped_candidates_without_provider_payload() -> None:
    ai = ScriptedAIClassifier()
    provider, http_client = _provider(
        [
            _valid_item("FB-1", "Pastillas Honda CG125 ES4", final_price="NaN"),
            _valid_item("FB-2", "Pastillas Kawasaki KLX125", country_code="CO"),
            _valid_item("FB-3", "Pastillas Suzuki DR125", url="not-a-url"),
            {"error": "Redirect to login page.", "error_code": "bad_input"},
        ],
        ai,
    )

    try:
        assert provider.search(SearchQuery("pastillas")) == []
    finally:
        http_client.close()

    source_error, invalid, foreign, invalid_url = provider.last_explanations
    assert source_error.reason == "source_error: bad_input"
    assert source_error.title is None
    assert invalid.outcome is FacebookCandidateOutcome.SKIPPED
    assert invalid.reason == "invalid_price"
    assert invalid.title == "Pastillas Honda CG125 ES4"
    assert invalid.price is None
    assert invalid.classification_source is None
    assert foreign.reason == "non_ve"
    assert invalid_url.reason == "source_error: bad_input"
    assert invalid_url.title is None
    assert ai.calls == []


def test_explanations_never_expose_descriptions_contact_or_account_data() -> None:
    ai = ScriptedAIClassifier()
    provider, http_client = _provider(
        [
            _valid_item(
                "FB-1",
                "Pastillas Honda CG125 ES4 escribe a ventas@example.test o +58 412 555 1234",
                description="Vendedor privado con perfil reservado",
                cookies="must-not-cross-boundary",
                profile_id="private-profile",
            )
        ],
        ai,
    )

    try:
        provider.search(SearchQuery("pastillas"))
    finally:
        http_client.close()

    explanation = provider.last_explanations[0]
    rendered = repr(provider.last_explanations)
    assert explanation.title is not None
    assert explanation.title.startswith("Pastillas Honda CG125 ES4")
    assert "[redacted]" in explanation.title
    assert "ventas@example.test" not in rendered
    assert "555 1234" not in rendered
    assert "Vendedor privado" not in rendered
    assert "must-not-cross-boundary" not in rendered
    assert "private-profile" not in rendered
