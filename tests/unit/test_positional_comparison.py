"""Offline tests for Implementation PR B positional comparison and identity isolation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

import pytest

from bera_price_tracker.application.provider_acquisition import ProviderRunMetrics
from bera_price_tracker.application.search_session import (
    AcquisitionBatch,
    AcquisitionBudgetPolicy,
    ExactProductContext,
    InternalAcquisitionStep,
    ProviderBudgetRule,
    ProviderRunResult,
    ProviderStatus,
    SearchIntent,
    SearchPositionComparisonRow,
    SearchSessionSnapshot,
    build_search_position_comparison_rows,
    displayed_listing_total,
    exact_product_context,
    execute_bounded_provider_search,
    freeze_canonical_prefix,
    native_listing_ids_establish_cross_market_identity,
    ordered_usable_pool_from_batches,
    positional_row_authorizes_exact_workflows,
    positional_rows_from_snapshot,
)
from bera_price_tracker.gui import analysis, comparison, marketplace_summary
from bera_price_tracker.gui.state import (
    UI_SUCCESS,
    AlibabaResultRow,
    FacebookProductResultRow,
    MercadoLibreResultRow,
    TrackerState,
)


@dataclass(frozen=True, slots=True)
class FakeCandidate:
    title: str
    identity: str | None = None
    native_id: str = ""
    image: str = ""
    price: str = ""
    usable: bool = True


def _metrics(**overrides: Any) -> ProviderRunMetrics:
    values: dict[str, Any] = {
        "display_requested": 10,
        "acquisition_budget": 10,
        "acquisition_requested": 10,
        "fetched": None,
        "mapped": None,
        "rejected": None,
        "usable": 1,
        "displayed": 1,
    }
    values.update(overrides)
    return ProviderRunMetrics(**values)


def _result(
    provider: str,
    titles: tuple[str, ...],
    *,
    display_limit: int = 10,
) -> ProviderRunResult[FakeCandidate]:
    pool = tuple(FakeCandidate(title) for title in titles)
    canonical = freeze_canonical_prefix(pool, display_limit)
    return ProviderRunResult(
        provider=provider,
        generation=1,
        status=ProviderStatus.SUCCESS if pool else ProviderStatus.EMPTY,
        ordered_usable_pool=pool,
        canonical_session_results=canonical,
        metrics=_metrics(
            display_requested=display_limit,
            usable=len(pool),
            displayed=len(canonical),
        ),
    )


def _alibaba(title: str, **overrides: Any) -> AlibabaResultRow:
    payload: dict[str, Any] = {
        "title": title,
        "price": "$4.00",
        "product_id": "ali-1",
        "relevance_value": 90,
        "score": "70",
        "score_value": 70,
    }
    payload.update(overrides)
    return AlibabaResultRow.model_validate(payload)


def _facebook(title: str, **overrides: Any) -> FacebookProductResultRow:
    payload: dict[str, Any] = {
        "title": title,
        "price": "10.00 VEF",
        "usd_price": "USD: $10.00",
        "relevance_value": 80,
        "external_id": "fb-1",
    }
    payload.update(overrides)
    return FacebookProductResultRow.model_validate(payload)


def _ml(title: str, **overrides: Any) -> MercadoLibreResultRow:
    payload: dict[str, Any] = {
        "title": title,
        "price": "$9.50",
        "relevance_value": 70,
        "external_id": "MLV-1",
    }
    payload.update(overrides)
    return MercadoLibreResultRow.model_validate(payload)


def test_search_position_comparison_row_is_one_based_and_not_identity() -> None:
    row = SearchPositionComparisonRow(
        rank=1,
        alibaba_candidate=FakeCandidate("A1"),
        facebook_candidate=FakeCandidate("F1"),
        mercadolibre_candidate=FakeCandidate("M1"),
    )
    assert row.rank == 1
    assert row.identity_confirmed is False
    with pytest.raises(ValueError, match="invariant false"):
        SearchPositionComparisonRow(
            rank=1,
            alibaba_candidate=FakeCandidate("A1"),
            identity_confirmed=True,
        )
    with pytest.raises(ValueError, match="one-based"):
        SearchPositionComparisonRow(rank=0, alibaba_candidate=FakeCandidate("A1"))
    with pytest.raises(ValueError, match="at least one candidate"):
        SearchPositionComparisonRow(rank=1)
    with pytest.raises(AttributeError):
        row.identity_confirmed = True  # type: ignore[misc]


def test_uneven_three_two_one_positional_rows() -> None:
    rows = build_search_position_comparison_rows(
        alibaba_candidates=(FakeCandidate("A1"), FakeCandidate("A2"), FakeCandidate("A3")),
        facebook_candidates=(FakeCandidate("F1"), FakeCandidate("F2")),
        mercadolibre_candidates=(FakeCandidate("M1"),),
    )
    assert len(rows) == 3
    assert rows[0].alibaba_candidate is not None and rows[0].alibaba_candidate.title == "A1"
    assert rows[0].facebook_candidate is not None and rows[0].facebook_candidate.title == "F1"
    assert rows[0].mercadolibre_candidate is not None and rows[0].mercadolibre_candidate.title == (
        "M1"
    )
    assert rows[1].mercadolibre_candidate is None
    assert rows[2].facebook_candidate is None
    assert rows[2].mercadolibre_candidate is None
    assert rows[2].alibaba_candidate is not None and rows[2].alibaba_candidate.title == "A3"
    assert all(row.identity_confirmed is False for row in rows)


def test_ten_valid_results_remain_positional_and_unrelated_looking_stay() -> None:
    alibaba = tuple(FakeCandidate(f"A{index}", native_id=str(index)) for index in range(1, 11))
    facebook = tuple(FakeCandidate(f"F{index}", native_id=str(index)) for index in range(1, 11))
    mercadolibre = tuple(FakeCandidate(f"M{index}", native_id=str(index)) for index in range(1, 11))
    rows = build_search_position_comparison_rows(
        alibaba_candidates=alibaba,
        facebook_candidates=facebook,
        mercadolibre_candidates=mercadolibre,
    )
    assert len(rows) == 10
    assert rows[0].alibaba_candidate is alibaba[0]
    assert rows[0].facebook_candidate is facebook[0]
    assert rows[0].mercadolibre_candidate is mercadolibre[0]
    assert rows[0].identity_confirmed is False
    assert positional_row_authorizes_exact_workflows(rows[0]) is False
    assert (
        native_listing_ids_establish_cross_market_identity(
            alibaba[0].native_id, facebook[0].native_id
        )
        is False
    )
    assert exact_product_context() is None


def test_single_acquisition_order_is_preserved_and_identity_less_retained() -> None:
    first = FakeCandidate("same title", image="same.jpg", price="10")
    second = FakeCandidate("same title", image="same.jpg", price="10")
    identified = FakeCandidate("same title", identity="sku-1", image="same.jpg", price="10")
    duplicate = FakeCandidate("duplicate", identity="sku-1")
    pool = ordered_usable_pool_from_batches(
        ((first, second, identified, duplicate),),
        stable_identity=lambda candidate: candidate.identity,
    )
    assert pool == (first, second, identified)


def test_multi_acquisition_uses_documented_deterministic_aggregation() -> None:
    first = FakeCandidate("partition-a", identity="keep")
    later_duplicate = FakeCandidate("partition-b-dup", identity="keep")
    later_unique = FakeCandidate("partition-b-new", identity="new")
    identity_less = FakeCandidate("no-id")
    pool = ordered_usable_pool_from_batches(
        ((first,), (later_duplicate, later_unique, identity_less)),
        stable_identity=lambda candidate: candidate.identity,
    )
    assert pool == (first, later_unique, identity_less)


def test_execute_preserves_single_acquisition_provider_order() -> None:
    policy = AcquisitionBudgetPolicy(provider_rules={"alibaba": ProviderBudgetRule(1, 10, 1)})
    intent = SearchIntent(
        original_user_query="mouse",
        display_limit=3,
        selected_providers=("alibaba",),
        generation=1,
    )
    plan = policy.create_plan(
        provider="alibaba",
        display_limit=3,
        steps=(InternalAcquisitionStep(key="step-1", candidate_limit=3),),
    )
    result = execute_bounded_provider_search(
        intent=intent,
        plan=plan,
        policy=policy,
        acquire=lambda _step: AcquisitionBatch(
            candidates=(
                FakeCandidate("first"),
                FakeCandidate("second"),
                FakeCandidate("third"),
            ),
            fetched=3,
            mapped=3,
            rejected=0,
        ),
        stable_identity=lambda candidate: candidate.identity,
    )
    assert [item.title for item in result.canonical_session_results] == [
        "first",
        "second",
        "third",
    ]


def test_snapshot_positional_rows_and_listing_total_ignore_row_count() -> None:
    snapshot = SearchSessionSnapshot(
        intent=SearchIntent(
            original_user_query="mouse",
            display_limit=3,
            selected_providers=("alibaba", "facebook", "mercadolibre"),
            generation=1,
        )
    )
    snapshot = snapshot.commit(_result("alibaba", ("A1",)))
    snapshot = snapshot.commit(_result("facebook", ("F1",)))
    snapshot = snapshot.commit(
        ProviderRunResult(
            provider="mercadolibre",
            generation=1,
            status=ProviderStatus.EMPTY,
            ordered_usable_pool=(),
            canonical_session_results=(),
            metrics=_metrics(usable=0, displayed=0, display_requested=3),
        )
    )
    rows = positional_rows_from_snapshot(snapshot)
    assert len(rows) == 1
    assert displayed_listing_total(snapshot) == 2
    assert rows[0].identity_confirmed is False
    frozen = rows
    resorted = replace(snapshot)
    assert positional_rows_from_snapshot(resorted) == frozen


def test_exact_association_requires_agreeing_non_empty_ids() -> None:
    assert exact_product_context() is None
    assert exact_product_context(facebook_association_id="A", ml_association_id="A") is None
    assert (
        exact_product_context(
            facebook_association_id="A",
            ml_association_id="B",
            context_id="A",
        )
        is None
    )
    context = exact_product_context(
        facebook_association_id="ALI-1",
        ml_association_id="ALI-1",
        context_id="ALI-1",
    )
    assert context == ExactProductContext(product_id="ALI-1")


def test_native_listing_id_equality_does_not_create_association_or_identity() -> None:
    assert native_listing_ids_establish_cross_market_identity("123", "123") is False
    assert native_listing_ids_establish_cross_market_identity("123", "456") is False
    rows = build_search_position_comparison_rows(
        alibaba_candidates=(FakeCandidate("Alibaba", native_id="123"),),
        facebook_candidates=(FakeCandidate("Facebook", native_id="123"),),
    )
    assert len(rows) == 1
    assert rows[0].identity_confirmed is False
    assert positional_row_authorizes_exact_workflows(rows[0]) is False
    assert (
        exact_product_context(
            facebook_association_id="123",
            ml_association_id="123",
            context_id="",
        )
        is None
    )


def test_gui_positional_rows_are_immutable_under_alibaba_and_ml_filters() -> None:
    state = TrackerState()
    state.search_limit = 3
    state.alibaba_ui_status = UI_SUCCESS
    state.facebook_product_ui_status = UI_SUCCESS
    state.ml_ui_status = UI_SUCCESS
    state.alibaba_results = [
        _alibaba("Cheap first", product_id="a1", price="$1.00", score_value=10, relevance_value=20),
        _alibaba(
            "Expensive later", product_id="a2", price="$90.00", score_value=99, relevance_value=100
        ),
    ]
    state.facebook_product_results = [_facebook("Unrelated FB")]
    state.ml_results = [
        _ml("Low relevance ML", relevance_value=10),
        _ml("High relevance ML", relevance_value=90),
    ]
    before = [
        (row.resultado_label, row.alibaba_title, row.facebook_title, row.ml_title)
        for row in state.positional_comparison_rows
    ]
    totals_before = state.search_total_results
    export_before = state.current_export_listing_count()
    status_before = (
        state.alibaba_ui_status,
        state.facebook_product_ui_status,
        state.ml_ui_status,
    )
    state.alibaba_sort = analysis.SORT_PRICE_DESC
    state.alibaba_min_relevance = 80
    state.set_ml_min_relevance("80+")
    state.ml_sort = analysis.SORT_PRICE_ASC
    after = [
        (row.resultado_label, row.alibaba_title, row.facebook_title, row.ml_title)
        for row in state.positional_comparison_rows
    ]
    assert before == after
    assert before[0][0] == "Resultado #1"
    assert before[0][1] == "Cheap first"
    assert before[0][3] == "Low relevance ML"
    assert state.search_total_results == totals_before
    assert state.current_export_listing_count() == export_before
    assert (
        state.alibaba_ui_status,
        state.facebook_product_ui_status,
        state.ml_ui_status,
    ) == status_before
    assert all(row.identity_confirmed is False for row in state.positional_comparison_rows)
    assert state.positional_comparison_rows[0].disclosure == comparison.POSITIONAL_DISCLOSURE


def test_generic_busquedas_keeps_low_relevance_mercadolibre_listing() -> None:
    """Regression from closed PR #24: specialized ML relevance must not hide generic results."""

    state = TrackerState()
    state.search_limit = 1
    state.search_session_active = True
    state.ml_ui_status = UI_SUCCESS
    state.ml_min_relevance = 60
    state.ml_results = [
        _ml(
            "Valid MLV listing below specialized threshold",
            relevance_value=40,
            price="$12.00",
            permalink="https://articulo.mercadolibre.com.ve/MLV-low",
        )
    ]
    state.ml_summary = {
        "requested": "1",
        "fetched": "1",
        "usable": "1",
        "comparable_count": "0",
        "comparables": "0",
    }
    assert state.ml_visible_rows == []
    assert state.search_total_results == "1"
    rows = state.positional_comparison_rows
    assert len(rows) == 1
    assert rows[0].resultado_label == "Resultado #1"
    assert rows[0].ml_title == "Valid MLV listing below specialized threshold"
    assert rows[0].ml_has_listing is True
    cards = state.generic_marketplace_summaries
    ml_card = next(card for card in cards if card.platform == "Mercado Libre")
    assert ml_card.result_count == "1"
    assert ml_card.status_label != "Sin resultados"


def test_specialized_filtered_empty_card_does_not_claim_nonzero_visible_results() -> None:
    cards = marketplace_summary.build_marketplace_summaries(
        alibaba_ui_status=UI_SUCCESS,
        alibaba_summary={"resultados": "3"},
        alibaba_rows=[],
        facebook_ui_status=UI_SUCCESS,
        facebook_summary={"usable": "2"},
        facebook_rows=[],
        ml_ui_status=UI_SUCCESS,
        ml_summary={"comparable_count": "4", "requested": "1", "fetched": "1", "usable": "1"},
        ml_rows=[],
    )
    assert cards[0].get("result_count") == "0" or cards[0]["result_count"] == "0"
    assert cards[0]["status_label"] == "Sin resultados"
    assert cards[1]["result_count"] == "0"
    assert cards[1]["status_label"] == "Sin resultados"
    assert cards[2]["result_count"] == "0"
    assert cards[2]["status_label"] == "Sin resultados"


def test_positional_cells_render_available_fields_and_blank_optional_ones() -> None:
    rows = comparison.build_positional_comparison_rows(
        alibaba_rows=[
            _alibaba(
                "Alibaba full",
                image_url="https://s.alicdn.com/a.jpg",
                url="https://www.alibaba.com/p/1",
                supplier_name="Shenzhen Co",
                moq="10",
                review_score="4.8",
                review_count="12",
                supplier_service_score="4.9",
                gold_supplier_years="6",
                currency="USD",
                price_min="1.00",
                price_max="2.00",
            )
        ],
        facebook_rows=[
            _facebook(
                "Facebook sparse",
                image_url="",
                permalink="https://facebook.com/marketplace/item/1",
                location="Caracas",
            )
        ],
        ml_rows=[
            _ml(
                "ML full",
                thumbnail_url="https://http2.mlstatic.com/b.jpg",
                permalink="https://articulo.mercadolibre.com.ve/MLV1",
                condition="Nuevo",
                seller_name="Tienda VE",
                rating_average="4.1",
                review_count="8",
                seller_reputation="MercadoLíder",
            )
        ],
        alibaba_status=UI_SUCCESS,
        facebook_status=UI_SUCCESS,
        ml_status=UI_SUCCESS,
    )
    row = rows[0]
    assert row["alibaba_title"] == "Alibaba full"
    assert row["alibaba_price"] == "$4.00"
    assert row["alibaba_url"] == "https://www.alibaba.com/p/1"
    assert row["alibaba_supplier"] == "Shenzhen Co"
    assert row["alibaba_moq"] == "MOQ: 10"
    assert row["alibaba_rating_available"] is True
    assert row["facebook_title"] == "Facebook sparse"
    assert row["facebook_rating_available"] is False
    assert row["facebook_rating_label"] == "Sin calificación"
    assert row["facebook_image_url"] == ""
    assert "facebook_seller" not in row
    assert row["ml_condition"] == "Nuevo"
    assert row["ml_seller"] == "Tienda VE"
    assert row["ml_rating_available"] is True
    assert row["identity_confirmed"] is False
    assert row["product_id"] == ""
    missing = comparison.build_positional_comparison_rows(
        facebook_rows=[_facebook("No extras")],
        facebook_status=UI_SUCCESS,
    )
    sparse = missing[0]
    assert sparse["facebook_has_listing"] is True
    assert sparse["alibaba_has_listing"] is False
    assert sparse["ml_has_listing"] is False
    assert sparse["opportunity_available"] is False
    assert sparse["facebook_rating_available"] is False
    assert sparse["alibaba_title"] == ""
    assert sparse["ml_title"] == ""
    assert sparse["ml_seller"] == ""
    assert sparse["alibaba_moq"] == ""


def test_row_without_alibaba_has_no_alibaba_opportunity() -> None:
    rows = comparison.build_positional_comparison_rows(
        facebook_rows=[_facebook("Only FB")],
        ml_rows=[_ml("Only ML")],
        facebook_status=UI_SUCCESS,
        ml_status=UI_SUCCESS,
    )
    assert len(rows) == 1
    assert rows[0]["opportunity_available"] is False
    assert rows[0]["analysis_heading"] == comparison.ANALYSIS_UNAVAILABLE
    assert rows[0]["facebook_has_listing"] is True
    assert rows[0]["ml_has_listing"] is True


def test_positional_landed_cost_is_not_attached_from_position() -> None:
    rows = comparison.build_positional_comparison_rows(
        alibaba_rows=[_alibaba("A")],
        facebook_rows=[_facebook("F")],
        ml_rows=[_ml("M")],
        alibaba_status=UI_SUCCESS,
        facebook_status=UI_SUCCESS,
        ml_status=UI_SUCCESS,
    )
    assert "6.10" not in str(rows[0])
    assert rows[0]["analysis_heading"] != "Costo puesto"
    assert (
        positional_row_authorizes_exact_workflows(
            SearchPositionComparisonRow(rank=1, alibaba_candidate=FakeCandidate("A"))
        )
        is False
    )


def test_association_builder_remains_available_for_specialized_views() -> None:
    rows = comparison.build_comparison_rows(
        facebook_rows=[_facebook("mouse")],
        ml_rows=[_ml("headphones")],
        facebook_status=UI_SUCCESS,
        ml_status=UI_SUCCESS,
    )
    combined = [row for row in rows if row["facebook_has_listing"] and row["ml_has_listing"]]
    assert combined == []
    associated = comparison.build_comparison_rows(
        alibaba_rows=[_alibaba("Mouse A", product_id="ali-A")],
        facebook_rows=[_facebook("Mouse FB A")],
        ml_rows=[_ml("Mouse ML A")],
        alibaba_status=UI_SUCCESS,
        facebook_status=UI_SUCCESS,
        ml_status=UI_SUCCESS,
        facebook_association_id="ali-A",
        ml_association_id="ali-A",
        alibaba_context={"external_id": "ali-A", "title": "Mouse A"},
    )
    assert len(associated) == 1
    assert associated[0]["product_id"] == "ali-A"
