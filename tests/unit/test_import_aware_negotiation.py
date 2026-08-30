"""Offline tests for landed-cost ceilings on negotiation plans."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from bera_price_tracker.application.alibaba_negotiation import (
    DEFAULT_DRAFT_CURRENCY,
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
    PROFITABILITY_CURRENCY_MISMATCH,
    CalculateImportAwareNegotiationPlan,
    apply_profitability_ceiling,
)
from bera_price_tracker.application.landed_cost import (
    CargoPackagingInput,
    LandedCostInput,
    LandedCostViability,
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


def _input(currency: str = DEFAULT_DRAFT_CURRENCY) -> AlibabaNegotiationInput:
    return AlibabaNegotiationInput(
        desired_quantity=40,
        title="Wireless Mouse",
        supplier_name="Example Electronics Co., Ltd.",
        min_order_quantity=1,
        tiers=_tiers(),
        negotiation_aggressiveness=50,
        currency=currency,
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
    assert composed.provenance is None
    assert composed.rate_status is None


def test_lower_landed_ceiling_reduces_ceiling() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(), maximum_supplier_unit_price=Decimal("4.10"), landed_currency="USD"
    )
    assert composed.original_ceiling == Decimal("4.30")
    assert composed.profitability_ceiling == Decimal("4.10")
    assert composed.effective_ceiling == Decimal("4.10")
    assert composed.plan.ceiling_price == Decimal("4.10")
    assert composed.plan.opening_offer == Decimal("4.03")
    assert composed.plan.target_price == Decimal("4.06")


def test_higher_landed_ceiling_does_not_raise_ceiling() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(), maximum_supplier_unit_price=Decimal("5.00"), landed_currency="USD"
    )
    assert composed.effective_ceiling == Decimal("4.30")
    assert composed.plan.ceiling_price == Decimal("4.30")
    assert composed.plan.target_price == Decimal("4.06")
    assert composed.plan.opening_offer == Decimal("4.03")


def test_import_aware_rebuild_preserves_cny_currency_and_display() -> None:
    plan = calculate_alibaba_negotiation_plan(_input(currency="CNY"))
    composed = apply_profitability_ceiling(
        plan, maximum_supplier_unit_price=Decimal("4.10"), landed_currency="CNY"
    )
    row = services.negotiation_plan_to_row(composed.plan)
    assert composed.plan.currency == "CNY"
    assert row["currency"] == "CNY"
    assert row["ceiling_price"] == "CNY 4.10"
    assert "$4.10" not in row.values()


def test_target_below_new_ceiling_stays() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(), maximum_supplier_unit_price=Decimal("4.10"), landed_currency="USD"
    )
    assert composed.plan.target_price == Decimal("4.06")


def test_target_above_new_ceiling_is_clamped() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(), maximum_supplier_unit_price=Decimal("4.00"), landed_currency="USD"
    )
    assert composed.plan.ceiling_price == Decimal("4.00")
    assert composed.plan.target_price == Decimal("4.00")
    assert composed.plan.opening_offer <= composed.plan.target_price


def test_opening_never_exceeds_target() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(), maximum_supplier_unit_price=Decimal("3.90"), landed_currency="USD"
    )
    assert composed.plan.opening_offer <= composed.plan.target_price <= composed.plan.ceiling_price
    assert composed.plan.opening_offer == Decimal("3.90")
    assert composed.plan.opening_offer > Decimal("0")


def test_invariants_always_hold() -> None:
    for cap in (Decimal("4.10"), Decimal("4.00"), Decimal("3.90"), Decimal("3.20"), Decimal("5")):
        composed = apply_profitability_ceiling(
            _base_plan(), maximum_supplier_unit_price=cap, landed_currency="USD"
        )
        plan = composed.plan
        assert plan.opening_offer <= plan.target_price <= plan.ceiling_price
        assert plan.ceiling_price <= plan.public_unit_price


def test_supplier_between_target_and_effective_ceiling_is_negotiable() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(), maximum_supplier_unit_price=Decimal("4.10"), landed_currency="USD"
    )
    recommendation = classify_supplier_price(Decimal("4.08"), composed.plan.bounds)
    assert recommendation.decision is CounterOfferDecision.NEGOTIABLE
    assert recommendation.authorized_price == Decimal("4.06")


def test_supplier_above_effective_ceiling_is_rejected() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(), maximum_supplier_unit_price=Decimal("4.10"), landed_currency="USD"
    )
    recommendation = classify_supplier_price(Decimal("4.15"), composed.plan.bounds)
    assert recommendation.decision is CounterOfferDecision.ABOVE_CEILING
    assert recommendation.authorized_price == Decimal("4.10")


def test_very_low_profitability_is_unattractive() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(), maximum_supplier_unit_price=Decimal("3.90"), landed_currency="USD"
    )
    assert composed.plan.attractiveness is DealAttractiveness.ECONOMICALLY_UNATTRACTIVE
    assert composed.plan.opening_offer <= composed.plan.target_price <= composed.plan.ceiling_price
    assert "no es económicamente atractivo" in composed.plan.explanation


def test_estimate_provenance() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(),
        maximum_supplier_unit_price=Decimal("4.10"),
        landed_currency="USD",
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
        landed_currency="USD",
        rate_status=ShippingRateStatus.CONFIRMED_QUOTE,
    )
    assert composed.provenance == CONFIRMED_PROVENANCE
    assert "cotización logística confirmada" in composed.profitability_note


def test_minimax_payload_excludes_landed_cost() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(), maximum_supplier_unit_price=Decimal("4.10"), landed_currency="USD"
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
            "currency": "USD",
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
        "currency": "USD",
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


def test_landed_recalc_does_not_keep_stale_profitability_ceiling() -> None:
    from bera_price_tracker.gui.state import TrackerState

    plan_row = services.calculate_alibaba_negotiation(
        {
            "title": "Wireless Mouse",
            "source": "tracked",
            "last_price": "5.00",
            "price_min": "5.00",
            "price_max": "5.00",
            "currency": "USD",
            "product_id": "mouse-1",
        },
        desired_quantity="40",
    )
    applied = services.apply_alibaba_profitability_ceiling(
        plan_row,
        {
            "max_supplier_raw": "4.60",
            "currency": "USD",
            "rate_status": ShippingRateStatus.ESTIMATE.value,
        },
    )
    assert applied["profitability_applied"] == "1"
    assert Decimal(applied["profitability_ceiling_raw"]) == Decimal("4.60")
    stale_quote = Decimal("4.20")
    assert (
        classify_supplier_price(stale_quote, services._plan_from_row(applied).bounds).decision
        is CounterOfferDecision.ACCEPTABLE
    )

    state = TrackerState()
    state._apply_negotiation_plan(applied)
    state.alibaba_landed_draft_product_id = "mouse-1"
    state.alibaba_landed_quantity = "40"
    state.alibaba_landed_supplier_price = "4.03"
    state.alibaba_landed_cartons = "2"
    state.alibaba_landed_units_per_carton = "20"
    state.alibaba_landed_length = "50"
    state.alibaba_landed_width = "40"
    state.alibaba_landed_height = "30"
    state.alibaba_landed_weight = "8"
    state.alibaba_landed_rate = "800"
    state.alibaba_landed_sale_price = "8.00"
    state.alibaba_landed_margin = "30"

    state.calculate_alibaba_landed_cost()

    assert state.alibaba_landed_has_result is True
    new_max = Decimal(str(state.alibaba_landed_result["max_supplier_raw"]))
    assert new_max < stale_quote
    live_plan = services._plan_from_row(state.alibaba_negotiation_plan_payload)
    assert classify_supplier_price(stale_quote, live_plan.bounds).decision is (
        CounterOfferDecision.ABOVE_CEILING
    )
    assert live_plan.ceiling_price == new_max
    assert state.alibaba_negotiation_plan_payload["profitability_applied"] == "1"


def test_failed_landed_recalc_detaches_applied_profitability() -> None:
    from bera_price_tracker.gui.state import TrackerState

    plan_row = services.calculate_alibaba_negotiation(
        {
            "title": "Wireless Mouse",
            "source": "tracked",
            "last_price": "5.00",
            "price_min": "5.00",
            "price_max": "5.00",
            "currency": "USD",
            "product_id": "mouse-1",
        },
        desired_quantity="40",
    )
    applied = services.apply_alibaba_profitability_ceiling(
        plan_row,
        {
            "max_supplier_raw": "4.60",
            "currency": "USD",
            "rate_status": ShippingRateStatus.ESTIMATE.value,
        },
    )
    state = TrackerState()
    state._apply_negotiation_plan(applied)
    state.alibaba_landed_draft_product_id = "mouse-1"
    state.calculate_alibaba_landed_cost()

    assert state.alibaba_landed_has_result is False
    assert state.alibaba_negotiation_plan_payload["profitability_applied"] == "0"
    restored = services._plan_from_row(state.alibaba_negotiation_plan_payload)
    assert restored.ceiling_price == Decimal(plan_row["public_raw"])
    assert restored.opening_offer <= restored.target_price <= restored.ceiling_price


def test_gui_apply_without_landed_keeps_plan() -> None:
    plan_row = services.calculate_alibaba_negotiation(
        {
            "title": "Wireless Mouse",
            "source": "tracked",
            "last_price": "4.30",
            "price_min": "4.30",
            "price_max": "4.30",
            "currency": "USD",
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


def _usd_plan_row() -> dict[str, str]:
    return services.calculate_alibaba_negotiation(
        {
            "title": "Wireless Mouse",
            "supplier_name": "Example",
            "source": "tracked",
            "last_price": "4.30",
            "price_min": "4.30",
            "price_max": "4.30",
            "currency": "USD",
        },
        desired_quantity="40",
        ladder_text="1-49:4.30\n50-199:4.00",
    )


def _cny_plan_row() -> dict[str, str]:
    return services.calculate_alibaba_negotiation(
        {
            "title": "Wireless Mouse",
            "supplier_name": "Example",
            "source": "tracked",
            "last_price": "4.30",
            "price_min": "4.30",
            "price_max": "4.30",
            "currency": "CNY",
        },
        desired_quantity="40",
        ladder_text="1-49:4.30\n50-199:4.00",
    )


def test_usd_plan_and_usd_landed_applies_profitability() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(),
        maximum_supplier_unit_price=Decimal("4.10"),
        landed_currency="USD",
    )
    assert composed.applied is True
    assert composed.effective_ceiling == Decimal("4.10")
    assert composed.plan.opening_offer == Decimal("4.03")
    assert composed.plan.target_price == Decimal("4.06")
    assert composed.plan.ceiling_price == Decimal("4.10")


def test_cny_plan_and_usd_landed_does_not_apply_profitability() -> None:
    plan = calculate_alibaba_negotiation_plan(_input(currency="CNY"))
    opening = plan.opening_offer
    target = plan.target_price
    ceiling = plan.ceiling_price
    composed = apply_profitability_ceiling(
        plan,
        maximum_supplier_unit_price=Decimal("4.10"),
        landed_currency="USD",
    )
    assert composed.applied is False
    assert composed.profitability_ceiling is None
    assert composed.plan.opening_offer == opening
    assert composed.plan.target_price == target
    assert composed.plan.ceiling_price == ceiling
    assert composed.profitability_note == PROFITABILITY_CURRENCY_MISMATCH
    assert composed.plan is plan


def test_eur_plan_and_usd_landed_is_blocked() -> None:
    plan = calculate_alibaba_negotiation_plan(_input(currency="EUR"))
    composed = apply_profitability_ceiling(
        plan,
        maximum_supplier_unit_price=Decimal("4.10"),
        landed_currency="USD",
    )
    assert composed.applied is False
    assert composed.plan.ceiling_price == plan.ceiling_price
    assert composed.profitability_note == PROFITABILITY_CURRENCY_MISMATCH


def test_missing_plan_currency_fails_closed() -> None:
    from dataclasses import replace

    plan = replace(_base_plan(), currency="")
    composed = apply_profitability_ceiling(
        plan,
        maximum_supplier_unit_price=Decimal("4.10"),
        landed_currency="USD",
    )
    assert composed.applied is False
    assert composed.plan.opening_offer == plan.opening_offer
    assert composed.profitability_note == PROFITABILITY_CURRENCY_MISMATCH


def test_missing_landed_currency_fails_closed() -> None:
    plan = _base_plan()
    composed = apply_profitability_ceiling(plan, maximum_supplier_unit_price=Decimal("4.10"))
    assert composed.applied is False
    assert composed.plan.ceiling_price == plan.ceiling_price
    assert composed.profitability_note == PROFITABILITY_CURRENCY_MISMATCH


def test_invalid_landed_currency_fails_closed() -> None:
    plan = _base_plan()
    composed = apply_profitability_ceiling(
        plan,
        maximum_supplier_unit_price=Decimal("4.10"),
        landed_currency="$",
    )
    assert composed.applied is False
    assert composed.plan.ceiling_price == plan.ceiling_price
    assert composed.profitability_note == PROFITABILITY_CURRENCY_MISMATCH


def test_cny_plan_and_cny_landed_applies_profitability() -> None:
    plan = calculate_alibaba_negotiation_plan(_input(currency="CNY"))
    composed = apply_profitability_ceiling(
        plan,
        maximum_supplier_unit_price=Decimal("4.10"),
        landed_currency="CNY",
    )
    assert composed.applied is True
    assert composed.plan.currency == "CNY"
    assert composed.effective_ceiling == Decimal("4.10")
    assert composed.plan.ceiling_price == Decimal("4.10")


def test_mismatch_does_not_compare_decimals(monkeypatch: pytest.MonkeyPatch) -> None:
    from bera_price_tracker.application import import_aware_negotiation as import_mod

    def boom(*_args: object, **_kwargs: object) -> Decimal:
        raise AssertionError("must not compare amounts across currencies")

    monkeypatch.setattr(import_mod, "capped_negotiation_ceiling", boom)
    plan = calculate_alibaba_negotiation_plan(_input(currency="CNY"))
    composed = apply_profitability_ceiling(
        plan,
        maximum_supplier_unit_price=Decimal("4.10"),
        landed_currency="USD",
    )
    assert composed.applied is False
    assert composed.plan.opening_offer == plan.opening_offer
    assert composed.plan.target_price == plan.target_price
    assert composed.plan.ceiling_price == plan.ceiling_price


def test_gui_usd_landed_applies_when_currencies_match() -> None:
    plan_row = _usd_plan_row()
    applied = services.apply_alibaba_profitability_ceiling(
        plan_row,
        {
            "max_supplier_raw": "4.10",
            "rate_status": ShippingRateStatus.ESTIMATE.value,
            "currency": "USD",
        },
    )
    assert applied["profitability_applied"] == "1"
    assert applied["ceiling_price"] == "$4.10"
    assert applied["opening_offer"] == "$4.03"
    assert applied["landed_currency"] == "USD"


def test_gui_cny_plan_usd_landed_keeps_original_bounds() -> None:
    plan_row = _cny_plan_row()
    opening = plan_row["opening_offer"]
    target = plan_row["target_price"]
    ceiling = plan_row["ceiling_price"]
    with pytest.raises(Exception, match="moneda del costo puesto"):
        services.apply_alibaba_profitability_ceiling(
            plan_row,
            {
                "max_supplier_raw": "4.10",
                "rate_status": ShippingRateStatus.ESTIMATE.value,
                "currency": "USD",
            },
        )
    untouched = services._plan_from_row(plan_row)
    assert plan_row["opening_offer"] == opening
    assert plan_row["target_price"] == target
    assert plan_row["ceiling_price"] == ceiling
    assert untouched.opening_offer == Decimal("4.03")
    assert untouched.target_price == Decimal("4.06")
    assert untouched.ceiling_price == Decimal("4.30")


def test_gui_eur_plan_usd_landed_is_blocked() -> None:
    plan_row = services.calculate_alibaba_negotiation(
        {
            "title": "Wireless Mouse",
            "source": "tracked",
            "last_price": "4.30",
            "price_min": "4.30",
            "price_max": "4.30",
            "currency": "EUR",
        },
        desired_quantity="40",
        ladder_text="1-49:4.30\n50-199:4.00",
    )
    with pytest.raises(Exception, match="moneda del costo puesto"):
        services.apply_alibaba_profitability_ceiling(
            plan_row,
            {"max_supplier_raw": "4.10", "currency": "USD"},
        )


def test_gui_missing_plan_currency_fails_closed() -> None:
    plan_row = {**_usd_plan_row(), "currency": ""}
    with pytest.raises(Exception, match="moneda del costo puesto"):
        services.apply_alibaba_profitability_ceiling(
            plan_row,
            {"max_supplier_raw": "4.10", "currency": "USD"},
        )


def test_gui_missing_landed_currency_fails_closed() -> None:
    with pytest.raises(Exception, match="moneda del costo puesto"):
        services.apply_alibaba_profitability_ceiling(
            _usd_plan_row(),
            {"max_supplier_raw": "4.10"},
        )


def test_gui_invalid_landed_currency_fails_closed() -> None:
    with pytest.raises(Exception, match="moneda del costo puesto"):
        services.apply_alibaba_profitability_ceiling(
            _usd_plan_row(),
            {"max_supplier_raw": "4.10", "currency": "${0}"},
        )


def test_gui_cny_plan_cny_landed_applies() -> None:
    plan_row = _cny_plan_row()
    applied = services.apply_alibaba_profitability_ceiling(
        plan_row,
        {
            "max_supplier_raw": "4.10",
            "rate_status": ShippingRateStatus.ESTIMATE.value,
            "currency": "CNY",
        },
    )
    assert applied["profitability_applied"] == "1"
    assert applied["ceiling_price"] == "CNY 4.10"
    assert "$4.10" not in applied.values()


def test_gui_mismatch_does_not_call_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("must not compare amounts across currencies")

    monkeypatch.setattr(
        "bera_price_tracker.application.import_aware_negotiation.apply_profitability_ceiling",
        boom,
    )
    with pytest.raises(Exception, match="moneda del costo puesto"):
        services.apply_alibaba_profitability_ceiling(
            _cny_plan_row(),
            {"max_supplier_raw": "4.10", "currency": "USD"},
        )


def test_state_shows_mismatch_hint_without_rewriting_plan() -> None:
    from bera_price_tracker.gui.state import TrackerState

    plan_row = _cny_plan_row()
    plan_row["product_id"] = "P-1"
    state = TrackerState()
    state.alibaba_negotiation_has_plan = True
    state.alibaba_negotiation_plan_payload = dict(plan_row)
    state.alibaba_negotiation_opening = plan_row["opening_offer"]
    state.alibaba_negotiation_target = plan_row["target_price"]
    state.alibaba_negotiation_ceiling = plan_row["ceiling_price"]
    state.alibaba_landed_has_result = True
    state.alibaba_landed_product_id = "P-1"
    state.alibaba_landed_result = {
        "max_supplier_raw": "4.10",
        "currency": "USD",
        "rate_status": ShippingRateStatus.ESTIMATE.value,
    }
    state.apply_alibaba_profitability_ceiling()
    assert state.alibaba_negotiation_profitability_hint == PROFITABILITY_CURRENCY_MISMATCH
    assert state.alibaba_negotiation_has_profitability is False
    assert state.alibaba_negotiation_opening == plan_row["opening_offer"]
    assert state.alibaba_negotiation_target == plan_row["target_price"]
    assert state.alibaba_negotiation_ceiling == plan_row["ceiling_price"]


def test_state_rejects_profitability_from_another_product_landed_cost() -> None:
    from bera_price_tracker.gui.state import TrackerState

    plan_row = _usd_plan_row()
    plan_row["product_id"] = "mouse-A"
    state = TrackerState()
    state.alibaba_negotiation_has_plan = True
    state.alibaba_negotiation_plan_payload = dict(plan_row)
    state.alibaba_negotiation_opening = plan_row["opening_offer"]
    state.alibaba_negotiation_target = plan_row["target_price"]
    state.alibaba_negotiation_ceiling = plan_row["ceiling_price"]
    state.alibaba_landed_has_result = True
    state.alibaba_landed_product_id = "headphones-B"
    state.alibaba_landed_result = {
        "max_supplier_raw": "4.10",
        "currency": "USD",
        "rate_status": ShippingRateStatus.ESTIMATE.value,
    }
    state.apply_alibaba_profitability_ceiling()
    assert state.alibaba_negotiation_profitability_hint == (
        services.ALIBABA_PROFITABILITY_PRODUCT_MISMATCH
    )
    assert state.alibaba_negotiation_has_profitability is False
    assert state.alibaba_negotiation_ceiling == plan_row["ceiling_price"]


def test_state_rejects_profitability_when_landed_product_id_is_missing() -> None:
    from bera_price_tracker.gui.state import TrackerState

    plan_row = _usd_plan_row()
    plan_row["product_id"] = "mouse-A"
    state = TrackerState()
    state.alibaba_negotiation_has_plan = True
    state.alibaba_negotiation_plan_payload = dict(plan_row)
    state.alibaba_negotiation_ceiling = plan_row["ceiling_price"]
    state.alibaba_landed_has_result = True
    state.alibaba_landed_product_id = ""
    state.alibaba_landed_result = {
        "max_supplier_raw": "4.10",
        "currency": "USD",
        "rate_status": ShippingRateStatus.ESTIMATE.value,
    }
    state.apply_alibaba_profitability_ceiling()
    assert state.alibaba_negotiation_profitability_hint == (
        services.ALIBABA_PROFITABILITY_PRODUCT_MISMATCH
    )
    assert state.alibaba_negotiation_has_profitability is False
    assert state.alibaba_negotiation_ceiling == plan_row["ceiling_price"]


def test_state_rejects_profitability_when_plan_product_id_is_missing() -> None:
    from bera_price_tracker.gui.state import TrackerState

    plan_row = _usd_plan_row()
    plan_row["product_id"] = ""
    state = TrackerState()
    state.alibaba_negotiation_has_plan = True
    state.alibaba_negotiation_plan_payload = dict(plan_row)
    state.alibaba_negotiation_ceiling = plan_row["ceiling_price"]
    state.alibaba_landed_has_result = True
    state.alibaba_landed_product_id = "mouse-A"
    state.alibaba_landed_result = {
        "max_supplier_raw": "4.10",
        "currency": "USD",
        "rate_status": ShippingRateStatus.ESTIMATE.value,
    }
    state.apply_alibaba_profitability_ceiling()
    assert state.alibaba_negotiation_profitability_hint == (
        services.ALIBABA_PROFITABILITY_PRODUCT_MISMATCH
    )
    assert state.alibaba_negotiation_has_profitability is False
    assert state.alibaba_negotiation_ceiling == plan_row["ceiling_price"]


def test_profitability_switch_from_a_to_b_and_back_to_a() -> None:
    from bera_price_tracker.gui.state import TrackerState

    plan_a = _usd_plan_row()
    plan_a["product_id"] = "mouse-A"
    plan_b = _usd_plan_row()
    plan_b["product_id"] = "headphones-B"
    landed_a = {
        "max_supplier_raw": "4.10",
        "currency": "USD",
        "rate_status": ShippingRateStatus.ESTIMATE.value,
        "unit_landed": "$99.99",
    }
    state = TrackerState()
    state.alibaba_landed_has_result = True
    state.alibaba_landed_product_id = "mouse-A"
    state.alibaba_landed_result = landed_a

    state.alibaba_negotiation_has_plan = True
    state.alibaba_negotiation_plan_payload = dict(plan_b)
    state.alibaba_negotiation_ceiling = plan_b["ceiling_price"]
    state.apply_alibaba_profitability_ceiling()
    assert state.alibaba_negotiation_profitability_hint == (
        services.ALIBABA_PROFITABILITY_PRODUCT_MISMATCH
    )
    assert state.alibaba_negotiation_has_profitability is False
    assert state.alibaba_negotiation_ceiling == plan_b["ceiling_price"]

    state.alibaba_negotiation_plan_payload = dict(plan_a)
    state.alibaba_negotiation_ceiling = plan_a["ceiling_price"]
    state.alibaba_negotiation_profitability_hint = ""
    state.apply_alibaba_profitability_ceiling()
    assert state.alibaba_negotiation_has_profitability is True
    assert state.alibaba_negotiation_profitability_hint == ""
    assert state.alibaba_negotiation_plan_payload["profitability_applied"] == "1"


def test_equal_profitability_ceiling_does_not_reduce() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(),
        maximum_supplier_unit_price=Decimal("4.30"),
        landed_currency="USD",
    )
    assert composed.applied is True
    assert composed.effective_ceiling == Decimal("4.30")
    assert composed.plan.ceiling_price == Decimal("4.30")
    assert composed.plan.opening_offer == Decimal("4.03")
    assert "no aumenta el máximo" in composed.profitability_note


def test_zero_profitability_is_unattractive_without_crossing_currencies() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(),
        maximum_supplier_unit_price=Decimal("0"),
        landed_currency="USD",
    )
    assert composed.applied is True
    assert composed.plan.attractiveness is DealAttractiveness.ECONOMICALLY_UNATTRACTIVE
    assert composed.plan.opening_offer <= composed.plan.target_price <= composed.plan.ceiling_price


def test_negative_profitability_is_unattractive() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(),
        maximum_supplier_unit_price=Decimal("-0.60"),
        landed_currency="USD",
    )
    assert composed.applied is True
    assert composed.plan.attractiveness is DealAttractiveness.ECONOMICALLY_UNATTRACTIVE


def test_analysis_currency_is_used_when_landed_currency_omitted() -> None:
    analysis = calculate_landed_cost(
        LandedCostInput(
            quantity=40,
            supplier_unit_price=Decimal("4.03"),
            currency="USD",
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
    composed = apply_profitability_ceiling(_base_plan(), analysis=analysis)
    assert composed.applied is True
    assert composed.effective_ceiling == Decimal("4.30")


def test_cny_analysis_does_not_cap_usd_plan() -> None:
    analysis = calculate_landed_cost(
        LandedCostInput(
            quantity=40,
            supplier_unit_price=Decimal("4.03"),
            currency="CNY",
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
            target_margin_percent=Decimal("40"),
        )
    )
    assert analysis.currency == "CNY"
    assert analysis.maximum_supplier_unit_price is not None
    plan = _base_plan()
    composed = apply_profitability_ceiling(plan, analysis=analysis)
    assert composed.applied is False
    assert composed.plan.ceiling_price == plan.ceiling_price
    assert composed.profitability_note == PROFITABILITY_CURRENCY_MISMATCH


def test_wrong_plan_type_is_rejected() -> None:
    with pytest.raises(TypeError, match="AlibabaNegotiationPlan"):
        apply_profitability_ceiling(
            "plan",  # type: ignore[arg-type]
            maximum_supplier_unit_price=Decimal("4.10"),
            landed_currency="USD",
        )


def test_wrong_analysis_type_is_rejected() -> None:
    with pytest.raises(TypeError, match="LandedCostAnalysis"):
        apply_profitability_ceiling(
            _base_plan(),
            analysis="landed",  # type: ignore[arg-type]
            landed_currency="USD",
        )


def test_string_and_int_profitability_are_quantized() -> None:
    from_int = apply_profitability_ceiling(
        _base_plan(),
        maximum_supplier_unit_price=4,  # type: ignore[arg-type]
        landed_currency="USD",
    )
    from_text = apply_profitability_ceiling(
        _base_plan(),
        maximum_supplier_unit_price="4.10",  # type: ignore[arg-type]
        landed_currency="USD",
    )
    assert from_int.applied is True
    assert from_int.effective_ceiling == Decimal("4.00")
    assert from_text.applied is True
    assert from_text.effective_ceiling == Decimal("4.10")


def test_boolean_profitability_is_ignored() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(),
        maximum_supplier_unit_price=True,  # type: ignore[arg-type]
        landed_currency="USD",
    )
    assert composed.applied is False
    assert composed.profitability_note == MISSING_PROFITABILITY_CEILING


def test_gui_apply_without_plan_row_is_rejected() -> None:
    with pytest.raises(Exception, match="estrategia"):
        services.apply_alibaba_profitability_ceiling(
            {},
            {"max_supplier_raw": "4.10", "currency": "USD"},
        )


def test_gui_invalid_max_supplier_after_currency_match() -> None:
    with pytest.raises(Exception, match="rentabilidad"):
        services.apply_alibaba_profitability_ceiling(
            _usd_plan_row(),
            {"max_supplier_raw": "not-a-price", "currency": "USD"},
        )


def test_gui_blank_max_supplier_after_currency_match() -> None:
    with pytest.raises(Exception, match="rentabilidad"):
        services.apply_alibaba_profitability_ceiling(
            _usd_plan_row(),
            {"max_supplier_raw": "", "currency": "USD"},
        )


def test_state_apply_without_plan_sets_hint() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.apply_alibaba_profitability_ceiling()
    assert state.alibaba_negotiation_profitability_hint == (
        "Calcula la estrategia antes de aplicar rentabilidad."
    )


def test_invalid_profitability_text_is_ignored() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(),
        maximum_supplier_unit_price="not-a-price",  # type: ignore[arg-type]
        landed_currency="USD",
    )
    assert composed.applied is False
    assert composed.profitability_note == MISSING_PROFITABILITY_CEILING


def test_dollar_text_and_non_finite_profitability_are_parsed_fail_closed() -> None:
    from_text = apply_profitability_ceiling(
        _base_plan(),
        maximum_supplier_unit_price="$4.10",  # type: ignore[arg-type]
        landed_currency="USD",
    )
    assert from_text.applied is True
    assert from_text.effective_ceiling == Decimal("4.10")
    infinite = apply_profitability_ceiling(
        _base_plan(),
        maximum_supplier_unit_price=Decimal("Infinity"),
        landed_currency="USD",
    )
    assert infinite.applied is False
    assert infinite.profitability_note == MISSING_PROFITABILITY_CEILING
    empty_container = apply_profitability_ceiling(
        _base_plan(),
        maximum_supplier_unit_price=[],  # type: ignore[arg-type]
        landed_currency="USD",
    )
    assert empty_container.applied is False


def test_no_next_tier_uses_opening_as_commercial_floor() -> None:
    plan = calculate_alibaba_negotiation_plan(
        AlibabaNegotiationInput(
            desired_quantity=40,
            title="Wireless Mouse",
            supplier_name="Example",
            min_order_quantity=1,
            tiers=(NegotiationTier(min_quantity=1, max_quantity=None, unit_price=Decimal("4.30")),),
            negotiation_aggressiveness=50,
            currency="USD",
        )
    )
    assert plan.next_tier_price is None
    composed = apply_profitability_ceiling(
        plan,
        maximum_supplier_unit_price=Decimal("4.20"),
        landed_currency="USD",
    )
    assert composed.applied is True
    assert composed.plan.ceiling_price <= plan.public_unit_price


def test_unattractive_analysis_marks_deal_without_raising_ceiling() -> None:
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
            expected_sale_price_per_unit=Decimal("3.00"),
            target_margin_percent=Decimal("40"),
        )
    )
    assert analysis.viability is LandedCostViability.ECONOMICALLY_UNATTRACTIVE
    composed = apply_profitability_ceiling(_base_plan(), analysis=analysis)
    assert composed.applied is True
    assert composed.plan.attractiveness is DealAttractiveness.ECONOMICALLY_UNATTRACTIVE


def test_explicit_kwargs_win_over_analysis_fields() -> None:
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
            rate=ShippingRateProfile(
                rate_usd_per_cbm=Decimal("800"),
                status=ShippingRateStatus.CONFIRMED_QUOTE,
            ),
            expected_sale_price_per_unit=Decimal("10.00"),
            target_margin_percent=Decimal("30"),
        )
    )
    composed = apply_profitability_ceiling(
        _base_plan(),
        analysis=analysis,
        maximum_supplier_unit_price=Decimal("4.10"),
        rate_status=ShippingRateStatus.ESTIMATE,
        landed_currency="USD",
    )
    assert composed.applied is True
    assert composed.effective_ceiling == Decimal("4.10")
    assert composed.rate_status is ShippingRateStatus.ESTIMATE


def test_zero_opening_is_clamped_to_money_quantum() -> None:
    from dataclasses import replace

    plan = replace(_base_plan(), opening_offer=Decimal("0"))
    composed = apply_profitability_ceiling(
        plan,
        maximum_supplier_unit_price=Decimal("4.10"),
        landed_currency="USD",
    )
    assert composed.applied is True
    assert composed.plan.opening_offer > Decimal("0")
    assert composed.plan.opening_offer <= composed.plan.target_price


def test_already_unattractive_plan_stays_unattractive_when_ceiling_is_high() -> None:
    from dataclasses import replace

    plan = replace(_base_plan(), attractiveness=DealAttractiveness.ECONOMICALLY_UNATTRACTIVE)
    composed = apply_profitability_ceiling(
        plan,
        maximum_supplier_unit_price=Decimal("5.00"),
        landed_currency="USD",
    )
    assert composed.applied is True
    assert composed.effective_ceiling == Decimal("4.30")
    assert composed.plan.attractiveness is DealAttractiveness.ECONOMICALLY_UNATTRACTIVE


def test_attractive_analysis_does_not_mark_deal_unattractive() -> None:
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
    assert analysis.viability is LandedCostViability.ATTRACTIVE
    composed = apply_profitability_ceiling(_base_plan(), analysis=analysis)
    assert composed.applied is True
    assert composed.plan.attractiveness is DealAttractiveness.ATTRACTIVE
    assert composed.rate_status is analysis.rate_status


def test_ceiling_equal_to_original_opening_stays_attractive() -> None:
    plan = _base_plan()
    composed = apply_profitability_ceiling(
        plan,
        maximum_supplier_unit_price=plan.opening_offer,
        landed_currency="USD",
    )
    assert composed.plan.opening_offer == plan.opening_offer
    assert composed.plan.ceiling_price == plan.opening_offer
    assert composed.plan.attractiveness is DealAttractiveness.ATTRACTIVE


def test_ceiling_equal_to_raised_commercial_floor_stays_attractive() -> None:
    from dataclasses import replace

    plan = replace(_base_plan(), next_tier_price=Decimal("4.20"))
    composed = apply_profitability_ceiling(
        plan,
        maximum_supplier_unit_price=Decimal("4.20"),
        landed_currency="USD",
    )
    assert composed.plan.ceiling_price == Decimal("4.20")
    assert composed.plan.attractiveness is DealAttractiveness.ATTRACTIVE


def test_unattractive_analysis_stays_unattractive_if_kwargs_raise_amount() -> None:
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
            expected_sale_price_per_unit=Decimal("3.00"),
            target_margin_percent=Decimal("40"),
        )
    )
    assert analysis.viability is LandedCostViability.ECONOMICALLY_UNATTRACTIVE
    composed = apply_profitability_ceiling(
        _base_plan(),
        analysis=analysis,
        maximum_supplier_unit_price=Decimal("4.10"),
        landed_currency="USD",
    )
    assert composed.applied is True
    assert composed.effective_ceiling == Decimal("4.10")
    assert composed.plan.attractiveness is DealAttractiveness.ECONOMICALLY_UNATTRACTIVE


def test_applied_plan_preserves_identity_and_appends_note() -> None:
    plan = _base_plan()
    composed = apply_profitability_ceiling(
        plan,
        maximum_supplier_unit_price=Decimal("4.10"),
        landed_currency="USD",
        rate_status=ShippingRateStatus.ESTIMATE,
    )
    adjusted = composed.plan
    assert adjusted.title == plan.title
    assert adjusted.supplier_name == plan.supplier_name
    assert adjusted.min_order_quantity == plan.min_order_quantity
    assert adjusted.public_unit_price == plan.public_unit_price
    assert adjusted.negotiable_reference == plan.negotiable_reference
    assert adjusted.selected_min_quantity == plan.selected_min_quantity
    assert adjusted.selected_max_quantity == plan.selected_max_quantity
    assert adjusted.next_tier_min_quantity == plan.next_tier_min_quantity
    assert adjusted.next_tier_price == plan.next_tier_price
    assert adjusted.tier_proximity == plan.tier_proximity
    assert adjusted.max_product_unit_price == plan.max_product_unit_price
    assert adjusted.aggressiveness == plan.aggressiveness
    assert adjusted.ladder_summary == plan.ladder_summary
    assert adjusted.warnings == plan.warnings
    assert adjusted.currency == plan.currency
    assert adjusted.bounds.public_unit_price == adjusted.public_unit_price
    assert adjusted.bounds.opening_offer == adjusted.opening_offer
    assert adjusted.bounds.target_price == adjusted.target_price
    assert adjusted.bounds.ceiling_price == adjusted.ceiling_price
    assert adjusted.bounds.negotiable_reference == adjusted.negotiable_reference
    assert composed.profitability_note in adjusted.explanation


def test_unapplied_mismatch_keeps_original_ceiling_and_status() -> None:
    plan = calculate_alibaba_negotiation_plan(_input(currency="CNY"))
    composed = apply_profitability_ceiling(
        plan,
        maximum_supplier_unit_price=Decimal("4.10"),
        landed_currency="USD",
        rate_status=ShippingRateStatus.CONFIRMED_QUOTE,
    )
    assert composed.applied is False
    assert composed.original_ceiling == plan.ceiling_price
    assert composed.effective_ceiling == plan.ceiling_price
    assert composed.rate_status is ShippingRateStatus.CONFIRMED_QUOTE
    assert composed.provenance == CONFIRMED_PROVENANCE


def test_thousands_separator_in_profitability_text_is_stripped() -> None:
    composed = apply_profitability_ceiling(
        _base_plan(),
        maximum_supplier_unit_price="$1,000.00",  # type: ignore[arg-type]
        landed_currency="USD",
    )
    assert composed.applied is True
    assert composed.profitability_ceiling == Decimal("1000.00")
    assert composed.effective_ceiling == Decimal("4.30")


def test_execute_forwards_analysis_and_explicit_kwargs() -> None:
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
            target_margin_percent=Decimal("40"),
        )
    )
    from_analysis = CalculateImportAwareNegotiationPlan().execute(_input(), analysis)
    assert from_analysis.applied is True
    assert from_analysis.profitability_ceiling == analysis.maximum_supplier_unit_price
    assert from_analysis.rate_status is analysis.rate_status

    from_kwargs = CalculateImportAwareNegotiationPlan().execute(
        _input(),
        maximum_supplier_unit_price=Decimal("4.10"),
        rate_status=ShippingRateStatus.ESTIMATE,
        landed_currency="USD",
    )
    assert from_kwargs.applied is True
    assert from_kwargs.effective_ceiling == Decimal("4.10")
    assert from_kwargs.rate_status is ShippingRateStatus.ESTIMATE
    assert from_kwargs.provenance == ESTIMATE_PROVENANCE

    blocked = CalculateImportAwareNegotiationPlan().execute(
        _input(currency="CNY"),
        maximum_supplier_unit_price=Decimal("4.10"),
        landed_currency="USD",
    )
    assert blocked.applied is False
    assert blocked.profitability_note == PROFITABILITY_CURRENCY_MISMATCH


def test_missing_profitability_still_keeps_rate_provenance() -> None:
    """Rate provenance is kept even when the ceiling cannot be applied yet.

    Remaining mutmut survivors in this module are equivalent or defensive:
    Spanish note punctuation, TypeError/ValueError wrapping, the unreachable
    incoherent-bounds raise, ``profitability_ceiling <= 0`` vs ``< 0`` (zero
    already clamps the ceiling to ``MONEY_QUANTUM``), and rewriting the
    placeholder ``explanation=""`` before ``build_negotiation_explanation``.
    """
    composed = apply_profitability_ceiling(
        _base_plan(),
        rate_status=ShippingRateStatus.ESTIMATE,
    )
    assert composed.applied is False
    assert composed.profitability_note == MISSING_PROFITABILITY_CEILING
    assert composed.rate_status is ShippingRateStatus.ESTIMATE
    assert composed.provenance == ESTIMATE_PROVENANCE
