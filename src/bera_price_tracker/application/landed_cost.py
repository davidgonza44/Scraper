"""Deterministic landed-cost calculator for imports into Venezuela.

Python owns every formula. This module never calls DTD Cargo, Apify, or any
network service, and it is independent of the Alibaba negotiation engine.
All money math uses Decimal.

Shipping total is computed in this exact order:

    freight_base      = total_cbm * rate_usd_per_cbm
    freight_adjusted  = freight_base * battery_multiplier
    shipping_total    = freight_adjusted
                        + pallet_or_wood_surcharge
                        + insurance
                        + pickup_cost
                        + delivery_extra
                        + customs_extra
                        + other_shipping_costs

No implicit percentages are applied anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from bera_price_tracker.domain.money import quantize_money

CBM_DIVISOR = Decimal("1000000")
CBM_QUANTUM = Decimal("0.000001")
WEIGHT_QUANTUM = Decimal("0.001")
PERCENT_QUANTUM = Decimal("0.01")

DEFAULT_CARGO_PROVIDER = "DTD Cargo"
DEFAULT_CARGO_SERVICE = "Door to Door"
DEFAULT_CARGO_DESTINATION = "Venezuela"
DEFAULT_LANDED_CURRENCY = "USD"

INVALID_LANDED_QUANTITY = "Indica una cantidad mayor que cero."
INVALID_SUPPLIER_PRICE = "El precio del proveedor no es utilizable."
INVALID_CARGO_RATE = "La tarifa USD/CBM debe ser mayor que cero."
INVALID_BATTERY_MULTIPLIER = "El multiplicador de batería debe ser mayor que cero."
INVALID_SURCHARGE = "Un recargo logístico no es utilizable."
INVALID_IMPORT_COST = "Un costo de importación no es utilizable."
INVALID_LANDED_MARGIN = "El margen objetivo debe estar entre 0 y 100."
INVALID_SALE_PRICE = "El precio de venta esperado no es utilizable."
MISSING_LOGISTICS_PREFIX = "Faltan datos logísticos"

MISSING_CARTON_COUNT = "número de cajas"
MISSING_UNITS_PER_CARTON = "unidades por caja"
MISSING_CARTON_DIMENSIONS = "dimensiones de caja (largo × ancho × alto)"
MISSING_GROSS_WEIGHT = "peso bruto por caja"


class LandedCostError(ValueError):
    """Local validation failure before a landed-cost analysis is produced."""


class ShippingRateStatus(StrEnum):
    """Whether the USD/CBM rate is a manual estimate or a confirmed quote."""

    ESTIMATE = "ESTIMATE"
    CONFIRMED_QUOTE = "CONFIRMED_QUOTE"


class LandedCostViability(StrEnum):
    """Whether the target margin leaves room to pay the supplier at all."""

    ATTRACTIVE = "ATTRACTIVE"
    ECONOMICALLY_UNATTRACTIVE = "ECONOMICALLY_UNATTRACTIVE"


def _decimal_or_none(value: object, message: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise LandedCostError(message)
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, int):
        parsed = Decimal(value)
    elif isinstance(value, str) and value.strip():
        try:
            parsed = Decimal(value.strip())
        except InvalidOperation:
            raise LandedCostError(message) from None
    else:
        raise LandedCostError(message)
    if not parsed.is_finite():
        raise LandedCostError(message)
    return parsed


def _positive_decimal_or_none(value: object, message: str) -> Decimal | None:
    parsed = _decimal_or_none(value, message)
    if parsed is not None and parsed <= Decimal("0"):
        raise LandedCostError(message)
    return parsed


def _non_negative_decimal(value: object, message: str) -> Decimal:
    parsed = _decimal_or_none(value, message)
    if parsed is None or parsed < Decimal("0"):
        raise LandedCostError(message)
    return parsed


def _positive_int_or_none(value: object, message: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise LandedCostError(message)
    if value <= 0:
        raise LandedCostError(message)
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class CargoPackagingInput:
    """Supplier-provided carton data. Missing values are never invented."""

    cartons: int | None = None
    units_per_carton: int | None = None
    carton_length_cm: Decimal | None = None
    carton_width_cm: Decimal | None = None
    carton_height_cm: Decimal | None = None
    gross_weight_kg_per_carton: Decimal | None = None

    def __post_init__(self) -> None:
        message = "Un dato de empaque no es utilizable."
        object.__setattr__(self, "cartons", _positive_int_or_none(self.cartons, message))
        object.__setattr__(
            self, "units_per_carton", _positive_int_or_none(self.units_per_carton, message)
        )
        for name in ("carton_length_cm", "carton_width_cm", "carton_height_cm"):
            object.__setattr__(self, name, _positive_decimal_or_none(getattr(self, name), message))
        object.__setattr__(
            self,
            "gross_weight_kg_per_carton",
            _positive_decimal_or_none(self.gross_weight_kg_per_carton, message),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ShippingRateProfile:
    """Editable cargo tariff. Manual rates are estimates, never confirmed truth."""

    rate_usd_per_cbm: Decimal
    provider: str = DEFAULT_CARGO_PROVIDER
    service: str = DEFAULT_CARGO_SERVICE
    destination_country: str = DEFAULT_CARGO_DESTINATION
    rate_source: str = "manual"
    rate_date: str | None = None
    status: ShippingRateStatus = ShippingRateStatus.ESTIMATE

    def __post_init__(self) -> None:
        rate = _positive_decimal_or_none(self.rate_usd_per_cbm, INVALID_CARGO_RATE)
        if rate is None:
            raise LandedCostError(INVALID_CARGO_RATE)
        object.__setattr__(self, "rate_usd_per_cbm", rate)
        if not isinstance(self.status, ShippingRateStatus):
            raise LandedCostError("El estado de la tarifa no es válido.")


@dataclass(frozen=True, slots=True, kw_only=True)
class ShippingSurcharges:
    """Manual shipping extras. Safe defaults: multiplier 1, surcharges 0."""

    battery_multiplier: Decimal = Decimal("1")
    pallet_or_wood_surcharge: Decimal = Decimal("0")
    insurance: Decimal = Decimal("0")
    pickup_cost: Decimal = Decimal("0")
    delivery_extra: Decimal = Decimal("0")
    customs_extra: Decimal = Decimal("0")
    other_shipping_costs: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        multiplier = _positive_decimal_or_none(self.battery_multiplier, INVALID_BATTERY_MULTIPLIER)
        if multiplier is None:
            raise LandedCostError(INVALID_BATTERY_MULTIPLIER)
        object.__setattr__(self, "battery_multiplier", multiplier)
        for name in (
            "pallet_or_wood_surcharge",
            "insurance",
            "pickup_cost",
            "delivery_extra",
            "customs_extra",
            "other_shipping_costs",
        ):
            object.__setattr__(
                self, name, _non_negative_decimal(getattr(self, name), INVALID_SURCHARGE)
            )

    @property
    def monetary_total(self) -> Decimal:
        return quantize_money(
            self.pallet_or_wood_surcharge
            + self.insurance
            + self.pickup_cost
            + self.delivery_extra
            + self.customs_extra
            + self.other_shipping_costs
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportOtherCosts:
    """Import costs that are not freight. Kept separate from shipping."""

    bank_fees: Decimal = Decimal("0")
    payment_fees: Decimal = Decimal("0")
    inspection_cost: Decimal = Decimal("0")
    sourcing_cost: Decimal = Decimal("0")
    local_transport: Decimal = Decimal("0")
    other_import_costs: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        for name in (
            "bank_fees",
            "payment_fees",
            "inspection_cost",
            "sourcing_cost",
            "local_transport",
            "other_import_costs",
        ):
            object.__setattr__(
                self, name, _non_negative_decimal(getattr(self, name), INVALID_IMPORT_COST)
            )

    @property
    def total(self) -> Decimal:
        return quantize_money(
            self.bank_fees
            + self.payment_fees
            + self.inspection_cost
            + self.sourcing_cost
            + self.local_transport
            + self.other_import_costs
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class LandedCostInput:
    """Purchase, packaging, tariff, and optional profitability inputs."""

    quantity: int
    supplier_unit_price: Decimal
    packaging: CargoPackagingInput
    rate: ShippingRateProfile
    currency: str = DEFAULT_LANDED_CURRENCY
    surcharges: ShippingSurcharges = ShippingSurcharges()
    import_costs: ImportOtherCosts = ImportOtherCosts()
    expected_sale_price_per_unit: Decimal | None = None
    target_margin_percent: Decimal | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class LandedCostAnalysis:
    """Full landed-cost breakdown. No component is hidden."""

    quantity: int
    currency: str
    merchandise_cost: Decimal
    carton_cbm: Decimal
    total_cbm: Decimal
    total_weight_kg: Decimal
    freight_base: Decimal
    freight_adjusted: Decimal
    shipping_surcharges: Decimal
    shipping_total: Decimal
    other_import_costs: Decimal
    total_landed_cost: Decimal
    landed_cost_per_unit: Decimal
    break_even_sale_price: Decimal
    non_product_cost_per_unit: Decimal
    rate_usd_per_cbm: Decimal
    rate_status: ShippingRateStatus
    rate_source: str
    rate_date: str | None
    provider: str
    service: str
    destination_country: str
    revenue: Decimal | None = None
    gross_profit: Decimal | None = None
    gross_profit_per_unit: Decimal | None = None
    margin_percent: Decimal | None = None
    max_total_unit_cost: Decimal | None = None
    maximum_supplier_unit_price: Decimal | None = None
    viability: LandedCostViability | None = None


def missing_logistics_fields(packaging: CargoPackagingInput) -> tuple[str, ...]:
    """Names of supplier logistics data still missing. Never invented."""

    missing: list[str] = []
    if packaging.cartons is None:
        missing.append(MISSING_CARTON_COUNT)
    if packaging.units_per_carton is None:
        missing.append(MISSING_UNITS_PER_CARTON)
    if (
        packaging.carton_length_cm is None
        or packaging.carton_width_cm is None
        or packaging.carton_height_cm is None
    ):
        missing.append(MISSING_CARTON_DIMENSIONS)
    if packaging.gross_weight_kg_per_carton is None:
        missing.append(MISSING_GROSS_WEIGHT)
    return tuple(missing)


def carton_cbm(
    length_cm: Decimal,
    width_cm: Decimal,
    height_cm: Decimal,
) -> Decimal:
    """``length * width * height / 1_000_000`` in Decimal, quantized to 1e-6."""

    volume = (length_cm * width_cm * height_cm) / CBM_DIVISOR
    return volume.quantize(CBM_QUANTUM)


def calculate_landed_cost(payload: LandedCostInput) -> LandedCostAnalysis:
    """Deterministic landed cost for Venezuela. All Decimal, no network."""

    if not isinstance(payload, LandedCostInput):
        raise TypeError("payload must be a LandedCostInput")
    if (
        isinstance(payload.quantity, bool)
        or not isinstance(payload.quantity, int)
        or payload.quantity <= 0
    ):
        raise LandedCostError(INVALID_LANDED_QUANTITY)
    unit_price = _positive_decimal_or_none(payload.supplier_unit_price, INVALID_SUPPLIER_PRICE)
    if unit_price is None:
        raise LandedCostError(INVALID_SUPPLIER_PRICE)

    missing = missing_logistics_fields(payload.packaging)
    if missing:
        raise LandedCostError(f"{MISSING_LOGISTICS_PREFIX}: {', '.join(missing)}.")
    packaging = payload.packaging
    assert packaging.cartons is not None
    assert packaging.carton_length_cm is not None
    assert packaging.carton_width_cm is not None
    assert packaging.carton_height_cm is not None
    assert packaging.gross_weight_kg_per_carton is not None

    one_carton_cbm = carton_cbm(
        packaging.carton_length_cm,
        packaging.carton_width_cm,
        packaging.carton_height_cm,
    )
    total_cbm = (one_carton_cbm * packaging.cartons).quantize(CBM_QUANTUM)
    total_weight = (packaging.gross_weight_kg_per_carton * packaging.cartons).quantize(
        WEIGHT_QUANTUM
    )

    freight_base = quantize_money(total_cbm * payload.rate.rate_usd_per_cbm)
    freight_adjusted = quantize_money(freight_base * payload.surcharges.battery_multiplier)
    surcharges_total = payload.surcharges.monetary_total
    shipping_total = quantize_money(freight_adjusted + surcharges_total)

    merchandise_cost = quantize_money(unit_price * payload.quantity)
    import_other = payload.import_costs.total
    total_landed = quantize_money(merchandise_cost + shipping_total + import_other)
    landed_per_unit = quantize_money(total_landed / payload.quantity)
    non_product_per_unit = quantize_money((shipping_total + import_other) / payload.quantity)

    sale_price = _positive_decimal_or_none(payload.expected_sale_price_per_unit, INVALID_SALE_PRICE)
    margin_input = _decimal_or_none(payload.target_margin_percent, INVALID_LANDED_MARGIN)
    if margin_input is not None and not Decimal("0") <= margin_input <= Decimal("100"):
        raise LandedCostError(INVALID_LANDED_MARGIN)

    revenue: Decimal | None = None
    gross_profit: Decimal | None = None
    gross_profit_per_unit: Decimal | None = None
    margin_percent: Decimal | None = None
    if sale_price is not None:
        revenue = quantize_money(sale_price * payload.quantity)
        gross_profit = quantize_money(revenue - total_landed)
        gross_profit_per_unit = quantize_money(sale_price - landed_per_unit)
        if revenue > Decimal("0"):
            margin_percent = (gross_profit / revenue * Decimal("100")).quantize(PERCENT_QUANTUM)

    max_total_unit_cost: Decimal | None = None
    maximum_supplier: Decimal | None = None
    viability: LandedCostViability | None = None
    if sale_price is not None and margin_input is not None:
        max_total_unit_cost = quantize_money(
            sale_price * (Decimal("1") - margin_input / Decimal("100"))
        )
        maximum_supplier = quantize_money(max_total_unit_cost - non_product_per_unit)
        viability = (
            LandedCostViability.ECONOMICALLY_UNATTRACTIVE
            if maximum_supplier <= Decimal("0")
            else LandedCostViability.ATTRACTIVE
        )

    return LandedCostAnalysis(
        quantity=payload.quantity,
        currency=payload.currency,
        merchandise_cost=merchandise_cost,
        carton_cbm=one_carton_cbm,
        total_cbm=total_cbm,
        total_weight_kg=total_weight,
        freight_base=freight_base,
        freight_adjusted=freight_adjusted,
        shipping_surcharges=surcharges_total,
        shipping_total=shipping_total,
        other_import_costs=import_other,
        total_landed_cost=total_landed,
        landed_cost_per_unit=landed_per_unit,
        break_even_sale_price=landed_per_unit,
        non_product_cost_per_unit=non_product_per_unit,
        rate_usd_per_cbm=payload.rate.rate_usd_per_cbm,
        rate_status=payload.rate.status,
        rate_source=payload.rate.rate_source,
        rate_date=payload.rate.rate_date,
        provider=payload.rate.provider,
        service=payload.rate.service,
        destination_country=payload.rate.destination_country,
        revenue=revenue,
        gross_profit=gross_profit,
        gross_profit_per_unit=gross_profit_per_unit,
        margin_percent=margin_percent,
        max_total_unit_cost=max_total_unit_cost,
        maximum_supplier_unit_price=maximum_supplier,
        viability=viability,
    )


def capped_negotiation_ceiling(
    current_ceiling: Decimal,
    maximum_supplier_unit_price: Decimal | None,
) -> Decimal:
    """Future explicit integration: ``min(ceiling, max supplier price)``.

    This helper does not modify the negotiation engine; callers opt in.
    """

    if not isinstance(current_ceiling, Decimal):
        raise TypeError("current_ceiling must be a Decimal")
    if maximum_supplier_unit_price is None:
        return current_ceiling
    if not isinstance(maximum_supplier_unit_price, Decimal):
        raise TypeError("maximum_supplier_unit_price must be a Decimal")
    return min(current_ceiling, maximum_supplier_unit_price)


__all__ = [
    "CBM_DIVISOR",
    "CBM_QUANTUM",
    "DEFAULT_CARGO_DESTINATION",
    "DEFAULT_CARGO_PROVIDER",
    "DEFAULT_CARGO_SERVICE",
    "DEFAULT_LANDED_CURRENCY",
    "INVALID_BATTERY_MULTIPLIER",
    "INVALID_CARGO_RATE",
    "INVALID_IMPORT_COST",
    "INVALID_LANDED_MARGIN",
    "INVALID_LANDED_QUANTITY",
    "INVALID_SALE_PRICE",
    "INVALID_SUPPLIER_PRICE",
    "INVALID_SURCHARGE",
    "MISSING_CARTON_COUNT",
    "MISSING_CARTON_DIMENSIONS",
    "MISSING_GROSS_WEIGHT",
    "MISSING_LOGISTICS_PREFIX",
    "MISSING_UNITS_PER_CARTON",
    "PERCENT_QUANTUM",
    "WEIGHT_QUANTUM",
    "CargoPackagingInput",
    "ImportOtherCosts",
    "LandedCostAnalysis",
    "LandedCostError",
    "LandedCostInput",
    "LandedCostViability",
    "ShippingRateProfile",
    "ShippingRateStatus",
    "ShippingSurcharges",
    "calculate_landed_cost",
    "capped_negotiation_ceiling",
    "carton_cbm",
    "missing_logistics_fields",
]
