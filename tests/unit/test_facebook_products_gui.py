"""Offline GUI/service coverage for generic Facebook comparables."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest

from bera_price_tracker.application.facebook_products import SearchFacebookMarketplaceProducts
from bera_price_tracker.application.ports import FacebookMarketplaceProductSearchProvider
from bera_price_tracker.domain.money import (
    DOLLAR_SYMBOL_EVIDENCE,
    FACEBOOK_VENEZUELA_EVIDENCE,
    NormalizationStatus,
)
from bera_price_tracker.gui import services
from bera_price_tracker.gui.state import (
    AlibabaResultRow,
    FacebookCurrencyStatsRow,
    FacebookProductResultRow,
    TrackerState,
)
from bera_price_tracker.infrastructure.providers.apify import (
    ApifyFacebookListing,
    ApifyFacebookMarketplaceClient,
    ApifyFacebookResult,
)
from bera_price_tracker.infrastructure.providers.facebook_products import (
    FacebookMarketplaceProductSearch,
)


@dataclass
class FakeClient:
    records: tuple[ApifyFacebookListing, ...]
    calls: int = 0

    def fetch(self, keyword: str, city: str, limit: int) -> ApifyFacebookResult:
        self.calls += 1
        return ApifyFacebookResult(records=self.records, fetched=len(self.records))


def _record(
    product_id: str,
    title: str,
    price: Decimal | None,
    formatted: str | None,
    currency: str | None = "USD",
) -> ApifyFacebookListing:
    return ApifyFacebookListing(
        product_id=product_id,
        title=title,
        price=price,
        currency=currency,
        formatted_price=formatted,
        location="Caracas",
        url=f"https://facebook.com/marketplace/item/{product_id}",
    )


def test_service_never_exposes_free_zero_or_missing_prices_to_ui() -> None:
    fake = FakeClient(
        (
            _record("valid", "Free Shipping Wireless Mouse", Decimal("15"), "$15"),
            _record("free", "Headphones", None, "Free"),
            _record("gratis", "Clothing", Decimal("10"), "Gratis"),
            _record("zero", "Pump", None, "$0.00"),
            _record("missing", "Automotive part", None, None),
        )
    )
    provider = FacebookMarketplaceProductSearch(
        cast(ApifyFacebookMarketplaceClient, fake),
        clock=lambda: datetime(2026, 8, 25, tzinfo=UTC),
    )
    service = SearchFacebookMarketplaceProducts(
        cast(FacebookMarketplaceProductSearchProvider, provider)
    )

    payload = services.run_facebook_product_search(
        "wireless mouse",
        "caracas",
        5,
        search_service=service,
    )

    assert fake.calls == 1
    assert [row["external_id"] for row in payload["results"]] == ["valid"]
    rendered = str(payload["results"])
    assert "Free Shipping Wireless Mouse" in rendered
    assert "Headphones" not in rendered
    assert "Clothing" not in rendered
    assert "Pump" not in rendered
    assert "Automotive part" not in rendered
    assert payload["summary"]["free_price"] == "2"
    assert payload["summary"]["invalid_price"] == "2"
    assert payload["summary"]["usable"] == "1"
    assert len(payload["statistics"]) == 1
    assert payload["statistics"][0]["basis"] == "source_currency"
    assert payload["statistics"][0]["count"] == "1"


def test_real_vef_fixture_shows_source_and_normalized_facebook_usd() -> None:
    observed = (
        ("25", "VEF25"),
        ("4", "VEF4"),
        ("15", "VEF15"),
        ("5", "VEF5"),
        ("10", "VEF10"),
    )
    fake = FakeClient(
        tuple(
            _record(
                f"real-{index}",
                "Mouse inalámbrico",
                Decimal(amount),
                formatted,
                "VEF",
            )
            for index, (amount, formatted) in enumerate(observed)
        )
    )
    provider = FacebookMarketplaceProductSearch(
        cast(ApifyFacebookMarketplaceClient, fake),
        clock=lambda: datetime(2026, 8, 25, tzinfo=UTC),
    )
    payload = services.run_facebook_product_search(
        "mouse inalámbrico",
        "caracas",
        5,
        search_service=SearchFacebookMarketplaceProducts(
            cast(FacebookMarketplaceProductSearchProvider, provider)
        ),
    )

    assert fake.calls == 1
    assert payload["ui_status"] == "SUCCESS"
    assert len(payload["results"]) == 5
    for row, (amount, formatted) in zip(payload["results"], observed, strict=True):
        assert row["price"] == f"{Decimal(amount):.2f} VEF"
        assert row["price_raw"] == amount
        assert row["currency"] == "VEF"
        assert row["formatted_price"] == formatted
        assert row["source_price_note"] == (f"{formatted} · etiqueta fuente del proveedor Facebook")
        assert row["usd_price"] == f"USD: ${Decimal(amount):.2f}"
        assert row["usd_amount"] == f"{Decimal(amount):.2f}"
        assert row["usd_normalization_status"] == NormalizationStatus.NORMALIZED.value
        assert row["usd_evidence"] == FACEBOOK_VENEZUELA_EVIDENCE
        assert row["usd_basis"] == "facebook_venezuela_normalized_usd"
        assert "sin FX" in row["usd_provenance"]

    assert payload["statistics"] == [
        {
            "currency": "USD",
            "label": "USD normalizado · Facebook Venezuela",
            "basis": "facebook_venezuela_normalized_usd",
            "source_currencies": "VEF",
            "normalization_status": "normalized",
            "evidence": FACEBOOK_VENEZUELA_EVIDENCE,
            "provenance": "Mismo valor numérico de la etiqueta VEF del proveedor; sin FX.",
            "count": "5",
            "minimum": "$4.00",
            "average": "$11.80",
            "median": "$10.00",
            "maximum": "$25.00",
            "p25": "$5.00",
            "p75": "$15.00",
            "iqr": "$10.00",
        }
    ]
    assert all(row["currency"] != "VEF" for row in payload["statistics"])


def test_unknown_dollar_currency_is_visible_but_excluded_from_statistics() -> None:
    fake = FakeClient((_record("unknown", "Mouse", Decimal("15"), "$15", None),))
    provider = FacebookMarketplaceProductSearch(
        cast(ApifyFacebookMarketplaceClient, fake),
        clock=lambda: datetime(2026, 8, 25, tzinfo=UTC),
    )
    payload = services.run_facebook_product_search(
        "mouse",
        "caracas",
        1,
        search_service=SearchFacebookMarketplaceProducts(
            cast(FacebookMarketplaceProductSearchProvider, provider)
        ),
    )
    assert payload["results"][0]["currency"] == "UNKNOWN"
    assert payload["results"][0]["price"] == "15.00 · moneda no disponible"
    assert payload["results"][0]["usd_price"] == "USD: $15.00"
    assert (
        payload["results"][0]["usd_normalization_status"] == NormalizationStatus.DOLLAR_SYMBOL.value
    )
    assert payload["results"][0]["usd_evidence"] == ", ".join(
        (DOLLAR_SYMBOL_EVIDENCE, FACEBOOK_VENEZUELA_EVIDENCE)
    )
    assert payload["statistics"] == []


def test_reflex_state_preserves_source_usd_and_statistics_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "results": [
            {
                "external_id": "real-1",
                "title": "Mouse inalámbrico",
                "permalink": "https://facebook.com/marketplace/item/real-1",
                "price": "25.00 VEF",
                "price_raw": "25",
                "currency": "VEF",
                "formatted_price": "VEF25",
                "source_price_note": "VEF25 · etiqueta fuente del proveedor Facebook",
                "usd_price": "USD: $25.00",
                "usd_amount": "25.00",
                "usd_normalization_status": "normalized",
                "usd_evidence": FACEBOOK_VENEZUELA_EVIDENCE,
                "usd_basis": "facebook_venezuela_normalized_usd",
                "usd_provenance": "Facebook Venezuela · mismo valor numérico · sin FX",
                "location": "Caracas",
            }
        ],
        "statistics": [
            {
                "currency": "USD",
                "label": "USD normalizado · Facebook Venezuela",
                "basis": "facebook_venezuela_normalized_usd",
                "source_currencies": "VEF",
                "normalization_status": "normalized",
                "evidence": FACEBOOK_VENEZUELA_EVIDENCE,
                "provenance": "Mismo valor numérico de la etiqueta VEF del proveedor; sin FX.",
                "count": "1",
                "minimum": "$25.00",
                "average": "$25.00",
                "median": "$25.00",
                "maximum": "$25.00",
                "p25": "$25.00",
                "p75": "$25.00",
                "iqr": "$0.00",
            }
        ],
        "summary": {"usable": "1"},
        "ui_status": "SUCCESS",
    }
    monkeypatch.setattr(services, "run_facebook_product_search", lambda *_args: payload)
    state = TrackerState()
    state.facebook_product_query = "mouse inalámbrico"
    state.facebook_product_city = "caracas"

    search_event = cast(Any, TrackerState.search_facebook_products)
    asyncio.run(search_event.fn(state))

    row = state.facebook_product_results[0]
    assert row.source_price_note == "VEF25 · etiqueta fuente del proveedor Facebook"
    assert row.usd_price == "USD: $25.00"
    assert row.usd_amount == "25.00"
    assert row.usd_normalization_status == "normalized"
    assert row.usd_evidence == FACEBOOK_VENEZUELA_EVIDENCE
    assert row.usd_basis == "facebook_venezuela_normalized_usd"
    assert row.usd_provenance == "Facebook Venezuela · mismo valor numérico · sin FX"
    statistics = state.facebook_product_statistics[0]
    assert statistics.label == "USD normalizado · Facebook Venezuela"
    assert statistics.basis == "facebook_venezuela_normalized_usd"
    assert statistics.source_currencies == "VEF"
    assert statistics.normalization_status == "normalized"
    assert statistics.evidence == FACEBOOK_VENEZUELA_EVIDENCE
    assert statistics.provenance.endswith("sin FX.")


def test_selecting_alibaba_product_prepares_only_and_clears_old_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(services, "product_translator_is_configured", lambda: False)
    state = TrackerState()
    state.alibaba_query = "wireless mouse"
    state.alibaba_results = [
        AlibabaResultRow(product_id="A", title="Mouse A"),
        AlibabaResultRow(product_id="B", title="Mouse B"),
    ]
    state.facebook_product_results = [FacebookProductResultRow(external_id="old")]
    state.facebook_product_statistics = [FacebookCurrencyStatsRow(currency="USD")]
    state.facebook_product_provenance = {
        "external_id": "OLD",
        "title": "Old",
        "facebook_query": "old",
    }

    returned_event = state.prepare_facebook_comparables_from_alibaba_result("A")

    assert returned_event is not None
    assert state.marketplace_tab == "facebook_products"
    assert state.facebook_product_query == "wireless mouse"
    assert state.facebook_product_is_loading is False
    assert state.facebook_product_results == []
    assert state.facebook_product_statistics == []
    assert state.facebook_product_provenance == {}
    assert state.facebook_product_alibaba_context == {
        "external_id": "A",
        "title": "Mouse A",
    }


def test_late_search_from_product_a_cannot_overwrite_product_b(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(services, "product_translator_is_configured", lambda: False)
    state = TrackerState()
    state.alibaba_query = "mouse"
    state.alibaba_results = [
        AlibabaResultRow(product_id="A", title="Mouse A"),
        AlibabaResultRow(product_id="B", title="Mouse B"),
    ]
    state.prepare_facebook_comparables_from_alibaba_result("A")
    query_a = state.facebook_product_query
    city_a = state.facebook_product_city
    state.facebook_product_is_loading = True
    state.facebook_product_ui_status = "LOADING"
    state.prepare_facebook_comparables_from_alibaba_result("B")

    state._finalize_facebook_product_search(
        product_id="A",
        query=query_a,
        city=city_a,
        rows=[FacebookProductResultRow(external_id="from-a", title="A result")],
        statistics=[FacebookCurrencyStatsRow(currency="USD", count="1")],
        summary={"usable": "1"},
        ui_status="SUCCESS",
    )

    assert state.facebook_product_alibaba_context["external_id"] == "B"
    assert state.facebook_product_results == []
    assert state.facebook_product_statistics == []
    assert state.facebook_product_summary == {}
    assert state.facebook_product_provenance == {}


def test_successful_search_provenance_is_exact_and_switch_clears_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(services, "product_translator_is_configured", lambda: False)
    state = TrackerState()
    state.alibaba_query = "mouse"
    state.alibaba_results = [
        AlibabaResultRow(product_id="A", title="Mouse A"),
        AlibabaResultRow(product_id="B", title="Mouse B"),
    ]
    state.prepare_facebook_comparables_from_alibaba_result("A")
    state._finalize_facebook_product_search(
        product_id="A",
        query="mouse",
        city="caracas",
        rows=[FacebookProductResultRow(external_id="fb-1", title="Mouse")],
        summary={"usable": "1"},
        ui_status="SUCCESS",
    )
    assert state.facebook_product_provenance == {
        "external_id": "A",
        "title": "Mouse A",
        "facebook_query": "mouse",
    }
    assert state.facebook_product_show_provenance is True

    state.prepare_facebook_comparables_from_alibaba_result("B")

    assert state.facebook_product_provenance == {}
    assert state.facebook_product_results == []
    assert state.facebook_product_ui_status == "INITIAL"
    assert state.facebook_product_show_provenance is False


def test_late_translation_from_product_a_cannot_change_product_b_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(services, "product_translator_is_configured", lambda: True)
    state = TrackerState()
    state.alibaba_results = [
        AlibabaResultRow(product_id="A", title="Mouse A"),
        AlibabaResultRow(product_id="B", title="Pump B"),
    ]
    state.prepare_facebook_comparables_from_alibaba_result("A")
    generation_a = state.facebook_product_translation_generation
    state.prepare_facebook_comparables_from_alibaba_result("B")
    state.set_facebook_product_query("bomba editable")

    state._finalize_facebook_product_translation(
        product_id="A",
        title="Mouse A",
        generation=generation_a,
        translated_title="Ratón A",
        search_query="ratón a",
    )

    assert state.facebook_product_alibaba_context["external_id"] == "B"
    assert state.facebook_product_query == "bomba editable"
    assert state.facebook_product_translated_title == ""


def test_sanitize_facebook_product_error_is_generic() -> None:
    assert (
        services.sanitize_facebook_product_error(ValueError("query must not be blank"))
        == services.FACEBOOK_PRODUCTS_QUERY_ERROR
    )
    assert (
        services.sanitize_facebook_product_error(ValueError("city must not be blank"))
        == services.FACEBOOK_PRODUCTS_CITY_ERROR
    )
    assert (
        services.sanitize_facebook_product_error(TypeError("limit must be an integer"))
        == services.FACEBOOK_PRODUCTS_LIMIT_ERROR
    )
    assert (
        services.sanitize_facebook_product_error(RuntimeError("Apify token missing"))
        == services.FACEBOOK_PRODUCTS_GENERIC_USER_MESSAGE
    )
