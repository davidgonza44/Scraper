"""Composition wiring and row/summary mapping. No Apify imports."""

from __future__ import annotations

import copy
import dataclasses
import logging
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from bera_price_tracker.composition import ApplicationComposition, build_composition
from bera_price_tracker.config import Settings
from bera_price_tracker.domain.models import MarketplaceSource, SearchQuery
from bera_price_tracker.gui.display import as_decimal, format_price, is_valid_price

logger = logging.getLogger(__name__)

UNAVAILABLE_USER_MESSAGE = "Facebook Marketplace no está disponible temporalmente."
GENERIC_USER_MESSAGE = "No se pudo consultar Facebook Marketplace."

_EXPLAIN_FIELDS = (
    "product_type",
    "h0019_match",
    "bike_models",
    "other_compatibility",
    "position",
    "classification_source",
)

_CITY_LABELS = {
    "caracas": "Caracas",
}


def get_composition(
    settings: Settings, provider_source: MarketplaceSource
) -> ApplicationComposition:
    """Default composition factory. Tests patch this callable."""
    return build_composition(settings, provider_source=provider_source)


def apply_facebook_scope(settings: Settings, city: str, limit: int) -> Settings:
    """Set city/limit on Settings. Prefer dataclasses.replace, then setattr on a copy."""
    city_value = (city or "").strip() or "caracas"
    limit_value = max(1, min(5, int(limit)))
    try:
        return dataclasses.replace(
            settings,
            facebook_city=city_value,
            facebook_record_limit=limit_value,
        )
    except (TypeError, ValueError, AttributeError):
        clone = copy.copy(settings)
        try:
            object.__setattr__(clone, "facebook_city", city_value)
            object.__setattr__(clone, "facebook_record_limit", limit_value)
            return clone
        except (TypeError, AttributeError):
            logger.info("Could not apply facebook city/limit onto Settings copy")
            return settings


def sanitize_error(exc: BaseException) -> str:
    """User-facing error only. Never leak tokens, stacks, payloads, or headers."""
    type_name = type(exc).__name__
    message = str(exc) if exc else ""
    logger.info("Facebook collect failed: %s", type_name)
    if "MarketplaceSourceUnavailable" in type_name:
        return UNAVAILABLE_USER_MESSAGE
    if "unavailable" in message.lower():
        return UNAVAILABLE_USER_MESSAGE
    return GENERIC_USER_MESSAGE


def city_label(slug: str) -> str:
    key = (slug or "").strip().lower()
    if key in _CITY_LABELS:
        return _CITY_LABELS[key]
    if not key:
        return "—"
    return " ".join(part.capitalize() for part in key.replace("_", "-").split("-"))


def _as_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                out.append(text)
        return tuple(out)
    text = str(value).strip()
    return (text,) if text else ()


def compatibility_label(explain: dict[str, Any] | None) -> str:
    if not explain:
        return ""
    models = _as_tuple(explain.get("bike_models"))
    other = _as_tuple(explain.get("other_compatibility"))
    h0019 = explain.get("h0019_match")
    parts: list[str] = []
    parts.extend(models[:2])
    if h0019 is True or (
        isinstance(h0019, str) and h0019.strip().lower() in {"true", "h0019", "yes", "1"}
    ):
        parts.append("H0019")
    elif (
        isinstance(h0019, str)
        and h0019.strip()
        and h0019.strip().lower()
        not in {
            "false",
            "no",
            "0",
        }
    ):
        parts.append(h0019.strip())
    if not parts:
        parts.extend(other[:1])
    return " / ".join(parts)


def explanation_to_dict(item: object) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for field in _EXPLAIN_FIELDS:
        data[field] = getattr(item, field, None)
    data["title"] = getattr(item, "title", None)
    data["price"] = getattr(item, "price", None)
    data["location"] = getattr(item, "location", None)
    return data


def public_details(explain: dict[str, Any] | None) -> dict[str, str]:
    if not explain:
        return {}
    details: dict[str, str] = {}
    for field in _EXPLAIN_FIELDS:
        value = explain.get(field)
        if value is None or value == "" or value == ():
            continue
        if isinstance(value, (list, tuple)):
            text = ", ".join(str(v) for v in value if str(v).strip())
        elif isinstance(value, bool):
            text = "sí" if value else "no"
        else:
            text = str(value).strip()
        if text:
            details[field] = text
    return details


def _match_explanation(
    title: str, explanations: list[dict[str, Any]], used: set[int]
) -> dict[str, Any] | None:
    target = (title or "").strip().lower()
    if not target:
        return None
    for index, item in enumerate(explanations):
        if index in used:
            continue
        other = str(item.get("title") or "").strip().lower()
        if other and other == target:
            used.add(index)
            return item
    return None


def observation_to_row(
    observation: object,
    *,
    city: str,
    explain: dict[str, Any] | None,
) -> dict[str, Any]:
    price = getattr(observation, "price", None)
    amount = as_decimal(price)
    return {
        "title": str(getattr(observation, "title", "") or ""),
        "price": format_price(price),
        "price_raw": str(amount) if amount is not None else "",
        "currency": str(getattr(observation, "currency", "") or ""),
        "compatibility": compatibility_label(explain),
        "city": city_label(city),
        "source": "Facebook Marketplace",
        "url": str(getattr(observation, "url", "") or ""),
        "details": public_details(explain),
        "details_items": [
            {"label": key, "value": value} for key, value in public_details(explain).items()
        ],
    }


def build_summary(
    *,
    listing_count: int,
    total_listings: int | None,
    persisted: int | None,
    prices: list[Decimal],
) -> dict[str, str]:
    encontrados = total_listings if total_listings is not None else listing_count
    guardados = persisted if persisted is not None else listing_count
    if prices:
        total = sum(prices, Decimal("0"))
        avg = (total / Decimal(len(prices))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        lo = min(prices).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        hi = max(prices).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        min_text = format_price(lo)
        avg_text = format_price(avg)
        max_text = format_price(hi)
    else:
        min_text = avg_text = max_text = "—"
    return {
        "encontrados": str(encontrados),
        "guardados": str(guardados),
        "min": min_text,
        "avg": avg_text,
        "max": max_text,
    }


def run_facebook_search(
    query_text: str,
    city: str,
    limit: int,
    *,
    get_composition: Callable[[Settings, MarketplaceSource], Any] | None = None,
) -> dict[str, Any]:
    """Collect via ApplicationComposition.collect, then inspect observations."""
    factory = get_composition if get_composition is not None else globals()["get_composition"]
    query_text = (query_text or "").strip() or "pastillas sbr"
    city = (city or "").strip() or "caracas"
    limit = max(1, min(5, int(limit)))

    settings = apply_facebook_scope(Settings.from_env(), city, limit)
    source = MarketplaceSource.FACEBOOK_MARKETPLACE
    composition = factory(settings, source)
    query = SearchQuery(text=query_text)
    result = composition.collect(query)

    inspection = composition.inspect_latest_collection(source, query, limit=limit)
    explanations = [explanation_to_dict(item) for item in getattr(result, "explanations", ()) or ()]
    used: set[int] = set()

    rows: list[dict[str, Any]] = []
    prices: list[Decimal] = []
    observations = ()
    total_listings = None
    if inspection is not None:
        observations = getattr(inspection, "observations", ()) or ()
        total_listings = getattr(inspection, "total_listings", None)
        for observation in observations:
            title = str(getattr(observation, "title", "") or "")
            explain = _match_explanation(title, explanations, used)
            rows.append(observation_to_row(observation, city=city, explain=explain))
            price = getattr(observation, "price", None)
            if is_valid_price(price):
                amount = as_decimal(price)
                if amount is not None:
                    prices.append(amount)

    listing_count = int(getattr(result, "listing_count", 0) or 0)
    metrics = getattr(result, "metrics", None)
    persisted = getattr(metrics, "persisted", None) if metrics is not None else None
    fetched = getattr(metrics, "fetched", None) if metrics is not None else None
    if total_listings is None:
        total_listings = listing_count if listing_count else fetched

    summary = build_summary(
        listing_count=listing_count,
        total_listings=total_listings,
        persisted=persisted if persisted is not None else listing_count,
        prices=prices,
    )
    status = "SUCCESS" if rows else "EMPTY"
    return {
        "ui_status": status,
        "results": rows,
        "summary": summary,
        "error_message": "",
    }


ALIBABA_GENERIC_USER_MESSAGE = "No se pudo completar la búsqueda en Alibaba."
ALIBABA_EMPTY_MESSAGE = "No se encontraron productos en Alibaba."
ALIBABA_LOADING_MESSAGE = "Buscando productos en Alibaba..."
ALIBABA_LIMIT_ERROR = "El límite debe estar entre 1 y 500."
ALIBABA_QUERY_ERROR = "La consulta no puede estar vacía."


def can_start_alibaba_search(is_loading: bool) -> bool:
    return not is_loading


def sanitize_alibaba_error(exc: BaseException) -> str:
    type_name = type(exc).__name__
    logger.info("Alibaba search failed: %s", type_name)
    return ALIBABA_GENERIC_USER_MESSAGE


def alibaba_product_to_row(product: object) -> dict[str, Any]:
    price_display = getattr(product, "price_display", None)
    price = str(price_display).strip() if price_display else ""
    return {
        "title": str(getattr(product, "title", "") or ""),
        "price": price,
        "moq": str(getattr(product, "moq", "") or ""),
        "supplier_name": str(getattr(product, "supplier_name", "") or ""),
        "supplier_country": str(getattr(product, "supplier_country", "") or ""),
        "url": str(getattr(product, "product_url", "") or ""),
        "image_url": str(getattr(product, "image_url", "") or ""),
    }


def build_alibaba_summary(products: list[object]) -> dict[str, str]:
    from bera_price_tracker.application.alibaba_statistics import (
        calculate_alibaba_price_statistics,
        format_alibaba_money,
        format_alibaba_typical_range,
        format_priced_count,
        interpret_alibaba_prices,
    )

    stats = calculate_alibaba_price_statistics(products)

    return {
        "resultados": str(stats.total_products),
        "con_precio": format_priced_count(stats.priced_products, stats.total_products),
        "minimo": format_alibaba_money(stats.minimum),
        "promedio": format_alibaba_money(stats.average),
        "mediana": format_alibaba_money(stats.median),
        "maximo": format_alibaba_money(stats.maximum),
        "p25": format_alibaba_money(stats.p25),
        "p75": format_alibaba_money(stats.p75),
        "precio_tipico": format_alibaba_money(stats.trimmed_mean),
        "outliers": str(stats.outlier_count),
        "rango_tipico": format_alibaba_typical_range(stats.p25, stats.p75),
        "interpretacion": interpret_alibaba_prices(stats),
    }


def run_alibaba_search(
    query_text: str,
    limit: int,
    *,
    search_service: Any | None = None,
) -> dict[str, Any]:
    from bera_price_tracker.application.alibaba_relevance import (
        format_relevance_display,
        relevance_label,
        score_alibaba_relevance,
    )
    from bera_price_tracker.application.alibaba_reputation import (
        REVIEW_COUNT_WEIGHT,
        REVIEW_SCORE_WEIGHT,
        SERVICE_WEIGHT,
        YEARS_WEIGHT,
        format_component_points,
        format_coverage_display,
        format_reputation_display,
        score_alibaba_reputation,
    )
    from bera_price_tracker.application.alibaba_score import (
        format_score_display,
        score_alibaba_listings,
    )
    from bera_price_tracker.application.alibaba_statistics import (
        STATS_CURRENCY,
        alibaba_representative_price,
        calculate_alibaba_price_statistics,
        infer_alibaba_currency,
    )
    from bera_price_tracker.application.services import (
        SearchAlibabaProducts,
        validate_alibaba_search,
    )
    from bera_price_tracker.composition import build_alibaba_search

    query, normalized_limit = validate_alibaba_search(query_text, limit)
    service = search_service if search_service is not None else build_alibaba_search()
    if not isinstance(service, SearchAlibabaProducts) and not hasattr(service, "execute"):
        raise TypeError("search_service must implement execute")
    products = list(service.execute(query, normalized_limit))
    stats = calculate_alibaba_price_statistics(products)
    scores = score_alibaba_listings(products, stats)
    relevances = score_alibaba_relevance(query, products)
    reputations = score_alibaba_reputation(products)
    rows: list[dict[str, Any]] = []
    for product, score, relevance, reputation in zip(
        products, scores, relevances, reputations, strict=True
    ):
        row = alibaba_product_to_row(product)
        representative = None
        if infer_alibaba_currency(product) == STATS_CURRENCY:
            representative = alibaba_representative_price(product)
        row["representative"] = "" if representative is None else str(representative)
        row["is_outlier"] = score.is_price_outlier
        row["score_value"] = score.total
        row["score"] = format_score_display(score.total)
        row["score_label"] = score.label
        row["score_price"] = f"{score.price_score}/45"
        row["score_moq"] = f"{score.moq_score}/25"
        row["score_info"] = f"{score.information_score}/20"
        row["score_clarity"] = f"{score.price_clarity_score}/10"
        row["relevance_value"] = relevance.relevance_score
        row["relevance"] = format_relevance_display(relevance.relevance_score)
        row["relevance_label"] = relevance_label(relevance.relevance_score)
        row["relevance_tokens"] = (
            f"{relevance.matched_tokens}/{relevance.total_query_tokens} términos de la búsqueda"
        )
        row["reputation_available"] = reputation.score is not None
        row["reputation_value"] = 0 if reputation.score is None else reputation.score
        row["reputation"] = format_reputation_display(reputation.score)
        row["reputation_label"] = reputation.label
        row["reputation_coverage"] = format_coverage_display(reputation.evidence_coverage)
        row["reputation_coverage_label"] = reputation.evidence_label
        row["reputation_service"] = format_component_points(
            reputation.service_points, SERVICE_WEIGHT
        )
        row["reputation_reviews"] = format_component_points(
            reputation.review_score_points, REVIEW_SCORE_WEIGHT
        )
        row["reputation_years"] = format_component_points(reputation.years_points, YEARS_WEIGHT)
        row["reputation_volume"] = format_component_points(
            reputation.review_count_points, REVIEW_COUNT_WEIGHT
        )
        rows.append(row)
    status = "SUCCESS" if rows else "EMPTY"

    def _raw(value: object) -> str:
        return "" if value is None else str(value)

    return {
        "ui_status": status,
        "results": rows,
        "summary": build_alibaba_summary(list(products)),
        "stats_raw": {
            "minimum": _raw(stats.minimum),
            "p25": _raw(stats.p25),
            "median": _raw(stats.median),
            "p75": _raw(stats.p75),
            "maximum": _raw(stats.maximum),
            "lower_fence": _raw(stats.lower_fence),
            "upper_fence": _raw(stats.upper_fence),
        },
        "error_message": "",
    }
