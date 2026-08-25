"""Local, in-memory view helpers for the Alibaba tab. Pure functions, no requests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from math import isqrt
from typing import cast

from bera_price_tracker.application.alibaba_ranking import (
    DEFAULT_WEIGHTS,
    RankingWeights,
    calculate_alibaba_ranking,
    format_ranking_display,
    format_ranking_tooltip,
    is_low_match,
)
from bera_price_tracker.application.alibaba_reputation import LABEL_INSUFFICIENT

SORT_ORIGINAL = "original"
SORT_PRICE_ASC = "price_asc"
SORT_PRICE_DESC = "price_desc"
SORT_SCORE_DESC = "score_desc"
SORT_RELEVANCE_DESC = "relevance_desc"
SORT_RANKING_DESC = "ranking_desc"
SORT_REPUTATION_DESC = "reputation_desc"
CHART_SCOPE_ALL = "all"
CHART_SCOPE_TYPICAL = "typical"

FILTER_MIN_INVALID = "Precio mínimo inválido."
FILTER_MAX_INVALID = "Precio máximo inválido."
FILTER_RANGE_INVALID = "El precio mínimo no puede ser mayor que el máximo."

_CENTS = Decimal("0.01")
_HUNDRED = Decimal("100")
_MAX_HISTOGRAM_BINS = 6


def _field(row: object, name: str) -> object:
    if isinstance(row, Mapping):
        return cast(Mapping[str, object], row).get(name)
    return getattr(row, name, None)


def parse_decimal_text(text: object) -> Decimal | None:
    """Parse a stored Decimal string. Blank or invalid text means "no value"."""

    if not isinstance(text, str) or not text.strip():
        return None
    try:
        value = Decimal(text.strip())
    except InvalidOperation:
        return None
    if not value.is_finite():
        return None
    return value


def parse_price_input(text: object) -> tuple[Decimal | None, bool]:
    """Return (bound, is_valid). Empty input is a valid "no bound"."""

    if text is None:
        return None, True
    if not isinstance(text, str):
        return None, False
    normalized = text.strip().replace("$", "").replace(",", ".")
    if not normalized:
        return None, True
    try:
        value = Decimal(normalized)
    except InvalidOperation:
        return None, False
    if not value.is_finite() or value < 0:
        return None, False
    return value, True


def validate_price_filters(
    min_text: object, max_text: object
) -> tuple[Decimal | None, Decimal | None, str]:
    """Parse both bounds. On any problem return (None, None, user message)."""

    minimum, min_ok = parse_price_input(min_text)
    maximum, max_ok = parse_price_input(max_text)
    if not min_ok:
        return None, None, FILTER_MIN_INVALID
    if not max_ok:
        return None, None, FILTER_MAX_INVALID
    if minimum is not None and maximum is not None and minimum > maximum:
        return None, None, FILTER_RANGE_INVALID
    return minimum, maximum, ""


def row_representative(row: object) -> Decimal | None:
    value = parse_decimal_text(_field(row, "representative"))
    if value is None or value <= 0:
        return None
    return value


def row_is_outlier(row: object) -> bool:
    return bool(_field(row, "is_outlier"))


def _int_field(row: object, name: str) -> int:
    value = _field(row, name)
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def row_score(row: object) -> int:
    return _int_field(row, "score_value")


def row_relevance(row: object) -> int:
    return _int_field(row, "relevance_value")


def row_ranking(row: object) -> int:
    return _int_field(row, "ranking_value")


def row_reputation_available(row: object) -> bool:
    return bool(_field(row, "reputation_available"))


def row_reputation(row: object) -> int | None:
    if not row_reputation_available(row):
        return None
    return _int_field(row, "reputation_value")


def _reputation_sort_key(row: object) -> int:
    value = row_reputation(row)
    return -1 if value is None else value


def _copy_with_fields[RowT](row: RowT, fields: dict[str, object]) -> RowT:
    if isinstance(row, Mapping):
        copy = dict(cast(Mapping[str, object], row))
        copy.update(fields)
        return cast(RowT, copy)
    copier = getattr(row, "model_copy", None)
    if callable(copier):
        return cast(RowT, copier(update=fields))
    # Older pydantic v1 models exposed copy(update=...). Keep the fallback so
    # ranking fields are not dropped if a legacy row type appears.
    legacy_copier = getattr(row, "copy", None)
    if callable(legacy_copier):
        try:
            return cast(RowT, legacy_copier(update=fields))
        except TypeError:
            return row
    return row


def annotate_ranking[RowT](
    rows: Sequence[RowT], weights: RankingWeights = DEFAULT_WEIGHTS
) -> list[RowT]:
    """Attach ranking fields to copies. The original sequence is never mutated.

    Reputation joins the blend only when the row has a valid reputation score;
    otherwise its weight is redistributed (absence is not a score of 0).
    """

    annotated: list[RowT] = []
    for row in rows:
        result = calculate_alibaba_ranking(
            row_score(row),
            row_relevance(row),
            row_reputation(row),
            weights,
        )
        annotated.append(
            _copy_with_fields(
                row,
                {
                    "ranking_value": result.ranking_score,
                    "ranking": format_ranking_display(result.ranking_score),
                    "ranking_low_match": is_low_match(row_relevance(row)),
                    "ranking_tooltip": format_ranking_tooltip(result),
                    "ranking_reputation_used": result.reputation_used,
                },
            )
        )
    return annotated


def select_top_ranked[RowT](rows: Sequence[RowT], *, limit: int = 3) -> list[RowT]:
    return sorted(rows, key=row_ranking, reverse=True)[: max(0, limit)]


def top_result_cards(rows: Sequence[object], *, limit: int = 3) -> list[dict[str, str]]:
    cards: list[dict[str, str]] = []
    for index, row in enumerate(select_top_ranked(rows, limit=limit), start=1):
        cards.append(
            {
                "place": str(index),
                "title": str(_field(row, "title") or ""),
                "price": str(_field(row, "price") or ""),
                "ranking": f"Ranking {row_ranking(row)}",
                "relevance": f"Relevancia {row_relevance(row)}",
                "opportunity": f"Oportunidad {row_score(row)}",
                "reputation": (
                    f"Reputación {row_reputation(row)}"
                    if row_reputation(row) is not None
                    else f"Reputación: {LABEL_INSUFFICIENT}"
                ),
            }
        )
    return cards


def rows_representatives(rows: Sequence[object]) -> list[Decimal]:
    values: list[Decimal] = []
    for row in rows:
        value = row_representative(row)
        if value is not None:
            values.append(value)
    return values


def apply_table_view[RowT](
    rows: Sequence[RowT],
    *,
    sort: str = SORT_ORIGINAL,
    minimum: Decimal | None = None,
    maximum: Decimal | None = None,
    hide_outliers: bool = False,
    min_relevance: int = 0,
    min_reputation: int = 0,
    weights: RankingWeights = DEFAULT_WEIGHTS,
) -> list[RowT]:
    """Derive the visible table rows. The original sequence is never mutated."""

    visible = annotate_ranking(rows, weights)
    if min_relevance > 0:
        visible = [row for row in visible if row_relevance(row) >= min_relevance]
    if min_reputation > 0:
        visible = [
            row
            for row in visible
            if row_reputation(row) is not None and cast(int, row_reputation(row)) >= min_reputation
        ]
    if minimum is not None or maximum is not None:
        bounded: list[RowT] = []
        for row in visible:
            representative = row_representative(row)
            if representative is None:
                continue
            if minimum is not None and representative < minimum:
                continue
            if maximum is not None and representative > maximum:
                continue
            bounded.append(row)
        visible = bounded
    if hide_outliers:
        visible = [row for row in visible if not row_is_outlier(row)]
    if sort in (SORT_PRICE_ASC, SORT_PRICE_DESC):
        priced = [row for row in visible if row_representative(row) is not None]
        unpriced = [row for row in visible if row_representative(row) is None]
        priced.sort(
            key=lambda row: cast(Decimal, row_representative(row)),
            reverse=sort == SORT_PRICE_DESC,
        )
        visible = priced + unpriced
    elif sort == SORT_SCORE_DESC:
        visible = sorted(visible, key=row_score, reverse=True)
    elif sort == SORT_RELEVANCE_DESC:
        visible = sorted(visible, key=row_relevance, reverse=True)
    elif sort == SORT_RANKING_DESC:
        visible = sorted(visible, key=row_ranking, reverse=True)
    elif sort == SORT_REPUTATION_DESC:
        visible = sorted(visible, key=_reputation_sort_key, reverse=True)
    return visible


def showing_counter(visible: int, total: int) -> str:
    return f"Mostrando {visible} de {total} productos"


def select_chart_values(
    values: Sequence[Decimal],
    scope: str,
    lower_fence: Decimal | None,
    upper_fence: Decimal | None,
) -> list[Decimal]:
    """Chart-only scope. ``typical`` keeps values inside the Tukey fences."""

    if scope != CHART_SCOPE_TYPICAL or lower_fence is None or upper_fence is None:
        return list(values)
    return [value for value in values if lower_fence <= value <= upper_fence]


def _money_label(value: Decimal) -> str:
    return f"${value.quantize(_CENTS, rounding=ROUND_HALF_EVEN)}"


def build_histogram(values: Sequence[Decimal]) -> list[dict[str, str]]:
    """Bin representative prices into dataset-driven ranges for a CSS bar chart."""

    prices = sorted(value for value in values if value.is_finite())
    if not prices:
        return []
    low = prices[0]
    high = prices[-1]
    if low == high:
        return [{"label": _money_label(low), "count": str(len(prices)), "width": "100%"}]
    bin_count = max(2, min(_MAX_HISTOGRAM_BINS, isqrt(len(prices)) + 1))
    width = (high - low) / Decimal(bin_count)
    counts = [0] * bin_count
    for price in prices:
        index = int((price - low) / width)
        if index >= bin_count:
            index = bin_count - 1
        counts[index] += 1
    max_count = max(counts)
    bins: list[dict[str, str]] = []
    for position, count in enumerate(counts):
        bin_low = low + width * Decimal(position)
        bin_high = low + width * Decimal(position + 1)
        percent = (Decimal(count) / Decimal(max_count) * _HUNDRED).quantize(
            _CENTS, rounding=ROUND_HALF_EVEN
        )
        bins.append(
            {
                "label": f"{_money_label(bin_low)}–{_money_label(bin_high)}",
                "count": str(count),
                "width": f"{percent}%",
            }
        )
    return bins


def boxplot_geometry(
    minimum: Decimal | None,
    p25: Decimal | None,
    median: Decimal | None,
    p75: Decimal | None,
    maximum: Decimal | None,
) -> dict[str, str]:
    """CSS positions (percent strings) for a simple horizontal box summary."""

    unavailable = {"available": "", "box_left": "0%", "box_width": "0%", "median_left": "0%"}
    values = (minimum, p25, median, p75, maximum)
    if any(value is None for value in values):
        return unavailable
    low = cast(Decimal, minimum)
    high = cast(Decimal, maximum)
    span = high - low

    def percent(value: Decimal) -> Decimal:
        if span == 0:
            return Decimal("50.00")
        return ((value - low) / span * _HUNDRED).quantize(_CENTS, rounding=ROUND_HALF_EVEN)

    left = percent(cast(Decimal, p25))
    right = percent(cast(Decimal, p75))
    return {
        "available": "1",
        "box_left": f"{left}%",
        "box_width": f"{right - left}%",
        "median_left": f"{percent(cast(Decimal, median))}%",
    }


__all__ = [
    "CHART_SCOPE_ALL",
    "CHART_SCOPE_TYPICAL",
    "FILTER_MAX_INVALID",
    "FILTER_MIN_INVALID",
    "FILTER_RANGE_INVALID",
    "SORT_ORIGINAL",
    "SORT_PRICE_ASC",
    "SORT_PRICE_DESC",
    "SORT_RANKING_DESC",
    "SORT_REPUTATION_DESC",
    "SORT_RELEVANCE_DESC",
    "SORT_SCORE_DESC",
    "annotate_ranking",
    "apply_table_view",
    "boxplot_geometry",
    "build_histogram",
    "parse_decimal_text",
    "parse_price_input",
    "row_is_outlier",
    "row_ranking",
    "row_relevance",
    "row_reputation",
    "row_reputation_available",
    "row_representative",
    "row_score",
    "rows_representatives",
    "select_chart_values",
    "select_top_ranked",
    "showing_counter",
    "top_result_cards",
    "validate_price_filters",
]
