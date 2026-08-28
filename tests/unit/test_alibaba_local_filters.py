"""Offline tests for local Alibaba view filters, sorting, charts and counters."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from bera_price_tracker.application.services import SearchAlibabaProducts
from bera_price_tracker.domain.alibaba import AlibabaProduct
from bera_price_tracker.gui import analysis
from bera_price_tracker.gui import services as gui_services

SRC = Path(__file__).resolve().parents[2] / "src"

OUTLIER_PRICES = ["$1.00", "$10.00", "$11.00", "$12.00", "$13.00", "$14.00", "$100.00"]


class FakeAlibabaProvider:
    def __init__(self, products: list[AlibabaProduct]) -> None:
        self.products = products
        self.calls = 0

    def search(self, query: str, limit: int) -> list[AlibabaProduct]:
        self.calls += 1
        return list(self.products)


def _product(title: str, price: str | None = None, currency: str | None = "USD") -> AlibabaProduct:
    from bera_price_tracker.infrastructure.providers.alibaba import map_alibaba_item

    raw: dict[str, Any] = {"title": title, "url": "https://www.alibaba.com/p"}
    if price is not None:
        raw["price"] = price
    if currency is not None:
        raw["currency"] = currency
    product = map_alibaba_item(raw)
    assert product is not None
    return product


def _payload(products: list[AlibabaProduct]) -> dict[str, Any]:
    return gui_services.run_alibaba_search(
        "wireless mouse",
        10,
        search_service=SearchAlibabaProducts(FakeAlibabaProvider(products)),
    )


def _rows(prices: list[tuple[str, str | None]]) -> list[dict[str, Any]]:
    payload = _payload([_product(title, price) for title, price in prices])
    return list(payload["results"])


def _titles(rows: list[dict[str, Any]]) -> list[str]:
    return [row["title"] for row in rows]


def test_original_order_preserved() -> None:
    rows = _rows([("A", "$3"), ("B", "$1"), ("C", "$2")])
    view = analysis.apply_table_view(rows)
    assert _titles(view) == ["A", "B", "C"]


def test_sort_price_ascending() -> None:
    rows = _rows([("A", "$3"), ("B", "$1"), ("C", "$2")])
    view = analysis.apply_table_view(rows, sort=analysis.SORT_PRICE_ASC)
    assert _titles(view) == ["B", "C", "A"]


def test_sort_price_descending() -> None:
    rows = _rows([("A", "$3"), ("B", "$1"), ("C", "$2")])
    view = analysis.apply_table_view(rows, sort=analysis.SORT_PRICE_DESC)
    assert _titles(view) == ["A", "C", "B"]


def test_unpriced_rows_go_last() -> None:
    rows = _rows([("NoPrice", None), ("Cheap", "$1"), ("Ask", "Contact supplier"), ("Mid", "$2")])
    view = analysis.apply_table_view(rows, sort=analysis.SORT_PRICE_ASC)
    assert _titles(view) == ["Cheap", "Mid", "NoPrice", "Ask"]


def test_range_rows_sort_by_representative_and_keep_display() -> None:
    rows = _rows([("Range", "$1.30-1.60"), ("Low", "$1.00")])
    assert rows[0]["representative"] == "1.45"
    view = analysis.apply_table_view(rows, sort=analysis.SORT_PRICE_ASC)
    assert _titles(view) == ["Low", "Range"]
    assert view[1]["price"] == "$1.30–$1.60"


def test_minimum_filter() -> None:
    rows = _rows([("A", "$1"), ("B", "$5"), ("C", None)])
    view = analysis.apply_table_view(rows, minimum=Decimal("2"))
    assert _titles(view) == ["B"]


def test_maximum_filter() -> None:
    rows = _rows([("A", "$1"), ("B", "$5"), ("C", None)])
    view = analysis.apply_table_view(rows, maximum=Decimal("2"))
    assert _titles(view) == ["A"]


def test_minimum_and_maximum_filter() -> None:
    rows = _rows([("A", "$1"), ("B", "$3"), ("C", "$9")])
    view = analysis.apply_table_view(rows, minimum=Decimal("1.00"), maximum=Decimal("5.00"))
    assert _titles(view) == ["A", "B"]


def test_non_usd_rows_excluded_when_filtering() -> None:
    rows = _payload([_product("EUR", "EUR 100", currency=None), _product("USD", "$5")])["results"]
    assert rows[0]["representative"] == ""
    view = analysis.apply_table_view(rows, minimum=Decimal("1"))
    assert _titles(view) == ["USD"]


def test_invalid_price_filters_return_messages() -> None:
    minimum, maximum, error = analysis.validate_price_filters("5", "2")
    assert (minimum, maximum) == (None, None)
    assert error == analysis.FILTER_RANGE_INVALID
    assert analysis.validate_price_filters("abc", "")[2] == analysis.FILTER_MIN_INVALID
    assert analysis.validate_price_filters("", "-1")[2] == analysis.FILTER_MAX_INVALID
    assert analysis.validate_price_filters("", "")[2] == ""
    assert analysis.validate_price_filters("1.50", "2.50") == (
        Decimal("1.50"),
        Decimal("2.50"),
        "",
    )


def test_hide_outliers_is_table_only() -> None:
    payload = _payload([_product(f"p{index}", price) for index, price in enumerate(OUTLIER_PRICES)])
    rows = list(payload["results"])
    view = analysis.apply_table_view(rows, hide_outliers=True)
    assert len(rows) == 7
    assert len(view) == 5
    assert "p0" not in _titles(view)
    assert "p6" not in _titles(view)
    assert payload["summary"]["outliers"] == "2"


def test_apply_view_does_not_mutate_original_rows() -> None:
    rows = _rows([("A", "$3"), ("B", None), ("C", "$1")])
    before = _titles(rows)
    analysis.apply_table_view(
        rows,
        sort=analysis.SORT_PRICE_DESC,
        minimum=Decimal("1"),
        maximum=Decimal("2"),
        hide_outliers=True,
    )
    assert _titles(rows) == before
    assert len(rows) == 3


def test_clear_filters_resets_state() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.set_alibaba_sort("Precio: mayor a menor")
    state.set_alibaba_price_min("1.00")
    state.set_alibaba_price_max("5.00")
    state.set_alibaba_hide_outliers(True)
    state.set_alibaba_chart_scope("Rango típico")
    assert state.alibaba_sort == analysis.SORT_PRICE_DESC
    assert state.alibaba_chart_scope == analysis.CHART_SCOPE_TYPICAL
    state.clear_alibaba_filters()
    assert state.alibaba_sort == analysis.SORT_ORIGINAL
    assert state.alibaba_price_min == ""
    assert state.alibaba_price_max == ""
    assert state.alibaba_hide_outliers is False
    assert state.alibaba_chart_scope == analysis.CHART_SCOPE_ALL
    assert state.alibaba_relevance_weight == 50
    assert state.alibaba_opportunity_weight == 30
    assert state.alibaba_reputation_weight == 20


def test_showing_counter_text() -> None:
    assert analysis.showing_counter(17, 50) == "Mostrando 17 de 50 productos"
    assert analysis.showing_counter(0, 0) == "Mostrando 0 de 0 productos"


def test_histogram_empty() -> None:
    assert analysis.build_histogram([]) == []


def test_histogram_single_value() -> None:
    bins = analysis.build_histogram([Decimal("4")])
    assert bins == [{"label": "$4.00", "count": "1", "width": "100%"}]


def test_histogram_two_values_does_not_fail() -> None:
    bins = analysis.build_histogram([Decimal("1.40"), Decimal("3.20")])
    assert sum(int(item["count"]) for item in bins) == 2
    assert len(bins) == 2


def test_histogram_normal_dataset() -> None:
    values = [Decimal(str(value)) for value in range(1, 11)]
    bins = analysis.build_histogram(values)
    assert 2 <= len(bins) <= 6
    assert sum(int(item["count"]) for item in bins) == 10
    for item in bins:
        assert item["label"].startswith("$")
        assert "–" in item["label"]
        assert item["width"].endswith("%")


def test_histogram_survives_extreme_representative_prices() -> None:
    bins = analysis.build_histogram([Decimal("4.00"), Decimal("1E+100")])
    assert bins
    assert sum(int(item["count"]) for item in bins) == 2


def test_chart_typical_scope_excludes_outliers() -> None:
    values = [Decimal(price.replace("$", "")) for price in OUTLIER_PRICES]
    scoped = analysis.select_chart_values(
        values, analysis.CHART_SCOPE_TYPICAL, Decimal("6.00"), Decimal("18.00")
    )
    assert len(scoped) == 5
    assert Decimal("1.00") not in scoped
    assert Decimal("100.00") not in scoped
    everything = analysis.select_chart_values(
        values, analysis.CHART_SCOPE_ALL, Decimal("6.00"), Decimal("18.00")
    )
    assert len(everything) == 7


def test_base_statistics_unchanged_after_filtering() -> None:
    payload = _payload([_product(f"p{index}", price) for index, price in enumerate(OUTLIER_PRICES)])
    summary_before = dict(payload["summary"])
    stats_raw_before = dict(payload["stats_raw"])
    view = analysis.apply_table_view(payload["results"], hide_outliers=True, minimum=Decimal("11"))
    assert len(view) < len(payload["results"])
    assert payload["summary"] == summary_before
    assert payload["stats_raw"] == stats_raw_before
    assert payload["summary"]["resultados"] == "7"


def test_boxplot_geometry_positions() -> None:
    geometry = analysis.boxplot_geometry(
        Decimal("0"), Decimal("25"), Decimal("50"), Decimal("75"), Decimal("100")
    )
    assert geometry["available"] == "1"
    assert geometry["box_left"] == "25.00%"
    assert geometry["box_width"] == "50.00%"
    assert geometry["median_left"] == "50.00%"
    missing = analysis.boxplot_geometry(None, None, None, None, None)
    assert missing["available"] == ""
    flat = analysis.boxplot_geometry(
        Decimal("4"), Decimal("4"), Decimal("4"), Decimal("4"), Decimal("4")
    )
    assert flat["available"] == "1"
    assert flat["median_left"] == "50.00%"


def test_analysis_module_uses_decimal_not_float() -> None:
    text = (SRC / "bera_price_tracker" / "gui" / "analysis.py").read_text(encoding="utf-8")
    assert "float(" not in text
    assert "Decimal" in text
