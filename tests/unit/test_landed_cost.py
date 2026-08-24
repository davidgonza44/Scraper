"""Offline tests for the Venezuela landed-cost calculator. No network calls."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from bera_price_tracker.application.landed_cost import (
    DEFAULT_CARGO_DESTINATION,
    DEFAULT_CARGO_PROVIDER,
    DEFAULT_CARGO_SERVICE,
    INVALID_BATTERY_MULTIPLIER,
    INVALID_CARGO_RATE,
    INVALID_IMPORT_COST,
    INVALID_LANDED_MARGIN,
    INVALID_SALE_PRICE,
    INVALID_SUPPLIER_PRICE,
    INVALID_SURCHARGE,
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
    assert row["currency"] == "USD"
    assert row["landed_cost_per_unit_raw"] == "6.43"


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


def test_capped_ceiling_rejects_non_decimal_types() -> None:
    with pytest.raises(TypeError, match="current_ceiling"):
        capped_negotiation_ceiling(4.30, Decimal("4.10"))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="maximum_supplier_unit_price"):
        capped_negotiation_ceiling(Decimal("4.30"), 4.10)  # type: ignore[arg-type]


def test_payload_must_be_landed_cost_input() -> None:
    with pytest.raises(TypeError, match="LandedCostInput"):
        calculate_landed_cost("payload")  # type: ignore[arg-type]


def test_boolean_quantity_is_rejected() -> None:
    with pytest.raises(LandedCostError, match="cantidad"):
        calculate_landed_cost(_input(quantity=True))


def test_gui_landed_row_can_carry_explicit_cny_iso() -> None:
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
        currency="CNY",
    )
    assert row["currency"] == "CNY"
    assert row["max_supplier_raw"] == "4.60"
    assert row["max_supplier_price"] == "CNY 4.60"
    assert "$" not in row["max_supplier_price"]
    assert "$" not in row["landed_cost_per_unit"]


def test_string_and_int_money_inputs_match_decimal_formula() -> None:
    packaging = CargoPackagingInput(
        cartons=2,
        units_per_carton=20,
        carton_length_cm="50",  # type: ignore[arg-type]
        carton_width_cm=40,  # type: ignore[arg-type]
        carton_height_cm=Decimal("30"),
        gross_weight_kg_per_carton="8",  # type: ignore[arg-type]
    )
    analysis = calculate_landed_cost(
        LandedCostInput(
            quantity=40,
            supplier_unit_price="4.03",  # type: ignore[arg-type]
            packaging=packaging,
            rate=ShippingRateProfile(rate_usd_per_cbm="800"),  # type: ignore[arg-type]
        )
    )
    assert analysis.carton_cbm == Decimal("0.060000")
    assert analysis.freight_base == Decimal("96.00")
    assert analysis.merchandise_cost == Decimal("161.20")
    assert analysis.total_landed_cost == Decimal("257.20")
    assert analysis.landed_cost_per_unit == Decimal("6.43")


def test_boolean_money_and_packaging_are_rejected() -> None:
    with pytest.raises(LandedCostError, match=INVALID_SUPPLIER_PRICE):
        calculate_landed_cost(_input(price=True))  # type: ignore[arg-type]
    with pytest.raises(LandedCostError, match="empaque"):
        CargoPackagingInput(cartons=True)
    with pytest.raises(LandedCostError, match="empaque"):
        CargoPackagingInput(cartons="2")  # type: ignore[arg-type]


def test_invalid_nan_and_infinity_money_are_rejected() -> None:
    with pytest.raises(LandedCostError, match=INVALID_SUPPLIER_PRICE):
        calculate_landed_cost(_input(price="not-a-price"))  # type: ignore[arg-type]
    with pytest.raises(LandedCostError, match=INVALID_SUPPLIER_PRICE):
        calculate_landed_cost(_input(price=Decimal("NaN")))
    with pytest.raises(LandedCostError, match=INVALID_SUPPLIER_PRICE):
        calculate_landed_cost(_input(price=Decimal("Infinity")))
    with pytest.raises(LandedCostError, match=INVALID_SUPPLIER_PRICE):
        calculate_landed_cost(_input(price=["4.03"]))  # type: ignore[arg-type]


def test_zero_and_negative_quantity_and_dimensions_are_rejected() -> None:
    with pytest.raises(LandedCostError, match="cantidad"):
        calculate_landed_cost(_input(quantity=-1))
    with pytest.raises(LandedCostError, match="empaque"):
        CargoPackagingInput(cartons=0)
    with pytest.raises(LandedCostError, match="empaque"):
        CargoPackagingInput(cartons=-3)
    with pytest.raises(LandedCostError, match="empaque"):
        CargoPackagingInput(carton_length_cm=Decimal("0"))
    with pytest.raises(LandedCostError, match="empaque"):
        CargoPackagingInput(carton_width_cm=Decimal("-10"))


def test_zero_and_none_rate_and_invalid_status_are_rejected() -> None:
    with pytest.raises(LandedCostError, match=INVALID_CARGO_RATE):
        ShippingRateProfile(rate_usd_per_cbm=Decimal("0"))
    with pytest.raises(LandedCostError, match=INVALID_CARGO_RATE):
        ShippingRateProfile(rate_usd_per_cbm=None)  # type: ignore[arg-type]
    with pytest.raises(LandedCostError, match="estado de la tarifa"):
        ShippingRateProfile(rate_usd_per_cbm=TEST_RATE, status="manual")  # type: ignore[arg-type]


def test_zero_battery_multiplier_and_negative_surcharges_are_rejected() -> None:
    with pytest.raises(LandedCostError, match=INVALID_BATTERY_MULTIPLIER):
        ShippingSurcharges(battery_multiplier=Decimal("0"))
    with pytest.raises(LandedCostError, match=INVALID_BATTERY_MULTIPLIER):
        ShippingSurcharges(battery_multiplier=None)  # type: ignore[arg-type]
    with pytest.raises(LandedCostError, match=INVALID_SURCHARGE):
        ShippingSurcharges(insurance=Decimal("-1"))
    with pytest.raises(LandedCostError, match=INVALID_IMPORT_COST):
        ImportOtherCosts(bank_fees=Decimal("-0.01"))


def test_missing_sale_price_skips_profitability_and_keeps_landed_math() -> None:
    analysis = calculate_landed_cost(_input(sale=None, margin=Decimal("30")))
    assert analysis.total_landed_cost == Decimal("257.20")
    assert analysis.revenue is None
    assert analysis.margin_percent is None
    assert analysis.max_total_unit_cost is None
    assert analysis.maximum_supplier_unit_price is None
    assert analysis.viability is None


def test_sale_without_margin_computes_profit_but_not_max_supplier() -> None:
    analysis = calculate_landed_cost(_input(sale=Decimal("10.00"), margin=None))
    assert analysis.revenue == Decimal("400.00")
    assert analysis.gross_profit == Decimal("142.80")
    assert analysis.margin_percent == Decimal("35.70")
    assert analysis.max_total_unit_cost is None
    assert analysis.maximum_supplier_unit_price is None
    assert analysis.viability is None


def test_invalid_sale_and_margin_bounds_are_rejected() -> None:
    with pytest.raises(LandedCostError, match=INVALID_SALE_PRICE):
        calculate_landed_cost(_input(sale=Decimal("0")))
    with pytest.raises(LandedCostError, match=INVALID_LANDED_MARGIN):
        calculate_landed_cost(_input(sale=Decimal("10.00"), margin=Decimal("-1")))
    with pytest.raises(LandedCostError, match=INVALID_LANDED_MARGIN):
        calculate_landed_cost(_input(sale=Decimal("10.00"), margin=Decimal("100.01")))
    with pytest.raises(LandedCostError, match=INVALID_LANDED_MARGIN):
        calculate_landed_cost(_input(sale=Decimal("10.00"), margin="abc"))  # type: ignore[arg-type]


def test_zero_margin_max_supplier_equals_sale_minus_non_product() -> None:
    analysis = calculate_landed_cost(_input(sale=Decimal("10.00"), margin=Decimal("0")))
    assert analysis.max_total_unit_cost == Decimal("10.00")
    assert analysis.non_product_cost_per_unit == Decimal("2.40")
    assert analysis.maximum_supplier_unit_price == Decimal("7.60")
    assert analysis.viability is LandedCostViability.ATTRACTIVE


def test_full_margin_makes_supplier_price_non_positive() -> None:
    analysis = calculate_landed_cost(_input(sale=Decimal("10.00"), margin=Decimal("100")))
    assert analysis.max_total_unit_cost == Decimal("0.00")
    assert analysis.maximum_supplier_unit_price == Decimal("-2.40")
    assert analysis.viability is LandedCostViability.ECONOMICALLY_UNATTRACTIVE


def test_missing_supplier_price_is_rejected() -> None:
    with pytest.raises(LandedCostError, match=INVALID_SUPPLIER_PRICE):
        calculate_landed_cost(
            LandedCostInput(
                quantity=40,
                supplier_unit_price=None,  # type: ignore[arg-type]
                packaging=_packaging(),
                rate=ShippingRateProfile(rate_usd_per_cbm=TEST_RATE),
            )
        )


def test_gui_rejects_negative_surcharge_and_invalid_battery_multiplier() -> None:
    with pytest.raises(LandedCostError, match=INVALID_SURCHARGE):
        services.calculate_alibaba_landed_cost(
            quantity="40",
            supplier_unit_price="4.03",
            cartons="2",
            units_per_carton="20",
            carton_length_cm="50",
            carton_width_cm="40",
            carton_height_cm="30",
            gross_weight_kg_per_carton="8",
            rate_usd_per_cbm="800",
            insurance="-1",
        )
    with pytest.raises(LandedCostError, match=INVALID_BATTERY_MULTIPLIER):
        services.calculate_alibaba_landed_cost(
            quantity="40",
            supplier_unit_price="4.03",
            cartons="2",
            units_per_carton="20",
            carton_length_cm="50",
            carton_width_cm="40",
            carton_height_cm="30",
            gross_weight_kg_per_carton="8",
            rate_usd_per_cbm="800",
            has_battery=True,
            battery_multiplier="",
        )


def test_sale_price_validation_guarantees_positive_revenue() -> None:
    """``if revenue > 0`` in calculate_landed_cost is defensive.

    ``expected_sale_price_per_unit`` is rejected unless it is a positive finite
    Decimal, and ``quantity`` is a positive int, so ``revenue = sale * quantity``
    cannot be 0 or negative after those checks. Mutating ``>`` to ``>=`` is
    therefore equivalent. Wrapping TypeError message punctuation is also
    equivalent: tests already match a distinctive substring. Do not change
    production or add message-pinning tests just to force those mutants.
    """

    analysis = calculate_landed_cost(_input(sale=Decimal("0.01"), quantity=1))
    assert analysis.revenue == Decimal("0.01")
    assert analysis.revenue is not None and analysis.revenue > Decimal("0")
    with pytest.raises(LandedCostError, match=INVALID_SALE_PRICE):
        calculate_landed_cost(_input(sale=Decimal("0")))
    with pytest.raises(LandedCostError, match=INVALID_SALE_PRICE):
        calculate_landed_cost(_input(sale=Decimal("-1")))


def test_one_carton_and_one_unit_per_carton_are_valid() -> None:
    packaging = CargoPackagingInput(
        cartons=1,
        units_per_carton=1,
        carton_length_cm=Decimal("50"),
        carton_width_cm=Decimal("40"),
        carton_height_cm=Decimal("30"),
        gross_weight_kg_per_carton=Decimal("8"),
    )
    analysis = calculate_landed_cost(_input(quantity=1, packaging=packaging))
    assert analysis.quantity == 1
    assert analysis.total_cbm == Decimal("0.060000")
    assert analysis.total_weight_kg == Decimal("8.000")


@pytest.mark.parametrize(
    "length, width, height",
    [
        (None, Decimal("40"), Decimal("30")),
        (Decimal("50"), None, Decimal("30")),
        (Decimal("50"), Decimal("40"), None),
    ],
)
def test_any_missing_carton_dimension_is_listed(
    length: Decimal | None,
    width: Decimal | None,
    height: Decimal | None,
) -> None:
    packaging = CargoPackagingInput(
        cartons=2,
        units_per_carton=20,
        carton_length_cm=length,
        carton_width_cm=width,
        carton_height_cm=height,
        gross_weight_kg_per_carton=Decimal("8"),
    )
    missing = missing_logistics_fields(packaging)
    assert MISSING_CARTON_DIMENSIONS in missing
    with pytest.raises(LandedCostError, match=MISSING_LOGISTICS_PREFIX):
        calculate_landed_cost(_input(packaging=packaging))


def test_non_product_cost_adds_shipping_and_import_costs() -> None:
    analysis = calculate_landed_cost(
        _input(
            import_costs=ImportOtherCosts(bank_fees=Decimal("4"), inspection_cost=Decimal("6")),
            sale=Decimal("10.00"),
            margin=Decimal("30"),
        )
    )
    # shipping 96 + import 10 = 106; per unit 2.65. Subtraction would yield 2.15.
    assert analysis.shipping_total == Decimal("96.00")
    assert analysis.other_import_costs == Decimal("10.00")
    assert analysis.non_product_cost_per_unit == Decimal("2.65")
    assert analysis.maximum_supplier_unit_price == Decimal("4.35")


def test_zero_maximum_supplier_is_economically_unattractive() -> None:
    analysis = calculate_landed_cost(_input(sale=Decimal("10.00"), margin=Decimal("76")))
    assert analysis.non_product_cost_per_unit == Decimal("2.40")
    assert analysis.max_total_unit_cost == Decimal("2.40")
    assert analysis.maximum_supplier_unit_price == Decimal("0.00")
    assert analysis.viability is LandedCostViability.ECONOMICALLY_UNATTRACTIVE


def test_analysis_copies_quantity_and_rate_metadata() -> None:
    confirmed = ShippingRateProfile(
        rate_usd_per_cbm=TEST_RATE,
        provider="DTD Cargo Valencia",
        service="Door to Door express",
        destination_country="Venezuela",
        rate_source="cotización DTD",
        rate_date="2026-08-24",
        status=ShippingRateStatus.CONFIRMED_QUOTE,
    )
    analysis = calculate_landed_cost(
        LandedCostInput(
            quantity=40,
            supplier_unit_price=Decimal("4.03"),
            packaging=_packaging(),
            rate=confirmed,
        )
    )
    assert analysis.quantity == 40
    assert analysis.provider == "DTD Cargo Valencia"
    assert analysis.service == "Door to Door express"
    assert analysis.destination_country == "Venezuela"
    assert analysis.rate_source == "cotización DTD"
    assert analysis.rate_date == "2026-08-24"
    defaults = calculate_landed_cost(_input())
    assert defaults.provider == DEFAULT_CARGO_PROVIDER
    assert defaults.service == DEFAULT_CARGO_SERVICE
    assert defaults.destination_country == DEFAULT_CARGO_DESTINATION
    assert defaults.rate_source == "manual"
    assert defaults.rate_date is None


def test_unparseable_surcharge_keeps_surcharge_error() -> None:
    with pytest.raises(LandedCostError, match=INVALID_SURCHARGE):
        ShippingSurcharges(insurance="not-a-surcharge")  # type: ignore[arg-type]
    with pytest.raises(LandedCostError, match=INVALID_IMPORT_COST):
        ImportOtherCosts(bank_fees="abc")  # type: ignore[arg-type]
