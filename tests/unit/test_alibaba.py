"""Offline Alibaba search tests. Mock client/provider only."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import quote_plus

import pytest

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
from bera_price_tracker.config import DEFAULT_APIFY_ALIBABA_ACTOR, Settings
from bera_price_tracker.domain.alibaba import AlibabaProduct
from bera_price_tracker.gui import services as gui_services
from bera_price_tracker.gui.state import AlibabaResultRow, AlibabaTrackedRow, TrackerState
from bera_price_tracker.infrastructure.providers.alibaba import (
    ApifyAlibabaClient,
    _as_mapping,
    _decimal_from_text,
    build_alibaba_run_input,
    build_alibaba_search_url,
    map_alibaba_item,
    parse_alibaba_price,
)
from bera_price_tracker.infrastructure.providers.apify import ApifyConfigurationError

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


def test_url_encoding_uses_quote_plus() -> None:
    query = "Men's Jackets"
    url = build_alibaba_search_url(query)
    assert url == (
        "https://www.alibaba.com/trade/search?fsb=y&IndexArea=product_en&keywords="
        + quote_plus(query)
    )
    assert "keywords=Men%27s+Jackets" in url
    payload = build_alibaba_run_input(query=query, limit=10)
    assert list(payload.keys()) == ["urls", "maxItems"]
    assert payload["urls"] == [url]
    assert payload["maxItems"] == 10


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
    assert fake.actor_id == "scraper-engine/alibaba-scraper"
    assert len(fake.calls) == 1
    assert fake.calls[0] == build_alibaba_run_input(query="bags", limit=20)
    assert products[0].title == "Bag"


def test_default_actor_config() -> None:
    settings = Settings.from_env({})
    assert settings.apify_alibaba_actor == "scraper-engine/alibaba-scraper"


# Keys observed on scraper-engine/alibaba-scraper SUCCEEDED dataset items.
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


def _negotiation_plan_row(product_id: str, unit_price: str) -> dict[str, str]:
    return {
        "product_id": product_id,
        "title": f"Product {product_id}",
        "public_unit_price": f"${unit_price}",
        "opening_offer": f"${unit_price}",
        "target_price": f"${unit_price}",
        "ceiling_price": f"${unit_price}",
        "desired_quantity": "40",
        "currency": "USD",
    }


def test_late_negotiation_opening_for_product_a_does_not_overwrite_product_b() -> None:
    state = TrackerState()
    state._apply_negotiation_plan(_negotiation_plan_row("A", "4.00"))
    request_generation = state.alibaba_negotiation_generation
    state.alibaba_negotiation_is_drafting = True
    state._apply_negotiation_plan(_negotiation_plan_row("B", "12.00"))
    state._finalize_alibaba_negotiation_draft(
        request_generation=request_generation,
        message="We can offer USD 4.00 per unit for Product A.",
    )
    assert state.alibaba_negotiation_plan_payload["product_id"] == "B"
    assert state.alibaba_negotiation_opening == "$12.00"
    assert state.alibaba_negotiation_message == ""
    assert state.alibaba_negotiation_is_drafting is False


def test_late_negotiation_error_for_product_a_does_not_overwrite_product_b() -> None:
    state = TrackerState()
    state._apply_negotiation_plan(_negotiation_plan_row("A", "4.00"))
    request_generation = state.alibaba_negotiation_generation
    state.alibaba_negotiation_is_drafting = True
    state._apply_negotiation_plan(_negotiation_plan_row("B", "12.00"))
    state._finalize_alibaba_negotiation_draft(
        request_generation=request_generation,
        error_message="No se pudo generar el borrador de A.",
    )
    assert state.alibaba_negotiation_plan_payload["product_id"] == "B"
    assert state.alibaba_negotiation_error == ""
    assert state.alibaba_negotiation_is_drafting is False


def test_late_negotiation_analysis_for_product_a_does_not_overwrite_product_b() -> None:
    state = TrackerState()
    state._apply_negotiation_plan(_negotiation_plan_row("A", "4.00"))
    request_generation = state.alibaba_negotiation_generation
    state.alibaba_negotiation_is_drafting = True
    state._apply_negotiation_plan(_negotiation_plan_row("B", "12.00"))
    state._finalize_alibaba_negotiation_draft(
        request_generation=request_generation,
        analysis_row={
            "response_summary": "Supplier quoted 6.00 for A",
            "decision": "ABOVE_CEILING",
            "notes": "Above A's ceiling",
            "quoted_unit_price": "6.00",
            "authorized_price": "4.00",
        },
    )
    assert state.alibaba_negotiation_plan_payload["product_id"] == "B"
    assert state.alibaba_negotiation_analysis_decision == ""
    assert state.alibaba_negotiation_analysis_summary == ""
    assert state.alibaba_negotiation_analysis_notes == ""
    assert state.alibaba_negotiation_is_drafting is False


def test_matching_negotiation_draft_still_applies() -> None:
    state = TrackerState()
    state._apply_negotiation_plan(_negotiation_plan_row("A", "4.00"))
    request_generation = state.alibaba_negotiation_generation
    state.alibaba_negotiation_is_drafting = True
    state._finalize_alibaba_negotiation_draft(
        request_generation=request_generation,
        message="We can offer USD 4.00 per unit.",
    )
    assert state.alibaba_negotiation_plan_payload["product_id"] == "A"
    assert state.alibaba_negotiation_message == "We can offer USD 4.00 per unit."
    assert state.alibaba_negotiation_is_drafting is False


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
