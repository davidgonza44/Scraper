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


_RESULT_STATUSES = frozenset({UI_SUCCESS, "EMPTY", "ERROR"})

IDLE_HEADINGS = {
    "dashboard": "Inteligencia de compras e importación",
    "searches": "Búsquedas Alibaba",
    "products": "Facebook Marketplace Venezuela",
    "comparisons": "Comparaciones de mercado",
    "tracking": "Seguimiento Alibaba",
    "import": "Importación y costo puesto",
    "tools": "Facebook H0019",
    "settings": "Ranking y filtros",
}


def shared_alibaba_association(
    facebook_association_id: object = "",
    ml_association_id: object = "",
    context_id: object = "",
) -> str:
    """Return the Alibaba id only when FB, ML, and context all name the same product."""

    facebook_id = _text(facebook_association_id)
    ml_id = _text(ml_association_id)
    selected_id = _text(context_id)
    if not facebook_id or not ml_id or not selected_id:
        return ""
    if facebook_id == ml_id == selected_id:
        return selected_id
    return ""


def _results_heading(query: object, status: object) -> str:
    text = _text(query)
    if _text(status) in _RESULT_STATUSES and text:
        return f"Resultados para: {text}"
    return ""


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
    facebook_association_id: str = "",
    ml_association_id: str = "",
    context_id: str = "",
    context_title: str = "",
) -> str:
    """Workspace-first heading. Another marketplace's SUCCESS never leaks in."""

    view = _text(workspace_view) or "dashboard"
    if view == "searches":
        return _results_heading(alibaba_query, alibaba_status) or IDLE_HEADINGS["searches"]
    if view == "products":
        return _results_heading(facebook_query, facebook_status) or IDLE_HEADINGS["products"]
    if view == "comparisons":
        heading = _results_heading(ml_query, ml_status)
        if heading:
            return heading
        if _text(context_title) and _text(context_id):
            return f"Resultados para: {_text(context_title)}"
        return IDLE_HEADINGS["comparisons"]
    if view == "tools":
        return _results_heading(h0019_query, h0019_status) or IDLE_HEADINGS["tools"]
    if view == "tracking":
        title = _text(context_title)
        return title or IDLE_HEADINGS["tracking"]
    if view == "import":
        title = _text(context_title)
        return title or IDLE_HEADINGS["import"]
    if view == "settings":
        return IDLE_HEADINGS["settings"]
    shared = shared_alibaba_association(facebook_association_id, ml_association_id, context_id)
    if view == "dashboard" and shared and _text(context_title):
        return f"Resultados para: {_text(context_title)}"
    return IDLE_HEADINGS.get(view, IDLE_HEADINGS["dashboard"])


def _lookup_alibaba(rows: Sequence[Any], product_id: str) -> Any | None:
    if not product_id:
        return None
    for item in rows:
        if _attr(item, "product_id") == product_id:
            return item
    return None


def _fill_product_row(
    *,
    alibaba_row: Any | None,
    facebook_row: Any | None,
    ml_row: Any | None,
    product_id: str,
    product_title: str,
    product_subtitle: str = "",
    ml_comparison: Mapping[str, object] | None = None,
    landed: Mapping[str, object] | None = None,
) -> dict[str, str | bool]:
    row = _empty_row()
    row["product_id"] = product_id
    row["product_title"] = product_title
    if product_subtitle:
        row["product_subtitle"] = product_subtitle
    if alibaba_row is not None:
        row["product_image_url"] = safe_public_image_url(_attr(alibaba_row, "image_url"))
        if not product_subtitle:
            row["product_subtitle"] = _attr(alibaba_row, "supplier_name") or row["product_subtitle"]
    row.update(_alibaba_cell(alibaba_row))
    row.update(_facebook_cell(facebook_row))
    row.update(_ml_cell(ml_row))
    row.update(
        build_analysis(
            alibaba_row=alibaba_row,
            ml_comparison=ml_comparison if ml_row is not None else None,
            landed=landed,
        )
    )
    return row


def _standalone_facebook_row(facebook_row: Any, fallback_title: str = "") -> dict[str, str | bool]:
    title = _attr(facebook_row, "title") or fallback_title
    return _fill_product_row(
        alibaba_row=None,
        facebook_row=facebook_row,
        ml_row=None,
        product_id="",
        product_title=title,
    )


def _standalone_ml_row(ml_row: Any, fallback_title: str = "") -> dict[str, str | bool]:
    title = _attr(ml_row, "title") or fallback_title
    return _fill_product_row(
        alibaba_row=None,
        facebook_row=None,
        ml_row=ml_row,
        product_id="",
        product_title=title,
    )


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
    """Fill FB/ML cells only when an explicit Alibaba association proves identity."""

    facebook_best = _best_by_relevance(facebook_rows) if facebook_status == UI_SUCCESS else None
    ml_best = _best_by_relevance(ml_rows) if ml_status == UI_SUCCESS else None
    context = dict(alibaba_context or {})
    context_id = _text(context.get("external_id"))
    context_title = _text(context.get("title"))
    facebook_id = _text(facebook_association_id)
    ml_id = _text(ml_association_id)

    rows: list[dict[str, str | bool]] = []
    facebook_placed = False
    ml_placed = False

    if alibaba_status == UI_SUCCESS and alibaba_rows:
        for item in alibaba_rows:
            product_id = _attr(item, "product_id")
            facebook_row = facebook_best if product_id and facebook_id == product_id else None
            ml_row = ml_best if product_id and ml_id == product_id else None
            if facebook_row is not None:
                facebook_placed = True
            if ml_row is not None:
                ml_placed = True
            rows.append(
                _fill_product_row(
                    alibaba_row=item,
                    facebook_row=facebook_row,
                    ml_row=ml_row,
                    product_id=product_id,
                    product_title=_attr(item, "title") or context_title or fallback_title,
                    ml_comparison=ml_comparison,
                    landed=landed if product_id and product_id == context_id else None,
                )
            )
    else:
        shared_id = shared_alibaba_association(facebook_id, ml_id, context_id)
        if shared_id and facebook_best is not None and ml_best is not None:
            associated = _lookup_alibaba(alibaba_rows, shared_id)
            rows.append(
                _fill_product_row(
                    alibaba_row=associated,
                    facebook_row=facebook_best,
                    ml_row=ml_best,
                    product_id=shared_id,
                    product_title=(
                        _attr(associated, "title")
                        or context_title
                        or fallback_title
                        or _attr(facebook_best, "title")
                    ),
                    ml_comparison=ml_comparison,
                    landed=landed,
                )
            )
            facebook_placed = True
            ml_placed = True

    if facebook_best is not None and not facebook_placed:
        rows.append(_standalone_facebook_row(facebook_best, fallback_title))
    if ml_best is not None and not ml_placed:
        rows.append(_standalone_ml_row(ml_best, fallback_title))
    return rows
