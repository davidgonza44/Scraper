"""Offline Mercado Libre Venezuela benchmark tests. No Actor runs. No MiniMax."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from bera_price_tracker.application.alibaba_relevance import calculate_listing_relevance
from bera_price_tracker.application.mercadolibre_benchmark import (
    CURRENCY_MISMATCH_MESSAGE,
    DEFAULT_BENCHMARK_RELEVANCE,
    SORT_PRICE_ASC,
    MercadoLibreMarketBenchmark,
    MercadoLibreScoredListing,
    apply_mercadolibre_table_view,
    build_market_benchmark,
    compare_landed_to_local_market,
    score_listings,
)
from bera_price_tracker.application.mercadolibre_relevance import MercadoLibreListingRelevance
from bera_price_tracker.application.mercadolibre_statistics import (
    calculate_mercadolibre_price_statistics,
    dominant_currency,
    explicit_currency,
)
from bera_price_tracker.application.ports import MarketplaceSourceUnavailable
from bera_price_tracker.application.services import (
    SearchMercadoLibreProducts,
    validate_mercadolibre_search,
)
from bera_price_tracker.config import DEFAULT_APIFY_MERCADOLIBRE_ACTOR, Settings
from bera_price_tracker.domain.mercadolibre import MercadoLibreListing
from bera_price_tracker.domain.models import MarketplaceSource
from bera_price_tracker.gui import services as gui_services
from bera_price_tracker.infrastructure.providers.mercadolibre_apify import (
    ApifyMercadoLibreClient,
    build_mercadolibre_run_input,
    is_venezuela_listing,
    map_mercadolibre_item,
    parse_mercadolibre_price,
    permalink_is_venezuela,
)
from tests.fixtures.mercadolibre_mlv import PILOT_ITEMS, PILOT_QUERY

SRC = Path(__file__).resolve().parents[2] / "src"
ML_PATHS = (
    SRC / "bera_price_tracker" / "application" / "mercadolibre_benchmark.py",
    SRC / "bera_price_tracker" / "application" / "mercadolibre_relevance.py",
    SRC / "bera_price_tracker" / "application" / "mercadolibre_statistics.py",
    SRC / "bera_price_tracker" / "domain" / "mercadolibre.py",
    SRC / "bera_price_tracker" / "infrastructure" / "providers" / "mercadolibre_apify.py",
)
ALIBABA_UNCHANGED = (
    SRC / "bera_price_tracker" / "application" / "alibaba_relevance.py",
    SRC / "bera_price_tracker" / "application" / "alibaba_statistics.py",
    SRC / "bera_price_tracker" / "application" / "alibaba_score.py",
    SRC / "bera_price_tracker" / "infrastructure" / "providers" / "alibaba.py",
)
FACEBOOK_UNCHANGED = (
    SRC / "bera_price_tracker" / "infrastructure" / "providers" / "facebook_marketplace.py",
    SRC / "bera_price_tracker" / "infrastructure" / "providers" / "apify.py",
    SRC / "bera_price_tracker" / "application" / "facebook_venezuela_price.py",
)


def _map_pilot() -> list[MercadoLibreListing]:
    listings = [map_mercadolibre_item(item) for item in PILOT_ITEMS]
    return [item for item in listings if item is not None]


class _FakeActor:
    def __init__(self, owner: _FakeClient) -> None:
        self._owner = owner

    def call(self, *, run_input: dict[str, object]) -> dict[str, object]:
        self._owner.calls.append(run_input)
        return {"status": "SUCCEEDED", "defaultDatasetId": "ds-mlv"}


class _FakeDataset:
    def __init__(self, items: list[object]) -> None:
        self.items = items

    def list_items(self, *, limit: int) -> _FakeDataset:
        return _FakeDataset(self.items[:limit])


class _FakeClient:
    def __init__(self, items: list[object]) -> None:
        self.items = items
        self.calls: list[dict[str, object]] = []

    def actor(self, actor_id: str) -> _FakeActor:
        assert actor_id == DEFAULT_APIFY_MERCADOLIBRE_ACTOR
        return _FakeActor(self)

    def dataset(self, dataset_id: str) -> _FakeDataset:
        assert dataset_id == "ds-mlv"
        return _FakeDataset(self.items)


def test_mapper_uses_real_actor_fields() -> None:
    listing = map_mercadolibre_item(PILOT_ITEMS[1])
    assert listing is not None
    assert listing.external_id == "MLV740384095"
    assert listing.title.startswith("Mouse Inalambrico")
    assert listing.permalink is not None
    assert listing.price == Decimal("4.95")
    assert listing.currency == "USD"
    assert listing.original_price is None
    assert listing.condition is None
    assert listing.seller_name == "77 Innovación"
    assert listing.free_shipping is False
    assert listing.country == "Venezuela"
    assert listing.thumbnail_url is not None


def test_identity_is_source_plus_item_id() -> None:
    listing = map_mercadolibre_item(PILOT_ITEMS[0])
    assert listing is not None
    assert listing.source is MarketplaceSource.MERCADO_LIBRE
    assert listing.external_id == "MLV982107672"
    assert listing.key.external_id == "MLV982107672"
    assert listing.key.source is MarketplaceSource.MERCADO_LIBRE
    assert listing.external_id != listing.title


def test_url_venezuela_is_accepted() -> None:
    url = "https://articulo.mercadolibre.com.ve/MLV-1"
    assert permalink_is_venezuela(url)
    assert is_venezuela_listing(external_id="X", site_id=None, permalink=url, country=None)


def test_geography_mismatch_is_skipped() -> None:
    raw = {
        "id": "MLA123",
        "siteId": "MLA",
        "title": "Mouse inalámbrico",
        "permalink": "https://articulo.mercadolibre.com.ar/MLA-123",
        "price": "10",
        "currency": "ARS",
        "location": {"country": "Argentina"},
    }
    assert map_mercadolibre_item(raw) is None


def test_explicit_usd_is_not_inferred() -> None:
    listing = map_mercadolibre_item(PILOT_ITEMS[0])
    assert listing is not None
    assert listing.currency == "USD"
    assert listing.price == Decimal("3.99")
    assert "$" not in (listing.currency or "")


def test_ves_is_kept_separate_from_usd() -> None:
    usd = MercadoLibreListing(
        external_id="MLV1",
        title="Mouse inalámbrico",
        price=Decimal("4.95"),
        currency="USD",
    )
    ves = MercadoLibreListing(
        external_id="MLV2",
        title="Mouse inalámbrico",
        price=Decimal("450.00"),
        currency="VES",
    )
    usd_stats = calculate_mercadolibre_price_statistics([usd, ves], currency="USD")
    ves_stats = calculate_mercadolibre_price_statistics([usd, ves], currency="VES")
    assert usd_stats.priced_listings == 1
    assert usd_stats.minimum == Decimal("4.95")
    assert ves_stats.priced_listings == 1
    assert ves_stats.minimum == Decimal("450.00")
    assert dominant_currency([usd, ves]) in {"USD", "VES"}


def test_no_fx_in_new_mercadolibre_modules() -> None:
    banned = ("get_rate", "exchange_rate", "fx_rate", "convert_to_usd", "minimax", "ollama")
    for path in ML_PATHS:
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for token in banned:
            assert token not in lowered


def test_missing_seller_and_null_condition_map() -> None:
    listing = map_mercadolibre_item(PILOT_ITEMS[0])
    assert listing is not None
    assert listing.seller_name is None
    assert listing.condition is None
    assert listing.original_price == Decimal("4")


def test_condition_null_and_missing_seller_do_not_fail() -> None:
    listing = map_mercadolibre_item(PILOT_ITEMS[4])
    assert listing is not None
    assert listing.seller_name is None
    assert listing.condition is None


def test_prices_are_decimal_only() -> None:
    for listing in _map_pilot():
        assert listing.price is None or isinstance(listing.price, Decimal)
        assert not isinstance(listing.price, float)
        assert listing.original_price is None or isinstance(listing.original_price, Decimal)


def test_json_float_price_becomes_decimal() -> None:
    assert parse_mercadolibre_price(3.99) == Decimal("3.99")
    assert isinstance(parse_mercadolibre_price(3.99), Decimal)


def test_relevance_normalizes_diacritics() -> None:
    wired = calculate_listing_relevance(PILOT_QUERY, PILOT_ITEMS[0]["title"])
    wireless = calculate_listing_relevance(PILOT_QUERY, PILOT_ITEMS[3]["title"])
    assert wireless.relevance_score >= 80
    assert wired.relevance_score < wireless.relevance_score
    assert wired.relevance_score < 60


def test_wired_g102_is_less_relevant_than_inalambrico() -> None:
    scored = score_listings(PILOT_QUERY, _map_pilot())
    by_id = {item.listing.external_id: item for item in scored}
    assert by_id["MLV982107672"].relevance_score < 60
    assert by_id["MLV738748594"].relevance_score >= 80


def test_benchmark_percentiles_use_relevance_filter() -> None:
    scored = score_listings(PILOT_QUERY, _map_pilot())
    benchmark = build_market_benchmark(scored, min_relevance=DEFAULT_BENCHMARK_RELEVANCE)
    assert benchmark.currency == "USD"
    assert benchmark.comparable_count == 8
    assert benchmark.p25 is not None
    assert benchmark.median is not None
    assert benchmark.p75 is not None
    assert benchmark.p25 <= benchmark.median <= benchmark.p75
    assert all(
        isinstance(value, Decimal) for value in (benchmark.p25, benchmark.median, benchmark.p75)
    )


def test_outliers_are_flagged_without_mutating_source() -> None:
    listings = _map_pilot()
    stats = calculate_mercadolibre_price_statistics(listings, currency="USD")
    assert stats.lower_fence is not None
    assert stats.upper_fence is not None
    original_prices = [item.price for item in listings]
    assert original_prices[0] == Decimal("3.99")


def test_local_filters_do_not_mutate_or_request() -> None:
    scored = score_listings(PILOT_QUERY, _map_pilot())
    visible = apply_mercadolibre_table_view(
        scored,
        sort=SORT_PRICE_ASC,
        min_relevance=60,
        minimum=Decimal("4"),
        maximum=Decimal("8"),
    )
    assert scored[0].listing.external_id == "MLV982107672"
    assert all(item.relevance_score >= 60 for item in visible)
    prices = [item.listing.price for item in visible if item.listing.price is not None]
    assert prices == sorted(prices)


def _scored(listing: MercadoLibreListing, score: int = 100) -> MercadoLibreScoredListing:
    return MercadoLibreScoredListing(
        listing=listing,
        relevance=MercadoLibreListingRelevance(
            relevance_score=score,
            matched_tokens=1,
            total_query_tokens=1,
            exact_phrase_match=True,
        ),
    )


def test_landed_cost_usd_comparison_and_margins() -> None:
    benchmark = MercadoLibreMarketBenchmark(
        comparable_count=3,
        currency="USD",
        p25=Decimal("9.50"),
        median=Decimal("11.00"),
        p75=Decimal("13.50"),
        typical_price=Decimal("11.00"),
        minimum=Decimal("9.50"),
        maximum=Decimal("13.50"),
        average=Decimal("11.333333"),
        iqr=Decimal("4.00"),
        trimmed_mean=Decimal("11.00"),
        outlier_count=0,
        total_results=3,
    )
    comparison = compare_landed_to_local_market(
        landed_cost_per_unit=Decimal("6.43"),
        landed_currency="USD",
        benchmark=benchmark,
    )
    assert comparison.comparable is True
    assert comparison.conservative is not None
    assert comparison.typical is not None
    assert comparison.high is not None
    assert comparison.conservative.profit_per_unit == Decimal("3.07")
    assert comparison.typical.profit_per_unit == Decimal("4.57")
    assert comparison.high.profit_per_unit == Decimal("7.07")
    assert comparison.conservative.margin_percent == Decimal("32.32")
    assert comparison.typical.margin_percent == Decimal("41.55")
    assert comparison.high.margin_percent == Decimal("52.37")


def test_negative_profitability_is_not_clamped() -> None:
    listing = MercadoLibreListing(
        external_id="MLV-A", title="mouse", price=Decimal("7.00"), currency="USD"
    )
    benchmark = build_market_benchmark(
        [_scored(listing), _scored(listing), _scored(listing)],
        min_relevance=0,
    )
    comparison = compare_landed_to_local_market(
        landed_cost_per_unit=Decimal("8.00"),
        landed_currency="USD",
        benchmark=benchmark,
    )
    assert comparison.typical is not None
    assert comparison.typical.profit_per_unit == Decimal("-1.00")
    assert comparison.typical.margin_percent is not None
    assert comparison.typical.margin_percent < 0


def test_currency_mismatch_does_not_convert() -> None:
    benchmark = build_market_benchmark(
        [
            _scored(
                MercadoLibreListing(
                    external_id="MLV-A", title="mouse", price=Decimal("100"), currency="VES"
                )
            )
        ],
        min_relevance=0,
    )
    comparison = compare_landed_to_local_market(
        landed_cost_per_unit=Decimal("6.43"),
        landed_currency="USD",
        benchmark=benchmark,
    )
    assert comparison.comparable is False
    assert comparison.message == CURRENCY_MISMATCH_MESSAGE
    assert comparison.conservative is None


def test_malformed_item_is_skipped() -> None:
    assert map_mercadolibre_item("nope") is None
    assert map_mercadolibre_item({"title": "solo titulo"}) is None
    assert map_mercadolibre_item({"id": "MLV1"}) is None


def test_search_service_uses_provider_once() -> None:
    client = _FakeClient(list(PILOT_ITEMS))
    provider = ApifyMercadoLibreClient(
        _api_token="token",
        client_factory=lambda _token: client,
    )
    service = SearchMercadoLibreProducts(provider=provider)
    listings = service.execute(PILOT_QUERY, 10)
    assert len(client.calls) == 1
    assert client.calls[0] == {
        "siteId": "MLV",
        "searchQueries": [PILOT_QUERY],
        "maxItems": 10,
    }
    assert len(listings) == 10
    assert all(item.source is MarketplaceSource.MERCADO_LIBRE for item in listings)


def test_failed_run_is_unavailable_without_retry() -> None:
    class _EmptyDataset:
        items: list[object] = []

        def list_items(self, *, limit: int) -> _EmptyDataset:
            raise AssertionError("must not read dataset after FAILED")

    class _Failing:
        def __init__(self) -> None:
            self.calls = 0

        def actor(self, actor_id: str) -> _Failing:
            return self

        def call(self, *, run_input: dict[str, object]) -> dict[str, object]:
            self.calls += 1
            return {"status": "FAILED"}

        def dataset(self, dataset_id: str) -> _EmptyDataset:
            raise AssertionError("must not read dataset after FAILED")

    failing = _Failing()
    provider = ApifyMercadoLibreClient(_api_token="token", client_factory=lambda _token: failing)
    with pytest.raises(MarketplaceSourceUnavailable):
        provider.search(PILOT_QUERY, 10)
    assert failing.calls == 1


def test_run_input_is_mlv_only() -> None:
    payload = build_mercadolibre_run_input(query="mouse inalámbrico", limit=10)
    assert payload == {
        "siteId": "MLV",
        "searchQueries": ["mouse inalámbrico"],
        "maxItems": 10,
    }
    assert "proxyConfiguration" not in payload


def test_token_never_in_repr() -> None:
    client = ApifyMercadoLibreClient(_api_token="apify-secret-token")
    assert "apify-secret-token" not in repr(client)
    settings = Settings.from_env(
        {
            "BERA_TRACKER_APIFY_API_TOKEN": "apify-secret-token",
            "BERA_TRACKER_APIFY_MERCADOLIBRE_ACTOR": DEFAULT_APIFY_MERCADOLIBRE_ACTOR,
        }
    )
    assert "apify-secret-token" not in repr(settings)


def test_validate_mercadolibre_search_bounds() -> None:
    assert validate_mercadolibre_search("  mouse  ", 10) == ("mouse", 10)
    with pytest.raises(ValueError, match="query"):
        validate_mercadolibre_search("  ", 10)
    with pytest.raises(ValueError, match="limit"):
        validate_mercadolibre_search("mouse", 0)
    with pytest.raises(ValueError, match="limit"):
        validate_mercadolibre_search("mouse", 51)


def test_gui_search_uses_injected_service() -> None:
    class _Service:
        def execute(self, query: str, limit: int) -> list[MercadoLibreListing]:
            assert query == PILOT_QUERY
            assert limit == 10
            return _map_pilot()

    payload = gui_services.run_mercadolibre_search(PILOT_QUERY, 10, search_service=_Service())
    assert payload["ui_status"] == "SUCCESS"
    assert len(payload["results"]) == 10
    g102 = next(row for row in payload["results"] if row["external_id"] == "MLV982107672")
    assert g102["seller_name"] == "—"
    assert g102["condition"] == "—"
    assert g102["relevance_value"] < 60


def test_alibaba_files_unchanged_by_this_module() -> None:
    for path in ALIBABA_UNCHANGED:
        text = path.read_text(encoding="utf-8")
        assert "mercadolibre_apify" not in text
        assert "SearchMercadoLibreProducts" not in text


def test_facebook_files_unchanged_by_this_module() -> None:
    for path in FACEBOOK_UNCHANGED:
        text = path.read_text(encoding="utf-8")
        assert "mercadolibre_apify" not in text
        assert "mouse inalámbrico" not in text


def test_explicit_currency_rejects_dollar_sign() -> None:
    listing = MercadoLibreListing(
        external_id="MLV9",
        title="Mouse",
        price=Decimal("4"),
        currency=None,
    )
    assert explicit_currency(listing) is None
    object.__setattr__(listing, "currency", "$")
    assert explicit_currency(listing) is None


CASE_A_PRICES = ("3.99", "4.95", "4.99", "7.99", "13.99", "14.99", "16.15")
LANDED_USD_ROW = {"landed_cost_per_unit_raw": "2.00", "currency": "USD"}


def _price_map_row(
    external_id: str, price: str, *, relevance: int = 80, is_outlier: bool = False
) -> dict[str, object]:
    return {
        "external_id": external_id,
        "title": f"Mouse {price}",
        "price_raw": price,
        "currency": "USD",
        "representative": price,
        "relevance_value": relevance,
        "is_outlier": is_outlier,
    }


def _case_a_map_rows() -> list[dict[str, object]]:
    return [
        _price_map_row(f"MLV{index}", price) for index, price in enumerate(CASE_A_PRICES, start=1)
    ]


def _state_with_case_a_rows() -> Any:
    from bera_price_tracker.gui.state import MercadoLibreResultRow, TrackerState

    state = TrackerState()
    state.ml_results = [
        MercadoLibreResultRow(
            external_id=f"MLV{index}",
            title=f"Mouse {price}",
            price=f"${price}",
            price_raw=price,
            currency="USD",
            representative=price,
            relevance_value=80,
        )
        for index, price in enumerate(CASE_A_PRICES, start=1)
    ]
    state.ml_min_relevance = 0
    state.alibaba_landed_has_result = True
    state.alibaba_landed_result = dict(LANDED_USD_ROW)
    return state


def _live_summary(state: Any) -> dict[str, str]:
    summary = state.ml_live_summary
    if callable(summary):
        summary = summary()
    return dict(summary)


def test_summary_and_landed_compare_share_price_max_subset() -> None:
    rows = _case_a_map_rows()
    filtered = gui_services.mercadolibre_benchmark_source_rows(rows, price_max="8")
    prices = [Decimal(str(row["price_raw"])) for row in filtered]
    assert prices == [Decimal("3.99"), Decimal("4.95"), Decimal("4.99"), Decimal("7.99")]
    assert Decimal("13.99") not in prices
    summary = gui_services.mercadolibre_summary_from_rows(
        filtered, min_relevance=0, total_results=len(rows)
    )
    comparison = gui_services.compare_mercadolibre_with_landed_cost(
        filtered, LANDED_USD_ROW, min_relevance=0
    )
    assert comparison["conservative_price"] == summary["p25"]
    assert comparison["typical_price"] == summary["mediana"]
    assert comparison["high_price"] == summary["p75"]


def test_state_landed_compare_matches_visible_cards_after_price_max() -> None:
    state = _state_with_case_a_rows()
    state.ml_price_max = "8"
    summary = _live_summary(state)
    state.compare_ml_with_landed_cost()
    assert state.ml_has_comparison is True
    assert state.ml_comparison["conservative_price"] == summary["p25"]
    assert state.ml_comparison["typical_price"] == summary["mediana"]
    assert state.ml_comparison["high_price"] == summary["p75"]


def test_changing_relevance_invalidates_landed_comparison() -> None:
    state = _state_with_case_a_rows()
    state.compare_ml_with_landed_cost()
    assert state.ml_has_comparison is True
    assert state.ml_comparison["comparable"] == "1"
    state.set_ml_min_relevance("60+")
    assert state.ml_has_comparison is False
    assert state.ml_comparison == {}


def test_changing_price_min_invalidates_landed_comparison() -> None:
    state = _state_with_case_a_rows()
    state.compare_ml_with_landed_cost()
    state.set_ml_price_min("4")
    assert state.ml_has_comparison is False
    assert state.ml_comparison == {}


def test_changing_price_max_invalidates_landed_comparison() -> None:
    state = _state_with_case_a_rows()
    state.compare_ml_with_landed_cost()
    state.set_ml_price_max("8")
    assert state.ml_has_comparison is False
    assert state.ml_comparison == {}


def test_clear_filters_invalidates_landed_comparison() -> None:
    state = _state_with_case_a_rows()
    state.compare_ml_with_landed_cost()
    state.clear_ml_filters()
    assert state.ml_has_comparison is False
    assert state.ml_comparison == {}


def test_sort_does_not_invalidate_landed_comparison() -> None:
    state = _state_with_case_a_rows()
    state.compare_ml_with_landed_cost()
    snapshot = dict(state.ml_comparison)
    state.set_ml_sort("Precio: menor a mayor")
    assert state.ml_has_comparison is True
    assert state.ml_comparison == snapshot
    state.set_ml_sort("Precio: mayor a menor")
    assert state.ml_has_comparison is True
    assert state.ml_comparison == snapshot
    state.set_ml_sort("Original")
    assert state.ml_has_comparison is True
    assert state.ml_comparison == snapshot


def test_hide_outliers_is_visual_and_does_not_change_benchmark() -> None:
    rows = _case_a_map_rows()
    rows[-1]["is_outlier"] = True
    visible = gui_services.mercadolibre_benchmark_source_rows(rows)
    assert [row["price_raw"] for row in visible] == list(CASE_A_PRICES)
    state = _state_with_case_a_rows()
    state.ml_results[-1].is_outlier = True
    before = _live_summary(state)
    state.compare_ml_with_landed_cost()
    snapshot = dict(state.ml_comparison)
    state.set_ml_hide_outliers(True)
    assert state.ml_has_comparison is True
    assert state.ml_comparison == snapshot
    assert _live_summary(state)["p25"] == before["p25"]
    assert _live_summary(state)["mediana"] == before["mediana"]
    assert _live_summary(state)["p75"] == before["p75"]


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
    state.alibaba_landed_rate_confirmed = False
    state.alibaba_landed_sale_price = "10.00"
    state.alibaba_landed_margin = "30"


def test_successful_landed_recalc_invalidates_ml_comparison() -> None:
    state = _state_with_case_a_rows()
    state.compare_ml_with_landed_cost()
    assert state.ml_has_comparison is True
    previous = dict(state.ml_comparison)
    _fill_valid_landed_inputs(state)
    state.calculate_alibaba_landed_cost()
    assert state.ml_has_comparison is False
    assert state.ml_comparison == {}
    assert state.alibaba_landed_has_result is True
    assert state.alibaba_landed_result["landed_cost_per_unit"] == "$6.43"
    state.compare_ml_with_landed_cost()
    assert state.ml_has_comparison is True
    assert state.ml_comparison["landed"] != previous["landed"]


def test_failed_landed_recalc_invalidates_ml_comparison() -> None:
    state = _state_with_case_a_rows()
    state.compare_ml_with_landed_cost()
    assert state.ml_has_comparison is True
    state.alibaba_landed_quantity = "40"
    state.alibaba_landed_supplier_price = "4.03"
    state.calculate_alibaba_landed_cost()
    assert state.ml_has_comparison is False
    assert state.ml_comparison == {}
    assert state.alibaba_landed_has_result is False
    assert state.alibaba_landed_result == {}
    assert state.alibaba_landed_error != ""


def test_editing_landed_inputs_does_not_invalidate_ml_comparison() -> None:
    state = _state_with_case_a_rows()
    state.compare_ml_with_landed_cost()
    snapshot = dict(state.ml_comparison)
    state.set_alibaba_landed_rate("900")
    state.set_alibaba_landed_quantity("50")
    state.set_alibaba_landed_insurance("10")
    assert state.ml_has_comparison is True
    assert state.ml_comparison == snapshot
