"""Multi-market vs single-market search planning. No provider I/O here."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from bera_price_tracker.application.facebook_products import MAX_FACEBOOK_PRODUCT_LIMIT
from bera_price_tracker.application.services import MAX_ALIBABA_LIMIT, MAX_MERCADOLIBRE_LIMIT
from bera_price_tracker.gui.brands import PLATFORM_ALIBABA, PLATFORM_FACEBOOK, PLATFORM_ML

MODE_MULTI = "multi-market"
MODE_SINGLE = "single-market"

SEARCH_LIMIT_OPTIONS: tuple[int, ...] = (1, 3, 5)
DEFAULT_SEARCH_LIMIT = 3

ALL_PLATFORMS: tuple[str, ...] = (PLATFORM_ALIBABA, PLATFORM_FACEBOOK, PLATFORM_ML)

SEARCH_QUERY_ERROR = "Escribe qué producto quieres buscar."
SEARCH_LIMIT_ERROR = "Elige 1, 3 o 5 resultados por plataforma."
SEARCH_MODE_ERROR = "Elige comparar las 3 plataformas o una sola plataforma."
SEARCH_PLATFORM_ERROR = "Selecciona Alibaba, Facebook Marketplace o Mercado Libre."

MODE_LABELS = {
    MODE_MULTI: "Comparar las 3 plataformas",
    MODE_SINGLE: "Una sola plataforma",
}
MODE_DESCRIPTIONS = {
    MODE_MULTI: "Busca en Alibaba, Facebook y Mercado Libre",
    MODE_SINGLE: "Busca solo en la plataforma que elijas",
}
PLATFORM_LABELS = {
    PLATFORM_ALIBABA: "Alibaba",
    PLATFORM_FACEBOOK: "Facebook Marketplace",
    PLATFORM_ML: "Mercado Libre",
}


@dataclass(frozen=True, slots=True)
class SearchPlan:
    mode: str
    providers: tuple[str, ...]
    query: str
    limit: int
    city: str


@dataclass
class ProviderCallLog:
    calls: list[str] = field(default_factory=list)

    def record(self, provider: str) -> None:
        self.calls.append(provider)

    def count(self, provider: str) -> int:
        return self.calls.count(provider)


@dataclass(frozen=True, slots=True)
class MarketSearchOutcome:
    results: dict[str, Any]
    errors: dict[str, str]
    calls: tuple[str, ...]
    retries: int = 0


def validate_search_limit(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        try:
            value = int(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(SEARCH_LIMIT_ERROR) from exc
    if value not in SEARCH_LIMIT_OPTIONS:
        raise ValueError(SEARCH_LIMIT_ERROR)
    if value > MAX_FACEBOOK_PRODUCT_LIMIT:
        raise ValueError(SEARCH_LIMIT_ERROR)
    if value > MAX_ALIBABA_LIMIT or value > MAX_MERCADOLIBRE_LIMIT:
        raise ValueError(SEARCH_LIMIT_ERROR)
    return value


def providers_for(mode: str, platform: str = "") -> tuple[str, ...]:
    if mode == MODE_MULTI:
        return ALL_PLATFORMS
    if mode != MODE_SINGLE:
        raise ValueError(SEARCH_MODE_ERROR)
    if platform not in PLATFORM_LABELS:
        raise ValueError(SEARCH_PLATFORM_ERROR)
    return (platform,)


def plan_search(
    *,
    mode: str,
    platform: str = "",
    query: str,
    limit: object,
    city: str = "caracas",
) -> SearchPlan:
    if not isinstance(query, str) or not query.strip():
        raise ValueError(SEARCH_QUERY_ERROR)
    normalized_limit = validate_search_limit(limit)
    providers = providers_for(mode, platform)
    city_text = city.strip() or "caracas"
    return SearchPlan(
        mode=mode,
        providers=providers,
        query=query.strip(),
        limit=normalized_limit,
        city=city_text,
    )


def cta_label(mode: str, platform: str = "") -> str:
    if mode == MODE_MULTI:
        return "Buscar y comparar"
    labels = {
        PLATFORM_ALIBABA: "Buscar en Alibaba",
        PLATFORM_FACEBOOK: "Buscar en Facebook",
        PLATFORM_ML: "Buscar en Mercado Libre",
    }
    return labels.get(platform, "Buscar")


def search_callout(limit: int) -> tuple[str, str]:
    primary = f"Se solicitarán hasta {limit} resultados por plataforma."
    secondary = (
        "Facebook puede mostrar menos resultados si algunos anuncios no tienen un precio válido."
    )
    return primary, secondary


def progress_label(status: str, result_count: str = "") -> str:
    if status == "LOADING":
        return "Buscando..."
    if status == "ERROR":
        return "Error"
    if status == "SUCCESS" and result_count:
        return f"{result_count} resultados"
    if status == "EMPTY":
        return "Sin resultados"
    return "Sin búsqueda"


def execute_market_search(
    plan: SearchPlan,
    runners: Mapping[str, Callable[..., Any]],
    *,
    log: ProviderCallLog | None = None,
) -> MarketSearchOutcome:
    """Call each selected runner once. Never retry. Keep partial successes."""

    results: dict[str, Any] = {}
    errors: dict[str, str] = {}
    calls: list[str] = []
    call_log = log or ProviderCallLog()
    for provider in plan.providers:
        runner = runners[provider]
        call_log.record(provider)
        calls.append(provider)
        try:
            results[provider] = runner(
                query=plan.query,
                limit=plan.limit,
                city=plan.city,
            )
        except Exception as exc:  # noqa: BLE001 — sanitized by the GUI layer
            errors[provider] = str(exc).strip() or type(exc).__name__
    return MarketSearchOutcome(
        results=results,
        errors=errors,
        calls=tuple(calls),
        retries=0,
    )
