"""Workspace heading and comparison-row provenance. Offline, no provider calls."""

from __future__ import annotations

from bera_price_tracker.gui import comparison
from bera_price_tracker.gui.state import (
    UI_INITIAL,
    UI_SUCCESS,
    AlibabaResultRow,
    FacebookProductResultRow,
    MercadoLibreResultRow,
    TrackerState,
)

ALIBABA_QUERY = "mouse inalámbrico"
FACEBOOK_QUERY = "mouse"
ML_QUERY = "audífonos bluetooth"
PRODUCT_A = "ali-A"
PRODUCT_B = "ali-B"


def _alibaba(product_id: str, title: str) -> AlibabaResultRow:
    return AlibabaResultRow(
        product_id=product_id,
        title=title,
        price="$4.00",
        supplier_name="Supplier",
        relevance_value=90,
    )


def _facebook(title: str, relevance_value: int = 80) -> FacebookProductResultRow:
    return FacebookProductResultRow(
        title=title,
        price="10.00 VEF",
        usd_price="USD: $10.00",
        relevance_value=relevance_value,
    )


def _ml(title: str, relevance_value: int = 70) -> MercadoLibreResultRow:
    return MercadoLibreResultRow(title=title, price="$9.50", relevance_value=relevance_value)


def test_facebook_workspace_idle_heading_ignores_alibaba_success() -> None:
    heading = comparison.page_heading(
        alibaba_query=ALIBABA_QUERY,
        alibaba_status=UI_SUCCESS,
        workspace_view="products",
    )
    assert heading == comparison.IDLE_HEADINGS["products"]
    assert ALIBABA_QUERY not in heading


def test_products_workspace_heading_uses_facebook_query_only() -> None:
    heading = comparison.page_heading(
        alibaba_query=ALIBABA_QUERY,
        alibaba_status=UI_SUCCESS,
        facebook_query=FACEBOOK_QUERY,
        facebook_status=UI_SUCCESS,
        workspace_view="products",
    )
    assert heading == f"Resultados para: {FACEBOOK_QUERY}"
    assert ALIBABA_QUERY not in heading


def test_comparisons_workspace_heading_uses_ml_not_alibaba() -> None:
    heading = comparison.page_heading(
        alibaba_query=ALIBABA_QUERY,
        alibaba_status=UI_SUCCESS,
        ml_query=ML_QUERY,
        ml_status=UI_SUCCESS,
        workspace_view="comparisons",
    )
    assert heading == f"Resultados para: {ML_QUERY}"
    assert ALIBABA_QUERY not in heading


def test_tools_workspace_heading_uses_h0019_only() -> None:
    heading = comparison.page_heading(
        alibaba_query=ALIBABA_QUERY,
        alibaba_status=UI_SUCCESS,
        facebook_query=FACEBOOK_QUERY,
        facebook_status=UI_SUCCESS,
        ml_query=ML_QUERY,
        ml_status=UI_SUCCESS,
        h0019_query="pastillas sbr",
        h0019_status=UI_SUCCESS,
        workspace_view="tools",
    )
    assert heading == "Resultados para: pastillas sbr"
    assert ALIBABA_QUERY not in heading
    assert FACEBOOK_QUERY not in heading
    assert ML_QUERY not in heading


def test_unrelated_standalone_facebook_and_ml_are_not_one_row() -> None:
    rows = comparison.build_comparison_rows(
        facebook_rows=[_facebook("mouse")],
        ml_rows=[_ml("headphones")],
        facebook_status=UI_SUCCESS,
        ml_status=UI_SUCCESS,
    )
    assert len(rows) == 2
    facebook_row = next(row for row in rows if row["facebook_has_listing"])
    ml_row = next(row for row in rows if row["ml_has_listing"])
    assert facebook_row is not ml_row
    assert facebook_row["ml_has_listing"] is False
    assert facebook_row["alibaba_has_listing"] is False
    assert ml_row["facebook_has_listing"] is False
    assert ml_row["alibaba_has_listing"] is False
    combined = [row for row in rows if row["facebook_has_listing"] and row["ml_has_listing"]]
    assert combined == []


def test_same_alibaba_association_may_share_one_row() -> None:
    rows = comparison.build_comparison_rows(
        alibaba_rows=[_alibaba(PRODUCT_A, "Mouse A")],
        facebook_rows=[_facebook("Mouse FB A")],
        ml_rows=[_ml("Mouse ML A")],
        alibaba_status=UI_SUCCESS,
        facebook_status=UI_SUCCESS,
        ml_status=UI_SUCCESS,
        facebook_association_id=PRODUCT_A,
        ml_association_id=PRODUCT_A,
        alibaba_context={"external_id": PRODUCT_A, "title": "Mouse A"},
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["product_id"] == PRODUCT_A
    assert row["alibaba_has_listing"] is True
    assert row["facebook_has_listing"] is True
    assert row["ml_has_listing"] is True
    assert row["facebook_title"] == "Mouse FB A"
    assert row["ml_title"] == "Mouse ML A"


def test_different_alibaba_associations_never_share_a_row() -> None:
    rows = comparison.build_comparison_rows(
        alibaba_rows=[
            _alibaba(PRODUCT_A, "Mouse A"),
            _alibaba(PRODUCT_B, "Headphones B"),
        ],
        facebook_rows=[_facebook("Mouse FB A")],
        ml_rows=[_ml("Headphones ML B")],
        alibaba_status=UI_SUCCESS,
        facebook_status=UI_SUCCESS,
        ml_status=UI_SUCCESS,
        facebook_association_id=PRODUCT_A,
        ml_association_id=PRODUCT_B,
        alibaba_context={"external_id": PRODUCT_B, "title": "Headphones B"},
    )
    assert len(rows) == 2
    by_id = {row["product_id"]: row for row in rows}
    assert by_id[PRODUCT_A]["facebook_has_listing"] is True
    assert by_id[PRODUCT_A]["ml_has_listing"] is False
    assert by_id[PRODUCT_B]["ml_has_listing"] is True
    assert by_id[PRODUCT_B]["facebook_has_listing"] is False
    assert by_id[PRODUCT_B]["facebook_title"] == ""
    combined = [row for row in rows if row["facebook_has_listing"] and row["ml_has_listing"]]
    assert combined == []


def test_standalone_facebook_does_not_invent_alibaba_or_ml() -> None:
    rows = comparison.build_comparison_rows(
        facebook_rows=[_facebook("Solo Facebook")],
        facebook_status=UI_SUCCESS,
    )
    assert len(rows) == 1
    assert rows[0]["facebook_has_listing"] is True
    assert rows[0]["alibaba_has_listing"] is False
    assert rows[0]["ml_has_listing"] is False
    assert rows[0]["alibaba_title"] == ""
    assert rows[0]["ml_title"] == ""
    assert rows[0]["alibaba_price"] == ""
    assert rows[0]["ml_price"] == ""


def test_standalone_ml_does_not_invent_alibaba_or_facebook() -> None:
    rows = comparison.build_comparison_rows(
        ml_rows=[_ml("Solo ML")],
        ml_status=UI_SUCCESS,
    )
    assert len(rows) == 1
    assert rows[0]["ml_has_listing"] is True
    assert rows[0]["alibaba_has_listing"] is False
    assert rows[0]["facebook_has_listing"] is False
    assert rows[0]["alibaba_title"] == ""
    assert rows[0]["facebook_title"] == ""
    assert rows[0]["alibaba_price"] == ""
    assert rows[0]["facebook_price"] == ""


def test_stale_association_a_never_leaks_into_product_b_row() -> None:
    facebook_a = _facebook("Stale mouse from A")
    ml_b = _ml("Current headphones B")
    rows = comparison.build_comparison_rows(
        alibaba_rows=[_alibaba(PRODUCT_B, "Headphones B")],
        facebook_rows=[facebook_a],
        ml_rows=[ml_b],
        alibaba_status=UI_SUCCESS,
        facebook_status=UI_SUCCESS,
        ml_status=UI_SUCCESS,
        facebook_association_id=PRODUCT_A,
        ml_association_id=PRODUCT_B,
        alibaba_context={"external_id": PRODUCT_B, "title": "Headphones B"},
    )
    b_rows = [row for row in rows if row["product_id"] == PRODUCT_B]
    assert len(b_rows) == 1
    assert b_rows[0]["ml_has_listing"] is True
    assert b_rows[0]["facebook_has_listing"] is False
    assert b_rows[0]["facebook_title"] == ""
    assert "Stale mouse from A" not in str(b_rows[0])
    leftover_facebook = [row for row in rows if row["facebook_title"] == "Stale mouse from A"]
    assert leftover_facebook
    assert leftover_facebook[0]["product_id"] != PRODUCT_B
    assert leftover_facebook[0]["ml_has_listing"] is False


def test_shared_association_requires_all_three_ids() -> None:
    assert comparison.shared_alibaba_association("", PRODUCT_A, PRODUCT_A) == ""
    assert comparison.shared_alibaba_association(PRODUCT_A, "", PRODUCT_A) == ""
    assert comparison.shared_alibaba_association(PRODUCT_A, PRODUCT_A, "") == ""
    assert comparison.shared_alibaba_association(PRODUCT_A, PRODUCT_B, PRODUCT_A) == ""
    assert comparison.shared_alibaba_association(PRODUCT_A, PRODUCT_A, PRODUCT_A) == PRODUCT_A


def test_titles_alone_never_create_a_combined_row() -> None:
    rows = comparison.build_comparison_rows(
        facebook_rows=[_facebook("mouse inalámbrico")],
        ml_rows=[_ml("mouse inalámbrico")],
        facebook_status=UI_SUCCESS,
        ml_status=UI_SUCCESS,
    )
    combined = [row for row in rows if row["facebook_has_listing"] and row["ml_has_listing"]]
    assert combined == []


def test_fallback_combined_row_requires_shared_context_id() -> None:
    allowed = comparison.build_comparison_rows(
        facebook_rows=[_facebook("Mouse FB A")],
        ml_rows=[_ml("Mouse ML A")],
        facebook_status=UI_SUCCESS,
        ml_status=UI_SUCCESS,
        facebook_association_id=PRODUCT_A,
        ml_association_id=PRODUCT_A,
        alibaba_context={"external_id": PRODUCT_A, "title": "Mouse A"},
    )
    assert len(allowed) == 1
    assert allowed[0]["facebook_has_listing"] is True
    assert allowed[0]["ml_has_listing"] is True
    assert allowed[0]["product_id"] == PRODUCT_A

    blocked = comparison.build_comparison_rows(
        facebook_rows=[_facebook("Mouse FB A")],
        ml_rows=[_ml("Headphones ML B")],
        facebook_status=UI_SUCCESS,
        ml_status=UI_SUCCESS,
        facebook_association_id=PRODUCT_A,
        ml_association_id=PRODUCT_B,
        alibaba_context={"external_id": PRODUCT_A, "title": "Mouse A"},
    )
    assert len(blocked) == 2
    assert all(not (row["facebook_has_listing"] and row["ml_has_listing"]) for row in blocked)


def test_tracker_state_heading_follows_workspace_not_stale_alibaba() -> None:
    products_idle = TrackerState()
    products_idle.alibaba_query = ALIBABA_QUERY
    products_idle.alibaba_ui_status = UI_SUCCESS
    products_idle.facebook_product_query = ""
    products_idle.facebook_product_ui_status = UI_INITIAL
    products_idle.show_products()
    assert products_idle.page_heading == comparison.IDLE_HEADINGS["products"]
    assert ALIBABA_QUERY not in products_idle.page_heading

    products_live = TrackerState()
    products_live.alibaba_query = ALIBABA_QUERY
    products_live.alibaba_ui_status = UI_SUCCESS
    products_live.facebook_product_query = FACEBOOK_QUERY
    products_live.facebook_product_ui_status = UI_SUCCESS
    products_live.show_products()
    assert products_live.page_heading == f"Resultados para: {FACEBOOK_QUERY}"

    comparisons = TrackerState()
    comparisons.alibaba_query = ALIBABA_QUERY
    comparisons.alibaba_ui_status = UI_SUCCESS
    comparisons.ml_query = ML_QUERY
    comparisons.ml_ui_status = UI_SUCCESS
    comparisons.show_comparisons()
    assert comparisons.page_heading == f"Resultados para: {ML_QUERY}"
    assert ALIBABA_QUERY not in comparisons.page_heading

    tools = TrackerState()
    tools.alibaba_query = ALIBABA_QUERY
    tools.alibaba_ui_status = UI_SUCCESS
    tools.query = "pastillas sbr"
    tools.ui_status = UI_SUCCESS
    tools.show_tools()
    assert tools.page_heading == "Resultados para: pastillas sbr"


def test_dashboard_heading_needs_shared_association_context() -> None:
    generic = comparison.page_heading(
        alibaba_query=ALIBABA_QUERY,
        alibaba_status=UI_SUCCESS,
        workspace_view="dashboard",
    )
    assert generic == comparison.IDLE_HEADINGS["dashboard"]
    shared = comparison.page_heading(
        workspace_view="dashboard",
        facebook_association_id=PRODUCT_A,
        ml_association_id=PRODUCT_A,
        context_id=PRODUCT_A,
        context_title="Mouse A",
    )
    assert shared == "Resultados para: Mouse A"


def test_comparisons_heading_can_use_selected_alibaba_context() -> None:
    heading = comparison.page_heading(
        alibaba_query=ALIBABA_QUERY,
        alibaba_status=UI_SUCCESS,
        workspace_view="comparisons",
        context_id=PRODUCT_A,
        context_title="Mouse A",
    )
    assert heading == "Resultados para: Mouse A"
    assert ALIBABA_QUERY not in heading


def test_tracking_and_import_headings_ignore_other_marketplace_queries() -> None:
    tracking = comparison.page_heading(
        alibaba_query=ALIBABA_QUERY,
        alibaba_status=UI_SUCCESS,
        facebook_query=FACEBOOK_QUERY,
        facebook_status=UI_SUCCESS,
        workspace_view="tracking",
    )
    assert tracking == comparison.IDLE_HEADINGS["tracking"]
    import_heading = comparison.page_heading(
        alibaba_query=ALIBABA_QUERY,
        alibaba_status=UI_SUCCESS,
        workspace_view="import",
        context_title="Mouse seleccionado",
    )
    assert import_heading == "Mouse seleccionado"
