"""Offline tests for the Alibaba relevance score (query vs title match)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bera_price_tracker.application.alibaba_relevance import (
    RELEVANCE_GOOD,
    RELEVANCE_HIGH,
    RELEVANCE_LOW,
    RELEVANCE_PARTIAL,
    calculate_listing_relevance,
    format_relevance_display,
    normalize_tokens,
    relevance_label,
    score_alibaba_relevance,
)
from bera_price_tracker.application.services import SearchAlibabaProducts
from bera_price_tracker.domain.alibaba import AlibabaProduct
from bera_price_tracker.gui import analysis
from bera_price_tracker.gui import services as gui_services
from bera_price_tracker.infrastructure.providers.alibaba import map_alibaba_item

SRC = Path(__file__).resolve().parents[2] / "src"


class FakeAlibabaProvider:
    def __init__(self, products: list[AlibabaProduct]) -> None:
        self.products = products

    def search(self, query: str, limit: int) -> list[AlibabaProduct]:
        return list(self.products)


def _product(title: str) -> AlibabaProduct:
    product = map_alibaba_item({"title": title, "price": "$5.00"})
    assert product is not None
    return product


def _payload(query: str, titles: list[str]) -> dict[str, Any]:
    return gui_services.run_alibaba_search(
        query,
        10,
        search_service=SearchAlibabaProducts(FakeAlibabaProvider([_product(t) for t in titles])),
    )


def test_normalization_example() -> None:
    assert normalize_tokens("Wireless-Mouse 2.4GHz") == ["wireless", "mouse", "2", "4ghz"]


def test_normalization_strips_diacritics_and_case() -> None:
    assert normalize_tokens("Ratón Inalámbrico ÓPTICO") == ["raton", "inalambrico", "optico"]


def test_full_coverage_with_exact_phrase_is_100() -> None:
    result = calculate_listing_relevance("wireless mouse", "Wholesale Wireless Mouse 2.4GHz")
    assert result.relevance_score == 100
    assert result.matched_tokens == 2
    assert result.total_query_tokens == 2
    assert result.exact_phrase_match is True


def test_full_coverage_without_phrase_is_80() -> None:
    result = calculate_listing_relevance("wireless mouse", "Mouse Rechargeable Wireless Gaming")
    assert result.relevance_score == 80
    assert result.exact_phrase_match is False


def test_half_coverage_is_40() -> None:
    result = calculate_listing_relevance("wireless mouse", "Ergonomic Mouse Pad")
    assert result.relevance_score == 40
    assert result.matched_tokens == 1
    assert result.total_query_tokens == 2


def test_zero_coverage_is_0() -> None:
    result = calculate_listing_relevance("wireless mouse", "Tracked Lawn Mower")
    assert result.relevance_score == 0
    assert result.matched_tokens == 0
    assert result.exact_phrase_match is False


def test_single_token_query_can_reach_100() -> None:
    result = calculate_listing_relevance("mouse", "Optical Mouse USB")
    assert result.relevance_score == 100
    missing = calculate_listing_relevance("mouse", "Mechanical Keyboard")
    assert missing.relevance_score == 0


def test_whole_token_matching_avoids_partial_words() -> None:
    result = calculate_listing_relevance("car", "SD Card Reader")
    assert result.relevance_score == 0
    exact = calculate_listing_relevance("car", "RC Car Toy")
    assert exact.relevance_score == 100


def test_empty_query_is_safe_zero() -> None:
    for query in ("", "   ", None):
        result = calculate_listing_relevance(query, "Wireless Mouse")
        assert result.relevance_score == 0
        assert result.total_query_tokens == 0
        assert result.exact_phrase_match is False


def test_missing_title_is_safe_zero() -> None:
    result = calculate_listing_relevance("wireless mouse", None)
    assert result.relevance_score == 0


def test_generic_queries_work() -> None:
    cases = {
        "solar panels": "550W Mono Solar Panels for Home",
        "office chair": "Ergonomic Office Chair Mesh",
        "motorcycle brake pads": "Motorcycle Brake Pads for Bera SBR",
        "coffee machine": "Automatic Espresso Coffee Machine",
        "cnc router": "3-Axis CNC Router 6090",
    }
    for query, title in cases.items():
        result = calculate_listing_relevance(query, title)
        assert result.relevance_score == 100


def test_relevance_labels_at_thresholds() -> None:
    assert relevance_label(100) == RELEVANCE_HIGH
    assert relevance_label(80) == RELEVANCE_HIGH
    assert relevance_label(79) == RELEVANCE_GOOD
    assert relevance_label(60) == RELEVANCE_GOOD
    assert relevance_label(59) == RELEVANCE_PARTIAL
    assert relevance_label(30) == RELEVANCE_PARTIAL
    assert relevance_label(29) == RELEVANCE_LOW
    assert relevance_label(0) == RELEVANCE_LOW


def test_rows_expose_relevance_separately_from_opportunity() -> None:
    payload = _payload("wireless mouse", ["Wholesale Wireless Mouse", "Tracked Lawn Mower"])
    first, second = payload["results"]
    assert first["relevance"] == "100/100"
    assert second["relevance"] == "0/100"
    assert format_relevance_display(40) == "40/100"
    for row in (first, second):
        assert "score" in row and "relevance" in row
        assert row["score"] != "" and row["relevance"] != ""
        assert row["relevance_tokens"].endswith("términos de la búsqueda")


def test_sort_by_relevance_descending_view() -> None:
    payload = _payload(
        "wireless mouse",
        ["Tracked Lawn Mower", "Ergonomic Mouse Pad", "Wholesale Wireless Mouse"],
    )
    rows = list(payload["results"])
    view = analysis.apply_table_view(rows, sort=analysis.SORT_RELEVANCE_DESC)
    assert [row["title"] for row in view] == [
        "Wholesale Wireless Mouse",
        "Ergonomic Mouse Pad",
        "Tracked Lawn Mower",
    ]
    assert [row["title"] for row in rows] == [
        "Tracked Lawn Mower",
        "Ergonomic Mouse Pad",
        "Wholesale Wireless Mouse",
    ]


def test_relevance_ignores_price_moq_and_country() -> None:
    text = (SRC / "bera_price_tracker" / "application" / "alibaba_relevance.py").read_text(
        encoding="utf-8"
    )
    for banned in ("price", "moq", "supplier_country", "representative"):
        assert banned not in text
    assert "float(" not in text
    lowered = text.lower()
    for alarmist in ("producto incorrecto", "fraude", "publicacion mala", "publicación mala"):
        assert alarmist not in lowered


def test_scoring_is_deterministic() -> None:
    first = calculate_listing_relevance("wireless mouse", "Rechargeable Wireless Mouse")
    second = calculate_listing_relevance("wireless mouse", "Rechargeable Wireless Mouse")
    assert first == second
    products = [_product("Wireless Mouse"), _product("Mouse Pad"), _product("Lawn Mower")]
    assert score_alibaba_relevance("wireless mouse", products) == score_alibaba_relevance(
        "wireless mouse", products
    )


def _filter_rows() -> list[dict[str, Any]]:
    payload = _payload(
        "wireless mouse",
        [
            "Wholesale Wireless Mouse",
            "Rechargeable Wireless Mouse USB",
            "Ergonomic Mouse Pad",
            "Tracked Lawn Mower",
        ],
    )
    return list(payload["results"])


def test_min_relevance_filter_30() -> None:
    rows = _filter_rows()
    view = analysis.apply_table_view(rows, min_relevance=30)
    assert [row["title"] for row in view] == [
        "Wholesale Wireless Mouse",
        "Rechargeable Wireless Mouse USB",
        "Ergonomic Mouse Pad",
    ]


def test_min_relevance_filter_60() -> None:
    rows = _filter_rows()
    view = analysis.apply_table_view(rows, min_relevance=60)
    assert [row["title"] for row in view] == [
        "Wholesale Wireless Mouse",
        "Rechargeable Wireless Mouse USB",
    ]


def test_min_relevance_filter_80() -> None:
    rows = _filter_rows()
    view = analysis.apply_table_view(rows, min_relevance=80)
    assert [row["title"] for row in view] == [
        "Wholesale Wireless Mouse",
        "Rechargeable Wireless Mouse USB",
    ]
    strict = analysis.apply_table_view(rows, min_relevance=0)
    assert len(strict) == 4


def test_min_relevance_filter_does_not_mutate_originals() -> None:
    rows = _filter_rows()
    before = [row["title"] for row in rows]
    analysis.apply_table_view(rows, min_relevance=80)
    assert [row["title"] for row in rows] == before
    assert len(rows) == 4


def test_clear_filters_resets_min_relevance() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.set_alibaba_min_relevance("60+")
    assert state.alibaba_min_relevance == 60
    state.set_alibaba_min_relevance("80+")
    assert state.alibaba_min_relevance == 80
    state.clear_alibaba_filters()
    assert state.alibaba_min_relevance == 0
    state.set_alibaba_min_relevance("Todas")
    assert state.alibaba_min_relevance == 0


def test_score_alibaba_relevance_batch() -> None:
    products = [_product("Wireless Mouse"), _product("Lawn Mower")]
    results = score_alibaba_relevance("wireless mouse", products)
    assert [r.relevance_score for r in results] == [100, 0]
