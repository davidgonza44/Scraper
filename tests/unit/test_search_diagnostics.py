"""Offline provider diagnostic tests. No provider I/O."""

from __future__ import annotations

import pytest

from bera_price_tracker.application.provider_acquisition import UNAVAILABLE
from bera_price_tracker.gui import search_diagnostics
from bera_price_tracker.gui.brands import PLATFORM_ALIBABA, PLATFORM_FACEBOOK, PLATFORM_ML
from bera_price_tracker.gui.state import UI_EMPTY, UI_ERROR, UI_SUCCESS, TrackerState


def test_successful_zero_results_is_empty_not_error() -> None:
    diagnostic = search_diagnostics.alibaba_diagnostic(
        ui_status=UI_EMPTY,
        summary={"requested": "1", "fetched": "0", "usable": "0"},
        requested_limit=1,
        usable_rows=0,
    )
    assert diagnostic["outcome"] == "empty"
    assert diagnostic["outcome_label"] == "Sin resultados"
    assert diagnostic["status"] != UI_ERROR


def test_provider_exception_is_error() -> None:
    diagnostic = search_diagnostics.facebook_diagnostic(
        ui_status=UI_ERROR,
        summary={},
        requested_limit=1,
        usable_rows=0,
        error="No se pudo consultar Facebook Marketplace.",
    )
    assert diagnostic["outcome"] == "error"
    assert diagnostic["outcome_label"] == "Error"
    assert "No se pudo consultar" in diagnostic["detail"]


def test_facebook_filtering_metrics_are_truthful() -> None:
    diagnostic = search_diagnostics.facebook_diagnostic(
        ui_status=UI_SUCCESS,
        summary={
            "requested": "3",
            "fetched": "3",
            "usable": "1",
            "free_price": "1",
            "invalid_price": "1",
        },
        requested_limit=3,
        usable_rows=1,
    )
    assert diagnostic["requested"] == "3"
    assert diagnostic["fetched"] == "3"
    assert diagnostic["usable"] == "1"
    labels = {item["label"]: item["value"] for item in diagnostic["lines"]}
    assert labels["Gratis"] == "1"
    assert labels["Precio inválido"] == "1"
    assert "0" not in {item["value"] for item in diagnostic["lines"] if item["label"] == "Gratis"}


def test_unavailable_fetched_is_not_invented() -> None:
    diagnostic = search_diagnostics.alibaba_diagnostic(
        ui_status=UI_SUCCESS,
        summary={"requested": "5", "usable": "2"},
        requested_limit=5,
        usable_rows=2,
    )
    assert diagnostic["fetched"] == UNAVAILABLE


def test_diagnostics_clear_on_nueva_busqueda() -> None:
    state = TrackerState()
    state.apply_complete_search_fixture()
    state.toggle_provider_diagnostic(PLATFORM_FACEBOOK)
    assert state.diagnostic_open_platforms == [PLATFORM_FACEBOOK]
    cards = state.marketplace_summaries
    facebook = next(card for card in cards if card.platform_id == PLATFORM_FACEBOOK)
    assert facebook.details_available is True
    assert facebook.diagnostic_outcome == "ready"
    state.start_new_search()
    assert state.diagnostic_open_platforms == []
    assert state.alibaba_summary == {}
    assert state.facebook_product_summary == {}
    assert state.ml_summary == {}
    idle = state.marketplace_summaries
    assert all(card.diagnostic_outcome in {"", "idle"} or card.status == "empty" for card in idle)


def test_nueva_busqueda_does_not_call_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    from bera_price_tracker.gui import services

    calls: list[str] = []
    monkeypatch.setattr(services, "run_alibaba_search", lambda *_a, **_k: calls.append("a"))
    monkeypatch.setattr(
        services, "run_facebook_product_search", lambda *_a, **_k: calls.append("f")
    )
    monkeypatch.setattr(services, "run_mercadolibre_search", lambda *_a, **_k: calls.append("m"))
    state = TrackerState()
    state.apply_zero_result_diagnostic_fixture()
    alibaba = next(
        card for card in state.marketplace_summaries if card.platform_id == PLATFORM_ALIBABA
    )
    assert alibaba.status_label == "Sin resultados"
    assert alibaba.result_count == "0"
    state.start_new_search()
    assert calls == []
    assert state.export_enabled is False


def test_empty_alibaba_card_exposes_requested_fetched_usable() -> None:
    state = TrackerState()
    state.apply_zero_result_diagnostic_fixture()
    alibaba = next(
        card for card in state.marketplace_summaries if card.platform_id == PLATFORM_ALIBABA
    )
    values = {line.label: line.value for line in alibaba.diagnostic_lines}
    assert values["Solicitados"] == "1"
    assert values["Recibidos"] == "0"
    assert values["Válidos"] == "0"


def test_diagnostic_usable_fallback_ignores_view_filters() -> None:
    state = TrackerState()
    state.apply_complete_search_fixture()
    state.alibaba_summary.pop("usable")
    state.alibaba_price_min = "999"
    assert state.alibaba_visible_rows == []
    alibaba = next(
        card for card in state.marketplace_summaries if card.platform_id == PLATFORM_ALIBABA
    )
    values = {line.label: line.value for line in alibaba.diagnostic_lines}
    assert values["Válidos"] == "1"


def test_attach_diagnostics_keeps_error_distinct_from_empty() -> None:
    cards = search_diagnostics.attach_diagnostics(
        [
            {"platform_id": PLATFORM_ALIBABA, "status": "error", "status_label": "Error"},
            {
                "platform_id": PLATFORM_ML,
                "status": "empty-results",
                "status_label": "Sin resultados",
            },
        ],
        [
            search_diagnostics.alibaba_diagnostic(
                ui_status=UI_ERROR,
                summary={},
                requested_limit=1,
                usable_rows=0,
                error="falló",
            ),
            search_diagnostics.mercadolibre_diagnostic(
                ui_status=UI_EMPTY,
                summary={"requested": "1", "fetched": "0", "usable": "0"},
                requested_limit=1,
                usable_rows=0,
            ),
        ],
    )
    assert cards[0]["status"] == "error"
    assert cards[0]["status_label"] == "Error"
    assert cards[1]["status"] == "empty-results"
    assert cards[1]["status_label"] == "Sin resultados"
