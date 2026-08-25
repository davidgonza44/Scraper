"""View-models for the three marketplace summary cards. Display-only."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from bera_price_tracker.gui.brands import PLATFORM_ALIBABA, PLATFORM_FACEBOOK, PLATFORM_ML
from bera_price_tracker.gui.search_session import seller_rating

UI_SUCCESS = "SUCCESS"
UI_LOADING = "LOADING"
UI_ERROR = "ERROR"
EMPTY_METRIC = "—"


def _status_overlay(card: dict[str, Any], ui_status: str) -> dict[str, Any] | None:
    if ui_status == UI_LOADING:
        card["status"] = "loading"
        card["status_label"] = "Buscando..."
        return card
    if ui_status == UI_ERROR:
        card["status"] = "error"
        card["status_label"] = "Error"
        return card
    return None


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _metric(mapping: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        text = _text(mapping.get(key))
        if text and text not in {"unavailable", "—"}:
            return text
    return EMPTY_METRIC


def empty_marketplace_card(platform: str, platform_id: str) -> dict[str, str | int | bool]:
    return {
        "platform": platform,
        "platform_id": platform_id,
        "status": "empty",
        "status_label": "Sin búsqueda",
        "result_count": "0",
        "minimum": EMPTY_METRIC,
        "median": EMPTY_METRIC,
        "average": EMPTY_METRIC,
        "maximum": EMPTY_METRIC,
        "p25": EMPTY_METRIC,
        "p75": EMPTY_METRIC,
        "range": EMPTY_METRIC,
        "currency": "",
        "basis": "",
        "meta_one": "",
        "meta_two": "",
        "note": "",
        "rating_available": False,
        "rating_value": "",
        "rating_label": "Sin calificación",
        "rating_filled": 0,
    }


def _range(minimum: object, maximum: object) -> str:
    min_text = str(minimum)
    max_text = str(maximum)
    if min_text == EMPTY_METRIC and max_text == EMPTY_METRIC:
        return EMPTY_METRIC
    if min_text == EMPTY_METRIC:
        return max_text
    if max_text == EMPTY_METRIC:
        return min_text
    if min_text == max_text:
        return min_text
    return f"{min_text} – {max_text}"


def alibaba_summary_card(
    *,
    ui_status: str,
    summary: Mapping[str, object],
    rows: Sequence[Any] = (),
) -> dict[str, Any]:
    card = empty_marketplace_card("Alibaba", PLATFORM_ALIBABA)
    overlay = _status_overlay(card, ui_status)
    if overlay is not None:
        return overlay
    if ui_status != UI_SUCCESS:
        return card
    card["status"] = "ready"
    card["status_label"] = "Resultados"
    card["result_count"] = (
        _metric(summary, "resultados")
        if _metric(summary, "resultados") != EMPTY_METRIC
        else str(len(rows))
    )
    card["minimum"] = _metric(summary, "minimo")
    card["median"] = _metric(summary, "mediana")
    card["average"] = _metric(summary, "promedio")
    card["maximum"] = _metric(summary, "maximo")
    card["p25"] = _metric(summary, "p25")
    card["p75"] = _metric(summary, "p75")
    card["currency"] = _text(summary.get("currency")) or "USD"
    card["range"] = _metric(summary, "rango_tipico")
    if card["range"] == EMPTY_METRIC:
        card["range"] = _range(card["minimum"], card["maximum"])
    supplier = ""
    moq = ""
    review_score = ""
    if rows:
        first = rows[0]
        supplier = _text(
            getattr(first, "supplier_name", None)
            or (first.get("supplier_name") if isinstance(first, Mapping) else "")
        )
        moq = _text(
            getattr(first, "moq", None) or (first.get("moq") if isinstance(first, Mapping) else "")
        )
        review_score = _text(
            getattr(first, "review_score", None)
            or (first.get("review_score") if isinstance(first, Mapping) else "")
        )
    if moq:
        card["meta_one"] = f"MOQ típico: {moq}"
    if supplier:
        card["meta_two"] = f"Mejor proveedor: {supplier}"
    rating = seller_rating(review_score)
    card["rating_available"] = bool(rating["available"])
    card["rating_value"] = str(rating["value"])
    card["rating_label"] = str(rating["label"])
    card["rating_filled"] = int(rating["filled"])
    return card


def facebook_summary_card(
    *,
    ui_status: str,
    summary: Mapping[str, object],
    statistics: Sequence[Any] = (),
    rows: Sequence[Any] = (),
) -> dict[str, Any]:
    card = empty_marketplace_card("Facebook Marketplace", PLATFORM_FACEBOOK)
    overlay = _status_overlay(card, ui_status)
    if overlay is not None:
        return overlay
    if ui_status != UI_SUCCESS:
        return card
    card["status"] = "ready"
    card["status_label"] = "Con precio"
    usable = _metric(summary, "usable")
    card["result_count"] = usable if usable != EMPTY_METRIC else str(len(rows))
    first_stats = statistics[0] if statistics else None
    card["minimum"] = _metric(
        first_stats if isinstance(first_stats, Mapping) else {},
        "minimum",
    )
    if first_stats is not None and not isinstance(first_stats, Mapping):
        card["minimum"] = _text(getattr(first_stats, "minimum", "")) or EMPTY_METRIC
        card["median"] = _text(getattr(first_stats, "median", "")) or EMPTY_METRIC
        card["average"] = _text(getattr(first_stats, "average", "")) or EMPTY_METRIC
        card["maximum"] = _text(getattr(first_stats, "maximum", "")) or EMPTY_METRIC
        label = _text(getattr(first_stats, "label", ""))
    else:
        stats = first_stats if isinstance(first_stats, Mapping) else {}
        card["minimum"] = _metric(stats, "minimum")
        card["median"] = _metric(stats, "median")
        card["average"] = _metric(stats, "average")
        card["maximum"] = _metric(stats, "maximum")
        label = _text(stats.get("label"))
    if card["minimum"] in {"unavailable"}:
        card["minimum"] = EMPTY_METRIC
    if card["median"] in {"unavailable"}:
        card["median"] = EMPTY_METRIC
    if card["average"] in {"unavailable"}:
        card["average"] = EMPTY_METRIC
    if card["maximum"] in {"unavailable"}:
        card["maximum"] = EMPTY_METRIC
    if label:
        card["meta_one"] = label
    location = ""
    if rows:
        first_row = rows[0]
        location = _text(
            getattr(first_row, "location", None)
            or (first_row.get("location") if isinstance(first_row, Mapping) else "")
        )
    if location and location != "—":
        card["meta_two"] = location
    note = _text(summary.get("note"))
    if note:
        card["note"] = note
    if first_stats is not None and not isinstance(first_stats, Mapping):
        card["currency"] = _text(getattr(first_stats, "currency", ""))
        card["basis"] = _text(getattr(first_stats, "basis", ""))
        card["p25"] = _text(getattr(first_stats, "p25", "")) or EMPTY_METRIC
        card["p75"] = _text(getattr(first_stats, "p75", "")) or EMPTY_METRIC
    elif isinstance(first_stats, Mapping):
        card["currency"] = _text(first_stats.get("currency"))
        card["basis"] = _text(first_stats.get("basis"))
        card["p25"] = _metric(first_stats, "p25")
        card["p75"] = _metric(first_stats, "p75")
    card["range"] = _range(card["minimum"], card["maximum"])
    return card


def mercadolibre_summary_card(
    *,
    ui_status: str,
    summary: Mapping[str, object],
    rows: Sequence[Any] = (),
) -> dict[str, Any]:
    card = empty_marketplace_card("Mercado Libre", PLATFORM_ML)
    overlay = _status_overlay(card, ui_status)
    if overlay is not None:
        return overlay
    if ui_status != UI_SUCCESS:
        return card
    card["status"] = "ready"
    card["status_label"] = "Comparables"
    count = _metric(summary, "comparable_count")
    if count == EMPTY_METRIC:
        count = _metric(summary, "comparables")
    card["result_count"] = count if count != EMPTY_METRIC else str(len(rows))
    card["minimum"] = _metric(summary, "minimo")
    card["median"] = _metric(summary, "mediana")
    card["average"] = _metric(summary, "precio_tipico")
    card["maximum"] = _metric(summary, "maximo")
    card["p25"] = _metric(summary, "p25")
    card["p75"] = _metric(summary, "p75")
    card["currency"] = _text(summary.get("currency"))
    card["range"] = _range(card["minimum"], card["maximum"])
    if rows:
        first = rows[0]
        condition = _text(
            getattr(first, "condition", None)
            or (first.get("condition") if isinstance(first, Mapping) else "")
        )
        seller = _text(
            getattr(first, "seller_name", None)
            or (first.get("seller_name") if isinstance(first, Mapping) else "")
        )
        if condition and condition != "—":
            card["meta_one"] = condition
        if seller and seller != "—":
            card["meta_two"] = f"Mejor vendedor: {seller}"
    return card


def build_marketplace_summaries(
    *,
    alibaba_ui_status: str,
    alibaba_summary: Mapping[str, object],
    alibaba_rows: Sequence[Any] = (),
    facebook_ui_status: str,
    facebook_summary: Mapping[str, object],
    facebook_statistics: Sequence[Any] = (),
    facebook_rows: Sequence[Any] = (),
    ml_ui_status: str,
    ml_summary: Mapping[str, object],
    ml_rows: Sequence[Any] = (),
) -> list[dict[str, Any]]:
    return [
        alibaba_summary_card(
            ui_status=alibaba_ui_status, summary=alibaba_summary, rows=alibaba_rows
        ),
        facebook_summary_card(
            ui_status=facebook_ui_status,
            summary=facebook_summary,
            statistics=facebook_statistics,
            rows=facebook_rows,
        ),
        mercadolibre_summary_card(ui_status=ml_ui_status, summary=ml_summary, rows=ml_rows),
    ]
