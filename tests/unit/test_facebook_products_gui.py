"""Offline GUI/service coverage for generic Facebook comparables."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

import pytest

from bera_price_tracker.application.facebook_products import SearchFacebookMarketplaceProducts
from bera_price_tracker.application.ports import FacebookMarketplaceProductSearchProvider
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


def test_unknown_currency_is_visible_but_excluded_from_statistics() -> None:
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
    assert payload["statistics"] == []


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
        services.sanitize_facebook_product_error(RuntimeError("Apify token missing"))
        == services.FACEBOOK_PRODUCTS_GENERIC_USER_MESSAGE
    )
