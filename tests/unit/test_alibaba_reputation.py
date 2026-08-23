"""Offline tests for the supplier reputation score using the observed fixture."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from bera_price_tracker.application.alibaba_reputation import (
    LABEL_INSUFFICIENT,
    LABEL_SOLID,
    LABEL_VERY_SOLID,
    UNAVAILABLE_DISPLAY,
    calculate_supplier_reputation,
    format_component_points,
    format_reputation_display,
    parse_gold_supplier_years,
    parse_rating_0_5,
    parse_review_count,
    review_count_points,
)
from bera_price_tracker.gui import analysis
from bera_price_tracker.infrastructure.providers.alibaba import map_alibaba_item

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "alibaba_reputation_observed.json"
SRC = ROOT / "src"


def _observed_items() -> list[dict[str, object]]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["source"] == "Alibaba via Apify"
    assert payload["actor"] == "scraper-engine/alibaba-scraper"
    assert payload["query"] == "wireless mouse"
    return list(payload["items"])


def test_parse_years_and_ratings() -> None:
    assert parse_gold_supplier_years("6 yrs") == Decimal("6")
    assert parse_gold_supplier_years("1 yr") == Decimal("1")
    assert parse_gold_supplier_years("not-a-year") is None
    assert parse_rating_0_5("4.5") == Decimal("4.5")
    assert parse_rating_0_5("5") == Decimal("5")
    assert parse_rating_0_5("5.1") is None
    assert parse_rating_0_5("-0.1") is None
    assert parse_rating_0_5("") is None
    assert parse_review_count("0") == Decimal("0")
    assert parse_review_count("200") == Decimal("200")
    assert parse_review_count("abc") is None


def test_review_count_buckets() -> None:
    assert review_count_points(Decimal("0")) == Decimal("0")
    assert review_count_points(Decimal("1")) == Decimal("3")
    assert review_count_points(Decimal("9")) == Decimal("3")
    assert review_count_points(Decimal("10")) == Decimal("6")
    assert review_count_points(Decimal("24")) == Decimal("6")
    assert review_count_points(Decimal("25")) == Decimal("9")
    assert review_count_points(Decimal("50")) == Decimal("12")
    assert review_count_points(Decimal("100")) == Decimal("15")


def test_component_formulas() -> None:
    result = calculate_supplier_reputation(
        {
            "supplierServiceScore": "4.5",
            "reviewScore": "4.5",
            "goldSupplierYears": "5 yrs",
            "reviewCount": "100",
        }
    )
    assert result.service_points == Decimal("31.5")
    assert result.review_score_points == Decimal("27")
    assert result.years_points == Decimal("10")
    assert result.review_count_points == Decimal("15")
    assert result.score == 84
    assert result.evidence_coverage == 100
    assert format_component_points(result.service_points, Decimal("35")) == "31.5/35"
    assert format_reputation_display(result.score) == "84/100"


def test_years_saturate_at_ten() -> None:
    ten = calculate_supplier_reputation({"goldSupplierYears": "10 yrs", "reviewCount": "100"})
    sixteen = calculate_supplier_reputation({"goldSupplierYears": "16 yrs", "reviewCount": "100"})
    one = calculate_supplier_reputation({"goldSupplierYears": "1 yr", "reviewCount": "100"})
    assert ten.years_points == Decimal("20")
    assert sixteen.years_points == Decimal("20")
    assert one.years_points == Decimal("2")


def test_missing_service_is_not_zero() -> None:
    result = calculate_supplier_reputation(
        {
            "reviewScore": "5",
            "goldSupplierYears": "10 yrs",
            "reviewCount": "100",
        }
    )
    assert result.service_points is None
    assert result.available_signal_count == 3
    assert result.evidence_coverage == 65
    assert result.score == 100


def test_insufficient_evidence_is_unavailable() -> None:
    only_years = calculate_supplier_reputation({"goldSupplierYears": "16 yrs"})
    assert only_years.score is None
    assert only_years.label == LABEL_INSUFFICIENT
    assert format_reputation_display(only_years.score) == UNAVAILABLE_DISPLAY
    thin = calculate_supplier_reputation({"goldSupplierYears": "1 yr", "reviewCount": "0"})
    assert thin.available_signal_count == 2
    assert thin.evidence_coverage == 35
    assert thin.score is None


def test_observed_fixture_scores() -> None:
    items = _observed_items()
    assert len(items) == 20
    deying = calculate_supplier_reputation(items[0])
    assert deying.score == 75
    assert deying.label == LABEL_SOLID
    assert deying.evidence_coverage == 100
    gracious = [
        calculate_supplier_reputation(item)
        for item in items
        if item["companyName"] == "Shenzhen Gracious Electronic Technology Co., Ltd."
    ]
    assert len(gracious) == 3
    assert {item.score for item in gracious} == {98}
    assert gracious[0].label == LABEL_VERY_SOLID
    couso = [
        calculate_supplier_reputation(item)
        for item in items
        if item["companyName"] == "Dongguan Couso Technology Co., Ltd."
    ]
    assert len(couso) == 2
    assert {item.score for item in couso} == {84}
    insufficient = calculate_supplier_reputation(items[6])
    assert items[6]["companyName"] == "Guangzhou Yanzhikang Technology Co., Ltd."
    assert insufficient.score is None
    assert insufficient.label == LABEL_INSUFFICIENT


def test_same_supplier_signals_are_deterministic() -> None:
    items = [
        item
        for item in _observed_items()
        if item["companyName"] == "Shenzhen Gracious Electronic Technology Co., Ltd."
    ]
    first = calculate_supplier_reputation(items[0])
    second = calculate_supplier_reputation(items[1])
    assert first == second


def test_unused_fields_do_not_change_score() -> None:
    base = {
        "supplierServiceScore": "4.5",
        "reviewScore": "4.6",
        "goldSupplierYears": "5 yrs",
        "reviewCount": "200",
        "companyName": "Acme",
    }
    original = calculate_supplier_reputation(base)
    mutated: dict[str, object] = dict(base)
    mutated.update(
        {
            "productScore": "1.0",
            "shippingScore": "1.0",
            "displayStarLevel": "5",
            "soldOrder": "99,999 sold",
            "certifications": ["CE", "FCC"],
            "showCrown": True,
            "countryCode": "US",
            "price": "$999.00",
            "moq": "Min. order: 10000 pieces",
            "companyName": "Totally Different Name Ltd.",
        }
    )
    changed = calculate_supplier_reputation(mutated)
    assert changed.score == original.score
    assert changed.service_points == original.service_points
    assert changed.review_score_points == original.review_score_points
    assert changed.years_points == original.years_points
    assert changed.review_count_points == original.review_count_points


def test_mapper_reads_observed_supplier_fields() -> None:
    raw = _observed_items()[0]
    product = map_alibaba_item(raw)
    assert product is not None
    assert product.gold_supplier_years == "6 yrs"
    assert product.supplier_service_score == "4.4"
    assert product.review_count == "13"
    assert product.review_score == "4.3"
    mapped = calculate_supplier_reputation(product)
    direct = calculate_supplier_reputation(raw)
    assert mapped.score == direct.score == 75


def test_reputation_sort_puts_unavailable_last() -> None:
    rows = [
        {
            "title": "thin",
            "reputation_available": False,
            "reputation_value": 0,
            "score_value": 10,
            "relevance_value": 10,
        },
        {
            "title": "high",
            "reputation_available": True,
            "reputation_value": 98,
            "score_value": 10,
            "relevance_value": 10,
        },
        {
            "title": "mid",
            "reputation_available": True,
            "reputation_value": 75,
            "score_value": 10,
            "relevance_value": 10,
        },
    ]
    view = analysis.apply_table_view(rows, sort=analysis.SORT_REPUTATION_DESC)
    assert [row["title"] for row in view] == ["high", "mid", "thin"]


def test_reputation_filter_hides_insufficient() -> None:
    rows = [
        {"title": "ok", "reputation_available": True, "reputation_value": 75},
        {"title": "low", "reputation_available": True, "reputation_value": 40},
        {"title": "none", "reputation_available": False, "reputation_value": 0},
    ]
    filtered = analysis.apply_table_view(rows, min_reputation=70)
    assert [row["title"] for row in filtered] == ["ok"]
    everyone = analysis.apply_table_view(rows, min_reputation=0)
    assert [row["title"] for row in everyone] == ["ok", "low", "none"]


def test_top_three_uses_general_ranking_and_shows_reputation() -> None:
    rows = analysis.apply_table_view(
        [
            {
                "title": "first",
                "price": "$1.00",
                "score_value": 80,
                "relevance_value": 100,
                "reputation_available": True,
                "reputation_value": 70,
            },
            {
                "title": "second",
                "price": "$2.00",
                "score_value": 90,
                "relevance_value": 80,
                "reputation_available": False,
                "reputation_value": 0,
            },
        ]
    )
    cards = analysis.top_result_cards(rows)
    # first: 100*0.50 + 80*0.30 + 70*0.20 = 88.
    # second (sin reputación, renormalizado): (80*50 + 90*30) / 80 = 83.75 -> 84.
    assert cards[0]["title"] == "first"
    assert cards[0]["ranking"] == "Ranking 88"
    assert cards[1]["ranking"] == "Ranking 84"
    assert cards[0]["reputation"] == "Reputación 70"
    assert cards[1]["reputation"] == "Reputación: Datos insuficientes"


def test_module_uses_decimal_and_avoids_trust_language() -> None:
    text = (SRC / "bera_price_tracker" / "application" / "alibaba_reputation.py").read_text(
        encoding="utf-8"
    )
    assert "float(" not in text
    assert "Decimal" in text
    lowered = text.lower()
    for banned in (
        "trust score",
        "guaranteed supplier",
        "safe supplier",
        "proveedor confiable",
        "proveedor seguro",
        "recomendado",
        "riesgo bajo",
        "fraude",
    ):
        assert banned not in lowered
