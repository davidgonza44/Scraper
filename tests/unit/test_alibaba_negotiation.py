"""Offline tests for the Alibaba negotiation copilot. No Actor or MiniMax calls."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from bera_price_tracker.application.alibaba_negotiation import (
    DEFAULT_NEGOTIATION_AGGRESSIVENESS,
    MISSING_PUBLIC_PRICE,
    NO_TIER_MAX_DISCOUNT,
    UNAUTHORIZED_DRAFT_PRICE,
    AlibabaNegotiationError,
    AlibabaNegotiationInput,
    AnalyzeSupplierResponse,
    CounterOfferDecision,
    DealAttractiveness,
    GenerateNegotiationOpeningMessage,
    GenerateNegotiationReply,
    NegotiationDraftAnalysis,
    NegotiationStage,
    NegotiationTier,
    NegotiationWarning,
    SanitizedNegotiationContext,
    calculate_alibaba_negotiation_plan,
    classify_supplier_price,
    margin_product_ceiling,
    negotiable_reference_price,
    next_better_tier,
    parse_ladder_text,
    parse_supplier_response,
    public_price_from_catalog_row,
    sanitized_negotiation_context,
    select_quantity_tier,
    tier_proximity,
)
from bera_price_tracker.gui import services

SRC = Path(__file__).resolve().parents[2] / "src"
NEGOTIATION = SRC / "bera_price_tracker" / "application" / "alibaba_negotiation.py"


def _tiers() -> tuple[NegotiationTier, ...]:
    return (
        NegotiationTier(min_quantity=1, max_quantity=49, unit_price=Decimal("4.30")),
        NegotiationTier(min_quantity=50, max_quantity=199, unit_price=Decimal("4.00")),
        NegotiationTier(min_quantity=200, max_quantity=999, unit_price=Decimal("3.80")),
        NegotiationTier(min_quantity=1000, max_quantity=None, unit_price=Decimal("3.50")),
    )


def _input(
    *,
    quantity: int = 40,
    tiers: tuple[NegotiationTier, ...] | None = None,
    public: Decimal | None = None,
    aggressiveness: int = DEFAULT_NEGOTIATION_AGGRESSIVENESS,
    resale: Decimal | None = None,
    margin: Decimal | None = None,
    shipping: Decimal | None = None,
    duties: Decimal | None = None,
    other: Decimal | None = None,
) -> AlibabaNegotiationInput:
    return AlibabaNegotiationInput(
        desired_quantity=quantity,
        title="Wireless Mouse",
        supplier_name="Example Electronics Co., Ltd.",
        min_order_quantity=1,
        tiers=_tiers() if tiers is None else tiers,
        public_unit_price=public,
        expected_resale_price=resale,
        target_margin_percent=margin,
        shipping_per_unit=shipping,
        duties_per_unit=duties,
        other_costs_per_unit=other,
        negotiation_aggressiveness=aggressiveness,
    )


class FakeDrafter:
    def __init__(
        self,
        message: str = "Please consider $4.03 for 40 units.",
        analysis: NegotiationDraftAnalysis | None = None,
        error: Exception | None = None,
    ) -> None:
        self.message = message
        self.analysis = analysis or NegotiationDraftAnalysis(
            response_summary="The supplier quoted a unit price.",
            quoted_unit_price="4.10",
            quoted_quantity="40",
            quoted_moq=None,
            shipping_mentioned=False,
            notes="",
        )
        self.error = error
        self.opening_contexts: list[SanitizedNegotiationContext] = []
        self.counter_contexts: list[SanitizedNegotiationContext] = []
        self.analyze_contexts: list[SanitizedNegotiationContext] = []

    def draft_opening(self, context: SanitizedNegotiationContext) -> str:
        if self.error is not None:
            raise self.error
        self.opening_contexts.append(context)
        return self.message

    def analyze_reply(
        self, context: SanitizedNegotiationContext, supplier_text: str
    ) -> NegotiationDraftAnalysis:
        del supplier_text
        if self.error is not None:
            raise self.error
        self.analyze_contexts.append(context)
        return self.analysis

    def draft_counter(self, context: SanitizedNegotiationContext) -> str:
        if self.error is not None:
            raise self.error
        self.counter_contexts.append(context)
        return self.message


def test_selects_covering_tier_for_desired_quantity() -> None:
    selected = select_quantity_tier(_tiers(), 40)
    assert selected is not None
    assert selected.min_quantity == 1
    assert selected.unit_price == Decimal("4.30")


def test_quantity_on_boundary_uses_new_tier() -> None:
    selected = select_quantity_tier(_tiers(), 50)
    assert selected is not None
    assert selected.min_quantity == 50
    assert selected.unit_price == Decimal("4.00")


def test_quantity_over_last_tier_uses_open_ended_tier() -> None:
    selected = select_quantity_tier(_tiers(), 2500)
    assert selected is not None
    assert selected.min_quantity == 1000
    assert selected.unit_price == Decimal("3.50")
    assert next_better_tier(_tiers(), selected) is None


def test_proximity_forty_over_fifty_is_point_eight() -> None:
    assert tier_proximity(40, 50) == Decimal("0.80")


def test_reference_price_example_is_four_point_zero_six() -> None:
    reference = negotiable_reference_price(
        Decimal("4.30"),
        Decimal("4.00"),
        Decimal("0.80"),
    )
    assert reference == Decimal("4.06")
    assert isinstance(reference, Decimal)


def test_plan_example_q40_opening_target_ceiling() -> None:
    plan = calculate_alibaba_negotiation_plan(_input())
    assert plan.public_unit_price == Decimal("4.30")
    assert plan.next_tier_min_quantity == 50
    assert plan.next_tier_price == Decimal("4.00")
    assert plan.tier_proximity == Decimal("0.80")
    assert plan.negotiable_reference == Decimal("4.06")
    assert plan.target_price == Decimal("4.06")
    assert plan.opening_offer == Decimal("4.03")
    assert plan.ceiling_price == Decimal("4.30")
    assert plan.opening_offer <= plan.target_price <= plan.ceiling_price
    assert plan.ceiling_price <= plan.public_unit_price
    assert "80%" in plan.explanation
    assert "$4.06" in plan.explanation
    assert "aceptará" not in plan.explanation


def test_no_ladder_uses_simple_public_price() -> None:
    plan = calculate_alibaba_negotiation_plan(_input(tiers=(), public=Decimal("4.30")))
    assert plan.public_unit_price == Decimal("4.30")
    assert plan.next_tier_price is None
    assert plan.negotiable_reference == Decimal("4.30")
    assert NegotiationWarning.NO_LADDER in plan.warnings
    assert plan.opening_offer <= plan.target_price <= plan.ceiling_price
    floor = (Decimal("4.30") * (Decimal("1") - NO_TIER_MAX_DISCOUNT)).quantize(Decimal("0.01"))
    assert plan.opening_offer >= floor


def test_range_midpoint_is_not_used_as_public() -> None:
    assert (
        public_price_from_catalog_row(
            {
                "source": "search",
                "representative": "98.70",
                "price_min": "89.20",
                "price_max": "108.20",
            }
        )
        is None
    )
    with pytest.raises(AlibabaNegotiationError, match="precio comparable"):
        calculate_alibaba_negotiation_plan(_input(tiers=(), public=None))
    assert MISSING_PUBLIC_PRICE


def test_tracked_canonical_price_is_usable_without_ladder() -> None:
    assert public_price_from_catalog_row(
        {"source": "tracked", "last_price": "$108.20", "price_min": "89.20", "price_max": "108.20"}
    ) == Decimal("108.20")


def test_simple_search_price_is_usable() -> None:
    assert public_price_from_catalog_row(
        {
            "source": "search",
            "representative": "4.30",
            "price_min": "4.30",
            "price_max": "4.30",
        }
    ) == Decimal("4.30")


def test_margin_ceiling_example() -> None:
    ceiling = margin_product_ceiling(
        Decimal("10"),
        Decimal("35"),
        Decimal("0.80"),
        Decimal("0"),
        Decimal("0.20"),
    )
    assert ceiling == Decimal("5.50")


def test_margin_reduces_ceiling_never_increases_it() -> None:
    plan = calculate_alibaba_negotiation_plan(
        _input(resale=Decimal("6.00"), margin=Decimal("20"), shipping=Decimal("0.50"))
    )
    # max_total = 6 * 0.80 = 4.80; max_product = 4.80 - 0.50 = 4.30
    assert plan.max_product_unit_price == Decimal("4.30")
    assert plan.ceiling_price == Decimal("4.30")
    assert plan.ceiling_price <= plan.public_unit_price


def test_costs_make_deal_unattractive() -> None:
    plan = calculate_alibaba_negotiation_plan(
        _input(
            resale=Decimal("5.00"),
            margin=Decimal("40"),
            shipping=Decimal("1.00"),
            other=Decimal("0.50"),
        )
    )
    # max_total = 5 * 0.60 = 3.00; max_product = 3.00 - 1.00 - 0.50 = 1.50
    assert plan.max_product_unit_price == Decimal("1.50")
    assert plan.attractiveness is DealAttractiveness.ECONOMICALLY_UNATTRACTIVE


def test_supplier_at_or_below_target_is_acceptable() -> None:
    plan = calculate_alibaba_negotiation_plan(_input())
    recommendation = classify_supplier_price(Decimal("4.05"), plan.bounds)
    assert recommendation.decision is CounterOfferDecision.ACCEPTABLE
    assert recommendation.authorized_price is None


def test_supplier_between_target_and_ceiling_is_negotiable() -> None:
    plan = calculate_alibaba_negotiation_plan(_input())
    recommendation = classify_supplier_price(Decimal("4.10"), plan.bounds)
    assert recommendation.decision is CounterOfferDecision.NEGOTIABLE
    assert recommendation.authorized_price == Decimal("4.06")


def test_supplier_above_ceiling_is_rejected() -> None:
    plan = calculate_alibaba_negotiation_plan(_input())
    recommendation = classify_supplier_price(Decimal("4.50"), plan.bounds)
    assert recommendation.decision is CounterOfferDecision.ABOVE_CEILING
    assert recommendation.authorized_price == Decimal("4.30")


def test_ambiguous_supplier_response_needs_review() -> None:
    parsed = parse_supplier_response("We can do $4.10 or $4.25 depending on color.")
    assert parsed.needs_human_review is True
    assert parsed.quoted_unit_price is None
    plan = calculate_alibaba_negotiation_plan(_input())
    recommendation = classify_supplier_price(None, plan.bounds, ambiguous=True)
    assert recommendation.decision is CounterOfferDecision.NEEDS_HUMAN_REVIEW


def test_minimax_cannot_overwrite_limits() -> None:
    plan = calculate_alibaba_negotiation_plan(_input())
    drafter = FakeDrafter(message="I can offer $4.20 right now.")
    with pytest.raises(AlibabaNegotiationError, match="autorizó"):
        GenerateNegotiationOpeningMessage(drafter).execute(plan)
    assert UNAUTHORIZED_DRAFT_PRICE


def test_authorized_opening_message_is_accepted() -> None:
    plan = calculate_alibaba_negotiation_plan(_input())
    drafter = FakeDrafter(message="Please consider $4.03 for 40 units toward the $4.06 target.")
    message = GenerateNegotiationOpeningMessage(drafter).execute(plan)
    assert "$4.03" in message
    context = drafter.opening_contexts[0]
    assert context.opening_offer == "4.03"
    assert context.target_price == "4.06"
    assert context.ceiling_price == "4.30"


def test_negotiable_reply_uses_target_not_an_invented_price() -> None:
    plan = calculate_alibaba_negotiation_plan(_input())
    drafter = FakeDrafter(
        message="Thank you. Our target remains $4.06.",
        analysis=NegotiationDraftAnalysis(
            response_summary="Quoted 4.10",
            quoted_unit_price="4.10",
            quoted_quantity="40",
            notes="",
        ),
    )
    parsed, recommendation = AnalyzeSupplierResponse(drafter).execute(
        plan, "We can offer $4.10 for 40 units."
    )
    assert recommendation.decision is CounterOfferDecision.NEGOTIABLE
    assert recommendation.authorized_price == Decimal("4.06")
    reply = GenerateNegotiationReply(drafter).execute(plan, parsed, recommendation)
    assert "$4.06" in reply
    assert drafter.counter_contexts[0].authorized_counter_price == "4.06"


def test_minimax_invented_supplier_price_is_reviewed() -> None:
    plan = calculate_alibaba_negotiation_plan(_input())
    drafter = FakeDrafter(
        analysis=NegotiationDraftAnalysis(
            response_summary="They agreed",
            quoted_unit_price="3.10",
            quoted_quantity="40",
            notes="",
        )
    )
    parsed, recommendation = AnalyzeSupplierResponse(drafter).execute(
        plan, "Please send your best offer for 40 units."
    )
    assert parsed.needs_human_review is True
    assert recommendation.decision is CounterOfferDecision.NEEDS_HUMAN_REVIEW


def test_context_has_no_secrets_or_scoring_internals() -> None:
    plan = calculate_alibaba_negotiation_plan(_input())
    context = sanitized_negotiation_context(plan, stage=NegotiationStage.OPENING)
    blob = " ".join(
        str(getattr(context, name)).lower()
        for name in (
            "product_title",
            "supplier_company_name",
            "public_ladder_summary",
            "negotiation_stage",
        )
    )
    for banned in ("apify", "chattoken", "contactsupplier", "score_price", "authorization"):
        assert banned not in blob
    assert "4.03" in context.opening_offer


def test_decimal_only_no_float() -> None:
    text = NEGOTIATION.read_text(encoding="utf-8")
    assert "float(" not in text
    assert "Decimal" in text


def test_parse_ladder_text() -> None:
    tiers = parse_ladder_text("1-49:4.30\n50-199:4.00\n")
    assert len(tiers) == 2
    assert tiers[1].unit_price == Decimal("4.00")


def test_quantity_below_tiers_is_rejected() -> None:
    high = (NegotiationTier(min_quantity=10, max_quantity=49, unit_price=Decimal("4.30")),)
    with pytest.raises(AlibabaNegotiationError, match="inferior"):
        calculate_alibaba_negotiation_plan(_input(quantity=5, tiers=high))


def test_zero_quantity_is_rejected() -> None:
    with pytest.raises(AlibabaNegotiationError, match="cantidad"):
        calculate_alibaba_negotiation_plan(_input(quantity=0, tiers=()))


def test_gui_calculate_uses_ladder_and_does_not_call_network() -> None:
    row = services.calculate_alibaba_negotiation(
        {
            "title": "Wireless Mouse",
            "supplier_name": "Example",
            "source": "tracked",
            "last_price": "$4.30",
            "price_min": "3.50",
            "price_max": "4.30",
        },
        desired_quantity="40",
        ladder_text="1-49:4.30\n50-199:4.00",
    )
    assert row["public_unit_price"] == "$4.30"
    assert row["target_price"] == "$4.06"
    assert row["opening_offer"] == "$4.03"
    assert row["ceiling_price"] == "$4.30"
    assert "80%" in row["explanation"]


def test_gui_opening_uses_injected_drafter() -> None:
    plan_row = services.calculate_alibaba_negotiation(
        {
            "title": "Wireless Mouse",
            "source": "tracked",
            "last_price": "4.30",
            "price_min": "4.30",
            "price_max": "4.30",
        },
        desired_quantity="40",
        ladder_text="1-49:4.30\n50-199:4.00",
    )
    message = services.generate_alibaba_negotiation_opening(
        plan_row,
        drafter=FakeDrafter(message="Opening at $4.03 against a $4.30 list."),
    )
    assert "$4.03" in message


def test_views_expose_negotiation_controls() -> None:
    views = (SRC / "bera_price_tracker" / "gui" / "views.py").read_text(encoding="utf-8")
    assert "Negociación" in views
    assert "Calcular estrategia" in views
    assert "Generar mensaje con MiniMax" in views
    assert "Copiar" in views
    assert "Regenerar" in views
    assert "Nada se envía a Alibaba" in views


def test_scoring_and_tracking_modules_unchanged_by_import_surface() -> None:
    score = (SRC / "bera_price_tracker" / "application" / "alibaba_score.py").read_text(
        encoding="utf-8"
    )
    ranking = (SRC / "bera_price_tracker" / "application" / "alibaba_ranking.py").read_text(
        encoding="utf-8"
    )
    tracking = (SRC / "bera_price_tracker" / "application" / "alibaba_tracking.py").read_text(
        encoding="utf-8"
    )
    assert "negotiation" not in score.lower()
    assert "negotiation" not in ranking.lower()
    assert "negotiation" not in tracking.lower()
    assert "minimax" not in score.lower()


def test_facebook_h0019_prompt_untouched() -> None:
    ollama = (SRC / "bera_price_tracker" / "infrastructure" / "ai" / "ollama.py").read_text(
        encoding="utf-8"
    )
    assert "h0019-brake-pad-v4" in ollama
    assert "submit_alibaba_negotiation_draft" not in ollama
