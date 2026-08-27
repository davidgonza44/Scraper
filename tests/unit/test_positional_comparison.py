"""Offline tests for Implementation PR B positional comparison and identity isolation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, cast

import pytest

from bera_price_tracker.application.provider_acquisition import ProviderRunMetrics
from bera_price_tracker.application.search_session import (
    GENERIC_SESSION_UNSET_GENERATION,
    AcquisitionBatch,
    AcquisitionBudgetPolicy,
    ExactProductContext,
    GenericSessionProviderSnapshot,
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
    generic_session_owned_provider_view,
    native_listing_ids_establish_cross_market_identity,
    ordered_usable_pool_from_batches,
    owned_generic_session_provider,
    positional_row_authorizes_exact_workflows,
    positional_rows_from_snapshot,
)
from bera_price_tracker.gui import analysis, comparison, marketplace_summary, search_export
from bera_price_tracker.gui.search_scope import MODE_MULTI, plan_search
from bera_price_tracker.gui.state import (
    UI_ERROR,
    UI_LOADING,
    UI_SUCCESS,
    AlibabaResultRow,
    FacebookCurrencyStatsRow,
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


def _facebook_stats(**overrides: Any) -> FacebookCurrencyStatsRow:
    payload: dict[str, Any] = {
        "currency": "USD",
        "label": "USD generic",
        "basis": "USD",
        "count": "1",
        "minimum": "150.00",
        "average": "150.00",
        "median": "150.00",
        "maximum": "150.00",
        "p25": "150.00",
        "p75": "150.00",
    }
    payload.update(overrides)
    return FacebookCurrencyStatsRow.model_validate(payload)


def _complete_generic_three_platform_search(state: TrackerState, *, generation: int = 4) -> None:
    state.search_generation = generation
    plan = plan_search(mode=MODE_MULTI, query="wireless mouse", limit=3)
    state.search_session_active = True
    state.search_session_query = plan.query
    state.search_limit = plan.limit
    state._prepare_scoped_search(plan)
    state._finalize_alibaba_search(
        request_query=plan.query,
        request_limit=plan.limit,
        rows=[_alibaba("Generic Alibaba", product_id="ali-generic", price="USD 4.00")],
        summary={
            "resultados": "1",
            "minimo": "USD 4.00",
            "mediana": "USD 4.00",
            "promedio": "USD 4.00",
            "maximo": "USD 4.00",
            "requested": "3",
            "fetched": "1",
            "usable": "1",
        },
        stats_raw={"minimum": "4.00", "median": "4.00", "average": "4.00", "maximum": "4.00"},
        ui_status=UI_SUCCESS,
        commit_generic_session=True,
    )
    state._finalize_facebook_product_search(
        product_id="",
        query=plan.query,
        city=plan.city,
        rows=[_facebook("Generic Facebook", external_id="fb-generic", usd_price="USD 150.00")],
        statistics=[_facebook_stats()],
        summary={"usable": "1", "requested": "3", "fetched": "1"},
        ui_status=UI_SUCCESS,
        commit_generic_session=True,
    )
    state._finalize_mercadolibre_search(
        search_product_id="",
        query=plan.query,
        rows=[
            _ml(
                "Generic ML listing",
                external_id="MLV-generic",
                price="USD 9.00",
                price_raw="9.00",
                currency="USD",
                relevance_value=80,
            )
        ],
        summary={
            "comparable_count": "1",
            "usable": "1",
            "requested": "3",
            "fetched": "1",
            "minimo": "USD 9.00",
            "mediana": "USD 9.00",
            "precio_tipico": "USD 9.00",
            "maximo": "USD 9.00",
            "currency": "USD",
        },
        ui_status=UI_SUCCESS,
    )


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
                shipping="Envío gratis",
                official_store="Tienda oficial",
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
    assert row["ml_shipping"] == "Envío gratis"
    assert row["ml_official_store"] == "Tienda oficial"
    assert row["ml_rating_available"] is True
    assert row["identity_confirmed"] is False
    assert row["product_id"] == ""
    paid = comparison.build_positional_comparison_rows(
        ml_rows=[
            _ml(
                "ML paid",
                shipping="Pago",
                official_store="",
                seller_name="Tienda VE",
            )
        ],
        ml_status=UI_SUCCESS,
    )[0]
    assert paid["ml_has_listing"] is True
    assert paid["ml_shipping"] == "Pago"
    assert paid["ml_official_store"] == ""
    unknown = comparison.build_positional_comparison_rows(
        ml_rows=[_ml("ML unknown shipping", shipping="—", official_store="")],
        ml_status=UI_SUCCESS,
    )[0]
    assert unknown["ml_has_listing"] is True
    assert unknown["ml_shipping"] == ""
    assert unknown["ml_official_store"] == ""
    inferred = comparison.build_positional_comparison_rows(
        ml_rows=[
            _ml(
                "Tienda oficial mouse",
                seller_name="Tienda oficial",
                seller_reputation="Tienda oficial",
                seller_status="Tienda oficial",
                official_store="",
                shipping="Pago",
            )
        ],
        ml_status=UI_SUCCESS,
    )[0]
    assert inferred["ml_has_listing"] is True
    assert inferred["ml_shipping"] == "Pago"
    assert inferred["ml_official_store"] == ""
    duplicate = comparison.build_positional_comparison_rows(
        ml_rows=[
            _ml(
                "ML duplicate store",
                shipping="Envío gratis",
                official_store="Tienda oficial",
                seller_status="Tienda oficial",
            )
        ],
        ml_status=UI_SUCCESS,
    )[0]
    assert duplicate["ml_has_listing"] is True
    assert duplicate["ml_official_store"] == "Tienda oficial"
    visible_official = [str(duplicate["ml_official_store"]), str(duplicate["ml_trust_line"])]
    assert "".join(visible_official).count("Tienda oficial") == 1
    associated = comparison.build_comparison_rows(
        alibaba_rows=[_alibaba("Alibaba associated", product_id="ali-1")],
        ml_rows=[
            _ml(
                "ML associated",
                shipping="Envío gratis",
                official_store="Tienda oficial",
            )
        ],
        alibaba_status=UI_SUCCESS,
        ml_status=UI_SUCCESS,
        ml_association_id="ali-1",
    )
    assert associated[0]["ml_has_listing"] is True
    assert associated[0]["ml_shipping"] == "Envío gratis"
    assert associated[0]["ml_official_store"] == "Tienda oficial"
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
    assert sparse["ml_shipping"] == ""
    assert sparse["ml_official_store"] == ""
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


def test_generic_session_owned_view_prefers_matching_generation_snapshot() -> None:
    live = GenericSessionProviderSnapshot(
        generation=GENERIC_SESSION_UNSET_GENERATION,
        status="ERROR",
        rows=(FakeCandidate("specialized"),),
        summary={"usable": "9", "minimo": "USD 99.00"},
        error="specialized failed",
        metadata={"diagnostic_summary": {"usable": "9"}},
    )
    stored = GenericSessionProviderSnapshot(
        generation=4,
        status="SUCCESS",
        rows=(FakeCandidate("generic"),),
        summary={"usable": "1", "minimo": "USD 9.00"},
        error="",
        metadata={"diagnostic_summary": {"usable": "1"}},
    )
    owned = owned_generic_session_provider(stored=stored, active_generation=4, live=live)
    assert [item.title for item in owned.rows] == ["generic"]
    assert owned.summary["minimo"] == "USD 9.00"
    assert owned.error == ""
    fallback = generic_session_owned_provider_view(
        stored_rows=stored.rows,
        stored_status=stored.status,
        stored_generation=GENERIC_SESSION_UNSET_GENERATION,
        active_generation=4,
        live_rows=live.rows,
        live_status=live.status,
    )
    assert [item.title for item in fallback.rows] == ["specialized"]
    assert fallback.status == "ERROR"
    stale = owned_generic_session_provider(stored=stored, active_generation=5, live=live)
    assert [item.title for item in stale.rows] == ["specialized"]
    assert stale.summary["usable"] == "9"
    assert stale.error == "specialized failed"


def test_generic_busquedas_keeps_session_owned_ml_after_specialized_overwrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1: specialized ML must not mix into the still-active generic Búsquedas session."""

    state = TrackerState()
    _complete_generic_three_platform_search(state)
    assert state.ml_results_from_generic_session is True
    assert [row.ml_title for row in state.positional_comparison_rows] == ["Generic ML listing"]
    generic_ml_card = next(
        card for card in state.generic_marketplace_summaries if card.platform == "Mercado Libre"
    )
    generic_average = generic_ml_card.average
    generic_diag = {line.label: line.value for line in generic_ml_card.diagnostic_lines}

    state.ml_results_from_generic_session = False
    state.ml_query = "specialized headphones"
    state.ml_results = [
        _ml(
            "Specialized ML listing",
            external_id="MLV-specialized",
            price="USD 99.00",
            price_raw="99.00",
            relevance_value=95,
        )
    ]
    state.ml_summary = {
        "comparable_count": "9",
        "usable": "9",
        "requested": "9",
        "fetched": "9",
        "minimo": "USD 99.00",
        "mediana": "USD 99.00",
        "precio_tipico": "USD 99.00",
        "maximo": "USD 99.00",
    }
    state.ml_error = "Specialized ML exploded"
    state.ml_ui_status = UI_SUCCESS
    state.show_searches()

    rows = state.positional_comparison_rows
    assert len(rows) == 1
    assert rows[0].resultado_label == "Resultado #1"
    assert rows[0].alibaba_title == "Generic Alibaba"
    assert rows[0].facebook_title == "Generic Facebook"
    assert rows[0].ml_title == "Generic ML listing"
    assert rows[0].ml_title != "Specialized ML listing"
    assert state.search_total_results == "3"
    ml_card = next(
        card for card in state.generic_marketplace_summaries if card.platform == "Mercado Libre"
    )
    assert ml_card.result_count == "1"
    assert ml_card.status != "error"
    assert ml_card.average == generic_average
    assert "99.00" not in ml_card.average
    assert "99.00" not in ml_card.minimum
    assert "Specialized ML exploded" not in ml_card.note
    assert "Specialized ML exploded" not in ml_card.diagnostic_detail
    diag = {line.label: line.value for line in ml_card.diagnostic_lines}
    assert diag == generic_diag
    assert diag.get("Válidos") != "9"
    assert state.current_export_listing_count() == 3
    captured: dict[str, object] = {}

    def capture(**kwargs: object) -> list[dict[str, str]]:
        captured.update(kwargs)
        return [{column: "" for column in search_export.CSV_COLUMNS}]

    monkeypatch.setattr(search_export, "listing_rows_for_export", capture)
    assert state.export_current_search() is not None
    exported_ml = cast(list[MercadoLibreResultRow], captured["ml_rows"])
    assert [row.title for row in exported_ml] == ["Generic ML listing"]
    ml_diag = cast(dict[str, object], captured["ml_diagnostic"])
    assert ml_diag.get("usable") != "9"
    assert ml_diag.get("detail", "") != "Specialized ML exploded"
    assert state.ml_results[0].title == "Specialized ML listing"
    assert state.ml_error == "Specialized ML exploded"
    spec_ml = next(card for card in state.marketplace_summaries if card.platform == "Mercado Libre")
    assert spec_ml.result_count == "1"
    spec_diag = {line.label: line.value for line in spec_ml.diagnostic_lines}
    assert spec_diag.get("Válidos") == "9"
    spec_rows = state.comparison_rows
    ml_specialized_titles = [row.ml_title for row in spec_rows if row.ml_has_listing]
    assert "Specialized ML listing" in ml_specialized_titles
    assert "Generic ML listing" not in ml_specialized_titles


def test_generic_card_count_equals_canonical_rows_not_comparable_count() -> None:
    """P2: generic Búsquedas counts canonical session rows, not specialized comparables."""

    state = TrackerState()
    state.search_limit = 5
    state.ml_ui_status = UI_SUCCESS
    state.ml_min_relevance = 60
    state.ml_results = [
        _ml("ML low", relevance_value=10, external_id="MLV-1"),
        _ml("ML mid", relevance_value=40, external_id="MLV-2"),
        _ml("ML high", relevance_value=90, external_id="MLV-3"),
    ]
    state.ml_summary = {
        "comparable_count": "1",
        "comparables": "1 de 3",
        "usable": "3",
        "requested": "3",
        "fetched": "3",
    }
    assert [row.title for row in state.ml_visible_rows] == ["ML high"]
    assert state.search_total_results == "3"
    rows = state.positional_comparison_rows
    assert len(rows) == 3
    assert [row.ml_title for row in rows] == ["ML low", "ML mid", "ML high"]
    ml_card = next(
        card for card in state.generic_marketplace_summaries if card.platform == "Mercado Libre"
    )
    assert ml_card.result_count == "3"


def test_specialized_card_count_equals_visible_projection_not_raw_comparable() -> None:
    """P2: specialized cards follow the filtered projection, including empty."""

    cards_one = marketplace_summary.build_marketplace_summaries(
        alibaba_ui_status=UI_SUCCESS,
        alibaba_summary={"resultados": "3"},
        alibaba_rows=[_alibaba("A1"), _alibaba("A2", product_id="ali-2")],
        facebook_ui_status=UI_SUCCESS,
        facebook_summary={"usable": "3"},
        facebook_rows=[_facebook("F1")],
        ml_ui_status=UI_SUCCESS,
        ml_summary={"comparable_count": "3", "comparables": "3"},
        ml_rows=[_ml("ML high", relevance_value=90)],
    )
    assert cards_one[0]["result_count"] == "2"
    assert cards_one[1]["result_count"] == "1"
    assert cards_one[2]["result_count"] == "1"

    state = TrackerState()
    state.ml_ui_status = UI_SUCCESS
    state.ml_min_relevance = 60
    state.ml_results = [
        _ml("ML low", relevance_value=10, external_id="MLV-1"),
        _ml("ML mid", relevance_value=40, external_id="MLV-2"),
        _ml("ML high", relevance_value=90, external_id="MLV-3"),
    ]
    state.ml_summary = {"comparable_count": "3", "usable": "3"}
    ml_card = next(card for card in state.marketplace_summaries if card.platform == "Mercado Libre")
    assert len(state.ml_visible_rows) == 1
    assert ml_card.result_count == "1"

    state.ml_min_relevance = 99
    empty_card = next(
        card for card in state.marketplace_summaries if card.platform == "Mercado Libre"
    )
    assert state.ml_visible_rows == []
    assert empty_card.result_count == "0"


def test_generic_busquedas_keeps_session_owned_facebook_after_specialized_overwrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = TrackerState()
    _complete_generic_three_platform_search(state)
    generic_fb = next(
        card
        for card in state.generic_marketplace_summaries
        if card.platform == "Facebook Marketplace"
    )
    generic_average = generic_fb.average
    generic_note = generic_fb.note

    state.facebook_product_results = [
        _facebook(
            "Specialized Facebook",
            external_id="fb-specialized",
            usd_price="USD 999.00",
            price="USD 999.00",
        )
    ]
    state.facebook_product_summary = {"usable": "9", "requested": "9", "fetched": "9"}
    state.facebook_product_statistics = [
        _facebook_stats(
            label="USD specialized",
            minimum="999.00",
            average="999.00",
            median="999.00",
            maximum="999.00",
        )
    ]
    state.facebook_product_error = "Specialized Facebook exploded"
    state.facebook_product_ui_status = UI_ERROR
    state.show_searches()

    rows = state.positional_comparison_rows
    assert rows[0].facebook_title == "Generic Facebook"
    assert rows[0].ml_title == "Generic ML listing"
    fb_card = next(
        card
        for card in state.generic_marketplace_summaries
        if card.platform == "Facebook Marketplace"
    )
    assert fb_card.result_count == "1"
    assert fb_card.status != "error"
    assert fb_card.average == generic_average
    assert "999.00" not in fb_card.average
    assert "Specialized Facebook exploded" not in fb_card.note
    assert fb_card.note == generic_note
    captured: dict[str, object] = {}

    def capture(**kwargs: object) -> list[dict[str, str]]:
        captured.update(kwargs)
        return [{column: "" for column in search_export.CSV_COLUMNS}]

    monkeypatch.setattr(search_export, "listing_rows_for_export", capture)
    assert state.export_current_search() is not None
    exported_fb = cast(list[FacebookProductResultRow], captured["facebook_rows"])
    assert [row.title for row in exported_fb] == ["Generic Facebook"]
    fb_diag = cast(dict[str, object], captured["facebook_diagnostic"])
    assert fb_diag.get("usable") != "9"
    assert fb_diag.get("detail", "") != "Specialized Facebook exploded"
    spec_fb = next(
        card for card in state.marketplace_summaries if card.platform == "Facebook Marketplace"
    )
    assert spec_fb.status == "error"
    assert "Specialized Facebook exploded" in spec_fb.note
    assert state.facebook_product_results[0].title == "Specialized Facebook"


def test_new_generic_generation_replaces_previous_snapshot_atomically() -> None:
    state = TrackerState()
    _complete_generic_three_platform_search(state, generation=4)
    assert [row.ml_title for row in state.positional_comparison_rows] == ["Generic ML listing"]
    stale = GenericSessionProviderSnapshot(
        generation=4,
        status=UI_SUCCESS,
        rows=(FakeCandidate("stale"),),
        summary={"usable": "1", "minimo": "USD 4.00"},
        error="",
        metadata={},
    )
    live = GenericSessionProviderSnapshot(
        generation=GENERIC_SESSION_UNSET_GENERATION,
        status=UI_SUCCESS,
        rows=(FakeCandidate("keyboard"),),
        summary={"usable": "1", "minimo": "USD 20.00"},
        error="",
        metadata={},
    )
    replaced = owned_generic_session_provider(stored=stale, active_generation=5, live=live)
    assert [item.title for item in replaced.rows] == ["keyboard"]
    assert replaced.summary["minimo"] == "USD 20.00"

    state.search_generation = 5
    plan = plan_search(mode=MODE_MULTI, query="keyboard", limit=3)
    state.search_session_query = plan.query
    state._prepare_scoped_search(plan)
    assert state.positional_comparison_rows == []
    mouse_cards = " ".join(
        f"{card.average} {card.note} {card.diagnostic_detail}"
        for card in state.generic_marketplace_summaries
    )
    assert "Generic ML listing" not in mouse_cards
    assert "USD 9.00" not in mouse_cards or all(
        card.result_count == "0" for card in state.generic_marketplace_summaries
    )

    state._finalize_alibaba_search(
        request_query=plan.query,
        request_limit=plan.limit,
        rows=[_alibaba("Keyboard Alibaba", product_id="ali-keyboard", price="USD 20.00")],
        summary={
            "resultados": "1",
            "minimo": "USD 20.00",
            "mediana": "USD 20.00",
            "promedio": "USD 20.00",
            "maximo": "USD 20.00",
            "usable": "1",
        },
        ui_status=UI_SUCCESS,
        commit_generic_session=True,
    )
    state._finalize_facebook_product_search(
        product_id="",
        query=plan.query,
        city=plan.city,
        rows=[_facebook("Keyboard Facebook", external_id="fb-keyboard")],
        statistics=[_facebook_stats(minimum="20.00", average="20.00", median="20.00")],
        summary={"usable": "1"},
        ui_status=UI_SUCCESS,
        commit_generic_session=True,
    )
    state._finalize_mercadolibre_search(
        search_product_id="",
        query=plan.query,
        rows=[_ml("Keyboard ML", external_id="MLV-keyboard", price="USD 20.00")],
        summary={
            "usable": "1",
            "comparable_count": "1",
            "minimo": "USD 20.00",
            "precio_tipico": "USD 20.00",
        },
        ui_status=UI_SUCCESS,
    )
    rows = state.positional_comparison_rows
    assert [row.alibaba_title for row in rows] == ["Keyboard Alibaba"]
    assert [row.facebook_title for row in rows] == ["Keyboard Facebook"]
    assert [row.ml_title for row in rows] == ["Keyboard ML"]
    assert all("Generic" not in row.ml_title for row in rows)
    ml_card = next(
        card for card in state.generic_marketplace_summaries if card.platform == "Mercado Libre"
    )
    assert "9.00" not in ml_card.average
    assert ml_card.result_count == "1"


def test_generic_ml_statistics_use_canonical_rows_not_relevance_filter() -> None:
    """P1: generic Búsquedas prices come from all canonical rows, not ml_min_relevance."""

    state = TrackerState()
    state.search_generation = 4
    plan = plan_search(mode=MODE_MULTI, query="wireless mouse", limit=3)
    state.search_session_active = True
    state.search_session_query = plan.query
    state.search_limit = plan.limit
    state.ml_min_relevance = 60
    state._prepare_scoped_search(plan)
    state._finalize_alibaba_search(
        request_query=plan.query,
        request_limit=plan.limit,
        rows=[_alibaba("Generic Alibaba", product_id="ali-generic", price="USD 4.00")],
        summary={"resultados": "1", "usable": "1"},
        stats_raw={"minimum": "4.00", "median": "4.00", "average": "4.00", "maximum": "4.00"},
        ui_status=UI_SUCCESS,
        commit_generic_session=True,
    )
    state._finalize_facebook_product_search(
        product_id="",
        query=plan.query,
        city=plan.city,
        rows=[_facebook("Generic Facebook", external_id="fb-generic")],
        statistics=[_facebook_stats()],
        summary={"usable": "1"},
        ui_status=UI_SUCCESS,
        commit_generic_session=True,
    )
    state._finalize_mercadolibre_search(
        search_product_id="",
        query=plan.query,
        rows=[
            _ml(
                "ML cheap",
                external_id="MLV-cheap",
                price="USD 10.00",
                price_raw="10.00",
                currency="USD",
                relevance_value=10,
            ),
            _ml(
                "ML mid",
                external_id="MLV-mid",
                price="USD 20.00",
                price_raw="20.00",
                currency="USD",
                relevance_value=20,
            ),
            _ml(
                "ML high",
                external_id="MLV-high",
                price="USD 100.00",
                price_raw="100.00",
                currency="USD",
                relevance_value=90,
            ),
        ],
        summary={
            "comparable_count": "1",
            "comparables": "1 de 3",
            "usable": "3",
            "requested": "3",
            "fetched": "3",
            "minimo": "100.00 USD",
            "mediana": "100.00 USD",
            "precio_tipico": "100.00 USD",
            "promedio": "100.00 USD",
            "maximo": "100.00 USD",
            "currency": "USD",
        },
        ui_status=UI_SUCCESS,
    )

    rows = state.positional_comparison_rows
    assert [row.ml_title for row in rows] == ["ML cheap", "ML mid", "ML high"]
    generic = next(
        card for card in state.generic_marketplace_summaries if card.platform == "Mercado Libre"
    )
    assert generic.result_count == "3"
    assert "10.00" in generic.minimum
    assert "100.00" not in generic.minimum
    assert "20.00" in generic.median
    assert "100.00" in generic.maximum
    assert "100.00" not in generic.average
    ml_track = next(
        track for track in state.price_distribution_tracks if track["platform"] == "mercadolibre"
    )
    assert "10.00" in ml_track["minimum"]
    assert "100.00" not in ml_track["minimum"]
    assert "20.00" in ml_track["median"]
    assert "100.00" in ml_track["maximum"]

    assert [row.title for row in state.ml_visible_rows] == ["ML high"]
    specialized = next(
        card for card in state.marketplace_summaries if card.platform == "Mercado Libre"
    )
    assert specialized.result_count == "1"
    assert "100.00" in specialized.minimum
    assert specialized.minimum != generic.minimum
    assert specialized.average != generic.average


def test_generic_search_phase_stays_session_owned_during_specialized_loading() -> None:
    """P1: Búsquedas phase/visibility stay on the owned generic generation."""

    state = TrackerState()
    _complete_generic_three_platform_search(state)
    assert state.search_session_phase == "COMPLETE"
    assert state.search_shows_results is True
    assert state.search_shows_setup is False

    state.facebook_product_is_loading = True
    state.facebook_product_ui_status = UI_LOADING
    state.ml_is_loading = True
    state.ml_ui_status = UI_LOADING
    state.show_searches()
    assert state.search_session_phase == "COMPLETE"
    assert state.search_shows_results is True
    assert state.search_shows_setup is False
    assert [row.ml_title for row in state.positional_comparison_rows] == ["Generic ML listing"]
    assert [row.alibaba_title for row in state.positional_comparison_rows] == ["Generic Alibaba"]

    state.facebook_product_is_loading = False
    state.facebook_product_ui_status = UI_ERROR
    state.facebook_product_error = "Specialized Facebook failed"
    state.facebook_product_results = []
    state.ml_is_loading = False
    state.ml_ui_status = UI_ERROR
    state.ml_error = "Specialized ML failed"
    state.ml_results = []
    assert state.search_session_phase == "COMPLETE"
    assert state.search_shows_results is True
    generic_cards = {card.platform: card for card in state.generic_marketplace_summaries}
    assert generic_cards["Facebook Marketplace"].status != "error"
    assert generic_cards["Mercado Libre"].status != "error"
    assert "Specialized Facebook failed" not in generic_cards["Facebook Marketplace"].note
    assert "Specialized ML failed" not in generic_cards["Mercado Libre"].note

    state.search_generation = 5
    plan = plan_search(mode=MODE_MULTI, query="keyboard", limit=3)
    state.search_session_query = plan.query
    state._prepare_scoped_search(plan)
    assert state.search_session_phase == "RUNNING"
    assert state.search_shows_setup is True
    assert state.search_shows_results is False
