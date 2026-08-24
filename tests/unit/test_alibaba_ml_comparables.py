"""Offline Alibaba → Mercado Libre Venezuela comparables flow. No Actor runs."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from bera_price_tracker.application.mercadolibre_benchmark import CURRENCY_MISMATCH_MESSAGE
from bera_price_tracker.gui import services as gui_services
from bera_price_tracker.gui.state import AlibabaResultRow, AlibabaTrackedRow, MercadoLibreResultRow

SRC = Path(__file__).resolve().parents[2] / "src"
PILOT_COMPARABLE_PRICES = ("3.50", "4.95", "4.99", "5.00", "7.59", "7.99", "13.99", "14.99")
LANDED_USD = {"landed_cost_per_unit_raw": "6.43", "currency": "USD"}
LANDED_VES = {"landed_cost_per_unit_raw": "100", "currency": "VES"}


def _ml_row(external_id: str, price: str, *, relevance: int = 80) -> dict[str, object]:
    return {
        "external_id": external_id,
        "title": f"Mouse {price}",
        "price_raw": price,
        "currency": "USD",
        "representative": price,
        "relevance_value": relevance,
        "is_outlier": False,
    }


def _ml_gui_row(external_id: str, price: str, *, relevance: int = 80) -> MercadoLibreResultRow:
    return MercadoLibreResultRow(
        external_id=external_id,
        title=f"Mouse {price}",
        price=f"${price}",
        price_raw=price,
        currency="USD",
        representative=price,
        relevance_value=relevance,
    )


def _pilot_map_rows() -> list[dict[str, object]]:
    return [
        _ml_row(f"MLV{index}", price)
        for index, price in enumerate(PILOT_COMPARABLE_PRICES, start=1)
    ]


def _summary_and_compare(
    rows: list[dict[str, object]],
    landed: dict[str, str] | None,
    *,
    min_relevance: int = 60,
) -> tuple[dict[str, str], dict[str, str]]:
    summary = gui_services.mercadolibre_summary_from_rows(
        rows, min_relevance=min_relevance, total_results=len(rows)
    )
    comparison = gui_services.compare_mercadolibre_with_landed_cost(
        rows, landed, min_relevance=min_relevance
    )
    return summary, comparison


def _show(state: Any) -> bool:
    value = state.ml_show_alibaba_association
    return bool(value() if callable(value) else value)


def _association(state: Any) -> dict[str, str]:
    value = state.ml_alibaba_association
    if callable(value):
        value = value()
    return dict(value)


def test_context_from_alibaba_product_does_not_copy_raw_payload() -> None:
    context = gui_services.build_alibaba_ml_context(
        external_id="P-1",
        title="Wireless Game Mouse Three Mode Lightweight",
        supplier="ShenZhen Co",
        supplier_price="$4.03",
        currency="USD",
        desired_quantity="40",
        landed_row=LANDED_USD,
    )
    assert context["external_id"] == "P-1"
    assert context["title"] == "Wireless Game Mouse Three Mode Lightweight"
    assert context["supplier"] == "ShenZhen Co"
    assert context["supplier_price"] == "$4.03"
    assert context["has_landed"] == "1"
    assert context["landed_currency"] == "USD"
    assert "raw" not in context["title"].lower()
    assert "apify" not in repr(context).lower()


def test_suggest_query_reuses_user_query_and_ignores_title() -> None:
    title = "Wireless Game Mouse Three Mode Lightweight Silent Click"
    assert (
        gui_services.suggest_mercadolibre_query(
            current_query="mouse inalámbrico gamer",
            fallback_query="wireless mouse",
        )
        == "mouse inalámbrico gamer"
    )
    assert (
        gui_services.suggest_mercadolibre_query(current_query="", fallback_query="wireless mouse")
        == "wireless mouse"
    )
    assert gui_services.suggest_mercadolibre_query(current_query="", fallback_query="") == ""
    suggested = gui_services.suggest_mercadolibre_query(
        current_query="", fallback_query="wireless mouse"
    )
    assert suggested != title
    assert title not in suggested


def test_prepare_alibaba_result_creates_context_without_request() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_query = "wireless mouse"
    state.alibaba_results = [
        AlibabaResultRow(
            product_id="P-1",
            title="Wireless Game Mouse Three Mode Lightweight",
            supplier_name="ShenZhen Co",
            price="$4.03",
            representative="4.03",
            currency="USD",
        )
    ]
    opening = state.alibaba_negotiation_opening
    ceiling = state.alibaba_negotiation_ceiling
    state.prepare_ml_comparables_from_alibaba_result("P-1")
    assert state.ml_has_alibaba_context is True
    assert state.ml_alibaba_context["external_id"] == "P-1"
    assert state.marketplace_tab == "mercadolibre"
    assert state.ml_query == "wireless mouse"
    assert state.ml_query != state.ml_alibaba_context["title"]
    assert state.ml_results == []
    assert state.ml_is_loading is False
    assert state.ml_ui_status == "INITIAL"
    assert state.alibaba_negotiation_opening == opening
    assert state.alibaba_negotiation_ceiling == ceiling


def test_prepared_query_is_editable() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_query = "wireless mouse"
    state.alibaba_results = [
        AlibabaResultRow(product_id="P-1", title="Long commercial title", price="$4")
    ]
    state.prepare_ml_comparables_from_alibaba_result("P-1")
    state.set_ml_query("mouse inalámbrico gamer")
    assert state.ml_query == "mouse inalámbrico gamer"
    assert state.ml_is_loading is False


def test_usd_landed_and_mlv_usd_enable_p25_median_p75_scenarios() -> None:
    rows = _pilot_map_rows()
    summary, comparison = _summary_and_compare(rows, LANDED_USD)
    context = gui_services.build_alibaba_ml_context(
        external_id="P-1",
        title="Wireless Game Mouse",
        supplier_price="$4.03",
        currency="USD",
        landed_row=LANDED_USD,
    )
    association = gui_services.build_alibaba_ml_association(context, summary, comparison)
    assert association["visible"] == "1"
    assert association["p25"] == summary["p25"]
    assert association["median"] == summary["mediana"]
    assert association["p75"] == summary["p75"]
    assert association["conservative_price"] == summary["p25"]
    assert association["typical_price"] == summary["mediana"]
    assert association["high_price"] == summary["p75"]
    assert association["has_profitability"] == "1"
    assert association["uses_min_as_scenario"] == "0"
    assert association["uses_max_as_scenario"] == "0"
    assert association["conservative_price"] != association["min"]
    assert association["high_price"] != association["max"]
    assert association["sparse"] == "0"


def test_missing_landed_allows_benchmark_without_profitability() -> None:
    rows = _pilot_map_rows()
    summary, _comparison = _summary_and_compare(rows, None)
    context = gui_services.build_alibaba_ml_context(
        external_id="P-1", title="Wireless Game Mouse", supplier_price="$4.03"
    )
    association = gui_services.build_alibaba_ml_association(context, summary, None)
    assert association["p25"] == summary["p25"]
    assert association["has_profitability"] == "0"
    assert association["missing_landed_message"] == gui_services.MERCADOLIBRE_NEED_LANDED_FOR_PROFIT
    assert association["conservative_profit"] == ""


def test_currency_mismatch_blocks_profitability() -> None:
    rows = _pilot_map_rows()
    summary, comparison = _summary_and_compare(rows, LANDED_VES)
    context = gui_services.build_alibaba_ml_context(
        external_id="P-1",
        title="Wireless Game Mouse",
        currency="USD",
        landed_row=LANDED_VES,
    )
    association = gui_services.build_alibaba_ml_association(context, summary, comparison)
    assert association["has_profitability"] == "0"
    assert association["currency_message"] == CURRENCY_MISMATCH_MESSAGE
    assert association["p25"] == summary["p25"]


def test_sparse_benchmark_warns_without_inventing_confidence() -> None:
    rows = [_ml_row("MLV1", "4.95"), _ml_row("MLV2", "5.00")]
    summary, comparison = _summary_and_compare(rows, LANDED_USD)
    context = gui_services.build_alibaba_ml_context(
        external_id="P-1", title="Mouse", landed_row=LANDED_USD
    )
    association = gui_services.build_alibaba_ml_association(context, summary, comparison)
    assert association["sparse"] == "1"
    assert association["sparse_message"] == gui_services.MERCADOLIBRE_SPARSE_BENCHMARK
    assert association["comparable_count"] == "2"


def test_changing_product_invalidates_previous_association() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_results = [
        AlibabaResultRow(product_id="P-1", title="Mouse A", price="$4"),
        AlibabaResultRow(product_id="P-2", title="Mouse B", price="$5"),
    ]
    state.prepare_ml_comparables_from_alibaba_result("P-1")
    state.ml_ui_status = "SUCCESS"
    state.ml_last_search_query = state.ml_query
    state.ml_association_product_id = "P-1"
    state.ml_results = [_ml_gui_row("MLV1", "4.95")]
    state.ml_has_comparison = True
    state.ml_comparison = {"comparable": "1", "typical_profit": "$1.00"}
    assert _show(state) is True
    state.prepare_ml_comparables_from_alibaba_result("P-2")
    assert state.ml_alibaba_context["external_id"] == "P-2"
    assert state.ml_association_product_id == ""
    assert state.ml_results == []
    assert state.ml_summary == {}
    assert state.ml_ui_status == "INITIAL"
    assert state.ml_last_search_query == ""
    assert state.ml_has_comparison is False
    assert state.ml_comparison == {}
    assert _show(state) is False


def test_landed_recalc_invalidates_stored_comparison_and_uses_new_cost() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_results = [
        AlibabaResultRow(product_id="P-1", title="Mouse A", price="$4", currency="USD")
    ]
    state.alibaba_landed_has_result = True
    state.alibaba_landed_result = dict(LANDED_USD)
    state.alibaba_landed_product_id = "P-1"
    state.prepare_ml_comparables_from_alibaba_result("P-1")
    state.ml_results = [_ml_gui_row("MLV1", "9.49", relevance=80) for _ in range(3)]
    state.ml_ui_status = "SUCCESS"
    state.ml_query = "mouse"
    state.ml_last_search_query = "mouse"
    state.ml_association_product_id = "P-1"
    state.ml_min_relevance = 0
    state.compare_ml_with_landed_cost()
    assert state.ml_has_comparison is True
    state.alibaba_landed_result = {"landed_cost_per_unit_raw": "9.00", "currency": "USD"}
    state._invalidate_ml_comparison()
    assert state.ml_has_comparison is False
    assert state.ml_comparison == {}
    association = _association(state)
    assert association["visible"] == "1"
    assert "9.00" in association["landed"] or association["landed"].endswith("9.00")


def test_landed_from_product_a_is_not_used_for_product_b() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_results = [
        AlibabaResultRow(product_id="A", title="Mouse A", price="$4"),
        AlibabaResultRow(product_id="B", title="Mouse B", price="$5"),
    ]
    state.alibaba_landed_has_result = True
    state.alibaba_landed_result = dict(LANDED_USD)
    state.alibaba_landed_product_id = "A"
    state.prepare_ml_comparables_from_alibaba_result("B")
    state.ml_results = [
        _ml_gui_row(f"MLV{index}", price)
        for index, price in enumerate(PILOT_COMPARABLE_PRICES, start=1)
    ]
    state.ml_ui_status = "SUCCESS"
    state.ml_query = "mouse"
    state.ml_last_search_query = "mouse"
    state.ml_association_product_id = "B"

    association = _association(state)
    state.compare_ml_with_landed_cost()

    assert state.alibaba_landed_has_result is True
    assert state.alibaba_landed_product_id == "A"
    assert association["p25"] != ""
    assert association["has_profitability"] == "0"
    assert association["landed"] == ""
    assert association["conservative_profit"] == ""
    assert state.ml_comparison["comparable"] == "0"
    assert state.ml_comparison["conservative_profit"] == ""
    assert (
        association["missing_landed_message"]
        == "Calcula primero el costo puesto en Venezuela para este producto."
    )


def test_landed_for_matching_product_enables_profitability() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_results = [
        AlibabaResultRow(product_id="A", title="Mouse A", price="$4", currency="USD")
    ]
    state.alibaba_landed_has_result = True
    state.alibaba_landed_result = dict(LANDED_USD)
    state.alibaba_landed_product_id = "A"
    state.prepare_ml_comparables_from_alibaba_result("A")
    state.ml_results = [
        _ml_gui_row(f"MLV{index}", price)
        for index, price in enumerate(PILOT_COMPARABLE_PRICES, start=1)
    ]
    state.ml_ui_status = "SUCCESS"
    state.ml_query = "mouse"
    state.ml_last_search_query = "mouse"
    state.ml_association_product_id = "A"

    association = _association(state)

    assert association["has_profitability"] == "1"
    assert association["landed"] == "6.43 USD"
    assert association["conservative_profit"] != ""


def test_missing_product_identity_fails_closed_for_landed_provenance() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_landed_has_result = True
    state.alibaba_landed_result = dict(LANDED_USD)
    state.alibaba_landed_product_id = ""
    assert state._landed_for_ml_product("") is None
    assert state._landed_for_ml_product("B") is None
    state._prepare_ml_comparables(
        external_id="",
        title="Unidentified mouse",
        supplier="Supplier",
        supplier_price="$4",
        currency="USD",
    )
    assert state.ml_has_alibaba_context is False


def test_use_negotiation_values_records_landed_draft_product_id() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_negotiation_plan_payload = {
        "product_id": "1601763520797",
        "desired_quantity": "40",
        "opening_offer": "$3.80",
    }
    state.use_negotiation_values_for_landed_cost()
    assert state.alibaba_landed_draft_product_id == "1601763520797"
    assert state.alibaba_landed_quantity == "40"
    assert state.alibaba_landed_supplier_price == "$3.80"


def _fill_valid_landed_inputs(state: Any) -> None:
    state.alibaba_landed_quantity = "40"
    state.alibaba_landed_supplier_price = "4.03"
    state.alibaba_landed_cartons = "2"
    state.alibaba_landed_units_per_carton = "20"
    state.alibaba_landed_length = "50"
    state.alibaba_landed_width = "40"
    state.alibaba_landed_height = "30"
    state.alibaba_landed_weight = "8"
    state.alibaba_landed_rate = "800"


def test_successful_landed_calculation_commits_product_provenance() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_landed_draft_product_id = "A"
    _fill_valid_landed_inputs(state)
    state.calculate_alibaba_landed_cost()
    assert state.alibaba_landed_has_result is True
    assert state.alibaba_landed_product_id == "A"


def test_failed_landed_calculation_clears_product_provenance() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_landed_product_id = "A"
    state.alibaba_landed_draft_product_id = "B"
    state.alibaba_landed_quantity = "40"
    state.alibaba_landed_supplier_price = "4.03"
    state.calculate_alibaba_landed_cost()
    assert state.alibaba_landed_has_result is False
    assert state.alibaba_landed_result == {}
    assert state.alibaba_landed_product_id == ""


def test_query_change_hides_association_without_new_request() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_results = [AlibabaResultRow(product_id="P-1", title="Mouse A", price="$4")]
    state.prepare_ml_comparables_from_alibaba_result("P-1")
    state.ml_results = [_ml_gui_row("MLV1", "4.95")]
    state.ml_ui_status = "SUCCESS"
    state.ml_query = "mouse inalámbrico"
    state.ml_last_search_query = "mouse inalámbrico"
    state.ml_association_product_id = "P-1"
    rows_before = list(state.ml_results)
    state.set_ml_query("otra consulta")
    assert state.ml_query == "otra consulta"
    assert state.ml_results == rows_before
    assert state.ml_is_loading is False
    assert _show(state) is False
    assert state.ml_has_comparison is False


def test_tracked_product_can_create_context() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_query = "mouse"
    state.alibaba_tracked_rows = [
        AlibabaTrackedRow(
            product_id="T-1",
            title="Tracked mouse",
            supplier_name="Cactus",
            current_price="$5.00",
            last_price="$5.00",
            currency="USD",
        )
    ]
    state.prepare_ml_comparables_from_alibaba_tracked("T-1")
    assert state.ml_has_alibaba_context is True
    assert state.ml_alibaba_context["external_id"] == "T-1"
    assert state.ml_alibaba_context["supplier_price"] == "$5.00"
    assert state.ml_alibaba_context["currency"] == "USD"
    assert state.marketplace_tab == "mercadolibre"


def test_tracked_cny_currency_survives_ml_context_without_usd_fallback() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_query = "mouse"
    state.alibaba_tracked_rows = [
        AlibabaTrackedRow(
            product_id="T-CNY",
            title="Tracked CNY mouse",
            supplier_name="Cactus",
            current_price="CNY 5.00",
            last_price="CNY 5.00",
            currency="CNY",
        )
    ]
    state.prepare_ml_comparables_from_alibaba_tracked("T-CNY")
    assert state.ml_alibaba_context["external_id"] == "T-CNY"
    assert state.ml_alibaba_context["currency"] == "CNY"
    assert state.ml_alibaba_context["currency"] != "USD"


def test_tracked_missing_iso_keeps_benchmark_context_but_blocks_landed_profitability() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_query = "mouse"
    state.alibaba_landed_has_result = True
    state.alibaba_landed_product_id = "T-UNKNOWN"
    state.alibaba_landed_result = LANDED_USD
    state.alibaba_tracked_rows = [
        AlibabaTrackedRow(
            product_id="T-UNKNOWN",
            title="Tracked mouse",
            current_price="5.00",
            last_price="5.00",
            currency="",
        )
    ]
    state.prepare_ml_comparables_from_alibaba_tracked("T-UNKNOWN")
    assert state.ml_has_alibaba_context is True
    assert state.ml_alibaba_context["currency"] == ""
    assert state.ml_alibaba_context["has_landed"] == "0"


def test_association_prices_are_decimal_formatted_not_float() -> None:
    rows = _pilot_map_rows()
    summary, comparison = _summary_and_compare(rows, LANDED_USD)
    context = gui_services.build_alibaba_ml_context(
        external_id="P-1", title="Mouse", currency="USD", landed_row=LANDED_USD
    )
    association = gui_services.build_alibaba_ml_association(context, summary, comparison)
    for key in ("conservative_profit", "typical_profit", "high_profit"):
        raw = association[key].replace("$", "").replace("/u", "").strip().split()[0]
        value = Decimal(raw)
        assert isinstance(value, Decimal)
        assert not isinstance(value, float)


def test_new_modules_have_no_minimax_or_mlv_tracking() -> None:
    text = (SRC / "bera_price_tracker" / "gui" / "services.py").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "minimax" not in lowered
    assert "mlv_snapshot" not in lowered
    assert "seguir precio mercado libre" not in lowered
    assert "xtracto" not in lowered


def _stale_success_payload() -> tuple[list[MercadoLibreResultRow], dict[str, str]]:
    rows = [_ml_gui_row("MLV-STALE", "4.95")]
    summary = {"comparable_count": "1", "p25": "4.95 USD"}
    return rows, summary


def _begin_in_flight_ml_search(
    state: Any,
    *,
    query: str,
    product_id: str = "",
) -> tuple[str, str]:
    state.ml_query = query
    state.ml_is_loading = True
    state.ml_ui_status = "LOADING"
    state.ml_error = ""
    if product_id:
        state.ml_has_alibaba_context = True
        context = dict(state.ml_alibaba_context)
        context["external_id"] = product_id
        state.ml_alibaba_context = context
    return product_id, query


def test_late_success_is_discarded_after_query_change() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    search_product_id, search_query = _begin_in_flight_ml_search(state, query="mouse")
    previous_results = list(state.ml_results)
    previous_summary = dict(state.ml_summary)
    state.set_ml_query("mouse gamer")
    rows, summary = _stale_success_payload()
    state._finalize_mercadolibre_search(
        search_product_id=search_product_id,
        query=search_query,
        rows=rows,
        summary=summary,
        ui_status="SUCCESS",
    )
    assert state.ml_query == "mouse gamer"
    assert state.ml_results == previous_results
    assert state.ml_summary == previous_summary
    assert state.ml_last_search_query == ""
    assert state.ml_association_product_id == ""
    assert state.ml_is_loading is False
    assert state.ml_ui_status == "INITIAL"
    assert state.ml_ui_status != "LOADING"
    assert state.ml_error == ""


def test_late_error_is_discarded_after_query_change() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    search_product_id, search_query = _begin_in_flight_ml_search(state, query="mouse")
    state.set_ml_query("mouse gamer")
    state._finalize_mercadolibre_search(
        search_product_id=search_product_id,
        query=search_query,
        error_message="Mercado Libre no está disponible.",
    )
    assert state.ml_error == ""
    assert state.ml_results == []
    assert state.ml_summary == {}
    assert state.ml_is_loading is False
    assert state.ml_ui_status == "INITIAL"
    assert state.ml_ui_status != "LOADING"


def test_late_success_after_product_change_keeps_initial_and_cleared_results() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_results = [
        AlibabaResultRow(product_id="P-1", title="Mouse A", price="$4"),
        AlibabaResultRow(product_id="P-2", title="Mouse B", price="$5"),
    ]
    state.prepare_ml_comparables_from_alibaba_result("P-1")
    search_product_id, search_query = _begin_in_flight_ml_search(
        state, query=state.ml_query, product_id="P-1"
    )
    state.ml_results = [_ml_gui_row("MLV-OLD", "3.50")]
    state.prepare_ml_comparables_from_alibaba_result("P-2")
    assert state.ml_ui_status == "INITIAL"
    assert state.ml_results == []
    rows, summary = _stale_success_payload()
    state._finalize_mercadolibre_search(
        search_product_id=search_product_id,
        query=search_query,
        rows=rows,
        summary=summary,
        ui_status="SUCCESS",
    )
    assert state.ml_alibaba_context["external_id"] == "P-2"
    assert state.ml_results == []
    assert state.ml_summary == {}
    assert state.ml_last_search_query == ""
    assert state.ml_association_product_id == ""
    assert state.ml_is_loading is False
    assert state.ml_ui_status == "INITIAL"
    assert _show(state) is False


def test_second_ml_search_cannot_start_while_loading() -> None:
    assert gui_services.can_start_mercadolibre_search(True) is False
    assert gui_services.can_start_mercadolibre_search(False) is True


def test_matching_ml_search_still_applies_success() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    search_product_id, search_query = _begin_in_flight_ml_search(
        state, query="mouse", product_id="P-1"
    )
    rows, summary = _stale_success_payload()
    state._finalize_mercadolibre_search(
        search_product_id=search_product_id,
        query=search_query,
        rows=rows,
        summary=summary,
        ui_status="SUCCESS",
    )
    assert state.ml_is_loading is False
    assert state.ml_ui_status == "SUCCESS"
    assert state.ml_results == rows
    assert state.ml_summary == summary
    assert state.ml_last_search_query == "mouse"
    assert state.ml_association_product_id == "P-1"


def test_prepare_does_not_call_minimax_or_change_negotiation_plan() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_negotiation_has_plan = True
    state.alibaba_negotiation_opening = "$3.80"
    state.alibaba_negotiation_target = "$3.50"
    state.alibaba_negotiation_ceiling = "$4.10"
    state.alibaba_negotiation_effective_ceiling = "$4.10"
    state.alibaba_results = [AlibabaResultRow(product_id="P-1", title="Mouse", price="$4")]
    state.prepare_ml_comparables_from_alibaba_result("P-1")
    assert state.alibaba_negotiation_has_plan is True
    assert state.alibaba_negotiation_opening == "$3.80"
    assert state.alibaba_negotiation_target == "$3.50"
    assert state.alibaba_negotiation_ceiling == "$4.10"
    assert state.alibaba_negotiation_effective_ceiling == "$4.10"


def test_gui_does_not_auto_search_mlv_when_selecting_alibaba_product() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_query = "impact wrench"
    state.alibaba_results = [
        AlibabaResultRow(
            product_id="P-1",
            title="Factory Direct 21V Brushless Cordless Impact Wrench 800Nm",
            price="$12",
        )
    ]
    state.prepare_ml_comparables_from_alibaba_result("P-1")
    assert state.ml_is_loading is False
    assert state.ml_results == []
    assert state.ml_ui_status == "INITIAL"
    assert state.ml_has_alibaba_context is True


def test_generated_search_query_remains_editable_in_gui() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_results = [
        AlibabaResultRow(product_id="P-1", title="21V Impact Wrench 800Nm", price="$12")
    ]
    state.prepare_ml_comparables_from_alibaba_result("P-1")
    state._finalize_product_translation(
        product_id="P-1",
        title="21V Impact Wrench 800Nm",
        generation=state.ml_translation_generation,
        translated_title="Llave de impacto 21V 800Nm",
        search_query="llave de impacto 21V 800Nm",
    )
    assert state.ml_query == "llave de impacto 21V 800Nm"
    assert state.ml_translated_title == "Llave de impacto 21V 800Nm"
    state.set_ml_query("llave de impacto inalámbrica 21V 800Nm")
    assert state.ml_query == "llave de impacto inalámbrica 21V 800Nm"
    assert state.ml_query_origin == gui_services.ML_QUERY_ORIGIN_USER
    assert state.ml_is_loading is False


def test_product_switch_invalidates_previous_translation() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_results = [
        AlibabaResultRow(product_id="P-1", title="Pump A 220V", price="$4"),
        AlibabaResultRow(product_id="P-2", title="Pump B 110V", price="$5"),
    ]
    state.prepare_ml_comparables_from_alibaba_result("P-1")
    state._finalize_product_translation(
        product_id="P-1",
        title="Pump A 220V",
        generation=state.ml_translation_generation,
        translated_title="Bomba A 220V",
        search_query="bomba A 220V",
    )
    assert state.ml_translated_title == "Bomba A 220V"
    state.prepare_ml_comparables_from_alibaba_result("P-2")
    assert state.ml_alibaba_context["external_id"] == "P-2"
    assert state.ml_translated_title == ""
    assert state.ml_translation_warning == ""
    assert state.ml_query == ""
    assert state.ml_query_origin == ""


def test_product_a_generated_query_is_cleared_when_switching_to_b() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_results = [
        AlibabaResultRow(product_id="A", title="Title A 220V", price="$4"),
        AlibabaResultRow(product_id="B", title="Title B 110V", price="$5"),
    ]
    state.prepare_ml_comparables_from_alibaba_result("A")
    state._finalize_product_translation(
        product_id="A",
        title="Title A 220V",
        generation=state.ml_translation_generation,
        translated_title="Título A 220V",
        search_query="titulo A 220V",
    )
    assert state.ml_query == "titulo A 220V"
    assert state.ml_query_origin == gui_services.ML_QUERY_ORIGIN_GENERATED
    state.prepare_ml_comparables_from_alibaba_result("B")
    assert state.ml_alibaba_context["external_id"] == "B"
    assert state.ml_query == ""
    assert state.ml_query_origin == ""
    assert state.ml_translated_title == ""
    assert state.ml_translation_warning == ""


def test_product_a_manually_edited_query_is_cleared_when_switching_to_b() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_results = [
        AlibabaResultRow(product_id="A", title="Title A 220V", price="$4"),
        AlibabaResultRow(product_id="B", title="Title B 110V", price="$5"),
    ]
    state.prepare_ml_comparables_from_alibaba_result("A")
    state.set_ml_query("consulta manual de A")
    assert state.ml_query == "consulta manual de A"
    assert state.ml_query_origin == gui_services.ML_QUERY_ORIGIN_USER
    state.prepare_ml_comparables_from_alibaba_result("B")
    assert state.ml_alibaba_context["external_id"] == "B"
    assert state.ml_query == ""
    assert state.ml_query_origin == ""
    assert state.ml_query != "consulta manual de A"


def test_late_translation_success_for_a_cannot_overwrite_b() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_results = [
        AlibabaResultRow(product_id="A", title="Title A 220V", price="$4"),
        AlibabaResultRow(product_id="B", title="Title B 110V", price="$5"),
    ]
    state.prepare_ml_comparables_from_alibaba_result("A")
    generation_a = state.ml_translation_generation
    title_a = state.ml_alibaba_context["title"]
    state.prepare_ml_comparables_from_alibaba_result("B")
    state._finalize_product_translation(
        product_id="A",
        title=title_a,
        generation=generation_a,
        translated_title="Traducción A",
        search_query="consulta A",
    )
    assert state.ml_alibaba_context["external_id"] == "B"
    assert state.ml_translated_title != "Traducción A"
    assert state.ml_translated_title == ""
    assert state.ml_query == ""
    assert state.ml_query != "consulta A"
    assert state.ml_query_origin == ""


def test_late_translation_from_a_cannot_repopulate_query_on_b() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_results = [
        AlibabaResultRow(product_id="A", title="Title A 220V", price="$4"),
        AlibabaResultRow(product_id="B", title="Title B 110V", price="$5"),
    ]
    state.prepare_ml_comparables_from_alibaba_result("A")
    generation_a = state.ml_translation_generation
    title_a = state.ml_alibaba_context["title"]
    state.set_ml_query("consulta manual de A")
    state.prepare_ml_comparables_from_alibaba_result("B")
    assert state.ml_query == ""
    state._finalize_product_translation(
        product_id="A",
        title=title_a,
        generation=generation_a,
        translated_title="Traducción tardía A",
        search_query="consulta tardía A",
    )
    assert state.ml_alibaba_context["external_id"] == "B"
    assert state.ml_translated_title == ""
    assert state.ml_query == ""
    assert state.ml_query_origin == ""
    assert state.ml_query != "consulta tardía A"
    assert state.ml_query != "consulta manual de A"


def test_late_translation_error_for_a_cannot_overwrite_b() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_results = [
        AlibabaResultRow(product_id="A", title="Title A", price="$4"),
        AlibabaResultRow(product_id="B", title="Title B", price="$5"),
    ]
    state.prepare_ml_comparables_from_alibaba_result("A")
    generation_a = state.ml_translation_generation
    title_a = state.ml_alibaba_context["title"]
    state.prepare_ml_comparables_from_alibaba_result("B")
    previous_error = state.ml_translation_error
    state._finalize_product_translation(
        product_id="A",
        title=title_a,
        generation=generation_a,
        error_message="stale translation error",
    )
    assert state.ml_alibaba_context["external_id"] == "B"
    assert state.ml_translation_error != "stale translation error"
    assert state.ml_translation_error == previous_error


def test_late_error_from_a_cannot_alter_b_status() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_results = [
        AlibabaResultRow(product_id="A", title="Title A", price="$4"),
        AlibabaResultRow(product_id="B", title="Title B", price="$5"),
    ]
    state.prepare_ml_comparables_from_alibaba_result("A")
    generation_a = state.ml_translation_generation
    title_a = state.ml_alibaba_context["title"]
    state.ml_ui_status = "LOADING"
    state.ml_is_loading = True
    state.ml_error = "error de búsqueda A"
    state.ml_translation_ui_status = "LOADING"
    state.prepare_ml_comparables_from_alibaba_result("B")
    b_ui_status = state.ml_ui_status
    b_translation_status = state.ml_translation_ui_status
    b_translation_error = state.ml_translation_error
    b_ml_error = state.ml_error
    assert b_ui_status == "INITIAL"
    assert state.ml_is_loading is False
    assert b_ml_error == ""
    state._finalize_product_translation(
        product_id="A",
        title=title_a,
        generation=generation_a,
        error_message="error tardío de A",
        configured=True,
    )
    assert state.ml_alibaba_context["external_id"] == "B"
    assert state.ml_translation_error == b_translation_error
    assert state.ml_translation_error != "error tardío de A"
    assert state.ml_translation_ui_status == b_translation_status
    assert state.ml_translation_ui_status != "ERROR"
    assert state.ml_ui_status == b_ui_status
    assert state.ml_ui_status == "INITIAL"
    assert state.ml_error == ""
    assert state.ml_is_loading is False


def test_old_mlv_results_benchmark_and_provenance_from_a_remain_cleared_on_b() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_results = [
        AlibabaResultRow(product_id="A", title="Title A", price="$4"),
        AlibabaResultRow(product_id="B", title="Title B", price="$5"),
    ]
    state.prepare_ml_comparables_from_alibaba_result("A")
    search_product_id, search_query = _begin_in_flight_ml_search(
        state, query="consulta A", product_id="A"
    )
    state.ml_results = [_ml_gui_row("MLV-A", "4.95")]
    state.ml_summary = {"comparable_count": "1", "p25": "4.95 USD", "mediana": "4.95 USD"}
    state.ml_ui_status = "SUCCESS"
    state.ml_last_search_query = "consulta A"
    state.ml_association_product_id = "A"
    state.ml_has_comparison = True
    state.ml_comparison = {"comparable": "1", "typical_profit": "$1.00"}
    assert _show(state) is True
    state.prepare_ml_comparables_from_alibaba_result("B")
    assert state.ml_alibaba_context["external_id"] == "B"
    assert state.ml_results == []
    assert state.ml_summary == {}
    assert state.ml_has_comparison is False
    assert state.ml_comparison == {}
    assert state.ml_last_search_query == ""
    assert state.ml_association_product_id == ""
    assert state.ml_ui_status == "INITIAL"
    assert state.ml_is_loading is False
    assert state.ml_error == ""
    assert state.ml_query == ""
    assert _show(state) is False
    rows, summary = _stale_success_payload()
    state._finalize_mercadolibre_search(
        search_product_id=search_product_id,
        query=search_query,
        rows=rows,
        summary=summary,
        ui_status="SUCCESS",
    )
    assert state.ml_alibaba_context["external_id"] == "B"
    assert state.ml_results == []
    assert state.ml_summary == {}
    assert state.ml_has_comparison is False
    assert state.ml_comparison == {}
    assert state.ml_last_search_query == ""
    assert state.ml_association_product_id == ""
    assert state.ml_ui_status == "INITIAL"
    assert state.ml_query == ""
    assert _show(state) is False


def test_missing_azure_config_still_allows_manual_mlv_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bera_price_tracker.gui.state import TrackerState

    monkeypatch.setattr(gui_services, "azure_translator_is_configured", lambda: False)
    state = TrackerState()
    state.alibaba_results = [AlibabaResultRow(product_id="P-1", title="Pump 220V", price="$4")]
    state.prepare_ml_comparables_from_alibaba_result("P-1")
    assert state.ml_translation_ui_status == "NOT_CONFIGURED"
    assert state.ml_translation_error == gui_services.TRANSLATION_NOT_CONFIGURED_MESSAGE
    assert state.ml_is_loading is False
    state.set_ml_query("bomba centrífuga 220V")
    assert state.ml_query == "bomba centrífuga 220V"
    assert gui_services.can_start_mercadolibre_search(state.ml_is_loading) is True


def test_gui_translation_cache_avoids_duplicate_calls() -> None:
    from tests.unit.test_product_translation import FakeProductTranslator

    gui_services.reset_product_translation_cache()
    translator = FakeProductTranslator("Llave de impacto 21V 800Nm")
    first = gui_services.translate_product_title(
        "Impact Wrench 21V 800Nm",
        translator=translator,
    )
    second = gui_services.translate_product_title(
        "Impact Wrench 21V 800Nm",
        translator=translator,
    )
    assert first["translated_text"] == "Llave de impacto 21V 800Nm"
    assert second["search_query"]
    assert len(translator.calls) == 1
    gui_services.reset_product_translation_cache()


def test_translation_does_not_change_alibaba_money_fields() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.alibaba_results = [
        AlibabaResultRow(
            product_id="P-1",
            title="Pump 220V",
            price="$4.03",
            currency="USD",
            representative="4.03",
        )
    ]
    state.prepare_ml_comparables_from_alibaba_result("P-1")
    supplier_price = state.ml_alibaba_context["supplier_price"]
    currency = state.ml_alibaba_context["currency"]
    state._finalize_product_translation(
        product_id="P-1",
        title="Pump 220V",
        generation=state.ml_translation_generation,
        translated_title="Bomba 220V",
        search_query="bomba 220V",
    )
    assert state.ml_alibaba_context["supplier_price"] == supplier_price
    assert state.ml_alibaba_context["currency"] == currency
    assert state.ml_alibaba_context["supplier_price"] == "$4.03"
