"""Offline tests for the Alibaba opportunity score (0-100 per listing)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from bera_price_tracker.application.alibaba_score import (
    LABEL_EXCELLENT,
    LABEL_GOOD,
    LABEL_LOW,
    LABEL_MIDDLE,
    AlibabaListingScore,
    extract_moq_quantity,
    format_score_display,
    score_alibaba_listings,
    score_label,
)
from bera_price_tracker.application.services import SearchAlibabaProducts
from bera_price_tracker.domain.alibaba import AlibabaProduct
from bera_price_tracker.gui import analysis
from bera_price_tracker.gui import services as gui_services
from bera_price_tracker.infrastructure.providers.alibaba import map_alibaba_item

SRC = Path(__file__).resolve().parents[2] / "src"

OUTLIER_PRICES = ["$1.00", "$10.00", "$11.00", "$12.00", "$13.00", "$14.00", "$100.00"]


class FakeAlibabaProvider:
    def __init__(self, products: list[AlibabaProduct]) -> None:
        self.products = products

    def search(self, query: str, limit: int) -> list[AlibabaProduct]:
        return list(self.products)


def _product(**overrides: Any) -> AlibabaProduct:
    raw: dict[str, Any] = {
        "title": "Wireless mouse",
        "price": "$5.00",
        "moq": "Min. order: 10 pieces",
        "companyName": "Acme Trading",
        "countryCode": "CN",
        "mainImage": "https://img.example.com/x.jpg",
        "productUrl": "https://www.alibaba.com/p",
    }
    raw.update(overrides)
    raw = {key: value for key, value in raw.items() if value is not None}
    product = map_alibaba_item(raw)
    assert product is not None
    return product


def _scores(products: list[AlibabaProduct]) -> list[AlibabaListingScore]:
    return score_alibaba_listings(products)


def _payload(products: list[AlibabaProduct]) -> dict[str, Any]:
    return gui_services.run_alibaba_search(
        "wireless mouse",
        10,
        search_service=SearchAlibabaProducts(FakeAlibabaProvider(products)),
    )


def test_total_score_always_between_0_and_100() -> None:
    products = [
        _product(title=f"p{index}", price=price) for index, price in enumerate(OUTLIER_PRICES)
    ]
    products.append(_product(title="sin precio", price=None, moq=None))
    products.append(_product(title="eur", price="EUR 100"))
    products.append(
        _product(
            title="minimo",
            price=None,
            moq=None,
            companyName=None,
            countryCode=None,
            mainImage=None,
            productUrl=None,
        )
    )
    for score in _scores(products):
        assert 0 <= score.total <= 100
        assert score.total == (
            score.price_score
            + score.moq_score
            + score.information_score
            + score.price_clarity_score
        )


def test_lowest_normal_price_gets_top_price_score() -> None:
    prices = ["$10.00", "$11.00", "$12.00", "$13.00", "$14.00"]
    scores = _scores(
        [_product(title=f"p{index}", price=price) for index, price in enumerate(prices)]
    )
    assert scores[0].price_score == 45
    assert scores[0].is_price_outlier is False
    assert all(scores[0].price_score >= other.price_score for other in scores)


def test_lower_outlier_price_score_is_capped() -> None:
    scores = _scores(
        [_product(title=f"p{index}", price=price) for index, price in enumerate(OUTLIER_PRICES)]
    )
    lowest = scores[0]
    assert lowest.is_price_outlier is True
    assert lowest.price_score == 25
    normal_lowest = scores[1]
    assert normal_lowest.is_price_outlier is False
    assert normal_lowest.price_score > lowest.price_score


def test_highest_price_gets_lowest_price_score() -> None:
    scores = _scores(
        [_product(title=f"p{index}", price=price) for index, price in enumerate(OUTLIER_PRICES)]
    )
    highest = scores[-1]
    assert highest.price_score == 0
    assert highest.is_price_outlier is True


def test_moq_one_beats_moq_hundred() -> None:
    scores = _scores(
        [
            _product(title="low", moq="Min. order: 1 piece"),
            _product(title="high", moq="Min. order: 100 sets"),
        ]
    )
    assert scores[0].moq_score == 25
    assert scores[1].moq_score == 0
    assert scores[0].moq_score > scores[1].moq_score


def test_unknown_moq_scores_zero_but_keeps_text() -> None:
    products = [
        _product(title="numeric", moq="Min. order: 2 pieces"),
        _product(title="negotiable", moq="Negotiable"),
    ]
    scores = _scores(products)
    assert scores[1].moq_score == 0
    payload = _payload(products)
    assert payload["results"][1]["moq"] == "Negotiable"


def test_extract_moq_quantity_examples() -> None:
    assert extract_moq_quantity("Min. order: 1 piece") == Decimal("1")
    assert extract_moq_quantity("Min. order: 10 pieces") == Decimal("10")
    assert extract_moq_quantity("Min. order: 100 sets") == Decimal("100")
    assert extract_moq_quantity("1,000 pieces") == Decimal("1000")
    assert extract_moq_quantity("Negotiable") is None
    assert extract_moq_quantity(None) is None


def test_complete_listing_gets_full_information_score() -> None:
    scores = _scores([_product()])
    assert scores[0].information_score == 20


def test_incomplete_listing_gets_partial_information_score() -> None:
    scores = _scores([_product(mainImage=None, countryCode=None)])
    assert scores[0].information_score == 12


def test_simple_usd_price_clarity() -> None:
    scores = _scores([_product(price="$4.00")])
    assert scores[0].price_clarity_score == 10


def test_usd_range_price_clarity() -> None:
    scores = _scores([_product(price="$1.30-$1.60")])
    assert scores[0].price_clarity_score == 7


def test_non_usd_price_clarity_is_partial() -> None:
    scores = _scores([_product(price="EUR 100")])
    assert scores[0].price_clarity_score == 4


def test_missing_price_clarity_is_zero() -> None:
    for display in (None, "Contact supplier"):
        scores = _scores([_product(price=display)])
        assert scores[0].price_clarity_score == 0


def test_score_labels_at_thresholds() -> None:
    assert score_label(100) == LABEL_EXCELLENT
    assert score_label(85) == LABEL_EXCELLENT
    assert score_label(84) == LABEL_GOOD
    assert score_label(70) == LABEL_GOOD
    assert score_label(69) == LABEL_MIDDLE
    assert score_label(50) == LABEL_MIDDLE
    assert score_label(49) == LABEL_LOW
    assert score_label(0) == LABEL_LOW


def test_score_display_is_integer_out_of_100() -> None:
    assert format_score_display(88) == "88/100"
    payload = _payload([_product()])
    row = payload["results"][0]
    assert row["score"].endswith("/100")
    assert row["score_price"].endswith("/45")
    assert row["score_moq"].endswith("/25")
    assert row["score_info"].endswith("/20")
    assert row["score_clarity"].endswith("/10")
    assert row["score_label"] in (LABEL_EXCELLENT, LABEL_GOOD, LABEL_MIDDLE, LABEL_LOW)


def test_sort_by_score_descending_view() -> None:
    products = [
        _product(title="weak", price=None, moq=None, mainImage=None, countryCode=None),
        _product(title="strong", price="$10.00", moq="Min. order: 1 piece"),
        _product(title="middle", price="$12.00", moq="Min. order: 50 pieces"),
    ]
    payload = _payload(products)
    rows = list(payload["results"])
    view = analysis.apply_table_view(rows, sort=analysis.SORT_SCORE_DESC)
    ordered_scores = [row["score_value"] for row in view]
    assert ordered_scores == sorted(ordered_scores, reverse=True)
    assert view[0]["title"] == "strong"
    assert view[-1]["title"] == "weak"


def test_sort_by_score_does_not_mutate_original_rows() -> None:
    payload = _payload(
        [
            _product(title="a", price="$10.00"),
            _product(title="b", price="$1.00", moq="Min. order: 1 piece"),
        ]
    )
    rows = list(payload["results"])
    before = [row["title"] for row in rows]
    analysis.apply_table_view(rows, sort=analysis.SORT_SCORE_DESC)
    assert [row["title"] for row in rows] == before


def test_score_module_uses_decimal_not_float() -> None:
    text = (SRC / "bera_price_tracker" / "application" / "alibaba_score.py").read_text(
        encoding="utf-8"
    )
    assert "float(" not in text
    assert "Decimal" in text
