"""Offline tests for the Venezuela landed-cost calculator. No network calls."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from bera_price_tracker.application.landed_cost import (
    MISSING_CARTON_COUNT,
    MISSING_CARTON_DIMENSIONS,
    MISSING_GROSS_WEIGHT,
    MISSING_LOGISTICS_PREFIX,
    MISSING_UNITS_PER_CARTON,
    CargoPackagingInput,
    ImportOtherCosts,
    LandedCostError,
    LandedCostInput,
    LandedCostViability,
    ShippingRateProfile,
    ShippingRateStatus,
    ShippingSurcharges,
    calculate_landed_cost,
    capped_negotiation_ceiling,
    carton_cbm,
    missing_logistics_fields,
)
from bera_price_tracker.gui import services

SRC = Path(__file__).resolve().parents[2] / "src"
LANDED = SRC / "bera_price_tracker" / "application" / "landed_cost.py"

# 800 USD/CBM is a TEST fixture rate, not a contractual DTD Cargo tariff.
TEST_RATE = Decimal("800")


def _packaging() -> CargoPackagingInput:
    return CargoPackagingInput(
        cartons=2,
        units_per_carton=20,
        carton_length_cm=Decimal("50"),
        carton_width_cm=Decimal("40"),
        carton_height_cm=Decimal("30"),
        gross_weight_kg_per_carton=Decimal("8"),
    )


def _input(
    *,
    quantity: int = 40,
    price: Decimal = Decimal("4.03"),
    packaging: CargoPackagingInput | None = None,
    rate: Decimal = TEST_RATE,
    surcharges: ShippingSurcharges | None = None,
    import_costs: ImportOtherCosts | None = None,
    sale: Decimal | None = None,
    margin: Decimal | None = None,
) -> LandedCostInput:
    return LandedCostInput(
        quantity=quantity,
        supplier_unit_price=price,
        packaging=_packaging() if packaging is None else packaging,
        rate=ShippingRateProfile(rate_usd_per_cbm=rate),
        surcharges=ShippingSurcharges() if surcharges is None else surcharges,
        import_costs=ImportOtherCosts() if import_costs is None else import_costs,
        expected_sale_price_per_unit=sale,
        target_margin_percent=margin,
    )


def test_carton_cbm_50_40_30_is_0_06() -> None:
    assert carton_cbm(Decimal("50"), Decimal("40"), Decimal("30")) == Decimal("0.060000")


def test_two_cartons_total_cbm_is_0_12() -> None:
    analysis = calculate_landed_cost(_input())
    assert analysis.carton_cbm == Decimal("0.060000")
    assert analysis.total_cbm == Decimal("0.120000")


def test_freight_base_0_12_times_800_is_96() -> None:
    analysis = calculate_landed_cost(_input())
    assert analysis.freight_base == Decimal("96.00")
    assert analysis.freight_adjusted == Decimal("96.00")


def test_merchandise_40_times_4_03_is_161_20() -> None:
    analysis = calculate_landed_cost(_input())
    assert analysis.merchandise_cost == Decimal("161.20")


def test_total_landed_cost_is_257_20() -> None:
    analysis = calculate_landed_cost(_input())
    assert analysis.shipping_total == Decimal("96.00")
    assert analysis.other_import_costs == Decimal("0.00")
    assert analysis.total_landed_cost == Decimal("257.20")


def test_landed_cost_per_unit_is_6_43() -> None:
    analysis = calculate_landed_cost(_input())
    assert analysis.landed_cost_per_unit == Decimal("6.43")


def test_battery_multiplier_scales_freight_only() -> None:
    analysis = calculate_landed_cost(
        _input(surcharges=ShippingSurcharges(battery_multiplier=Decimal("1.5")))
    )
    assert analysis.freight_base == Decimal("96.00")
    assert analysis.freight_adjusted == Decimal("144.00")
    assert analysis.shipping_total == Decimal("144.00")


def test_surcharges_added_after_battery_multiplier() -> None:
    analysis = calculate_landed_cost(
        _input(
            surcharges=ShippingSurcharges(
                battery_multiplier=Decimal("2"),
                pallet_or_wood_surcharge=Decimal("10"),
                insurance=Decimal("5.50"),
                pickup_cost=Decimal("3"),
            )
        )
    )
    # adjusted = 96 * 2 = 192; surcharges are NOT multiplied.
    assert analysis.freight_adjusted == Decimal("192.00")
    assert analysis.shipping_surcharges == Decimal("18.50")
    assert analysis.shipping_total == Decimal("210.50")


def test_other_import_costs_are_separate_from_shipping() -> None:
    analysis = calculate_landed_cost(
        _input(
            import_costs=ImportOtherCosts(
                bank_fees=Decimal("4"),
                inspection_cost=Decimal("6"),
            )
        )
    )
    assert analysis.shipping_total == Decimal("96.00")
    assert analysis.other_import_costs == Decimal("10.00")
    assert analysis.total_landed_cost == Decimal("267.20")


def test_expected_revenue_400_and_profit() -> None:
    analysis = calculate_landed_cost(_input(sale=Decimal("10.00")))
    assert analysis.revenue == Decimal("400.00")
    assert analysis.gross_profit == Decimal("142.80")
    assert analysis.gross_profit_per_unit == Decimal("3.57")


def test_margin_is_35_70_percent() -> None:
    analysis = calculate_landed_cost(_input(sale=Decimal("10.00")))
    assert analysis.margin_percent == Decimal("35.70")


def test_break_even_equals_landed_cost_per_unit() -> None:
    analysis = calculate_landed_cost(_input())
    assert analysis.break_even_sale_price == analysis.landed_cost_per_unit == Decimal("6.43")


def test_target_margin_max_total_unit_cost() -> None:
    analysis = calculate_landed_cost(_input(sale=Decimal("10.00"), margin=Decimal("30")))
    assert analysis.max_total_unit_cost == Decimal("7.00")


def test_max_supplier_price_subtracts_non_product_cost() -> None:
    analysis = calculate_landed_cost(_input(sale=Decimal("10.00"), margin=Decimal("30")))
    # non-product = 96 / 40 = 2.40; max supplier = 7.00 - 2.40 = 4.60
    assert analysis.non_product_cost_per_unit == Decimal("2.40")
    assert analysis.maximum_supplier_unit_price == Decimal("4.60")
    assert analysis.viability is LandedCostViability.ATTRACTIVE


def test_economically_unattractive_when_margin_leaves_nothing() -> None:
    analysis = calculate_landed_cost(_input(sale=Decimal("3.00"), margin=Decimal("40")))
    # max_total = 1.80; non-product = 2.40 → -0.60
    assert analysis.maximum_supplier_unit_price == Decimal("-0.60")
    assert analysis.viability is LandedCostViability.ECONOMICALLY_UNATTRACTIVE


def test_capped_negotiation_ceiling_helper() -> None:
    assert capped_negotiation_ceiling(Decimal("4.30"), Decimal("4.60")) == Decimal("4.30")
    assert capped_negotiation_ceiling(Decimal("4.30"), Decimal("4.10")) == Decimal("4.10")
    assert capped_negotiation_ceiling(Decimal("4.30"), None) == Decimal("4.30")


def test_invalid_quantity_is_rejected() -> None:
    with pytest.raises(LandedCostError, match="cantidad"):
        calculate_landed_cost(_input(quantity=0))


def test_missing_dimensions_are_listed_not_invented() -> None:
    packaging = CargoPackagingInput(cartons=2)
    missing = missing_logistics_fields(packaging)
    assert MISSING_CARTON_DIMENSIONS in missing
    assert MISSING_GROSS_WEIGHT in missing
    assert MISSING_UNITS_PER_CARTON in missing
    assert MISSING_CARTON_COUNT not in missing
    with pytest.raises(LandedCostError, match=MISSING_LOGISTICS_PREFIX):
        calculate_landed_cost(_input(packaging=packaging))


def test_rate_is_estimate_by_default_and_confirmable() -> None:
    assert ShippingRateProfile(rate_usd_per_cbm=TEST_RATE).status is ShippingRateStatus.ESTIMATE
    confirmed = ShippingRateProfile(
        rate_usd_per_cbm=TEST_RATE,
        status=ShippingRateStatus.CONFIRMED_QUOTE,
        rate_source="cotización DTD",
    )
    assert (
        calculate_landed_cost(_input(packaging=_packaging())).rate_status
        is ShippingRateStatus.ESTIMATE
    )
    analysis = calculate_landed_cost(
        LandedCostInput(
            quantity=40,
            supplier_unit_price=Decimal("4.03"),
            packaging=_packaging(),
            rate=confirmed,
        )
    )
    assert analysis.rate_status is ShippingRateStatus.CONFIRMED_QUOTE


def test_decimal_only_no_float() -> None:
    text = LANDED.read_text(encoding="utf-8")
    assert "float(" not in text
    assert "Decimal" in text


def test_no_dependency_on_minimax_or_ollama() -> None:
    imports = [
        line
        for line in LANDED.read_text(encoding="utf-8").splitlines()
        if line.startswith(("import ", "from "))
    ]
    blob = "\n".join(imports).lower()
    for banned in ("minimax", "ollama", "drafter", "httpx", "apify", "apify_client"):
        assert banned not in blob


def test_no_dependency_on_negotiation_scoring_or_tracking() -> None:
    text = LANDED.read_text(encoding="utf-8")
    for banned in (
        "alibaba_negotiation",
        "alibaba_score",
        "alibaba_ranking",
        "alibaba_tracking",
        "alibaba_refresh",
    ):
        assert banned not in text


def test_gui_service_returns_display_row() -> None:
    row = services.calculate_alibaba_landed_cost(
        quantity="40",
        supplier_unit_price="4.03",
        cartons="2",
        units_per_carton="20",
        carton_length_cm="50",
        carton_width_cm="40",
        carton_height_cm="30",
        gross_weight_kg_per_carton="8",
        rate_usd_per_cbm="800",
        expected_sale_price="10.00",
        target_margin_percent="30",
    )
    assert row["merchandise_cost"] == "$161.20"
    assert row["shipping_total"] == "$96.00"
    assert row["total_landed_cost"] == "$257.20"
    assert row["landed_cost_per_unit"] == "$6.43"
    assert row["total_cbm"] == "0.12 CBM"
    assert row["total_weight"] == "16 kg"
    assert row["expected_sale_price"] == "$10.00"
    assert row["gross_profit_per_unit"] == "$3.57"
    assert row["margin_percent"] == "35.70%"
    assert row["max_supplier_price"] == "$4.60"
    assert row["rate_label"] == services.ALIBABA_LANDED_ESTIMATE_LABEL
    assert row["unattractive"] == "0"


def test_gui_service_battery_and_confirmed_quote() -> None:
    row = services.calculate_alibaba_landed_cost(
        quantity="40",
        supplier_unit_price="4.03",
        cartons="2",
        units_per_carton="20",
        carton_length_cm="50",
        carton_width_cm="40",
        carton_height_cm="30",
        gross_weight_kg_per_carton="8",
        rate_usd_per_cbm="800",
        rate_confirmed=True,
        has_battery=True,
        battery_multiplier="1.5",
    )
    assert row["freight_adjusted"] == "$144.00"
    assert row["rate_label"] == services.ALIBABA_LANDED_CONFIRMED_LABEL


def test_gui_service_reports_missing_logistics() -> None:
    with pytest.raises(LandedCostError, match=MISSING_LOGISTICS_PREFIX):
        services.calculate_alibaba_landed_cost(
            quantity="40",
            supplier_unit_price="4.03",
            cartons="",
            units_per_carton="",
            carton_length_cm="",
            carton_width_cm="",
            carton_height_cm="",
            gross_weight_kg_per_carton="",
            rate_usd_per_cbm="800",
        )


def test_views_expose_landed_cost_section() -> None:
    views = (SRC / "bera_price_tracker" / "gui" / "views.py").read_text(encoding="utf-8")
    assert "Importación / Costo Venezuela" in views
    assert "Calcular costo puesto en Venezuela" in views
    assert "Tarifa DTD USD/CBM" in views
    assert "No se consulta DTD Cargo" in views


def test_estimate_label_is_visible_not_definitive() -> None:
    assert services.ALIBABA_LANDED_ESTIMATE_LABEL == "ESTIMACIÓN LOGÍSTICA"
    gui_views = (SRC / "bera_price_tracker" / "gui" / "views.py").read_text(encoding="utf-8")
    assert "Costo DTD definitivo" not in gui_views
