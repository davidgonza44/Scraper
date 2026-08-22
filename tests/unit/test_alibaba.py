"""Offline Alibaba search tests. Mock client/provider only."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote_plus

import pytest

from bera_price_tracker.application.alibaba_statistics import (
    UNAVAILABLE_DISPLAY,
    alibaba_percentile,
    alibaba_representative_price,
    calculate_alibaba_price_statistics,
    format_alibaba_money,
    format_alibaba_typical_range,
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
from bera_price_tracker.gui.state import AlibabaResultRow, TrackerState
from bera_price_tracker.infrastructure.providers.alibaba import (
    ApifyAlibabaClient,
    build_alibaba_run_input,
    build_alibaba_search_url,
    map_alibaba_item,
    parse_alibaba_price,
)

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
    def __init__(self, items: list[object]) -> None:
        self.items = items

    def list_items(self, *, limit: int) -> _FakePage:
        return _FakePage(self.items[:limit])


class _FakeActor:
    def __init__(self, owner: FakeApify) -> None:
        self.owner = owner

    def call(self, *, run_input: dict[str, object]) -> dict[str, object]:
        self.owner.calls.append(run_input)
        return {"status": "SUCCEEDED", "defaultDatasetId": "ds1"}


class FakeApify:
    def __init__(self, items: list[object]) -> None:
        self.items = items
        self.calls: list[dict[str, object]] = []

    def actor(self, actor_id: str) -> _FakeActor:
        self.actor_id = actor_id
        return _FakeActor(self)

    def dataset(self, dataset_id: str) -> _FakeDataset:
        self.dataset_id = dataset_id
        return _FakeDataset(self.items)


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
    assert currency == "USD"


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
    assert product.currency == "USD"
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
    assert rows[0].price == "$1.38"
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
        map_alibaba_item({"title": "A", "price": "$1"}),
        map_alibaba_item({"title": "B", "price": "$1.30-1.60"}),
        map_alibaba_item({"title": "C", "price": "$13.45"}),
    ]
    mapped = [product for product in products if product is not None]
    stats = calculate_alibaba_price_statistics(mapped)
    assert stats.minimum == Decimal("1")
    assert format_alibaba_money(stats.minimum) == "$1.00"


def test_maximum_uses_price_max() -> None:
    products = [
        map_alibaba_item({"title": "A", "price": "$4"}),
        map_alibaba_item({"title": "B", "price": "$159-699"}),
    ]
    mapped = [product for product in products if product is not None]
    stats = calculate_alibaba_price_statistics(mapped)
    assert stats.maximum == Decimal("699")
    assert format_alibaba_money(stats.maximum) == "$699.00"


def test_average_is_decimal_of_representatives() -> None:
    products = [
        map_alibaba_item({"title": "A", "price": "$1.00"}),
        map_alibaba_item({"title": "B", "price": "$2.00"}),
        map_alibaba_item({"title": "C", "price": "$3.00"}),
    ]
    mapped = [product for product in products if product is not None]
    stats = calculate_alibaba_price_statistics(mapped)
    assert stats.average == Decimal("2")
    assert isinstance(stats.average, Decimal)
    assert format_alibaba_money(stats.average) == "$2.00"


def test_median_odd_count() -> None:
    products = [
        map_alibaba_item({"title": "A", "price": "$1.00"}),
        map_alibaba_item({"title": "B", "price": "$4.00"}),
        map_alibaba_item({"title": "C", "price": "$13.45"}),
    ]
    mapped = [product for product in products if product is not None]
    stats = calculate_alibaba_price_statistics(mapped)
    assert stats.median == Decimal("4.00")
    assert format_alibaba_money(stats.median) == "$4.00"


def test_median_even_count() -> None:
    products = [
        map_alibaba_item({"title": "A", "price": "$1.00"}),
        map_alibaba_item({"title": "B", "price": "$2.00"}),
        map_alibaba_item({"title": "C", "price": "$3.00"}),
        map_alibaba_item({"title": "D", "price": "$4.00"}),
    ]
    mapped = [product for product in products if product is not None]
    stats = calculate_alibaba_price_statistics(mapped)
    assert stats.median == Decimal("2.5")
    assert isinstance(stats.median, Decimal)
    assert format_alibaba_money(stats.median) == "$2.50"


def test_missing_price_excluded_from_statistics_but_kept_in_table() -> None:
    products = [
        map_alibaba_item({"title": "Priced", "price": "$4"}),
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
    assert payload["results"][1]["price"] == "Contact supplier"
    assert payload["results"][2]["price"] == "unavailable"
    assert payload["summary"]["resultados"] == "4"
    assert payload["summary"]["con_precio"] == "1 de 4"
    assert payload["summary"]["minimo"] == "$4.00"
    assert payload["summary"]["maximo"] == "$4.00"
    assert payload["summary"]["promedio"] == "$4.00"
    assert payload["summary"]["mediana"] == "$4.00"


def test_range_display_remains_on_row() -> None:
    product = map_alibaba_item({"title": "Range mouse", "price": "$1.30-1.60"})
    assert product is not None
    payload = gui_services.run_alibaba_search(
        "wireless mouse",
        10,
        search_service=SearchAlibabaProducts(FakeAlibabaProvider([product])),
    )
    assert payload["results"][0]["price"] == "$1.30-1.60"
    assert payload["summary"]["promedio"] == "$1.45"
    assert payload["summary"]["mediana"] == "$1.45"


def test_statistics_do_not_mix_currencies() -> None:
    products = [
        map_alibaba_item({"title": "USD cheap", "price": "$4"}),
        map_alibaba_item({"title": "USD mid", "price": "$5"}),
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
    assert payload["results"][2]["price"] == "EUR 100"
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
    product = map_alibaba_item({"title": "Mouse", "price": "$4", "moq": "Min. order: 1000 pieces"})
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
    product = map_alibaba_item({"title": title, "price": price})
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
    assert payload["results"][1]["price"] == "Contact supplier"
    assert payload["results"][2]["price"] == "EUR 100"


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
