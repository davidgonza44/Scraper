"""Compose a negotiation plan with an optional landed-cost ceiling.

``alibaba_negotiation`` still owns commercial opening/target/ceiling.
``landed_cost`` still owns ``maximum_supplier_unit_price``.
This module only applies:

    effective_ceiling = min(negotiation_ceiling, maximum_supplier_unit_price)

Landed cost may keep or reduce the ceiling. It never raises it.

Target and opening rules (deterministic, minimum change):

    effective_target  = min(original_target, effective_ceiling)
    effective_opening = min(original_opening, effective_target)
    if effective_opening <= 0: effective_opening = MONEY_QUANTUM

The deal is ECONOMICALLY_UNATTRACTIVE when the profitability ceiling is
at or below zero, below the original opening, or below the commercial
floor (next-tier price, else the original opening). MiniMax is not asked
to hide that.

This module does not call MiniMax, DTD Cargo, or any network service.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from bera_price_tracker.application.alibaba_negotiation import (
    AlibabaNegotiationInput,
    AlibabaNegotiationPlan,
    DealAttractiveness,
    NegotiationPriceBounds,
    build_negotiation_explanation,
    calculate_alibaba_negotiation_plan,
)
from bera_price_tracker.application.landed_cost import (
    LandedCostAnalysis,
    LandedCostViability,
    ShippingRateStatus,
    capped_negotiation_ceiling,
)
from bera_price_tracker.domain.money import MONEY_QUANTUM, quantize_money

MISSING_PROFITABILITY_CEILING = (
    "Completa el costo de importación para calcular el máximo por rentabilidad."
)

ESTIMATE_PROVENANCE = "estimación logística"
CONFIRMED_PROVENANCE = "cotización logística confirmada"


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportAwareNegotiationPlan:
    """Negotiation plan plus explicit ceiling provenance. MiniMax never sees this."""

    plan: AlibabaNegotiationPlan
    original_ceiling: Decimal
    profitability_ceiling: Decimal | None
    effective_ceiling: Decimal
    applied: bool
    rate_status: ShippingRateStatus | None
    provenance: str | None
    profitability_note: str


def _quantize_optional_money(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, int):
        parsed = Decimal(value)
    elif isinstance(value, str) and value.strip():
        try:
            parsed = Decimal(value.strip().replace(",", "").replace("$", ""))
        except InvalidOperation:
            return None
    else:
        return None
    if not parsed.is_finite():
        return None
    return quantize_money(parsed)


def _commercial_floor(plan: AlibabaNegotiationPlan) -> Decimal:
    if plan.next_tier_price is not None:
        return plan.next_tier_price
    return plan.opening_offer


def _is_unattractive(
    plan: AlibabaNegotiationPlan,
    *,
    profitability_ceiling: Decimal,
    effective_ceiling: Decimal,
    analysis: LandedCostAnalysis | None,
) -> bool:
    if plan.attractiveness is DealAttractiveness.ECONOMICALLY_UNATTRACTIVE:
        return True
    if analysis is not None and analysis.viability is LandedCostViability.ECONOMICALLY_UNATTRACTIVE:
        return True
    if profitability_ceiling <= Decimal("0"):
        return True
    if effective_ceiling < plan.opening_offer:
        return True
    return effective_ceiling < _commercial_floor(plan)


def _profitability_note(
    *,
    original_ceiling: Decimal,
    effective_ceiling: Decimal,
    reduced: bool,
    rate_status: ShippingRateStatus | None,
) -> str:
    if not reduced:
        return (
            "La rentabilidad no aumenta el máximo de negociación. "
            f"El máximo autorizado sigue en ${original_ceiling}."
        )
    if rate_status is ShippingRateStatus.CONFIRMED_QUOTE:
        return (
            "El costo de importación según cotización logística confirmada "
            f"reduce tu máximo de compra de ${original_ceiling} a ${effective_ceiling} "
            "para mantener el margen objetivo."
        )
    return (
        "El costo estimado de importación reduce tu máximo de compra de "
        f"${original_ceiling} a ${effective_ceiling} para mantener el margen objetivo."
    )


def _rebuild_plan(
    plan: AlibabaNegotiationPlan,
    *,
    opening: Decimal,
    target: Decimal,
    ceiling: Decimal,
    attractiveness: DealAttractiveness,
    extra_explanation: str,
) -> AlibabaNegotiationPlan:
    bounds = NegotiationPriceBounds(
        public_unit_price=plan.public_unit_price,
        opening_offer=opening,
        target_price=target,
        ceiling_price=ceiling,
        negotiable_reference=plan.negotiable_reference,
    )
    draft = AlibabaNegotiationPlan(
        title=plan.title,
        supplier_name=plan.supplier_name,
        desired_quantity=plan.desired_quantity,
        min_order_quantity=plan.min_order_quantity,
        public_unit_price=plan.public_unit_price,
        opening_offer=opening,
        target_price=target,
        ceiling_price=ceiling,
        negotiable_reference=plan.negotiable_reference,
        selected_min_quantity=plan.selected_min_quantity,
        selected_max_quantity=plan.selected_max_quantity,
        next_tier_min_quantity=plan.next_tier_min_quantity,
        next_tier_price=plan.next_tier_price,
        tier_proximity=plan.tier_proximity,
        max_product_unit_price=plan.max_product_unit_price,
        aggressiveness=plan.aggressiveness,
        attractiveness=attractiveness,
        explanation="",
        ladder_summary=plan.ladder_summary,
        warnings=plan.warnings,
        bounds=bounds,
    )
    explanation = build_negotiation_explanation(draft)
    if extra_explanation:
        explanation = f"{explanation} {extra_explanation}"
    return AlibabaNegotiationPlan(
        title=draft.title,
        supplier_name=draft.supplier_name,
        desired_quantity=draft.desired_quantity,
        min_order_quantity=draft.min_order_quantity,
        public_unit_price=draft.public_unit_price,
        opening_offer=draft.opening_offer,
        target_price=draft.target_price,
        ceiling_price=draft.ceiling_price,
        negotiable_reference=draft.negotiable_reference,
        selected_min_quantity=draft.selected_min_quantity,
        selected_max_quantity=draft.selected_max_quantity,
        next_tier_min_quantity=draft.next_tier_min_quantity,
        next_tier_price=draft.next_tier_price,
        tier_proximity=draft.tier_proximity,
        max_product_unit_price=draft.max_product_unit_price,
        aggressiveness=draft.aggressiveness,
        attractiveness=draft.attractiveness,
        explanation=explanation,
        ladder_summary=draft.ladder_summary,
        warnings=draft.warnings,
        bounds=draft.bounds,
    )


def apply_profitability_ceiling(
    plan: AlibabaNegotiationPlan,
    *,
    analysis: LandedCostAnalysis | None = None,
    maximum_supplier_unit_price: Decimal | None = None,
    rate_status: ShippingRateStatus | None = None,
) -> ImportAwareNegotiationPlan:
    """Cap an already-computed plan. Pass ``None`` to leave it unchanged."""

    if not isinstance(plan, AlibabaNegotiationPlan):
        raise TypeError("plan must be an AlibabaNegotiationPlan")
    profitability = maximum_supplier_unit_price
    status = rate_status
    if analysis is not None:
        if not isinstance(analysis, LandedCostAnalysis):
            raise TypeError("analysis must be a LandedCostAnalysis")
        if profitability is None:
            profitability = analysis.maximum_supplier_unit_price
        if status is None:
            status = analysis.rate_status
    profitability = _quantize_optional_money(profitability)
    original = plan.ceiling_price
    provenance = None
    if status is ShippingRateStatus.CONFIRMED_QUOTE:
        provenance = CONFIRMED_PROVENANCE
    elif status is ShippingRateStatus.ESTIMATE:
        provenance = ESTIMATE_PROVENANCE
    if profitability is None:
        return ImportAwareNegotiationPlan(
            plan=plan,
            original_ceiling=original,
            profitability_ceiling=None,
            effective_ceiling=original,
            applied=False,
            rate_status=status,
            provenance=provenance,
            profitability_note=MISSING_PROFITABILITY_CEILING,
        )
    capped = (
        MONEY_QUANTUM
        if profitability <= Decimal("0")
        else capped_negotiation_ceiling(original, profitability)
    )
    target = min(plan.target_price, capped)
    opening = min(plan.opening_offer, target)
    if opening <= Decimal("0"):
        opening = MONEY_QUANTUM
    reduced = capped < original
    note = _profitability_note(
        original_ceiling=original,
        effective_ceiling=capped,
        reduced=reduced,
        rate_status=status,
    )
    attractiveness = (
        DealAttractiveness.ECONOMICALLY_UNATTRACTIVE
        if _is_unattractive(
            plan,
            profitability_ceiling=profitability,
            effective_ceiling=capped,
            analysis=analysis,
        )
        else DealAttractiveness.ATTRACTIVE
    )
    adjusted = _rebuild_plan(
        plan,
        opening=opening,
        target=target,
        ceiling=capped,
        attractiveness=attractiveness,
        extra_explanation=note,
    )
    if not (adjusted.opening_offer <= adjusted.target_price <= adjusted.ceiling_price):
        raise ValueError("Los límites de negociación quedaron incoherentes.")
    return ImportAwareNegotiationPlan(
        plan=adjusted,
        original_ceiling=original,
        profitability_ceiling=profitability,
        effective_ceiling=capped,
        applied=True,
        rate_status=status,
        provenance=provenance,
        profitability_note=note,
    )


class CalculateImportAwareNegotiationPlan:
    """Commercial plan first, then an optional landed-cost ceiling."""

    def execute(
        self,
        payload: AlibabaNegotiationInput,
        analysis: LandedCostAnalysis | None = None,
        *,
        maximum_supplier_unit_price: Decimal | None = None,
        rate_status: ShippingRateStatus | None = None,
    ) -> ImportAwareNegotiationPlan:
        plan = calculate_alibaba_negotiation_plan(payload)
        return apply_profitability_ceiling(
            plan,
            analysis=analysis,
            maximum_supplier_unit_price=maximum_supplier_unit_price,
            rate_status=rate_status,
        )


__all__ = [
    "CONFIRMED_PROVENANCE",
    "ESTIMATE_PROVENANCE",
    "MISSING_PROFITABILITY_CEILING",
    "CalculateImportAwareNegotiationPlan",
    "ImportAwareNegotiationPlan",
    "apply_profitability_ceiling",
]
