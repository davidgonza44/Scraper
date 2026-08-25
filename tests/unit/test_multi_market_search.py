"""Offline multi-market search orchestration, brands, and provenance."""

from __future__ import annotations

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
    assert cards[0]["rating_available"] is True
    assert cards[0]["rating_filled"] == 5
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
    assert "marketplace_brand(" in source


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
