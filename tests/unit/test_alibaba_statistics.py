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
    _canonical_exponent,
    _decimal_context,
    _eligible_for_group_statistics,
    _quantize_cents,
    alibaba_price_bounds,
    alibaba_representative_price,
    calculate_alibaba_price_statistics,
    format_alibaba_currency,
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
    over = _huge(_OVER_EXPONENT)
    underflow = Decimal("1E-100000000")
    for raw_max in (over, underflow):
        product = SimpleNamespace(
            min_price=Decimal("0.01"),
            max_price=raw_max,
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


def test_tiny_emin_price_does_not_starve_ordinary_sibling_statistics() -> None:
    emin = Context().Emin
    tiny = Decimal(f"1E{emin}")
    ordinary = (Decimal("1"), Decimal("2"), Decimal("3"))
    assert _quantize_cents(tiny) is not None
    for value in ordinary:
        assert _quantize_cents(value) is not None
    assert _calculation_context([tiny, *ordinary]) is None

    tiny_product = _usd_product("tiny", tiny)
    one = _usd_product("one", Decimal("1"))
    two = _usd_product("two", Decimal("2"))
    three = _usd_product("three", Decimal("3"))
    groups = (
        [tiny_product, one, two, three],
        [one, two, three, tiny_product],
        [three, tiny_product, one, two],
        [one, tiny_product, two, three],
    )
    for products in groups:
        payload = run_alibaba_search(
            "mouse",
            10,
            search_service=SearchAlibabaProducts(FakeAlibabaProvider(products)),
        )
        assert payload["ui_status"] == "SUCCESS"
        assert [row["title"] for row in payload["results"]] == [item.title for item in products]
        stats = calculate_alibaba_price_statistics(products)
        assert stats.priced_products == 3
        assert stats.minimum == Decimal("1")
        assert stats.maximum == Decimal("3")
        assert stats.average == Decimal("2")
        assert stats.median == Decimal("2")
        assert format_alibaba_money(stats.average) != "$0.00"
        assert format_alibaba_money(stats.minimum) == "$1.00"

    near_tiny = Decimal(f"1E{emin + 1}")
    near_group = [
        _usd_product("near", near_tiny),
        one,
        two,
        three,
    ]
    near_stats = calculate_alibaba_price_statistics(near_group)
    assert near_stats.priced_products == 3
    assert near_stats.minimum == Decimal("1")
    assert near_stats.maximum == Decimal("3")

    hundredths = Decimal("1E-100")
    assert _calculation_context([hundredths, *ordinary]) is not None
    hundredths_stats = calculate_alibaba_price_statistics(
        [_usd_product("hundredths", hundredths), one, two, three]
    )
    assert hundredths_stats.priced_products == 4
    assert hundredths_stats.minimum == hundredths
    assert hundredths_stats.maximum == Decimal("3")

    dual_extreme_stats = calculate_alibaba_price_statistics(
        [tiny_product, _usd_product("near", near_tiny), one, two, three]
    )
    assert dual_extreme_stats.priced_products == 3
    assert dual_extreme_stats.minimum == Decimal("1")
    assert dual_extreme_stats.maximum == Decimal("3")


def test_ordinary_small_prices_remain_eligible_with_siblings() -> None:
    products = [
        _usd_product("milli", Decimal("0.001")),
        _usd_product("one", Decimal("1")),
        _usd_product("two", Decimal("2")),
        _usd_product("three", Decimal("3")),
    ]
    assert _calculation_context([item.min_price for item in products if item.min_price]) is not None
    stats = calculate_alibaba_price_statistics(products)
    assert stats.priced_products == 4
    assert stats.minimum == Decimal("0.001")
    assert stats.maximum == Decimal("3")
    payload = run_alibaba_search(
        "mouse",
        10,
        search_service=SearchAlibabaProducts(FakeAlibabaProvider(products)),
    )
    assert [row["title"] for row in payload["results"]] == ["milli", "one", "two", "three"]


def _padded_one() -> Decimal:
    return Decimal("1." + ("0" * 9998))


def _ordinary_usd_cohort(count: int) -> list[AlibabaProduct]:
    return [_usd_product(f"n{index}", Decimal(index)) for index in range(1, count + 1)]


def test_equivalent_coefficient_padding_shares_technical_context() -> None:
    one = Decimal("1")
    one_padded = Decimal("1.000000")
    thousand = Decimal("1000")
    thousand_padded = Decimal("1000.000000")
    thousand_exp = Decimal("1E+3")
    sibling = Decimal("2")
    assert one == one_padded
    assert thousand == thousand_padded == thousand_exp
    assert _canonical_exponent(one) == _canonical_exponent(one_padded) == 0
    assert (
        _canonical_exponent(thousand)
        == _canonical_exponent(thousand_padded)
        == _canonical_exponent(thousand_exp)
        == 3
    )

    one_context = _calculation_context([one, sibling])
    padded_one_context = _calculation_context([one_padded, sibling])
    assert one_context is not None
    assert padded_one_context is not None
    assert one_context.prec == padded_one_context.prec

    thousand_precs: list[int] = []
    for value in (thousand, thousand_padded, thousand_exp):
        context = _calculation_context([value, Decimal("1")])
        assert context is not None
        thousand_precs.append(context.prec)
    assert len(set(thousand_precs)) == 1

    compact = _padded_one()
    assert compact == one
    assert _canonical_exponent(compact) == _canonical_exponent(one) == 0
    compact_context = _calculation_context([compact, one])
    plain_context = _calculation_context([one, one])
    assert compact_context is not None
    assert plain_context is not None
    assert compact_context.prec == plain_context.prec


def test_insignificant_coefficient_padding_does_not_collapse_ordinary_statistics() -> None:
    padded_one = _padded_one()
    assert padded_one == Decimal("1")
    ordinary = _ordinary_usd_cohort(499)
    assert len(ordinary) == 499
    padded = _usd_product("padded", padded_one)
    values = [padded_one, *[item.min_price for item in ordinary if item.min_price is not None]]
    assert len(values) == 500
    assert _calculation_context(values) is not None

    placements = (
        [padded, *ordinary],
        [*ordinary, padded],
        [*ordinary[:249], padded, *ordinary[249:]],
    )
    stats_by_placement: list[tuple[int, Decimal | None, Decimal | None, Decimal | None]] = []
    for products in placements:
        payload = run_alibaba_search(
            "mouse",
            500,
            search_service=SearchAlibabaProducts(FakeAlibabaProvider(products)),
        )
        assert payload["ui_status"] == "SUCCESS"
        assert [row["title"] for row in payload["results"]] == [item.title for item in products]
        stats = calculate_alibaba_price_statistics(products)
        assert stats.priced_products == 500
        assert stats.minimum == Decimal("1")
        assert stats.maximum == Decimal("499")
        assert stats.average is not None
        stats_by_placement.append(
            (stats.priced_products, stats.minimum, stats.maximum, stats.average)
        )
    assert stats_by_placement[0] == stats_by_placement[1] == stats_by_placement[2]


def test_padded_huge_magnitude_still_fails_closed_from_ordinary_siblings() -> None:
    huge = Decimal("1E+9997")
    padded_huge = Decimal("1." + ("0" * 100) + "E+9997")
    assert padded_huge == huge
    assert _canonical_exponent(padded_huge) == _canonical_exponent(huge)
    assert _quantize_cents(huge) is not None
    assert _quantize_cents(padded_huge) is not None
    assert _calculation_context([Decimal("0.01"), padded_huge]) is None
    low = _usd_product("ok-low", Decimal("0.01"))
    high = _usd_product("ok-high", Decimal("0.03"))
    extreme = _usd_product("padded-huge", padded_huge)
    for products in (
        [low, extreme],
        [extreme, low],
        [low, extreme, high],
        [high, extreme, low],
    ):
        stats = calculate_alibaba_price_statistics(products)
        ok_mins = [
            item.min_price for item in products if item.title.startswith("ok") and item.min_price
        ]
        assert stats.priced_products == len(ok_mins)
        assert stats.minimum == min(ok_mins)
        assert stats.maximum == max(ok_mins)


def test_padded_tiny_exponent_still_does_not_starve_ordinary_cluster() -> None:
    emin = Context().Emin
    tiny = Decimal(f"1E{emin}")
    padded_tiny = Decimal("1." + ("0" * 10) + f"E{emin}")
    assert padded_tiny == tiny
    assert _canonical_exponent(padded_tiny) == _canonical_exponent(tiny)
    one = _usd_product("one", Decimal("1"))
    two = _usd_product("two", Decimal("2"))
    three = _usd_product("three", Decimal("3"))
    padded = _usd_product("padded-tiny", padded_tiny)
    for products in (
        [padded, one, two, three],
        [one, two, three, padded],
        [one, padded, two, three],
    ):
        stats = calculate_alibaba_price_statistics(products)
        assert stats.priced_products == 3
        assert stats.minimum == Decimal("1")
        assert stats.maximum == Decimal("3")
        assert stats.average == Decimal("2")


def test_general_currency_formatter_preserves_signed_and_zero_amounts() -> None:
    assert format_alibaba_currency(Decimal("-3.20"), "USD") == "$-3.20"
    assert format_alibaba_currency(Decimal("0"), "USD") == "$0.00"
    assert format_alibaba_currency(Decimal("0.00"), "USD") == "$0.00"
    assert format_alibaba_currency(Decimal("3.20"), "USD") == "$3.20"
    assert format_alibaba_currency(Decimal("-3.20"), "EUR") == "EUR -3.20"
    assert format_alibaba_money(Decimal("-3.20")) == "$-3.20"
    assert format_alibaba_money(Decimal("0")) == "$0.00"
    assert format_alibaba_money(Decimal("3.20")) == "$3.20"
    assert format_alibaba_money(Decimal("-1.50")) == "$-1.50"


def test_listing_prices_remain_strictly_positive() -> None:
    assert format_alibaba_listing_price(Decimal("-3.20"), Decimal("-3.20"), "USD") == ""
    assert format_alibaba_listing_price(Decimal("0"), Decimal("0"), "USD") == ""
    assert format_alibaba_listing_price(Decimal("0.00"), Decimal("0.00"), "USD") == ""
    assert format_alibaba_listing_price(Decimal("-3.20"), Decimal("3.20"), "USD") == ""
    assert format_alibaba_listing_price(Decimal("5.00"), Decimal("3.00"), "USD") == ""
    assert format_alibaba_listing_price(Decimal("3.20"), Decimal("-3.20"), "USD") == ""
    product = SimpleNamespace(
        min_price=Decimal("-3.20"), max_price=Decimal("-3.20"), currency="USD"
    )
    assert alibaba_price_bounds(product) is None
    assert alibaba_representative_price(product) is None
    zero = SimpleNamespace(min_price=Decimal("0"), max_price=Decimal("0"), currency="USD")
    assert alibaba_price_bounds(zero) is None
    nan = SimpleNamespace(min_price=Decimal("NaN"), max_price=Decimal("NaN"), currency="USD")
    assert alibaba_price_bounds(nan) is None
    assert format_alibaba_listing_price(Decimal("NaN"), Decimal("NaN"), "USD") == ""
    assert format_alibaba_listing_price(Decimal("Infinity"), Decimal("Infinity"), "USD") == ""
    assert format_alibaba_listing_price(Decimal("-Infinity"), Decimal("-Infinity"), "USD") == ""


def test_signed_unsafe_extremes_fail_closed_in_general_formatter() -> None:
    over = Decimal("1E+10001")
    negative_over = Decimal("-1E+10001")
    underflow = Decimal("1E-100000000")
    negative_underflow = Decimal("-1E-100000000")
    assert format_alibaba_currency(over, "USD") == UNAVAILABLE_DISPLAY
    assert format_alibaba_currency(negative_over, "USD") == UNAVAILABLE_DISPLAY
    assert format_alibaba_money(over) == UNAVAILABLE_DISPLAY
    assert format_alibaba_money(negative_over) == UNAVAILABLE_DISPLAY
    assert format_alibaba_currency(underflow, "USD") == UNAVAILABLE_DISPLAY
    assert format_alibaba_currency(negative_underflow, "USD") == UNAVAILABLE_DISPLAY
    assert format_alibaba_currency(Decimal("NaN"), "USD") == UNAVAILABLE_DISPLAY
    assert format_alibaba_currency(Decimal("Infinity"), "USD") == UNAVAILABLE_DISPLAY
    assert format_alibaba_currency(Decimal("-Infinity"), "USD") == UNAVAILABLE_DISPLAY
    assert format_alibaba_listing_price(over, over, "USD") == ""
    assert format_alibaba_listing_price(negative_over, negative_over, "USD") == ""
    assert _quantize_cents(over) is None
    assert _quantize_cents(negative_over) is None


def _singleton_placements(
    singleton: AlibabaProduct, crowd: list[AlibabaProduct]
) -> tuple[list[AlibabaProduct], ...]:
    middle = len(crowd) // 2
    return (
        [singleton, *crowd],
        [*crowd, singleton],
        [*crowd[:middle], singleton, *crowd[middle:]],
    )


def _assert_stats_cohort(
    products: list[AlibabaProduct],
    *,
    priced: int,
    minimum: Decimal,
    maximum: Decimal,
) -> None:
    payload = run_alibaba_search(
        "mouse",
        max(len(products), 1),
        search_service=SearchAlibabaProducts(FakeAlibabaProvider(products)),
    )
    assert payload["ui_status"] == "SUCCESS"
    assert [row["title"] for row in payload["results"]] == [item.title for item in products]
    stats = calculate_alibaba_price_statistics(products)
    assert stats.priced_products == priced
    assert stats.minimum == minimum
    assert stats.maximum == maximum
    assert stats.average is not None


def test_majority_extreme_cluster_beats_ordinary_singleton() -> None:
    ordinary = _usd_product("ordinary", Decimal("1"))
    extreme_value = _huge(_AT_CAP_EXPONENT)
    crowd = [_usd_product(f"extreme-{index}", extreme_value) for index in range(499)]
    values = [Decimal("1"), *([extreme_value] * 499)]
    assert _calculation_context([extreme_value] * 499) is not None
    assert _calculation_context(values) is None
    keep = _eligible_for_group_statistics(values)
    assert sum(keep) == 499
    for products in _singleton_placements(ordinary, crowd):
        _assert_stats_cohort(products, priced=499, minimum=extreme_value, maximum=extreme_value)


def test_majority_ordinary_cluster_excludes_group_threatening_extreme() -> None:
    extreme = _usd_product("extreme", _huge(_AT_CAP_EXPONENT))
    crowd = [_usd_product(f"n{index}", Decimal(index)) for index in range(1, 500)]
    for products in _singleton_placements(extreme, crowd):
        _assert_stats_cohort(products, priced=499, minimum=Decimal("1"), maximum=Decimal("499"))


def test_all_extreme_mutually_compatible_values_remain_selected() -> None:
    extreme_value = _huge(_AT_CAP_EXPONENT)
    products = [_usd_product(f"extreme-{index}", extreme_value) for index in range(500)]
    assert _calculation_context([extreme_value] * 500) is not None
    _assert_stats_cohort(products, priced=500, minimum=extreme_value, maximum=extreme_value)


def test_count_width_nine_to_ten_selects_larger_compatible_cluster() -> None:
    tiny = Decimal("1E-9998")
    ordinary = _usd_product("ordinary", Decimal("1"))
    nine = [_usd_product(f"tiny-{index}", tiny) for index in range(9)]
    assert _calculation_context([Decimal("1")] + [tiny] * 8) is not None
    assert _calculation_context([Decimal("1")] + [tiny] * 9) is None
    for products in _singleton_placements(ordinary, nine):
        _assert_stats_cohort(products, priced=9, minimum=tiny, maximum=tiny)


def test_count_width_nine_mixed_span_still_fits_all_nine() -> None:
    tiny = Decimal("1E-9998")
    products = [_usd_product("ordinary", Decimal("1"))] + [
        _usd_product(f"tiny-{index}", tiny) for index in range(8)
    ]
    assert _calculation_context([item.min_price for item in products if item.min_price]) is not None
    _assert_stats_cohort(products, priced=9, minimum=tiny, maximum=Decimal("1"))


def test_count_width_ninety_nine_to_one_hundred_prefers_homogeneous_cluster() -> None:
    extreme_value = _huge(_AT_CAP_EXPONENT)
    ordinary = _usd_product("ordinary", Decimal("1"))
    ninety_nine = [_usd_product(f"extreme-{index}", extreme_value) for index in range(99)]
    assert _calculation_context([Decimal("1")] + [extreme_value] * 98) is not None
    assert _calculation_context([Decimal("1")] + [extreme_value] * 99) is None
    for products in _singleton_placements(ordinary, ninety_nine):
        _assert_stats_cohort(products, priced=99, minimum=extreme_value, maximum=extreme_value)


def test_count_width_ninety_eight_extremes_plus_ordinary_all_fit() -> None:
    extreme_value = _huge(_AT_CAP_EXPONENT)
    products = [_usd_product("ordinary", Decimal("1"))] + [
        _usd_product(f"extreme-{index}", extreme_value) for index in range(98)
    ]
    assert _calculation_context([Decimal("1")] + [extreme_value] * 98) is not None
    _assert_stats_cohort(products, priced=99, minimum=Decimal("1"), maximum=extreme_value)


def test_equal_cardinality_clusters_prefer_ordinary_magnitude() -> None:
    tiny = Decimal(f"1E{Context().Emin}")
    ordinary_crowd = [_usd_product(f"one-{index}", Decimal("1")) for index in range(2)]
    tiny_crowd = [_usd_product(f"tiny-{index}", tiny) for index in range(2)]
    assert _calculation_context([Decimal("1")] * 2) is not None
    assert _calculation_context([tiny] * 2) is not None
    assert _calculation_context([Decimal("1"), Decimal("1"), tiny, tiny]) is None
    placements = (
        ordinary_crowd + tiny_crowd,
        tiny_crowd + ordinary_crowd,
        [ordinary_crowd[0], tiny_crowd[0], ordinary_crowd[1], tiny_crowd[1]],
        [tiny_crowd[0], ordinary_crowd[0], tiny_crowd[1], ordinary_crowd[1]],
    )
    for products in placements:
        _assert_stats_cohort(products, priced=2, minimum=Decimal("1"), maximum=Decimal("1"))


def test_equal_large_clusters_are_not_beaten_by_mixed_digit_width_subset() -> None:
    extreme_value = _huge(_AT_CAP_EXPONENT)
    ones = [_usd_product(f"one-{index}", Decimal("1")) for index in range(100)]
    extremes = [_usd_product(f"extreme-{index}", extreme_value) for index in range(100)]
    assert _calculation_context([Decimal("1")] * 100) is not None
    assert _calculation_context([extreme_value] * 100) is not None
    assert _calculation_context([Decimal("1")] * 100 + [extreme_value] * 100) is None
    for products in (ones + extremes, extremes + ones):
        _assert_stats_cohort(products, priced=100, minimum=Decimal("1"), maximum=Decimal("1"))
