"""Offline Alibaba Decimal context and statistics boundary tests."""

from __future__ import annotations

from decimal import MAX_PREC, Context, Decimal
from types import SimpleNamespace

from bera_price_tracker.application.alibaba_score import score_alibaba_listings
from bera_price_tracker.application.alibaba_statistics import (
    ALIBABA_DECIMAL_WORK_PRECISION_CAP,
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
from bera_price_tracker.gui.services import alibaba_product_to_row, run_alibaba_search
from bera_price_tracker.infrastructure.providers.alibaba import map_alibaba_item

_WORK_CAP = ALIBABA_DECIMAL_WORK_PRECISION_CAP
_OVER_EXPONENT = _WORK_CAP - 2
_AT_CAP_EXPONENT = _WORK_CAP - 3
_BELOW_CAP_EXPONENT = _WORK_CAP - 4


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


def test_compact_exponent_above_work_cap_is_unavailable_without_huge_work() -> None:
    compact = Decimal("1E+10001")
    required = max(50, compact.adjusted() + 3)
    assert required == 10004
    assert _bounded_precision(required) is None
    assert _quantize_cents(compact) is None
    product = map_alibaba_item({"title": "huge", "price": "1e10001", "currency": "USD"})
    assert product is not None
    assert product.price_display == "1e10001"
    assert alibaba_price_bounds(product) is None
    assert alibaba_representative_price(product) is None
    sibling = map_alibaba_item({"title": "ok", "price": "$4.00", "currency": "USD"})
    assert sibling is not None
    payload = run_alibaba_search(
        "mouse",
        10,
        search_service=SearchAlibabaProducts(FakeAlibabaProvider([product, sibling])),
    )
    assert payload["ui_status"] == "SUCCESS"
    assert [row["title"] for row in payload["results"]] == ["huge", "ok"]
    stats = calculate_alibaba_price_statistics([product, sibling])
    assert stats.priced_products == 1
    assert stats.minimum == Decimal("4.00")
    scores = score_alibaba_listings([product, sibling])
    assert scores[0].price_score == 0
    assert scores[1].price_score >= 0
    row = alibaba_product_to_row(product)
    assert isinstance(row["price"], str)


def test_bounded_precision_uses_technical_work_cap() -> None:
    assert _bounded_precision(1) == 1
    assert _bounded_precision(_WORK_CAP) == _WORK_CAP
    assert _bounded_precision(_WORK_CAP + 1) is None
    assert _bounded_precision(MAX_PREC) is None
    assert _bounded_precision(0) is None
    at_cap = _decimal_context(_WORK_CAP)
    assert at_cap is not None
    assert at_cap.prec == _WORK_CAP
    assert _decimal_context(_WORK_CAP + 1) is None
    assert _decimal_context(MAX_PREC) is None


def test_quantize_cents_survives_documented_extreme_decimals() -> None:
    for value in (
        Decimal("1E+100"),
        Decimal("1E+500"),
        Decimal("1E-20"),
        Decimal("4.03"),
    ):
        quantized = _quantize_cents(value)
        assert quantized is not None
        listing = format_alibaba_listing_price(value, value, "USD")
        assert listing
        assert format_alibaba_money(value) != ""


def test_quantize_cents_fail_closes_above_work_cap() -> None:
    below = _huge(_BELOW_CAP_EXPONENT)
    at_cap = _huge(_AT_CAP_EXPONENT)
    over = _huge(_OVER_EXPONENT)
    assert max(50, below.adjusted() + 3) == _WORK_CAP - 1
    assert max(50, at_cap.adjusted() + 3) == _WORK_CAP
    assert max(50, over.adjusted() + 3) == _WORK_CAP + 1
    assert _quantize_cents(below) is not None
    assert _quantize_cents(at_cap) is not None
    assert _quantize_cents(over) is None
    assert format_alibaba_listing_price(over, over, "USD") == ""
    assert format_alibaba_money(over) == UNAVAILABLE_DISPLAY


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
        assert context is None or context.prec <= _WORK_CAP


def test_textual_near_max_exponent_does_not_crash_rows() -> None:
    for raw in ("1e100", "1e500", f"1e{_OVER_EXPONENT}"):
        product = map_alibaba_item({"title": "Mouse", "price": raw, "currency": "USD"})
        assert product is not None
        row = alibaba_product_to_row(product)
        assert isinstance(row["price"], str)
        payload = run_alibaba_search(
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
        payload = run_alibaba_search(
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
            ok_mins = [item.min_price for item in ok_products if item.min_price is not None]
            ok_maxes = [item.max_price for item in ok_products if item.max_price is not None]
            assert ok_mins
            assert ok_maxes
            assert stats.priced_products == len(ok_products)
            assert stats.minimum == min(ok_mins)
            assert stats.maximum == max(ok_maxes)
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


def test_group_threatening_at_cap_price_does_not_erase_sibling_statistics() -> None:
    extreme_value = _huge(_AT_CAP_EXPONENT)
    assert _quantize_cents(Decimal("0.01")) is not None
    assert _quantize_cents(extreme_value) is not None
    assert _calculation_context([Decimal("0.01"), extreme_value]) is None

    low = _usd_product("ok-low", Decimal("0.01"))
    high = _usd_product("ok-high", Decimal("0.03"))
    extreme = _usd_product("extreme", extreme_value)
    for products in (
        [low, extreme],
        [extreme, low],
        [low, extreme, low],
        [low, extreme, high],
    ):
        payload = run_alibaba_search(
            "mouse",
            10,
            search_service=SearchAlibabaProducts(FakeAlibabaProvider(products)),
        )
        assert payload["ui_status"] == "SUCCESS"
        assert [row["title"] for row in payload["results"]] == [item.title for item in products]
        stats = calculate_alibaba_price_statistics(products)
        ok_products = [item for item in products if item.title.startswith("ok")]
        ok_mins = [item.min_price for item in ok_products if item.min_price is not None]
        assert stats.priced_products == len(ok_products)
        assert stats.minimum == min(ok_mins)
        assert stats.maximum == max(ok_mins)
        assert stats.average is not None
        assert stats.median is not None
        scores = score_alibaba_listings(products)
        for index, item in enumerate(products):
            if item.title.startswith("ok"):
                assert payload["results"][index]["price"]
                assert scores[index].price_score >= 0
            else:
                assert scores[index].price_score == 0


def test_unrepresentable_max_bound_does_not_collapse_to_min_only() -> None:
    product = SimpleNamespace(
        min_price=Decimal("0.01"),
        max_price=_huge(_AT_CAP_EXPONENT),
        currency="USD",
    )
    assert _quantize_cents(Decimal("0.01")) is not None
    assert alibaba_price_bounds(product) is None
    assert alibaba_representative_price(product) is None
    assert format_alibaba_listing_price(product.min_price, product.max_price, "USD") == ""


def test_negative_exponent_outside_context_range_is_unavailable() -> None:
    underflow = Decimal("1E-100000000")
    assert _quantize_cents(underflow) is None
    assert format_alibaba_listing_price(underflow, underflow, "USD") == ""
    assert format_alibaba_money(underflow) == UNAVAILABLE_DISPLAY

    product = map_alibaba_item({"title": "tiny", "price": "1e-100000000", "currency": "USD"})
    sibling = map_alibaba_item({"title": "ok", "price": "$0.01", "currency": "USD"})
    assert product is not None
    assert sibling is not None
    assert product.price_display == "1e-100000000"
    assert alibaba_price_bounds(product) is None
    assert alibaba_representative_price(product) is None
    row = alibaba_product_to_row(product)
    assert row["price"] == ""
    assert "$0.00" not in row["price"]

    payload = run_alibaba_search(
        "mouse",
        10,
        search_service=SearchAlibabaProducts(FakeAlibabaProvider([product, sibling])),
    )
    assert payload["ui_status"] == "SUCCESS"
    assert [row["title"] for row in payload["results"]] == ["tiny", "ok"]
    assert payload["results"][0]["price"] == ""
    assert payload["results"][1]["price"]
    stats = calculate_alibaba_price_statistics([product, sibling])
    assert stats.priced_products == 1
    assert stats.minimum == Decimal("0.01")
    assert stats.average == Decimal("0.01")
    scores = score_alibaba_listings([product, sibling])
    assert scores[0].price_score == 0
    assert scores[0].price_clarity_score == 0
    assert scores[1].price_score >= 0

    emin = Context().Emin
    at_floor = Decimal(f"1E{emin}")
    below_floor = Decimal(f"1E{emin - 1}")
    assert _quantize_cents(at_floor) is not None
    assert _quantize_cents(below_floor) is None
    for raw, expected_usable in (
        ("0.01", True),
        ("0.001", True),
        ("1", True),
        ("1e-20", True),
    ):
        mapped = map_alibaba_item({"title": raw, "price": raw, "currency": "USD"})
        assert mapped is not None
        bounds = alibaba_price_bounds(mapped)
        assert (bounds is not None) is expected_usable
        if expected_usable:
            listing = format_alibaba_listing_price(mapped.min_price, mapped.max_price, "USD")
            assert listing
            if raw == "1e-20":
                assert listing == "$0.00"
