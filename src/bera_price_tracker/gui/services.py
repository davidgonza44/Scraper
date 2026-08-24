"""Composition wiring and row/summary mapping. No Apify imports."""

from __future__ import annotations

import copy
import dataclasses
import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
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
    min_price = getattr(product, "min_price", None)
    max_price = getattr(product, "max_price", None)
    return {
        "title": str(getattr(product, "title", "") or ""),
        "price": price,
        "moq": str(getattr(product, "moq", "") or ""),
        "supplier_name": str(getattr(product, "supplier_name", "") or ""),
        "supplier_country": str(getattr(product, "supplier_country", "") or ""),
        "url": str(getattr(product, "product_url", "") or ""),
        "image_url": str(getattr(product, "image_url", "") or ""),
        "product_id": str(getattr(product, "product_id", "") or ""),
        "price_min": "" if min_price is None else str(min_price),
        "price_max": "" if max_price is None else str(max_price),
        "currency": str(getattr(product, "currency", "") or ""),
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


def _format_tracked_utc(value: datetime) -> str:
    utc_value = value.astimezone(UTC)
    return utc_value.strftime("%Y-%m-%d %H:%M UTC")


def _format_tracked_variation(tracked: Any) -> str:
    from bera_price_tracker.application.alibaba_statistics import format_alibaba_money
    from bera_price_tracker.application.alibaba_tracking import PERCENT_UNAVAILABLE

    variation = tracked.variation
    if variation.absolute_change is None:
        return "—"
    absolute = format_alibaba_money(variation.absolute_change)
    if variation.percentage_change is None:
        return f"{absolute} ({PERCENT_UNAVAILABLE})"
    percent = variation.percentage_change.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    return f"{absolute} ({percent}%)"


def _tracked_observation_tag(observation: Any) -> str:
    from bera_price_tracker.application.alibaba_tracking import (
        REFRESH_QUERY_PREFIX,
        is_canonical_tracking_observation,
    )

    if observation.query.text.startswith(REFRESH_QUERY_PREFIX):
        return " · Seguimiento"
    if not is_canonical_tracking_observation(observation):
        return " · Discovery"
    return ""


def tracked_product_to_row(tracked: Any) -> dict[str, str]:
    from bera_price_tracker.application.alibaba_statistics import format_alibaba_money
    from bera_price_tracker.application.alibaba_tracking import is_canonical_tracking_observation

    history_lines = [
        f"{_format_tracked_utc(item.collected_at)} · {format_alibaba_money(item.price)}"
        + _tracked_observation_tag(item)
        for item in tracked.history
    ]
    baseline = tracked.variation.baseline_price
    published_range = ""
    if (
        tracked.price_min is not None
        and tracked.price_max is not None
        and tracked.price_min != tracked.price_max
    ):
        published_range = (
            f"{format_alibaba_money(tracked.price_min)}–{format_alibaba_money(tracked.price_max)}"
        )
    first_is_provisional = bool(tracked.history) and not is_canonical_tracking_observation(
        tracked.history[0]
    )
    return {
        "product_id": tracked.product_id,
        "title": tracked.title,
        "supplier_name": tracked.supplier_name or "",
        "current_price": tracked.current_price_display,
        "last_price": format_alibaba_money(tracked.variation.last_price),
        "published_range": published_range,
        "first_price": format_alibaba_money(tracked.variation.first_price),
        "first_price_tag": "Discovery" if first_is_provisional else "",
        "baseline": "—" if baseline is None else format_alibaba_money(baseline),
        "last_updated": _format_tracked_utc(tracked.last_updated),
        "variation": _format_tracked_variation(tracked),
        "history": "\n".join(history_lines),
        "url": tracked.url,
        "is_active": "1" if tracked.is_active else "0",
        "snapshot_count": str(tracked.variation.snapshot_count),
        "price_min": "" if tracked.price_min is None else str(tracked.price_min),
        "price_max": "" if tracked.price_max is None else str(tracked.price_max),
    }


def follow_alibaba_price(
    row: Mapping[str, object],
    query: str,
    *,
    settings: Settings | None = None,
    clock: Any | None = None,
    composition: Any | None = None,
) -> dict[str, str]:
    from bera_price_tracker.application.alibaba_tracking import observation_from_loaded_row

    resolved = settings if settings is not None else Settings.from_env()
    service = composition if composition is not None else build_composition(resolved)
    observation = observation_from_loaded_row(row, query)
    tracked = service.follow_alibaba_price(observation, clock=clock)
    return tracked_product_to_row(tracked)


def unfollow_alibaba_price(
    product_id: str,
    *,
    settings: Settings | None = None,
    composition: Any | None = None,
) -> dict[str, str]:
    resolved = settings if settings is not None else Settings.from_env()
    service = composition if composition is not None else build_composition(resolved)
    tracked = service.unfollow_alibaba_price(product_id)
    return tracked_product_to_row(tracked)


def list_alibaba_tracked(
    *,
    settings: Settings | None = None,
    composition: Any | None = None,
    active_only: bool = True,
) -> list[dict[str, str]]:
    resolved = settings if settings is not None else Settings.from_env()
    service = composition if composition is not None else build_composition(resolved)
    return [
        tracked_product_to_row(item)
        for item in service.list_alibaba_tracked(active_only=active_only)
    ]


ALIBABA_REFRESH_CONFIRM_INTRO = (
    "Vas a consultar {count} productos en Alibaba mediante Apify. Esto puede consumir créditos."
)
ALIBABA_REFRESH_EMPTY_SELECTION = "Selecciona al menos un producto para actualizar."


def clamp_alibaba_refresh_selection(
    product_ids: Sequence[str],
    *,
    limit: int = 50,
) -> list[str]:
    from bera_price_tracker.application.alibaba_refresh import MAX_ALIBABA_REFRESH_BATCH

    cap = MAX_ALIBABA_REFRESH_BATCH if limit > MAX_ALIBABA_REFRESH_BATCH else limit
    unique: list[str] = []
    seen: set[str] = set()
    for raw in product_ids:
        if not isinstance(raw, str):
            continue
        product_id = raw.strip()
        if not product_id or product_id in seen:
            continue
        unique.append(product_id)
        seen.add(product_id)
        if len(unique) >= cap:
            break
    return unique


def alibaba_refresh_confirmation(count: int) -> dict[str, str]:
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        raise ValueError(ALIBABA_REFRESH_EMPTY_SELECTION)
    from bera_price_tracker.application.alibaba_refresh import MAX_ALIBABA_REFRESH_BATCH

    if count > MAX_ALIBABA_REFRESH_BATCH:
        raise ValueError("No se pueden actualizar más de 50 productos en una sola operación.")
    return {
        "intro": ALIBABA_REFRESH_CONFIRM_INTRO.format(count=count),
        "selected": str(count),
        "predicted_runs": "1",
    }


def refresh_summary_to_row(summary: Any) -> dict[str, str]:
    return {
        "requested": str(getattr(summary, "requested", 0)),
        "updated": str(getattr(summary, "updated", 0)),
        "unchanged": str(getattr(summary, "unchanged", 0)),
        "not_found": str(getattr(summary, "not_found", 0)),
        "identity_mismatch": str(getattr(summary, "identity_mismatch", 0)),
        "invalid_price": str(getattr(summary, "invalid_price", 0)),
        "failed": str(getattr(summary, "failed", 0)),
        "predicted_runs": str(getattr(summary, "predicted_runs", 1)),
    }


def refresh_alibaba_tracked(
    product_ids: Sequence[str],
    operation_id: str,
    *,
    settings: Settings | None = None,
    clock: Any | None = None,
    composition: Any | None = None,
    refresh_provider: Any | None = None,
) -> dict[str, str]:
    resolved = settings if settings is not None else Settings.from_env()
    service = composition if composition is not None else build_composition(resolved)
    summary = service.refresh_alibaba_products(
        product_ids,
        operation_id=operation_id,
        clock=clock,
        refresh_provider=refresh_provider,
    )
    return refresh_summary_to_row(summary)


ALIBABA_NEGOTIATION_GENERIC_ERROR = "No se pudo completar la negociación."
ALIBABA_NEGOTIATION_PRODUCT_ERROR = "Selecciona un producto para negociar."


def sanitize_alibaba_negotiation_error(exc: BaseException) -> str:
    from bera_price_tracker.application.alibaba_negotiation import AlibabaNegotiationError

    if isinstance(exc, AlibabaNegotiationError):
        return str(exc)
    logger.info("Alibaba negotiation failed: %s", type(exc).__name__)
    return ALIBABA_NEGOTIATION_GENERIC_ERROR


def _optional_form_money(value: object) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = Decimal(value.strip().replace(",", "").replace("$", ""))
    except InvalidOperation:
        return None
    if not parsed.is_finite() or parsed <= Decimal("0"):
        return None
    return parsed


def _parse_aggressiveness(value: object) -> int:
    if isinstance(value, bool):
        return 50
    if isinstance(value, int) and 0 <= value <= 100:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        if 0 <= parsed <= 100:
            return parsed
    return 50


def _optional_form_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed > 0 else None
    return None


def build_alibaba_negotiation_catalog(
    tracked_rows: Sequence[Mapping[str, object]],
    result_rows: Sequence[Mapping[str, object]],
) -> list[dict[str, str]]:
    """Selector options from followed products first, then loaded search rows."""

    catalog: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in tracked_rows:
        product_id = str(row.get("product_id") or "").strip()
        if not product_id or product_id in seen:
            continue
        seen.add(product_id)
        title = str(row.get("title") or product_id)
        catalog.append(
            {
                "key": f"t:{product_id}",
                "label": f"{title[:60]} · seguido",
                "source": "tracked",
                "product_id": product_id,
                "title": title,
                "supplier_name": str(row.get("supplier_name") or ""),
                "last_price": str(row.get("last_price") or ""),
                "price_min": str(row.get("price_min") or ""),
                "price_max": str(row.get("price_max") or ""),
                "moq": "",
                "representative": "",
            }
        )
    for row in result_rows:
        product_id = str(row.get("product_id") or "").strip()
        if not product_id or product_id in seen:
            continue
        seen.add(product_id)
        title = str(row.get("title") or product_id)
        catalog.append(
            {
                "key": f"s:{product_id}",
                "label": f"{title[:60]} · búsqueda",
                "source": "search",
                "product_id": product_id,
                "title": title,
                "supplier_name": str(row.get("supplier_name") or ""),
                "last_price": "",
                "price_min": str(row.get("price_min") or ""),
                "price_max": str(row.get("price_max") or ""),
                "moq": str(row.get("moq") or ""),
                "representative": str(row.get("representative") or ""),
            }
        )
    return catalog


def negotiation_plan_to_row(plan: Any) -> dict[str, str]:
    from bera_price_tracker.application.alibaba_statistics import format_alibaba_money

    next_qty = plan.next_tier_min_quantity
    proximity = plan.tier_proximity
    return {
        "title": plan.title,
        "supplier_name": plan.supplier_name or "",
        "desired_quantity": str(plan.desired_quantity),
        "public_unit_price": format_alibaba_money(plan.public_unit_price),
        "opening_offer": format_alibaba_money(plan.opening_offer),
        "target_price": format_alibaba_money(plan.target_price),
        "ceiling_price": format_alibaba_money(plan.ceiling_price),
        "negotiable_reference": format_alibaba_money(plan.negotiable_reference),
        "next_tier": (
            "—"
            if next_qty is None or plan.next_tier_price is None
            else f"{next_qty} u · {format_alibaba_money(plan.next_tier_price)}"
        ),
        "tier_proximity": (
            "—" if proximity is None else f"{(proximity * Decimal('100')).quantize(Decimal('1'))}%"
        ),
        "explanation": plan.explanation,
        "attractiveness": plan.attractiveness.value,
        "ladder_summary": plan.ladder_summary,
        "public_raw": str(plan.public_unit_price),
        "min_order_quantity": (
            "" if plan.min_order_quantity is None else str(plan.min_order_quantity)
        ),
        "original_ceiling": "",
        "profitability_ceiling": "",
        "profitability_ceiling_raw": "",
        "effective_ceiling": "",
        "profitability_applied": "0",
        "ceiling_provenance": "",
        "profitability_note": "",
        "rate_status": "",
    }


def calculate_alibaba_negotiation(
    catalog_row: Mapping[str, object] | None,
    *,
    desired_quantity: object,
    expected_resale_price: object = "",
    target_margin_percent: object = "",
    shipping_per_unit: object = "",
    duties_per_unit: object = "",
    other_costs_per_unit: object = "",
    negotiation_aggressiveness: object = "50",
    ladder_text: object = "",
) -> dict[str, str]:
    from bera_price_tracker.application.alibaba_negotiation import (
        AlibabaNegotiationError,
        AlibabaNegotiationInput,
        calculate_alibaba_negotiation_plan,
        parse_ladder_text,
        public_price_from_catalog_row,
    )
    from bera_price_tracker.application.alibaba_score import extract_moq_quantity

    if catalog_row is None:
        raise AlibabaNegotiationError(ALIBABA_NEGOTIATION_PRODUCT_ERROR)
    quantity = _optional_form_int(desired_quantity)
    if quantity is None:
        raise AlibabaNegotiationError("Indica una cantidad deseada mayor que cero.")
    aggressiveness = _parse_aggressiveness(negotiation_aggressiveness)
    moq_decimal = extract_moq_quantity(catalog_row.get("moq"))
    moq = None if moq_decimal is None else int(moq_decimal)
    margin = _optional_form_money(target_margin_percent)
    plan = calculate_alibaba_negotiation_plan(
        AlibabaNegotiationInput(
            desired_quantity=quantity,
            title=str(catalog_row.get("title") or ""),
            supplier_name=str(catalog_row.get("supplier_name") or "") or None,
            min_order_quantity=moq,
            tiers=parse_ladder_text(ladder_text),
            public_unit_price=public_price_from_catalog_row(catalog_row),
            expected_resale_price=_optional_form_money(expected_resale_price),
            target_margin_percent=margin,
            shipping_per_unit=_optional_form_money(shipping_per_unit),
            duties_per_unit=_optional_form_money(duties_per_unit),
            other_costs_per_unit=_optional_form_money(other_costs_per_unit),
            negotiation_aggressiveness=aggressiveness,
        )
    )
    row = negotiation_plan_to_row(plan)
    row.update(
        {
            "ladder_text": ladder_text if isinstance(ladder_text, str) else "",
            "expected_resale_price": (
                ""
                if _optional_form_money(expected_resale_price) is None
                else str(_optional_form_money(expected_resale_price))
            ),
            "target_margin_percent": "" if margin is None else str(margin),
            "shipping_per_unit": (
                ""
                if _optional_form_money(shipping_per_unit) is None
                else str(_optional_form_money(shipping_per_unit))
            ),
            "duties_per_unit": (
                ""
                if _optional_form_money(duties_per_unit) is None
                else str(_optional_form_money(duties_per_unit))
            ),
            "other_costs_per_unit": (
                ""
                if _optional_form_money(other_costs_per_unit) is None
                else str(_optional_form_money(other_costs_per_unit))
            ),
            "aggressiveness": str(aggressiveness),
        }
    )
    return row


def _plan_from_row(row: Mapping[str, object]) -> Any:
    from bera_price_tracker.application.alibaba_negotiation import (
        AlibabaNegotiationError,
        AlibabaNegotiationInput,
        calculate_alibaba_negotiation_plan,
        parse_ladder_text,
    )
    from bera_price_tracker.application.import_aware_negotiation import apply_profitability_ceiling
    from bera_price_tracker.application.landed_cost import ShippingRateStatus

    quantity = _optional_form_int(row.get("desired_quantity"))
    public = _optional_form_money(str(row.get("public_raw") or ""))
    if quantity is None or public is None:
        raise AlibabaNegotiationError("Calcula la estrategia antes de generar un mensaje.")
    plan = calculate_alibaba_negotiation_plan(
        AlibabaNegotiationInput(
            desired_quantity=quantity,
            title=str(row.get("title") or ""),
            supplier_name=str(row.get("supplier_name") or "") or None,
            min_order_quantity=_optional_form_int(row.get("min_order_quantity")),
            tiers=parse_ladder_text(row.get("ladder_text") or ""),
            public_unit_price=public,
            expected_resale_price=_optional_form_money(row.get("expected_resale_price")),
            target_margin_percent=_optional_form_money(row.get("target_margin_percent")),
            shipping_per_unit=_optional_form_money(row.get("shipping_per_unit")),
            duties_per_unit=_optional_form_money(row.get("duties_per_unit")),
            other_costs_per_unit=_optional_form_money(row.get("other_costs_per_unit")),
            negotiation_aggressiveness=_parse_aggressiveness(row.get("aggressiveness")),
        )
    )
    if str(row.get("profitability_applied") or "") != "1":
        return plan
    raw = str(row.get("profitability_ceiling_raw") or "").strip()
    try:
        max_supplier = Decimal(raw) if raw else None
    except InvalidOperation:
        max_supplier = None
    status_text = str(row.get("rate_status") or "").strip()
    status = None
    if status_text in {item.value for item in ShippingRateStatus}:
        status = ShippingRateStatus(status_text)
    return apply_profitability_ceiling(
        plan,
        maximum_supplier_unit_price=max_supplier,
        rate_status=status,
    ).plan


def generate_alibaba_negotiation_opening(
    plan_row: Mapping[str, object],
    *,
    drafter: Any | None = None,
) -> str:
    from bera_price_tracker.application.alibaba_negotiation import (
        AlibabaNegotiationDrafter,
        GenerateNegotiationOpeningMessage,
    )
    from bera_price_tracker.composition import build_alibaba_negotiation_drafter

    resolved: AlibabaNegotiationDrafter = (
        drafter if drafter is not None else build_alibaba_negotiation_drafter()
    )
    return GenerateNegotiationOpeningMessage(resolved).execute(_plan_from_row(plan_row))


def analyze_alibaba_supplier_reply(
    plan_row: Mapping[str, object],
    supplier_text: str,
    *,
    drafter: Any | None = None,
) -> dict[str, str]:
    from bera_price_tracker.application.alibaba_negotiation import (
        AlibabaNegotiationDrafter,
        AnalyzeSupplierResponse,
    )
    from bera_price_tracker.application.alibaba_statistics import format_alibaba_money
    from bera_price_tracker.composition import build_alibaba_negotiation_drafter

    resolved: AlibabaNegotiationDrafter = (
        drafter if drafter is not None else build_alibaba_negotiation_drafter()
    )
    parsed, recommendation = AnalyzeSupplierResponse(resolved).execute(
        _plan_from_row(plan_row),
        supplier_text,
    )
    return {
        "response_summary": parsed.response_summary,
        "quoted_unit_price": (
            "—"
            if parsed.quoted_unit_price is None
            else format_alibaba_money(parsed.quoted_unit_price)
        ),
        "quoted_quantity": "—" if parsed.quoted_quantity is None else str(parsed.quoted_quantity),
        "quoted_moq": "—" if parsed.quoted_moq is None else str(parsed.quoted_moq),
        "shipping_mentioned": "sí" if parsed.shipping_mentioned else "no",
        "decision": recommendation.decision.value,
        "authorized_price": (
            "—"
            if recommendation.authorized_price is None
            else format_alibaba_money(recommendation.authorized_price)
        ),
        "notes": recommendation.notes,
        "needs_review": "1" if parsed.needs_human_review else "0",
        "quoted_raw": "" if parsed.quoted_unit_price is None else str(parsed.quoted_unit_price),
    }


def generate_alibaba_negotiation_reply(
    plan_row: Mapping[str, object],
    supplier_text: str,
    *,
    drafter: Any | None = None,
) -> str:
    from bera_price_tracker.application.alibaba_negotiation import (
        AlibabaNegotiationDrafter,
        AnalyzeSupplierResponse,
        GenerateNegotiationReply,
    )
    from bera_price_tracker.composition import build_alibaba_negotiation_drafter

    resolved: AlibabaNegotiationDrafter = (
        drafter if drafter is not None else build_alibaba_negotiation_drafter()
    )
    plan = _plan_from_row(plan_row)
    parsed, recommendation = AnalyzeSupplierResponse(resolved).execute(plan, supplier_text)
    return GenerateNegotiationReply(resolved).execute(plan, parsed, recommendation)


ALIBABA_LANDED_COST_GENERIC_ERROR = "No se pudo calcular el costo puesto en Venezuela."
ALIBABA_LANDED_ESTIMATE_LABEL = "ESTIMACIÓN LOGÍSTICA"
ALIBABA_LANDED_CONFIRMED_LABEL = "Cotización confirmada"


def sanitize_alibaba_landed_cost_error(exc: BaseException) -> str:
    from bera_price_tracker.application.landed_cost import LandedCostError

    if isinstance(exc, LandedCostError):
        return str(exc)
    logger.info("Alibaba landed cost failed: %s", type(exc).__name__)
    return ALIBABA_LANDED_COST_GENERIC_ERROR


def _zero_or_form_money(value: object, message: str) -> Decimal:
    """Blank form fields mean 0. Non-blank fields must be non-negative money."""

    from bera_price_tracker.application.landed_cost import LandedCostError

    if value is None or (isinstance(value, str) and not value.strip()):
        return Decimal("0")
    if not isinstance(value, str):
        raise LandedCostError(message)
    try:
        parsed = Decimal(value.strip().replace(",", "").replace("$", ""))
    except InvalidOperation:
        raise LandedCostError(message) from None
    if not parsed.is_finite() or parsed < Decimal("0"):
        raise LandedCostError(message)
    return parsed


def calculate_alibaba_landed_cost(
    *,
    quantity: object,
    supplier_unit_price: object,
    cartons: object,
    units_per_carton: object,
    carton_length_cm: object,
    carton_width_cm: object,
    carton_height_cm: object,
    gross_weight_kg_per_carton: object,
    rate_usd_per_cbm: object,
    rate_confirmed: bool = False,
    has_battery: bool = False,
    battery_multiplier: object = "",
    wood_surcharge: object = "",
    insurance: object = "",
    other_shipping_costs: object = "",
    other_import_costs: object = "",
    expected_sale_price: object = "",
    target_margin_percent: object = "",
    product_title: str = "",
) -> dict[str, str]:
    """Parse GUI form strings and return a display row. Formulas live in application."""

    from bera_price_tracker.application.alibaba_statistics import format_alibaba_money
    from bera_price_tracker.application.landed_cost import (
        INVALID_BATTERY_MULTIPLIER,
        INVALID_CARGO_RATE,
        INVALID_IMPORT_COST,
        INVALID_LANDED_QUANTITY,
        INVALID_SUPPLIER_PRICE,
        INVALID_SURCHARGE,
        CargoPackagingInput,
        ImportOtherCosts,
        LandedCostError,
        LandedCostInput,
        LandedCostViability,
        ShippingRateProfile,
        ShippingRateStatus,
        ShippingSurcharges,
        calculate_landed_cost,
    )

    parsed_quantity = _optional_form_int(quantity)
    if parsed_quantity is None:
        raise LandedCostError(INVALID_LANDED_QUANTITY)
    parsed_price = _optional_form_money(supplier_unit_price)
    if parsed_price is None:
        raise LandedCostError(INVALID_SUPPLIER_PRICE)
    parsed_sale = _optional_form_money(expected_sale_price)
    parsed_rate = _optional_form_money(rate_usd_per_cbm)
    if parsed_rate is None:
        raise LandedCostError(INVALID_CARGO_RATE)
    multiplier = Decimal("1")
    if has_battery:
        parsed_multiplier = _optional_form_money(battery_multiplier)
        if parsed_multiplier is None:
            raise LandedCostError(INVALID_BATTERY_MULTIPLIER)
        multiplier = parsed_multiplier
    analysis = calculate_landed_cost(
        LandedCostInput(
            quantity=parsed_quantity,
            supplier_unit_price=parsed_price,
            packaging=CargoPackagingInput(
                cartons=_optional_form_int(cartons),
                units_per_carton=_optional_form_int(units_per_carton),
                carton_length_cm=_optional_form_money(carton_length_cm),
                carton_width_cm=_optional_form_money(carton_width_cm),
                carton_height_cm=_optional_form_money(carton_height_cm),
                gross_weight_kg_per_carton=_optional_form_money(gross_weight_kg_per_carton),
            ),
            rate=ShippingRateProfile(
                rate_usd_per_cbm=parsed_rate,
                status=(
                    ShippingRateStatus.CONFIRMED_QUOTE
                    if rate_confirmed
                    else ShippingRateStatus.ESTIMATE
                ),
                rate_source="manual" if not rate_confirmed else "confirmed_quote",
            ),
            surcharges=ShippingSurcharges(
                battery_multiplier=multiplier,
                pallet_or_wood_surcharge=_zero_or_form_money(wood_surcharge, INVALID_SURCHARGE),
                insurance=_zero_or_form_money(insurance, INVALID_SURCHARGE),
                other_shipping_costs=_zero_or_form_money(other_shipping_costs, INVALID_SURCHARGE),
            ),
            import_costs=ImportOtherCosts(
                other_import_costs=_zero_or_form_money(other_import_costs, INVALID_IMPORT_COST),
            ),
            expected_sale_price_per_unit=parsed_sale,
            target_margin_percent=_optional_form_money(target_margin_percent),
        )
    )
    return {
        "product_title": product_title,
        "quantity": str(analysis.quantity),
        "merchandise_cost": format_alibaba_money(analysis.merchandise_cost),
        "carton_cbm": f"{analysis.carton_cbm.normalize():f} CBM",
        "total_cbm": f"{analysis.total_cbm.normalize():f} CBM",
        "total_weight": f"{analysis.total_weight_kg.normalize():f} kg",
        "freight_base": format_alibaba_money(analysis.freight_base),
        "freight_adjusted": format_alibaba_money(analysis.freight_adjusted),
        "shipping_surcharges": format_alibaba_money(analysis.shipping_surcharges),
        "shipping_total": format_alibaba_money(analysis.shipping_total),
        "other_import_costs": format_alibaba_money(analysis.other_import_costs),
        "total_landed_cost": format_alibaba_money(analysis.total_landed_cost),
        "landed_cost_per_unit": format_alibaba_money(analysis.landed_cost_per_unit),
        "break_even": format_alibaba_money(analysis.break_even_sale_price),
        "rate_label": (
            ALIBABA_LANDED_CONFIRMED_LABEL
            if analysis.rate_status is ShippingRateStatus.CONFIRMED_QUOTE
            else ALIBABA_LANDED_ESTIMATE_LABEL
        ),
        "rate_display": f"{analysis.rate_usd_per_cbm.normalize():f} USD/CBM · "
        f"{analysis.provider} · {analysis.service} · {analysis.destination_country}",
        "expected_sale_price": ("" if parsed_sale is None else format_alibaba_money(parsed_sale)),
        "revenue": "" if analysis.revenue is None else format_alibaba_money(analysis.revenue),
        "gross_profit": (
            "" if analysis.gross_profit is None else format_alibaba_money(analysis.gross_profit)
        ),
        "gross_profit_per_unit": (
            ""
            if analysis.gross_profit_per_unit is None
            else format_alibaba_money(analysis.gross_profit_per_unit)
        ),
        "margin_percent": (
            "" if analysis.margin_percent is None else f"{analysis.margin_percent}%"
        ),
        "max_supplier_price": (
            ""
            if analysis.maximum_supplier_unit_price is None
            else format_alibaba_money(analysis.maximum_supplier_unit_price)
        ),
        "max_supplier_raw": (
            ""
            if analysis.maximum_supplier_unit_price is None
            else f"{analysis.maximum_supplier_unit_price:f}"
        ),
        "rate_status": analysis.rate_status.value,
        "unattractive": (
            "1" if analysis.viability is LandedCostViability.ECONOMICALLY_UNATTRACTIVE else "0"
        ),
    }


def apply_alibaba_profitability_ceiling(
    plan_row: Mapping[str, object],
    landed_row: Mapping[str, object] | None,
) -> dict[str, str]:
    """Apply a completed landed-cost ceiling to an existing negotiation row."""

    from bera_price_tracker.application.alibaba_negotiation import AlibabaNegotiationError
    from bera_price_tracker.application.alibaba_statistics import format_alibaba_money
    from bera_price_tracker.application.import_aware_negotiation import (
        MISSING_PROFITABILITY_CEILING,
        apply_profitability_ceiling,
    )
    from bera_price_tracker.application.landed_cost import LandedCostError, ShippingRateStatus

    if not plan_row:
        raise AlibabaNegotiationError("Calcula la estrategia antes de aplicar rentabilidad.")
    raw = "" if landed_row is None else str(landed_row.get("max_supplier_raw") or "").strip()
    if not raw:
        raise LandedCostError(MISSING_PROFITABILITY_CEILING)
    try:
        max_supplier = Decimal(raw)
    except InvalidOperation:
        raise LandedCostError(MISSING_PROFITABILITY_CEILING) from None
    status_text = "" if landed_row is None else str(landed_row.get("rate_status") or "").strip()
    status = (
        ShippingRateStatus(status_text)
        if status_text in {item.value for item in ShippingRateStatus}
        else ShippingRateStatus.ESTIMATE
    )
    base = {str(key): str(value) for key, value in plan_row.items()}
    composed = apply_profitability_ceiling(
        _plan_from_row({**base, "profitability_applied": "0"}),
        maximum_supplier_unit_price=max_supplier,
        rate_status=status,
    )
    row = {**base, **negotiation_plan_to_row(composed.plan)}
    row.update(
        {
            "original_ceiling": format_alibaba_money(composed.original_ceiling),
            "profitability_ceiling": format_alibaba_money(composed.profitability_ceiling)
            if composed.profitability_ceiling is not None
            else "",
            "profitability_ceiling_raw": (
                ""
                if composed.profitability_ceiling is None
                else f"{composed.profitability_ceiling:f}"
            ),
            "effective_ceiling": format_alibaba_money(composed.effective_ceiling),
            "profitability_applied": "1" if composed.applied else "0",
            "ceiling_provenance": composed.provenance or "",
            "profitability_note": composed.profitability_note,
            "rate_status": "" if composed.rate_status is None else composed.rate_status.value,
        }
    )
    return row


MERCADOLIBRE_GENERIC_USER_MESSAGE = "No se pudo completar la búsqueda en Mercado Libre Venezuela."
MERCADOLIBRE_EMPTY_MESSAGE = "No se encontraron publicaciones en Mercado Libre Venezuela."
MERCADOLIBRE_LOADING_MESSAGE = "Buscando publicaciones en Mercado Libre Venezuela..."
MERCADOLIBRE_QUERY_ERROR = "Indica un término de búsqueda."
MERCADOLIBRE_LIMIT_ERROR = "La cantidad debe estar entre 1 y 50."
MERCADOLIBRE_LANDED_MISSING = "Calcula el costo Venezuela en Alibaba antes de comparar."
MERCADOLIBRE_PUBLISHED_NOTE = "Precios publicados observados en Mercado Libre Venezuela"


def can_start_mercadolibre_search(is_loading: bool) -> bool:
    return not is_loading


def sanitize_mercadolibre_error(exc: BaseException) -> str:
    from bera_price_tracker.application.ports import MarketplaceSourceUnavailable

    type_name = type(exc).__name__
    logger.info("Mercado Libre search failed: %s", type_name)
    if isinstance(exc, ValueError) and "query" in str(exc):
        return MERCADOLIBRE_QUERY_ERROR
    if isinstance(exc, (ValueError, TypeError)) and "limit" in str(exc):
        return MERCADOLIBRE_LIMIT_ERROR
    if isinstance(exc, MarketplaceSourceUnavailable) or type_name == "ApifyConfigurationError":
        return MERCADOLIBRE_GENERIC_USER_MESSAGE
    return MERCADOLIBRE_GENERIC_USER_MESSAGE


def _blank_or_dash(value: str | None) -> str:
    if value is None or not value.strip():
        return "—"
    return value


def _relevance_stub(score: int) -> Any:
    from bera_price_tracker.application.mercadolibre_relevance import MercadoLibreListingRelevance

    safe = score if isinstance(score, int) and not isinstance(score, bool) else 0
    return MercadoLibreListingRelevance(
        relevance_score=safe,
        matched_tokens=0,
        total_query_tokens=0,
        exact_phrase_match=False,
    )


def mercadolibre_listing_to_row(scored: Any) -> dict[str, Any]:
    from bera_price_tracker.application.mercadolibre_relevance import (
        format_relevance_display,
        relevance_label,
    )
    from bera_price_tracker.application.mercadolibre_statistics import format_mercadolibre_money

    listing = scored.listing
    price = listing.price
    currency = listing.currency
    if listing.free_shipping is True:
        shipping = "Envío gratis"
    elif listing.free_shipping is False:
        shipping = "Pago"
    else:
        shipping = "—"
    return {
        "external_id": listing.external_id,
        "title": listing.title,
        "permalink": listing.permalink or "",
        "price": (
            "—"
            if price is None
            else (
                format_mercadolibre_money(price, currency)
                if currency
                else f"{price.quantize(Decimal('0.01'))}"
            )
        ),
        "price_raw": "" if price is None else f"{price:f}",
        "currency": currency or "—",
        "condition": _blank_or_dash(listing.condition),
        "seller_name": _blank_or_dash(listing.seller_name),
        "shipping": shipping,
        "thumbnail_url": listing.thumbnail_url or "",
        "country": _blank_or_dash(listing.country),
        "representative": "" if price is None else f"{price:f}",
        "relevance_value": scored.relevance_score,
        "relevance": format_relevance_display(scored.relevance_score),
        "relevance_label": relevance_label(scored.relevance_score),
        "relevance_tokens": (
            f"{scored.relevance.matched_tokens}/{scored.relevance.total_query_tokens} "
            "términos de la búsqueda"
        ),
        "is_outlier": False,
    }


def _row_to_listing(row: Mapping[str, object]) -> Any:
    from bera_price_tracker.domain.mercadolibre import MercadoLibreListing

    raw_price = str(row.get("price_raw") or "").strip()
    price = None
    if raw_price:
        try:
            parsed = Decimal(raw_price)
        except InvalidOperation:
            parsed = None
        if parsed is not None and parsed.is_finite() and parsed > 0:
            price = parsed
    currency = str(row.get("currency") or "").strip()
    return MercadoLibreListing(
        external_id=str(row.get("external_id") or "UNKNOWN"),
        title=str(row.get("title") or "Sin título"),
        permalink=str(row.get("permalink") or "") or None,
        price=price,
        currency=None if currency in {"", "—"} else currency,
    )


def _scored_from_rows(rows: Sequence[Mapping[str, object]]) -> list[Any]:
    from bera_price_tracker.application.mercadolibre_benchmark import MercadoLibreScoredListing

    scored = []
    for row in rows:
        relevance_value = row.get("relevance_value", 0)
        score = relevance_value if isinstance(relevance_value, int) else 0
        scored.append(
            MercadoLibreScoredListing(
                listing=_row_to_listing(row), relevance=_relevance_stub(score)
            )
        )
    return scored


def build_mercadolibre_summary(
    scored: Sequence[Any],
    *,
    min_relevance: int,
    total_results: int | None = None,
) -> dict[str, str]:
    from bera_price_tracker.application.mercadolibre_benchmark import build_market_benchmark
    from bera_price_tracker.application.mercadolibre_statistics import (
        format_mercadolibre_money,
        format_mercadolibre_typical_range,
    )

    benchmark = build_market_benchmark(
        scored, min_relevance=min_relevance, total_results=total_results
    )
    currency = benchmark.currency
    return {
        "comparables": f"{benchmark.comparable_count} de {benchmark.total_results}",
        "minimo": format_mercadolibre_money(benchmark.minimum, currency),
        "p25": format_mercadolibre_money(benchmark.p25, currency),
        "mediana": format_mercadolibre_money(benchmark.median, currency),
        "precio_tipico": format_mercadolibre_money(benchmark.typical_price, currency),
        "p75": format_mercadolibre_money(benchmark.p75, currency),
        "maximo": format_mercadolibre_money(benchmark.maximum, currency),
        "promedio": format_mercadolibre_money(benchmark.average, currency),
        "outliers": str(benchmark.outlier_count),
        "rango_tipico": format_mercadolibre_typical_range(benchmark.p25, benchmark.p75, currency),
        "currency": currency or "",
        "note": benchmark.note,
    }


def run_mercadolibre_search(
    query_text: str,
    limit: int,
    *,
    search_service: Any | None = None,
) -> dict[str, Any]:
    from bera_price_tracker.application.mercadolibre_benchmark import (
        DEFAULT_BENCHMARK_RELEVANCE,
        score_listings,
    )
    from bera_price_tracker.application.mercadolibre_statistics import (
        calculate_mercadolibre_price_statistics,
        dominant_currency,
        explicit_currency,
        is_price_outlier,
        listing_price,
    )
    from bera_price_tracker.application.services import (
        SearchMercadoLibreProducts,
        validate_mercadolibre_search,
    )
    from bera_price_tracker.composition import build_mercadolibre_search

    query, normalized_limit = validate_mercadolibre_search(query_text, limit)
    service = search_service if search_service is not None else build_mercadolibre_search()
    if not isinstance(service, SearchMercadoLibreProducts) and not hasattr(service, "execute"):
        raise TypeError("search_service must implement execute")
    listings = list(service.execute(query, normalized_limit))
    scored = score_listings(query, listings)
    comparables = [
        item.listing for item in scored if item.relevance_score >= DEFAULT_BENCHMARK_RELEVANCE
    ]
    currency = dominant_currency(comparables)
    stats = (
        None
        if currency is None
        else calculate_mercadolibre_price_statistics(comparables, currency=currency)
    )
    rows: list[dict[str, Any]] = []
    for item in scored:
        row = mercadolibre_listing_to_row(item)
        price = listing_price(item.listing)
        if (
            stats is not None
            and price is not None
            and explicit_currency(item.listing) == stats.currency
        ):
            row["is_outlier"] = is_price_outlier(price, stats.lower_fence, stats.upper_fence)
        rows.append(row)
    return {
        "ui_status": "SUCCESS" if rows else "EMPTY",
        "results": rows,
        "summary": build_mercadolibre_summary(scored, min_relevance=DEFAULT_BENCHMARK_RELEVANCE),
        "error_message": "",
    }


def mercadolibre_benchmark_source_rows[RowT](
    rows: Sequence[RowT],
    *,
    price_min: object = "",
    price_max: object = "",
) -> list[RowT]:
    """Rows that feed cards and landed comparison. Hide-outliers stays visual-only."""

    from bera_price_tracker.gui.analysis import (
        SORT_ORIGINAL,
        apply_table_view,
        validate_price_filters,
    )

    minimum, maximum, error = validate_price_filters(price_min, price_max)
    if error:
        minimum = None
        maximum = None
    return apply_table_view(
        rows,
        sort=SORT_ORIGINAL,
        minimum=minimum,
        maximum=maximum,
        hide_outliers=False,
        min_relevance=0,
    )


def mercadolibre_summary_from_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    min_relevance: int,
    total_results: int,
) -> dict[str, str]:
    return build_mercadolibre_summary(
        _scored_from_rows(rows),
        min_relevance=min_relevance,
        total_results=total_results,
    )


def parse_landed_unit_from_display_row(
    landed_row: Mapping[str, object] | None,
) -> tuple[Decimal | None, str]:
    from bera_price_tracker.application.landed_cost import DEFAULT_LANDED_CURRENCY
    from bera_price_tracker.gui.analysis import parse_price_input

    if not landed_row:
        return None, DEFAULT_LANDED_CURRENCY
    raw = str(landed_row.get("landed_cost_per_unit_raw") or "").strip()
    if raw:
        try:
            value = Decimal(raw)
        except InvalidOperation:
            value = None
        if value is not None and value.is_finite():
            currency = str(landed_row.get("currency") or DEFAULT_LANDED_CURRENCY).strip()
            return value, currency or DEFAULT_LANDED_CURRENCY
    parsed, ok = parse_price_input(landed_row.get("landed_cost_per_unit"))
    if not ok:
        return None, DEFAULT_LANDED_CURRENCY
    return parsed, DEFAULT_LANDED_CURRENCY


def compare_mercadolibre_with_landed_cost(
    rows: Sequence[Mapping[str, object]],
    landed_row: Mapping[str, object] | None,
    *,
    min_relevance: int,
) -> dict[str, str]:
    from bera_price_tracker.application.mercadolibre_benchmark import (
        build_market_benchmark,
        compare_landed_to_local_market,
    )
    from bera_price_tracker.application.mercadolibre_statistics import format_mercadolibre_money

    landed, currency = parse_landed_unit_from_display_row(landed_row)
    empty = {
        "comparable": "0",
        "message": MERCADOLIBRE_LANDED_MISSING,
        "landed": "",
        "conservative_profit": "",
        "conservative_margin": "",
        "typical_profit": "",
        "typical_margin": "",
        "high_profit": "",
        "high_margin": "",
    }
    if landed is None:
        return empty
    scored = _scored_from_rows(rows)
    benchmark = build_market_benchmark(scored, min_relevance=min_relevance)
    comparison = compare_landed_to_local_market(
        landed_cost_per_unit=landed,
        landed_currency=currency,
        benchmark=benchmark,
    )
    conservative = comparison.conservative
    typical = comparison.typical
    high = comparison.high
    if not comparison.comparable or conservative is None or typical is None or high is None:
        return {
            **empty,
            "message": comparison.message,
            "landed": format_mercadolibre_money(landed, currency),
        }

    def _profit(scenario: Any) -> str:
        return format_mercadolibre_money(scenario.profit_per_unit, comparison.currency)

    def _margin(scenario: Any) -> str:
        if scenario.margin_percent is None:
            return "—"
        return f"{scenario.margin_percent}%"

    return {
        "comparable": "1",
        "message": "",
        "landed": format_mercadolibre_money(comparison.landed_cost_per_unit, comparison.currency),
        "conservative_price": format_mercadolibre_money(
            conservative.local_price, comparison.currency
        ),
        "conservative_profit": _profit(conservative),
        "conservative_margin": _margin(conservative),
        "typical_price": format_mercadolibre_money(typical.local_price, comparison.currency),
        "typical_profit": _profit(typical),
        "typical_margin": _margin(typical),
        "high_price": format_mercadolibre_money(high.local_price, comparison.currency),
        "high_profit": _profit(high),
        "high_margin": _margin(high),
    }
