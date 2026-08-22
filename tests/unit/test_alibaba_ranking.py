"""Offline tests for the configurable Alibaba ranking blend."""

from __future__ import annotations

from pathlib import Path

from bera_price_tracker.application.alibaba_ranking import (
    DEFAULT_RELEVANCE_WEIGHT,
    PRESET_BALANCED,
    PRESET_MORE_OPPORTUNITY,
    PRESET_MORE_RELEVANT,
    calculate_alibaba_ranking,
    clamp_relevance_weight,
    format_ranking_display,
    format_ranking_tooltip,
    is_low_match,
)
from bera_price_tracker.gui import analysis

SRC = Path(__file__).resolve().parents[2] / "src"


def _row(
    title: str,
    *,
    opportunity: int,
    relevance: int,
    price: str = "$1.00",
) -> dict[str, object]:
    return {
        "title": title,
        "price": price,
        "score_value": opportunity,
        "score": f"{opportunity}/100",
        "relevance_value": relevance,
        "relevance": f"{relevance}/100",
    }


def test_default_blend_100_relevance_80_opportunity() -> None:
    result = calculate_alibaba_ranking(80, 100, 60)
    assert result.ranking_score == 92
    assert result.relevance_weight == 60
    assert result.opportunity_weight == 40
    assert format_ranking_display(result.ranking_score) == "92/100"


def test_default_blend_20_relevance_95_opportunity() -> None:
    result = calculate_alibaba_ranking(95, 20, 60)
    assert result.ranking_score == 50


def test_default_blend_80_relevance_90_opportunity() -> None:
    result = calculate_alibaba_ranking(90, 80, 60)
    assert result.ranking_score == 84


def test_balanced_preset_50_50() -> None:
    result = calculate_alibaba_ranking(80, 100, PRESET_BALANCED)
    assert result.ranking_score == 90
    assert result.relevance_weight == 50
    assert result.opportunity_weight == 50


def test_more_relevant_preset_75_25() -> None:
    result = calculate_alibaba_ranking(80, 100, PRESET_MORE_RELEVANT)
    assert result.ranking_score == 95
    assert result.relevance_weight == 75
    assert result.opportunity_weight == 25


def test_more_opportunity_preset_25_75() -> None:
    result = calculate_alibaba_ranking(80, 100, PRESET_MORE_OPPORTUNITY)
    assert result.ranking_score == 85
    assert result.relevance_weight == 25
    assert result.opportunity_weight == 75


def test_weight_limit_zero_uses_only_opportunity() -> None:
    result = calculate_alibaba_ranking(80, 20, 0)
    assert result.ranking_score == 80
    assert result.opportunity_weight == 100


def test_weight_limit_hundred_uses_only_relevance() -> None:
    result = calculate_alibaba_ranking(80, 20, 100)
    assert result.ranking_score == 20
    assert result.relevance_weight == 100
    assert result.opportunity_weight == 0


def test_ranking_always_between_0_and_100() -> None:
    for relevance in (0, 20, 50, 80, 100):
        for opportunity in (0, 20, 50, 80, 100):
            for weight in (0, 25, 50, 60, 75, 100):
                result = calculate_alibaba_ranking(opportunity, relevance, weight)
                assert 0 <= result.ranking_score <= 100


def test_ranking_module_uses_decimal_not_float() -> None:
    text = (SRC / "bera_price_tracker" / "application" / "alibaba_ranking.py").read_text(
        encoding="utf-8"
    )
    assert "float(" not in text
    assert "0.6" not in text
    assert "0.4" not in text
    assert "Decimal" in text
    assert 'Decimal("100")' in text


def test_sort_by_ranking_descending() -> None:
    rows = [
        _row("cheap-unrelated", opportunity=95, relevance=20),
        _row("balanced", opportunity=80, relevance=100),
        _row("mid", opportunity=90, relevance=80),
    ]
    view = analysis.apply_table_view(rows, sort=analysis.SORT_RANKING_DESC)
    assert [row["title"] for row in view] == ["balanced", "mid", "cheap-unrelated"]
    assert [row["ranking_value"] for row in view] == [92, 84, 50]


def test_changing_weights_changes_ranking() -> None:
    rows = [_row("item", opportunity=95, relevance=20)]
    default_view = analysis.apply_table_view(rows, relevance_weight=60)
    opportunity_view = analysis.apply_table_view(rows, relevance_weight=25)
    assert default_view[0]["ranking_value"] == 50
    assert opportunity_view[0]["ranking_value"] == 76


def test_changing_weights_does_not_mutate_original_scores() -> None:
    rows = [_row("item", opportunity=80, relevance=100)]
    before = (rows[0]["score_value"], rows[0]["relevance_value"])
    analysis.apply_table_view(rows, relevance_weight=25)
    analysis.apply_table_view(rows, relevance_weight=75)
    assert (rows[0]["score_value"], rows[0]["relevance_value"]) == before
    assert "ranking_value" not in rows[0]


def test_top_three_by_ranking() -> None:
    rows = analysis.apply_table_view(
        [
            _row("fourth", opportunity=10, relevance=10, price="$9.00"),
            _row("first", opportunity=80, relevance=100, price="$1.80"),
            _row("third", opportunity=90, relevance=80, price="$3.00"),
            _row("second", opportunity=72, relevance=100, price="$2.10"),
        ]
    )
    cards = analysis.top_result_cards(rows)
    assert [card["title"] for card in cards] == ["first", "second", "third"]
    assert cards[0]["ranking"] == "Ranking 92"
    assert cards[0]["relevance"] == "Relevancia 100"
    assert cards[0]["opportunity"] == "Oportunidad 80"
    assert cards[0]["price"] == "$1.80"
    assert cards[1]["ranking"] == "Ranking 89"


def test_top_three_respects_relevance_filter() -> None:
    rows = [
        _row("cheap-unrelated", opportunity=95, relevance=20),
        _row("good", opportunity=72, relevance=100),
        _row("ok", opportunity=90, relevance=80),
        _row("partial", opportunity=80, relevance=40),
    ]
    filtered = analysis.apply_table_view(rows, min_relevance=60)
    cards = analysis.top_result_cards(filtered)
    titles = [card["title"] for card in cards]
    assert "cheap-unrelated" not in titles
    assert "partial" not in titles
    assert titles == ["good", "ok"]


def test_alibaba_results_are_not_modified() -> None:
    rows = [
        _row("a", opportunity=80, relevance=100),
        _row("b", opportunity=95, relevance=20),
    ]
    snapshot = [dict(row) for row in rows]
    analysis.apply_table_view(rows, sort=analysis.SORT_RANKING_DESC, min_relevance=60)
    assert rows == snapshot


def test_annotate_ranking_supports_reflex_row_models() -> None:
    from bera_price_tracker.gui.state import AlibabaResultRow

    row = AlibabaResultRow(
        title="item",
        score="80/100",
        score_value=80,
        relevance="100/100",
        relevance_value=100,
    )
    annotated = analysis.annotate_ranking([row])
    assert annotated[0] is not row
    assert annotated[0].ranking_value == 92
    assert annotated[0].ranking == "92/100"
    assert annotated[0].title == "item"
    assert row.ranking_value == 0
    assert row.ranking == ""


def test_ranking_is_local_no_network_imports() -> None:
    text = (SRC / "bera_price_tracker" / "application" / "alibaba_ranking.py").read_text(
        encoding="utf-8"
    )
    for banned in ("requests", "apify", "httpx", "urllib", "socket"):
        assert banned not in text


def test_low_match_badge_does_not_cap_ranking() -> None:
    result = calculate_alibaba_ranking(95, 20, 60)
    assert result.ranking_score == 50
    assert is_low_match(20) is True
    assert is_low_match(30) is False
    view = analysis.apply_table_view([_row("cheap", opportunity=95, relevance=20)])
    assert view[0]["ranking_low_match"] is True
    assert view[0]["ranking_value"] == 50


def test_tooltip_follows_weights() -> None:
    assert (
        format_ranking_tooltip(DEFAULT_RELEVANCE_WEIGHT)
        == "Ranking = 60% relevancia + 40% oportunidad"
    )
    assert format_ranking_tooltip(75) == "Ranking = 75% relevancia + 25% oportunidad"


def test_presets_and_clear_filters_are_local() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    assert state.alibaba_relevance_weight == 60
    state.apply_ranking_preset_balanced()
    assert state.alibaba_relevance_weight == 50
    state.apply_ranking_preset_more_relevant()
    assert state.alibaba_relevance_weight == 75
    state.apply_ranking_preset_more_opportunity()
    assert state.alibaba_relevance_weight == 25
    state.set_alibaba_relevance_weight(40)
    assert state.alibaba_relevance_weight == 40
    state.clear_alibaba_filters()
    assert state.alibaba_relevance_weight == 60
    assert clamp_relevance_weight(-10) == 0
    assert clamp_relevance_weight(140) == 100


def test_ranking_module_avoids_commercial_claims() -> None:
    text = (
        (SRC / "bera_price_tracker" / "application" / "alibaba_ranking.py")
        .read_text(encoding="utf-8")
        .lower()
    )
    for banned in (
        "compra recomendada",
        "proveedor confiable",
        "garantía",
        "garantia",
        "fraude",
    ):
        assert banned not in text
