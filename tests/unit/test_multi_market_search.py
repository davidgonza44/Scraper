"""Offline multi-market search orchestration, brands, and provenance."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

import pytest

from bera_price_tracker.application.facebook_products import SearchFacebookMarketplaceProducts
from bera_price_tracker.application.ports import FacebookMarketplaceProductSearchProvider
from bera_price_tracker.gui import brands, comparison, search_scope
from bera_price_tracker.gui.brands import PLATFORM_ALIBABA, PLATFORM_FACEBOOK, PLATFORM_ML
from bera_price_tracker.gui.search_scope import (
    DEFAULT_SEARCH_LIMIT,
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
    UI_SUCCESS,
    AlibabaResultRow,
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


def test_brand_assets_exist_locally() -> None:
    alibaba, facebook = brands.local_brand_files()
    assert alibaba.is_file()
    assert facebook.is_file()
    assert alibaba.read_text(encoding="utf-8").lstrip().startswith("<svg")
    assert facebook.read_text(encoding="utf-8").lstrip().startswith("<svg")
    assert not (alibaba.parent / "mercado-libre.svg").exists()


def test_brand_component_specs_cover_three_marketplaces() -> None:
    alibaba = brands.brand_spec(PLATFORM_ALIBABA)
    facebook = brands.brand_spec(PLATFORM_FACEBOOK)
    ml = brands.brand_spec(PLATFORM_ML)
    assert alibaba.kind == "image" and alibaba.src == "/brands/alibaba.svg"
    assert facebook.kind == "image" and facebook.src == "/brands/facebook.svg"
    assert ml.kind == "text" and ml.src == ""
    assert ml.label == "Mercado Libre"


def test_brand_specs_have_no_runtime_cdn() -> None:
    for spec in brands.BRANDS.values():
        assert brands.brand_uses_runtime_cdn(spec) is False
        assert "simpleicons.org" not in spec.src
        assert not spec.src.startswith("https://")


def test_no_fabricated_mercadolibre_logo_file() -> None:
    source = (brands._ASSETS_ROOT.parent.parent / "src/bera_price_tracker/gui/brands.py").read_text(
        encoding="utf-8"
    )
    assert "handshake" not in source.casefold()
    attribution = (brands._ASSETS_ROOT / "ATTRIBUTION.md").read_text(encoding="utf-8")
    assert "text only" in attribution.casefold()


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


def test_partial_fixture_preserves_success_and_error() -> None:
    state = TrackerState()
    state.apply_partial_search_fixture()
    assert state.alibaba_ui_status == UI_SUCCESS
    assert state.facebook_product_ui_status == UI_ERROR
    assert state.ml_ui_status == UI_SUCCESS
    assert state.facebook_product_results == []
    assert state.ml_results[0].title == "Fixture ML"
    assert state.ml_results[0].relevance_value == 90
