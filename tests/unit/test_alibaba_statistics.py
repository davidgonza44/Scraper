"""Offline Alibaba Decimal context and statistics boundary tests."""

from __future__ import annotations

from decimal import MAX_PREC, Decimal
from types import SimpleNamespace

from bera_price_tracker.application.alibaba_score import score_alibaba_listings
from bera_price_tracker.application.alibaba_statistics import (
    UNAVAILABLE_DISPLAY,
    _bounded_precision,
    _calculation_context,
    _decimal_context,
    _quantize_cents,
    alibaba_price_bounds,
    alibaba_representative_price,
    calculate_alibaba_price_statistics,
    format_alibaba_listing_price,
    format_alibaba_money,
)
from bera_price_tracker.application.services import SearchAlibabaProducts
from bera_price_tracker.domain.alibaba import AlibabaProduct
from bera_price_tracker.gui import services as gui_services
from bera_price_tracker.infrastructure.providers.alibaba import map_alibaba_item

_OVER_EXPONENT = MAX_PREC - 2
_AT_MAX_EXPONENT = MAX_PREC - 3


def _huge(exponent: int) -> Decimal:
    return Decimal(f"1E+{exponent}")


class FakeAlibabaProvider:
    def __init__(self, products: list[AlibabaProduct]) -> None:
        self.products = products

    def search(self, query: str, limit: int) -> list[AlibabaProduct]:
        return list(self.products)


def _usd_product(title: str, min_price: Decimal) -> AlibabaProduct:
    return AlibabaProduct(
        title=title,
        min_price=min_price,
        max_price=min_price,
        currency="USD",
    )


def test_bounded_precision_uses_decimal_max_prec() -> None:
    assert _bounded_precision(1) == 1
    assert _bounded_precision(MAX_PREC) == MAX_PREC
    assert _bounded_precision(MAX_PREC + 1) is None
    assert _bounded_precision(0) is None
    at_max = _decimal_context(MAX_PREC)
    assert at_max is not None
    assert at_max.prec == MAX_PREC
    assert _decimal_context(MAX_PREC + 1) is None


def test_quantize_cents_survives_documented_extreme_decimals() -> None:
    for value in (
        Decimal("1E+100"),
        Decimal("1E+500"),
        Decimal("1E+999999"),
        Decimal("1E-20"),
        Decimal("4.03"),
    ):
        quantized = _quantize_cents(value)
        assert quantized is not None
        listing = format_alibaba_listing_price(value, value, "USD")
        assert listing
        assert format_alibaba_money(value) != ""


def test_quantize_cents_fail_closes_above_max_prec() -> None:
    over = _huge(_OVER_EXPONENT)
    assert max(50, over.adjusted() + 3) == MAX_PREC + 1
    assert _quantize_cents(over) is None
    assert format_alibaba_listing_price(over, over, "USD") == ""
    assert format_alibaba_money(over) == UNAVAILABLE_DISPLAY
    at_limit = _huge(_AT_MAX_EXPONENT)
    assert max(50, at_limit.adjusted() + 3) == MAX_PREC


def test_calculation_context_does_not_raise_for_unrepresentable_precision() -> None:
    over = _huge(_OVER_EXPONENT)
    normal = Decimal("4.00")
    for group in (
        [over],
        [normal, over],
        [over, normal],
        [over, over],
        [normal, over, normal],
    ):
        context = _calculation_context(group)
        assert context is None or context.prec <= MAX_PREC


def test_textual_near_max_exponent_does_not_crash_rows() -> None:
    for raw in ("1e100", "1e500", f"1e{_OVER_EXPONENT}"):
        product = map_alibaba_item({"title": "Mouse", "price": raw, "currency": "USD"})
        assert product is not None
        row = gui_services.alibaba_product_to_row(product)
        assert isinstance(row["price"], str)
        payload = gui_services.run_alibaba_search(
            "mouse",
            10,
            search_service=SearchAlibabaProducts(FakeAlibabaProvider([product])),
        )
        assert payload["ui_status"] == "SUCCESS"


def test_unrepresentable_usd_price_does_not_contaminate_or_abort_siblings() -> None:
    over = _huge(_OVER_EXPONENT)
    extreme = _usd_product("extreme", over)
    low = map_alibaba_item({"title": "ok-low", "price": "$4.00", "currency": "USD"})
    high = map_alibaba_item({"title": "ok-high", "price": "$6.00", "currency": "USD"})
    assert low is not None
    assert high is not None
    assert alibaba_price_bounds(extreme) is None
    assert alibaba_representative_price(extreme) is None

    for products in (
        [low, extreme],
        [extreme, low],
        [low, extreme, high],
        [extreme, _usd_product("extreme-2", over)],
    ):
        payload = gui_services.run_alibaba_search(
            "mouse",
            10,
            search_service=SearchAlibabaProducts(FakeAlibabaProvider(products)),
        )
        assert payload["ui_status"] == "SUCCESS"
        assert [row["title"] for row in payload["results"]] == [item.title for item in products]
        stats = calculate_alibaba_price_statistics(products)
        scores = score_alibaba_listings(products)
        assert len(scores) == len(products)
        if any(item.title.startswith("ok") for item in products):
            ok_products = [item for item in products if item.title.startswith("ok")]
            assert stats.priced_products == len(ok_products)
            assert stats.minimum == min(item.min_price for item in ok_products)
            assert stats.maximum == max(item.max_price for item in ok_products)
            for index, item in enumerate(products):
                if item.title.startswith("ok"):
                    assert payload["results"][index]["price"]
                    assert scores[index].price_score >= 0
        else:
            assert stats.priced_products == 0
            assert stats.minimum is None
        for index, item in enumerate(products):
            if item.title.startswith("extreme"):
                assert scores[index].price_score == 0


def test_namespace_unrepresentable_price_is_excluded_from_bounds() -> None:
    over = _huge(_OVER_EXPONENT)
    product = SimpleNamespace(min_price=over, max_price=over, currency="USD")
    assert alibaba_price_bounds(product) is None
    assert alibaba_representative_price(product) is None
    stats = calculate_alibaba_price_statistics([product])
    assert stats.priced_products == 0
