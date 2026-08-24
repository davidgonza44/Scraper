"""Offline tests for landed-cost ceilings on negotiation plans."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from bera_price_tracker.application.alibaba_negotiation import (
    AlibabaNegotiationInput,
    AlibabaNegotiationPlan,
    CounterOfferDecision,
    DealAttractiveness,
    GenerateNegotiationOpeningMessage,
    NegotiationDraftAnalysis,
    NegotiationDraftContext,
    NegotiationStage,
    NegotiationTier,
    calculate_alibaba_negotiation_plan,
    classify_supplier_price,
    draft_context_from_plan,
    draft_context_payload,
)
from bera_price_tracker.application.import_aware_negotiation import (
    CONFIRMED_PROVENANCE,
    ESTIMATE_PROVENANCE,
    MISSING_PROFITABILITY_CEILING,
    CalculateImportAwareNegotiationPlan,
    apply_profitability_ceiling,
)
from bera_price_tracker.application.landed_cost import (
    CargoPackagingInput,
    LandedCostInput,
    ShippingRateProfile,
    ShippingRateStatus,
    calculate_landed_cost,
)
from bera_price_tracker.gui import services

SRC = Path(__file__).resolve().parents[2] / "src"
COMPOSITION = SRC / "bera_price_tracker" / "application" / "import_aware_negotiation.py"


def _tiers() -> tuple[NegotiationTier, ...]:
    return (
        NegotiationTier(min_quantity=1, max_quantity=49, unit_price=Decimal("4.30")),
        NegotiationTier(min_quantity=50, max_quantity=199, unit_price=Decimal("4.00")),
        NegotiationTier(min_quantity=200, max_quantity=999, unit_price=Decimal("3.80")),
        NegotiationTier(min_quantity=1000, max_quantity=None, unit_price=Decimal("3.50")),
    )


def _input() -> AlibabaNegotiationInput:
    return AlibabaNegotiationInput(
        desired_quantity=40,
        title="Wireless Mouse",
        supplier_name="Example Electronics Co., Ltd.",
        min_order_quantity=1,
        tiers=_tiers(),
        negotiation_aggressiveness=50,
    )


def _base_plan() -> AlibabaNegotiationPlan:
    return calculate_alibaba_negotiation_plan(_input())


class FakeDrafter:
    def __init__(self) -> None:
        self.opening_contexts: list[NegotiationDraftContext] = []

    def draft_opening(self, context: NegotiationDraftContext) -> str:
        self.opening_contexts.append(context)
        return "Please consider $4.03 for 40 units."

    def analyze_reply(
        self, context: NegotiationDraftContext, supplier_text: str
    ) -> NegotiationDraftAnalysis:
        del context, supplier_text
        raise AssertionError("analyze is not used")

    def draft_counter(self, context: NegotiationDraftContext) -> str:
        raise AssertionError("counter is not used")


def test_without_landed_cost_matches_previous_plan() -> None:
    composed = CalculateImportAwareNegotiationPlan().execute(_input())
    plan = composed.plan
    assert plan.opening_offer == Decimal("4.03")
    assert plan.target_price == Decimal("4.06")
    assert plan.ceiling_price == Decimal("4.30")
    assert composed.applied is False
    assert composed.effective_ceiling == Decimal("4.30")
    assert composed.profitability_note == MISSING_PROFITABILITY_CEILING


def test_lower_landed_ceiling_reduces_ceiling() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(), maximum_supplier_unit_price=Decimal("4.10")
    )
    assert composed.original_ceiling == Decimal("4.30")
    assert composed.profitability_ceiling == Decimal("4.10")
    assert composed.effective_ceiling == Decimal("4.10")
    assert composed.plan.ceiling_price == Decimal("4.10")
    assert composed.plan.opening_offer == Decimal("4.03")
    assert composed.plan.target_price == Decimal("4.06")


def test_higher_landed_ceiling_does_not_raise_ceiling() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(), maximum_supplier_unit_price=Decimal("5.00")
    )
    assert composed.effective_ceiling == Decimal("4.30")
    assert composed.plan.ceiling_price == Decimal("4.30")
    assert composed.plan.target_price == Decimal("4.06")
    assert composed.plan.opening_offer == Decimal("4.03")


def test_target_below_new_ceiling_stays() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(), maximum_supplier_unit_price=Decimal("4.10")
    )
    assert composed.plan.target_price == Decimal("4.06")


def test_target_above_new_ceiling_is_clamped() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(), maximum_supplier_unit_price=Decimal("4.00")
    )
    assert composed.plan.ceiling_price == Decimal("4.00")
    assert composed.plan.target_price == Decimal("4.00")
    assert composed.plan.opening_offer <= composed.plan.target_price


def test_opening_never_exceeds_target() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(), maximum_supplier_unit_price=Decimal("3.90")
    )
    assert composed.plan.opening_offer <= composed.plan.target_price <= composed.plan.ceiling_price
    assert composed.plan.opening_offer == Decimal("3.90")
    assert composed.plan.opening_offer > Decimal("0")


def test_invariants_always_hold() -> None:
    for cap in (Decimal("4.10"), Decimal("4.00"), Decimal("3.90"), Decimal("3.20"), Decimal("5")):
        composed = apply_profitability_ceiling(_base_plan(), maximum_supplier_unit_price=cap)
        plan = composed.plan
        assert plan.opening_offer <= plan.target_price <= plan.ceiling_price
        assert plan.ceiling_price <= plan.public_unit_price


def test_supplier_between_target_and_effective_ceiling_is_negotiable() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(), maximum_supplier_unit_price=Decimal("4.10")
    )
    recommendation = classify_supplier_price(Decimal("4.08"), composed.plan.bounds)
    assert recommendation.decision is CounterOfferDecision.NEGOTIABLE
    assert recommendation.authorized_price == Decimal("4.06")


def test_supplier_above_effective_ceiling_is_rejected() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(), maximum_supplier_unit_price=Decimal("4.10")
    )
    recommendation = classify_supplier_price(Decimal("4.15"), composed.plan.bounds)
    assert recommendation.decision is CounterOfferDecision.ABOVE_CEILING
    assert recommendation.authorized_price == Decimal("4.10")


def test_very_low_profitability_is_unattractive() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(), maximum_supplier_unit_price=Decimal("3.90")
    )
    assert composed.plan.attractiveness is DealAttractiveness.ECONOMICALLY_UNATTRACTIVE
    assert composed.plan.opening_offer <= composed.plan.target_price <= composed.plan.ceiling_price
    assert "no es económicamente atractivo" in composed.plan.explanation


def test_estimate_provenance() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(),
        maximum_supplier_unit_price=Decimal("4.10"),
        rate_status=ShippingRateStatus.ESTIMATE,
    )
    assert composed.provenance == ESTIMATE_PROVENANCE
    assert "estimado" in composed.profitability_note
    assert "$4.30" in composed.profitability_note
    assert "$4.10" in composed.profitability_note


def test_confirmed_quote_provenance() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(),
        maximum_supplier_unit_price=Decimal("4.10"),
        rate_status=ShippingRateStatus.CONFIRMED_QUOTE,
    )
    assert composed.provenance == CONFIRMED_PROVENANCE
    assert "cotización logística confirmada" in composed.profitability_note


def test_minimax_payload_excludes_landed_cost() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(), maximum_supplier_unit_price=Decimal("4.10")
    )
    context = draft_context_from_plan(composed.plan, stage=NegotiationStage.OPENING)
    blob = str(draft_context_payload(context)).lower()
    for banned in (
        "profitability",
        "original_ceiling",
        "landed",
        "dtd",
        "freight",
        "margin",
        "4.10",
        "4.06",
        "4.30",
    ):
        assert banned not in blob
    assert context.authorized_offer == "4.03"
    message = GenerateNegotiationOpeningMessage(FakeDrafter()).execute(composed.plan)
    assert "$4.03" in message


def test_decimal_only_no_float() -> None:
    text = COMPOSITION.read_text(encoding="utf-8")
    assert "float(" not in text
    assert "Decimal" in text


def test_scoring_and_tracking_untouched() -> None:
    for name in ("alibaba_score.py", "alibaba_ranking.py", "alibaba_tracking.py"):
        text = (SRC / "bera_price_tracker" / "application" / name).read_text(encoding="utf-8")
        assert "import_aware" not in text
        assert "landed_cost" not in text
        assert "profitability_ceiling" not in text


def test_gui_apply_updates_row_and_reconstructs_bounds() -> None:
    plan_row = services.calculate_alibaba_negotiation(
        {
            "title": "Wireless Mouse",
            "supplier_name": "Example",
            "source": "tracked",
            "last_price": "4.30",
            "price_min": "4.30",
            "price_max": "4.30",
        },
        desired_quantity="40",
        ladder_text="1-49:4.30\n50-199:4.00",
    )
    assert plan_row["opening_offer"] == "$4.03"
    assert plan_row["target_price"] == "$4.06"
    assert plan_row["ceiling_price"] == "$4.30"
    landed = {
        "max_supplier_raw": "4.10",
        "rate_status": ShippingRateStatus.ESTIMATE.value,
    }
    applied = services.apply_alibaba_profitability_ceiling(plan_row, landed)
    assert applied["ceiling_price"] == "$4.10"
    assert applied["target_price"] == "$4.06"
    assert applied["opening_offer"] == "$4.03"
    assert applied["original_ceiling"] == "$4.30"
    assert applied["profitability_ceiling"] == "$4.10"
    assert applied["effective_ceiling"] == "$4.10"
    assert applied["profitability_applied"] == "1"
    reconstructed = services._plan_from_row(applied)
    assert reconstructed.ceiling_price == Decimal("4.10")
    assert classify_supplier_price(Decimal("4.15"), reconstructed.bounds).decision is (
        CounterOfferDecision.ABOVE_CEILING
    )


def test_gui_apply_without_landed_keeps_plan() -> None:
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
    with pytest.raises(Exception, match="rentabilidad"):
        services.apply_alibaba_profitability_ceiling(plan_row, None)
    untouched = services._plan_from_row(plan_row)
    assert untouched.ceiling_price == Decimal("4.30")
    assert untouched.opening_offer == Decimal("4.03")
    assert untouched.target_price == Decimal("4.06")


def test_apply_accepts_real_landed_analysis() -> None:
    analysis = calculate_landed_cost(
        LandedCostInput(
            quantity=40,
            supplier_unit_price=Decimal("4.03"),
            packaging=CargoPackagingInput(
                cartons=2,
                units_per_carton=20,
                carton_length_cm=Decimal("50"),
                carton_width_cm=Decimal("40"),
                carton_height_cm=Decimal("30"),
                gross_weight_kg_per_carton=Decimal("8"),
            ),
            rate=ShippingRateProfile(rate_usd_per_cbm=Decimal("800")),
            expected_sale_price_per_unit=Decimal("10.00"),
            target_margin_percent=Decimal("30"),
        )
    )
    assert analysis.maximum_supplier_unit_price == Decimal("4.60")
    composed = apply_profitability_ceiling(_base_plan(), analysis=analysis)
    assert composed.effective_ceiling == Decimal("4.30")
    assert composed.plan.ceiling_price == Decimal("4.30")


def test_views_expose_apply_action() -> None:
    views = (SRC / "bera_price_tracker" / "gui" / "views.py").read_text(encoding="utf-8")
    assert "Aplicar rentabilidad a negociación" in views
    assert "Máximo negociación" in views
    assert "Máximo por rentabilidad" in views
    assert "Máximo final" in views
