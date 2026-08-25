"""Cross-marketplace comparison view-model. Display-only; no matching AI."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from bera_price_tracker.gui.images import safe_public_image_url

UI_SUCCESS = "SUCCESS"

ANALYSIS_UNAVAILABLE = "Análisis no disponible"
MATCH_HIGH = "Alta coincidencia"
MATCH_MEDIUM = "Coincidencia media"
MATCH_COMPARABLE = "Comparable"


def match_label(relevance_value: object, *, has_listing: bool) -> str:
    """Deterministic labels from existing relevance scores only."""

    if not has_listing:
        return ""
    score = 0
    if isinstance(relevance_value, bool):
        score = 0
    elif isinstance(relevance_value, int):
        score = relevance_value
    elif isinstance(relevance_value, str):
        try:
            score = int(relevance_value)
        except ValueError:
            score = 0
    if score >= 80:
        return MATCH_HIGH
    if score >= 60:
        return MATCH_MEDIUM
    return MATCH_COMPARABLE


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _attr(row: object, name: str, default: str = "") -> str:
    if row is None:
        return default
    if isinstance(row, Mapping):
        return _text(row.get(name, default)) or default
    return _text(getattr(row, name, default)) or default


def _int_attr(row: object, name: str) -> int:
    raw = getattr(row, name, None) if not isinstance(row, Mapping) else row.get(name)
    try:
        return int(raw) if raw is not None and not isinstance(raw, bool) else 0
    except (TypeError, ValueError):
        return 0


def _best_by_relevance(rows: Sequence[Any]) -> Any | None:
    if not rows:
        return None
    return max(rows, key=lambda item: _int_attr(item, "relevance_value"))


def _published_range(row: Any) -> str:
    if row is None:
        return ""
    minimum = _attr(row, "price_min")
    maximum = _attr(row, "price_max")
    if minimum and maximum and minimum != maximum:
        currency = _attr(row, "currency")
        prefix = f"{currency} " if currency else ""
        return f"{prefix}{minimum} – {maximum}"
    return ""


def _alibaba_cell(row: Any) -> dict[str, str | bool]:
    if row is None:
        return {
            "alibaba_has_listing": False,
            "alibaba_image_url": "",
            "alibaba_title": "",
            "alibaba_price": "",
            "alibaba_range": "",
            "alibaba_moq": "",
            "alibaba_supplier": "",
            "alibaba_relevance": "",
            "alibaba_match_label": "",
            "alibaba_url": "",
        }
    relevance_value = _int_attr(row, "relevance_value")
    moq = _attr(row, "moq")
    return {
        "alibaba_has_listing": True,
        "alibaba_image_url": safe_public_image_url(_attr(row, "image_url")),
        "alibaba_title": _attr(row, "title"),
        "alibaba_price": _attr(row, "price"),
        "alibaba_range": _published_range(row),
        "alibaba_moq": f"MOQ: {moq}" if moq else "",
        "alibaba_supplier": _attr(row, "supplier_name"),
        "alibaba_relevance": _attr(row, "relevance"),
        "alibaba_match_label": match_label(relevance_value, has_listing=True),
        "alibaba_url": _attr(row, "url"),
    }


def _facebook_cell(row: Any) -> dict[str, str | bool]:
    if row is None:
        return {
            "facebook_has_listing": False,
            "facebook_image_url": "",
            "facebook_title": "",
            "facebook_price": "",
            "facebook_source_note": "",
            "facebook_usd_note": "",
            "facebook_location": "",
            "facebook_relevance": "",
            "facebook_match_label": "",
            "facebook_url": "",
        }
    relevance_value = _int_attr(row, "relevance_value")
    usd_price = _attr(row, "usd_price")
    provenance = _attr(row, "usd_provenance")
    usd_note = usd_price
    if provenance:
        usd_note = f"{usd_price} · {provenance}" if usd_price else provenance
    return {
        "facebook_has_listing": True,
        "facebook_image_url": safe_public_image_url(_attr(row, "image_url")),
        "facebook_title": _attr(row, "title"),
        "facebook_price": usd_price or _attr(row, "price"),
        "facebook_source_note": _attr(row, "source_price_note") or _attr(row, "formatted_price"),
        "facebook_usd_note": usd_note,
        "facebook_location": _attr(row, "location"),
        "facebook_relevance": _attr(row, "relevance"),
        "facebook_match_label": match_label(relevance_value, has_listing=True),
        "facebook_url": _attr(row, "permalink"),
    }


def _ml_cell(row: Any) -> dict[str, str | bool]:
    if row is None:
        return {
            "ml_has_listing": False,
            "ml_image_url": "",
            "ml_title": "",
            "ml_price": "",
            "ml_condition": "",
            "ml_seller": "",
            "ml_relevance": "",
            "ml_match_label": "",
            "ml_url": "",
        }
    relevance_value = _int_attr(row, "relevance_value")
    condition = _attr(row, "condition")
    seller = _attr(row, "seller_name")
    return {
        "ml_has_listing": True,
        "ml_image_url": safe_public_image_url(_attr(row, "thumbnail_url")),
        "ml_title": _attr(row, "title"),
        "ml_price": _attr(row, "price"),
        "ml_condition": "" if condition == "—" else condition,
        "ml_seller": "" if seller == "—" else seller,
        "ml_relevance": _attr(row, "relevance"),
        "ml_match_label": match_label(relevance_value, has_listing=True),
        "ml_url": _attr(row, "permalink"),
    }


def build_analysis(
    *,
    alibaba_row: Any,
    ml_comparison: Mapping[str, object] | None = None,
    landed: Mapping[str, object] | None = None,
) -> dict[str, str | bool]:
    """Use existing Alibaba opportunity / landed context. Never invent a score."""

    details: list[str] = []
    heading = ANALYSIS_UNAVAILABLE
    if alibaba_row is not None:
        score = _attr(alibaba_row, "score")
        label = _attr(alibaba_row, "score_label")
        if score:
            heading = "Oportunidad Alibaba"
            details.append(score if not label else f"{score} · {label}")
    comparison = dict(ml_comparison or {})
    if comparison.get("comparable") == "1":
        if heading == ANALYSIS_UNAVAILABLE:
            heading = "Costo puesto"
        landed_price = _text(comparison.get("landed"))
        typical = _text(comparison.get("typical_price"))
        typical_profit = _text(comparison.get("typical_profit"))
        if landed_price:
            details.append(f"Costo puesto / u: {landed_price}")
        if typical:
            details.append(f"Típico ML: {typical}")
        if typical_profit:
            details.append(f"Margen típico: {typical_profit}")
    elif landed:
        unit = _text(
            landed.get("unit_landed") or landed.get("landed_per_unit") or landed.get("unit")
        )
        if unit:
            if heading == ANALYSIS_UNAVAILABLE:
                heading = "Costo puesto"
            details.append(f"Costo puesto / u: {unit}")
    if heading == ANALYSIS_UNAVAILABLE:
        return {
            "analysis_available": False,
            "analysis_heading": ANALYSIS_UNAVAILABLE,
            "analysis_detail": "",
        }
    return {
        "analysis_available": True,
        "analysis_heading": heading,
        "analysis_detail": " · ".join(details),
    }


def _empty_row() -> dict[str, str | bool]:
    row: dict[str, str | bool] = {
        "product_title": "",
        "product_image_url": "",
        "product_subtitle": "Producto comparable en distintas plataformas",
        "product_id": "",
    }
    row.update(_alibaba_cell(None))
    row.update(_facebook_cell(None))
    row.update(_ml_cell(None))
    row.update(build_analysis(alibaba_row=None))
    return row


def page_heading(
    *,
    alibaba_query: str = "",
    facebook_query: str = "",
    ml_query: str = "",
    h0019_query: str = "",
    alibaba_status: str = "",
    facebook_status: str = "",
    ml_status: str = "",
    h0019_status: str = "",
    workspace_view: str = "",
) -> str:
    """Show a real search query only when a search has actually run."""

    if alibaba_status in {UI_SUCCESS, "EMPTY", "ERROR"} and alibaba_query.strip():
        return f"Resultados para: {alibaba_query.strip()}"
    if facebook_status in {UI_SUCCESS, "EMPTY", "ERROR"} and facebook_query.strip():
        return f"Resultados para: {facebook_query.strip()}"
    if ml_status in {UI_SUCCESS, "EMPTY", "ERROR"} and ml_query.strip():
        return f"Resultados para: {ml_query.strip()}"
    if h0019_status in {UI_SUCCESS, "EMPTY", "ERROR"} and h0019_query.strip():
        return f"Resultados para: {h0019_query.strip()}"
    idle_titles = {
        "dashboard": "Inteligencia de compras e importación",
        "searches": "Búsquedas Alibaba",
        "products": "Facebook Marketplace Venezuela",
        "comparisons": "Comparaciones de mercado",
        "tracking": "Seguimiento Alibaba",
        "import": "Importación y costo puesto",
        "tools": "Facebook H0019",
        "settings": "Ranking y filtros",
    }
    return idle_titles.get(workspace_view, "Inteligencia de compras e importación")


def build_comparison_rows(
    *,
    alibaba_rows: Sequence[Any] = (),
    facebook_rows: Sequence[Any] = (),
    ml_rows: Sequence[Any] = (),
    alibaba_status: str = "",
    facebook_status: str = "",
    ml_status: str = "",
    alibaba_context: Mapping[str, object] | None = None,
    facebook_association_id: str = "",
    ml_association_id: str = "",
    ml_comparison: Mapping[str, object] | None = None,
    landed: Mapping[str, object] | None = None,
    fallback_title: str = "",
) -> list[dict[str, str | bool]]:
    """One honest row per Alibaba product; FB/ML fill only the associated product."""

    facebook_best = _best_by_relevance(facebook_rows) if facebook_status == UI_SUCCESS else None
    ml_best = _best_by_relevance(ml_rows) if ml_status == UI_SUCCESS else None
    context = dict(alibaba_context or {})
    context_id = _text(context.get("external_id"))
    context_title = _text(context.get("title"))

    rows: list[dict[str, str | bool]] = []
    if alibaba_status == UI_SUCCESS and alibaba_rows:
        for item in alibaba_rows:
            product_id = _attr(item, "product_id")
            facebook_row = (
                facebook_best
                if product_id and facebook_association_id and product_id == facebook_association_id
                else None
            )
            ml_row = (
                ml_best
                if product_id and ml_association_id and product_id == ml_association_id
                else None
            )
            row = _empty_row()
            row["product_title"] = _attr(item, "title") or context_title or fallback_title
            row["product_image_url"] = safe_public_image_url(_attr(item, "image_url"))
            row["product_id"] = product_id
            row["product_subtitle"] = _attr(item, "supplier_name") or row["product_subtitle"]
            row.update(_alibaba_cell(item))
            row.update(_facebook_cell(facebook_row))
            row.update(_ml_cell(ml_row))
            row.update(
                build_analysis(
                    alibaba_row=item,
                    ml_comparison=ml_comparison if ml_row is not None else None,
                    landed=landed if product_id and product_id == context_id else None,
                )
            )
            rows.append(row)
        return rows

    if facebook_best is not None or ml_best is not None:
        row = _empty_row()
        title = context_title or fallback_title
        if not title and facebook_best is not None:
            title = _attr(facebook_best, "title")
        if not title and ml_best is not None:
            title = _attr(ml_best, "title")
        row["product_title"] = title
        row["product_id"] = context_id
        associated_alibaba = None
        if context_id:
            for item in alibaba_rows:
                if _attr(item, "product_id") == context_id:
                    associated_alibaba = item
                    break
        row.update(_alibaba_cell(associated_alibaba))
        row.update(_facebook_cell(facebook_best))
        row.update(_ml_cell(ml_best))
        if associated_alibaba is not None:
            row["product_image_url"] = safe_public_image_url(_attr(associated_alibaba, "image_url"))
        row.update(
            build_analysis(
                alibaba_row=associated_alibaba,
                ml_comparison=ml_comparison,
                landed=landed,
            )
        )
        return [row]
    return []
