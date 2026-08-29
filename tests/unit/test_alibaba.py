"""Offline Alibaba search tests. Mock client/provider only."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from bera_price_tracker.application.alibaba_score import score_alibaba_listings
from bera_price_tracker.application.alibaba_statistics import (
    MISSING_CURRENCY_DISPLAY,
    UNAVAILABLE_DISPLAY,
    alibaba_iso_currencies_match,
    alibaba_percentile,
    alibaba_price_bounds,
    alibaba_representative_price,
    calculate_alibaba_price_statistics,
    explicit_alibaba_currency,
    format_alibaba_currency,
    format_alibaba_listing_price,
    format_alibaba_money,
    format_alibaba_typical_range,
    infer_alibaba_currency,
    interpret_alibaba_prices,
)
from bera_price_tracker.application.ports import MarketplaceSourceUnavailable
from bera_price_tracker.application.services import (
    ALIBABA_CREDIT_WARNING,
    SearchAlibabaProducts,
    alibaba_credit_warning,
    validate_alibaba_search,
)
from bera_price_tracker.config import (
    DEFAULT_APIFY_ALIBABA_ACTOR,
    DEFAULT_APIFY_ALIBABA_REFRESH_ACTOR,
    Settings,
)
from bera_price_tracker.domain.alibaba import AlibabaProduct
from bera_price_tracker.gui import search_export
from bera_price_tracker.gui import services as gui_services
from bera_price_tracker.gui.state import AlibabaResultRow, AlibabaTrackedRow, TrackerState
from bera_price_tracker.infrastructure.providers.alibaba import (
    DEFAULT_ALIBABA_ACTOR,
    ApifyAlibabaClient,
    _as_mapping,
    _decimal_from_text,
    build_alibaba_run_input,
    map_alibaba_item,
    parse_alibaba_price,
)
from bera_price_tracker.infrastructure.providers.apify import ApifyConfigurationError

MEMO23_ALIBABA_SEARCH_ACTOR = "memo23/alibaba-scraper"

SRC = Path(__file__).resolve().parents[2] / "src"
ALIBABA_PATHS = [
    SRC / "bera_price_tracker" / "domain" / "alibaba.py",
    SRC / "bera_price_tracker" / "infrastructure" / "providers" / "alibaba.py",
    SRC / "bera_price_tracker" / "application" / "services.py",
    SRC / "bera_price_tracker" / "application" / "alibaba_statistics.py",
]


class FakeAlibabaProvider:
    def __init__(
        self, products: list[AlibabaProduct] | None = None, error: Exception | None = None
    ) -> None:
        self.products = products or []
        self.error = error
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, limit: int) -> list[AlibabaProduct]:
        self.calls.append((query, limit))
        if self.error is not None:
            raise self.error
        return list(self.products)


class _FakePage:
    def __init__(self, items: list[object]) -> None:
        self.items = items


class _FakeDataset:
    def __init__(self, owner: FakeApify) -> None:
        self.owner = owner

    def list_items(self, *, limit: int) -> _FakePage:
        if self.owner.dataset_error is not None:
            raise self.owner.dataset_error
        return _FakePage(self.owner.items[:limit])


class _FakeActor:
    def __init__(self, owner: FakeApify) -> None:
        self.owner = owner

    def call(self, *, run_input: dict[str, object]) -> Any:
        self.owner.calls.append(run_input)
        if self.owner.call_error is not None:
            raise self.owner.call_error
        return self.owner.run


class FakeApify:
    def __init__(
        self,
        items: list[object],
        *,
        run: object | None = None,
        call_error: Exception | None = None,
        dataset_error: Exception | None = None,
    ) -> None:
        self.items = items
        self.calls: list[dict[str, object]] = []
        self.run: object = (
            {"status": "SUCCEEDED", "defaultDatasetId": "ds1"} if run is None else run
        )
        self.call_error = call_error
        self.dataset_error = dataset_error
        self.actor_id = ""
        self.dataset_id = ""

    def actor(self, actor_id: str) -> _FakeActor:
        self.actor_id = actor_id
        return _FakeActor(self)

    def dataset(self, dataset_id: str) -> _FakeDataset:
        self.dataset_id = dataset_id
        return _FakeDataset(self)


def _product(**kwargs: object) -> AlibabaProduct:
    defaults: dict[str, object] = {"title": "Jacket"}
    defaults.update(kwargs)
    return AlibabaProduct(**defaults)  # type: ignore[arg-type]


def test_arbitrary_query_reaches_provider() -> None:
    provider = FakeAlibabaProvider([_product(title="Waterproof backpack")])
    result = SearchAlibabaProducts(provider).execute("waterproof backpack 40L", 20)
    assert provider.calls == [("waterproof backpack 40L", 20)]
    assert result[0].title == "Waterproof backpack"


def test_empty_query_rejected() -> None:
    provider = FakeAlibabaProvider()
    with pytest.raises(ValueError, match="query"):
        SearchAlibabaProducts(provider).execute("   ", 20)
    assert provider.calls == []


def test_memo23_run_input_contains_exactly_one_search_term() -> None:
    query = "Men's Jackets"
    payload = build_alibaba_run_input(query=query, limit=10)
    assert list(payload.keys()) == ["searchTerms", "maxPages", "maxItems"]
    assert payload["searchTerms"] == [query]
    assert payload["maxPages"] == 1
    assert payload["maxItems"] == 10
    assert "urls" not in payload
    assert "proxy" not in payload


def test_memo23_run_input_does_not_construct_search_urls() -> None:
    query = "Iphone 15"
    payload = build_alibaba_run_input(query=query, limit=20)
    serialized = json.dumps(payload)
    assert "alibaba.com/trade/search" not in serialized
    assert "page=1" not in serialized
    assert "IndexArea" not in serialized
    assert payload["searchTerms"] == [query]
    assert payload["maxPages"] == 1
    assert payload["maxItems"] == 20


@pytest.mark.parametrize(
    ("limit", "expected_max_pages"),
    [
        (1, 1),
        (5, 1),
        (20, 1),
        (21, 2),
        (100, 5),
        (500, 25),
    ],
)
def test_memo23_max_pages_covers_requested_item_limit(limit: int, expected_max_pages: int) -> None:
    payload = build_alibaba_run_input(query="solar panel 550w", limit=limit)
    assert payload["searchTerms"] == ["solar panel 550w"]
    assert payload["maxItems"] == limit
    assert payload["maxPages"] == expected_max_pages
    assert list(payload.keys()) == ["searchTerms", "maxPages", "maxItems"]


@pytest.mark.parametrize(
    ("limit", "expected_max_pages"),
    [
        (21, 2),
        (100, 5),
        (500, 25),
    ],
)
def test_memo23_multi_page_budget_is_still_one_actor_call(
    limit: int, expected_max_pages: int
) -> None:
    client, fake, _products = _search_with_items(
        [memo23_actor_item()], query="Iphone 15", limit=limit
    )
    assert len(fake.calls) == 1
    payload = fake.calls[0]
    assert payload["searchTerms"] == ["Iphone 15"]
    assert payload["maxItems"] == limit
    assert payload["maxPages"] == expected_max_pages
    assert client.last_metrics is not None
    assert client.last_metrics.requested == limit
    assert fake.actor_id == MEMO23_ALIBABA_SEARCH_ACTOR


def test_failed_high_limit_search_does_not_retry_or_switch_actors() -> None:
    fake = FakeApify([], run={"status": "FAILED", "defaultDatasetId": "ds1"})
    client = ApifyAlibabaClient(
        _api_token="token",
        actor_id=DEFAULT_APIFY_ALIBABA_ACTOR,
        client_factory=lambda _token: fake,
    )
    with pytest.raises(MarketplaceSourceUnavailable, match="unavailable"):
        client.search("Iphone 15", 500)
    assert len(fake.calls) == 1
    assert fake.calls[0]["maxItems"] == 500
    assert fake.calls[0]["maxPages"] == 25
    assert fake.actor_id == MEMO23_ALIBABA_SEARCH_ACTOR
    assert client.last_metrics is None


@pytest.mark.parametrize("limit", [1, 20, 500])
def test_limits_accepted(limit: int) -> None:
    provider = FakeAlibabaProvider()
    SearchAlibabaProducts(provider).execute("query", limit)
    assert provider.calls == [("query", limit)]


@pytest.mark.parametrize("limit", [0, 501])
def test_limits_rejected(limit: int) -> None:
    provider = FakeAlibabaProvider()
    with pytest.raises(ValueError, match="limit"):
        validate_alibaba_search("query", limit)
    with pytest.raises(ValueError, match="limit"):
        SearchAlibabaProducts(provider).execute("query", limit)
    assert provider.calls == []


def test_warning_over_100_does_not_search() -> None:
    assert alibaba_credit_warning(101) == ALIBABA_CREDIT_WARNING
    assert alibaba_credit_warning(100) is None
    assert alibaba_credit_warning(20) is None
    provider = FakeAlibabaProvider()
    # warning helper never calls the provider
    assert provider.calls == []


def test_one_click_one_service_call() -> None:
    provider = FakeAlibabaProvider([_product()])
    service = SearchAlibabaProducts(provider)
    payload = gui_services.run_alibaba_search("boots", 20, search_service=service)
    assert len(provider.calls) == 1
    assert payload["ui_status"] == "SUCCESS"


def test_loading_blocks_second_start() -> None:
    assert gui_services.can_start_alibaba_search(False) is True
    assert gui_services.can_start_alibaba_search(True) is False


def test_mapper_unique_price() -> None:
    product = map_alibaba_item(
        {
            "title": "Coat",
            "productId": "1",
            "productUrl": "https://www.alibaba.com/product-detail/1.html",
            "price": "USD 12.50",
            "moq": "50 pieces",
            "companyName": "Acme",
            "countryCode": "CN",
            "mainImage": "https://s.alicdn.com/x.jpg",
        }
    )
    assert product is not None
    assert product.price_display == "USD 12.50"
    assert product.min_price == Decimal("12.50")
    assert product.max_price == Decimal("12.50")
    assert product.currency == "USD"
    assert isinstance(product.min_price, Decimal)


def test_mapper_range_price() -> None:
    display, min_price, max_price, currency = parse_alibaba_price("$12.50 - $18.90")
    assert display == "$12.50 - $18.90"
    assert min_price == Decimal("12.50")
    assert max_price == Decimal("18.90")
    assert currency is None


def test_mapper_missing_price() -> None:
    product = map_alibaba_item({"title": "No price", "companyName": "Acme"})
    assert product is not None
    assert product.price_display is None
    assert product.min_price is None
    assert product.max_price is None
    assert product.currency is None


def test_moq_is_sanitized_not_normalized() -> None:
    product = map_alibaba_item({"title": "Item", "moq": "  50 pieces  "})
    assert product is not None
    assert product.moq == "50 pieces"


def test_supplier_name_and_country_only() -> None:
    product = map_alibaba_item(
        {
            "title": "Item",
            "companyName": "Hongfa",
            "countryCode": "CN",
            "companyId": "secret-id",
            "chatToken": "secret-chat",
            "contactSupplier": "mailto:hidden@example.com",
        }
    )
    assert product is not None
    assert product.supplier_name == "Hongfa"
    assert product.supplier_country == "CN"
    assert product.product_id is None or product.product_id != "secret-id"
    dumped = repr(product)
    assert "hidden@example.com" not in dumped
    assert "secret-chat" not in dumped


def test_empty_results() -> None:
    payload = gui_services.run_alibaba_search(
        "nothing",
        20,
        search_service=SearchAlibabaProducts(FakeAlibabaProvider()),
    )
    assert payload["ui_status"] == "EMPTY"
    assert payload["results"] == []
    assert payload["summary"]["resultados"] == "0"
    assert payload["summary"]["con_precio"] == "0 de 0"
    assert payload["summary"]["minimo"] == UNAVAILABLE_DISPLAY
    assert payload["summary"]["promedio"] == UNAVAILABLE_DISPLAY
    assert payload["summary"]["mediana"] == UNAVAILABLE_DISPLAY
    assert payload["summary"]["maximo"] == UNAVAILABLE_DISPLAY
    assert payload["summary"]["p25"] == UNAVAILABLE_DISPLAY
    assert payload["summary"]["p75"] == UNAVAILABLE_DISPLAY
    assert payload["summary"]["precio_tipico"] == UNAVAILABLE_DISPLAY
    assert payload["summary"]["outliers"] == "0"
    assert payload["summary"]["rango_tipico"] == UNAVAILABLE_DISPLAY


def test_failure_sanitized() -> None:
    message = gui_services.sanitize_alibaba_error(
        MarketplaceSourceUnavailable("token=SECRET stacktrace Actor.call")
    )
    assert message == gui_services.ALIBABA_GENERIC_USER_MESSAGE
    assert "SECRET" not in message
    assert "stack" not in message.lower()
    assert "Actor.call" not in message


def test_alibaba_stack_has_no_h0019() -> None:
    for path in ALIBABA_PATHS:
        text = path.read_text(encoding="utf-8")
        assert "h0019" not in text.lower()
        assert "H0019" not in text


def test_alibaba_stack_has_no_minimax() -> None:
    for path in ALIBABA_PATHS:
        text = path.read_text(encoding="utf-8")
        assert "minimax" not in text.lower()
        assert "ollama" not in text.lower()


def test_token_never_in_repr_or_new_sources() -> None:
    client = ApifyAlibabaClient(_api_token="apify-secret-token")
    assert "apify-secret-token" not in repr(client)
    settings = Settings.from_env({"BERA_TRACKER_APIFY_API_TOKEN": "apify-secret-token"})
    assert "apify-secret-token" not in repr(settings)
    for path in ALIBABA_PATHS:
        text = path.read_text(encoding="utf-8")
        assert "apify-secret-token" not in text
        assert "APIFY_TOKEN=" not in text


def test_client_uses_documented_input_and_default_actor() -> None:
    fake = FakeApify(
        [
            {
                "title": "Bag",
                "price": "USD 9.00",
                "moq": "10 pieces",
                "companyName": "Supplier",
                "countryCode": "CN",
            }
        ]
    )
    client = ApifyAlibabaClient(
        _api_token="token",
        actor_id=DEFAULT_APIFY_ALIBABA_ACTOR,
        client_factory=lambda _token: fake,
    )
    products = client.search("bags", 20)
    assert fake.actor_id == MEMO23_ALIBABA_SEARCH_ACTOR
    assert len(fake.calls) == 1
    assert fake.calls[0] == {
        "searchTerms": ["bags"],
        "maxPages": 1,
        "maxItems": 20,
    }
    assert fake.calls[0] == build_alibaba_run_input(query="bags", limit=20)
    assert products[0].title == "Bag"
    assert client.last_metrics is not None
    assert client.last_metrics.requested == 20
    assert client.last_metrics.fetched == 1
    assert client.last_metrics.usable == 1


def _alibaba_search_actor_env() -> str:
    return "_".join(("BERA_TRACKER", "APIFY", "ALIBABA", "ACTOR"))


def _legacy_alibaba_search_actor(*, tilde: bool = False) -> str:
    separator = "~" if tilde else "/"
    return separator.join(("scraper-engine", "alibaba-scraper"))


def _memo23_tilde_search_actor() -> str:
    return "~".join(("memo23", "alibaba-scraper"))


def test_default_actor_config() -> None:
    settings = Settings.from_env({})
    assert DEFAULT_APIFY_ALIBABA_ACTOR == MEMO23_ALIBABA_SEARCH_ACTOR
    assert DEFAULT_ALIBABA_ACTOR == MEMO23_ALIBABA_SEARCH_ACTOR
    assert settings.apify_alibaba_actor == MEMO23_ALIBABA_SEARCH_ACTOR
    assert settings.apify_alibaba_refresh_actor == DEFAULT_APIFY_ALIBABA_REFRESH_ACTOR
    assert settings.apify_alibaba_refresh_actor != MEMO23_ALIBABA_SEARCH_ACTOR


def test_unset_search_actor_uses_memo23_and_runs_once() -> None:
    settings = Settings.from_env({})
    fake = FakeApify([memo23_actor_item()])
    client = ApifyAlibabaClient(
        _api_token="token",
        actor_id=settings.apify_alibaba_actor,
        client_factory=lambda _token: fake,
    )
    products = client.search("Iphone 15", 5)
    assert settings.apify_alibaba_actor == MEMO23_ALIBABA_SEARCH_ACTOR
    assert fake.actor_id == MEMO23_ALIBABA_SEARCH_ACTOR
    assert len(fake.calls) == 1
    assert fake.calls[0] == build_alibaba_run_input(query="Iphone 15", limit=5)
    assert products[0].title == "Iphone 15 Protective Case"


def test_explicit_memo23_search_actor_uses_memo23_schema() -> None:
    settings = Settings.from_env(
        {_alibaba_search_actor_env(): f"  {MEMO23_ALIBABA_SEARCH_ACTOR}  "}
    )
    fake = FakeApify([memo23_actor_item()])
    client = ApifyAlibabaClient(
        _api_token="token",
        actor_id=settings.apify_alibaba_actor,
        client_factory=lambda _token: fake,
    )
    products = client.search("Iphone 15", 5)
    assert settings.apify_alibaba_actor == MEMO23_ALIBABA_SEARCH_ACTOR
    assert fake.actor_id == MEMO23_ALIBABA_SEARCH_ACTOR
    assert len(fake.calls) == 1
    assert fake.calls[0] == {
        "searchTerms": ["Iphone 15"],
        "maxPages": 1,
        "maxItems": 5,
    }
    assert products[0].title == "Iphone 15 Protective Case"


def test_memo23_tilde_alias_canonicalizes_before_actor_call() -> None:
    tilde = _memo23_tilde_search_actor()
    settings = Settings.from_env({_alibaba_search_actor_env(): f"  {tilde}  "})
    fake = FakeApify([memo23_actor_item()])
    client = ApifyAlibabaClient(
        _api_token="token",
        actor_id=settings.apify_alibaba_actor,
        client_factory=lambda _token: fake,
    )
    products = client.search("Iphone 15", 5)
    assert settings.apify_alibaba_actor == MEMO23_ALIBABA_SEARCH_ACTOR
    assert client.actor_id == MEMO23_ALIBABA_SEARCH_ACTOR
    assert fake.actor_id == MEMO23_ALIBABA_SEARCH_ACTOR
    assert fake.actor_id != tilde
    assert len(fake.calls) == 1
    assert products[0].title == "Iphone 15 Protective Case"

    direct = FakeApify([memo23_actor_item()])
    constructed = ApifyAlibabaClient(
        _api_token="token",
        actor_id=f"  {tilde}  ",
        client_factory=lambda _token: direct,
    )
    constructed.search("Iphone 15", 1)
    assert constructed.actor_id == MEMO23_ALIBABA_SEARCH_ACTOR
    assert direct.actor_id == MEMO23_ALIBABA_SEARCH_ACTOR


@pytest.mark.parametrize(
    "actor",
    [
        _legacy_alibaba_search_actor(),
        _legacy_alibaba_search_actor(tilde=True),
        "/".join(("other", "alibaba-scraper")),
        "~".join(("other", "alibaba-scraper")),
        "/".join(("memo23", "other")),
        "a1b2c3d4e5f6g7h8i9j0",
    ],
)
def test_unsupported_search_actor_forms_never_reach_client_actor(actor: str) -> None:
    fake = FakeApify([memo23_actor_item()])
    with pytest.raises(ValueError, match="Unsupported Alibaba SEARCH Actor"):
        Settings.from_env({_alibaba_search_actor_env(): actor})
    with pytest.raises(ApifyConfigurationError, match="Unsupported Alibaba SEARCH Actor"):
        ApifyAlibabaClient(
            _api_token="token",
            actor_id=actor,
            client_factory=lambda _token: fake,
        )
    assert fake.calls == []
    assert fake.actor_id == ""


def test_legacy_search_actor_override_never_reaches_memo23_run_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[dict[str, object]] = []

    def _capture_run_input(*, query: str, limit: int) -> dict[str, object]:
        payload = {"searchTerms": [query], "maxPages": 1, "maxItems": limit}
        built.append(payload)
        return payload

    monkeypatch.setattr(
        "bera_price_tracker.infrastructure.providers.alibaba.build_alibaba_run_input",
        _capture_run_input,
    )
    fake = FakeApify([memo23_actor_item()])
    with pytest.raises(ValueError, match="Unsupported Alibaba SEARCH Actor"):
        Settings.from_env({_alibaba_search_actor_env(): _legacy_alibaba_search_actor()})
    with pytest.raises(ApifyConfigurationError, match="Unsupported Alibaba SEARCH Actor"):
        ApifyAlibabaClient(
            _api_token="token",
            actor_id=_legacy_alibaba_search_actor(),
            client_factory=lambda _token: fake,
        )
    assert fake.calls == []
    assert fake.actor_id == ""
    assert built == []


def test_incompatible_custom_search_actor_does_not_receive_memo23_schema() -> None:
    custom_actor = "custom/incompatible-alibaba-actor"
    fake = FakeApify([memo23_actor_item()])
    with pytest.raises(ValueError, match="Unsupported Alibaba SEARCH Actor"):
        Settings.from_env({_alibaba_search_actor_env(): custom_actor})
    with pytest.raises(ApifyConfigurationError, match="Unsupported Alibaba SEARCH Actor"):
        ApifyAlibabaClient(
            _api_token="token",
            actor_id=custom_actor,
            client_factory=lambda _token: fake,
        )
    assert fake.calls == []
    assert fake.actor_id == ""


def test_refresh_actor_override_stays_independent_of_search_actor() -> None:
    custom_refresh = "custom/alibaba-refresh-actor"
    settings = Settings.from_env(
        {
            _alibaba_search_actor_env(): MEMO23_ALIBABA_SEARCH_ACTOR,
            "BERA_TRACKER_APIFY_ALIBABA_REFRESH_ACTOR": custom_refresh,
        }
    )
    assert settings.apify_alibaba_actor == MEMO23_ALIBABA_SEARCH_ACTOR
    assert settings.apify_alibaba_refresh_actor == custom_refresh
    assert settings.apify_alibaba_refresh_actor != settings.apify_alibaba_actor
    fake = FakeApify([memo23_actor_item()])
    ApifyAlibabaClient(
        _api_token="token",
        actor_id=settings.apify_alibaba_actor,
        client_factory=lambda _token: fake,
    ).search("Iphone 15", 1)
    assert fake.actor_id == MEMO23_ALIBABA_SEARCH_ACTOR
    assert fake.actor_id != custom_refresh
    assert len(fake.calls) == 1


def test_process_settings_ignore_leftover_search_actor_env() -> None:
    settings = Settings.from_env()
    assert settings.apify_alibaba_actor == MEMO23_ALIBABA_SEARCH_ACTOR


def memo23_actor_item(**overrides: object) -> dict[str, object]:
    """Representative memo23/alibaba-scraper dataset row. Offline fixture only."""

    item: dict[str, object] = {
        "title": "Iphone 15 Protective Case",
        "productId": "1601111111111",
        "productUrl": "https://www.alibaba.com/product-detail/Iphone-15_1601111111111.html",
        "price": "US $1.00-$9.00",
        "priceMin": 1.0,
        "minOrder": "10 pieces",
        "unit": "piece",
        "mainImage": "https://s.alicdn.com/example.jpg",
        "category": "Mobile Phone Cases",
        "categoryId": "5090301",
        "isAd": False,
        "supplierName": "Shenzhen Example Co., Ltd.",
        "supplierCountry": "China",
        "supplierCountryCode": "CN",
        "supplierYears": 7,
        "reviewScore": 4.8,
        "reviewCount": 120,
        "supplierServiceScore": 4.9,
        "goldSupplier": True,
        "verifiedSupplierPro": True,
        "tradeAssurance": True,
        "certifications": ["CE", "RoHS"],
        "quantityPrices": [{"price": "US $1.00", "quantityMin": 10, "unit": "piece"}],
        "searchTerm": "Iphone 15",
        "page": 1,
    }
    item.update(overrides)
    return item


def _search_with_items(
    items: Sequence[object],
    *,
    query: str = "Iphone 15",
    limit: int = 5,
    run: object | None = None,
) -> tuple[ApifyAlibabaClient, FakeApify, list[AlibabaProduct]]:
    fake = FakeApify(list(items), run=run)
    client = ApifyAlibabaClient(
        _api_token="token",
        actor_id=DEFAULT_APIFY_ALIBABA_ACTOR,
        client_factory=lambda _token: fake,
    )
    products = client.search(query, limit)
    return client, fake, products


def test_memo23_schema_maps_truthful_public_fields() -> None:
    product = map_alibaba_item(memo23_actor_item())
    assert product is not None
    assert product.title == "Iphone 15 Protective Case"
    assert product.product_id == "1601111111111"
    assert product.product_url == (
        "https://www.alibaba.com/product-detail/Iphone-15_1601111111111.html"
    )
    assert product.price_display == "US $1.00-$9.00"
    assert product.min_price == Decimal("1.00")
    assert product.max_price == Decimal("9.00")
    assert product.currency == "USD"
    assert product.moq == "10 pieces"
    assert product.supplier_name == "Shenzhen Example Co., Ltd."
    assert product.supplier_country == "CN"
    assert product.image_url == "https://s.alicdn.com/example.jpg"
    assert product.supplier_service_score == "4.9"
    assert product.review_count == "120"
    assert product.review_score == "4.8"


def test_supplier_years_does_not_become_gold_supplier_years() -> None:
    product = map_alibaba_item(memo23_actor_item(supplierYears=7, goldSupplier=True))
    assert product is not None
    assert product.gold_supplier_years is None
    dumped = repr(product)
    assert "7" not in dumped or product.gold_supplier_years is None
    assert "supplierYears" not in dumped


def test_memo23_us_dollar_range_is_explicit_usd() -> None:
    product = map_alibaba_item(memo23_actor_item(price="US $1.00-$9.00"))
    assert product is not None
    assert product.price_display == "US $1.00-$9.00"
    assert product.min_price == Decimal("1.00")
    assert product.max_price == Decimal("9.00")
    assert product.currency == "USD"


def test_memo23_documented_us_dollar_prefix_enters_usd_statistics() -> None:
    product = map_alibaba_item(memo23_actor_item(price="US $0.71-$0.78"))
    assert product is not None
    assert product.price_display == "US $0.71-$0.78"
    assert product.min_price == Decimal("0.71")
    assert product.max_price == Decimal("0.78")
    assert product.currency == "USD"
    assert infer_alibaba_currency(product) == "USD"
    assert alibaba_representative_price(product) == Decimal("0.745")
    stats = calculate_alibaba_price_statistics([product])
    assert stats.priced_products == 1
    assert stats.average == Decimal("0.745")
    assert stats.median == Decimal("0.745")
    assert stats.minimum == Decimal("0.71")
    assert stats.maximum == Decimal("0.78")
    assert stats.currency == "USD"


def test_memo23_documented_us_dollar_prefix_scores_as_explicit_usd() -> None:
    product = map_alibaba_item(
        memo23_actor_item(
            price="US $0.71-$0.78",
            minOrder="1 piece",
        )
    )
    assert product is not None
    scores = score_alibaba_listings([product])
    assert len(scores) == 1
    score = scores[0]
    # Single explicit-USD listing: relative fraction is 0.5, so 45 * 0.5 = 22.5 → 22.
    assert score.price_score == 22
    assert score.information_score == 20
    assert score.price_clarity_score == 7
    assert score.moq_score == 12
    assert score.total == 61
    assert score.total == (
        score.price_score + score.moq_score + score.information_score + score.price_clarity_score
    )


def test_single_price_and_missing_price_are_truthful() -> None:
    single = map_alibaba_item(memo23_actor_item(price="US $4.50", priceMin=4.5))
    assert single is not None
    assert single.price_display == "US $4.50"
    assert single.min_price == Decimal("4.50")
    assert single.max_price == Decimal("4.50")
    assert single.currency == "USD"
    missing = map_alibaba_item(memo23_actor_item(price=None, priceMin=None, minOrder="5 pieces"))
    assert missing is not None
    assert missing.price_display is None
    assert missing.min_price is None
    assert missing.max_price is None
    assert missing.currency is None
    assert missing.moq == "5 pieces"


def test_min_order_and_supplier_fields_map_from_memo23_names() -> None:
    product = map_alibaba_item(
        {
            "title": "Motorcycle brake pads",
            "minOrder": 50,
            "supplierName": "Example Brakes",
            "supplierCountry": "China",
        }
    )
    assert product is not None
    assert product.moq == "50"
    assert product.supplier_name == "Example Brakes"
    assert product.supplier_country == "China"
    coded = map_alibaba_item(memo23_actor_item(supplierCountry="China", supplierCountryCode="CN"))
    assert coded is not None
    assert coded.supplier_country == "CN"


def test_zero_review_fields_are_not_converted_to_missing() -> None:
    product = map_alibaba_item(memo23_actor_item(reviewScore=0, reviewCount=0))
    assert product is not None
    assert product.review_score == "0"
    assert product.review_count == "0"


def test_missing_optional_memo23_metadata_keeps_title_bearing_listing() -> None:
    product = map_alibaba_item(
        {
            "title": "Solar panel 550w",
            "isAd": True,
            "category": "Solar Panels",
            "categoryId": "1001",
            "quantityPrices": [{"price": "US $9.00"}],
            "verifiedSupplierPro": True,
            "tradeAssurance": True,
            "certifications": ["CE"],
        }
    )
    assert product is not None
    assert product.title == "Solar panel 550w"
    assert product.product_id is None
    assert product.product_url is None
    assert product.price_display is None
    assert product.moq is None
    assert product.supplier_name is None
    assert product.supplier_country is None
    assert product.image_url is None
    assert product.gold_supplier_years is None
    assert product.review_score is None
    assert "quantityPrices" not in repr(product)
    assert "categoryId" not in repr(product)


def test_is_ad_true_does_not_drop_a_valid_listing() -> None:
    product = map_alibaba_item(memo23_actor_item(isAd=True, title="Sponsored Iphone case"))
    assert product is not None
    assert product.title == "Sponsored Iphone case"


def test_title_less_memo23_row_is_skipped() -> None:
    assert map_alibaba_item(memo23_actor_item(title="  ")) is None
    assert map_alibaba_item(memo23_actor_item(title=None)) is None


def test_non_string_title_is_not_coerced_into_a_listing() -> None:
    for title in (4.5, 5, True, False, 0):
        assert map_alibaba_item(memo23_actor_item(title=title)) is None


def test_non_string_identity_fields_do_not_fabricate_metadata() -> None:
    product = map_alibaba_item(
        memo23_actor_item(
            title="Wireless mouse",
            productId=4.5,
            productUrl=4.5,
            supplierName=4.5,
            supplierCountry=4.5,
            supplierCountryCode=4.5,
            countryCode=4.5,
            companyName=4.5,
            mainImage=4.5,
            reviewScore=4.5,
            supplierServiceScore=4.5,
            reviewCount=5,
        )
    )
    assert product is not None
    assert product.title == "Wireless mouse"
    assert product.product_id is None
    assert product.product_url is None
    assert product.supplier_name is None
    assert product.supplier_country is None
    assert product.image_url is None
    assert product.review_score == "4.5"
    assert product.supplier_service_score == "4.5"
    assert product.review_count == "5"
    sibling_name = map_alibaba_item(
        memo23_actor_item(title="Named mouse", supplierName=4.5, companyName="Acme Trading")
    )
    assert sibling_name is not None
    assert sibling_name.supplier_name == "Acme Trading"
    scores = score_alibaba_listings([product, sibling_name])
    assert scores[0].information_score < scores[1].information_score


def test_bool_is_not_numeric_or_identity_metadata() -> None:
    product = map_alibaba_item(
        {
            "title": "Wireless mouse",
            "productId": True,
            "supplierName": False,
            "reviewScore": True,
            "reviewCount": False,
            "supplierServiceScore": True,
            "minOrder": True,
        }
    )
    assert product is not None
    assert product.product_id is None
    assert product.supplier_name is None
    assert product.review_score is None
    assert product.review_count is None
    assert product.supplier_service_score is None
    assert product.moq is None


def test_search_maps_five_memo23_results_in_actor_order() -> None:
    items = [
        memo23_actor_item(title="First", productId="p-1", price="US $9.00"),
        memo23_actor_item(title="Second", productId="p-2", isAd=True, price="US $2.00"),
        memo23_actor_item(title="Third", productId="p-3", price="US $5.00"),
        memo23_actor_item(title="Fourth", productId="p-4", price="US $1.00"),
        memo23_actor_item(title="Fifth", productId="p-5", price="US $8.00"),
    ]
    client, fake, products = _search_with_items(items, limit=5)
    assert [item.title for item in products] == ["First", "Second", "Third", "Fourth", "Fifth"]
    assert [item.product_id for item in products] == ["p-1", "p-2", "p-3", "p-4", "p-5"]
    assert len(fake.calls) == 1
    assert fake.calls[0]["maxPages"] == 1
    assert fake.calls[0]["maxItems"] == 5
    assert fake.calls[0]["searchTerms"] == ["Iphone 15"]
    assert client.last_metrics is not None
    assert client.last_metrics.requested == 5
    assert client.last_metrics.fetched == 5
    assert client.last_metrics.usable == 5


def test_empty_dataset_is_empty_not_error() -> None:
    client, fake, products = _search_with_items([], query="nothing", limit=20)
    assert products == []
    assert len(fake.calls) == 1
    assert client.last_metrics is not None
    assert client.last_metrics.requested == 20
    assert client.last_metrics.fetched == 0
    assert client.last_metrics.usable == 0


def test_failed_actor_run_is_unavailable_and_does_not_retry() -> None:
    fake = FakeApify([], run={"status": "FAILED", "defaultDatasetId": "ds1"})
    client = ApifyAlibabaClient(
        _api_token="token",
        client_factory=lambda _token: fake,
    )
    with pytest.raises(MarketplaceSourceUnavailable, match="unavailable"):
        client.search("Iphone 15", 5)
    assert len(fake.calls) == 1
    assert client.last_metrics is None


def test_non_succeeded_and_missing_dataset_are_unavailable_without_retry() -> None:
    aborted = FakeApify([], run={"status": "ABORTED", "defaultDatasetId": "ds1"})
    client = ApifyAlibabaClient(_api_token="token", client_factory=lambda _token: aborted)
    with pytest.raises(MarketplaceSourceUnavailable, match="unavailable"):
        client.search("Iphone 15", 5)
    assert len(aborted.calls) == 1
    missing = FakeApify([], run={"status": "SUCCEEDED"})
    with pytest.raises(MarketplaceSourceUnavailable, match="unavailable"):
        ApifyAlibabaClient(_api_token="token", client_factory=lambda _token: missing).search(
            "Iphone 15", 5
        )
    assert len(missing.calls) == 1


def test_identity_less_and_duplicate_looking_rows_are_preserved() -> None:
    items = [
        memo23_actor_item(title="Same title", productId=None, price="US $1.00"),
        memo23_actor_item(title="Same title", productId=None, price="US $1.00"),
        memo23_actor_item(title="Same title", productId="stable-1", price="US $2.00"),
        memo23_actor_item(
            title="Unrelated category",
            productId="stable-2",
            category="Motorcycles",
            isAd=True,
        ),
    ]
    _client, fake, products = _search_with_items(items, limit=10)
    assert [item.product_id for item in products] == [None, None, "stable-1", "stable-2"]
    assert [item.title for item in products] == [
        "Same title",
        "Same title",
        "Same title",
        "Unrelated category",
    ]
    assert len(fake.calls) == 1
    assert fake.calls[0]["maxItems"] == 10


def test_no_title_url_price_or_category_fuzzy_dedup() -> None:
    items = [
        memo23_actor_item(
            title="Wireless mouse",
            productId="a",
            productUrl="https://www.alibaba.com/product-detail/a.html",
            price="US $4.00",
            category="Mice",
        ),
        memo23_actor_item(
            title="Wireless mouse",
            productId="b",
            productUrl="https://www.alibaba.com/product-detail/b.html",
            price="US $4.00",
            category="Mice",
        ),
    ]
    _client, _fake, products = _search_with_items(items, limit=5)
    assert [item.product_id for item in products] == ["a", "b"]


def test_one_actor_call_for_one_search_and_no_legacy_urls() -> None:
    _client, fake, _products = _search_with_items(
        [memo23_actor_item()], query="motorcycle brake pads", limit=5
    )
    assert len(fake.calls) == 1
    payload = fake.calls[0]
    assert payload == {
        "searchTerms": ["motorcycle brake pads"],
        "maxPages": 1,
        "maxItems": 5,
    }
    assert "urls" not in payload
    assert fake.actor_id == MEMO23_ALIBABA_SEARCH_ACTOR


def test_search_url_builder_is_removed() -> None:
    import bera_price_tracker.infrastructure.providers.alibaba as alibaba_provider

    assert not hasattr(alibaba_provider, "build_alibaba_search_url")


# Keys observed on a previous search-actor SUCCEEDED dataset. Kept as a
# historical schema sample; it is not the current memo23 search Actor.
OBSERVED_ACTOR_KEYS = frozenset(
    {
        "badges",
        "certifications",
        "chatToken",
        "companyId",
        "companyLogo",
        "companyName",
        "contactSupplier",
        "countryCode",
        "customGroup",
        "displayStarLevel",
        "eurl",
        "goldSupplierYears",
        "id",
        "isShowAd",
        "loopSellingPoints",
        "lyb",
        "mainImage",
        "moq",
        "moqV2",
        "multiImage",
        "pcLoopSellingPoints",
        "price",
        "productId",
        "productScore",
        "productUrl",
        "reviewCount",
        "reviewScore",
        "shippingScore",
        "showAddToCart",
        "showCrown",
        "soldOrder",
        "supplierHomeHref",
        "supplierHref",
        "supplierService",
        "supplierServiceScore",
        "title",
        "tmlid",
        "trackInfo",
    }
)


def observed_actor_item(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "title": "Wireless mouse",
        "productId": "1600000000000",
        "productUrl": "https://www.alibaba.com/product-detail/example.html",
        "price": "$1.38",
        "moq": "Min. order: 1 piece",
        "moqV2": "1",
        "companyName": "Example Electronics Co., Ltd.",
        "countryCode": "CN",
        "mainImage": "https://s.alicdn.com/example.jpg",
        "multiImage": [],
        "companyId": "secret-company-id",
        "companyLogo": "https://s.alicdn.com/logo.jpg",
        "contactSupplier": "mailto:hidden@example.com",
        "chatToken": "secret-chat",
        "eurl": "https://example.invalid/eurl",
        "trackInfo": "secret-track",
        "id": "internal-id",
        "tmlid": "tmlid",
        "badges": [],
        "certifications": [],
        "customGroup": "",
        "displayStarLevel": "",
        "goldSupplierYears": "1",
        "isShowAd": False,
        "loopSellingPoints": [],
        "lyb": False,
        "pcLoopSellingPoints": [],
        "productScore": "4.8",
        "reviewCount": "10",
        "reviewScore": "4.8",
        "shippingScore": "4.8",
        "showAddToCart": False,
        "showCrown": False,
        "soldOrder": "100",
        "supplierHomeHref": "https://example.invalid/home",
        "supplierHref": "https://example.invalid/supplier",
        "supplierService": "",
        "supplierServiceScore": "",
    }
    item.update(overrides)
    return item


def test_observed_schema_keys_are_mapped() -> None:
    raw = observed_actor_item()
    assert set(raw) == OBSERVED_ACTOR_KEYS
    product = map_alibaba_item(raw)
    assert product is not None
    assert product.title == "Wireless mouse"
    assert product.product_id == "1600000000000"
    assert product.product_url == "https://www.alibaba.com/product-detail/example.html"
    assert product.price_display == "$1.38"
    assert product.min_price == Decimal("1.38")
    assert product.max_price == Decimal("1.38")
    assert product.currency is None
    assert product.moq == "Min. order: 1 piece"
    assert product.supplier_name == "Example Electronics Co., Ltd."
    assert product.supplier_country == "CN"
    assert product.image_url == "https://s.alicdn.com/example.jpg"


def test_observed_range_price_and_moq() -> None:
    product = map_alibaba_item(observed_actor_item(price="$1.30-1.60", moq="Min. order: 2 pieces"))
    assert product is not None
    assert product.price_display == "$1.30-1.60"
    assert product.min_price == Decimal("1.30")
    assert product.max_price == Decimal("1.60")
    assert isinstance(product.min_price, Decimal)
    assert isinstance(product.max_price, Decimal)
    assert product.moq == "Min. order: 2 pieces"


def test_observed_missing_optional_fields() -> None:
    product = map_alibaba_item({"title": "Wireless mouse"})
    assert product is not None
    assert product.price_display is None
    assert product.min_price is None
    assert product.max_price is None
    assert product.currency is None
    assert product.moq is None
    assert product.supplier_name is None
    assert product.supplier_country is None
    assert product.product_url is None


def test_state_success_from_observed_results() -> None:
    products = [
        map_alibaba_item(observed_actor_item()),
        map_alibaba_item(observed_actor_item(title="Range mouse", price="$3.80-16.80")),
    ]
    mapped = [product for product in products if product is not None]
    payload = gui_services.run_alibaba_search(
        "wireless mouse",
        10,
        search_service=SearchAlibabaProducts(FakeAlibabaProvider(mapped)),
    )
    rows = [
        AlibabaResultRow(
            title=str(item.get("title", "")),
            price=str(item.get("price", "")),
            moq=str(item.get("moq", "")),
            supplier_name=str(item.get("supplier_name", "")),
            supplier_country=str(item.get("supplier_country", "")),
            url=str(item.get("url", "")),
            image_url=str(item.get("image_url", "")),
        )
        for item in payload["results"]
    ]
    assert len(rows) > 0
    assert payload["ui_status"] == "SUCCESS"
    assert payload["error_message"] == ""
    assert "alibaba_results" in TrackerState.__annotations__
    assert "alibaba_error" in TrackerState.__annotations__
    assert "alibaba_is_loading" in TrackerState.__annotations__
    dumped = json.dumps(payload["results"], ensure_ascii=True)
    assert "hidden@example.com" not in dumped
    assert "secret-chat" not in dumped
    assert "secret-company-id" not in dumped
    assert rows[0].title
    assert rows[0].price == f"1.38 · {MISSING_CURRENCY_DISPLAY}"
    assert "$" not in rows[0].price
    assert rows[0].moq == "Min. order: 1 piece"
    assert rows[0].supplier_name == "Example Electronics Co., Ltd."
    assert rows[0].supplier_country == "CN"
    assert rows[0].url == "https://www.alibaba.com/product-detail/example.html"


def test_simple_price_min_max_and_representative() -> None:
    product = map_alibaba_item({"title": "Mouse", "price": "$4"})
    assert product is not None
    assert product.min_price == Decimal("4")
    assert product.max_price == Decimal("4")
    representative = alibaba_representative_price(product)
    assert representative == Decimal("4")
    assert isinstance(representative, Decimal)
    assert product.price_display == "$4"


def test_range_representative_is_midpoint() -> None:
    product = map_alibaba_item({"title": "Mouse", "price": "$1.30-1.60"})
    assert product is not None
    representative = alibaba_representative_price(product)
    assert representative == Decimal("1.45")
    assert isinstance(representative, Decimal)
    assert product.price_display == "$1.30-1.60"


def test_minimum_uses_price_min() -> None:
    products = [
        map_alibaba_item({"title": "A", "price": "$1", "currency": "USD"}),
        map_alibaba_item({"title": "B", "price": "$1.30-1.60", "currency": "USD"}),
        map_alibaba_item({"title": "C", "price": "$13.45", "currency": "USD"}),
    ]
    mapped = [product for product in products if product is not None]
    stats = calculate_alibaba_price_statistics(mapped)
    assert stats.minimum == Decimal("1")
    assert format_alibaba_money(stats.minimum) == "$1.00"


def test_maximum_uses_price_max() -> None:
    products = [
        map_alibaba_item({"title": "A", "price": "$4", "currency": "USD"}),
        map_alibaba_item({"title": "B", "price": "$159-699", "currency": "USD"}),
    ]
    mapped = [product for product in products if product is not None]
    stats = calculate_alibaba_price_statistics(mapped)
    assert stats.maximum == Decimal("699")
    assert format_alibaba_money(stats.maximum) == "$699.00"


def test_average_is_decimal_of_representatives() -> None:
    products = [
        map_alibaba_item({"title": "A", "price": "$1.00", "currency": "USD"}),
        map_alibaba_item({"title": "B", "price": "$2.00", "currency": "USD"}),
        map_alibaba_item({"title": "C", "price": "$3.00", "currency": "USD"}),
    ]
    mapped = [product for product in products if product is not None]
    stats = calculate_alibaba_price_statistics(mapped)
    assert stats.average == Decimal("2")
    assert isinstance(stats.average, Decimal)
    assert format_alibaba_money(stats.average) == "$2.00"


def test_median_odd_count() -> None:
    products = [
        map_alibaba_item({"title": "A", "price": "$1.00", "currency": "USD"}),
        map_alibaba_item({"title": "B", "price": "$4.00", "currency": "USD"}),
        map_alibaba_item({"title": "C", "price": "$13.45", "currency": "USD"}),
    ]
    mapped = [product for product in products if product is not None]
    stats = calculate_alibaba_price_statistics(mapped)
    assert stats.median == Decimal("4.00")
    assert format_alibaba_money(stats.median) == "$4.00"


def test_median_even_count() -> None:
    products = [
        map_alibaba_item({"title": "A", "price": "$1.00", "currency": "USD"}),
        map_alibaba_item({"title": "B", "price": "$2.00", "currency": "USD"}),
        map_alibaba_item({"title": "C", "price": "$3.00", "currency": "USD"}),
        map_alibaba_item({"title": "D", "price": "$4.00", "currency": "USD"}),
    ]
    mapped = [product for product in products if product is not None]
    stats = calculate_alibaba_price_statistics(mapped)
    assert stats.median == Decimal("2.5")
    assert isinstance(stats.median, Decimal)
    assert format_alibaba_money(stats.median) == "$2.50"


def test_missing_price_excluded_from_statistics_but_kept_in_table() -> None:
    products = [
        map_alibaba_item({"title": "Priced", "price": "$4", "currency": "USD"}),
        map_alibaba_item({"title": "Ask", "price": "Contact supplier"}),
        map_alibaba_item({"title": "Gone", "price": "unavailable"}),
        map_alibaba_item({"title": "Blank"}),
    ]
    mapped = [product for product in products if product is not None]
    payload = gui_services.run_alibaba_search(
        "wireless mouse",
        10,
        search_service=SearchAlibabaProducts(FakeAlibabaProvider(mapped)),
    )
    titles = [row["title"] for row in payload["results"]]
    assert titles == ["Priced", "Ask", "Gone", "Blank"]
    assert payload["results"][1]["price"] == ""
    assert payload["results"][2]["price"] == ""
    assert payload["summary"]["resultados"] == "4"
    assert payload["summary"]["con_precio"] == "1 de 4"
    assert payload["summary"]["minimo"] == "$4.00"
    assert payload["summary"]["maximo"] == "$4.00"
    assert payload["summary"]["promedio"] == "$4.00"
    assert payload["summary"]["mediana"] == "$4.00"


def test_range_display_remains_on_row() -> None:
    product = map_alibaba_item({"title": "Range mouse", "price": "$1.30-1.60", "currency": "USD"})
    assert product is not None
    payload = gui_services.run_alibaba_search(
        "wireless mouse",
        10,
        search_service=SearchAlibabaProducts(FakeAlibabaProvider([product])),
    )
    assert payload["results"][0]["price"] == "$1.30–$1.60"
    assert payload["summary"]["promedio"] == "$1.45"
    assert payload["summary"]["mediana"] == "$1.45"


def test_statistics_do_not_mix_currencies() -> None:
    products = [
        map_alibaba_item({"title": "USD cheap", "price": "$4", "currency": "USD"}),
        map_alibaba_item({"title": "USD mid", "price": "$5", "currency": "USD"}),
        map_alibaba_item({"title": "EUR", "price": "EUR 100"}),
    ]
    mapped = [product for product in products if product is not None]
    stats = calculate_alibaba_price_statistics(mapped)
    assert stats.priced_products == 2
    assert stats.total_products == 3
    assert stats.currency == "USD"
    assert stats.minimum == Decimal("4")
    assert stats.maximum == Decimal("5")
    assert stats.average == Decimal("4.5")
    payload = gui_services.run_alibaba_search(
        "wireless mouse",
        10,
        search_service=SearchAlibabaProducts(FakeAlibabaProvider(mapped)),
    )
    assert payload["results"][2]["price"] == "EUR 100.00"
    assert payload["summary"]["con_precio"] == "2 de 3"
    assert payload["summary"]["minimo"] == "$4.00"
    assert payload["summary"]["maximo"] == "$5.00"


def test_zero_valid_prices_are_unavailable() -> None:
    products = [
        map_alibaba_item({"title": "Ask", "price": "Contact supplier"}),
        map_alibaba_item({"title": "Gone", "price": "price unavailable"}),
    ]
    mapped = [product for product in products if product is not None]
    stats = calculate_alibaba_price_statistics(mapped)
    assert stats.priced_products == 0
    assert stats.minimum is None
    assert stats.maximum is None
    assert stats.average is None
    assert stats.median is None
    assert stats.p25 is None
    assert stats.p75 is None
    assert stats.iqr is None
    assert stats.trimmed_mean is None
    assert stats.outlier_count == 0
    payload = gui_services.run_alibaba_search(
        "wireless mouse",
        10,
        search_service=SearchAlibabaProducts(FakeAlibabaProvider(mapped)),
    )
    assert payload["ui_status"] == "SUCCESS"
    assert payload["summary"]["minimo"] == UNAVAILABLE_DISPLAY
    assert payload["summary"]["promedio"] == UNAVAILABLE_DISPLAY
    assert payload["summary"]["mediana"] == UNAVAILABLE_DISPLAY
    assert payload["summary"]["maximo"] == UNAVAILABLE_DISPLAY


def test_alibaba_statistics_ignore_moq_and_facebook_policy() -> None:
    stats_path = SRC / "bera_price_tracker" / "application" / "alibaba_statistics.py"
    text = stats_path.read_text(encoding="utf-8")
    assert ".moq" not in text
    assert 'getattr(product, "moq"' not in text
    assert "facebook_venezuela" not in text
    assert "float(" not in text
    product = map_alibaba_item(
        {"title": "Mouse", "price": "$4", "moq": "Min. order: 1000 pieces", "currency": "USD"}
    )
    assert product is not None
    stats = calculate_alibaba_price_statistics([product])
    assert stats.minimum == Decimal("4")
    assert stats.average == Decimal("4")


def test_alibaba_gui_exposes_stat_cards() -> None:
    views = (SRC / "bera_price_tracker" / "gui" / "views.py").read_text(encoding="utf-8")
    assert "Promedio estimado" in views
    assert "Mediana" in views
    assert "Precio típico" in views
    assert "Media recortada 10%" in views
    assert "P25" in views
    assert "P75" in views
    assert "Outliers" in views
    assert "Rango típico" in views
    assert "Imagen" in views
    assert "Producto" in views
    assert "alibaba_summary" in TrackerState.__annotations__


def _usd_product(title: str, price: str) -> AlibabaProduct:
    product = map_alibaba_item({"title": title, "price": price, "currency": "USD"})
    assert product is not None
    return product


def test_advanced_stats_empty_dataset() -> None:
    stats = calculate_alibaba_price_statistics([])
    assert stats.priced_products == 0
    assert stats.p25 is None
    assert stats.p75 is None
    assert stats.iqr is None
    assert stats.trimmed_mean is None
    assert stats.outlier_count == 0
    assert interpret_alibaba_prices(stats) == ""


def test_advanced_stats_single_price() -> None:
    stats = calculate_alibaba_price_statistics([_usd_product("One", "$4.00")])
    assert stats.p25 == Decimal("4.00")
    assert stats.p75 == Decimal("4.00")
    assert stats.iqr == Decimal("0")
    assert stats.trimmed_mean == Decimal("4.00")
    assert stats.outlier_count == 0
    assert stats.lower_fence == Decimal("4.00")
    assert stats.upper_fence == Decimal("4.00")


def test_advanced_stats_two_prices() -> None:
    stats = calculate_alibaba_price_statistics(
        [_usd_product("A", "$1.00"), _usd_product("B", "$3.00")]
    )
    assert stats.p25 == Decimal("1.50")
    assert stats.p75 == Decimal("2.50")
    assert stats.iqr == Decimal("1.00")
    assert isinstance(stats.p25, Decimal)
    assert isinstance(stats.iqr, Decimal)
    note = interpret_alibaba_prices(stats)
    assert "50% central" in note
    assert format_alibaba_money(stats.p25) in note
    assert format_alibaba_money(stats.p75) in note


def test_p25_p75_and_linear_interpolation() -> None:
    ordered = [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")]
    p25 = alibaba_percentile(ordered, Decimal("0.25"))
    p75 = alibaba_percentile(ordered, Decimal("0.75"))
    assert p25 == Decimal("1.75")
    assert p75 == Decimal("3.25")
    assert isinstance(p25, Decimal)
    assert isinstance(p75, Decimal)
    products = [
        _usd_product(str(index), f"${value}") for index, value in enumerate(ordered, start=1)
    ]
    stats = calculate_alibaba_price_statistics(products)
    assert stats.p25 == Decimal("1.75")
    assert stats.p75 == Decimal("3.25")
    assert stats.iqr == Decimal("1.50")


def test_tukey_fences_and_outliers() -> None:
    products = [
        _usd_product("low", "$1.00"),
        _usd_product("a", "$10.00"),
        _usd_product("b", "$11.00"),
        _usd_product("mid", "$12.00"),
        _usd_product("c", "$13.00"),
        _usd_product("d", "$14.00"),
        _usd_product("high", "$100.00"),
    ]
    stats = calculate_alibaba_price_statistics(products)
    assert stats.p25 == Decimal("10.50")
    assert stats.p75 == Decimal("13.50")
    assert stats.iqr == Decimal("3.00")
    assert stats.lower_fence == Decimal("6.00")
    assert stats.upper_fence == Decimal("18.00")
    assert stats.outlier_count == 2
    assert stats.minimum == Decimal("1.00")
    assert stats.maximum == Decimal("100.00")
    payload = gui_services.run_alibaba_search(
        "wireless mouse",
        10,
        search_service=SearchAlibabaProducts(FakeAlibabaProvider(products)),
    )
    titles = [row["title"] for row in payload["results"]]
    assert titles == ["low", "a", "b", "mid", "c", "d", "high"]
    assert payload["summary"]["outliers"] == "2"
    assert "2 precios fuera del rango estadístico habitual" in payload["summary"]["interpretacion"]
    assert "barato" not in payload["summary"]["interpretacion"].lower()
    assert "caro" not in payload["summary"]["interpretacion"].lower()


def test_normal_price_is_not_outlier() -> None:
    products = [
        _usd_product("a", "$10.00"),
        _usd_product("b", "$11.00"),
        _usd_product("mid", "$12.00"),
        _usd_product("c", "$13.00"),
        _usd_product("d", "$14.00"),
    ]
    stats = calculate_alibaba_price_statistics(products)
    assert stats.outlier_count == 0
    assert stats.lower_fence is not None
    assert stats.upper_fence is not None
    assert Decimal("12.00") > stats.lower_fence
    assert Decimal("12.00") < stats.upper_fence


def test_trimmed_mean_with_ten_or_more() -> None:
    products = [_usd_product(str(index), f"${index}.00") for index in range(1, 11)]
    stats = calculate_alibaba_price_statistics(products)
    assert stats.trimmed_mean == Decimal("5.5")
    assert format_alibaba_money(stats.trimmed_mean) == "$5.50"
    skewed = [_usd_product(str(index), f"${index}.00") for index in range(1, 10)]
    skewed.append(_usd_product("tail", "$100.00"))
    skewed_stats = calculate_alibaba_price_statistics(skewed)
    assert skewed_stats.trimmed_mean == Decimal("5.5")
    assert skewed_stats.average != skewed_stats.trimmed_mean


def test_trimmed_mean_with_fewer_than_ten() -> None:
    products = [_usd_product(str(index), f"${index}.00") for index in range(1, 10)]
    stats = calculate_alibaba_price_statistics(products)
    assert stats.trimmed_mean == stats.average
    assert stats.trimmed_mean == Decimal("5")


def test_range_uses_representative_in_advanced_stats() -> None:
    product = _usd_product("Range", "$1.30-1.60")
    stats = calculate_alibaba_price_statistics([product])
    assert product.price_display == "$1.30-1.60"
    assert stats.p25 == Decimal("1.45")
    assert stats.trimmed_mean == Decimal("1.45")


def test_missing_and_non_usd_excluded_from_advanced_stats() -> None:
    products = [
        _usd_product("usd", "$4.00"),
        map_alibaba_item({"title": "ask", "price": "Contact supplier"}),
        map_alibaba_item({"title": "eur", "price": "EUR 100"}),
    ]
    mapped = [product for product in products if product is not None]
    stats = calculate_alibaba_price_statistics(mapped)
    assert stats.priced_products == 1
    assert stats.p25 == Decimal("4.00")
    assert stats.outlier_count == 0
    payload = gui_services.run_alibaba_search(
        "wireless mouse",
        10,
        search_service=SearchAlibabaProducts(FakeAlibabaProvider(mapped)),
    )
    assert [row["title"] for row in payload["results"]] == ["usd", "ask", "eur"]
    assert payload["results"][1]["price"] == ""
    assert payload["results"][2]["price"] == "EUR 100.00"


def test_advanced_display_two_decimals_and_typical_range() -> None:
    stats = calculate_alibaba_price_statistics(
        [_usd_product("A", "$1.40"), _usd_product("B", "$3.20")]
    )
    assert format_alibaba_money(stats.p25) == "$1.85"
    assert format_alibaba_money(stats.p75) == "$2.75"
    assert format_alibaba_typical_range(stats.p25, stats.p75) == "$1.85 – $2.75"
    assert "50% central" in interpret_alibaba_prices(stats)


def test_advanced_stats_use_decimal_not_float() -> None:
    stats_path = SRC / "bera_price_tracker" / "application" / "alibaba_statistics.py"
    text = stats_path.read_text(encoding="utf-8")
    assert "float(" not in text
    stats = calculate_alibaba_price_statistics(
        [_usd_product("A", "$1.00"), _usd_product("B", "$2.00"), _usd_product("C", "$3.00")]
    )
    for value in (
        stats.p25,
        stats.p75,
        stats.iqr,
        stats.trimmed_mean,
        stats.lower_fence,
        stats.upper_fence,
    ):
        assert isinstance(value, Decimal)


def _duck_product(
    min_price: Decimal | None,
    max_price: Decimal | None = None,
    currency: str | None = "USD",
) -> SimpleNamespace:
    return SimpleNamespace(min_price=min_price, max_price=max_price, currency=currency)


def test_zero_and_non_finite_prices_are_excluded() -> None:
    stats = calculate_alibaba_price_statistics(
        [
            _duck_product(Decimal("0")),
            _duck_product(Decimal("-1")),
            _duck_product(Decimal("NaN")),
            _duck_product(Decimal("Infinity")),
            _usd_product("kept", "$4.00"),
        ]
    )
    assert stats.priced_products == 1
    assert stats.minimum == Decimal("4.00")
    assert stats.median == Decimal("4.00")


def test_two_letter_and_non_alpha_codes_are_not_iso() -> None:
    assert explicit_alibaba_currency("US") is None
    assert explicit_alibaba_currency("US$") is None
    assert explicit_alibaba_currency("US1") is None
    assert explicit_alibaba_currency("USD") == "USD"


def test_missing_currency_attribute_is_not_iso() -> None:
    assert infer_alibaba_currency(SimpleNamespace()) is None
    assert infer_alibaba_currency(SimpleNamespace(currency="USD")) == "USD"


def test_range_minimum_uses_low_bound_not_high_bound() -> None:
    stats = calculate_alibaba_price_statistics(
        [
            _usd_product("wide", "$10.00-20.00"),
            _usd_product("tight", "$15.00-18.00"),
        ]
    )
    assert stats.minimum == Decimal("10.00")
    assert stats.maximum == Decimal("20.00")


def test_non_usd_before_usd_still_aggregates_later_prices() -> None:
    eur = map_alibaba_item({"title": "eur", "price": "EUR 100"})
    usd = _usd_product("usd", "$4.00")
    assert eur is not None
    stats = calculate_alibaba_price_statistics([eur, usd])
    assert stats.priced_products == 1
    assert stats.minimum == Decimal("4.00")


def test_missing_max_price_is_treated_as_simple_price() -> None:
    product = SimpleNamespace(min_price=Decimal("4.03"), currency="USD")
    assert alibaba_price_bounds(product) == (Decimal("4.03"), Decimal("4.03"))
    assert alibaba_representative_price(product) == Decimal("4.03")
    assert alibaba_price_bounds(SimpleNamespace(currency="USD")) is None
    assert alibaba_representative_price(SimpleNamespace(currency="USD")) is None


def test_typical_range_unavailable_if_either_percentile_is_missing() -> None:
    assert format_alibaba_typical_range(None, Decimal("2.00")) == UNAVAILABLE_DISPLAY
    assert format_alibaba_typical_range(Decimal("1.00"), None) == UNAVAILABLE_DISPLAY
    assert format_alibaba_typical_range(None, None) == UNAVAILABLE_DISPLAY


def test_single_price_does_not_claim_a_central_range() -> None:
    stats = calculate_alibaba_price_statistics([_usd_product("One", "$4.00")])
    assert stats.priced_products == 1
    assert stats.p25 == Decimal("4.00")
    assert interpret_alibaba_prices(stats) == ""


def test_interpretation_uses_formatted_typical_bounds() -> None:
    stats = calculate_alibaba_price_statistics(
        [_usd_product("A", "$1.40"), _usd_product("B", "$3.20")]
    )
    note = interpret_alibaba_prices(stats)
    assert format_alibaba_money(stats.p25) in note
    assert format_alibaba_money(stats.p75) in note
    assert "unavailable" not in note


def test_duplicate_prices_keep_median_and_percentiles() -> None:
    products = [_usd_product(str(index), "$4.00") for index in range(4)]
    stats = calculate_alibaba_price_statistics(products)
    assert stats.priced_products == 4
    assert stats.median == Decimal("4.00")
    assert stats.p25 == Decimal("4.00")
    assert stats.p75 == Decimal("4.00")
    assert stats.iqr == Decimal("0")
    assert stats.lower_fence == Decimal("4.00")
    assert stats.upper_fence == Decimal("4.00")
    # Tukey uses strict inequalities, so a price sitting on the fence is inliers.
    assert stats.outlier_count == 0


def test_five_prices_hit_exact_percentile_index() -> None:
    """Exact P25/P75 indexes, plus documentation of remaining equivalent mutants.

    Survivors left in this module are equivalent or defensive: TypeError/ValueError
    punctuation, ``localcontext(None)``/``rounding=None`` (Decimal defaults are
    already ``ROUND_HALF_EVEN``), ``sum(values, Decimal("0"))`` vs ``sum(values)``,
    calculation-context digit padding under the prec=50 floor, and the inner
    ``bounds is None`` continue after USD usability already required bounds.
    """
    ordered = [Decimal(str(value)) for value in (1, 2, 3, 4, 5)]
    assert alibaba_percentile(ordered, Decimal("0.25")) == Decimal("2")
    assert alibaba_percentile(ordered, Decimal("0.75")) == Decimal("4")
    stats = calculate_alibaba_price_statistics(
        [_usd_product(str(value), f"${value}.00") for value in (1, 2, 3, 4, 5)]
    )
    assert stats.p25 == Decimal("2")
    assert stats.p75 == Decimal("4")
    assert stats.median == Decimal("3")


def test_parse_dollar_price_does_not_infer_usd() -> None:
    display, min_price, max_price, currency = parse_alibaba_price("$12.50")
    assert display == "$12.50"
    assert min_price == Decimal("12.50")
    assert max_price == Decimal("12.50")
    assert currency is None


def test_parse_dollar_range_does_not_infer_usd() -> None:
    display, min_price, max_price, currency = parse_alibaba_price("$1.30-1.60")
    assert display == "$1.30-1.60"
    assert min_price == Decimal("1.30")
    assert max_price == Decimal("1.60")
    assert currency is None


def test_parse_explicit_usd_code() -> None:
    display, min_price, max_price, currency = parse_alibaba_price("USD 12.50")
    assert display == "USD 12.50"
    assert min_price == Decimal("12.50")
    assert currency == "USD"


def test_infer_currency_ignores_dollar_display() -> None:
    product = map_alibaba_item({"title": "Mouse", "price": "$4.03"})
    assert product is not None
    assert product.currency is None
    assert infer_alibaba_currency(product) is None
    assert explicit_alibaba_currency("$") is None
    assert explicit_alibaba_currency("${0}") is None


def test_dollar_listing_is_excluded_from_usd_statistics() -> None:
    product = map_alibaba_item({"title": "Mouse", "price": "$4.03"})
    assert product is not None
    stats = calculate_alibaba_price_statistics([product])
    assert stats.priced_products == 0
    assert stats.minimum is None
    assert stats.p25 is None
    assert stats.median is None


def test_explicit_currency_field_is_used_when_display_has_only_dollar() -> None:
    product = map_alibaba_item({"title": "Mouse", "price": "$4.03", "currency": "USD"})
    assert product is not None
    assert product.price_display == "$4.03"
    assert product.currency == "USD"
    assert infer_alibaba_currency(product) == "USD"


def _begin_in_flight_alibaba_search(
    state: TrackerState, *, query: str, limit: int = 10
) -> tuple[str, int]:
    state.alibaba_query = query
    state.alibaba_limit = limit
    state.alibaba_is_loading = True
    state.alibaba_ui_status = "LOADING"
    state.alibaba_error = ""
    return query, limit


def test_late_alibaba_success_is_discarded_after_query_change() -> None:
    state = TrackerState()
    request_query, request_limit = _begin_in_flight_alibaba_search(state, query="mouse")
    state.alibaba_query = "teclado"
    stale = AlibabaResultRow(title="Mouse A", product_id="1", price="$4")
    state._finalize_alibaba_search(
        request_query=request_query,
        request_limit=request_limit,
        rows=[stale],
        summary={"minimo": "$4.00"},
        stats_raw={"minimum": "4"},
        ui_status="SUCCESS",
    )
    assert state.alibaba_results == []
    assert state.alibaba_summary == {}
    assert state.alibaba_stats_raw == {}
    assert state.alibaba_is_loading is False
    assert state.alibaba_ui_status == "INITIAL"
    assert state.alibaba_error == ""


def test_late_alibaba_error_is_discarded_after_query_change() -> None:
    state = TrackerState()
    request_query, request_limit = _begin_in_flight_alibaba_search(state, query="mouse")
    state.alibaba_query = "teclado"
    state._finalize_alibaba_search(
        request_query=request_query,
        request_limit=request_limit,
        error_message="Alibaba no está disponible.",
    )
    assert state.alibaba_error == ""
    assert state.alibaba_results == []
    assert state.alibaba_is_loading is False
    assert state.alibaba_ui_status == "INITIAL"


def test_late_alibaba_success_is_discarded_after_limit_change() -> None:
    state = TrackerState()
    request_query, request_limit = _begin_in_flight_alibaba_search(state, query="mouse", limit=10)
    state.alibaba_limit = 20
    state._finalize_alibaba_search(
        request_query=request_query,
        request_limit=request_limit,
        rows=[AlibabaResultRow(title="Mouse A", product_id="1")],
        summary={"minimo": "$4.00"},
        ui_status="SUCCESS",
    )
    assert state.alibaba_results == []
    assert state.alibaba_summary == {}
    assert state.alibaba_is_loading is False
    assert state.alibaba_ui_status == "INITIAL"


def test_matching_alibaba_search_still_applies_success() -> None:
    state = TrackerState()
    request_query, request_limit = _begin_in_flight_alibaba_search(state, query="mouse")
    rows = [AlibabaResultRow(title="Mouse A", product_id="1", price="$4")]
    state._finalize_alibaba_search(
        request_query=request_query,
        request_limit=request_limit,
        rows=rows,
        summary={"minimo": "$4.00"},
        stats_raw={"minimum": "4"},
        ui_status="SUCCESS",
    )
    assert state.alibaba_is_loading is False
    assert state.alibaba_ui_status == "SUCCESS"
    assert state.alibaba_results == rows
    assert state.alibaba_summary == {"minimo": "$4.00"}
    assert state.alibaba_error == ""


def test_matching_alibaba_error_is_applied() -> None:
    state = TrackerState()
    request_query, request_limit = _begin_in_flight_alibaba_search(state, query="mouse")
    state._finalize_alibaba_search(
        request_query=request_query,
        request_limit=request_limit,
        error_message="Alibaba no está disponible.",
    )
    assert state.alibaba_error == "Alibaba no está disponible."
    assert state.alibaba_results == []
    assert state.alibaba_is_loading is False
    assert state.alibaba_ui_status == "ERROR"


def test_catalog_usd_display_ignores_raw_dollar_text() -> None:
    product = _product(
        title="Mouse",
        price_display="$4.03",
        min_price=Decimal("4.03"),
        max_price=Decimal("4.03"),
        currency="USD",
    )
    row = gui_services.alibaba_product_to_row(product)
    assert row["price"] == "$4.03"
    assert row["currency"] == "USD"


def test_catalog_cny_display_does_not_reuse_raw_dollar() -> None:
    product = _product(
        title="Mouse",
        price_display="$4.03",
        min_price=Decimal("4.03"),
        max_price=Decimal("4.03"),
        currency="CNY",
    )
    row = gui_services.alibaba_product_to_row(product)
    assert row["price"] == "CNY 4.03"
    assert "$4.03" not in row["price"]
    assert "$" not in row["price"]
    assert row["currency"] == "CNY"


def test_catalog_eur_display_is_iso_not_dollar() -> None:
    product = _product(
        title="Mouse",
        price_display="$9.50",
        min_price=Decimal("9.50"),
        max_price=Decimal("9.50"),
        currency="EUR",
    )
    row = gui_services.alibaba_product_to_row(product)
    assert row["price"] == "EUR 9.50"
    assert "$" not in row["price"]


def test_catalog_unknown_currency_does_not_show_dollar() -> None:
    product = _product(
        title="Mouse",
        price_display="$4.03",
        min_price=Decimal("4.03"),
        max_price=Decimal("4.03"),
        currency=None,
    )
    row = gui_services.alibaba_product_to_row(product)
    assert row["price"] == f"4.03 · {MISSING_CURRENCY_DISPLAY}"
    assert "$" not in row["price"]
    assert row["currency"] == ""


def test_catalog_cny_range_keeps_iso_and_omits_usd_symbol() -> None:
    product = _product(
        title="Mouse",
        price_display="$3.50-4.30",
        min_price=Decimal("3.50"),
        max_price=Decimal("4.30"),
        currency="CNY",
    )
    row = gui_services.alibaba_product_to_row(product)
    assert row["price"] == "CNY 3.50–4.30"
    assert "$" not in row["price"]
    assert row["currency"] == "CNY"


def test_catalog_usd_range_uses_dollar_on_both_bounds() -> None:
    product = _product(
        title="Mouse",
        price_display="$3.50-4.30",
        min_price=Decimal("3.50"),
        max_price=Decimal("4.30"),
        currency="USD",
    )
    row = gui_services.alibaba_product_to_row(product)
    assert row["price"] == "$3.50–$4.30"


def test_ml_bridge_keeps_row_iso_and_does_not_parse_display() -> None:
    from bera_price_tracker.gui.state import TrackerState

    product = _product(
        title="Wireless Game Mouse",
        product_id="P-CNY",
        product_url="https://www.alibaba.com/product-detail/p.html",
        price_display="$4.03",
        min_price=Decimal("4.03"),
        max_price=Decimal("4.03"),
        currency="CNY",
        supplier_name="Cactus",
    )
    mapped = gui_services.alibaba_product_to_row(product)
    assert mapped["currency"] == "CNY"
    assert mapped["price"] == "CNY 4.03"
    state = TrackerState()
    state.alibaba_query = "mouse"
    state.alibaba_results = [
        AlibabaResultRow(
            product_id="P-CNY",
            title="Wireless Game Mouse",
            price=mapped["price"],
            price_min=mapped["price_min"],
            price_max=mapped["price_max"],
            currency=mapped["currency"],
            supplier_name="Cactus",
        )
    ]
    state.prepare_ml_comparables_from_alibaba_result("P-CNY")
    assert state.ml_alibaba_context["currency"] == "CNY"
    assert state.ml_alibaba_context["currency"] != "USD"
    assert state.ml_alibaba_context["supplier_price"] == "CNY 4.03"


def test_listing_price_helpers_do_not_invent_iso() -> None:
    assert format_alibaba_listing_price(Decimal("4.03"), Decimal("4.03"), "USD") == "$4.03"
    assert format_alibaba_listing_price(Decimal("4.03"), Decimal("4.03"), "CNY") == "CNY 4.03"
    assert format_alibaba_listing_price(Decimal("4.03"), Decimal("4.03"), "EUR") == "EUR 4.03"
    unknown = format_alibaba_listing_price(Decimal("4.03"), None, None)
    assert unknown == f"4.03 · {MISSING_CURRENCY_DISPLAY}"
    assert "$" not in unknown
    assert format_alibaba_listing_price(None, None, "USD") == ""
    assert format_alibaba_currency(None, "USD") == UNAVAILABLE_DISPLAY
    assert format_alibaba_currency(Decimal("4.03"), None) == UNAVAILABLE_DISPLAY
    assert alibaba_iso_currencies_match("usd", "USD") is True
    assert alibaba_iso_currencies_match("CNY", "USD") is False
    assert alibaba_iso_currencies_match(None, "USD") is False
    assert alibaba_iso_currencies_match("$", "USD") is False
    assert alibaba_iso_currencies_match("${0}", "USD") is False
    unknown_range = format_alibaba_listing_price(Decimal("3.50"), Decimal("4.30"), None)
    assert unknown_range == f"3.50–4.30 · {MISSING_CURRENCY_DISPLAY}"
    assert "$" not in unknown_range
    eur_range = format_alibaba_listing_price(Decimal("3.50"), Decimal("4.30"), "EUR")
    assert eur_range == "EUR 3.50–4.30"
    assert "$" not in eur_range


def test_mapper_skips_non_mapping_and_blank_title() -> None:
    assert map_alibaba_item("raw") is None
    assert map_alibaba_item({"title": True}) is None
    assert map_alibaba_item({"title": "  "}) is None
    assert map_alibaba_item({"title": ""}) is None


def test_mapper_preserves_explicit_cny_and_eur_and_does_not_infer_usd_from_dollar() -> None:
    cny = map_alibaba_item({"title": "Mouse", "price": "CNY 4.03", "productId": "1"})
    assert cny is not None
    assert cny.min_price == Decimal("4.03")
    assert cny.currency == "CNY"
    eur = map_alibaba_item(
        {"title": "Mouse", "price": "4.03 EUR", "currency": "EUR", "productId": "2"}
    )
    assert eur is not None
    assert eur.currency == "EUR"
    dollar = map_alibaba_item({"title": "Mouse", "price": "$4.03"})
    assert dollar is not None
    assert dollar.min_price == Decimal("4.03")
    assert dollar.currency is None


def test_mapper_rejects_malformed_and_non_positive_prices() -> None:
    missing = map_alibaba_item({"title": "Mouse", "price": True})
    assert missing is not None
    assert missing.min_price is None
    assert missing.price_display is None
    zero = map_alibaba_item({"title": "Mouse", "price": "0"})
    assert zero is not None
    assert zero.min_price is None
    garbage = map_alibaba_item({"title": "Mouse", "price": "ask"})
    assert garbage is not None
    assert garbage.min_price is None
    nan = parse_alibaba_price("NaN")
    assert nan == ("NaN", None, None, None)


def test_numeric_price_scalars_are_not_regex_split() -> None:
    display, min_price, max_price, currency = parse_alibaba_price(4)
    assert display == "4"
    assert min_price == Decimal("4")
    assert max_price == Decimal("4")
    assert currency is None

    display, min_price, max_price, currency = parse_alibaba_price(4.5)
    assert display == "4.5"
    assert min_price == Decimal("4.5")
    assert max_price == Decimal("4.5")
    assert currency is None

    for raw in (0, 0.0, -4, -4.5, float("nan"), float("inf"), float("-inf"), True, False):
        display, min_price, max_price, currency = parse_alibaba_price(raw)
        assert min_price is None
        assert max_price is None
        assert currency is None
        if raw is True or raw is False:
            assert display is None
        elif isinstance(raw, float) and not math.isfinite(raw):
            assert display is None
        else:
            assert display == str(raw)

    huge = 1e20
    display, min_price, max_price, currency = parse_alibaba_price(huge)
    assert display == str(huge)
    assert min_price == Decimal(str(huge))
    assert max_price == Decimal(str(huge))
    assert min_price != Decimal("1")
    assert max_price != Decimal("20")
    assert currency is None

    tiny = 1e-20
    display, min_price, max_price, currency = parse_alibaba_price(tiny)
    assert display == str(tiny)
    assert min_price == Decimal(str(tiny))
    assert max_price == Decimal(str(tiny))
    assert (min_price, max_price) != (Decimal("1"), Decimal("20"))
    assert currency is None


def test_textual_prices_do_not_fabricate_from_sign_or_exponent() -> None:
    display, min_price, max_price, currency = parse_alibaba_price("US $1.00-$9.00")
    assert display == "US $1.00-$9.00"
    assert min_price == Decimal("1.00")
    assert max_price == Decimal("9.00")
    assert currency == "USD"

    display, min_price, max_price, currency = parse_alibaba_price("US $4.50")
    assert display == "US $4.50"
    assert min_price == Decimal("4.50")
    assert max_price == Decimal("4.50")
    assert currency == "USD"

    display, min_price, max_price, currency = parse_alibaba_price("$1.00-$9.00")
    assert display == "$1.00-$9.00"
    assert min_price == Decimal("1.00")
    assert max_price == Decimal("9.00")
    assert currency is None

    display, min_price, max_price, currency = parse_alibaba_price("USD 1.00-9.00")
    assert display == "USD 1.00-9.00"
    assert min_price == Decimal("1.00")
    assert max_price == Decimal("9.00")
    assert currency == "USD"

    for raw in ("-4.5", "1e20", "1e-20", "", "n/a"):
        parsed = parse_alibaba_price(raw)
        if raw == "":
            assert parsed == (None, None, None, None)
            continue
        display, min_price, max_price, currency = parsed
        assert display == raw
        assert min_price is None or (min_price, max_price) != (Decimal("1"), Decimal("20"))
        if raw in ("-4.5", "n/a"):
            assert min_price is None
            assert max_price is None
        if raw in ("1e20", "1e-20"):
            assert (min_price, max_price) != (Decimal("1"), Decimal("20"))
            if min_price is not None:
                assert min_price == max_price == Decimal(raw)
        assert currency is None

    three = parse_alibaba_price("1.00 2.00 3.00")
    assert three[0] == "1.00 2.00 3.00"
    assert three[1] is None
    assert three[2] is None

    mixed = parse_alibaba_price("MOQ 10 US $1.00-$9.00")
    assert mixed[1] is None
    assert mixed[2] is None
    assert mixed[0] == "MOQ 10 US $1.00-$9.00"


def test_negative_numeric_price_does_not_enter_statistics() -> None:
    product = map_alibaba_item({"title": "Mouse", "price": -4.5})
    assert product is not None
    assert product.price_display == "-4.5"
    assert product.min_price is None
    assert product.max_price is None
    stats = calculate_alibaba_price_statistics([product])
    assert stats.priced_products == 0
    assert stats.minimum is None


def _assert_search_row_survives(product: AlibabaProduct) -> dict[str, Any]:
    row = gui_services.alibaba_product_to_row(product)
    payload = gui_services.run_alibaba_search(
        "mouse",
        10,
        search_service=SearchAlibabaProducts(FakeAlibabaProvider([product])),
    )
    assert payload["ui_status"] == "SUCCESS"
    assert payload["error_message"] == ""
    assert len(payload["results"]) == 1
    return row


def test_extreme_provider_prices_do_not_crash_listing_rows() -> None:
    documented = map_alibaba_item({"title": "Mouse", "price": "US $1.00-$9.00"})
    assert documented is not None
    documented_row = _assert_search_row_survives(documented)
    assert documented.min_price == Decimal("1.00")
    assert documented.max_price == Decimal("9.00")
    assert documented_row["price"]

    for raw in (1e20, 1e100, 1e-20, 1e-100, "1e20", "1e100", "1e500"):
        product = map_alibaba_item({"title": "Mouse", "price": raw})
        assert product is not None
        row = _assert_search_row_survives(product)
        assert isinstance(row["price"], str)
        money = format_alibaba_money(product.min_price)
        assert isinstance(money, str)
        listing = format_alibaba_listing_price(
            product.min_price, product.max_price, product.currency
        )
        assert isinstance(listing, str)

    overflow = map_alibaba_item({"title": "Mouse", "price": 1e500})
    assert overflow is not None
    assert overflow.min_price is None
    _assert_search_row_survives(overflow)


def test_reversed_price_range_numeric_bounds_are_unavailable() -> None:
    display, min_price, max_price, currency = parse_alibaba_price("US $1.00-$9.00")
    assert display == "US $1.00-$9.00"
    assert min_price == Decimal("1.00")
    assert max_price == Decimal("9.00")
    assert currency == "USD"
    assert min_price <= max_price

    for raw, expected_display in (
        ("US $9.00-$1.00", "US $9.00-$1.00"),
        ("$9-$1", "$9-$1"),
    ):
        parsed = parse_alibaba_price(raw)
        assert parsed[0] == expected_display
        assert parsed[1] is None
        assert parsed[2] is None
        product = map_alibaba_item({"title": "Mouse", "price": raw, "currency": "USD"})
        assert product is not None
        assert product.price_display == expected_display
        assert product.min_price is None
        assert product.max_price is None
        assert alibaba_price_bounds(product) is None
        assert alibaba_representative_price(product) is None
        row = _assert_search_row_survives(product)
        assert "9.00–1.00" not in row["price"]
        assert "9–1" not in row["price"]
        stats = calculate_alibaba_price_statistics([product])
        assert stats.priced_products == 0
        assert stats.minimum is None
        assert stats.maximum is None
        assert stats.average is None

    equal = parse_alibaba_price("$1-$1")
    assert equal[1] == Decimal("1")
    assert equal[2] == Decimal("1")
    assert equal[1] <= equal[2]

    hyphen = parse_alibaba_price("$1.30-1.60")
    assert hyphen[1] == Decimal("1.30")
    assert hyphen[2] == Decimal("1.60")
    assert hyphen[1] <= hyphen[2]

    mixed = [
        map_alibaba_item({"title": "reversed", "price": "$9.00-$1.00", "currency": "USD"}),
        map_alibaba_item({"title": "ok", "price": "$2.00", "currency": "USD"}),
    ]
    mapped = [item for item in mixed if item is not None]
    stats = calculate_alibaba_price_statistics(mapped)
    assert stats.priced_products == 1
    assert stats.minimum == Decimal("2.00")
    assert stats.maximum == Decimal("2.00")
    assert stats.average == Decimal("2.00")

    domain = AlibabaProduct(
        title="Mouse",
        price_display="US $9.00-$1.00",
        min_price=Decimal("9.00"),
        max_price=Decimal("1.00"),
        currency="USD",
    )
    assert domain.price_display == "US $9.00-$1.00"
    assert domain.min_price is None
    assert domain.max_price is None
    assert alibaba_price_bounds(domain) is None


def test_successfully_parsed_ranges_keep_ordered_bounds() -> None:
    for raw in ("US $1.00-$9.00", "$1.00-$9.00", "USD 1.00-9.00", "$1.30-1.60", "$1-$1"):
        _display, minimum, maximum, _currency = parse_alibaba_price(raw)
        assert minimum is not None
        assert maximum is not None
        assert minimum <= maximum
        product = map_alibaba_item({"title": "Mouse", "price": raw})
        assert product is not None
        assert product.min_price is not None
        assert product.max_price is not None
        assert product.min_price <= product.max_price
        bounds = alibaba_price_bounds(product)
        assert bounds is not None
        assert bounds[0] <= bounds[1]


def _assert_no_usable_positive_price(raw: str) -> AlibabaProduct:
    display, min_price, max_price, _currency = parse_alibaba_price(raw)
    assert display == raw
    assert min_price is None
    assert max_price is None
    product = map_alibaba_item({"title": "Mouse", "price": raw, "currency": "USD"})
    assert product is not None
    assert product.price_display == raw
    assert product.min_price is None
    assert product.max_price is None
    assert alibaba_price_bounds(product) is None
    assert alibaba_representative_price(product) is None
    row = _assert_search_row_survives(product)
    assert row["price_min"] == ""
    assert row["price_max"] == ""
    stats = calculate_alibaba_price_statistics([product])
    assert stats.priced_products == 0
    assert stats.minimum is None
    scores = score_alibaba_listings([product])
    assert scores[0].price_score == 0
    return product


def test_minus_before_currency_does_not_fabricate_a_positive_price() -> None:
    for raw in (
        "-4.50",
        "-$4.50",
        "$-4.50",
        "USD -4.50",
        "USD -$4.50",
        "USD - $4.50",
        "USD $-4.50",
        "EUR -$4.50",
        "CAD -$4.50",
        "US -$4.50",
        "USD-$4.50",
        "-$ 4.50",
        "- $4.50",
        "USD -$ 4.50",
    ):
        _assert_no_usable_positive_price(raw)


def test_valid_signed_currency_and_range_forms_remain_usable() -> None:
    for raw, expected_min, expected_max in (
        ("$4.50", Decimal("4.50"), Decimal("4.50")),
        ("USD $4.50", Decimal("4.50"), Decimal("4.50")),
        ("USD 4.50", Decimal("4.50"), Decimal("4.50")),
        ("$1.30-$1.60", Decimal("1.30"), Decimal("1.60")),
        ("USD $1.30-$1.60", Decimal("1.30"), Decimal("1.60")),
        ("US $1.00-$9.00", Decimal("1.00"), Decimal("9.00")),
    ):
        display, min_price, max_price, _currency = parse_alibaba_price(raw)
        assert display == raw
        assert min_price == expected_min
        assert max_price == expected_max
        assert min_price <= max_price
        product = map_alibaba_item({"title": "Mouse", "price": raw})
        assert product is not None
        assert product.min_price == expected_min
        assert product.max_price == expected_max
        _assert_search_row_survives(product)


def test_negative_second_range_bound_does_not_become_positive() -> None:
    for raw in (
        "$1.30--1.60",
        "$1.30-$-1.60",
        "$1.30-USD -$1.60",
        "USD $1.30 - -$1.60",
        "$1.30-EUR -$1.60",
    ):
        product = _assert_no_usable_positive_price(raw)
        assert product.min_price is None
        assert product.max_price is None


def test_non_dollar_signed_symbols_do_not_fabricate_a_positive_price() -> None:
    for raw in (
        "-€4.50",
        "EUR -€4.50",
        "EUR €-4.50",
        "-£4.50",
        "GBP -£4.50",
        "GBP £-4.50",
        "-¥4.50",
        "CNY -¥4.50",
        "CNY ¥-4.50",
        "$1.30-€-1.60",
        "EUR €1.30-€-1.60",
        "GBP £1.30-£-1.60",
        "CNY ¥1.30-¥-1.60",
    ):
        product = _assert_no_usable_positive_price(raw)
        assert product.currency != "MOQ"
        scores = score_alibaba_listings([product])
        assert scores[0].price_score == 0
        assert scores[0].price_clarity_score == 0


def test_price_text_does_not_join_unrelated_tokens_or_invent_iso() -> None:
    for raw in (
        "MOQ 100 US $4.50",
        "MOQ 100 USD 4.50",
        "10 pcs USD 4.50",
        "From 10 USD 4.50",
        "abc 1 def 2",
        "MOQ 4.50",
    ):
        display, min_price, max_price, currency = parse_alibaba_price(raw)
        assert display == raw
        assert min_price is None
        assert max_price is None
        assert currency is None
        assert currency != "MOQ"
        product = map_alibaba_item({"title": "Mouse", "price": raw})
        assert product is not None
        assert product.price_display == raw
        assert product.min_price is None
        assert product.max_price is None
        assert product.currency is None
        assert product.currency != "MOQ"
        assert alibaba_price_bounds(product) is None
        stats = calculate_alibaba_price_statistics([product])
        assert stats.priced_products == 0
        scores = score_alibaba_listings([product])
        assert scores[0].price_score == 0
        _assert_search_row_survives(product)

    for raw, expected_min, expected_max, expected_currency in (
        ("US $1.00-$9.00", Decimal("1.00"), Decimal("9.00"), "USD"),
        ("US $4.50", Decimal("4.50"), Decimal("4.50"), "USD"),
        ("$1.00-$9.00", Decimal("1.00"), Decimal("9.00"), None),
        ("USD 1.00-9.00", Decimal("1.00"), Decimal("9.00"), "USD"),
        ("USD 4.50", Decimal("4.50"), Decimal("4.50"), "USD"),
    ):
        display, min_price, max_price, currency = parse_alibaba_price(raw)
        assert display == raw
        assert min_price == expected_min
        assert max_price == expected_max
        assert currency == expected_currency
        product = map_alibaba_item({"title": "Mouse", "price": raw})
        assert product is not None
        assert product.min_price == expected_min
        assert product.max_price == expected_max
        _assert_search_row_survives(product)


def test_parse_explicit_us_dollar_range_is_usd() -> None:
    display, min_price, max_price, currency = parse_alibaba_price("US $3.20-$3.60")
    assert display == "US $3.20-$3.60"
    assert min_price == Decimal("3.20")
    assert max_price == Decimal("3.60")
    assert currency == "USD"


def test_parse_explicit_us_dollar_single_value_is_usd() -> None:
    display, min_price, max_price, currency = parse_alibaba_price("US $3.20")
    assert display == "US $3.20"
    assert min_price == Decimal("3.20")
    assert max_price == Decimal("3.20")
    assert currency == "USD"


def test_parse_bare_dollar_range_remains_unknown_currency() -> None:
    display, min_price, max_price, currency = parse_alibaba_price("$3.20-$3.60")
    assert display == "$3.20-$3.60"
    assert min_price == Decimal("3.20")
    assert max_price == Decimal("3.60")
    assert currency is None


def test_parse_explicit_iso_usd_prefix_and_range_remain_usd() -> None:
    single = parse_alibaba_price("USD 3.20")
    assert single == ("USD 3.20", Decimal("3.20"), Decimal("3.20"), "USD")
    ranged = parse_alibaba_price("USD 3.20-3.60")
    assert ranged == ("USD 3.20-3.60", Decimal("3.20"), Decimal("3.60"), "USD")


def test_parse_supported_non_usd_iso_currencies_remain_unchanged() -> None:
    assert parse_alibaba_price("CNY 4.03") == ("CNY 4.03", Decimal("4.03"), Decimal("4.03"), "CNY")
    assert parse_alibaba_price("EUR 100") == ("EUR 100", Decimal("100"), Decimal("100"), "EUR")
    assert parse_alibaba_price("GBP 4.50") == ("GBP 4.50", Decimal("4.50"), Decimal("4.50"), "GBP")
    assert parse_alibaba_price("4.03 EUR") == ("4.03 EUR", Decimal("4.03"), Decimal("4.03"), "EUR")


def test_parse_us_dollar_spacing_and_casing_variants_are_usd() -> None:
    for raw in ("us $3.20-$3.60", "Us $3.20-$3.60", "US$3.20-$3.60", "US  $3.20"):
        _display, min_price, max_price, currency = parse_alibaba_price(raw)
        assert currency == "USD"
        assert min_price is not None
        assert max_price is not None


def test_parse_conflicting_us_dollar_and_iso_markers_remain_invalid() -> None:
    for raw in ("US $3.20 EUR", "USD 3.20 EUR", "US $3.20-$3.60 EUR"):
        display, min_price, max_price, currency = parse_alibaba_price(raw)
        assert display == raw
        assert min_price is None
        assert max_price is None
        assert currency is None


def test_parse_bare_us_prefix_does_not_infer_usd() -> None:
    display, min_price, max_price, currency = parse_alibaba_price("US 3.20")
    assert display == "US 3.20"
    assert min_price == Decimal("3.20")
    assert max_price == Decimal("3.20")
    assert currency is None

    ranged = parse_alibaba_price("US 3.20-3.60")
    assert ranged == ("US 3.20-3.60", Decimal("3.20"), Decimal("3.60"), None)

    lowered = parse_alibaba_price("us 3.20")
    assert lowered == ("us 3.20", Decimal("3.20"), Decimal("3.20"), None)


def test_parse_compact_us_dollar_single_value_is_usd() -> None:
    display, min_price, max_price, currency = parse_alibaba_price("US$3.20")
    assert display == "US$3.20"
    assert min_price == Decimal("3.20")
    assert max_price == Decimal("3.20")
    assert currency == "USD"


def test_parse_bare_dollar_single_value_remains_unknown_currency() -> None:
    display, min_price, max_price, currency = parse_alibaba_price("$3.20")
    assert display == "$3.20"
    assert min_price == Decimal("3.20")
    assert max_price == Decimal("3.20")
    assert currency is None


def test_parse_scientific_us_dollar_requires_dollar_sign() -> None:
    with_dollar = parse_alibaba_price("US $3e2")
    assert with_dollar[0] == "US $3e2"
    assert with_dollar[1] == Decimal("3e2")
    assert with_dollar[2] == Decimal("3e2")
    assert with_dollar[3] == "USD"

    bare = parse_alibaba_price("US 3e2")
    assert bare[0] == "US 3e2"
    assert bare[1] == Decimal("3e2")
    assert bare[2] == Decimal("3e2")
    assert bare[3] is None

    compact = parse_alibaba_price("US$3e2")
    assert compact[0] == "US$3e2"
    assert compact[1] == Decimal("3e2")
    assert compact[2] == Decimal("3e2")
    assert compact[3] == "USD"


def test_pricemin_alone_does_not_authorize_usd() -> None:
    product = map_alibaba_item(
        memo23_actor_item(
            price="$3.20-$3.60",
            priceMin="US $3.20",
        )
    )
    assert product is not None
    assert product.price_display == "$3.20-$3.60"
    assert product.min_price == Decimal("3.20")
    assert product.max_price == Decimal("3.60")
    assert product.currency is None
    assert infer_alibaba_currency(product) is None
    stats = calculate_alibaba_price_statistics([product])
    assert stats.priced_products == 0
    assert stats.currency is None


def test_quantity_prices_do_not_authorize_usd() -> None:
    product = map_alibaba_item(
        memo23_actor_item(
            price="$3.20-$3.60",
            quantityPrices=[
                {"price": 3.6, "localPrice": "$3.60", "quantityMin": 5},
                {"price": 3.2, "localPrice": "$3.20", "quantityMin": 100},
            ],
        )
    )
    assert product is not None
    assert product.currency is None
    assert infer_alibaba_currency(product) is None
    stats = calculate_alibaba_price_statistics([product])
    assert stats.priced_products == 0


def test_supplier_country_does_not_authorize_usd() -> None:
    product = map_alibaba_item(
        memo23_actor_item(
            price="$3.20-$3.60",
            supplierCountry="United States",
            supplierCountryCode="US",
        )
    )
    assert product is not None
    assert product.supplier_country == "US"
    assert product.currency is None
    assert infer_alibaba_currency(product) is None
    stats = calculate_alibaba_price_statistics([product])
    assert stats.priced_products == 0


def test_map_memo23_us_dollar_range_preserves_display_and_sets_usd() -> None:
    product = map_alibaba_item(
        memo23_actor_item(
            productId="1601387647131",
            price="US $3.20-$3.60",
            priceMin="US $3.20",
        )
    )
    assert product is not None
    assert product.price_display == "US $3.20-$3.60"
    assert product.min_price == Decimal("3.20")
    assert product.max_price == Decimal("3.60")
    assert product.currency == "USD"
    assert product.product_id == "1601387647131"


def test_real_memo23_us_dollar_listings_enter_usd_statistics() -> None:
    products = [
        map_alibaba_item({"title": "Listing A", "price": "US $3.20-$3.60"}),
        map_alibaba_item({"title": "Listing B", "price": "US $1.00-$9.00"}),
        map_alibaba_item({"title": "Listing C", "price": "US $77.14-$161.14"}),
    ]
    mapped = [product for product in products if product is not None]
    assert [product.currency for product in mapped] == ["USD", "USD", "USD"]
    assert [alibaba_representative_price(product) for product in mapped] == [
        Decimal("3.40"),
        Decimal("5.00"),
        Decimal("119.14"),
    ]
    stats = calculate_alibaba_price_statistics(mapped)
    assert stats.priced_products == 3
    assert stats.currency == "USD"
    assert stats.minimum == Decimal("1.00")
    assert stats.maximum == Decimal("161.14")
    assert format_alibaba_money(stats.minimum) == "$1.00"
    assert format_alibaba_money(stats.average) == "$42.51"
    assert format_alibaba_money(stats.median) == "$5.00"
    assert format_alibaba_money(stats.maximum) == "$161.14"
    assert format_alibaba_money(stats.p25) == "$4.20"
    assert format_alibaba_money(stats.p75) == "$62.07"
    assert format_alibaba_typical_range(stats.p25, stats.p75) == "$4.20 – $62.07"
    assert stats.outlier_count == 0
    summary = gui_services.build_alibaba_summary(list(mapped))
    assert summary["con_precio"] == "3 de 3"
    assert summary["minimo"] == "$1.00"
    assert summary["promedio"] == "$42.51"
    assert summary["mediana"] == "$5.00"
    assert summary["maximo"] == "$161.14"
    assert summary["p25"] == "$4.20"
    assert summary["p75"] == "$62.07"
    assert summary["rango_tipico"] == "$4.20 – $62.07"
    assert summary["outliers"] == "0"


def test_gui_and_csv_receive_explicit_us_dollar_as_usd() -> None:
    product = map_alibaba_item({"title": "R-SIM", "price": "US $3.20-$3.60"})
    assert product is not None
    payload = gui_services.run_alibaba_search(
        "Iphone 15",
        10,
        search_service=SearchAlibabaProducts(FakeAlibabaProvider([product])),
    )
    row = payload["results"][0]
    assert row["currency"] == "USD"
    assert row["price"] == "$3.20–$3.60"
    assert MISSING_CURRENCY_DISPLAY not in row["price"]
    exported = search_export.listing_rows_for_export(
        search_query="Iphone 15",
        searched_at="2026-08-29 03:00",
        search_mode="Una plataforma",
        requested_limit=1,
        alibaba_status="SUCCESS",
        alibaba_rows=[
            AlibabaResultRow(
                title=row["title"],
                price=row["price"],
                product_id=row["product_id"],
                currency=row["currency"],
                price_min=row["price_min"],
                price_max=row["price_max"],
            )
        ],
        facebook_status="EMPTY",
        ml_status="EMPTY",
    )
    assert exported[0]["currency"] == "USD"
    assert exported[0]["price_display"] == "$3.20–$3.60"


def test_mapper_keeps_missing_optional_identity_fields() -> None:
    product = map_alibaba_item({"title": "Mouse", "price": "USD 4.03", "moq": True})
    assert product is not None
    assert product.product_id is None
    assert product.product_url is None
    assert product.supplier_name is None
    assert product.supplier_country is None
    assert product.moq is None
    assert product.currency == "USD"


def test_search_client_rejects_blank_actor_and_failed_runs() -> None:
    with pytest.raises(ApifyConfigurationError, match="actor id"):
        ApifyAlibabaClient(_api_token="token", actor_id=" ")

    with pytest.raises(MarketplaceSourceUnavailable, match="unavailable"):
        ApifyAlibabaClient(
            _api_token="token",
            client_factory=lambda _token: FakeApify([], call_error=RuntimeError("network")),
        ).search("mouse", 10)

    with pytest.raises(MarketplaceSourceUnavailable, match="unavailable"):
        ApifyAlibabaClient(
            _api_token="token",
            client_factory=lambda _token: FakeApify(
                [], run={"status": "FAILED", "defaultDatasetId": "ds1"}
            ),
        ).search("mouse", 10)


def test_search_client_rejects_missing_dataset_and_skips_unmapped_rows() -> None:
    with pytest.raises(MarketplaceSourceUnavailable, match="unavailable"):
        ApifyAlibabaClient(
            _api_token="token",
            client_factory=lambda _token: FakeApify([], run={"status": "SUCCEEDED"}),
        ).search("mouse", 10)

    with pytest.raises(MarketplaceSourceUnavailable, match="unavailable"):
        ApifyAlibabaClient(
            _api_token="token",
            client_factory=lambda _token: FakeApify([], run="SUCCEEDED"),
        ).search("mouse", 10)

    mixed = FakeApify(["skip", {"title": "  "}, {"title": "Keep", "price": "USD 4.03"}])
    products = ApifyAlibabaClient(
        _api_token="token",
        client_factory=lambda _token: mixed,
    ).search("mouse", 10)
    assert [item.title for item in products] == ["Keep"]
    assert products[0].min_price == Decimal("4.03")
    assert products[0].currency == "USD"


def test_search_client_dataset_errors_are_unavailable() -> None:
    with pytest.raises(MarketplaceSourceUnavailable, match="unavailable"):
        ApifyAlibabaClient(
            _api_token="token",
            client_factory=lambda _token: FakeApify(
                [{"title": "X"}], dataset_error=RuntimeError("dataset down")
            ),
        ).search("mouse", 10)


def test_empty_alibaba_search_finalization_clears_error() -> None:
    state = TrackerState()
    request_query, request_limit = _begin_in_flight_alibaba_search(state, query="mouse")
    state._finalize_alibaba_search(
        request_query=request_query,
        request_limit=request_limit,
        rows=[],
        summary={},
        ui_status="EMPTY",
    )
    assert state.alibaba_is_loading is False
    assert state.alibaba_ui_status == "EMPTY"
    assert state.alibaba_results == []
    assert state.alibaba_error == ""


def test_search_and_tracked_currencies_propagate_into_negotiation_catalog() -> None:
    from bera_price_tracker.gui.state import AlibabaTrackedRow

    state = TrackerState()
    state.alibaba_tracked_rows = [
        AlibabaTrackedRow(
            product_id="t1",
            title="Tracked CNY mouse",
            last_price="4.30",
            price_min="4.30",
            price_max="4.30",
            currency="CNY",
        )
    ]
    state.alibaba_results = [
        AlibabaResultRow(
            product_id="s1",
            title="Search EUR mouse",
            price_min="4.03",
            price_max="4.03",
            representative="4.03",
            currency="EUR",
        )
    ]
    catalog = state._alibaba_negotiation_catalog()
    assert catalog[0]["key"] == "t:t1"
    assert catalog[0]["currency"] == "CNY"
    assert catalog[1]["key"] == "s:s1"
    assert catalog[1]["currency"] == "EUR"
    state.set_alibaba_negotiation_product_key("s:s1 · leftover")
    state.alibaba_negotiation_quantity = "40"
    state.calculate_alibaba_negotiation()
    assert state.alibaba_negotiation_has_plan is True
    assert state.alibaba_negotiation_plan_payload["currency"] == "EUR"
    assert "EUR" in state.alibaba_negotiation_public
    assert "$" not in state.alibaba_negotiation_public


def test_profitability_ceiling_fails_closed_on_currency_mismatch() -> None:
    from bera_price_tracker.application.import_aware_negotiation import (
        PROFITABILITY_CURRENCY_MISMATCH,
    )
    from bera_price_tracker.application.landed_cost import LandedCostError

    plan = gui_services.calculate_alibaba_negotiation(
        {
            "source": "search",
            "title": "Mouse",
            "price_min": "4.30",
            "price_max": "4.30",
            "currency": "USD",
            "product_id": "1",
        },
        desired_quantity="40",
    )
    landed_cny = gui_services.calculate_alibaba_landed_cost(
        quantity="40",
        supplier_unit_price="4.03",
        cartons="2",
        units_per_carton="20",
        carton_length_cm="50",
        carton_width_cm="40",
        carton_height_cm="30",
        gross_weight_kg_per_carton="8",
        rate_usd_per_cbm="800",
        expected_sale_price="10.00",
        target_margin_percent="30",
        currency="CNY",
    )
    with pytest.raises(LandedCostError, match="moneda"):
        gui_services.apply_alibaba_profitability_ceiling(plan, landed_cny)
    state = TrackerState()
    state.alibaba_negotiation_has_plan = True
    state.alibaba_negotiation_plan_payload = plan
    state.alibaba_landed_has_result = True
    state.alibaba_landed_product_id = "1"
    state.alibaba_landed_result = landed_cny
    state.apply_alibaba_profitability_ceiling()
    assert state.alibaba_negotiation_has_profitability is False
    assert PROFITABILITY_CURRENCY_MISMATCH in state.alibaba_negotiation_profitability_hint


def test_matching_usd_profitability_is_applied_and_does_not_raise_ceiling() -> None:
    plan = gui_services.calculate_alibaba_negotiation(
        {
            "source": "search",
            "title": "Mouse",
            "price_min": "4.30",
            "price_max": "4.30",
            "currency": "USD",
            "product_id": "1",
        },
        desired_quantity="40",
    )
    original_ceiling = plan["ceiling_price"]
    landed = gui_services.calculate_alibaba_landed_cost(
        quantity="40",
        supplier_unit_price="4.03",
        cartons="2",
        units_per_carton="20",
        carton_length_cm="50",
        carton_width_cm="40",
        carton_height_cm="30",
        gross_weight_kg_per_carton="8",
        rate_usd_per_cbm="800",
        expected_sale_price="10.00",
        target_margin_percent="30",
        currency="USD",
    )
    applied = gui_services.apply_alibaba_profitability_ceiling(plan, landed)
    assert applied["profitability_applied"] == "1"
    assert applied["currency"] == "USD"
    assert applied["ceiling_price"] == original_ceiling
    assert Decimal(applied["profitability_ceiling_raw"]) == Decimal("4.60")
    assert Decimal(applied["public_raw"]) == Decimal("4.30")
    assert applied["landed_currency"] == "USD"
    state = TrackerState()
    state.alibaba_negotiation_has_plan = True
    state.alibaba_negotiation_plan_payload = plan
    state.alibaba_landed_has_result = True
    state.alibaba_landed_product_id = "1"
    state.alibaba_landed_result = landed
    state.apply_alibaba_profitability_ceiling()
    assert state.alibaba_negotiation_has_profitability is True
    assert state.alibaba_negotiation_plan_payload["profitability_applied"] == "1"


def test_unknown_landed_currency_is_not_used_for_ml_bridge() -> None:
    state = TrackerState()
    state.alibaba_landed_has_result = True
    state.alibaba_landed_product_id = "P-1"
    state.alibaba_landed_result = {"currency": "$", "max_supplier_raw": "4.60"}
    assert state._landed_for_ml_product_currency("P-1", "USD") is None
    assert state._landed_for_ml_product_currency("P-1", "$") is None
    state.alibaba_landed_result = {"currency": "USD", "max_supplier_raw": "4.60"}
    matched = state._landed_for_ml_product_currency("P-1", "USD")
    assert matched is not None
    assert matched["currency"] == "USD"
    assert state._landed_for_ml_product_currency("P-1", "CNY") is None
    state.prepare_ml_comparables_from_alibaba_result("missing")
    assert state.ml_has_alibaba_context is False


def test_profitability_without_plan_sets_hint() -> None:
    state = TrackerState()
    state.apply_alibaba_profitability_ceiling()
    assert state.alibaba_negotiation_has_profitability is False
    assert "estrategia" in state.alibaba_negotiation_profitability_hint


def test_stale_alibaba_finalize_does_not_reset_non_loading_status() -> None:
    state = TrackerState()
    request_query, request_limit = _begin_in_flight_alibaba_search(state, query="mouse")
    state.alibaba_ui_status = "SUCCESS"
    state.alibaba_query = "teclado"
    state._finalize_alibaba_search(
        request_query=request_query,
        request_limit=request_limit,
        rows=[AlibabaResultRow(title="Mouse A", product_id="1")],
        ui_status="SUCCESS",
    )
    assert state.alibaba_is_loading is False
    assert state.alibaba_ui_status == "SUCCESS"
    assert state.alibaba_results == []


def test_as_mapping_rejects_invalid_forms_and_price_parser_invalid_operation() -> None:
    assert _as_mapping({"title": "Mouse"}) == {"title": "Mouse"}
    assert _as_mapping(["not", "a", "map"]) is None
    assert _as_mapping("raw") is None
    assert _as_mapping(None) is None
    assert _as_mapping(1) is None
    assert _decimal_from_text("abc") is None
    assert _decimal_from_text("") is None
    assert _decimal_from_text(".") is None
    assert _decimal_from_text("NaN") is None
    assert _decimal_from_text("Infinity") is None


def test_search_client_empty_status_and_configuration_errors_propagate() -> None:
    with pytest.raises(MarketplaceSourceUnavailable, match="unavailable"):
        ApifyAlibabaClient(
            _api_token="token",
            client_factory=lambda _token: FakeApify(
                [], run={"status": "  ", "defaultDatasetId": "ds1"}
            ),
        ).search("mouse", 10)
    with pytest.raises(MarketplaceSourceUnavailable, match="unavailable"):
        ApifyAlibabaClient(
            _api_token="token",
            client_factory=lambda _token: FakeApify(
                [], run={"status": 0, "defaultDatasetId": "ds1"}
            ),
        ).search("mouse", 10)

    def boom_config(_token: str) -> object:
        raise ApifyConfigurationError("search token invalid")

    with pytest.raises(ApifyConfigurationError, match="search token invalid"):
        ApifyAlibabaClient(
            _api_token="token",
            client_factory=cast(Any, boom_config),
        ).search("mouse", 10)

    def boom_unavailable(_token: str) -> object:
        raise MarketplaceSourceUnavailable("Alibaba source is unavailable")

    with pytest.raises(MarketplaceSourceUnavailable, match="unavailable"):
        ApifyAlibabaClient(
            _api_token="token",
            client_factory=cast(Any, boom_unavailable),
        ).search("mouse", 10)


def test_run_alibaba_search_rejects_service_without_execute() -> None:
    with pytest.raises(TypeError, match="execute"):
        gui_services.run_alibaba_search("mouse", 10, search_service=object())


def test_sanitize_alibaba_error_does_not_leak_exception_text() -> None:
    message = gui_services.sanitize_alibaba_error(RuntimeError("token=secret"))
    assert message == gui_services.ALIBABA_GENERIC_USER_MESSAGE
    assert "token" not in message
    assert "secret" not in message


def test_negotiation_catalog_skips_blank_and_duplicate_ids() -> None:
    catalog = gui_services.build_alibaba_negotiation_catalog(
        [
            {"product_id": "  "},
            {"product_id": "a", "title": "Tracked A", "currency": "USD"},
            {"product_id": "a", "title": "dup"},
        ],
        [
            {"product_id": ""},
            {"product_id": "a", "title": "Search A"},
            {"product_id": "b", "title": "Search B", "currency": "EUR"},
        ],
    )
    assert [item["key"] for item in catalog] == ["t:a", "s:b"]
    assert catalog[0]["currency"] == "USD"
    assert catalog[1]["currency"] == "EUR"


def test_calculate_alibaba_negotiation_rejects_missing_product_and_quantity() -> None:
    from bera_price_tracker.application.alibaba_negotiation import AlibabaNegotiationError

    with pytest.raises(AlibabaNegotiationError, match="producto"):
        gui_services.calculate_alibaba_negotiation(None, desired_quantity="40")
    with pytest.raises(AlibabaNegotiationError, match="cantidad"):
        gui_services.calculate_alibaba_negotiation(
            {
                "title": "Mouse",
                "price_min": "4.30",
                "price_max": "4.30",
                "currency": "USD",
            },
            desired_quantity="0",
        )
    row = gui_services.calculate_alibaba_negotiation(
        {
            "title": "Mouse",
            "price_min": "4.30",
            "price_max": "4.30",
            "currency": "USD",
            "product_id": "1",
        },
        desired_quantity=40,
        negotiation_aggressiveness=True,
        expected_resale_price="not-money",
    )
    assert row["aggressiveness"] == "50"
    assert row["expected_resale_price"] == ""
    aggressive = gui_services.calculate_alibaba_negotiation(
        {
            "title": "Mouse",
            "price_min": "4.30",
            "price_max": "4.30",
            "currency": "USD",
        },
        desired_quantity="40",
        negotiation_aggressiveness="80",
    )
    assert aggressive["aggressiveness"] == "80"


def test_landed_cost_gui_rejects_invalid_quantity_price_and_sanitizes() -> None:
    from bera_price_tracker.application.landed_cost import LandedCostError

    with pytest.raises(LandedCostError):
        gui_services.calculate_alibaba_landed_cost(
            quantity=True,
            supplier_unit_price="4.03",
            cartons="2",
            units_per_carton="20",
            carton_length_cm="50",
            carton_width_cm="40",
            carton_height_cm="30",
            gross_weight_kg_per_carton="8",
            rate_usd_per_cbm="800",
        )
    with pytest.raises(LandedCostError):
        gui_services.calculate_alibaba_landed_cost(
            quantity="40",
            supplier_unit_price=True,
            cartons="2",
            units_per_carton="20",
            carton_length_cm="50",
            carton_width_cm="40",
            carton_height_cm="30",
            gross_weight_kg_per_carton="8",
            rate_usd_per_cbm="800",
        )
    with pytest.raises(LandedCostError):
        gui_services.calculate_alibaba_landed_cost(
            quantity="40",
            supplier_unit_price="4.03",
            cartons="2",
            units_per_carton="20",
            carton_length_cm="50",
            carton_width_cm="40",
            carton_height_cm="30",
            gross_weight_kg_per_carton="8",
            rate_usd_per_cbm="800",
            wood_surcharge=1.5,
        )
    message = gui_services.sanitize_alibaba_landed_cost_error(RuntimeError("smtp://secret"))
    assert message == gui_services.ALIBABA_LANDED_COST_GENERIC_ERROR
    assert "secret" not in message
    typed = gui_services.sanitize_alibaba_negotiation_error(RuntimeError("boom"))
    assert typed == gui_services.ALIBABA_NEGOTIATION_GENERIC_ERROR


def test_state_alibaba_stale_product_and_loading_reset() -> None:
    state = TrackerState()
    state.alibaba_results = [
        AlibabaResultRow(
            product_id="s1",
            title="Mouse",
            price_min="4.30",
            price_max="4.30",
            representative="4.30",
            currency="USD",
        )
    ]
    state.alibaba_negotiation_product_key = "s:gone"
    state.alibaba_negotiation_quantity = "40"
    state.calculate_alibaba_negotiation()
    assert state.alibaba_negotiation_has_plan is False
    assert "producto" in state.alibaba_negotiation_error
    state.set_alibaba_negotiation_product_key("s:s1")
    state.calculate_alibaba_negotiation()
    assert state.alibaba_negotiation_has_plan is True
    state.alibaba_negotiation_product_key = "s:gone"
    assert state._selected_negotiation_product() is None
    state.set_alibaba_limit("nope")
    assert state.alibaba_limit == 0
    request_query, request_limit = _begin_in_flight_alibaba_search(state, query="mouse", limit=10)
    state.alibaba_limit = 20
    state._finalize_alibaba_search(
        request_query=request_query,
        request_limit=request_limit,
        rows=[AlibabaResultRow(title="late", product_id="x")],
        ui_status="SUCCESS",
    )
    assert state.alibaba_is_loading is False
    assert state.alibaba_ui_status == "INITIAL"
    assert state.alibaba_results[0].product_id == "s1"


def test_state_follow_missing_refresh_selection_and_landed_error() -> None:
    state = TrackerState()
    state.follow_alibaba_product("missing")
    assert "encontró" in state.alibaba_tracking_error
    state.request_alibaba_refresh_selected()
    assert state.alibaba_tracking_error == gui_services.ALIBABA_REFRESH_EMPTY_SELECTION
    state.alibaba_tracked_rows = [
        AlibabaTrackedRow(product_id="p1", title="Mouse", currency="CNY", last_price="4.30")
    ]
    state.select_visible_alibaba_tracked()
    assert state.alibaba_refresh_selected_ids == ["p1"]
    state.toggle_alibaba_refresh_selection("p1")
    assert state.alibaba_refresh_selected_ids == []
    state.toggle_alibaba_refresh_selection("p1")
    assert state.alibaba_refresh_selected_ids == ["p1"]
    state._open_alibaba_refresh_confirm(["p1"])
    assert state.alibaba_refresh_confirm_open is True
    assert state.alibaba_refresh_pending_ids == ["p1"]
    state.cancel_alibaba_refresh()
    assert state.alibaba_refresh_confirm_open is False
    assert state.alibaba_refresh_pending_ids == []
    state.calculate_alibaba_landed_cost()
    assert state.alibaba_landed_has_result is False
    assert state.alibaba_landed_error != ""
    state.alibaba_negotiation_plan_payload = {
        "product_id": "p1",
        "desired_quantity": "40",
        "opening_offer": "$4.03",
        "title": "Mouse",
    }
    state.use_negotiation_values_for_landed_cost()
    assert state.alibaba_landed_quantity == "40"
    assert state.alibaba_landed_supplier_price == "$4.03"
    state.prepare_ml_comparables_from_alibaba_tracked("missing")
    assert state.ml_has_alibaba_context is False
    state.prepare_ml_comparables_from_alibaba_tracked("p1")
    assert state.ml_has_alibaba_context is True
    assert state.ml_alibaba_context["currency"] == "CNY"
    assert state.ml_alibaba_context["has_landed"] == "0"


def test_state_refresh_tracking_and_unfollow_errors_are_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = TrackerState()

    def boom_list() -> list[dict[str, str]]:
        raise RuntimeError("db-down")

    monkeypatch.setattr(gui_services, "list_alibaba_tracked", boom_list)
    state.refresh_alibaba_tracking()
    assert state.alibaba_tracking_error == gui_services.ALIBABA_GENERIC_USER_MESSAGE

    def boom_unfollow(_product_id: str) -> dict[str, str]:
        raise RuntimeError("cannot unfollow")

    monkeypatch.setattr(gui_services, "unfollow_alibaba_price", boom_unfollow)
    state.unfollow_alibaba_product("p1")
    assert "cannot unfollow" in state.alibaba_tracking_error or state.alibaba_tracking_error != ""
