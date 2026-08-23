"""Offline tests for the three-component Alibaba ranking blend."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from bera_price_tracker.application.alibaba_ranking import (
    DEFAULT_WEIGHTS,
    PRESET_BALANCED,
    PRESET_MORE_OPPORTUNITY,
    PRESET_MORE_RELEVANT,
    PRESET_MORE_REPUTATION,
    WEIGHT_RANGE_ERROR,
    WEIGHT_TOTAL_ERROR,
    RankingComponent,
    RankingWeights,
    calculate_alibaba_ranking,
    clamp_weight,
    combine_ranking_components,
    format_ranking_display,
    format_ranking_tooltip,
    is_low_match,
    validate_ranking_weights,
)
from bera_price_tracker.gui import analysis

SRC = Path(__file__).resolve().parents[2] / "src"


def _row(
    title: str,
    *,
    opportunity: int,
    relevance: int,
    reputation: int | None = None,
    price: str = "$1.00",
) -> dict[str, object]:
    return {
        "title": title,
        "price": price,
        "score_value": opportunity,
        "score": f"{opportunity}/100",
        "relevance_value": relevance,
        "relevance": f"{relevance}/100",
        "reputation_available": reputation is not None,
        "reputation_value": 0 if reputation is None else reputation,
        "reputation": "—" if reputation is None else f"{reputation}/100",
    }


# ---------------------------------------------------------------------------
# Formula (spec cases A–E)
# ---------------------------------------------------------------------------


def test_case_a_default_blend_with_reputation() -> None:
    result = calculate_alibaba_ranking(80, 100, 90)
    assert result.ranking_score == 92
    assert result.reputation_used is True
    assert result.relevance_weight_effective == Decimal("50")
    assert result.opportunity_weight_effective == Decimal("30")
    assert result.reputation_weight_effective == Decimal("20")
    assert format_ranking_display(result.ranking_score) == "92/100"


def test_case_b_exact_decimal_blend() -> None:
    # 80*0.50 + 90*0.30 + 70*0.20 = 40 + 27 + 14 = 81
    result = calculate_alibaba_ranking(90, 80, 70)
    assert result.ranking_score == 81


def test_case_c_unavailable_reputation_renormalizes_62_5_37_5() -> None:
    result = calculate_alibaba_ranking(80, 100, None)
    # (100*50 + 80*30) / 80 = 92.5 -> ROUND_HALF_EVEN -> 92
    assert result.ranking_score == 92
    assert result.reputation_used is False
    assert result.relevance_weight_effective == Decimal("62.5")
    assert result.opportunity_weight_effective == Decimal("37.5")
    assert result.reputation_weight_effective == Decimal("0")


def test_case_d_real_zero_reputation_participates_with_weight() -> None:
    result = calculate_alibaba_ranking(80, 100, 0)
    # 100*0.50 + 80*0.30 + 0*0.20 = 74
    assert result.ranking_score == 74
    assert result.reputation_used is True
    assert result.reputation_weight_effective == Decimal("20")


def test_case_e_unavailable_is_not_the_same_as_zero() -> None:
    unavailable = calculate_alibaba_ranking(80, 100, None)
    zero = calculate_alibaba_ranking(80, 100, 0)
    assert unavailable.ranking_score == 92
    assert zero.ranking_score == 74
    assert unavailable.ranking_score != zero.ranking_score
    assert unavailable.reputation_used is False
    assert zero.reputation_used is True
    assert unavailable.reputation_weight_effective != zero.reputation_weight_effective


def test_banker_rounding_on_exact_halves() -> None:
    # 60 + 20 + 13.5 = 93.5 -> 94 (even); 35 + 16 + 40.5 = 91.5 -> 92 (even)
    assert calculate_alibaba_ranking(80, 100, 90, PRESET_MORE_RELEVANT).ranking_score == 94
    assert calculate_alibaba_ranking(80, 100, 90, PRESET_MORE_REPUTATION).ranking_score == 92


def test_ranking_always_between_0_and_100() -> None:
    for relevance in (0, 20, 50, 80, 100):
        for opportunity in (0, 20, 50, 80, 100):
            for reputation in (None, 0, 50, 100):
                for weights in (
                    DEFAULT_WEIGHTS,
                    PRESET_BALANCED,
                    PRESET_MORE_RELEVANT,
                    PRESET_MORE_OPPORTUNITY,
                    PRESET_MORE_REPUTATION,
                ):
                    result = calculate_alibaba_ranking(opportunity, relevance, reputation, weights)
                    assert 0 <= result.ranking_score <= 100


def test_generic_renormalization_helper() -> None:
    components = [
        RankingComponent(score=100, weight=50, available=True),
        RankingComponent(score=80, weight=30, available=True),
        RankingComponent(score=90, weight=20, available=False),
    ]
    blended, effective = combine_ranking_components(components)
    assert blended == Decimal("92.5")
    assert effective == [Decimal("62.5"), Decimal("37.5"), Decimal("0")]


def test_renormalization_with_no_available_components_is_zero() -> None:
    components = [RankingComponent(score=90, weight=100, available=False)]
    blended, effective = combine_ranking_components(components)
    assert blended == Decimal("0")
    assert effective == [Decimal("0")]


# ---------------------------------------------------------------------------
# Presets and weight validation
# ---------------------------------------------------------------------------


def test_default_and_presets_sum_100() -> None:
    assert DEFAULT_WEIGHTS == RankingWeights(relevance=50, opportunity=30, reputation=20)
    assert PRESET_BALANCED == RankingWeights(relevance=40, opportunity=30, reputation=30)
    assert PRESET_MORE_RELEVANT == RankingWeights(relevance=60, opportunity=25, reputation=15)
    assert PRESET_MORE_OPPORTUNITY == RankingWeights(relevance=35, opportunity=45, reputation=20)
    assert PRESET_MORE_REPUTATION == RankingWeights(relevance=35, opportunity=20, reputation=45)
    for weights in (
        DEFAULT_WEIGHTS,
        PRESET_BALANCED,
        PRESET_MORE_RELEVANT,
        PRESET_MORE_OPPORTUNITY,
        PRESET_MORE_REPUTATION,
    ):
        assert weights.total() == 100
        assert (
            validate_ranking_weights(weights.relevance, weights.opportunity, weights.reputation)
            == ""
        )


def test_preset_rankings_for_same_scores() -> None:
    assert calculate_alibaba_ranking(80, 100, 90, DEFAULT_WEIGHTS).ranking_score == 92
    assert calculate_alibaba_ranking(80, 100, 90, PRESET_BALANCED).ranking_score == 91
    assert calculate_alibaba_ranking(80, 100, 90, PRESET_MORE_RELEVANT).ranking_score == 94
    assert calculate_alibaba_ranking(80, 100, 90, PRESET_MORE_OPPORTUNITY).ranking_score == 89
    assert calculate_alibaba_ranking(80, 100, 90, PRESET_MORE_REPUTATION).ranking_score == 92


def test_weight_validation_rejects_bad_inputs() -> None:
    assert validate_ranking_weights(50, 30, 20) == ""
    assert validate_ranking_weights(-1, 81, 20) == WEIGHT_RANGE_ERROR
    assert validate_ranking_weights(101, -1, 0) == WEIGHT_RANGE_ERROR
    assert validate_ranking_weights(50, 30, 10) == WEIGHT_TOTAL_ERROR
    assert validate_ranking_weights(50, 30, 30) == WEIGHT_TOTAL_ERROR
    assert clamp_weight(-10, 50) == 0
    assert clamp_weight(140, 50) == 100
    assert clamp_weight("x", 30) == 30
    assert clamp_weight(True, 20) == 20


# ---------------------------------------------------------------------------
# Tooltip / effective weights display
# ---------------------------------------------------------------------------


def test_tooltip_with_all_components_available() -> None:
    result = calculate_alibaba_ranking(80, 100, 90)
    assert format_ranking_tooltip(result) == "Relevancia: 50% · Oportunidad: 30% · Reputación: 20%"


def test_tooltip_with_unavailable_reputation_mentions_redistribution() -> None:
    result = calculate_alibaba_ranking(80, 100, None)
    assert format_ranking_tooltip(result) == (
        "Relevancia: 62.5% · Oportunidad: 37.5% · Reputación: sin datos suficientes. "
        "Los pesos se redistribuyeron entre las métricas disponibles."
    )


def test_effective_weights_with_non_terminating_shares() -> None:
    result = calculate_alibaba_ranking(80, 100, None, PRESET_MORE_RELEVANT)
    # 60/85 and 25/85, quantized to one decimal with ROUND_HALF_EVEN.
    assert result.relevance_weight_effective == Decimal("70.6")
    assert result.opportunity_weight_effective == Decimal("29.4")


# ---------------------------------------------------------------------------
# Decimal / locality guards
# ---------------------------------------------------------------------------


def test_ranking_module_uses_decimal_not_float() -> None:
    text = (SRC / "bera_price_tracker" / "application" / "alibaba_ranking.py").read_text(
        encoding="utf-8"
    )
    assert "float(" not in text
    assert "0.50" not in text
    assert "0.625" not in text
    assert "Decimal" in text
    assert 'Decimal("100")' in text


def test_ranking_is_local_no_network_imports() -> None:
    text = (SRC / "bera_price_tracker" / "application" / "alibaba_ranking.py").read_text(
        encoding="utf-8"
    )
    for banned in ("requests", "apify", "httpx", "urllib", "socket"):
        assert banned not in text


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


# ---------------------------------------------------------------------------
# View: annotation, sort, Top 3, filters
# ---------------------------------------------------------------------------


def test_sort_by_ranking_descending_uses_new_formula() -> None:
    rows = [
        _row("cheap-unrelated", opportunity=95, relevance=20),
        _row("balanced", opportunity=80, relevance=100, reputation=90),
        _row("mid", opportunity=90, relevance=80, reputation=70),
    ]
    view = analysis.apply_table_view(rows, sort=analysis.SORT_RANKING_DESC)
    assert [row["title"] for row in view] == ["balanced", "mid", "cheap-unrelated"]
    # cheap-unrelated has no reputation: (20*50 + 95*30) / 80 = 48.125 -> 48
    assert [row["ranking_value"] for row in view] == [92, 81, 48]


def test_reputation_can_change_ranking_positions() -> None:
    rows = [
        _row("more-relevant-weak-rep", opportunity=80, relevance=100, reputation=50),
        _row("less-relevant-strong-rep", opportunity=80, relevance=95, reputation=95),
    ]
    view = analysis.apply_table_view(rows, sort=analysis.SORT_RANKING_DESC)
    # 47.5+24+19 = 90.5 -> 90 beats 50+24+10 = 84.
    assert [row["title"] for row in view] == [
        "less-relevant-strong-rep",
        "more-relevant-weak-rep",
    ]
    assert [row["ranking_value"] for row in view] == [90, 84]


def test_row_with_unavailable_reputation_differs_from_zero_in_view() -> None:
    view = analysis.apply_table_view(
        [
            _row("unavailable", opportunity=80, relevance=100),
            _row("real-zero", opportunity=80, relevance=100, reputation=0),
        ]
    )
    by_title = {row["title"]: row for row in view}
    assert by_title["unavailable"]["ranking_value"] == 92
    assert by_title["real-zero"]["ranking_value"] == 74
    assert by_title["unavailable"]["ranking_reputation_used"] is False
    assert by_title["real-zero"]["ranking_reputation_used"] is True


def test_row_tooltips_follow_reputation_availability() -> None:
    view = analysis.apply_table_view(
        [
            _row("full", opportunity=80, relevance=100, reputation=90),
            _row("thin", opportunity=80, relevance=100),
        ]
    )
    by_title = {row["title"]: row for row in view}
    assert (
        by_title["full"]["ranking_tooltip"]
        == "Relevancia: 50% · Oportunidad: 30% · Reputación: 20%"
    )
    assert by_title["thin"]["ranking_tooltip"] == (
        "Relevancia: 62.5% · Oportunidad: 37.5% · Reputación: sin datos suficientes. "
        "Los pesos se redistribuyeron entre las métricas disponibles."
    )


def test_changing_weights_changes_ranking_locally() -> None:
    rows = [_row("item", opportunity=40, relevance=100, reputation=40)]
    default_view = analysis.apply_table_view(rows)
    reputation_view = analysis.apply_table_view(rows, weights=PRESET_MORE_REPUTATION)
    # 50+12+8 = 70 vs 35+8+18 = 61
    assert default_view[0]["ranking_value"] == 70
    assert reputation_view[0]["ranking_value"] == 61


def test_changing_weights_reorders_top_results() -> None:
    rows = [
        _row("relevant", opportunity=40, relevance=100, reputation=40),
        _row("reputable", opportunity=60, relevance=60, reputation=90),
    ]
    default_cards = analysis.top_result_cards(analysis.apply_table_view(rows))
    reputation_cards = analysis.top_result_cards(
        analysis.apply_table_view(rows, weights=PRESET_MORE_REPUTATION)
    )
    # Default: relevant 70 vs reputable 30+18+18 = 66.
    # Más reputación: relevant 61 vs reputable 21+12+40.5 = 73.5 -> 74.
    assert [card["title"] for card in default_cards] == ["relevant", "reputable"]
    assert [card["title"] for card in reputation_cards] == ["reputable", "relevant"]


def test_changing_weights_does_not_mutate_original_scores() -> None:
    rows = [_row("item", opportunity=80, relevance=100, reputation=90)]
    before = (
        rows[0]["score_value"],
        rows[0]["relevance_value"],
        rows[0]["reputation_value"],
        rows[0]["reputation_available"],
    )
    analysis.apply_table_view(rows, weights=PRESET_MORE_REPUTATION)
    analysis.apply_table_view(rows, weights=PRESET_MORE_RELEVANT)
    assert (
        rows[0]["score_value"],
        rows[0]["relevance_value"],
        rows[0]["reputation_value"],
        rows[0]["reputation_available"],
    ) == before
    assert "ranking_value" not in rows[0]
    assert "ranking_tooltip" not in rows[0]


def test_top_three_by_new_ranking_with_reputation() -> None:
    rows = analysis.apply_table_view(
        [
            _row("fourth", opportunity=10, relevance=10, price="$9.00"),
            _row("first", opportunity=80, relevance=100, reputation=90, price="$1.80"),
            _row("third", opportunity=90, relevance=80, reputation=70, price="$3.00"),
            _row("second", opportunity=72, relevance=100, reputation=95, price="$2.10"),
        ]
    )
    cards = analysis.top_result_cards(rows)
    assert [card["title"] for card in cards] == ["first", "second", "third"]
    assert cards[0]["ranking"] == "Ranking 92"
    assert cards[0]["relevance"] == "Relevancia 100"
    assert cards[0]["opportunity"] == "Oportunidad 80"
    assert cards[0]["reputation"] == "Reputación 90"
    assert cards[0]["price"] == "$1.80"
    # 50 + 21.6 + 19 = 90.6 -> 91
    assert cards[1]["ranking"] == "Ranking 91"


def test_top_three_shows_insufficient_reputation_but_keeps_valid_ranking() -> None:
    rows = analysis.apply_table_view(
        [
            _row("thin", opportunity=80, relevance=100),
            _row("full", opportunity=90, relevance=80, reputation=70),
        ]
    )
    cards = analysis.top_result_cards(rows)
    assert cards[0]["title"] == "thin"
    assert cards[0]["ranking"] == "Ranking 92"
    assert cards[0]["reputation"] == "Reputación: Datos insuficientes"
    assert cards[1]["reputation"] == "Reputación 70"


def test_top_three_respects_relevance_filter() -> None:
    rows = [
        _row("cheap-unrelated", opportunity=95, relevance=20, reputation=90),
        _row("good", opportunity=72, relevance=100, reputation=80),
        _row("ok", opportunity=90, relevance=80, reputation=70),
        _row("partial", opportunity=80, relevance=40),
    ]
    filtered = analysis.apply_table_view(rows, min_relevance=60)
    cards = analysis.top_result_cards(filtered)
    titles = [card["title"] for card in cards]
    assert "cheap-unrelated" not in titles
    assert "partial" not in titles
    assert titles == ["good", "ok"]


def test_top_three_respects_reputation_filter() -> None:
    rows = [
        _row("thin", opportunity=80, relevance=100),
        _row("weak", opportunity=80, relevance=100, reputation=40),
        _row("strong", opportunity=72, relevance=90, reputation=90),
    ]
    filtered = analysis.apply_table_view(rows, min_reputation=70)
    cards = analysis.top_result_cards(filtered)
    assert [card["title"] for card in cards] == ["strong"]


def test_alibaba_results_are_not_modified() -> None:
    rows = [
        _row("a", opportunity=80, relevance=100, reputation=90),
        _row("b", opportunity=95, relevance=20),
    ]
    snapshot = [dict(row) for row in rows]
    analysis.apply_table_view(rows, sort=analysis.SORT_RANKING_DESC, min_relevance=60)
    assert rows == snapshot


def test_low_match_badge_does_not_cap_ranking() -> None:
    assert is_low_match(20) is True
    assert is_low_match(30) is False
    view = analysis.apply_table_view([_row("cheap", opportunity=95, relevance=20, reputation=80)])
    # 10 + 28.5 + 16 = 54.5 -> 54 (banker's rounding to even)
    assert view[0]["ranking_low_match"] is True
    assert view[0]["ranking_value"] == 54


# ---------------------------------------------------------------------------
# Real AlibabaResultRow (rx.Base) — regression for copy(update=...)
# ---------------------------------------------------------------------------


def test_annotate_ranking_supports_reflex_row_models() -> None:
    from bera_price_tracker.gui.state import AlibabaResultRow

    row = AlibabaResultRow(
        title="item",
        score="80/100",
        score_value=80,
        relevance="100/100",
        relevance_value=100,
        reputation_available=True,
        reputation_value=90,
        reputation="90/100",
    )
    annotated = analysis.annotate_ranking([row])
    assert annotated[0] is not row
    assert annotated[0].ranking_value == 92
    assert annotated[0].ranking == "92/100"
    assert annotated[0].ranking_reputation_used is True
    assert annotated[0].title == "item"
    assert row.ranking_value == 0
    assert row.ranking == ""
    assert row.ranking_tooltip == ""


def test_reflex_row_with_unavailable_reputation_renormalizes() -> None:
    from bera_price_tracker.gui.state import AlibabaResultRow

    row = AlibabaResultRow(
        title="thin",
        score="90/100",
        score_value=90,
        relevance="80/100",
        relevance_value=80,
        reputation_available=False,
        reputation_value=0,
        reputation="—",
    )
    annotated = analysis.annotate_ranking([row])
    # (80*50 + 90*30) / 80 = 83.75 -> 84; a real 0 would give 40+27+0 = 67.
    assert annotated[0].ranking_value == 84
    assert annotated[0].ranking_reputation_used is False
    zero_row = row.copy(update={"reputation_available": True, "reputation_value": 0})
    assert analysis.annotate_ranking([zero_row])[0].ranking_value == 67


def test_reflex_rows_survive_full_local_view_pipeline() -> None:
    from bera_price_tracker.gui.state import AlibabaResultRow

    rows = [
        AlibabaResultRow(
            title="full",
            price="$2.00",
            representative="2.00",
            score_value=80,
            score="80/100",
            relevance_value=100,
            relevance="100/100",
            reputation_available=True,
            reputation_value=90,
            reputation="90/100",
        ),
        AlibabaResultRow(
            title="thin",
            price="$3.00",
            representative="3.00",
            score_value=90,
            score="90/100",
            relevance_value=80,
            relevance="80/100",
            reputation_available=False,
            reputation_value=0,
            reputation="—",
        ),
    ]
    view = analysis.apply_table_view(rows, sort=analysis.SORT_RANKING_DESC)
    assert [row.title for row in view] == ["full", "thin"]
    for row in view:
        assert row.score.endswith("/100")
        assert row.relevance.endswith("/100")
        assert row.ranking.endswith("/100")
        assert row.reputation in ("90/100", "—")
        assert row.ranking_tooltip != ""
    assert view[0].ranking == "92/100"
    assert view[1].ranking == "84/100"
    cards = analysis.top_result_cards(view)
    assert cards[0]["reputation"] == "Reputación 90"
    assert cards[1]["reputation"] == "Reputación: Datos insuficientes"
    assert rows[0].ranking == ""
    assert rows[1].ranking == ""


# ---------------------------------------------------------------------------
# State: presets, custom weights, validation, reset
# ---------------------------------------------------------------------------


def test_state_presets_and_clear_filters_are_local() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    assert (
        state.alibaba_relevance_weight,
        state.alibaba_opportunity_weight,
        state.alibaba_reputation_weight,
    ) == (50, 30, 20)
    state.apply_ranking_preset_balanced()
    assert (
        state.alibaba_relevance_weight,
        state.alibaba_opportunity_weight,
        state.alibaba_reputation_weight,
    ) == (40, 30, 30)
    state.apply_ranking_preset_more_relevant()
    assert (
        state.alibaba_relevance_weight,
        state.alibaba_opportunity_weight,
        state.alibaba_reputation_weight,
    ) == (60, 25, 15)
    state.apply_ranking_preset_more_opportunity()
    assert (
        state.alibaba_relevance_weight,
        state.alibaba_opportunity_weight,
        state.alibaba_reputation_weight,
    ) == (35, 45, 20)
    state.apply_ranking_preset_more_reputation()
    assert (
        state.alibaba_relevance_weight,
        state.alibaba_opportunity_weight,
        state.alibaba_reputation_weight,
    ) == (35, 20, 45)
    assert state.alibaba_weights_total == 100
    state.clear_alibaba_filters()
    assert (
        state.alibaba_relevance_weight,
        state.alibaba_opportunity_weight,
        state.alibaba_reputation_weight,
    ) == (50, 30, 20)


def test_state_invalid_total_keeps_last_valid_weights_applied() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.apply_ranking_preset_balanced()
    state.set_alibaba_relevance_weight(70)
    assert state.alibaba_weights_total == 130
    assert state.alibaba_weights_valid is False
    assert state.alibaba_weights_error != ""
    assert (
        state.alibaba_applied_relevance_weight,
        state.alibaba_applied_opportunity_weight,
        state.alibaba_applied_reputation_weight,
    ) == (40, 30, 30)
    state.set_alibaba_opportunity_weight(20)
    state.set_alibaba_reputation_weight(10)
    assert state.alibaba_weights_total == 100
    assert state.alibaba_weights_valid is True
    assert (
        state.alibaba_applied_relevance_weight,
        state.alibaba_applied_opportunity_weight,
        state.alibaba_applied_reputation_weight,
    ) == (70, 20, 10)


def test_state_weight_setters_clamp_and_stay_local() -> None:
    from bera_price_tracker.gui.state import TrackerState

    state = TrackerState()
    state.set_alibaba_relevance_weight([80])
    assert state.alibaba_relevance_weight == 80
    state.set_alibaba_relevance_weight("140")
    assert state.alibaba_relevance_weight == 100
    state.set_alibaba_relevance_weight(-10)
    assert state.alibaba_relevance_weight == 0
    state.set_alibaba_relevance_weight("no-numeric")
    assert state.alibaba_relevance_weight == 50
