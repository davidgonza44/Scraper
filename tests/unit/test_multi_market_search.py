"""Offline multi-market search orchestration, brands, and provenance."""

from __future__ import annotations

import asyncio
import threading
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from bera_price_tracker.application.facebook_products import SearchFacebookMarketplaceProducts
from bera_price_tracker.application.ports import FacebookMarketplaceProductSearchProvider
from bera_price_tracker.gui import brands, comparison, search_scope, search_session
from bera_price_tracker.gui.brands import PLATFORM_ALIBABA, PLATFORM_FACEBOOK, PLATFORM_ML
from bera_price_tracker.gui.search_scope import (
    DEFAULT_SEARCH_LIMIT,
    MODE_LABELS,
    MODE_MULTI,
    MODE_SINGLE,
    SEARCH_LIMIT_ERROR,
    SEARCH_LIMIT_OPTIONS,
    ProviderCallLog,
    execute_market_search,
    plan_search,
    validate_search_limit,
)
from bera_price_tracker.gui.state import (
    UI_ERROR,
    UI_INITIAL,
    UI_LOADING,
    UI_SUCCESS,
    AlibabaResultRow,
    AlibabaTrackedRow,
    FacebookCurrencyStatsRow,
    FacebookProductResultRow,
    MercadoLibreResultRow,
    TrackerState,
)
from bera_price_tracker.infrastructure.providers.apify import (
    ApifyFacebookMarketplaceClient,
    ApifyFacebookResult,
)
from bera_price_tracker.infrastructure.providers.facebook_products import (
    FacebookMarketplaceProductSearch,
)
from tests.unit.test_facebook_products import COLLECTED_AT, FakeFacebookClient, _record


def _runners(log: ProviderCallLog) -> dict[str, Any]:
    def alibaba(**kwargs: object) -> dict[str, str]:
        log.record("alibaba-run")
        return {"provider": "alibaba", "query": str(kwargs["query"])}

    def facebook(**kwargs: object) -> dict[str, str]:
        log.record("facebook-run")
        return {"provider": "facebook", "query": str(kwargs["query"])}

    def ml(**kwargs: object) -> dict[str, str]:
        log.record("ml-run")
        return {"provider": "ml", "query": str(kwargs["query"])}

    return {
        PLATFORM_ALIBABA: alibaba,
        PLATFORM_FACEBOOK: facebook,
        PLATFORM_ML: ml,
    }


def test_default_limit_and_shared_options() -> None:
    assert DEFAULT_SEARCH_LIMIT == 3
    assert SEARCH_LIMIT_OPTIONS == (1, 3, 5)
    for option in SEARCH_LIMIT_OPTIONS:
        assert validate_search_limit(option) == option


def test_invalid_limits_are_rejected() -> None:
    for value in (0, 2, 4, 6, 10, 20, "abc", True):
        with pytest.raises(ValueError, match="1, 3 o 5"):
            validate_search_limit(value)


def test_multi_market_calls_each_provider_once() -> None:
    log = ProviderCallLog()
    plan = plan_search(mode=MODE_MULTI, query="mouse", limit=3)
    outcome = execute_market_search(plan, _runners(log), log=log)
    assert plan.providers == (PLATFORM_ALIBABA, PLATFORM_FACEBOOK, PLATFORM_ML)
    assert log.count(PLATFORM_ALIBABA) == 1
    assert log.count(PLATFORM_FACEBOOK) == 1
    assert log.count(PLATFORM_ML) == 1
    assert log.count("alibaba-run") == 1
    assert log.count("facebook-run") == 1
    assert log.count("ml-run") == 1
    assert outcome.retries == 0
    assert set(outcome.results) == {PLATFORM_ALIBABA, PLATFORM_FACEBOOK, PLATFORM_ML}


def test_single_alibaba_does_not_call_others() -> None:
    log = ProviderCallLog()
    plan = plan_search(mode=MODE_SINGLE, platform=PLATFORM_ALIBABA, query="mouse", limit=3)
    execute_market_search(plan, _runners(log), log=log)
    assert plan.providers == (PLATFORM_ALIBABA,)
    assert log.count("alibaba-run") == 1
    assert log.count("facebook-run") == 0
    assert log.count("ml-run") == 0


def test_single_facebook_does_not_call_others() -> None:
    log = ProviderCallLog()
    plan = plan_search(mode=MODE_SINGLE, platform=PLATFORM_FACEBOOK, query="mouse", limit=3)
    execute_market_search(plan, _runners(log), log=log)
    assert log.count("facebook-run") == 1
    assert log.count("alibaba-run") == 0
    assert log.count("ml-run") == 0


def test_single_ml_does_not_call_others() -> None:
    log = ProviderCallLog()
    plan = plan_search(mode=MODE_SINGLE, platform=PLATFORM_ML, query="mouse", limit=3)
    execute_market_search(plan, _runners(log), log=log)
    assert log.count("ml-run") == 1
    assert log.count("alibaba-run") == 0
    assert log.count("facebook-run") == 0


def test_facebook_free_listing_is_rejected_without_retry() -> None:
    fake = FakeFacebookClient(
        ApifyFacebookResult(
            records=(
                _record(product_id="1", price=Decimal("10"), formatted_price="$10"),
                _record(product_id="2", price=Decimal("0"), formatted_price="Free"),
                _record(product_id="3", price=Decimal("12"), formatted_price="$12"),
            ),
            fetched=3,
            source_errors=0,
        ),
        [],
    )
    provider = FacebookMarketplaceProductSearch(
        cast(ApifyFacebookMarketplaceClient, fake),
        clock=lambda: COLLECTED_AT,
    )
    service = SearchFacebookMarketplaceProducts(
        cast(FacebookMarketplaceProductSearchProvider, provider)
    )
    calls = {"count": 0}

    def facebook_runner(*, query: str, limit: int, city: str) -> object:
        calls["count"] += 1
        return service.execute(query, city, limit)

    log = ProviderCallLog()
    plan = plan_search(mode=MODE_SINGLE, platform=PLATFORM_FACEBOOK, query="mouse", limit=3)
    outcome = execute_market_search(
        plan,
        {
            PLATFORM_FACEBOOK: facebook_runner,
            PLATFORM_ALIBABA: lambda **kwargs: None,
            PLATFORM_ML: lambda **kwargs: None,
        },
        log=log,
    )
    result = outcome.results[PLATFORM_FACEBOOK]
    assert result.metrics.usable == 2
    assert result.metrics.free_price == 1
    assert calls["count"] == 1
    assert len(fake.calls) == 1
    assert outcome.retries == 0
    assert all("Free" not in (listing.formatted_amount or "") for listing in result.listings)


def test_partial_provider_error_keeps_other_results() -> None:
    log = ProviderCallLog()

    def facebook_error(**kwargs: object) -> dict[str, str]:
        raise RuntimeError("facebook down")

    runners = _runners(log)
    runners[PLATFORM_FACEBOOK] = facebook_error
    outcome = execute_market_search(
        plan_search(mode=MODE_MULTI, query="mouse", limit=3),
        runners,
        log=log,
    )
    assert PLATFORM_ALIBABA in outcome.results
    assert PLATFORM_ML in outcome.results
    assert PLATFORM_FACEBOOK in outcome.errors
    assert PLATFORM_FACEBOOK not in outcome.results
    assert outcome.retries == 0


def test_stale_generation_does_not_overwrite_newer_search() -> None:
    state = TrackerState()
    state.search_generation = 2
    state.alibaba_query = "headphones"
    state.alibaba_limit = 3
    state._finalize_alibaba_search(
        request_query="mouse",
        request_limit=3,
        rows=[AlibabaResultRow(title="stale mouse", product_id="old")],
        ui_status=UI_SUCCESS,
        request_generation=1,
    )
    assert state.alibaba_results == []
    assert all(row.title != "stale mouse" for row in state.alibaba_results)


def _bind_comparable_context(state: TrackerState, product_id: str, title: str) -> None:
    from bera_price_tracker.gui import services

    state.alibaba_query = "mouse"
    state.alibaba_results = [AlibabaResultRow(product_id=product_id, title=title)]
    state.prepare_facebook_comparables_from_alibaba_result(product_id)
    state._prepare_ml_comparables(
        external_id=product_id,
        title=title,
        supplier="Supplier",
        supplier_price="$4.00",
        currency="USD",
    )
    state.facebook_product_association_product_id = product_id
    state.ml_association_product_id = product_id
    state.facebook_product_last_search_query = "mouse"
    state.ml_last_search_query = (
        services.suggest_mercadolibre_query(
            current_query="",
            fallback_query="mouse",
        )
        or "mouse"
    )


def test_scoped_search_detaches_comparable_context_and_keeps_session_neutral(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bera_price_tracker.gui import services

    monkeypatch.setattr(services, "product_translator_is_configured", lambda: False)
    state = TrackerState()
    _bind_comparable_context(state, "P-OLD", "Old mouse")
    assert state.facebook_product_has_alibaba_context is True
    assert state.ml_has_alibaba_context is True
    assert state._facebook_product_active_id() == "P-OLD"
    assert state._ml_active_search_product_id() == "P-OLD"

    plan = plan_search(mode=MODE_MULTI, query="headphones", limit=3)
    state._prepare_scoped_search(plan)

    assert state.facebook_product_has_alibaba_context is False
    assert state.ml_has_alibaba_context is False
    assert state._facebook_product_active_id() == ""
    assert state._ml_active_search_product_id() == ""
    assert state.facebook_product_association_product_id == ""
    assert state.ml_association_product_id == ""
    assert state.facebook_product_alibaba_context == {}
    assert state.ml_alibaba_context == {}
    assert state.ml_query == "headphones"
    assert state.ml_query_origin == services.ML_QUERY_ORIGIN_USER
    assert state.ml_results_from_generic_session is True

    state._finalize_facebook_product_search(
        product_id="",
        query="headphones",
        city=state.facebook_product_city,
        rows=[FacebookProductResultRow(title="session facebook", relevance_value=80)],
        ui_status=UI_SUCCESS,
    )
    state._finalize_mercadolibre_search(
        search_product_id="",
        query="headphones",
        rows=[MercadoLibreResultRow(title="session ml", relevance_value=70)],
        ui_status=UI_SUCCESS,
    )
    state.alibaba_results = [
        AlibabaResultRow(
            product_id="P-OLD",
            title="Old mouse",
            score_value=90,
            score="90",
        )
    ]
    state.alibaba_ui_status = UI_SUCCESS

    assert state.facebook_product_association_product_id == ""
    assert state.ml_association_product_id == ""
    assert state.ml_show_alibaba_association is False
    assert state.facebook_product_show_provenance is False
    matching = [row for row in state.comparison_rows if row.product_id == "P-OLD"]
    assert matching
    assert matching[0].facebook_has_listing is False
    assert matching[0].ml_has_listing is False


def test_nueva_busqueda_detaches_alibaba_comparable_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bera_price_tracker.gui import services

    monkeypatch.setattr(services, "product_translator_is_configured", lambda: False)
    state = TrackerState()
    _bind_comparable_context(state, "P-OLD", "Old mouse")
    state.set_ml_query("consulta usuario de A")
    generation = state.facebook_product_translation_generation
    ml_generation = state.ml_translation_generation
    state.start_new_search()
    assert state.facebook_product_has_alibaba_context is False
    assert state.ml_has_alibaba_context is False
    assert state._facebook_product_active_id() == ""
    assert state._ml_active_search_product_id() == ""
    assert state.facebook_product_association_product_id == ""
    assert state.ml_association_product_id == ""
    assert state.ml_query == ""
    assert state.ml_query_origin == ""
    assert state.ml_results_from_generic_session is False
    assert state.facebook_product_translation_generation == generation + 1
    assert state.ml_translation_generation == ml_generation + 1


def test_detached_ml_user_query_is_not_reused_for_later_alibaba_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bera_price_tracker.gui import services

    monkeypatch.setattr(services, "product_translator_is_configured", lambda: False)
    state = TrackerState()
    query_a = "consulta usuario de A"
    _bind_comparable_context(state, "P-A", "Product A mouse")
    state.set_ml_query(query_a)
    assert state.ml_query == query_a
    assert state.ml_query_origin == services.ML_QUERY_ORIGIN_USER
    assert state.ml_alibaba_context["external_id"] == "P-A"

    calls = {"alibaba": 0, "facebook": 0, "ml": 0}

    def run_alibaba(*_args: object, **_kwargs: object) -> dict[str, object]:
        calls["alibaba"] += 1
        return {
            "results": [
                {
                    "title": "Product B headphones",
                    "product_id": "P-B",
                    "score_value": 90,
                }
            ],
            "summary": {"resultados": "1"},
            "stats_raw": {},
            "ui_status": UI_SUCCESS,
        }

    def run_facebook(*_args: object, **_kwargs: object) -> dict[str, object]:
        calls["facebook"] += 1
        raise AssertionError("Alibaba-only search must not call Facebook")

    def run_ml(*_args: object, **_kwargs: object) -> dict[str, object]:
        calls["ml"] += 1
        raise AssertionError("Alibaba-only search must not call Mercado Libre")

    monkeypatch.setattr(services, "run_alibaba_search", run_alibaba)
    monkeypatch.setattr(services, "run_facebook_product_search", run_facebook)
    monkeypatch.setattr(services, "run_mercadolibre_search", run_ml)

    state.search_mode = MODE_SINGLE
    state.search_platform = PLATFORM_ALIBABA
    state.search_query = "headphones"
    state.search_limit = 3
    asyncio.run(cast(Any, TrackerState.run_scoped_search).fn(state))

    assert calls == {"alibaba": 1, "facebook": 0, "ml": 0}
    assert state.ml_has_alibaba_context is False
    assert state.ml_alibaba_context == {}
    assert state.ml_query == ""
    assert state.ml_query_origin == ""
    assert state.ml_query != query_a
    assert state.ml_results_from_generic_session is False

    opening = state.prepare_ml_comparables_from_alibaba_result("P-B")
    assert opening is TrackerState.translate_selected_alibaba_title
    assert state.ml_alibaba_context["external_id"] == "P-B"
    assert state.ml_query != query_a
    assert query_a not in state.ml_query
    assert state.ml_query == "headphones"
    assert state.ml_query_origin == services.ML_QUERY_ORIGIN_FALLBACK
    assert state.ml_association_product_id == ""
    assert state.ml_last_search_query != query_a
    assert state.ml_results_from_generic_session is False

    state._finalize_product_translation(
        product_id="P-B",
        title=state.ml_alibaba_context["title"],
        generation=state.ml_translation_generation,
        translated_title="Audífonos B",
        search_query="audifonos producto B",
    )
    assert state.ml_query != query_a
    assert state.ml_query == "audifonos producto B"
    assert state.ml_query_origin == services.ML_QUERY_ORIGIN_GENERATED


def test_current_product_user_query_is_not_overwritten_by_translation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bera_price_tracker.gui import services

    monkeypatch.setattr(services, "product_translator_is_configured", lambda: False)
    state = TrackerState()
    _bind_comparable_context(state, "P-A", "Product A mouse")
    state.set_ml_query("consulta usuario de A")
    state.prepare_ml_comparables_from_alibaba_result("P-A")
    assert state.ml_query == "consulta usuario de A"
    assert state.ml_query_origin == services.ML_QUERY_ORIGIN_USER
    state._finalize_product_translation(
        product_id="P-A",
        title=state.ml_alibaba_context["title"],
        generation=state.ml_translation_generation,
        translated_title="Producto A",
        search_query="consulta traducida de A",
    )
    assert state.ml_query == "consulta usuario de A"
    assert state.ml_query_origin == services.ML_QUERY_ORIGIN_USER
    assert state.ml_query != "consulta traducida de A"


def test_late_standalone_alibaba_search_does_not_repopulate_cleared_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bera_price_tracker.gui import services

    state = TrackerState()

    def run_search(*_args: object, **_kwargs: object) -> dict[str, object]:
        state.start_new_search()
        return {
            "results": [{"title": "stale mouse", "product_id": "old"}],
            "summary": {},
            "stats_raw": {},
            "ui_status": UI_SUCCESS,
        }

    monkeypatch.setattr(services, "run_alibaba_search", run_search)
    state.alibaba_query = "mouse"
    state.alibaba_limit = 3
    asyncio.run(cast(Any, TrackerState.search_alibaba).fn(state))
    assert state.alibaba_results == []
    assert all(row.title != "stale mouse" for row in state.alibaba_results)
    assert state.alibaba_ui_status != UI_SUCCESS


def test_late_standalone_facebook_search_does_not_repopulate_cleared_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bera_price_tracker.gui import services

    state = TrackerState()

    def run_search(*_args: object, **_kwargs: object) -> dict[str, object]:
        state.start_new_search()
        return {
            "results": [{"title": "stale facebook", "external_id": "fb-old"}],
            "statistics": [],
            "summary": {},
            "ui_status": UI_SUCCESS,
        }

    monkeypatch.setattr(services, "run_facebook_product_search", run_search)
    state.facebook_product_query = "mouse"
    asyncio.run(cast(Any, TrackerState.search_facebook_products).fn(state))
    assert state.facebook_product_results == []
    assert all(row.title != "stale facebook" for row in state.facebook_product_results)
    assert state.facebook_product_ui_status != UI_SUCCESS
    assert state.facebook_product_association_product_id == ""
    assert state.facebook_product_provenance == {}
    assert state.facebook_product_is_loading is False
    assert state.facebook_product_error == ""


def test_late_standalone_facebook_error_does_not_repopulate_cleared_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bera_price_tracker.gui import services

    state = TrackerState()

    def run_search(*_args: object, **_kwargs: object) -> dict[str, object]:
        state.start_new_search()
        raise RuntimeError("stale facebook")

    monkeypatch.setattr(services, "run_facebook_product_search", run_search)
    state.facebook_product_query = "mouse"
    asyncio.run(cast(Any, TrackerState.search_facebook_products).fn(state))
    assert state.facebook_product_results == []
    assert state.facebook_product_ui_status == UI_INITIAL
    assert state.facebook_product_error == ""
    assert state.facebook_product_association_product_id == ""
    assert state.facebook_product_provenance == {}
    assert state.facebook_product_is_loading is False


def test_late_standalone_ml_search_does_not_repopulate_cleared_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bera_price_tracker.gui import services

    state = TrackerState()

    def run_search(*_args: object, **_kwargs: object) -> dict[str, object]:
        state.start_new_search()
        return {
            "results": [{"title": "stale ml", "external_id": "MLV-OLD", "price_raw": "9.00"}],
            "summary": {"comparables": "1"},
            "ui_status": UI_SUCCESS,
        }

    monkeypatch.setattr(services, "run_mercadolibre_search", run_search)
    state.ml_query = "mouse"
    asyncio.run(cast(Any, TrackerState.search_mercadolibre).fn(state))
    assert state.ml_results == []
    assert all(row.title != "stale ml" for row in state.ml_results)
    assert state.ml_ui_status != UI_SUCCESS
    assert state.ml_association_product_id == ""
    assert state.ml_is_loading is False
    assert state.ml_error == ""
    assert state.ml_has_comparison is False
    assert state.ml_comparison == {}


def test_late_standalone_ml_error_does_not_repopulate_cleared_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bera_price_tracker.gui import services

    state = TrackerState()

    def run_search(*_args: object, **_kwargs: object) -> dict[str, object]:
        state.start_new_search()
        raise RuntimeError("stale ml")

    monkeypatch.setattr(services, "run_mercadolibre_search", run_search)
    state.ml_query = "mouse"
    asyncio.run(cast(Any, TrackerState.search_mercadolibre).fn(state))
    assert state.ml_results == []
    assert state.ml_ui_status == UI_INITIAL
    assert state.ml_error == ""
    assert state.ml_association_product_id == ""
    assert state.ml_is_loading is False
    assert state.ml_has_comparison is False


def test_generic_session_ml_compare_does_not_use_old_landed_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bera_price_tracker.gui import services

    monkeypatch.setattr(services, "product_translator_is_configured", lambda: False)
    state = TrackerState()
    _bind_comparable_context(state, "P-OLD", "Old mouse")
    state.alibaba_landed_has_result = True
    state.alibaba_landed_result = {
        "landed_cost_per_unit_raw": "6.43",
        "landed_cost_per_unit": "$6.43",
        "currency": "USD",
    }
    state.alibaba_landed_product_id = "P-OLD"

    plan = plan_search(mode=MODE_MULTI, query="headphones", limit=3)
    state.search_session_active = True
    state.search_session_query = plan.query
    state._prepare_scoped_search(plan)
    state._finalize_mercadolibre_search(
        search_product_id="",
        query="headphones",
        rows=[
            MercadoLibreResultRow(
                title="session headphones",
                price_raw="9.00",
                currency="USD",
                relevance_value=80,
            )
        ],
        ui_status=UI_SUCCESS,
    )

    assert state.ml_has_alibaba_context is False
    assert state.ml_association_product_id == ""
    assert state.ml_results_from_generic_session is True
    assert state.alibaba_landed_has_result is True
    assert state.alibaba_landed_product_id == "P-OLD"
    assert state.alibaba_landed_result["landed_cost_per_unit_raw"] == "6.43"

    state.compare_ml_with_landed_cost()
    assert state.ml_comparison.get("landed", "") == ""
    assert state.ml_comparison.get("comparable") == "0"
    assert state.ml_comparison.get("conservative_profit", "") == ""
    assert state.ml_comparison.get("typical_profit", "") == ""
    assert state.ml_comparison.get("high_profit", "") == ""
    assert "6.43" not in str(state.ml_comparison)
    assert state.ml_show_alibaba_association is False
    association = state.ml_alibaba_association
    assert association["visible"] == "0"
    assert association["has_profitability"] == "0"
    assert association["landed"] == ""
    assert state.alibaba_landed_has_result is True
    assert state.alibaba_landed_product_id == "P-OLD"


def test_run_scoped_search_generic_session_does_not_inherit_old_alibaba_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bera_price_tracker.gui import services

    monkeypatch.setattr(services, "product_translator_is_configured", lambda: False)
    state = TrackerState()
    _bind_comparable_context(state, "P-OLD", "Old mouse")
    state.alibaba_landed_has_result = True
    state.alibaba_landed_result = {
        "landed_cost_per_unit_raw": "6.43",
        "landed_cost_per_unit": "$6.43",
        "currency": "USD",
    }
    state.alibaba_landed_product_id = "P-OLD"
    calls = {"alibaba": 0, "facebook": 0, "ml": 0}

    def run_alibaba(*_args: object, **_kwargs: object) -> dict[str, object]:
        calls["alibaba"] += 1
        return {
            "results": [{"title": "session alibaba", "product_id": "P-NEW", "score_value": 80}],
            "summary": {"resultados": "1"},
            "stats_raw": {},
            "ui_status": UI_SUCCESS,
        }

    def run_facebook(*_args: object, **_kwargs: object) -> dict[str, object]:
        calls["facebook"] += 1
        return {
            "results": [{"title": "session facebook", "external_id": "fb-new"}],
            "statistics": [],
            "summary": {"usable": "1"},
            "ui_status": UI_SUCCESS,
        }

    def run_ml(*_args: object, **_kwargs: object) -> dict[str, object]:
        calls["ml"] += 1
        return {
            "results": [
                {
                    "title": "session ml",
                    "external_id": "MLV-NEW",
                    "price_raw": "9.00",
                    "currency": "USD",
                    "relevance_value": 80,
                }
            ],
            "summary": {"comparables": "1"},
            "ui_status": UI_SUCCESS,
        }

    monkeypatch.setattr(services, "run_alibaba_search", run_alibaba)
    monkeypatch.setattr(services, "run_facebook_product_search", run_facebook)
    monkeypatch.setattr(services, "run_mercadolibre_search", run_ml)

    state.search_mode = MODE_MULTI
    state.search_query = "headphones"
    state.search_limit = 3
    asyncio.run(cast(Any, TrackerState.run_scoped_search).fn(state))

    assert calls == {"alibaba": 1, "facebook": 1, "ml": 1}
    assert state.facebook_product_association_product_id == ""
    assert state.ml_association_product_id == ""
    assert "P-OLD" not in str(state.facebook_product_provenance)
    assert state.facebook_product_provenance.get("external_id", "") != "P-OLD"
    assert state.ml_show_alibaba_association is False
    assert state.facebook_product_show_provenance is False
    assert state.ml_has_alibaba_context is False
    assert all(row.product_id != "P-OLD" for row in state.alibaba_results)
    matching_old = [row for row in state.comparison_rows if row.product_id == "P-OLD"]
    assert matching_old == []
    for row in state.comparison_rows:
        assert row.product_id != "P-OLD"
        if row.facebook_has_listing or row.ml_has_listing:
            assert row.product_id != "P-OLD"

    assert state.alibaba_landed_has_result is True
    assert state.alibaba_landed_product_id == "P-OLD"
    assert state.ml_results_from_generic_session is True
    state.compare_ml_with_landed_cost()
    assert "6.43" not in str(state.ml_comparison)
    assert state.ml_comparison.get("landed", "") == ""
    assert state.ml_comparison.get("comparable") == "0"
    association = state.ml_alibaba_association
    assert association["visible"] == "0"
    assert association["has_profitability"] == "0"
    assert association["landed"] == ""


def test_standalone_ml_search_after_generic_session_can_use_retained_landed_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bera_price_tracker.gui import services

    monkeypatch.setattr(services, "product_translator_is_configured", lambda: False)
    state = TrackerState()
    _bind_comparable_context(state, "P-OLD", "Old mouse")
    state.alibaba_landed_has_result = True
    state.alibaba_landed_result = {
        "landed_cost_per_unit_raw": "6.43",
        "landed_cost_per_unit": "$6.43",
        "currency": "USD",
    }
    state.alibaba_landed_product_id = "P-OLD"

    plan = plan_search(mode=MODE_MULTI, query="headphones", limit=3)
    state.search_session_active = True
    state.search_session_query = plan.query
    state._prepare_scoped_search(plan)
    state._finalize_mercadolibre_search(
        search_product_id="",
        query="headphones",
        rows=[
            MercadoLibreResultRow(
                title="session headphones",
                price_raw="9.00",
                currency="USD",
                relevance_value=80,
            )
        ],
        ui_status=UI_SUCCESS,
    )
    assert state.ml_results_from_generic_session is True
    assert state.search_session_active is True
    state.compare_ml_with_landed_cost()
    assert state.ml_comparison.get("landed", "") == ""
    assert "6.43" not in str(state.ml_comparison)

    calls = {"ml": 0}

    def run_ml(*_args: object, **_kwargs: object) -> dict[str, object]:
        calls["ml"] += 1
        return {
            "results": [
                {
                    "title": "standalone headphones",
                    "external_id": "MLV-STANDALONE",
                    "price_raw": "9.00",
                    "currency": "USD",
                    "relevance_value": 80,
                }
            ],
            "summary": {"comparables": "1"},
            "ui_status": UI_SUCCESS,
        }

    monkeypatch.setattr(services, "run_mercadolibre_search", run_ml)
    state.ml_query = "standalone headphones"
    asyncio.run(cast(Any, TrackerState.search_mercadolibre).fn(state))

    assert calls == {"ml": 1}
    assert state.search_session_active is True
    assert state.ml_results_from_generic_session is False
    assert state.ml_has_alibaba_context is False
    assert state.ml_association_product_id == ""
    assert state.alibaba_landed_has_result is True
    assert state.alibaba_landed_product_id == "P-OLD"
    state.compare_ml_with_landed_cost()
    assert "6.43" in str(state.ml_comparison)
    assert state.ml_comparison.get("landed", "") != ""
    assert state.ml_has_comparison is True


def test_explicit_alibaba_ml_workflow_does_not_inherit_generic_session_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bera_price_tracker.gui import services

    monkeypatch.setattr(services, "product_translator_is_configured", lambda: False)
    state = TrackerState()
    plan = plan_search(mode=MODE_MULTI, query="headphones", limit=3)
    state.search_session_active = True
    state._prepare_scoped_search(plan)
    state._finalize_mercadolibre_search(
        search_product_id="",
        query="headphones",
        rows=[MercadoLibreResultRow(title="session ml", relevance_value=70)],
        ui_status=UI_SUCCESS,
    )
    assert state.ml_results_from_generic_session is True
    assert state.search_session_active is True

    state.alibaba_results = [
        AlibabaResultRow(product_id="P-B", title="Product B headphones", score_value=90, score="90")
    ]
    state.prepare_ml_comparables_from_alibaba_result("P-B")
    assert state.search_session_active is True
    assert state.ml_results_from_generic_session is False
    assert state.ml_has_alibaba_context is True
    assert state.ml_alibaba_context["external_id"] == "P-B"


def test_unsupported_plan_limit_never_reaches_runners() -> None:
    log = ProviderCallLog()
    with pytest.raises(ValueError, match="1, 3 o 5"):
        plan_search(mode=MODE_MULTI, query="mouse", limit=10)
    assert log.calls == []
    state = TrackerState()
    state.search_query = "mouse"
    state.set_search_limit(10)
    assert state.search_error == SEARCH_LIMIT_ERROR
    assert state.search_limit == DEFAULT_SEARCH_LIMIT


def _gui_python_sources() -> list[Path]:
    root = Path(__file__).resolve().parents[2] / "src/bera_price_tracker/gui"
    return sorted(root.rglob("*.py"))


def test_brand_assets_exist_locally() -> None:
    alibaba, facebook, mercado_libre = brands.local_brand_files()
    assert alibaba.is_file()
    assert facebook.is_file()
    assert mercado_libre.is_file()
    assert mercado_libre.name == "mercado-libre.svg"
    for path in (alibaba, facebook, mercado_libre):
        text = path.read_text(encoding="utf-8")
        assert text.lstrip().startswith("<svg")
        lowered = text.casefold()
        assert "jsdelivr" not in lowered
        assert "thesvg.org" not in lowered
        assert "simpleicons.org" not in lowered
        assert 'href="http' not in lowered


def test_brand_component_specs_cover_three_marketplaces() -> None:
    alibaba = brands.brand_spec(PLATFORM_ALIBABA)
    facebook = brands.brand_spec(PLATFORM_FACEBOOK)
    ml = brands.brand_spec(PLATFORM_ML)
    assert alibaba.kind == "image" and alibaba.src == "/brands/alibaba.svg"
    assert facebook.kind == "image" and facebook.src == "/brands/facebook.svg"
    assert ml.kind == "image" and ml.src == "/brands/mercado-libre.svg"
    assert ml.label == "Mercado Libre"
    assert ml.local_path is not None and ml.local_path.is_file()


def test_brand_specs_have_no_runtime_cdn() -> None:
    for spec in brands.BRANDS.values():
        assert spec.kind == "image"
        assert spec.src.startswith("/brands/")
        assert spec.src.endswith(".svg")
        assert brands.brand_uses_runtime_cdn(spec) is False
        assert "simpleicons.org" not in spec.src
        assert "thesvg" not in spec.src.casefold()
        assert "jsdelivr" not in spec.src.casefold()
        assert not spec.src.startswith("http://")
        assert not spec.src.startswith("https://")


def test_no_fabricated_mercadolibre_logo_file() -> None:
    source = (brands._ASSETS_ROOT.parent.parent / "src/bera_price_tracker/gui/brands.py").read_text(
        encoding="utf-8"
    )
    assert "handshake" not in source.casefold()
    assert "<svg" not in source.casefold()
    attribution = (brands._ASSETS_ROOT / "ATTRIBUTION.md").read_text(encoding="utf-8")
    lowered = attribution.casefold()
    assert "thesvg" in lowered
    assert "https://thesvg.org/icon/mercado-libre" in lowered
    assert "license reported by source: mit" in lowered
    assert "does not grant trademark rights" in lowered
    assert "trademark of its respective owner" in lowered
    assert "marketplace identification only" in lowered
    assert "not an official asset obtained from mercado libre" in lowered
    assert "text only" not in lowered
    svg = (brands._ASSETS_ROOT / "mercado-libre.svg").read_text(encoding="utf-8")
    assert "#2D3277" in svg and "#FFE600" in svg


def test_unrelated_marketplace_results_stay_on_separate_rows() -> None:
    rows = comparison.build_comparison_rows(
        facebook_rows=[FacebookProductResultRow(title="mouse", relevance_value=80)],
        ml_rows=[MercadoLibreResultRow(title="headphones", relevance_value=70)],
        facebook_status=UI_SUCCESS,
        ml_status=UI_SUCCESS,
    )
    combined = [row for row in rows if row["facebook_has_listing"] and row["ml_has_listing"]]
    assert combined == []


def test_cta_and_callout_are_maxima_not_guarantees() -> None:
    assert search_scope.cta_label(MODE_MULTI) == "Buscar y comparar"
    assert search_scope.cta_label(MODE_SINGLE, PLATFORM_FACEBOOK) == "Buscar en Facebook"
    primary, secondary = search_scope.search_callout(3)
    assert "hasta 3" in primary.casefold()
    assert "garant" not in primary.casefold()
    assert "precio válido" in secondary


def test_tracker_state_defaults_and_progress() -> None:
    state = TrackerState()
    assert state.search_mode == MODE_MULTI
    assert state.search_limit == 3
    assert state.search_query == ""
    assert state.search_cta_label == "Buscar y comparar"
    state.alibaba_ui_status = UI_ERROR
    state.facebook_product_ui_status = UI_SUCCESS
    state.facebook_product_summary = {"usable": "2"}
    state.ml_ui_status = UI_SUCCESS
    state.ml_summary = {"comparables": "3"}
    details = [row.detail for row in state.search_progress_rows]
    assert "Error" in details
    assert "2 resultados válidos" in details


def test_unknown_brand_and_progress_labels() -> None:
    with pytest.raises(ValueError, match="unknown marketplace brand"):
        brands.brand_spec("amazon")
    assert search_scope.progress_label("LOADING") == "Buscando..."
    assert search_scope.progress_label("SUCCESS", "3") == "3 resultados"
    assert search_scope.progress_label("EMPTY") == "Sin resultados"
    assert search_scope.progress_label("INITIAL") == "Sin búsqueda"


def test_plan_search_rejects_blank_query_and_bad_mode() -> None:
    with pytest.raises(ValueError, match="producto"):
        plan_search(mode=MODE_MULTI, query="  ", limit=3)
    with pytest.raises(ValueError, match="comparar"):
        search_scope.providers_for("other")
    with pytest.raises(ValueError, match="Selecciona"):
        search_scope.providers_for(MODE_SINGLE, "amazon")


def test_summary_cards_show_loading_and_error() -> None:
    from bera_price_tracker.gui import marketplace_summary

    cards = marketplace_summary.build_marketplace_summaries(
        alibaba_ui_status="LOADING",
        alibaba_summary={},
        facebook_ui_status="ERROR",
        facebook_summary={},
        ml_ui_status="LOADING",
        ml_summary={},
    )
    assert cards[0]["status_label"] == "Buscando..."
    assert cards[1]["status_label"] == "Error"
    assert cards[2]["status_label"] == "Buscando..."
    assert cards[0]["minimum"] == "—"
    errored = marketplace_summary.facebook_summary_card(
        ui_status="ERROR",
        summary={},
        error="No se pudo consultar Facebook Marketplace.",
    )
    assert errored["status"] == "error"
    assert errored["note"] == "No se pudo consultar Facebook Marketplace."


def test_prepare_scoped_search_clears_selected_providers() -> None:
    state = TrackerState()
    state.alibaba_results = [AlibabaResultRow(title="old")]
    state.facebook_product_results = [FacebookProductResultRow(title="old fb")]
    state.ml_results = [MercadoLibreResultRow(title="old ml")]
    plan = plan_search(mode=MODE_MULTI, query="headphones", limit=3)
    state._prepare_scoped_search(plan)
    assert state.alibaba_query == "headphones"
    assert state.alibaba_results == []
    assert state.facebook_product_results == []
    assert state.ml_results == []
    assert state.alibaba_ui_status == "LOADING"
    assert state.facebook_product_ui_status == "LOADING"
    assert state.ml_ui_status == "LOADING"
    assert state.search_is_busy is True


def test_payload_helpers_and_row_mapping() -> None:
    state = TrackerState()
    assert state._payload_maps({"results": "nope"}, "results") == []
    assert state._payload_int({"score_value": "x"}, "score_value") == 0
    rows = state._alibaba_rows_from_payload(
        {"results": [{"title": "Mouse", "product_id": "a1", "score_value": "7"}]}
    )
    assert rows[0].title == "Mouse"
    assert rows[0].score_value == 7
    fb_rows, stats = state._facebook_rows_from_payload(
        {
            "results": [{"title": "FB", "relevance_value": "4"}],
            "statistics": [{"currency": "USD", "count": "1"}],
        }
    )
    assert fb_rows[0].title == "FB"
    assert stats[0].currency == "USD"
    ml_rows = state._ml_rows_from_payload({"results": [{"title": "ML"}]})
    assert ml_rows[0].title == "ML"


def test_search_setters_and_single_platform_busy_flag() -> None:
    state = TrackerState()
    state.set_search_query("mouse")
    state.set_search_mode_single()
    state.set_search_platform_facebook()
    state.set_search_limit("3")
    assert state.search_query == "mouse"
    assert state.search_mode == MODE_SINGLE
    assert state.search_platform == PLATFORM_FACEBOOK
    assert state.search_limit == 3
    assert state.search_cta_label == "Buscar en Facebook"
    state.facebook_product_is_loading = True
    assert state.search_is_busy is True
    state.facebook_product_is_loading = False
    state.alibaba_is_loading = True
    assert state.search_is_busy is False


def test_running_fixture_keeps_setup_and_not_complete() -> None:
    state = TrackerState()
    state.apply_running_search_fixture()
    assert state.search_session_phase == "RUNNING"
    assert state.search_shows_setup is True
    assert state.search_shows_results is False
    assert (
        search_session.completion_status_copy(state.search_session_phase)["label"] == "Buscando..."
    )
    assert state.search_cta_label == "Buscar y comparar"


def test_partial_fixture_preserves_success_and_error() -> None:
    state = TrackerState()
    state.apply_partial_search_fixture()
    assert state.alibaba_ui_status == UI_SUCCESS
    assert state.facebook_product_ui_status == UI_ERROR
    assert state.ml_ui_status == UI_SUCCESS
    assert state.facebook_product_results == []
    assert state.ml_results[0].title == "Fixture ML"
    assert state.ml_results[0].relevance_value == 90
    assert state.search_session_phase == "PARTIAL"
    assert state.search_shows_results is True
    assert "completada" in search_session.completion_status_copy("PARTIAL")["label"].casefold()
    assert "completada" in search_session.completion_status_copy("COMPLETE")["label"].casefold()
    assert search_session.completion_status_copy("COMPLETE")["tone"] == "success"


def test_setup_state_before_search() -> None:
    from bera_price_tracker.gui.search_scope import SEARCH_MODE_LAYOUT, SEARCH_SETUP_TITLE

    state = TrackerState()
    assert state.search_session_phase == "IDLE"
    assert state.search_shows_setup is True
    assert state.search_shows_results is False
    assert SEARCH_MODE_LAYOUT == "two-columns"
    assert SEARCH_SETUP_TITLE == "Buscar productos"
    assert state.search_limit == DEFAULT_SEARCH_LIMIT
    css = (Path(__file__).resolve().parents[2] / "assets" / "bera.css").read_text(encoding="utf-8")
    assert ".bera-mode-row" in css
    assert "flex-direction: row" in css
    setup_source = (
        Path(__file__).resolve().parents[2]
        / "src/bera_price_tracker/gui/components/search_scope.py"
    ).read_text(encoding="utf-8")
    assert 'class_name="bera-mode-row"' in setup_source
    assert setup_source.count("marketplace_brand_alibaba") >= 2
    assert setup_source.count("marketplace_brand_facebook") >= 2
    assert setup_source.count("marketplace_brand_ml") >= 2


def test_summary_and_table_headers_use_brand_ids() -> None:
    from bera_price_tracker.gui import marketplace_summary

    cards = marketplace_summary.build_marketplace_summaries(
        alibaba_ui_status="SUCCESS",
        alibaba_summary={"resultados": "2", "minimo": "USD 3.00", "maximo": "USD 7.00"},
        alibaba_rows=[
            AlibabaResultRow(title="a", review_score="4.8", moq="10", supplier_name="Acme")
        ],
        facebook_ui_status="SUCCESS",
        facebook_summary={"usable": "1"},
        facebook_statistics=[],
        ml_ui_status="SUCCESS",
        ml_summary={"comparable_count": "1", "currency": "USD"},
        ml_rows=[MercadoLibreResultRow(title="ml", seller_name="Shop")],
    )
    assert [card["platform_id"] for card in cards] == [
        PLATFORM_ALIBABA,
        PLATFORM_FACEBOOK,
        PLATFORM_ML,
    ]
    assert cards[0]["rating_available"] is False
    assert cards[0]["rating_filled"] == 0
    assert cards[1]["rating_available"] is False
    assert cards[1]["rating_label"] == "Sin calificación"
    comparison_source = (
        Path(__file__).resolve().parents[2] / "src/bera_price_tracker/gui/components/comparison.py"
    ).read_text(encoding="utf-8")
    assert "marketplace_brand_alibaba" in comparison_source
    assert "marketplace_brand_facebook" in comparison_source
    assert "marketplace_brand_ml" in comparison_source
    results_source = (
        Path(__file__).resolve().parents[2]
        / "src/bera_price_tracker/gui/components/search_results.py"
    ).read_text(encoding="utf-8")
    assert "marketplace_brand_alibaba(size=16, show_name=False)" in results_source


def test_complete_search_green_and_nueva_busqueda_zero_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bera_price_tracker.gui import search_session, services

    calls: list[str] = []
    monkeypatch.setattr(
        services, "run_alibaba_search", lambda *args, **kwargs: calls.append("alibaba")
    )
    monkeypatch.setattr(
        services, "run_facebook_product_search", lambda *args, **kwargs: calls.append("facebook")
    )
    monkeypatch.setattr(
        services, "run_mercadolibre_search", lambda *args, **kwargs: calls.append("ml")
    )
    state = TrackerState()
    state.apply_complete_search_fixture()
    generation = state.search_generation
    assert state.search_session_phase == "COMPLETE"
    assert search_session.completion_status_copy(state.search_session_phase)["tone"] == "success"
    tracked = list(state.alibaba_tracked_rows)
    state.start_new_search()
    assert state.search_session_phase == "IDLE"
    assert state.search_shows_setup is True
    assert state.alibaba_results == []
    assert state.facebook_product_results == []
    assert state.ml_results == []
    assert state.alibaba_tracked_rows == tracked
    assert state.search_generation == generation + 1
    assert calls == []


def test_ratings_and_opportunity_never_invented() -> None:
    from bera_price_tracker.gui import search_session

    empty = search_session.seller_rating("")
    assert empty["available"] is False
    assert empty["filled"] == 0
    genuine = search_session.seller_rating("4.8")
    assert genuine["available"] is True
    assert genuine["label"] == "4.8/5"
    relevance_is_not_a_rating = search_session.seller_rating("90")
    assert relevance_is_not_a_rating["available"] is False
    gauge = search_session.opportunity_gauge(92, "92")
    assert gauge["available"] is True
    assert gauge["label"] == "Oportunidad Alibaba"
    assert search_session.opportunity_gauge(0, "")["available"] is False
    rows = comparison.build_comparison_rows(
        alibaba_rows=[
            AlibabaResultRow(title="mouse", score_value=88, score="88", review_score="4.2")
        ],
        alibaba_status=UI_SUCCESS,
    )
    assert rows[0]["opportunity_available"] is True
    assert rows[0]["opportunity_score"] == "88"
    assert rows[0]["alibaba_rating_available"] is True
    assert rows[0]["facebook_rating_available"] is False


def test_range_strip_and_boxplot_currency_safety() -> None:
    from bera_price_tracker.gui import marketplace_summary, search_session

    cards = marketplace_summary.build_marketplace_summaries(
        alibaba_ui_status="SUCCESS",
        alibaba_summary={
            "resultados": "2",
            "minimo": "USD 3.00",
            "maximo": "USD 7.20",
            "p25": "USD 3.50",
            "p75": "USD 6.00",
        },
        facebook_ui_status="SUCCESS",
        facebook_summary={"usable": "1"},
        ml_ui_status="INITIAL",
        ml_summary={},
    )
    assert "USD 3.00" in cards[0]["range"] or cards[0]["range"] != "—"
    usd = search_session.boxplot_track(
        platform=PLATFORM_ALIBABA,
        minimum="3",
        p25="3.5",
        median="5",
        p75="6",
        maximum="7",
        currency="USD",
        basis="USD",
    )
    ves = search_session.boxplot_track(
        platform=PLATFORM_FACEBOOK,
        minimum="20",
        p25="25",
        median="30",
        p75="40",
        maximum="50",
        currency="VES",
        basis="VES",
    )
    aligned = search_session.align_boxplot_tracks([usd, ves])
    assert aligned[0]["available"] == "1"
    assert aligned[1]["available"] == ""
    insight = search_session.quick_insight(
        [
            {
                **usd,
                "platform": PLATFORM_ALIBABA,
                "label": "Alibaba",
                "median": "5",
            },
            {
                **usd,
                "platform": PLATFORM_ML,
                "label": "Mercado Libre",
                "median": "10",
                "available": "1",
            },
        ]
    )
    assert "mediana" in insight.casefold()
    assert "35%" in insight or "50%" in insight


def test_search_duration_and_stale_session_clear() -> None:
    from bera_price_tracker.gui import search_session

    assert search_session.format_session_duration(12400) == "12.4 s"
    assert "min" in search_session.format_session_duration(72000)
    state = TrackerState()
    state.apply_complete_search_fixture()
    assert state.search_elapsed_ms > 0
    state.facebook_product_results = [FacebookProductResultRow(title="old")]
    plan = plan_search(mode=MODE_SINGLE, platform=PLATFORM_ALIBABA, query="headphones", limit=3)
    state._prepare_scoped_search(plan)
    assert state.alibaba_results == []
    assert state.facebook_product_results == []
    assert state.facebook_product_ui_status == "INITIAL"
    state.start_new_search()
    assert state.facebook_product_results == []
    assert state.search_session_phase == "IDLE"


def test_fixture_controls_hidden_without_env() -> None:
    from bera_price_tracker.gui.search_session import should_render_search_fixtures

    assert should_render_search_fixtures({}) is False
    assert should_render_search_fixtures({"BERA_UI_FIXTURES": "1"}) is True
    source = (
        Path(__file__).resolve().parents[2]
        / "src/bera_price_tracker/gui/components/search_scope.py"
    ).read_text(encoding="utf-8")
    assert "should_render_search_fixtures" in source


def test_platform_logo_component_has_no_cdn() -> None:
    from bera_price_tracker.gui.components import brands as brand_components

    source = Path(brand_components.__file__).read_text(encoding="utf-8")
    assert "https://" not in source
    assert "simpleicons.org" not in source
    assert "thesvg" not in source.casefold()
    assert "jsdelivr" not in source.casefold()
    assert "marketplace_brand(" in source
    assert "PLATFORM_ALIBABA" in source
    assert "PLATFORM_FACEBOOK" in source
    assert "PLATFORM_ML" in source
    assert "object_fit" in source


def test_shared_brand_component_covers_all_marketplace_surfaces() -> None:
    from bera_price_tracker.gui.components import brands as brand_components

    component_source = Path(brand_components.__file__).read_text(encoding="utf-8")
    assert "def marketplace_brand(" in component_source
    assert "def marketplace_brand_alibaba" in component_source
    assert "def marketplace_brand_facebook" in component_source
    assert "def marketplace_brand_ml" in component_source
    summary_source = (
        Path(__file__).resolve().parents[2] / "src/bera_price_tracker/gui/components/summary.py"
    ).read_text(encoding="utf-8")
    assert "marketplace_brand_alibaba()" in summary_source
    assert "marketplace_brand_facebook()" in summary_source
    assert "marketplace_brand_ml()" in summary_source
    comparison_source = (
        Path(__file__).resolve().parents[2] / "src/bera_price_tracker/gui/components/comparison.py"
    ).read_text(encoding="utf-8")
    assert "marketplace_brand_alibaba(size=16)" in comparison_source
    assert "marketplace_brand_facebook(size=16)" in comparison_source
    assert "marketplace_brand_ml(size=16)" in comparison_source
    results_source = (
        Path(__file__).resolve().parents[2]
        / "src/bera_price_tracker/gui/components/search_results.py"
    ).read_text(encoding="utf-8")
    assert "marketplace_brand_alibaba(size=16, show_name=False)" in results_source
    assert "marketplace_brand_facebook(size=16, show_name=False)" in results_source
    assert "marketplace_brand_ml(size=16, show_name=False)" in results_source
    setup_source = (
        Path(__file__).resolve().parents[2]
        / "src/bera_price_tracker/gui/components/search_scope.py"
    ).read_text(encoding="utf-8")
    assert "marketplace_brand_alibaba()" in setup_source
    assert "marketplace_brand_facebook()" in setup_source
    assert "marketplace_brand_ml()" in setup_source
    assert "marketplace_brand_alibaba(show_name=True)" in setup_source
    assert "marketplace_brand_facebook(show_name=True)" in setup_source
    assert "marketplace_brand_ml(show_name=True)" in setup_source
    for path in _gui_python_sources():
        text = path.read_text(encoding="utf-8").casefold()
        assert "thesvg.org" not in text
        assert "cdn.jsdelivr.net" not in text
        assert "@thesvg" not in text


def test_search_session_phase_duration_and_parsing_branches() -> None:
    assert (
        search_session.session_phase(
            session_active=False,
            providers=(PLATFORM_ALIBABA,),
            loading={PLATFORM_ALIBABA: False},
            statuses={PLATFORM_ALIBABA: "INITIAL"},
        )
        == "IDLE"
    )
    assert (
        search_session.session_phase(
            session_active=True,
            providers=(PLATFORM_ALIBABA,),
            loading={PLATFORM_ALIBABA: True},
            statuses={PLATFORM_ALIBABA: "LOADING"},
        )
        == "RUNNING"
    )
    assert (
        search_session.session_phase(
            session_active=True,
            providers=(PLATFORM_ALIBABA, PLATFORM_FACEBOOK),
            loading={PLATFORM_ALIBABA: False, PLATFORM_FACEBOOK: False},
            statuses={PLATFORM_ALIBABA: "SUCCESS", PLATFORM_FACEBOOK: "ERROR"},
        )
        == "PARTIAL"
    )
    assert (
        search_session.session_phase(
            session_active=True,
            providers=(PLATFORM_ALIBABA, PLATFORM_FACEBOOK),
            loading={PLATFORM_ALIBABA: False, PLATFORM_FACEBOOK: False},
            statuses={PLATFORM_ALIBABA: "ERROR", PLATFORM_FACEBOOK: "ERROR"},
        )
        == "ERROR"
    )
    assert (
        search_session.session_phase(
            session_active=True,
            providers=(PLATFORM_ALIBABA,),
            loading={PLATFORM_ALIBABA: False},
            statuses={PLATFORM_ALIBABA: "SUCCESS"},
        )
        == "COMPLETE"
    )
    assert (
        search_session.session_phase(
            session_active=True,
            providers=(PLATFORM_ALIBABA,),
            loading={PLATFORM_ALIBABA: False},
            statuses={PLATFORM_ALIBABA: "INITIAL"},
        )
        == "RUNNING"
    )
    assert search_session.shows_setup("IDLE") is True
    assert search_session.shows_results("COMPLETE") is True
    assert search_session.completion_status_copy("RUNNING")["label"] == "Buscando..."
    assert search_session.completion_status_copy("IDLE")["label"] == ""
    assert search_session.completion_status_copy("ERROR")["tone"] == "danger"
    assert search_session.parse_stat_number("Infinity") is None
    assert (
        search_session.boxplot_track(
            platform=PLATFORM_FACEBOOK,
            minimum="1",
            p25="2",
            median="3",
            p75="4",
            maximum="5",
            currency="VES",
            basis="USD",
        )["available"]
        == ""
    )
    assert (
        search_session.quick_insight(
            [
                {
                    "available": "1",
                    "median": "0",
                    "platform": PLATFORM_ALIBABA,
                    "label": "Alibaba",
                },
                {
                    "available": "1",
                    "median": "0",
                    "platform": PLATFORM_ML,
                    "label": "Mercado Libre",
                },
            ]
        )
        == ""
    )
    assert search_session.format_session_duration(0) == "—"
    assert search_session.format_session_duration(60000) == "1 min 0 s"
    assert search_session.format_session_duration(119500) == "2 min 0 s"
    from datetime import datetime

    assert (
        search_session.format_session_timestamp(datetime(2026, 5, 24, 10, 30)) == "2026-05-24 10:30"
    )
    assert search_session.parse_stat_number("USD 4.50") == Decimal("4.50")
    assert search_session.parse_stat_number("VES 20") == Decimal("20")
    assert search_session.parse_stat_number("nope") is None
    assert search_session.parse_stat_number(True) is None
    assert search_session.parse_stat_number(3) is None or search_session.parse_stat_number(
        3
    ) == Decimal("3")
    assert search_session.opportunity_gauge("bad", "")["available"] is False
    assert search_session.opportunity_gauge(True, "1")["available"] is True
    assert search_session.opportunity_gauge(140, "140")["score"] == 100
    assert search_session.seller_rating(4)["available"] is True
    assert search_session.quick_insight([]) == ""
    assert (
        search_session.quick_insight(
            [{"available": "1", "median": "0", "platform": "a", "label": "A"}]
        )
        == ""
    )
    summary = search_session.search_summary_view(
        mode=MODE_MULTI,
        limit=3,
        counts={PLATFORM_ALIBABA: 1, PLATFORM_FACEBOOK: 2, PLATFORM_ML: 0},
        duration_label="1.2 s",
    )
    assert summary["total_label"] == "3"
    copy = search_session.best_opportunity_copy(
        AlibabaResultRow(title="Mouse", price="USD 4.00", score_value=80, score="80")
    )
    assert copy["available"] == "1"
    assert search_session.best_opportunity_copy(None)["available"] == ""
    assert (
        search_session.best_opportunity_copy(AlibabaResultRow(title="x", score_value=0, score=""))[
            "heading"
        ]
        == "Análisis no disponible"
    )
    missing = search_session.boxplot_track(
        platform=PLATFORM_ML,
        minimum="",
        p25="",
        median="",
        p75="",
        maximum="",
        currency="USD",
        basis="USD",
    )
    assert missing["available"] == ""
    equal = search_session.boxplot_track(
        platform=PLATFORM_ALIBABA,
        minimum="5",
        p25="5",
        median="5",
        p75="5",
        maximum="5",
        currency="USD",
        basis="USD",
    )
    aligned_equal = search_session.align_boxplot_tracks([equal])
    assert aligned_equal[0]["median_left"] == "50.00%"
    empty_align = search_session.align_boxplot_tracks([missing])
    assert empty_align[0]["available"] == ""
    mixed = search_session.align_boxplot_tracks(
        [
            equal,
            {
                "available": "1",
                "minimum": "",
                "p25": "1",
                "median": "2",
                "p75": "3",
                "maximum": "4",
            },
        ]
    )
    assert mixed[1]["available"] == ""
    from bera_price_tracker.gui.components.search_results import search_results_view
    from bera_price_tracker.gui.components.search_scope import search_setup_view

    assert search_setup_view() is not None
    assert search_results_view() is not None


def _prepare_generic_session(
    state: TrackerState,
    *,
    mode: str,
    platform: str = PLATFORM_ALIBABA,
    generation: int = 4,
    limit: int = 3,
    query: str = "wireless mouse",
) -> search_scope.SearchPlan:
    state.search_generation = generation
    state.search_mode = mode
    state.search_platform = platform
    plan = plan_search(mode=mode, platform=platform, query=query, limit=limit)
    state.search_session_active = True
    state.search_session_query = plan.query
    state.search_limit = plan.limit
    state._prepare_scoped_search(plan)
    return plan


def test_mutating_live_mode_during_multi_acquisition_cannot_complete_after_one_provider() -> None:
    """P1: live SINGLE/Alibaba must not finish a MULTI generation early."""

    state = TrackerState()
    plan = _prepare_generic_session(state, mode=MODE_MULTI)
    state._finalize_alibaba_search(
        request_query=plan.query,
        request_limit=plan.limit,
        rows=[AlibabaResultRow(title="Generic Alibaba", product_id="ali-generic")],
        summary={"resultados": "1", "usable": "1"},
        ui_status=UI_SUCCESS,
        commit_generic_session=True,
    )
    assert state.search_session_phase == "RUNNING"
    state.search_mode = MODE_SINGLE
    state.search_platform = PLATFORM_ALIBABA
    assert state.search_session_phase == "RUNNING"
    assert state.search_shows_results is False
    assert state.export_enabled is False
    assert state.search_mode_label == MODE_LABELS[MODE_MULTI]
    assert {row.platform for row in state.search_progress_rows} == {
        PLATFORM_ALIBABA,
        PLATFORM_FACEBOOK,
        PLATFORM_ML,
    }


def test_mutating_live_mode_during_single_acquisition_does_not_enroll_unselected_providers() -> (
    None
):
    """P1: live MULTI must not enroll providers excluded from this generation."""

    state = TrackerState()
    _prepare_generic_session(state, mode=MODE_SINGLE, platform=PLATFORM_ALIBABA)
    state.search_mode = MODE_MULTI
    assert state.search_session_phase == "RUNNING"
    assert {row.platform for row in state.search_progress_rows} == {PLATFORM_ALIBABA}
    assert state.search_mode_label == MODE_LABELS[MODE_SINGLE]
    assert state.generic_session_facebook.status == UI_INITIAL
    assert state.generic_session_ml.status == UI_INITIAL


def test_mutating_live_mode_after_completion_does_not_relabel_generation() -> None:
    """P1: completed MULTI label must ignore later setup mutations."""

    state = TrackerState()
    plan = _prepare_generic_session(state, mode=MODE_MULTI)
    state._finalize_alibaba_search(
        request_query=plan.query,
        request_limit=plan.limit,
        rows=[AlibabaResultRow(title="Generic Alibaba", product_id="ali-generic")],
        summary={"resultados": "1"},
        ui_status=UI_SUCCESS,
        commit_generic_session=True,
    )
    state._finalize_facebook_product_search(
        product_id="",
        query=plan.query,
        city=plan.city,
        rows=[FacebookProductResultRow(title="Generic Facebook", external_id="fb-generic")],
        statistics=[FacebookCurrencyStatsRow()],
        summary={"usable": "1"},
        ui_status=UI_SUCCESS,
        commit_generic_session=True,
    )
    state._finalize_mercadolibre_search(
        search_product_id="",
        query=plan.query,
        rows=[MercadoLibreResultRow(title="Generic ML", external_id="MLV-generic")],
        summary={"usable": "1"},
        ui_status=UI_SUCCESS,
        commit_generic_session=True,
    )
    assert state.search_session_phase == "COMPLETE"
    assert state.search_mode_label == MODE_LABELS[MODE_MULTI]
    state.search_mode = MODE_SINGLE
    state.search_platform = PLATFORM_FACEBOOK
    assert state.search_session_phase == "COMPLETE"
    assert state.search_mode_label == MODE_LABELS[MODE_MULTI]
    assert {row.platform for row in state.search_progress_rows} == {
        PLATFORM_ALIBABA,
        PLATFORM_FACEBOOK,
        PLATFORM_ML,
    }


def test_generic_alibaba_completion_survives_live_query_mutation() -> None:
    """P1: generic Alibaba snapshot commits even if live query/limit changed."""

    state = TrackerState()
    plan = _prepare_generic_session(state, mode=MODE_SINGLE, platform=PLATFORM_ALIBABA)
    state.alibaba_query = "specialized headphones"
    state.alibaba_limit = 1
    state._finalize_alibaba_search(
        request_query=plan.query,
        request_limit=plan.limit,
        rows=[AlibabaResultRow(title="Generic Alibaba kept", product_id="ali-kept")],
        summary={"resultados": "1", "usable": "1"},
        ui_status=UI_SUCCESS,
        commit_generic_session=True,
    )
    assert [row.title for row in state.generic_session_alibaba.rows] == ["Generic Alibaba kept"]
    assert state.generic_session_alibaba.status == UI_SUCCESS
    assert all(row.title != "Generic Alibaba kept" for row in state.alibaba_results)


def test_specialized_alibaba_stale_query_is_still_rejected() -> None:
    state = TrackerState()
    state.search_generation = 4
    state.alibaba_query = "mouse"
    state.alibaba_limit = 3
    state.alibaba_is_loading = True
    state.alibaba_ui_status = UI_LOADING
    state.alibaba_query = "headphones"
    state._finalize_alibaba_search(
        request_query="mouse",
        request_limit=3,
        rows=[AlibabaResultRow(title="Specialized stale Alibaba", product_id="ali-stale")],
        ui_status=UI_SUCCESS,
        commit_generic_session=False,
    )
    assert all(row.title != "Specialized stale Alibaba" for row in state.alibaba_results)
    assert state.generic_session_alibaba.rows == []


def test_generic_facebook_completion_survives_live_context_mutation() -> None:
    state = TrackerState()
    plan = _prepare_generic_session(state, mode=MODE_SINGLE, platform=PLATFORM_FACEBOOK)
    state.facebook_product_query = "specialized facebook"
    state.facebook_product_city = "maracaibo"
    state.facebook_product_has_alibaba_context = True
    state.facebook_product_alibaba_context = {"external_id": "P-SPEC", "title": "Spec"}
    state._finalize_facebook_product_search(
        product_id="",
        query=plan.query,
        city=plan.city,
        rows=[FacebookProductResultRow(title="Generic Facebook kept", external_id="fb-kept")],
        statistics=[FacebookCurrencyStatsRow()],
        summary={"usable": "1"},
        ui_status=UI_SUCCESS,
        commit_generic_session=True,
    )
    assert [row.title for row in state.generic_session_facebook.rows] == ["Generic Facebook kept"]
    assert state.generic_session_facebook.status == UI_SUCCESS
    assert all(row.title != "Generic Facebook kept" for row in state.facebook_product_results)


def test_specialized_facebook_stale_query_is_still_rejected() -> None:
    state = TrackerState()
    state.search_generation = 4
    state.facebook_product_query = "mouse"
    state.facebook_product_city = "caracas"
    state.facebook_product_is_loading = True
    state.facebook_product_ui_status = UI_LOADING
    state.facebook_product_query = "headphones"
    state._finalize_facebook_product_search(
        product_id="",
        query="mouse",
        city="caracas",
        rows=[FacebookProductResultRow(title="Specialized stale Facebook", external_id="fb-stale")],
        ui_status=UI_SUCCESS,
        commit_generic_session=False,
    )
    assert all(row.title != "Specialized stale Facebook" for row in state.facebook_product_results)
    assert state.generic_session_facebook.rows == []


def test_generic_ml_completion_survives_live_context_mutation() -> None:
    state = TrackerState()
    plan = _prepare_generic_session(state, mode=MODE_SINGLE, platform=PLATFORM_ML)
    state.ml_query = "specialized ml"
    state.ml_has_alibaba_context = True
    state.ml_alibaba_context = {"external_id": "P-SPEC", "title": "Spec"}
    state._finalize_mercadolibre_search(
        search_product_id="",
        query=plan.query,
        rows=[MercadoLibreResultRow(title="Generic ML kept", external_id="MLV-kept")],
        summary={"usable": "1"},
        ui_status=UI_SUCCESS,
        commit_generic_session=True,
    )
    assert [row.title for row in state.generic_session_ml.rows] == ["Generic ML kept"]
    assert state.generic_session_ml.status == UI_SUCCESS
    assert all(row.title != "Generic ML kept" for row in state.ml_results)


def test_specialized_ml_stale_query_is_still_rejected() -> None:
    state = TrackerState()
    state.search_generation = 4
    state.ml_query = "mouse"
    state.ml_is_loading = True
    state.ml_ui_status = UI_LOADING
    state.ml_query = "headphones"
    state._finalize_mercadolibre_search(
        search_product_id="",
        query="mouse",
        rows=[MercadoLibreResultRow(title="Specialized stale ML", external_id="MLV-stale")],
        ui_status=UI_SUCCESS,
        commit_generic_session=False,
    )
    assert all(row.title != "Specialized stale ML" for row in state.ml_results)
    assert state.generic_session_ml.rows == []


def test_generic_progress_ignores_specialized_live_alibaba_mutation() -> None:
    """P2: generic progress must keep settled owned Alibaba detail."""

    state = TrackerState()
    plan = _prepare_generic_session(state, mode=MODE_MULTI)
    state._finalize_alibaba_search(
        request_query=plan.query,
        request_limit=plan.limit,
        rows=[AlibabaResultRow(title="Generic Alibaba", product_id="ali-generic")],
        summary={"resultados": "1", "usable": "1"},
        ui_status=UI_SUCCESS,
        commit_generic_session=True,
    )
    before = {row.platform: row.detail for row in state.search_progress_rows}
    assert before[PLATFORM_ALIBABA] == "1 resultados"
    assert before[PLATFORM_FACEBOOK] == "Buscando..."
    state.alibaba_ui_status = UI_LOADING
    state.alibaba_is_loading = True
    state.alibaba_results = [AlibabaResultRow(title="Specialized Alibaba", product_id="ali-spec")]
    state.alibaba_summary = {"resultados": "9", "usable": "9"}
    after = {row.platform: row.detail for row in state.search_progress_rows}
    assert after[PLATFORM_ALIBABA] == before[PLATFORM_ALIBABA]
    assert after[PLATFORM_FACEBOOK] == "Buscando..."


def test_generic_progress_ignores_specialized_live_facebook_mutation() -> None:
    """P2: generic progress is provider-neutral and ignores specialized Facebook live state."""

    state = TrackerState()
    plan = _prepare_generic_session(state, mode=MODE_MULTI)
    state._finalize_facebook_product_search(
        product_id="",
        query=plan.query,
        city=plan.city,
        rows=[FacebookProductResultRow(title="Generic Facebook", external_id="fb-generic")],
        statistics=[FacebookCurrencyStatsRow()],
        summary={"usable": "1"},
        ui_status=UI_SUCCESS,
        commit_generic_session=True,
    )
    before = {row.platform: row.detail for row in state.search_progress_rows}
    assert before[PLATFORM_FACEBOOK] == "1 resultados válidos"
    assert before[PLATFORM_ALIBABA] == "Buscando..."
    state.facebook_product_ui_status = UI_LOADING
    state.facebook_product_is_loading = True
    state.facebook_product_results = [
        FacebookProductResultRow(title="Specialized Facebook", external_id="fb-spec")
    ]
    state.facebook_product_summary = {"usable": "9"}
    after = {row.platform: row.detail for row in state.search_progress_rows}
    assert after[PLATFORM_FACEBOOK] == before[PLATFORM_FACEBOOK]
    assert after[PLATFORM_ALIBABA] == "Buscando..."


def test_generic_ml_progress_counts_canonical_rows_not_comparables() -> None:
    """P2: generic ML progress uses canonical membership, not benchmark comparables."""

    state = TrackerState()
    plan = _prepare_generic_session(state, mode=MODE_SINGLE, platform=PLATFORM_ML)
    state._finalize_mercadolibre_search(
        search_product_id="",
        query=plan.query,
        rows=[
            MercadoLibreResultRow(
                title="Low A", external_id="MLV-a", relevance_value=10, price_raw="10.00"
            ),
            MercadoLibreResultRow(
                title="Low B", external_id="MLV-b", relevance_value=20, price_raw="20.00"
            ),
            MercadoLibreResultRow(
                title="High C", external_id="MLV-c", relevance_value=90, price_raw="100.00"
            ),
        ],
        summary={"comparables": "1", "comparable_count": "1", "usable": "3"},
        ui_status=UI_SUCCESS,
        commit_generic_session=True,
    )
    details = {row.platform: row.detail for row in state.search_progress_rows}
    assert details[PLATFORM_ML] == "3 resultados"


def test_mutating_live_mode_after_provider_error_keeps_pending_generic_providers() -> None:
    """Adversarial: one ERROR must not complete/error the MULTI generation early."""

    state = TrackerState()
    plan = _prepare_generic_session(state, mode=MODE_MULTI)
    state._finalize_alibaba_search(
        request_query=plan.query,
        request_limit=plan.limit,
        error_message="Alibaba failed",
        commit_generic_session=True,
    )
    assert state.search_session_phase == "RUNNING"
    state.search_mode = MODE_SINGLE
    state.search_platform = PLATFORM_ALIBABA
    assert state.search_session_phase == "RUNNING"
    assert state.export_enabled is False
    assert {row.platform for row in state.search_progress_rows} == {
        PLATFORM_ALIBABA,
        PLATFORM_FACEBOOK,
        PLATFORM_ML,
    }


def test_new_generic_generation_replaces_frozen_mode_and_providers() -> None:
    """A later generation may freeze a different mode than the previous one."""

    state = TrackerState()
    plan = _prepare_generic_session(state, mode=MODE_MULTI, generation=4)
    state._finalize_alibaba_search(
        request_query=plan.query,
        request_limit=plan.limit,
        rows=[AlibabaResultRow(title="Generic Alibaba", product_id="ali-generic")],
        summary={"resultados": "1"},
        ui_status=UI_SUCCESS,
        commit_generic_session=True,
    )
    state._finalize_facebook_product_search(
        product_id="",
        query=plan.query,
        city=plan.city,
        rows=[FacebookProductResultRow(title="Generic Facebook", external_id="fb-generic")],
        statistics=[FacebookCurrencyStatsRow()],
        summary={"usable": "1"},
        ui_status=UI_SUCCESS,
        commit_generic_session=True,
    )
    state._finalize_mercadolibre_search(
        search_product_id="",
        query=plan.query,
        rows=[MercadoLibreResultRow(title="Generic ML", external_id="MLV-generic")],
        summary={"usable": "1"},
        ui_status=UI_SUCCESS,
        commit_generic_session=True,
    )
    state.search_mode = MODE_SINGLE
    state.search_platform = PLATFORM_ALIBABA
    assert state.search_mode_label == MODE_LABELS[MODE_MULTI]
    _prepare_generic_session(state, mode=MODE_SINGLE, platform=PLATFORM_ALIBABA, generation=5)
    assert state.search_mode_label == MODE_LABELS[MODE_SINGLE]
    assert {row.platform for row in state.search_progress_rows} == {PLATFORM_ALIBABA}
    assert state.search_session_phase == "RUNNING"


def test_mutating_live_query_limit_and_platform_does_not_rewrite_active_generation() -> None:
    state = TrackerState()
    plan = _prepare_generic_session(state, mode=MODE_MULTI, query="wireless mouse", limit=3)
    state.search_query = "headphones"
    state.search_limit = 1
    state.search_platform = PLATFORM_ML
    state.alibaba_query = "specialized alibaba"
    assert state.search_session_phase == "RUNNING"
    assert state.search_mode_label == MODE_LABELS[MODE_MULTI]
    assert {row.platform for row in state.search_progress_rows} == {
        PLATFORM_ALIBABA,
        PLATFORM_FACEBOOK,
        PLATFORM_ML,
    }
    state._finalize_alibaba_search(
        request_query=plan.query,
        request_limit=plan.limit,
        rows=[AlibabaResultRow(title="Generic Alibaba kept", product_id="ali-kept")],
        summary={"resultados": "1"},
        ui_status=UI_SUCCESS,
        commit_generic_session=True,
    )
    assert [row.title for row in state.generic_session_alibaba.rows] == ["Generic Alibaba kept"]
    assert state.search_session_phase == "RUNNING"
    assert all(row.title != "Generic Alibaba kept" for row in state.alibaba_results)


async def _wait_thread_event(event: threading.Event, *, timeout: float = 5.0) -> None:
    await asyncio.to_thread(event.wait, timeout)
    assert event.is_set()


def test_alibaba_specialized_search_cannot_start_while_generic_alibaba_is_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alibaba overlap is not production-reachable: shared loading blocks search_alibaba."""

    from bera_price_tracker.gui import services

    generic_started = threading.Event()
    generic_release = threading.Event()
    specialized_calls = {"count": 0}

    def run_alibaba(query: str, limit: int) -> dict[str, object]:
        if query == "specialized alibaba":
            specialized_calls["count"] += 1
            return {"results": [{"title": "Specialized Alibaba", "product_id": "ali-spec"}]}
        generic_started.set()
        generic_release.wait(5)
        return {
            "results": [{"title": "Generic Alibaba", "product_id": "ali-generic"}],
            "summary": {"resultados": "1"},
            "stats_raw": {},
            "ui_status": UI_SUCCESS,
        }

    monkeypatch.setattr(services, "run_alibaba_search", run_alibaba)

    async def scenario() -> None:
        state = TrackerState()
        state.search_mode = MODE_SINGLE
        state.search_platform = PLATFORM_ALIBABA
        state.search_query = "wireless mouse"
        state.search_limit = 3
        generic_task = asyncio.create_task(cast(Any, TrackerState.run_scoped_search).fn(state))
        await _wait_thread_event(generic_started)
        assert state.alibaba_is_loading is True
        state.set_alibaba_query("specialized alibaba")
        await cast(Any, TrackerState.search_alibaba).fn(state)
        assert specialized_calls["count"] == 0
        assert state.alibaba_is_loading is True
        assert state.alibaba_ui_status == UI_LOADING
        generic_release.set()
        await generic_task

    asyncio.run(scenario())


def test_generic_facebook_completion_does_not_clear_concurrent_specialized_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1: generic Facebook finalize must not reset a specialized live request it does not own."""

    from bera_price_tracker.gui import services

    monkeypatch.setattr(services, "product_translator_is_configured", lambda: False)
    generic_started = threading.Event()
    generic_release = threading.Event()
    specialized_started = threading.Event()
    specialized_release = threading.Event()

    def run_facebook(query: str, city: str, limit: int) -> dict[str, object]:
        if query == "specialized facebook":
            specialized_started.set()
            specialized_release.wait(5)
            return {
                "results": [{"title": "Specialized Facebook", "external_id": "fb-spec"}],
                "statistics": [],
                "summary": {"usable": "1"},
                "ui_status": UI_SUCCESS,
            }
        generic_started.set()
        generic_release.wait(5)
        return {
            "results": [{"title": "Generic Facebook", "external_id": "fb-generic"}],
            "statistics": [],
            "summary": {"usable": "1"},
            "ui_status": UI_SUCCESS,
        }

    monkeypatch.setattr(services, "run_facebook_product_search", run_facebook)

    async def scenario() -> None:
        state = TrackerState()
        state.search_mode = MODE_SINGLE
        state.search_platform = PLATFORM_FACEBOOK
        state.search_query = "wireless mouse"
        state.search_limit = 3
        state.facebook_product_city = "caracas"
        state.alibaba_tracked_rows = [AlibabaTrackedRow(product_id="P-SPEC", title="Tracked mouse")]
        generic_task = asyncio.create_task(cast(Any, TrackerState.run_scoped_search).fn(state))
        await _wait_thread_event(generic_started)
        assert state.facebook_product_is_loading is True
        opening = state.prepare_facebook_comparables_from_alibaba_tracked("P-SPEC")
        assert opening is TrackerState.translate_selected_alibaba_title_for_facebook
        state.set_facebook_product_query("specialized facebook")
        specialized_task = asyncio.create_task(
            cast(Any, TrackerState.search_facebook_products).fn(state)
        )
        await _wait_thread_event(specialized_started)
        assert state.facebook_product_is_loading is True
        assert state.facebook_product_ui_status == UI_LOADING
        generic_release.set()
        await generic_task
        try:
            assert [row.title for row in state.generic_session_facebook.rows] == [
                "Generic Facebook"
            ]
            assert state.generic_session_facebook.status == UI_SUCCESS
            assert state.facebook_product_is_loading is True
            assert state.facebook_product_ui_status == UI_LOADING
            assert state.facebook_product_query == "specialized facebook"
            assert all(row.title != "Generic Facebook" for row in state.facebook_product_results)
            specialized_release.set()
            await specialized_task
            assert [row.title for row in state.facebook_product_results] == ["Specialized Facebook"]
            assert state.facebook_product_is_loading is False
            assert state.facebook_product_ui_status == UI_SUCCESS
        finally:
            specialized_release.set()

    asyncio.run(scenario())


def test_generic_ml_completion_does_not_clear_concurrent_specialized_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1: generic Mercado Libre finalize must not reset a specialized live request it does not own."""

    from bera_price_tracker.gui import services

    monkeypatch.setattr(services, "product_translator_is_configured", lambda: False)
    generic_started = threading.Event()
    generic_release = threading.Event()
    specialized_started = threading.Event()
    specialized_release = threading.Event()

    def run_ml(query: str, limit: int) -> dict[str, object]:
        if query == "specialized ml":
            specialized_started.set()
            specialized_release.wait(5)
            return {
                "results": [{"title": "Specialized ML", "external_id": "MLV-spec"}],
                "summary": {"usable": "1"},
                "ui_status": UI_SUCCESS,
            }
        generic_started.set()
        generic_release.wait(5)
        return {
            "results": [{"title": "Generic ML", "external_id": "MLV-generic"}],
            "summary": {"usable": "1"},
            "ui_status": UI_SUCCESS,
        }

    monkeypatch.setattr(services, "run_mercadolibre_search", run_ml)

    async def scenario() -> None:
        state = TrackerState()
        state.search_mode = MODE_SINGLE
        state.search_platform = PLATFORM_ML
        state.search_query = "wireless mouse"
        state.search_limit = 3
        state.alibaba_tracked_rows = [AlibabaTrackedRow(product_id="P-SPEC", title="Tracked mouse")]
        generic_task = asyncio.create_task(cast(Any, TrackerState.run_scoped_search).fn(state))
        await _wait_thread_event(generic_started)
        assert state.ml_is_loading is True
        opening = state.prepare_ml_comparables_from_alibaba_tracked("P-SPEC")
        assert opening is TrackerState.translate_selected_alibaba_title
        state.set_ml_query("specialized ml")
        specialized_task = asyncio.create_task(
            cast(Any, TrackerState.search_mercadolibre).fn(state)
        )
        await _wait_thread_event(specialized_started)
        assert state.ml_is_loading is True
        assert state.ml_ui_status == UI_LOADING
        generic_release.set()
        await generic_task
        try:
            assert [row.title for row in state.generic_session_ml.rows] == ["Generic ML"]
            assert state.generic_session_ml.status == UI_SUCCESS
            assert state.ml_is_loading is True
            assert state.ml_ui_status == UI_LOADING
            assert state.ml_query == "specialized ml"
            assert all(row.title != "Generic ML" for row in state.ml_results)
            specialized_release.set()
            await specialized_task
            assert [row.title for row in state.ml_results] == ["Specialized ML"]
            assert state.ml_is_loading is False
            assert state.ml_ui_status == UI_SUCCESS
        finally:
            specialized_release.set()

    asyncio.run(scenario())


def test_generic_facebook_completion_does_not_clear_specialized_loading_when_query_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same live query is not ownership: product_id differs after prepare."""

    from bera_price_tracker.gui import services

    monkeypatch.setattr(services, "product_translator_is_configured", lambda: False)
    generic_started = threading.Event()
    generic_release = threading.Event()
    specialized_started = threading.Event()
    specialized_release = threading.Event()
    calls = {"count": 0}

    def run_facebook(query: str, city: str, limit: int) -> dict[str, object]:
        calls["count"] += 1
        if calls["count"] == 1:
            generic_started.set()
            generic_release.wait(5)
            return {
                "results": [{"title": "Generic Facebook", "external_id": "fb-generic"}],
                "statistics": [],
                "summary": {"usable": "1"},
                "ui_status": UI_SUCCESS,
            }
        specialized_started.set()
        specialized_release.wait(5)
        return {
            "results": [{"title": "Specialized Facebook", "external_id": "fb-spec"}],
            "statistics": [],
            "summary": {"usable": "1"},
            "ui_status": UI_SUCCESS,
        }

    monkeypatch.setattr(services, "run_facebook_product_search", run_facebook)

    async def scenario() -> None:
        state = TrackerState()
        state.search_mode = MODE_SINGLE
        state.search_platform = PLATFORM_FACEBOOK
        state.search_query = "wireless mouse"
        state.search_limit = 3
        state.facebook_product_city = "caracas"
        state.alibaba_tracked_rows = [AlibabaTrackedRow(product_id="P-SPEC", title="Tracked mouse")]
        generic_task = asyncio.create_task(cast(Any, TrackerState.run_scoped_search).fn(state))
        await _wait_thread_event(generic_started)
        opening = state.prepare_facebook_comparables_from_alibaba_tracked("P-SPEC")
        assert opening is TrackerState.translate_selected_alibaba_title_for_facebook
        state.set_facebook_product_query("wireless mouse")
        specialized_task = asyncio.create_task(
            cast(Any, TrackerState.search_facebook_products).fn(state)
        )
        await _wait_thread_event(specialized_started)
        assert state.facebook_product_is_loading is True
        generic_release.set()
        await generic_task
        try:
            assert [row.title for row in state.generic_session_facebook.rows] == [
                "Generic Facebook"
            ]
            assert state.facebook_product_is_loading is True
            assert state.facebook_product_ui_status == UI_LOADING
            assert state.facebook_product_query == "wireless mouse"
            assert all(row.title != "Generic Facebook" for row in state.facebook_product_results)
            specialized_release.set()
            await specialized_task
            assert [row.title for row in state.facebook_product_results] == ["Specialized Facebook"]
        finally:
            specialized_release.set()

    asyncio.run(scenario())


def test_generic_facebook_error_does_not_clear_concurrent_specialized_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bera_price_tracker.gui import services

    monkeypatch.setattr(services, "product_translator_is_configured", lambda: False)
    generic_started = threading.Event()
    generic_release = threading.Event()
    specialized_started = threading.Event()
    specialized_release = threading.Event()

    def run_facebook(query: str, city: str, limit: int) -> dict[str, object]:
        if query == "specialized facebook":
            specialized_started.set()
            specialized_release.wait(5)
            return {
                "results": [{"title": "Specialized Facebook", "external_id": "fb-spec"}],
                "statistics": [],
                "summary": {"usable": "1"},
                "ui_status": UI_SUCCESS,
            }
        generic_started.set()
        generic_release.wait(5)
        raise RuntimeError("generic facebook failed")

    monkeypatch.setattr(services, "run_facebook_product_search", run_facebook)

    async def scenario() -> None:
        state = TrackerState()
        state.search_mode = MODE_SINGLE
        state.search_platform = PLATFORM_FACEBOOK
        state.search_query = "wireless mouse"
        state.search_limit = 3
        state.facebook_product_city = "caracas"
        state.alibaba_tracked_rows = [AlibabaTrackedRow(product_id="P-SPEC", title="Tracked mouse")]
        generic_task = asyncio.create_task(cast(Any, TrackerState.run_scoped_search).fn(state))
        await _wait_thread_event(generic_started)
        state.prepare_facebook_comparables_from_alibaba_tracked("P-SPEC")
        state.set_facebook_product_query("specialized facebook")
        specialized_task = asyncio.create_task(
            cast(Any, TrackerState.search_facebook_products).fn(state)
        )
        await _wait_thread_event(specialized_started)
        generic_release.set()
        await generic_task
        try:
            assert state.generic_session_facebook.status == UI_ERROR
            assert state.generic_session_facebook.rows == []
            assert state.facebook_product_is_loading is True
            assert state.facebook_product_ui_status == UI_LOADING
            specialized_release.set()
            await specialized_task
            assert [row.title for row in state.facebook_product_results] == ["Specialized Facebook"]
            assert state.generic_session_facebook.status == UI_ERROR
        finally:
            specialized_release.set()

    asyncio.run(scenario())


def test_generic_ml_error_does_not_clear_concurrent_specialized_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bera_price_tracker.gui import services

    monkeypatch.setattr(services, "product_translator_is_configured", lambda: False)
    generic_started = threading.Event()
    generic_release = threading.Event()
    specialized_started = threading.Event()
    specialized_release = threading.Event()

    def run_ml(query: str, limit: int) -> dict[str, object]:
        if query == "specialized ml":
            specialized_started.set()
            specialized_release.wait(5)
            return {
                "results": [{"title": "Specialized ML", "external_id": "MLV-spec"}],
                "summary": {"usable": "1"},
                "ui_status": UI_SUCCESS,
            }
        generic_started.set()
        generic_release.wait(5)
        raise RuntimeError("generic ml failed")

    monkeypatch.setattr(services, "run_mercadolibre_search", run_ml)

    async def scenario() -> None:
        state = TrackerState()
        state.search_mode = MODE_SINGLE
        state.search_platform = PLATFORM_ML
        state.search_query = "wireless mouse"
        state.search_limit = 3
        state.alibaba_tracked_rows = [AlibabaTrackedRow(product_id="P-SPEC", title="Tracked mouse")]
        generic_task = asyncio.create_task(cast(Any, TrackerState.run_scoped_search).fn(state))
        await _wait_thread_event(generic_started)
        state.prepare_ml_comparables_from_alibaba_tracked("P-SPEC")
        state.set_ml_query("specialized ml")
        specialized_task = asyncio.create_task(
            cast(Any, TrackerState.search_mercadolibre).fn(state)
        )
        await _wait_thread_event(specialized_started)
        generic_release.set()
        await generic_task
        try:
            assert state.generic_session_ml.status == UI_ERROR
            assert state.generic_session_ml.rows == []
            assert state.ml_is_loading is True
            assert state.ml_ui_status == UI_LOADING
            specialized_release.set()
            await specialized_task
            assert [row.title for row in state.ml_results] == ["Specialized ML"]
            assert state.generic_session_ml.status == UI_ERROR
        finally:
            specialized_release.set()

    asyncio.run(scenario())


def test_specialized_facebook_error_after_generic_overlap_does_not_rewrite_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bera_price_tracker.gui import services

    monkeypatch.setattr(services, "product_translator_is_configured", lambda: False)
    generic_started = threading.Event()
    generic_release = threading.Event()
    specialized_started = threading.Event()
    specialized_release = threading.Event()

    def run_facebook(query: str, city: str, limit: int) -> dict[str, object]:
        if query == "specialized facebook":
            specialized_started.set()
            specialized_release.wait(5)
            raise RuntimeError("specialized facebook failed")
        generic_started.set()
        generic_release.wait(5)
        return {
            "results": [{"title": "Generic Facebook", "external_id": "fb-generic"}],
            "statistics": [],
            "summary": {"usable": "1"},
            "ui_status": UI_SUCCESS,
        }

    monkeypatch.setattr(services, "run_facebook_product_search", run_facebook)

    async def scenario() -> None:
        state = TrackerState()
        state.search_mode = MODE_SINGLE
        state.search_platform = PLATFORM_FACEBOOK
        state.search_query = "wireless mouse"
        state.search_limit = 3
        state.facebook_product_city = "caracas"
        state.alibaba_tracked_rows = [AlibabaTrackedRow(product_id="P-SPEC", title="Tracked mouse")]
        generic_task = asyncio.create_task(cast(Any, TrackerState.run_scoped_search).fn(state))
        await _wait_thread_event(generic_started)
        state.prepare_facebook_comparables_from_alibaba_tracked("P-SPEC")
        state.set_facebook_product_query("specialized facebook")
        specialized_task = asyncio.create_task(
            cast(Any, TrackerState.search_facebook_products).fn(state)
        )
        await _wait_thread_event(specialized_started)
        generic_release.set()
        await generic_task
        try:
            assert [row.title for row in state.generic_session_facebook.rows] == [
                "Generic Facebook"
            ]
            assert state.facebook_product_is_loading is True
            specialized_release.set()
            await specialized_task
            assert state.facebook_product_is_loading is False
            assert state.facebook_product_ui_status == UI_ERROR
            assert state.facebook_product_results == []
            assert [row.title for row in state.generic_session_facebook.rows] == [
                "Generic Facebook"
            ]
            assert state.generic_session_facebook.status == UI_SUCCESS
        finally:
            specialized_release.set()

    asyncio.run(scenario())


def test_generic_alibaba_completion_clears_owned_loading_after_live_query_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Generic still owns Alibaba live state; mutating the query must not stick LOADING."""

    from bera_price_tracker.gui import services

    generic_started = threading.Event()
    generic_release = threading.Event()
    specialized_calls = {"count": 0}

    def run_alibaba(query: str, limit: int) -> dict[str, object]:
        if query == "mutated alibaba":
            specialized_calls["count"] += 1
            return {"results": [{"title": "Specialized Alibaba", "product_id": "ali-spec"}]}
        generic_started.set()
        generic_release.wait(5)
        return {
            "results": [{"title": "Generic Alibaba", "product_id": "ali-generic"}],
            "summary": {"resultados": "1"},
            "stats_raw": {},
            "ui_status": UI_SUCCESS,
        }

    monkeypatch.setattr(services, "run_alibaba_search", run_alibaba)

    async def scenario() -> None:
        state = TrackerState()
        state.search_mode = MODE_SINGLE
        state.search_platform = PLATFORM_ALIBABA
        state.search_query = "wireless mouse"
        state.search_limit = 3
        generic_task = asyncio.create_task(cast(Any, TrackerState.run_scoped_search).fn(state))
        await _wait_thread_event(generic_started)
        state.set_alibaba_query("mutated alibaba")
        await cast(Any, TrackerState.search_alibaba).fn(state)
        assert specialized_calls["count"] == 0
        assert state.alibaba_is_loading is True
        generic_release.set()
        await generic_task
        assert [row.title for row in state.generic_session_alibaba.rows] == ["Generic Alibaba"]
        assert state.generic_session_alibaba.status == UI_SUCCESS
        assert state.alibaba_is_loading is False
        assert state.alibaba_ui_status == UI_INITIAL
        assert all(row.title != "Generic Alibaba" for row in state.alibaba_results)

    asyncio.run(scenario())


def test_generic_facebook_completion_still_applies_when_it_owns_live_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bera_price_tracker.gui import services

    monkeypatch.setattr(services, "product_translator_is_configured", lambda: False)

    def run_facebook(query: str, city: str, limit: int) -> dict[str, object]:
        return {
            "results": [{"title": "Generic Facebook", "external_id": "fb-generic"}],
            "statistics": [],
            "summary": {"usable": "1"},
            "ui_status": UI_SUCCESS,
        }

    monkeypatch.setattr(services, "run_facebook_product_search", run_facebook)

    state = TrackerState()
    state.search_mode = MODE_SINGLE
    state.search_platform = PLATFORM_FACEBOOK
    state.search_query = "wireless mouse"
    state.search_limit = 3
    state.facebook_product_city = "caracas"
    asyncio.run(cast(Any, TrackerState.run_scoped_search).fn(state))
    assert [row.title for row in state.generic_session_facebook.rows] == ["Generic Facebook"]
    assert [row.title for row in state.facebook_product_results] == ["Generic Facebook"]
    assert state.facebook_product_is_loading is False
    assert state.facebook_product_ui_status == UI_SUCCESS


def test_stale_facebook_specialized_completion_does_not_clear_newer_specialized_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bera_price_tracker.gui import services

    monkeypatch.setattr(services, "product_translator_is_configured", lambda: False)
    first_started = threading.Event()
    first_release = threading.Event()
    second_started = threading.Event()
    second_release = threading.Event()

    def run_facebook(query: str, city: str, limit: int) -> dict[str, object]:
        if query == "second specialized":
            second_started.set()
            second_release.wait(5)
            return {
                "results": [{"title": "Second Specialized", "external_id": "fb-2"}],
                "statistics": [],
                "summary": {"usable": "1"},
                "ui_status": UI_SUCCESS,
            }
        first_started.set()
        first_release.wait(5)
        return {
            "results": [{"title": "First Specialized", "external_id": "fb-1"}],
            "statistics": [],
            "summary": {"usable": "1"},
            "ui_status": UI_SUCCESS,
        }

    monkeypatch.setattr(services, "run_facebook_product_search", run_facebook)

    async def scenario() -> None:
        state = TrackerState()
        state.facebook_product_city = "caracas"
        state.facebook_product_query = "first specialized"
        state.alibaba_tracked_rows = [
            AlibabaTrackedRow(product_id="P-1", title="First tracked"),
            AlibabaTrackedRow(product_id="P-2", title="Second tracked"),
        ]
        first_task = asyncio.create_task(cast(Any, TrackerState.search_facebook_products).fn(state))
        await _wait_thread_event(first_started)
        opening = state.prepare_facebook_comparables_from_alibaba_tracked("P-2")
        assert opening is TrackerState.translate_selected_alibaba_title_for_facebook
        state.set_facebook_product_query("second specialized")
        second_task = asyncio.create_task(
            cast(Any, TrackerState.search_facebook_products).fn(state)
        )
        await _wait_thread_event(second_started)
        assert state.facebook_product_is_loading is True
        first_release.set()
        await first_task
        try:
            assert state.facebook_product_is_loading is True
            assert state.facebook_product_ui_status == UI_LOADING
            assert all(row.title != "First Specialized" for row in state.facebook_product_results)
            second_release.set()
            await second_task
            assert [row.title for row in state.facebook_product_results] == ["Second Specialized"]
            assert state.facebook_product_is_loading is False
        finally:
            first_release.set()
            second_release.set()

    asyncio.run(scenario())


def test_repeated_facebook_specialized_search_after_completion_replaces_live_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bera_price_tracker.gui import services

    monkeypatch.setattr(services, "product_translator_is_configured", lambda: False)

    def run_facebook(query: str, city: str, limit: int) -> dict[str, object]:
        return {
            "results": [{"title": query, "external_id": f"fb-{query}"}],
            "statistics": [],
            "summary": {"usable": "1"},
            "ui_status": UI_SUCCESS,
        }

    monkeypatch.setattr(services, "run_facebook_product_search", run_facebook)

    state = TrackerState()
    state.facebook_product_city = "caracas"
    state.facebook_product_query = "first specialized"
    asyncio.run(cast(Any, TrackerState.search_facebook_products).fn(state))
    assert [row.title for row in state.facebook_product_results] == ["first specialized"]
    assert state.facebook_product_is_loading is False
    state.set_facebook_product_query("second specialized")
    asyncio.run(cast(Any, TrackerState.search_facebook_products).fn(state))
    assert [row.title for row in state.facebook_product_results] == ["second specialized"]
    assert state.facebook_product_is_loading is False
    assert state.facebook_product_ui_status == UI_SUCCESS
