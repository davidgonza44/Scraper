"""TrackerState — serializable fields only. Collect via services."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import reflex as rx
from pydantic import BaseModel, ConfigDict

from bera_price_tracker.application.alibaba_ranking import (
    DEFAULT_OPPORTUNITY_WEIGHT,
    DEFAULT_RELEVANCE_WEIGHT,
    DEFAULT_REPUTATION_WEIGHT,
    DEFAULT_WEIGHTS,
    PRESET_BALANCED,
    PRESET_MORE_OPPORTUNITY,
    PRESET_MORE_RELEVANT,
    PRESET_MORE_REPUTATION,
    RankingWeights,
    clamp_weight,
    validate_ranking_weights,
)
from bera_price_tracker.application.mercadolibre_benchmark import DEFAULT_BENCHMARK_RELEVANCE
from bera_price_tracker.application.search_session import (
    GENERIC_SESSION_UNSET_GENERATION,
    GenericSessionProviderSnapshot,
    owned_generic_session_provider,
)
from bera_price_tracker.application.services import (
    alibaba_credit_warning,
    mercadolibre_credit_warning,
)
from bera_price_tracker.gui import (
    analysis,
    comparison,
    marketplace_summary,
    search_diagnostics,
    search_export,
    search_scope,
    search_session,
    services,
)
from bera_price_tracker.gui.brands import PLATFORM_ALIBABA, PLATFORM_FACEBOOK, PLATFORM_ML
from bera_price_tracker.gui.images import safe_public_image_url
from bera_price_tracker.gui.navigation import (
    DEFAULT_WORKSPACE,
    WORKSPACE_COMPARISONS,
    WORKSPACE_DASHBOARD,
    WORKSPACE_IMPORT,
    WORKSPACE_PRODUCTS,
    WORKSPACE_SEARCHES,
    WORKSPACE_SETTINGS,
    WORKSPACE_TOOLS,
    WORKSPACE_TRACKING,
    marketplace_tab_for,
)
from bera_price_tracker.gui.search_scope import (
    DEFAULT_SEARCH_LIMIT,
    MODE_LABELS,
    MODE_MULTI,
    MODE_SINGLE,
)

UI_INITIAL = "INITIAL"
UI_LOADING = "LOADING"
UI_SUCCESS = "SUCCESS"
UI_EMPTY = "EMPTY"
UI_ERROR = "ERROR"
UI_NOT_CONFIGURED = "NOT_CONFIGURED"

ALIBABA_SORT_BY_LABEL = {
    "Relevancia original": analysis.SORT_ORIGINAL,
    "Precio: menor a mayor": analysis.SORT_PRICE_ASC,
    "Precio: mayor a menor": analysis.SORT_PRICE_DESC,
    "Mejor puntuación": analysis.SORT_SCORE_DESC,
    "Mayor relevancia": analysis.SORT_RELEVANCE_DESC,
    "Mejor ranking general": analysis.SORT_RANKING_DESC,
    "Mayor reputación": analysis.SORT_REPUTATION_DESC,
}
ALIBABA_SORT_LABELS = {value: label for label, value in ALIBABA_SORT_BY_LABEL.items()}
ALIBABA_SCOPE_BY_LABEL = {
    "Todos los precios": analysis.CHART_SCOPE_ALL,
    "Rango típico": analysis.CHART_SCOPE_TYPICAL,
}
ALIBABA_SCOPE_LABELS = {value: label for label, value in ALIBABA_SCOPE_BY_LABEL.items()}
ALIBABA_MIN_RELEVANCE_BY_LABEL = {"Todas": 0, "30+": 30, "60+": 60, "80+": 80}
ALIBABA_MIN_RELEVANCE_LABELS = {
    value: label for label, value in ALIBABA_MIN_RELEVANCE_BY_LABEL.items()
}
ALIBABA_MIN_REPUTATION_BY_LABEL = {"Todas": 0, "50+": 50, "70+": 70, "85+": 85}
ALIBABA_MIN_REPUTATION_LABELS = {
    value: label for label, value in ALIBABA_MIN_REPUTATION_BY_LABEL.items()
}
ALIBABA_RANKING_PRESETS = {
    "Equilibrado": PRESET_BALANCED,
    "Más relevante": PRESET_MORE_RELEVANT,
    "Mejor oportunidad": PRESET_MORE_OPPORTUNITY,
    "Más reputación": PRESET_MORE_REPUTATION,
}
ML_SORT_BY_LABEL = {
    "Original": analysis.SORT_ORIGINAL,
    "Precio: menor a mayor": analysis.SORT_PRICE_ASC,
    "Precio: mayor a menor": analysis.SORT_PRICE_DESC,
    "Mayor relevancia": analysis.SORT_RELEVANCE_DESC,
}
ML_SORT_LABELS = {value: label for label, value in ML_SORT_BY_LABEL.items()}
ML_MIN_RELEVANCE_BY_LABEL = {"Todos": 0, "30+": 30, "60+": 60, "80+": 80}
ML_MIN_RELEVANCE_LABELS = {value: label for label, value in ML_MIN_RELEVANCE_BY_LABEL.items()}


def _ml_row_mapping(row: MercadoLibreResultRow) -> dict[str, object]:
    return {
        "external_id": row.external_id,
        "title": row.title,
        "permalink": row.permalink,
        "price": row.price,
        "price_raw": row.price_raw,
        "currency": row.currency,
        "condition": row.condition,
        "seller_name": row.seller_name,
        "shipping": row.shipping,
        "thumbnail_url": row.thumbnail_url,
        "country": row.country,
        "representative": row.representative,
        "relevance_value": row.relevance_value,
        "relevance": row.relevance,
        "relevance_label": row.relevance_label,
        "is_outlier": row.is_outlier,
    }


def parse_weight_input(value: object, default: int) -> int:
    """Local parsing for slider/input events. Falls back to ``default``."""

    raw: object = value[0] if isinstance(value, list) and value else value
    if isinstance(raw, str):
        try:
            raw = Decimal(raw.strip())
        except (InvalidOperation, ValueError):
            raw = default
    elif isinstance(raw, float):
        raw = Decimal(str(raw))
    return clamp_weight(raw, default)


def clamp_limit(value: int | str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 5
    return max(1, min(5, number))


def _payload_text(item: object, key: str, default: str = "") -> str:
    if not isinstance(item, dict):
        return default
    value = item.get(key, default)
    if value is None:
        return default
    return str(value)


def _official_store_label(value: object) -> str:
    if value is True:
        return "Tienda oficial"
    text = str(value or "").strip()
    if text.casefold() in {"1", "true", "tienda oficial"}:
        return "Tienda oficial"
    return text if text and text != "—" else ""


class GuiModel(BaseModel):
    """Serializable GUI row models. pydantic v2 replacement for deprecated rx.Base."""

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True, use_enum_values=True)


class DetailItem(GuiModel):
    label: str = ""
    value: str = ""


class AlibabaTrackedRow(GuiModel):
    product_id: str = ""
    title: str = ""
    supplier_name: str = ""
    current_price: str = ""
    last_price: str = ""
    published_range: str = ""
    first_price: str = ""
    first_price_tag: str = ""
    baseline: str = ""
    last_updated: str = ""
    variation: str = ""
    history: str = ""
    url: str = ""
    snapshot_count: str = ""
    price_min: str = ""
    price_max: str = ""
    currency: str = ""
    selected: bool = False
    image_url: str = ""
    history_open: bool = False


class AlibabaResultRow(GuiModel):
    title: str = ""
    price: str = ""
    moq: str = ""
    supplier_name: str = ""
    supplier_country: str = ""
    url: str = ""
    image_url: str = ""
    product_id: str = ""
    price_min: str = ""
    price_max: str = ""
    currency: str = ""
    representative: str = ""
    is_followed: bool = False
    is_outlier: bool = False
    score_value: int = 0
    score: str = ""
    score_label: str = ""
    score_price: str = ""
    score_moq: str = ""
    score_info: str = ""
    score_clarity: str = ""
    relevance_value: int = 0
    relevance: str = ""
    relevance_label: str = ""
    relevance_tokens: str = ""
    ranking_value: int = 0
    ranking: str = ""
    ranking_low_match: bool = False
    ranking_tooltip: str = ""
    ranking_reputation_used: bool = False
    reputation_available: bool = False
    reputation_value: int = 0
    reputation: str = "—"
    reputation_label: str = ""
    reputation_coverage: str = ""
    reputation_coverage_label: str = ""
    reputation_service: str = ""
    reputation_reviews: str = ""
    reputation_years: str = ""
    reputation_volume: str = ""
    review_score: str = ""
    review_count: str = ""
    supplier_service_score: str = ""
    gold_supplier_years: str = ""


class MercadoLibreResultRow(GuiModel):
    external_id: str = ""
    title: str = ""
    permalink: str = ""
    price: str = "—"
    price_raw: str = ""
    currency: str = "—"
    condition: str = "—"
    seller_name: str = "—"
    shipping: str = "—"
    thumbnail_url: str = ""
    country: str = "—"
    representative: str = ""
    relevance_value: int = 0
    relevance: str = ""
    relevance_label: str = ""
    relevance_tokens: str = ""
    is_outlier: bool = False
    ranking_value: int = 0
    ranking: str = ""
    ranking_low_match: bool = False
    ranking_tooltip: str = ""
    ranking_reputation_used: bool = False
    score_value: int = 0
    reputation_available: bool = False
    reputation_value: int = 0
    rating_average: str = ""
    review_count: str = ""
    seller_reputation: str = ""
    seller_status: str = ""
    official_store: str = ""


class FacebookProductResultRow(GuiModel):
    external_id: str = ""
    title: str = ""
    permalink: str = ""
    price: str = ""
    price_raw: str = ""
    currency: str = "UNKNOWN"
    formatted_price: str = ""
    source_price_note: str = ""
    usd_price: str = ""
    usd_amount: str = ""
    usd_normalization_status: str = ""
    usd_evidence: str = ""
    usd_basis: str = ""
    usd_provenance: str = ""
    location: str = "—"
    representative: str = ""
    relevance_value: int = 0
    relevance: str = ""
    relevance_label: str = ""
    relevance_tokens: str = ""
    is_outlier: bool = False
    image_url: str = ""


class FacebookCurrencyStatsRow(GuiModel):
    currency: str = ""
    label: str = ""
    basis: str = ""
    source_currencies: str = ""
    normalization_status: str = ""
    evidence: str = ""
    provenance: str = ""
    count: str = "0"
    minimum: str = "unavailable"
    average: str = "unavailable"
    median: str = "unavailable"
    maximum: str = "unavailable"
    p25: str = "unavailable"
    p75: str = "unavailable"
    iqr: str = "unavailable"


class ResultRow(GuiModel):
    title: str = ""
    price: str = ""
    price_raw: str = ""
    currency: str = ""
    compatibility: str = ""
    city: str = ""
    source: str = ""
    url: str = ""
    details_items: list[DetailItem] = []


class SearchProgressRow(GuiModel):
    platform: str = ""
    label: str = ""
    detail: str = ""


class DiagnosticLine(GuiModel):
    label: str = ""
    value: str = ""


class MarketplaceSummaryCard(GuiModel):
    platform: str = ""
    platform_id: str = ""
    status: str = "empty"
    status_label: str = "Sin búsqueda"
    result_count: str = "0"
    minimum: str = "—"
    median: str = "—"
    average: str = "—"
    maximum: str = "—"
    p25: str = "—"
    p75: str = "—"
    range: str = "—"
    currency: str = ""
    basis: str = ""
    meta_one: str = ""
    meta_two: str = ""
    note: str = ""
    rating_available: bool = False
    rating_value: str = ""
    rating_label: str = "Sin calificación"
    rating_filled: int = 0
    details_available: bool = False
    details_open: bool = False
    diagnostic_detail: str = ""
    diagnostic_outcome: str = ""
    diagnostic_lines: list[DiagnosticLine] = []


class ComparisonRow(GuiModel):
    product_title: str = ""
    product_image_url: str = ""
    product_subtitle: str = ""
    product_id: str = ""
    alibaba_has_listing: bool = False
    alibaba_image_url: str = ""
    alibaba_title: str = ""
    alibaba_price: str = ""
    alibaba_range: str = ""
    alibaba_moq: str = ""
    alibaba_supplier: str = ""
    alibaba_relevance: str = ""
    alibaba_match_label: str = ""
    alibaba_url: str = ""
    alibaba_score_value: int = 0
    alibaba_score: str = ""
    alibaba_rating_available: bool = False
    alibaba_rating_filled: int = 0
    alibaba_rating_label: str = "Sin calificación"
    alibaba_rating_caption: str = ""
    alibaba_review_count: str = ""
    alibaba_review_count_line: str = ""
    alibaba_trust_line: str = ""
    opportunity_available: bool = False
    opportunity_score: str = "0"
    opportunity_percent: str = "0%"
    opportunity_ring: str = ""
    facebook_has_listing: bool = False
    facebook_image_url: str = ""
    facebook_title: str = ""
    facebook_price: str = ""
    facebook_source_note: str = ""
    facebook_usd_note: str = ""
    facebook_location: str = ""
    facebook_relevance: str = ""
    facebook_match_label: str = ""
    facebook_url: str = ""
    facebook_rating_available: bool = False
    facebook_rating_filled: int = 0
    facebook_rating_label: str = "Sin calificación"
    ml_has_listing: bool = False
    ml_image_url: str = ""
    ml_title: str = ""
    ml_price: str = ""
    ml_condition: str = ""
    ml_seller: str = ""
    ml_shipping: str = ""
    ml_official_store: str = ""
    ml_relevance: str = ""
    ml_match_label: str = ""
    ml_url: str = ""
    ml_rating_available: bool = False
    ml_rating_filled: int = 0
    ml_rating_label: str = "Sin calificación"
    ml_rating_caption: str = ""
    ml_review_count: str = ""
    ml_review_count_line: str = ""
    ml_trust_line: str = ""
    analysis_available: bool = False
    analysis_heading: str = "Análisis no disponible"
    analysis_detail: str = ""
    rank: int = 0
    identity_confirmed: bool = False
    disclosure: str = ""
    resultado_label: str = ""
    comparison_kind: str = "association"


class GenericAlibabaSessionSnapshot(GuiModel):
    generation: int = GENERIC_SESSION_UNSET_GENERATION
    status: str = UI_INITIAL
    rows: list[AlibabaResultRow] = []
    summary: dict[str, str] = {}
    stats_raw: dict[str, str] = {}
    error: str = ""
    requested_limit: int = 0


class GenericFacebookSessionSnapshot(GuiModel):
    generation: int = GENERIC_SESSION_UNSET_GENERATION
    status: str = UI_INITIAL
    rows: list[FacebookProductResultRow] = []
    summary: dict[str, str] = {}
    statistics: list[FacebookCurrencyStatsRow] = []
    error: str = ""
    requested_limit: int = 0


class GenericMercadoLibreSessionSnapshot(GuiModel):
    generation: int = GENERIC_SESSION_UNSET_GENERATION
    status: str = UI_INITIAL
    rows: list[MercadoLibreResultRow] = []
    summary: dict[str, str] = {}
    diagnostic_summary: dict[str, str] = {}
    error: str = ""
    requested_limit: int = 0


class TrackerState(rx.State):
    workspace_view: str = DEFAULT_WORKSPACE
    alibaba_history_open_ids: list[str] = []
    query: str = "pastillas sbr"
    city: str = "caracas"
    limit: int = 5
    is_loading: bool = False
    error_message: str = ""
    results: list[ResultRow] = []
    summary: dict[str, str] = {}
    ui_status: str = UI_INITIAL
    alibaba_query: str = ""
    alibaba_limit: int = 20
    alibaba_results: list[AlibabaResultRow] = []
    alibaba_is_loading: bool = False
    alibaba_error: str = ""
    alibaba_summary: dict[str, str] = {}
    alibaba_ui_status: str = UI_INITIAL
    alibaba_warning: str = ""
    alibaba_stats_raw: dict[str, str] = {}
    alibaba_tracked_rows: list[AlibabaTrackedRow] = []
    alibaba_tracking_error: str = ""
    alibaba_refresh_selected_ids: list[str] = []
    alibaba_refresh_pending_ids: list[str] = []
    alibaba_refresh_operation_id: str = ""
    alibaba_refresh_confirm_open: bool = False
    alibaba_refresh_confirm_intro: str = ""
    alibaba_refresh_confirm_count: str = ""
    alibaba_refresh_is_loading: bool = False
    alibaba_refresh_summary: dict[str, str] = {}
    alibaba_sort: str = analysis.SORT_ORIGINAL
    alibaba_price_min: str = ""
    alibaba_price_max: str = ""
    alibaba_hide_outliers: bool = False
    alibaba_min_relevance: int = 0
    alibaba_min_reputation: int = 0
    alibaba_relevance_weight: int = DEFAULT_RELEVANCE_WEIGHT
    alibaba_opportunity_weight: int = DEFAULT_OPPORTUNITY_WEIGHT
    alibaba_reputation_weight: int = DEFAULT_REPUTATION_WEIGHT
    alibaba_applied_relevance_weight: int = DEFAULT_RELEVANCE_WEIGHT
    alibaba_applied_opportunity_weight: int = DEFAULT_OPPORTUNITY_WEIGHT
    alibaba_applied_reputation_weight: int = DEFAULT_REPUTATION_WEIGHT
    alibaba_chart_scope: str = analysis.CHART_SCOPE_ALL
    marketplace_tab: str = "facebook"
    ml_query: str = ""
    ml_limit: int = 10
    ml_results: list[MercadoLibreResultRow] = []
    ml_is_loading: bool = False
    ml_error: str = ""
    ml_summary: dict[str, str] = {}
    ml_ui_status: str = UI_INITIAL
    ml_warning: str = ""
    ml_sort: str = analysis.SORT_ORIGINAL
    ml_price_min: str = ""
    ml_price_max: str = ""
    ml_hide_outliers: bool = False
    ml_min_relevance: int = DEFAULT_BENCHMARK_RELEVANCE
    ml_comparison: dict[str, str] = {}
    ml_has_comparison: bool = False
    ml_has_alibaba_context: bool = False
    ml_alibaba_context: dict[str, str] = {}
    ml_last_search_query: str = ""
    ml_association_product_id: str = ""
    ml_translated_title: str = ""
    ml_translation_ui_status: str = UI_INITIAL
    ml_translation_error: str = ""
    ml_translation_warning: str = ""
    ml_translation_is_loading: bool = False
    ml_translation_generation: int = 0
    ml_translation_source_language: str = ""
    ml_query_origin: str = ""
    ml_results_from_generic_session: bool = False
    generic_session_alibaba: GenericAlibabaSessionSnapshot = GenericAlibabaSessionSnapshot()
    generic_session_facebook: GenericFacebookSessionSnapshot = GenericFacebookSessionSnapshot()
    generic_session_ml: GenericMercadoLibreSessionSnapshot = GenericMercadoLibreSessionSnapshot()
    facebook_product_query: str = ""
    facebook_product_city: str = "caracas"
    facebook_product_limit: int = 5
    facebook_product_results: list[FacebookProductResultRow] = []
    facebook_product_statistics: list[FacebookCurrencyStatsRow] = []
    facebook_product_summary: dict[str, str] = {}
    facebook_product_ui_status: str = UI_INITIAL
    facebook_product_error: str = ""
    facebook_product_is_loading: bool = False
    facebook_product_alibaba_context: dict[str, str] = {}
    facebook_product_has_alibaba_context: bool = False
    facebook_product_provenance: dict[str, str] = {}
    facebook_product_last_search_query: str = ""
    facebook_product_association_product_id: str = ""
    facebook_product_translated_title: str = ""
    facebook_product_translation_ui_status: str = UI_INITIAL
    facebook_product_translation_error: str = ""
    facebook_product_translation_warning: str = ""
    facebook_product_translation_is_loading: bool = False
    facebook_product_translation_generation: int = 0
    facebook_product_query_origin: str = ""
    search_mode: str = MODE_MULTI
    search_platform: str = PLATFORM_ALIBABA
    search_query: str = ""
    search_limit: int = DEFAULT_SEARCH_LIMIT
    search_error: str = ""
    search_generation: int = 0
    search_session_active: bool = False
    search_started_monotonic: str = ""
    search_elapsed_ms: int = 0
    search_completed_at: str = ""
    search_session_query: str = ""
    search_session_limit: int = 0
    search_session_mode: str = ""
    search_session_platform: str = ""
    search_session_providers: list[str] = []
    diagnostic_open_platforms: list[str] = []
    alibaba_negotiation_product_key: str = ""
    alibaba_negotiation_quantity: str = "40"
    alibaba_negotiation_resale: str = ""
    alibaba_negotiation_margin: str = ""
    alibaba_negotiation_shipping: str = ""
    alibaba_negotiation_duties: str = ""
    alibaba_negotiation_other: str = ""
    alibaba_negotiation_aggressiveness: str = "50"
    alibaba_negotiation_ladder: str = ""
    alibaba_negotiation_error: str = ""
    alibaba_negotiation_has_plan: bool = False
    alibaba_negotiation_public: str = ""
    alibaba_negotiation_opening: str = ""
    alibaba_negotiation_target: str = ""
    alibaba_negotiation_ceiling: str = ""
    alibaba_negotiation_next_tier: str = ""
    alibaba_negotiation_proximity: str = ""
    alibaba_negotiation_quantity_shown: str = ""
    alibaba_negotiation_explanation: str = ""
    alibaba_negotiation_attractiveness: str = ""
    alibaba_negotiation_message: str = ""
    alibaba_negotiation_supplier_text: str = ""
    alibaba_negotiation_analysis_summary: str = ""
    alibaba_negotiation_analysis_decision: str = ""
    alibaba_negotiation_analysis_notes: str = ""
    alibaba_negotiation_is_drafting: bool = False
    alibaba_negotiation_plan_payload: dict[str, str] = {}
    alibaba_negotiation_original_ceiling: str = ""
    alibaba_negotiation_profitability_ceiling: str = ""
    alibaba_negotiation_effective_ceiling: str = ""
    alibaba_negotiation_ceiling_provenance: str = ""
    alibaba_negotiation_profitability_note: str = ""
    alibaba_negotiation_has_profitability: bool = False
    alibaba_negotiation_profitability_hint: str = ""
    alibaba_landed_quantity: str = "40"
    alibaba_landed_supplier_price: str = ""
    alibaba_landed_cartons: str = ""
    alibaba_landed_units_per_carton: str = ""
    alibaba_landed_length: str = ""
    alibaba_landed_width: str = ""
    alibaba_landed_height: str = ""
    alibaba_landed_weight: str = ""
    alibaba_landed_rate: str = ""
    alibaba_landed_rate_confirmed: bool = False
    alibaba_landed_has_battery: bool = False
    alibaba_landed_battery_multiplier: str = "1"
    alibaba_landed_wood_surcharge: str = ""
    alibaba_landed_insurance: str = ""
    alibaba_landed_other_logistics: str = ""
    alibaba_landed_other_import: str = ""
    alibaba_landed_sale_price: str = ""
    alibaba_landed_margin: str = ""
    alibaba_landed_error: str = ""
    alibaba_landed_has_result: bool = False
    alibaba_landed_result: dict[str, str] = {}
    alibaba_landed_draft_product_id: str = ""
    alibaba_landed_product_id: str = ""

    def set_query(self, value: str) -> None:
        self.query = value

    def set_city(self, value: str) -> None:
        self.city = value

    def set_limit(self, value: str | int) -> None:
        self.limit = clamp_limit(value)

    @rx.event(background=True)
    async def search(self) -> None:
        async with self:
            if self.is_loading:
                return
            self.is_loading = True
            self.error_message = ""
            self.ui_status = UI_LOADING
            query = self.query
            city = self.city
            limit = clamp_limit(self.limit)
            self.limit = limit

        try:
            payload = await asyncio.to_thread(
                services.run_facebook_search,
                query,
                city,
                limit,
            )
        except Exception as exc:  # noqa: BLE001 — sanitized before display
            message = services.sanitize_error(exc)
            async with self:
                self.is_loading = False
                self.error_message = message
                self.results = []
                self.summary = {}
                self.ui_status = UI_ERROR
            return

        rows: list[ResultRow] = []
        for item in payload.get("results") or []:
            details = [
                DetailItem(label=str(entry.get("label", "")), value=str(entry.get("value", "")))
                for entry in (item.get("details_items") or [])
            ]
            rows.append(
                ResultRow(
                    title=str(item.get("title", "")),
                    price=str(item.get("price", "")),
                    price_raw=str(item.get("price_raw", "")),
                    currency=str(item.get("currency", "")),
                    compatibility=str(item.get("compatibility", "")),
                    city=str(item.get("city", "")),
                    source=str(item.get("source", "")),
                    url=str(item.get("url", "")),
                    details_items=details,
                )
            )

        async with self:
            self.is_loading = False
            self.error_message = ""
            self.results = rows
            self.summary = dict(payload.get("summary") or {})
            self.ui_status = str(payload.get("ui_status") or UI_EMPTY)

    def _open_workspace(self, view: str) -> None:
        self.workspace_view = view
        self.marketplace_tab = marketplace_tab_for(view)

    def show_dashboard(self) -> None:
        self._open_workspace(WORKSPACE_DASHBOARD)

    def show_searches(self) -> None:
        self._open_workspace(WORKSPACE_SEARCHES)
        self.refresh_alibaba_tracking()

    def show_products(self) -> None:
        self._open_workspace(WORKSPACE_PRODUCTS)

    def show_comparisons(self) -> None:
        self._open_workspace(WORKSPACE_COMPARISONS)

    def show_tracking(self) -> None:
        self._open_workspace(WORKSPACE_TRACKING)
        self.refresh_alibaba_tracking()

    def show_import(self) -> None:
        self._open_workspace(WORKSPACE_IMPORT)

    def show_tools(self) -> None:
        self._open_workspace(WORKSPACE_TOOLS)

    def show_settings(self) -> None:
        self._open_workspace(WORKSPACE_SETTINGS)

    def show_facebook_tab(self) -> None:
        self._open_workspace(WORKSPACE_TOOLS)

    def show_facebook_products_tab(self) -> None:
        self._open_workspace(WORKSPACE_PRODUCTS)

    def show_alibaba_tab(self) -> None:
        self._open_workspace(WORKSPACE_SEARCHES)
        self.refresh_alibaba_tracking()

    def show_mercadolibre_tab(self) -> None:
        self._open_workspace(WORKSPACE_COMPARISONS)

    def toggle_alibaba_history(self, product_id: str) -> None:
        if product_id in self.alibaba_history_open_ids:
            self.alibaba_history_open_ids = [
                item for item in self.alibaba_history_open_ids if item != product_id
            ]
            return
        self.alibaba_history_open_ids = [*self.alibaba_history_open_ids, product_id]

    def set_alibaba_negotiation_product_key(self, value: str) -> None:
        key = value.split(" · ", 1)[0].strip()
        self.alibaba_negotiation_product_key = key

    def set_alibaba_negotiation_quantity(self, value: str) -> None:
        self.alibaba_negotiation_quantity = value

    def set_alibaba_negotiation_resale(self, value: str) -> None:
        self.alibaba_negotiation_resale = value

    def set_alibaba_negotiation_margin(self, value: str) -> None:
        self.alibaba_negotiation_margin = value

    def set_alibaba_negotiation_shipping(self, value: str) -> None:
        self.alibaba_negotiation_shipping = value

    def set_alibaba_negotiation_duties(self, value: str) -> None:
        self.alibaba_negotiation_duties = value

    def set_alibaba_negotiation_other(self, value: str) -> None:
        self.alibaba_negotiation_other = value

    def set_alibaba_negotiation_aggressiveness(self, value: str) -> None:
        self.alibaba_negotiation_aggressiveness = value

    def set_alibaba_negotiation_ladder(self, value: str) -> None:
        self.alibaba_negotiation_ladder = value

    def set_alibaba_negotiation_message(self, value: str) -> None:
        self.alibaba_negotiation_message = value

    def set_alibaba_negotiation_supplier_text(self, value: str) -> None:
        self.alibaba_negotiation_supplier_text = value

    def _alibaba_negotiation_catalog(self) -> list[dict[str, str]]:
        tracked = [
            {
                "product_id": row.product_id,
                "title": row.title,
                "supplier_name": row.supplier_name,
                "last_price": row.last_price,
                "price_min": row.price_min,
                "price_max": row.price_max,
                "currency": row.currency,
            }
            for row in self.alibaba_tracked_rows
        ]
        results = [
            {
                "product_id": row.product_id,
                "title": row.title,
                "supplier_name": row.supplier_name,
                "price_min": row.price_min,
                "price_max": row.price_max,
                "moq": row.moq,
                "representative": row.representative,
                "currency": row.currency,
            }
            for row in self.alibaba_results
        ]
        return services.build_alibaba_negotiation_catalog(tracked, results)

    def _selected_negotiation_product(self) -> dict[str, str] | None:
        for item in self._alibaba_negotiation_catalog():
            if item["key"] == self.alibaba_negotiation_product_key:
                return item
        return None

    def _apply_negotiation_plan(self, row: dict[str, str]) -> None:
        self.alibaba_negotiation_has_plan = True
        self.alibaba_negotiation_error = ""
        self.alibaba_negotiation_public = row.get("public_unit_price", "")
        self.alibaba_negotiation_opening = row.get("opening_offer", "")
        self.alibaba_negotiation_target = row.get("target_price", "")
        self.alibaba_negotiation_ceiling = row.get("ceiling_price", "")
        self.alibaba_negotiation_next_tier = row.get("next_tier", "")
        self.alibaba_negotiation_proximity = row.get("tier_proximity", "")
        self.alibaba_negotiation_quantity_shown = row.get("desired_quantity", "")
        self.alibaba_negotiation_explanation = row.get("explanation", "")
        self.alibaba_negotiation_attractiveness = row.get("attractiveness", "")
        self.alibaba_negotiation_plan_payload = dict(row)
        self.alibaba_negotiation_original_ceiling = row.get("original_ceiling", "")
        self.alibaba_negotiation_profitability_ceiling = row.get("profitability_ceiling", "")
        self.alibaba_negotiation_effective_ceiling = row.get("effective_ceiling", "")
        self.alibaba_negotiation_ceiling_provenance = row.get("ceiling_provenance", "")
        self.alibaba_negotiation_profitability_note = row.get("profitability_note", "")
        self.alibaba_negotiation_has_profitability = row.get("profitability_applied") == "1"
        self.alibaba_negotiation_profitability_hint = ""
        self.alibaba_negotiation_message = ""
        self.alibaba_negotiation_analysis_summary = ""
        self.alibaba_negotiation_analysis_decision = ""
        self.alibaba_negotiation_analysis_notes = ""

    def calculate_alibaba_negotiation(self) -> None:
        try:
            row = services.calculate_alibaba_negotiation(
                self._selected_negotiation_product(),
                desired_quantity=self.alibaba_negotiation_quantity,
                expected_resale_price=self.alibaba_negotiation_resale,
                target_margin_percent=self.alibaba_negotiation_margin,
                shipping_per_unit=self.alibaba_negotiation_shipping,
                duties_per_unit=self.alibaba_negotiation_duties,
                other_costs_per_unit=self.alibaba_negotiation_other,
                negotiation_aggressiveness=self.alibaba_negotiation_aggressiveness,
                ladder_text=self.alibaba_negotiation_ladder,
            )
        except Exception as exc:  # noqa: BLE001 — sanitized before display
            self.alibaba_negotiation_error = services.sanitize_alibaba_negotiation_error(exc)
            self.alibaba_negotiation_has_plan = False
            return
        self._apply_negotiation_plan(row)
        self.alibaba_negotiation_has_profitability = False
        self.alibaba_negotiation_original_ceiling = ""
        self.alibaba_negotiation_profitability_ceiling = ""
        self.alibaba_negotiation_effective_ceiling = ""
        self.alibaba_negotiation_ceiling_provenance = ""
        self.alibaba_negotiation_profitability_note = ""

    def apply_alibaba_profitability_ceiling(self) -> None:
        if not self.alibaba_negotiation_has_plan:
            self.alibaba_negotiation_profitability_hint = (
                "Calcula la estrategia antes de aplicar rentabilidad."
            )
            return
        plan_product_id = str(self.alibaba_negotiation_plan_payload.get("product_id") or "").strip()
        landed_product_id = self.alibaba_landed_product_id.strip()
        if not self.alibaba_landed_has_result:
            landed = None
        elif not comparison.landed_context_applies(plan_product_id, landed_product_id):
            self.alibaba_negotiation_profitability_hint = (
                services.ALIBABA_PROFITABILITY_PRODUCT_MISMATCH
            )
            return
        else:
            landed = self.alibaba_landed_result
        try:
            row = services.apply_alibaba_profitability_ceiling(
                self.alibaba_negotiation_plan_payload,
                landed,
            )
        except Exception as exc:  # noqa: BLE001 — sanitized before display
            message = services.sanitize_alibaba_landed_cost_error(exc)
            if message == services.ALIBABA_LANDED_COST_GENERIC_ERROR:
                message = services.sanitize_alibaba_negotiation_error(exc)
            self.alibaba_negotiation_profitability_hint = message
            return
        self._apply_negotiation_plan(row)

    @rx.event(background=True)
    async def generate_alibaba_negotiation_opening(self) -> None:
        async with self:
            if self.alibaba_negotiation_is_drafting or not self.alibaba_negotiation_has_plan:
                return
            self.alibaba_negotiation_is_drafting = True
            self.alibaba_negotiation_error = ""
            payload = dict(self.alibaba_negotiation_plan_payload)
        try:
            message = await asyncio.to_thread(
                services.generate_alibaba_negotiation_opening,
                payload,
            )
        except Exception as exc:  # noqa: BLE001 — sanitized before display
            async with self:
                self.alibaba_negotiation_is_drafting = False
                self.alibaba_negotiation_error = services.sanitize_alibaba_negotiation_error(exc)
            return
        async with self:
            self.alibaba_negotiation_is_drafting = False
            self.alibaba_negotiation_message = message

    @rx.event(background=True)
    async def analyze_alibaba_supplier_reply(self) -> None:
        async with self:
            if self.alibaba_negotiation_is_drafting or not self.alibaba_negotiation_has_plan:
                return
            self.alibaba_negotiation_is_drafting = True
            self.alibaba_negotiation_error = ""
            payload = dict(self.alibaba_negotiation_plan_payload)
            supplier_text = self.alibaba_negotiation_supplier_text
        try:
            analysis_row = await asyncio.to_thread(
                services.analyze_alibaba_supplier_reply,
                payload,
                supplier_text,
            )
        except Exception as exc:  # noqa: BLE001 — sanitized before display
            async with self:
                self.alibaba_negotiation_is_drafting = False
                self.alibaba_negotiation_error = services.sanitize_alibaba_negotiation_error(exc)
            return
        async with self:
            self.alibaba_negotiation_is_drafting = False
            self.alibaba_negotiation_analysis_summary = analysis_row.get("response_summary", "")
            self.alibaba_negotiation_analysis_decision = analysis_row.get("decision", "")
            notes = analysis_row.get("notes", "")
            quoted = analysis_row.get("quoted_unit_price", "")
            authorized = analysis_row.get("authorized_price", "")
            self.alibaba_negotiation_analysis_notes = (
                f"{notes} Precio citado: {quoted}. Precio autorizado: {authorized}."
            )

    @rx.event(background=True)
    async def generate_alibaba_negotiation_reply(self) -> None:
        async with self:
            if self.alibaba_negotiation_is_drafting or not self.alibaba_negotiation_has_plan:
                return
            self.alibaba_negotiation_is_drafting = True
            self.alibaba_negotiation_error = ""
            payload = dict(self.alibaba_negotiation_plan_payload)
            supplier_text = self.alibaba_negotiation_supplier_text
        try:
            message = await asyncio.to_thread(
                services.generate_alibaba_negotiation_reply,
                payload,
                supplier_text,
            )
        except Exception as exc:  # noqa: BLE001 — sanitized before display
            async with self:
                self.alibaba_negotiation_is_drafting = False
                self.alibaba_negotiation_error = services.sanitize_alibaba_negotiation_error(exc)
            return
        async with self:
            self.alibaba_negotiation_is_drafting = False
            self.alibaba_negotiation_message = message

    def set_alibaba_landed_quantity(self, value: str) -> None:
        self.alibaba_landed_quantity = value

    def set_alibaba_landed_supplier_price(self, value: str) -> None:
        self.alibaba_landed_supplier_price = value

    def set_alibaba_landed_cartons(self, value: str) -> None:
        self.alibaba_landed_cartons = value

    def set_alibaba_landed_units_per_carton(self, value: str) -> None:
        self.alibaba_landed_units_per_carton = value

    def set_alibaba_landed_length(self, value: str) -> None:
        self.alibaba_landed_length = value

    def set_alibaba_landed_width(self, value: str) -> None:
        self.alibaba_landed_width = value

    def set_alibaba_landed_height(self, value: str) -> None:
        self.alibaba_landed_height = value

    def set_alibaba_landed_weight(self, value: str) -> None:
        self.alibaba_landed_weight = value

    def set_alibaba_landed_rate(self, value: str) -> None:
        self.alibaba_landed_rate = value

    def set_alibaba_landed_rate_confirmed(self, value: bool) -> None:
        self.alibaba_landed_rate_confirmed = bool(value)

    def set_alibaba_landed_has_battery(self, value: bool) -> None:
        self.alibaba_landed_has_battery = bool(value)

    def set_alibaba_landed_battery_multiplier(self, value: str) -> None:
        self.alibaba_landed_battery_multiplier = value

    def set_alibaba_landed_wood_surcharge(self, value: str) -> None:
        self.alibaba_landed_wood_surcharge = value

    def set_alibaba_landed_insurance(self, value: str) -> None:
        self.alibaba_landed_insurance = value

    def set_alibaba_landed_other_logistics(self, value: str) -> None:
        self.alibaba_landed_other_logistics = value

    def set_alibaba_landed_other_import(self, value: str) -> None:
        self.alibaba_landed_other_import = value

    def set_alibaba_landed_sale_price(self, value: str) -> None:
        self.alibaba_landed_sale_price = value

    def set_alibaba_landed_margin(self, value: str) -> None:
        self.alibaba_landed_margin = value

    def use_negotiation_values_for_landed_cost(self) -> None:
        """Minimal wiring: copy quantity and opening offer from the negotiation plan."""

        payload = self.alibaba_negotiation_plan_payload
        if not payload:
            return
        self.alibaba_landed_draft_product_id = str(payload.get("product_id") or "").strip()
        self.alibaba_landed_quantity = payload.get("desired_quantity", self.alibaba_landed_quantity)
        opening = payload.get("opening_offer", "")
        if opening:
            self.alibaba_landed_supplier_price = opening

    def calculate_alibaba_landed_cost(self) -> None:
        self._invalidate_ml_comparison()
        try:
            row = services.calculate_alibaba_landed_cost(
                quantity=self.alibaba_landed_quantity,
                supplier_unit_price=self.alibaba_landed_supplier_price,
                cartons=self.alibaba_landed_cartons,
                units_per_carton=self.alibaba_landed_units_per_carton,
                carton_length_cm=self.alibaba_landed_length,
                carton_width_cm=self.alibaba_landed_width,
                carton_height_cm=self.alibaba_landed_height,
                gross_weight_kg_per_carton=self.alibaba_landed_weight,
                rate_usd_per_cbm=self.alibaba_landed_rate,
                rate_confirmed=self.alibaba_landed_rate_confirmed,
                has_battery=self.alibaba_landed_has_battery,
                battery_multiplier=self.alibaba_landed_battery_multiplier,
                wood_surcharge=self.alibaba_landed_wood_surcharge,
                insurance=self.alibaba_landed_insurance,
                other_shipping_costs=self.alibaba_landed_other_logistics,
                other_import_costs=self.alibaba_landed_other_import,
                expected_sale_price=self.alibaba_landed_sale_price,
                target_margin_percent=self.alibaba_landed_margin,
                product_title=self.alibaba_negotiation_plan_payload.get("title", ""),
            )
        except Exception as exc:  # noqa: BLE001 — sanitized before display
            self.alibaba_landed_error = services.sanitize_alibaba_landed_cost_error(exc)
            self.alibaba_landed_has_result = False
            self.alibaba_landed_result = {}
            self.alibaba_landed_product_id = ""
            return
        self.alibaba_landed_error = ""
        self.alibaba_landed_has_result = True
        self.alibaba_landed_result = row
        self.alibaba_landed_product_id = self.alibaba_landed_draft_product_id

    def set_alibaba_query(self, value: str) -> None:
        self.alibaba_query = value

    def set_search_query(self, value: str) -> None:
        self.search_query = value
        self.search_error = ""

    def clear_search_query(self) -> None:
        self.search_query = ""
        self.search_error = ""

    def set_search_mode_multi(self) -> None:
        self.search_mode = MODE_MULTI
        self.search_error = ""

    def set_search_mode_single(self) -> None:
        self.search_mode = MODE_SINGLE
        self.search_error = ""

    def set_search_platform_alibaba(self) -> None:
        self.search_platform = PLATFORM_ALIBABA
        self.search_mode = MODE_SINGLE
        self.search_error = ""

    def set_search_platform_facebook(self) -> None:
        self.search_platform = PLATFORM_FACEBOOK
        self.search_mode = MODE_SINGLE
        self.search_error = ""

    def set_search_platform_ml(self) -> None:
        self.search_platform = PLATFORM_ML
        self.search_mode = MODE_SINGLE
        self.search_error = ""

    def set_search_limit(self, value: str | int) -> None:
        try:
            self.search_limit = search_scope.validate_search_limit(value)
            self.search_error = ""
        except ValueError as exc:
            self.search_error = str(exc)

    def set_alibaba_limit(self, value: str | int) -> None:
        try:
            self.alibaba_limit = int(value)
        except (TypeError, ValueError):
            self.alibaba_limit = 0
        self.alibaba_warning = alibaba_credit_warning(self.alibaba_limit) or ""

    @rx.event(background=True)
    async def search_alibaba(self) -> None:
        async with self:
            if not services.can_start_alibaba_search(self.alibaba_is_loading):
                return
            query = self.alibaba_query
            limit = self.alibaba_limit
            if not isinstance(query, str) or not query.strip():
                self.alibaba_error = services.ALIBABA_QUERY_ERROR
                self.alibaba_results = []
                self.alibaba_summary = {}
                self.alibaba_ui_status = UI_ERROR
                self.alibaba_is_loading = False
                return
            if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 500:
                self.alibaba_error = services.ALIBABA_LIMIT_ERROR
                self.alibaba_results = []
                self.alibaba_summary = {}
                self.alibaba_ui_status = UI_ERROR
                self.alibaba_is_loading = False
                return
            self.alibaba_is_loading = True
            self.alibaba_error = ""
            self.alibaba_warning = alibaba_credit_warning(limit) or ""
            self.alibaba_ui_status = UI_LOADING
            generation = self.search_generation

        try:
            payload = await asyncio.to_thread(
                services.run_alibaba_search,
                query,
                limit,
            )
        except Exception as exc:  # noqa: BLE001 - sanitized before display
            message = services.sanitize_alibaba_error(exc)
            async with self:
                self._finalize_alibaba_search(
                    request_query=query,
                    request_limit=limit,
                    error_message=message,
                    request_generation=generation,
                )
            return

        rows = [
            AlibabaResultRow(
                title=str(item.get("title", "")),
                price=str(item.get("price", "")),
                moq=str(item.get("moq", "")),
                supplier_name=str(item.get("supplier_name", "")),
                supplier_country=str(item.get("supplier_country", "")),
                url=str(item.get("url", "")),
                image_url=safe_public_image_url(item.get("image_url", "")),
                representative=str(item.get("representative", "")),
                product_id=str(item.get("product_id", "")),
                price_min=str(item.get("price_min", "")),
                price_max=str(item.get("price_max", "")),
                currency=str(item.get("currency", "")),
                is_outlier=bool(item.get("is_outlier", False)),
                score_value=int(item.get("score_value", 0) or 0),
                score=str(item.get("score", "")),
                score_label=str(item.get("score_label", "")),
                score_price=str(item.get("score_price", "")),
                score_moq=str(item.get("score_moq", "")),
                score_info=str(item.get("score_info", "")),
                score_clarity=str(item.get("score_clarity", "")),
                relevance_value=int(item.get("relevance_value", 0) or 0),
                relevance=str(item.get("relevance", "")),
                relevance_label=str(item.get("relevance_label", "")),
                relevance_tokens=str(item.get("relevance_tokens", "")),
                reputation_available=bool(item.get("reputation_available", False)),
                reputation_value=int(item.get("reputation_value", 0) or 0),
                reputation=str(item.get("reputation", "—")),
                reputation_label=str(item.get("reputation_label", "")),
                reputation_coverage=str(item.get("reputation_coverage", "")),
                reputation_coverage_label=str(item.get("reputation_coverage_label", "")),
                reputation_service=str(item.get("reputation_service", "")),
                reputation_reviews=str(item.get("reputation_reviews", "")),
                reputation_years=str(item.get("reputation_years", "")),
                reputation_volume=str(item.get("reputation_volume", "")),
                review_score=str(item.get("review_score", "")),
                review_count=_payload_text(item, "review_count"),
                supplier_service_score=_payload_text(item, "supplier_service_score"),
                gold_supplier_years=_payload_text(item, "gold_supplier_years"),
            )
            for item in payload.get("results") or []
        ]
        async with self:
            self._finalize_alibaba_search(
                request_query=query,
                request_limit=limit,
                rows=rows,
                summary=dict(payload.get("summary") or {}),
                stats_raw=dict(payload.get("stats_raw") or {}),
                ui_status=str(payload.get("ui_status") or UI_EMPTY),
                request_generation=generation,
            )

    def set_alibaba_sort(self, value: str) -> None:
        self.alibaba_sort = ALIBABA_SORT_BY_LABEL.get(value, analysis.SORT_ORIGINAL)

    def set_alibaba_price_min(self, value: str) -> None:
        self.alibaba_price_min = value

    def set_alibaba_price_max(self, value: str) -> None:
        self.alibaba_price_max = value

    def set_alibaba_hide_outliers(self, value: bool) -> None:
        self.alibaba_hide_outliers = bool(value)

    def set_alibaba_chart_scope(self, value: str) -> None:
        self.alibaba_chart_scope = ALIBABA_SCOPE_BY_LABEL.get(value, analysis.CHART_SCOPE_ALL)

    def set_alibaba_min_relevance(self, value: str) -> None:
        self.alibaba_min_relevance = ALIBABA_MIN_RELEVANCE_BY_LABEL.get(value, 0)

    def set_alibaba_min_reputation(self, value: str) -> None:
        self.alibaba_min_reputation = ALIBABA_MIN_REPUTATION_BY_LABEL.get(value, 0)

    def _apply_weights_if_valid(self) -> None:
        error = validate_ranking_weights(
            self.alibaba_relevance_weight,
            self.alibaba_opportunity_weight,
            self.alibaba_reputation_weight,
        )
        if not error:
            self.alibaba_applied_relevance_weight = self.alibaba_relevance_weight
            self.alibaba_applied_opportunity_weight = self.alibaba_opportunity_weight
            self.alibaba_applied_reputation_weight = self.alibaba_reputation_weight

    def _set_ranking_weights(self, weights: RankingWeights) -> None:
        self.alibaba_relevance_weight = weights.relevance
        self.alibaba_opportunity_weight = weights.opportunity
        self.alibaba_reputation_weight = weights.reputation
        self._apply_weights_if_valid()

    def set_alibaba_relevance_weight(self, value: object) -> None:
        self.alibaba_relevance_weight = parse_weight_input(value, DEFAULT_RELEVANCE_WEIGHT)
        self._apply_weights_if_valid()

    def set_alibaba_opportunity_weight(self, value: object) -> None:
        self.alibaba_opportunity_weight = parse_weight_input(value, DEFAULT_OPPORTUNITY_WEIGHT)
        self._apply_weights_if_valid()

    def set_alibaba_reputation_weight(self, value: object) -> None:
        self.alibaba_reputation_weight = parse_weight_input(value, DEFAULT_REPUTATION_WEIGHT)
        self._apply_weights_if_valid()

    def set_alibaba_ranking_preset(self, value: str) -> None:
        self._set_ranking_weights(ALIBABA_RANKING_PRESETS.get(value, DEFAULT_WEIGHTS))

    def apply_ranking_preset_balanced(self) -> None:
        self._set_ranking_weights(PRESET_BALANCED)

    def apply_ranking_preset_more_relevant(self) -> None:
        self._set_ranking_weights(PRESET_MORE_RELEVANT)

    def apply_ranking_preset_more_opportunity(self) -> None:
        self._set_ranking_weights(PRESET_MORE_OPPORTUNITY)

    def apply_ranking_preset_more_reputation(self) -> None:
        self._set_ranking_weights(PRESET_MORE_REPUTATION)

    def clear_alibaba_filters(self) -> None:
        self.alibaba_sort = analysis.SORT_ORIGINAL
        self.alibaba_price_min = ""
        self.alibaba_price_max = ""
        self.alibaba_hide_outliers = False
        self.alibaba_min_relevance = 0
        self.alibaba_min_reputation = 0
        self._set_ranking_weights(DEFAULT_WEIGHTS)
        self.alibaba_chart_scope = analysis.CHART_SCOPE_ALL

    def _finalize_alibaba_search(
        self,
        *,
        request_query: str,
        request_limit: int,
        rows: list[AlibabaResultRow] | None = None,
        summary: dict[str, str] | None = None,
        stats_raw: dict[str, str] | None = None,
        ui_status: str = "",
        error_message: str | None = None,
        request_generation: int | None = None,
        commit_generic_session: bool = False,
    ) -> None:
        if request_generation is not None and request_generation != self.search_generation:
            return
        live_matches = (
            request_query.strip() == self.alibaba_query.strip()
            and request_limit == self.alibaba_limit
        )
        if commit_generic_session:
            if error_message is not None:
                self._replace_generic_session_alibaba(
                    status=UI_ERROR,
                    rows=[],
                    summary={},
                    stats_raw={},
                    error=error_message,
                )
            else:
                self._replace_generic_session_alibaba(
                    status=ui_status or UI_EMPTY,
                    rows=list(rows or []),
                    summary=dict(summary or {}),
                    stats_raw=dict(stats_raw or {}),
                    error="",
                )
        # Specialized stale-request guard: do not apply the payload to live state.
        if not live_matches:
            self.alibaba_is_loading = False
            if self.alibaba_ui_status == UI_LOADING:
                self.alibaba_ui_status = UI_INITIAL
            return
        self.alibaba_is_loading = False
        if error_message is not None:
            self.alibaba_error = error_message
            self.alibaba_results = []
            self.alibaba_summary = {}
            self.alibaba_stats_raw = {}
            self.alibaba_ui_status = UI_ERROR
            return
        self.alibaba_error = ""
        self.alibaba_results = list(rows or [])
        self.alibaba_summary = dict(summary or {})
        self.alibaba_stats_raw = dict(stats_raw or {})
        self.alibaba_ui_status = ui_status or UI_EMPTY

    def _clear_facebook_product_results(self) -> None:
        self.facebook_product_results = []
        self.facebook_product_statistics = []
        self.facebook_product_summary = {}
        self.facebook_product_ui_status = UI_INITIAL
        self.facebook_product_error = ""
        self.facebook_product_is_loading = False
        self.facebook_product_provenance = {}
        self.facebook_product_last_search_query = ""
        self.facebook_product_association_product_id = ""

    def set_facebook_product_query(self, value: str) -> None:
        self.facebook_product_query = value
        self.facebook_product_query_origin = services.ML_QUERY_ORIGIN_USER
        if value.strip() != self.facebook_product_last_search_query.strip():
            self.facebook_product_provenance = {}

    def set_facebook_product_city(self, value: str) -> None:
        self.facebook_product_city = value

    def set_facebook_product_limit(self, value: str | int) -> None:
        self.facebook_product_limit = clamp_limit(value)

    def prepare_facebook_comparables_from_alibaba_result(self, product_id: str) -> object | None:
        row = next((item for item in self.alibaba_results if item.product_id == product_id), None)
        if row is None:
            return None
        self._prepare_facebook_comparables(external_id=row.product_id, title=row.title)
        return TrackerState.translate_selected_alibaba_title_for_facebook

    def prepare_facebook_comparables_from_alibaba_tracked(self, product_id: str) -> object | None:
        row = next(
            (item for item in self.alibaba_tracked_rows if item.product_id == product_id), None
        )
        if row is None:
            return None
        self._prepare_facebook_comparables(external_id=row.product_id, title=row.title)
        return TrackerState.translate_selected_alibaba_title_for_facebook

    def _prepare_facebook_comparables(self, *, external_id: str, title: str) -> None:
        stable_id = external_id.strip()
        if not stable_id:
            return
        previous_id = self.facebook_product_alibaba_context.get("external_id", "")
        product_changed = previous_id != stable_id
        self.facebook_product_translation_generation += 1
        self.facebook_product_alibaba_context = {
            "external_id": stable_id,
            "title": title.strip() or "Sin título",
        }
        self.facebook_product_has_alibaba_context = True
        self._open_workspace(WORKSPACE_PRODUCTS)
        self._clear_facebook_product_results()
        if product_changed:
            self.facebook_product_query = self.alibaba_query.strip()
            self.facebook_product_query_origin = (
                services.ML_QUERY_ORIGIN_FALLBACK if self.facebook_product_query else ""
            )
        self.facebook_product_translated_title = ""
        self.facebook_product_translation_warning = ""
        configured = services.product_translator_is_configured()
        self.facebook_product_translation_is_loading = configured
        self.facebook_product_translation_ui_status = (
            UI_LOADING if configured else UI_NOT_CONFIGURED
        )
        self.facebook_product_translation_error = (
            "" if configured else services.TRANSLATION_NOT_CONFIGURED_MESSAGE
        )

    def _facebook_product_active_id(self) -> str:
        if not self.facebook_product_has_alibaba_context:
            return ""
        return self.facebook_product_alibaba_context.get("external_id", "")

    def _finalize_facebook_product_translation(
        self,
        *,
        product_id: str,
        title: str,
        generation: int,
        translated_title: str = "",
        search_query: str = "",
        warning: str = "",
        error_message: str | None = None,
        configured: bool = True,
    ) -> None:
        if (
            product_id != self._facebook_product_active_id()
            or title != self.facebook_product_alibaba_context.get("title", "")
            or generation != self.facebook_product_translation_generation
        ):
            return
        self.facebook_product_translation_is_loading = False
        if error_message is not None:
            self.facebook_product_translated_title = ""
            self.facebook_product_translation_warning = ""
            self.facebook_product_translation_error = error_message
            self.facebook_product_translation_ui_status = (
                UI_ERROR if configured else UI_NOT_CONFIGURED
            )
            return
        self.facebook_product_translated_title = translated_title
        self.facebook_product_translation_warning = warning
        self.facebook_product_translation_error = ""
        self.facebook_product_translation_ui_status = UI_SUCCESS
        if (
            services.should_replace_generated_query(self.facebook_product_query_origin)
            and search_query.strip()
        ):
            self.facebook_product_query = search_query.strip()
            self.facebook_product_query_origin = services.ML_QUERY_ORIGIN_GENERATED

    @rx.event(background=True)
    async def translate_selected_alibaba_title_for_facebook(self) -> None:
        async with self:
            if (
                not self.facebook_product_has_alibaba_context
                or self.facebook_product_translation_ui_status == UI_NOT_CONFIGURED
            ):
                return
            product_id = self._facebook_product_active_id()
            title = self.facebook_product_alibaba_context.get("title", "")
            generation = self.facebook_product_translation_generation
            self.facebook_product_translation_is_loading = True
            self.facebook_product_translation_ui_status = UI_LOADING
            self.facebook_product_translation_error = ""
        try:
            payload = await asyncio.to_thread(services.translate_product_title, title)
        except Exception as exc:  # noqa: BLE001 - sanitized before display
            from bera_price_tracker.application.ports import ProductTranslatorNotConfiguredError

            async with self:
                self._finalize_facebook_product_translation(
                    product_id=product_id,
                    title=title,
                    generation=generation,
                    error_message=services.sanitize_translation_error(exc),
                    configured=not isinstance(exc, ProductTranslatorNotConfiguredError),
                )
            return
        async with self:
            self._finalize_facebook_product_translation(
                product_id=product_id,
                title=title,
                generation=generation,
                translated_title=str(payload.get("translated_text", "") or ""),
                search_query=str(payload.get("search_query", "") or ""),
                warning=str(payload.get("warning", "") or ""),
            )

    def _finalize_facebook_product_search(
        self,
        *,
        product_id: str,
        query: str,
        city: str,
        rows: list[FacebookProductResultRow] | None = None,
        statistics: list[FacebookCurrencyStatsRow] | None = None,
        summary: dict[str, str] | None = None,
        ui_status: str = "",
        error_message: str | None = None,
        request_generation: int | None = None,
        commit_generic_session: bool = False,
    ) -> None:
        if request_generation is not None and request_generation != self.search_generation:
            return
        live_matches = (
            product_id == self._facebook_product_active_id()
            and query.strip() == self.facebook_product_query.strip()
            and city.strip().casefold() == self.facebook_product_city.strip().casefold()
        )
        if commit_generic_session:
            if error_message is not None:
                self._replace_generic_session_facebook(
                    status=UI_ERROR,
                    rows=[],
                    summary={},
                    statistics=[],
                    error=error_message,
                )
            else:
                self._replace_generic_session_facebook(
                    status=ui_status or UI_EMPTY,
                    rows=list(rows or []),
                    summary=dict(summary or {}),
                    statistics=list(statistics or []),
                    error="",
                )
        if not live_matches:
            self.facebook_product_is_loading = False
            if self.facebook_product_ui_status == UI_LOADING:
                self.facebook_product_ui_status = UI_INITIAL
            return
        self.facebook_product_is_loading = False
        if error_message is not None:
            self.facebook_product_results = []
            self.facebook_product_statistics = []
            self.facebook_product_summary = {}
            self.facebook_product_provenance = {}
            self.facebook_product_error = error_message
            self.facebook_product_ui_status = UI_ERROR
            return
        self.facebook_product_results = list(rows or [])
        self.facebook_product_statistics = list(statistics or [])
        self.facebook_product_summary = dict(summary or {})
        self.facebook_product_error = ""
        self.facebook_product_ui_status = ui_status or UI_EMPTY
        self.facebook_product_last_search_query = query.strip()
        self.facebook_product_association_product_id = product_id
        self.facebook_product_provenance = (
            {
                "external_id": product_id,
                "title": self.facebook_product_alibaba_context.get("title", ""),
                "facebook_query": query.strip(),
            }
            if product_id
            else {}
        )

    @rx.event(background=True)
    async def search_facebook_products(self) -> None:
        async with self:
            if self.facebook_product_is_loading:
                return
            query = self.facebook_product_query
            city = self.facebook_product_city
            limit = clamp_limit(self.facebook_product_limit)
            product_id = self._facebook_product_active_id()
            if not query.strip():
                self._clear_facebook_product_results()
                self.facebook_product_error = services.FACEBOOK_PRODUCTS_QUERY_ERROR
                self.facebook_product_ui_status = UI_ERROR
                return
            if not city.strip():
                self._clear_facebook_product_results()
                self.facebook_product_error = services.FACEBOOK_PRODUCTS_CITY_ERROR
                self.facebook_product_ui_status = UI_ERROR
                return
            self.facebook_product_limit = limit
            self.facebook_product_is_loading = True
            self.facebook_product_error = ""
            self.facebook_product_ui_status = UI_LOADING
            self.facebook_product_provenance = {}
            generation = self.search_generation
        try:
            payload = await asyncio.to_thread(
                services.run_facebook_product_search,
                query,
                city,
                limit,
            )
        except Exception as exc:  # noqa: BLE001 - sanitized before display
            async with self:
                self._finalize_facebook_product_search(
                    product_id=product_id,
                    query=query,
                    city=city,
                    error_message=services.sanitize_facebook_product_error(exc),
                    request_generation=generation,
                )
            return
        rows = [
            FacebookProductResultRow(
                external_id=str(item.get("external_id", "")),
                title=str(item.get("title", "")),
                permalink=str(item.get("permalink", "")),
                price=str(item.get("price", "")),
                price_raw=str(item.get("price_raw", "")),
                currency=str(item.get("currency", "UNKNOWN")),
                formatted_price=str(item.get("formatted_price", "")),
                source_price_note=str(item.get("source_price_note", "")),
                usd_price=str(item.get("usd_price", "")),
                usd_amount=str(item.get("usd_amount", "")),
                usd_normalization_status=str(item.get("usd_normalization_status", "")),
                usd_evidence=str(item.get("usd_evidence", "")),
                usd_basis=str(item.get("usd_basis", "")),
                usd_provenance=str(item.get("usd_provenance", "")),
                location=str(item.get("location", "—")),
                representative=str(item.get("representative", "")),
                relevance_value=int(item.get("relevance_value", 0) or 0),
                relevance=str(item.get("relevance", "")),
                relevance_label=str(item.get("relevance_label", "")),
                relevance_tokens=str(item.get("relevance_tokens", "")),
                is_outlier=bool(item.get("is_outlier", False)),
                image_url=safe_public_image_url(item.get("image_url", "")),
            )
            for item in payload.get("results") or []
        ]
        statistics = [
            FacebookCurrencyStatsRow(
                currency=str(item.get("currency", "")),
                label=str(item.get("label", "")),
                basis=str(item.get("basis", "")),
                source_currencies=str(item.get("source_currencies", "")),
                normalization_status=str(item.get("normalization_status", "")),
                evidence=str(item.get("evidence", "")),
                provenance=str(item.get("provenance", "")),
                count=str(item.get("count", "0")),
                minimum=str(item.get("minimum", "unavailable")),
                average=str(item.get("average", "unavailable")),
                median=str(item.get("median", "unavailable")),
                maximum=str(item.get("maximum", "unavailable")),
                p25=str(item.get("p25", "unavailable")),
                p75=str(item.get("p75", "unavailable")),
                iqr=str(item.get("iqr", "unavailable")),
            )
            for item in payload.get("statistics") or []
        ]
        async with self:
            self._finalize_facebook_product_search(
                product_id=product_id,
                query=query,
                city=city,
                rows=rows,
                statistics=statistics,
                summary=dict(payload.get("summary") or {}),
                ui_status=str(payload.get("ui_status") or UI_EMPTY),
                request_generation=generation,
            )

    def set_ml_query(self, value: str) -> None:
        self.ml_query = value
        self.ml_query_origin = services.ML_QUERY_ORIGIN_USER
        if value.strip() != self.ml_last_search_query.strip():
            self._invalidate_ml_comparison()

    def prepare_ml_comparables_from_alibaba_result(self, product_id: str) -> object | None:
        row = next((item for item in self.alibaba_results if item.product_id == product_id), None)
        if row is None:
            return None
        self._prepare_ml_comparables(
            external_id=row.product_id,
            title=row.title,
            supplier=row.supplier_name,
            supplier_price=row.price or row.representative,
            currency=row.currency,
        )
        return TrackerState.translate_selected_alibaba_title

    def prepare_ml_comparables_from_alibaba_tracked(self, product_id: str) -> object | None:
        row = next(
            (item for item in self.alibaba_tracked_rows if item.product_id == product_id), None
        )
        if row is None:
            return None
        self._prepare_ml_comparables(
            external_id=row.product_id,
            title=row.title,
            supplier=row.supplier_name,
            supplier_price=row.current_price or row.last_price,
            currency=row.currency,
        )
        return TrackerState.translate_selected_alibaba_title

    def _prepare_ml_comparables(
        self,
        *,
        external_id: str,
        title: str,
        supplier: str,
        supplier_price: str,
        currency: str,
    ) -> None:
        stable_external_id = external_id.strip()
        if not stable_external_id:
            return
        previous_id = self.ml_alibaba_context.get("external_id", "")
        landed = self._landed_for_ml_product_currency(stable_external_id, currency)
        context = services.build_alibaba_ml_context(
            external_id=stable_external_id,
            title=title,
            supplier=supplier,
            supplier_price=supplier_price,
            currency=currency,
            desired_quantity=self.alibaba_landed_quantity or self.alibaba_negotiation_quantity,
            landed_row=landed,
        )
        if not context["external_id"]:
            return
        product_changed = previous_id != context["external_id"]
        switched_from_another_product = bool(previous_id) and product_changed
        self.ml_alibaba_context = context
        self.ml_has_alibaba_context = True
        self.ml_results_from_generic_session = False
        if switched_from_another_product:
            self.ml_query = ""
            self.ml_query_origin = ""
        else:
            self.ml_query = services.suggest_mercadolibre_query(
                current_query=self.ml_query,
                fallback_query=self.alibaba_query,
            )
            if not self.ml_query_origin and self.ml_query:
                self.ml_query_origin = services.ML_QUERY_ORIGIN_FALLBACK
        self._reset_product_translation_state(
            configured=services.product_translator_is_configured()
        )
        self._open_workspace(WORKSPACE_COMPARISONS)
        if product_changed:
            self.ml_results = []
            self.ml_summary = {}
            self.ml_ui_status = UI_INITIAL
            self.ml_error = ""
            self.ml_is_loading = False
            self.ml_last_search_query = ""
            self.ml_association_product_id = ""
            self._invalidate_ml_comparison()

    def _reset_product_translation_state(self, *, configured: bool) -> None:
        self.ml_translation_generation += 1
        self.ml_translated_title = ""
        self.ml_translation_warning = ""
        self.ml_translation_source_language = ""
        if configured:
            self.ml_translation_is_loading = True
            self.ml_translation_ui_status = UI_LOADING
            self.ml_translation_error = ""
        else:
            self.ml_translation_is_loading = False
            self.ml_translation_ui_status = UI_NOT_CONFIGURED
            self.ml_translation_error = services.TRANSLATION_NOT_CONFIGURED_MESSAGE

    def _finalize_product_translation(
        self,
        *,
        product_id: str,
        title: str,
        generation: int,
        translated_title: str = "",
        search_query: str = "",
        source_language: str = "",
        warning: str = "",
        error_message: str | None = None,
        configured: bool = True,
    ) -> None:
        current_product_id = self._ml_active_search_product_id()
        current_title = str(self.ml_alibaba_context.get("title", "") or "")
        if (
            product_id != current_product_id
            or title != current_title
            or generation != self.ml_translation_generation
        ):
            return
        self.ml_translation_is_loading = False
        if error_message is not None:
            self.ml_translated_title = ""
            self.ml_translation_warning = ""
            self.ml_translation_source_language = ""
            self.ml_translation_error = error_message
            self.ml_translation_ui_status = UI_NOT_CONFIGURED if not configured else UI_ERROR
            return
        self.ml_translation_error = ""
        self.ml_translated_title = translated_title
        self.ml_translation_warning = warning
        self.ml_translation_source_language = source_language
        self.ml_translation_ui_status = UI_SUCCESS
        if services.should_replace_generated_query(self.ml_query_origin) and search_query.strip():
            self.ml_query = search_query.strip()
            self.ml_query_origin = services.ML_QUERY_ORIGIN_GENERATED

    @rx.event(background=True)
    async def translate_selected_alibaba_title(self) -> None:
        async with self:
            if not self.ml_has_alibaba_context:
                return
            if self.ml_translation_ui_status == UI_NOT_CONFIGURED:
                return
            product_id = self._ml_active_search_product_id()
            title = str(self.ml_alibaba_context.get("title", "") or "")
            generation = self.ml_translation_generation
            self.ml_translation_is_loading = True
            self.ml_translation_ui_status = UI_LOADING
            self.ml_translation_error = ""
            self.ml_translation_warning = ""

        try:
            payload = await asyncio.to_thread(services.translate_product_title, title)
        except Exception as exc:  # noqa: BLE001 - sanitized before display
            from bera_price_tracker.application.ports import ProductTranslatorNotConfiguredError

            message = services.sanitize_translation_error(exc)
            async with self:
                self._finalize_product_translation(
                    product_id=product_id,
                    title=title,
                    generation=generation,
                    error_message=message,
                    configured=not isinstance(exc, ProductTranslatorNotConfiguredError),
                )
            return

        async with self:
            self._finalize_product_translation(
                product_id=product_id,
                title=title,
                generation=generation,
                translated_title=str(payload.get("translated_text", "") or ""),
                search_query=str(payload.get("search_query", "") or ""),
                source_language=str(payload.get("source_language", "") or ""),
                warning=str(payload.get("warning", "") or ""),
            )

    def set_ml_limit(self, value: str | int) -> None:
        try:
            self.ml_limit = int(value)
        except (TypeError, ValueError):
            self.ml_limit = 0
        self.ml_warning = mercadolibre_credit_warning(self.ml_limit) or ""

    def set_ml_sort(self, value: str) -> None:
        self.ml_sort = ML_SORT_BY_LABEL.get(value, analysis.SORT_ORIGINAL)

    def set_ml_price_min(self, value: str) -> None:
        self.ml_price_min = value
        self._invalidate_ml_comparison()

    def set_ml_price_max(self, value: str) -> None:
        self.ml_price_max = value
        self._invalidate_ml_comparison()

    def set_ml_hide_outliers(self, value: bool) -> None:
        self.ml_hide_outliers = bool(value)

    def set_ml_min_relevance(self, value: str) -> None:
        self.ml_min_relevance = ML_MIN_RELEVANCE_BY_LABEL.get(value, DEFAULT_BENCHMARK_RELEVANCE)
        self._invalidate_ml_comparison()

    def clear_ml_filters(self) -> None:
        self.ml_sort = analysis.SORT_ORIGINAL
        self.ml_price_min = ""
        self.ml_price_max = ""
        self.ml_hide_outliers = False
        self.ml_min_relevance = DEFAULT_BENCHMARK_RELEVANCE
        self._invalidate_ml_comparison()

    def _invalidate_ml_comparison(self) -> None:
        self.ml_has_comparison = False
        self.ml_comparison = {}

    def _landed_for_ml_product(self, external_id: str) -> dict[str, str] | None:
        stable_external_id = external_id.strip()
        if not stable_external_id or stable_external_id != self.alibaba_landed_product_id:
            return None
        if not self.alibaba_landed_has_result:
            return None
        return self.alibaba_landed_result

    def _landed_for_ml_product_currency(
        self, external_id: str, currency: object
    ) -> dict[str, str] | None:
        from bera_price_tracker.application.alibaba_statistics import (
            explicit_alibaba_currency,
        )

        explicit = explicit_alibaba_currency(currency)
        if explicit is None:
            return None
        landed = self._landed_for_ml_product(external_id)
        if landed is None:
            return None
        landed_currency = explicit_alibaba_currency(landed.get("currency"))
        return landed if landed_currency == explicit else None

    def _ml_benchmark_row_maps(self) -> list[dict[str, object]]:
        return [
            _ml_row_mapping(item)
            for item in services.mercadolibre_benchmark_source_rows(
                self.ml_results,
                price_min=self.ml_price_min,
                price_max=self.ml_price_max,
            )
        ]

    def _ml_active_search_product_id(self) -> str:
        if not self.ml_has_alibaba_context:
            return ""
        return str(self.ml_alibaba_context.get("external_id", "") or "")

    def _finalize_mercadolibre_search(
        self,
        *,
        search_product_id: str,
        query: str,
        rows: list[MercadoLibreResultRow] | None = None,
        summary: dict[str, str] | None = None,
        ui_status: str = "",
        error_message: str | None = None,
        request_generation: int | None = None,
        commit_generic_session: bool | None = None,
    ) -> None:
        if request_generation is not None and request_generation != self.search_generation:
            return
        current_product_id = self._ml_active_search_product_id()
        live_matches = (
            search_product_id == current_product_id and query.strip() == self.ml_query.strip()
        )
        should_commit = (
            self.ml_results_from_generic_session
            if commit_generic_session is None
            else commit_generic_session
        )
        if should_commit:
            if error_message is not None:
                self._replace_generic_session_ml(
                    status=UI_ERROR,
                    rows=[],
                    pipeline_summary={},
                    error=error_message,
                )
            else:
                self._replace_generic_session_ml(
                    status=ui_status or UI_EMPTY,
                    rows=list(rows or []),
                    pipeline_summary=dict(summary or {}),
                    error="",
                )
        if not live_matches:
            self.ml_is_loading = False
            if self.ml_ui_status == UI_LOADING:
                self.ml_ui_status = UI_INITIAL
            return
        self.ml_is_loading = False
        if error_message is not None:
            self.ml_error = error_message
            self.ml_results = []
            self.ml_summary = {}
            self.ml_ui_status = UI_ERROR
            self._invalidate_ml_comparison()
            return
        self.ml_error = ""
        self.ml_results = list(rows or [])
        self.ml_summary = dict(summary or {})
        self.ml_ui_status = ui_status or UI_EMPTY
        self.ml_last_search_query = query.strip()
        self.ml_association_product_id = search_product_id
        self._invalidate_ml_comparison()

    @rx.event(background=True)
    async def search_mercadolibre(self) -> None:
        async with self:
            if not services.can_start_mercadolibre_search(self.ml_is_loading):
                return
            self.ml_results_from_generic_session = False
            query = self.ml_query
            limit = self.ml_limit
            search_product_id = self._ml_active_search_product_id()
            if not isinstance(query, str) or not query.strip():
                self.ml_error = services.MERCADOLIBRE_QUERY_ERROR
                self.ml_results = []
                self.ml_summary = {}
                self.ml_ui_status = UI_ERROR
                self.ml_is_loading = False
                self._invalidate_ml_comparison()
                return
            if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 50:
                self.ml_error = services.MERCADOLIBRE_LIMIT_ERROR
                self.ml_results = []
                self.ml_summary = {}
                self.ml_ui_status = UI_ERROR
                self.ml_is_loading = False
                self._invalidate_ml_comparison()
                return
            self.ml_is_loading = True
            self.ml_error = ""
            self.ml_warning = mercadolibre_credit_warning(limit) or ""
            self.ml_ui_status = UI_LOADING
            self._invalidate_ml_comparison()
            generation = self.search_generation

        try:
            payload = await asyncio.to_thread(
                services.run_mercadolibre_search,
                query,
                limit,
            )
        except Exception as exc:  # noqa: BLE001 - sanitized before display
            message = services.sanitize_mercadolibre_error(exc)
            async with self:
                self._finalize_mercadolibre_search(
                    search_product_id=search_product_id,
                    query=query,
                    error_message=message,
                    request_generation=generation,
                )
            return

        rows = [
            MercadoLibreResultRow(
                external_id=str(item.get("external_id", "")),
                title=str(item.get("title", "")),
                permalink=str(item.get("permalink", "")),
                price=str(item.get("price", "—")),
                price_raw=str(item.get("price_raw", "")),
                currency=str(item.get("currency", "—")),
                condition=str(item.get("condition", "—")),
                seller_name=str(item.get("seller_name", "—")),
                shipping=str(item.get("shipping", "—")),
                thumbnail_url=safe_public_image_url(item.get("thumbnail_url", "")),
                country=str(item.get("country", "—")),
                representative=str(item.get("representative", "")),
                relevance_value=int(item.get("relevance_value", 0) or 0),
                relevance=str(item.get("relevance", "")),
                relevance_label=str(item.get("relevance_label", "")),
                relevance_tokens=str(item.get("relevance_tokens", "")),
                is_outlier=bool(item.get("is_outlier", False)),
                rating_average=_payload_text(item, "rating_average"),
                review_count=_payload_text(item, "review_count"),
                seller_reputation=_payload_text(item, "seller_reputation"),
                seller_status=_payload_text(item, "seller_status"),
                official_store=_official_store_label(item.get("official_store")),
            )
            for item in payload.get("results") or []
        ]
        async with self:
            self._finalize_mercadolibre_search(
                search_product_id=search_product_id,
                query=query,
                rows=rows,
                summary=dict(payload.get("summary") or {}),
                ui_status=str(payload.get("ui_status") or UI_EMPTY),
                request_generation=generation,
            )

    def _payload_maps(self, payload: dict[str, object], key: str) -> list[dict[str, Any]]:
        raw = payload.get(key) or []
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, dict)]

    def _payload_int(self, item: dict[str, Any], key: str) -> int:
        try:
            return int(item.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _alibaba_rows_from_payload(self, payload: dict[str, object]) -> list[AlibabaResultRow]:
        return [
            AlibabaResultRow(
                title=str(item.get("title", "")),
                price=str(item.get("price", "")),
                moq=str(item.get("moq", "")),
                supplier_name=str(item.get("supplier_name", "")),
                supplier_country=str(item.get("supplier_country", "")),
                url=str(item.get("url", "")),
                image_url=safe_public_image_url(item.get("image_url", "")),
                representative=str(item.get("representative", "")),
                product_id=str(item.get("product_id", "")),
                price_min=str(item.get("price_min", "")),
                price_max=str(item.get("price_max", "")),
                currency=str(item.get("currency", "")),
                is_outlier=bool(item.get("is_outlier", False)),
                score_value=self._payload_int(item, "score_value"),
                score=str(item.get("score", "")),
                score_label=str(item.get("score_label", "")),
                score_price=str(item.get("score_price", "")),
                score_moq=str(item.get("score_moq", "")),
                score_info=str(item.get("score_info", "")),
                score_clarity=str(item.get("score_clarity", "")),
                relevance_value=self._payload_int(item, "relevance_value"),
                relevance=str(item.get("relevance", "")),
                relevance_label=str(item.get("relevance_label", "")),
                relevance_tokens=str(item.get("relevance_tokens", "")),
                reputation_available=bool(item.get("reputation_available", False)),
                reputation_value=self._payload_int(item, "reputation_value"),
                reputation=str(item.get("reputation", "—")),
                reputation_label=str(item.get("reputation_label", "")),
                reputation_coverage=str(item.get("reputation_coverage", "")),
                reputation_coverage_label=str(item.get("reputation_coverage_label", "")),
                reputation_service=str(item.get("reputation_service", "")),
                reputation_reviews=str(item.get("reputation_reviews", "")),
                reputation_years=str(item.get("reputation_years", "")),
                reputation_volume=str(item.get("reputation_volume", "")),
                review_score=str(item.get("review_score", "")),
                review_count=_payload_text(item, "review_count"),
                supplier_service_score=_payload_text(item, "supplier_service_score"),
                gold_supplier_years=_payload_text(item, "gold_supplier_years"),
            )
            for item in self._payload_maps(payload, "results")
        ]

    def _facebook_rows_from_payload(
        self, payload: dict[str, object]
    ) -> tuple[list[FacebookProductResultRow], list[FacebookCurrencyStatsRow]]:
        rows = [
            FacebookProductResultRow(
                external_id=str(item.get("external_id", "")),
                title=str(item.get("title", "")),
                permalink=str(item.get("permalink", "")),
                price=str(item.get("price", "")),
                price_raw=str(item.get("price_raw", "")),
                currency=str(item.get("currency", "UNKNOWN")),
                formatted_price=str(item.get("formatted_price", "")),
                source_price_note=str(item.get("source_price_note", "")),
                usd_price=str(item.get("usd_price", "")),
                usd_amount=str(item.get("usd_amount", "")),
                usd_normalization_status=str(item.get("usd_normalization_status", "")),
                usd_evidence=str(item.get("usd_evidence", "")),
                usd_basis=str(item.get("usd_basis", "")),
                usd_provenance=str(item.get("usd_provenance", "")),
                location=str(item.get("location", "—")),
                representative=str(item.get("representative", "")),
                relevance_value=self._payload_int(item, "relevance_value"),
                relevance=str(item.get("relevance", "")),
                relevance_label=str(item.get("relevance_label", "")),
                relevance_tokens=str(item.get("relevance_tokens", "")),
                is_outlier=bool(item.get("is_outlier", False)),
                image_url=safe_public_image_url(item.get("image_url", "")),
            )
            for item in self._payload_maps(payload, "results")
        ]
        statistics = [
            FacebookCurrencyStatsRow(
                currency=str(item.get("currency", "")),
                label=str(item.get("label", "")),
                basis=str(item.get("basis", "")),
                source_currencies=str(item.get("source_currencies", "")),
                normalization_status=str(item.get("normalization_status", "")),
                evidence=str(item.get("evidence", "")),
                provenance=str(item.get("provenance", "")),
                count=str(item.get("count", "0")),
                minimum=str(item.get("minimum", "unavailable")),
                average=str(item.get("average", "unavailable")),
                median=str(item.get("median", "unavailable")),
                maximum=str(item.get("maximum", "unavailable")),
                p25=str(item.get("p25", "unavailable")),
                p75=str(item.get("p75", "unavailable")),
                iqr=str(item.get("iqr", "unavailable")),
            )
            for item in self._payload_maps(payload, "statistics")
        ]
        return rows, statistics

    def _ml_rows_from_payload(self, payload: dict[str, object]) -> list[MercadoLibreResultRow]:
        return [
            MercadoLibreResultRow(
                external_id=str(item.get("external_id", "")),
                title=str(item.get("title", "")),
                permalink=str(item.get("permalink", "")),
                price=str(item.get("price", "—")),
                price_raw=str(item.get("price_raw", "")),
                currency=str(item.get("currency", "—")),
                condition=str(item.get("condition", "—")),
                seller_name=str(item.get("seller_name", "—")),
                shipping=str(item.get("shipping", "—")),
                thumbnail_url=safe_public_image_url(item.get("thumbnail_url", "")),
                country=str(item.get("country", "—")),
                representative=str(item.get("representative", "")),
                relevance_value=self._payload_int(item, "relevance_value"),
                relevance=str(item.get("relevance", "")),
                relevance_label=str(item.get("relevance_label", "")),
                relevance_tokens=str(item.get("relevance_tokens", "")),
                is_outlier=bool(item.get("is_outlier", False)),
                rating_average=_payload_text(item, "rating_average"),
                review_count=_payload_text(item, "review_count"),
                seller_reputation=_payload_text(item, "seller_reputation"),
                seller_status=_payload_text(item, "seller_status"),
                official_store=_official_store_label(item.get("official_store")),
            )
            for item in self._payload_maps(payload, "results")
        ]

    def _detach_alibaba_comparable_context(self) -> None:
        """Drop Alibaba product binding so a generic session cannot inherit it.

        Comparable Facebook/ML lookups are bound to one Alibaba ``product_id``.
        A later multi-market or Nueva búsqueda session is not that lookup, so
        leftover context must not stamp session results onto the old product.
        Clear the detached Mercado Libre query so a later product cannot reuse
        a user query that belonged to the previous comparable.
        """

        self.facebook_product_translation_generation += 1
        self.facebook_product_has_alibaba_context = False
        self.facebook_product_alibaba_context = {}
        self.facebook_product_association_product_id = ""
        self.facebook_product_provenance = {}
        self.facebook_product_last_search_query = ""
        self.facebook_product_translated_title = ""
        self.facebook_product_translation_warning = ""
        self.facebook_product_translation_error = ""
        self.facebook_product_translation_is_loading = False
        self.facebook_product_translation_ui_status = UI_INITIAL

        self.ml_translation_generation += 1
        self.ml_has_alibaba_context = False
        self.ml_alibaba_context = {}
        self.ml_association_product_id = ""
        self.ml_last_search_query = ""
        self.ml_translated_title = ""
        self.ml_translation_warning = ""
        self.ml_translation_error = ""
        self.ml_translation_is_loading = False
        self.ml_translation_ui_status = UI_INITIAL
        self.ml_translation_source_language = ""
        self.ml_query = ""
        self.ml_query_origin = ""
        self._invalidate_ml_comparison()

    def _prepare_scoped_search(self, plan: search_scope.SearchPlan) -> None:
        self.search_query = plan.query
        self.search_limit = plan.limit
        self.search_session_limit = plan.limit
        self.search_session_mode = plan.mode
        self.search_session_providers = list(plan.providers)
        self.search_session_platform = (
            plan.providers[0] if plan.mode == MODE_SINGLE and plan.providers else ""
        )
        self._detach_alibaba_comparable_context()
        selected = set(plan.providers)
        self.alibaba_results = []
        self.alibaba_summary = {}
        self.alibaba_stats_raw = {}
        self.alibaba_error = ""
        self.diagnostic_open_platforms = []
        self._clear_generic_session_alibaba()
        if PLATFORM_ALIBABA in selected:
            self.alibaba_query = plan.query
            self.alibaba_limit = plan.limit
            self.alibaba_is_loading = True
            self.alibaba_ui_status = UI_LOADING
            self.generic_session_alibaba = GenericAlibabaSessionSnapshot(
                generation=self.search_generation,
                status=UI_LOADING,
                rows=[],
                summary={},
                stats_raw={},
                error="",
                requested_limit=self.search_session_limit,
            )
        else:
            self.alibaba_is_loading = False
            self.alibaba_ui_status = UI_INITIAL
            self.generic_session_alibaba = GenericAlibabaSessionSnapshot(
                generation=self.search_generation,
                status=UI_INITIAL,
                rows=[],
                summary={},
                stats_raw={},
                error="",
                requested_limit=self.search_session_limit,
            )
        self.facebook_product_results = []
        self.facebook_product_statistics = []
        self.facebook_product_summary = {}
        self.facebook_product_error = ""
        self.facebook_product_provenance = {}
        self._clear_generic_session_facebook()
        if PLATFORM_FACEBOOK in selected:
            self.facebook_product_query = plan.query
            self.facebook_product_limit = plan.limit
            self.facebook_product_query_origin = services.ML_QUERY_ORIGIN_USER
            self.facebook_product_is_loading = True
            self.facebook_product_ui_status = UI_LOADING
            self.generic_session_facebook = GenericFacebookSessionSnapshot(
                generation=self.search_generation,
                status=UI_LOADING,
                rows=[],
                summary={},
                statistics=[],
                error="",
                requested_limit=self.search_session_limit,
            )
        else:
            self.facebook_product_is_loading = False
            self.facebook_product_ui_status = UI_INITIAL
            self.generic_session_facebook = GenericFacebookSessionSnapshot(
                generation=self.search_generation,
                status=UI_INITIAL,
                rows=[],
                summary={},
                statistics=[],
                error="",
                requested_limit=self.search_session_limit,
            )
        self.ml_results = []
        self.ml_summary = {}
        self.ml_error = ""
        self._clear_generic_session_ml()
        if PLATFORM_ML in selected:
            self.ml_query = plan.query
            self.ml_limit = plan.limit
            self.ml_query_origin = services.ML_QUERY_ORIGIN_USER
            self.ml_is_loading = True
            self.ml_ui_status = UI_LOADING
            self.ml_results_from_generic_session = True
            self.generic_session_ml = GenericMercadoLibreSessionSnapshot(
                generation=self.search_generation,
                status=UI_LOADING,
                rows=[],
                summary={},
                diagnostic_summary={},
                error="",
                requested_limit=self.search_session_limit,
            )
            self._invalidate_ml_comparison()
        else:
            self.ml_is_loading = False
            self.ml_ui_status = UI_INITIAL
            self.ml_results_from_generic_session = False
            self.generic_session_ml = GenericMercadoLibreSessionSnapshot(
                generation=self.search_generation,
                status=UI_INITIAL,
                rows=[],
                summary={},
                diagnostic_summary={},
                error="",
                requested_limit=self.search_session_limit,
            )
            self._invalidate_ml_comparison()

    @rx.event(background=True)
    async def run_scoped_search(self) -> None:
        async with self:
            try:
                plan = search_scope.plan_search(
                    mode=self.search_mode,
                    platform=self.search_platform,
                    query=self.search_query,
                    limit=self.search_limit,
                    city=self.facebook_product_city,
                )
            except ValueError as exc:
                self.search_error = str(exc)
                return
            generation = self.search_generation + 1
            self.search_generation = generation
            self.search_error = ""
            self.search_session_active = True
            self.search_session_query = plan.query
            self.search_started_monotonic = str(time.monotonic())
            self.search_elapsed_ms = 0
            self.search_completed_at = ""
            self._prepare_scoped_search(plan)

        async def run_provider(provider: str) -> None:
            try:
                if provider == PLATFORM_ALIBABA:
                    payload = await asyncio.to_thread(
                        services.run_alibaba_search, plan.query, plan.limit
                    )
                elif provider == PLATFORM_FACEBOOK:
                    payload = await asyncio.to_thread(
                        services.run_facebook_product_search,
                        plan.query,
                        plan.city,
                        plan.limit,
                    )
                else:
                    payload = await asyncio.to_thread(
                        services.run_mercadolibre_search, plan.query, plan.limit
                    )
            except Exception as exc:  # noqa: BLE001 — sanitized before display
                async with self:
                    if provider == PLATFORM_ALIBABA:
                        self._finalize_alibaba_search(
                            request_query=plan.query,
                            request_limit=plan.limit,
                            error_message=services.sanitize_alibaba_error(exc),
                            request_generation=generation,
                            commit_generic_session=True,
                        )
                    elif provider == PLATFORM_FACEBOOK:
                        # Session search is never an Alibaba-comparable lookup.
                        self._finalize_facebook_product_search(
                            product_id="",
                            query=plan.query,
                            city=plan.city,
                            error_message=services.sanitize_facebook_product_error(exc),
                            request_generation=generation,
                            commit_generic_session=True,
                        )
                    else:
                        self._finalize_mercadolibre_search(
                            search_product_id="",
                            query=plan.query,
                            error_message=services.sanitize_mercadolibre_error(exc),
                            request_generation=generation,
                            commit_generic_session=True,
                        )
                return
            if not isinstance(payload, dict):
                payload = {}
            async with self:
                if provider == PLATFORM_ALIBABA:
                    self._finalize_alibaba_search(
                        request_query=plan.query,
                        request_limit=plan.limit,
                        rows=self._alibaba_rows_from_payload(payload),
                        summary=dict(payload.get("summary") or {}),
                        stats_raw=dict(payload.get("stats_raw") or {}),
                        ui_status=str(payload.get("ui_status") or UI_EMPTY),
                        request_generation=generation,
                        commit_generic_session=True,
                    )
                elif provider == PLATFORM_FACEBOOK:
                    rows, statistics = self._facebook_rows_from_payload(payload)
                    self._finalize_facebook_product_search(
                        product_id="",
                        query=plan.query,
                        city=plan.city,
                        rows=rows,
                        statistics=statistics,
                        summary=dict(payload.get("summary") or {}),
                        ui_status=str(payload.get("ui_status") or UI_EMPTY),
                        request_generation=generation,
                        commit_generic_session=True,
                    )
                else:
                    self._finalize_mercadolibre_search(
                        search_product_id="",
                        query=plan.query,
                        rows=self._ml_rows_from_payload(payload),
                        summary=dict(payload.get("summary") or {}),
                        ui_status=str(payload.get("ui_status") or UI_EMPTY),
                        request_generation=generation,
                        commit_generic_session=True,
                    )

        await asyncio.gather(*[run_provider(provider) for provider in plan.providers])
        async with self:
            if generation != self.search_generation:
                return
            started = float(self.search_started_monotonic or "0")
            if started:
                self.search_elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
            self.search_completed_at = search_session.format_session_timestamp(
                datetime.now().astimezone()
            )

    def apply_partial_search_fixture(self) -> None:
        """Isolated visual fixture. Not used by production search."""

        self.search_mode = MODE_MULTI
        self.search_limit = DEFAULT_SEARCH_LIMIT
        self.search_query = "fixture mouse"
        self.search_session_query = "fixture mouse"
        self.search_session_active = True
        self.search_elapsed_ms = 12400
        self.search_completed_at = search_session.format_session_timestamp(
            datetime.now().astimezone()
        )
        self.alibaba_query = "fixture mouse"
        self.alibaba_ui_status = UI_SUCCESS
        self.alibaba_is_loading = False
        self.alibaba_error = ""
        self.alibaba_summary = {
            "resultados": "1",
            "minimo": "USD 4.00",
            "mediana": "USD 4.00",
            "promedio": "USD 4.00",
            "maximo": "USD 4.00",
            "p25": "USD 4.00",
            "p75": "USD 4.00",
            "requested": "5",
            "fetched": "1",
            "usable": "1",
        }
        self.alibaba_stats_raw = {
            "minimum": "4.00",
            "p25": "4.00",
            "median": "4.00",
            "p75": "4.00",
            "maximum": "4.00",
        }
        self.alibaba_results = [
            AlibabaResultRow(
                title="Fixture Alibaba",
                price="USD 4.00",
                product_id="fixture-ali",
                score_value=72,
                score="72",
                review_score="4.8",
                review_count="128",
                supplier_service_score="4.9",
                gold_supplier_years="6",
                supplier_name="Fixture Supplier",
                moq="50",
                currency="USD",
                image_url="http://127.0.0.1:3000/fixture-alibaba.png",
            )
        ]
        self.facebook_product_ui_status = UI_ERROR
        self.facebook_product_is_loading = False
        self.facebook_product_results = []
        self.facebook_product_statistics = []
        self.facebook_product_error = "No se pudo consultar Facebook Marketplace."
        self.ml_query = "fixture mouse"
        self.ml_ui_status = UI_SUCCESS
        self.ml_is_loading = False
        self.ml_error = ""
        self.ml_summary = {
            "comparables": "1 de 1",
            "comparable_count": "1",
            "minimo": "USD 9.00",
            "mediana": "USD 9.00",
            "precio_tipico": "USD 9.00",
            "maximo": "USD 9.00",
            "p25": "USD 9.00",
            "p75": "USD 9.00",
            "currency": "USD",
            "requested": "5",
            "fetched": "1",
            "usable": "1",
        }
        self.ml_results = [
            MercadoLibreResultRow(
                title="Fixture ML",
                price="USD 9.00",
                price_raw="9.00",
                currency="USD",
                relevance_value=90,
                seller_name="Fixture Seller",
                condition="Nuevo",
                thumbnail_url="http://127.0.0.1:3000/fixture-ml.png",
                rating_average="4.8",
                review_count="742",
                seller_reputation="green_power",
                seller_status="platinum · Tienda oficial",
                official_store="Tienda oficial",
            )
        ]

    def apply_complete_search_fixture(self) -> None:
        """Isolated visual fixture for a completed 3-platform search."""

        self.apply_partial_search_fixture()
        self.search_query = "Mouse inalámbrico"
        self.search_session_query = "Mouse inalámbrico"
        self.alibaba_query = "Mouse inalámbrico"
        self.ml_query = "Mouse inalámbrico"
        self.facebook_product_query = "Mouse inalámbrico"
        self.facebook_product_ui_status = UI_SUCCESS
        self.facebook_product_error = ""
        self.facebook_product_results = [
            FacebookProductResultRow(
                title="Bate de sóftball",
                usd_price="USD 150.00",
                usd_amount="150.00",
                usd_provenance="Facebook VE · USD",
                location="Caracas",
                currency="USD",
                price="USD 150.00",
                price_raw="150.00",
                permalink="https://www.facebook.com/marketplace/item/fixture-bat",
                image_url="http://127.0.0.1:3000/fixture-facebook.png",
                relevance_value=88,
                relevance="88/100",
            )
        ]
        self.facebook_product_statistics = [
            FacebookCurrencyStatsRow(
                currency="USD",
                label="USD normalizado",
                basis="USD",
                provenance="Facebook VE",
                count="1",
                minimum="150.00",
                average="150.00",
                median="150.00",
                maximum="150.00",
                p25="150.00",
                p75="150.00",
            )
        ]
        self.facebook_product_summary = {
            "requested": "3",
            "fetched": "3",
            "usable": "1",
            "free_price": "1",
            "invalid_price": "1",
        }

    def apply_zero_result_diagnostic_fixture(self) -> None:
        """Completed search with Alibaba empty, Facebook filtered, ML missing image."""

        self.apply_complete_search_fixture()
        self.search_query = "béisbol"
        self.search_session_query = "béisbol"
        self.alibaba_query = "béisbol"
        self.alibaba_ui_status = UI_EMPTY
        self.alibaba_results = []
        self.alibaba_summary = {
            "resultados": "0",
            "requested": "1",
            "fetched": "0",
            "usable": "0",
        }
        self.ml_query = "béisbol"
        self.ml_results = [
            MercadoLibreResultRow(
                title="Bate de béisbol, aluminio",
                price="USD 9.00",
                price_raw="9.00",
                currency="USD",
                relevance_value=90,
                seller_name="Fixture Seller",
                condition="Nuevo",
                thumbnail_url="",
                rating_average="4.8",
                review_count="742",
                seller_reputation="MercadoLíder",
                seller_status="Tienda oficial",
                official_store="Tienda oficial",
            )
        ]
        self.ml_summary = {
            "comparables": "1 de 1",
            "comparable_count": "1",
            "minimo": "USD 9.00",
            "mediana": "USD 9.00",
            "precio_tipico": "USD 9.00",
            "maximo": "USD 9.00",
            "p25": "USD 9.00",
            "p75": "USD 9.00",
            "currency": "USD",
            "requested": "1",
            "fetched": "1",
            "usable": "1",
        }

    def apply_running_search_fixture(self) -> None:
        """Isolated visual fixture for in-progress search."""

        self.search_mode = MODE_MULTI
        self.search_limit = DEFAULT_SEARCH_LIMIT
        self.search_query = "Mouse inalámbrico"
        self.search_session_query = "Mouse inalámbrico"
        self.search_session_active = True
        self.search_completed_at = ""
        self.search_elapsed_ms = 0
        self.alibaba_ui_status = UI_LOADING
        self.alibaba_is_loading = True
        self.facebook_product_ui_status = UI_LOADING
        self.facebook_product_is_loading = True
        self.ml_ui_status = UI_LOADING
        self.ml_is_loading = True

    def start_new_search(self) -> None:
        """Return to setup. Clears session presentation. Does not call providers."""

        self.search_generation += 1
        self.search_session_active = False
        self.search_error = ""
        self.search_elapsed_ms = 0
        self.search_completed_at = ""
        self.search_started_monotonic = ""
        self.search_session_query = ""
        self.search_session_limit = 0
        self.search_session_mode = ""
        self.search_session_platform = ""
        self.search_session_providers = []
        self.alibaba_results = []
        self.alibaba_summary = {}
        self.alibaba_stats_raw = {}
        self.alibaba_error = ""
        self.alibaba_is_loading = False
        self.alibaba_ui_status = UI_INITIAL
        self.facebook_product_results = []
        self.facebook_product_statistics = []
        self.facebook_product_summary = {}
        self.facebook_product_error = ""
        self.facebook_product_is_loading = False
        self.facebook_product_ui_status = UI_INITIAL
        self.ml_results = []
        self.ml_summary = {}
        self.ml_error = ""
        self.ml_is_loading = False
        self.ml_ui_status = UI_INITIAL
        self.ml_results_from_generic_session = False
        self._clear_generic_session_alibaba()
        self._clear_generic_session_facebook()
        self._clear_generic_session_ml()
        self.diagnostic_open_platforms = []
        self._detach_alibaba_comparable_context()

    def compare_ml_with_landed_cost(self) -> None:
        if self.ml_has_alibaba_context:
            selected_id = self.ml_alibaba_context.get("external_id", "")
            landed = self._landed_for_ml_product_currency(
                selected_id, self.ml_alibaba_context.get("currency")
            )
        elif self.ml_results_from_generic_session:
            # Generic Búsquedas results have no truthful Alibaba product
            # context. Leftover landed cost belongs to a different product.
            landed = None
        else:
            landed = self.alibaba_landed_result if self.alibaba_landed_has_result else None
        row = services.compare_mercadolibre_with_landed_cost(
            self._ml_benchmark_row_maps(),
            landed,
            min_relevance=self.ml_min_relevance,
        )
        self.ml_comparison = row
        self.ml_has_comparison = True

    def _apply_tracked_payload(self, rows: list[dict[str, str]]) -> None:
        self.alibaba_tracked_rows = [
            AlibabaTrackedRow(
                product_id=str(item.get("product_id", "")),
                title=str(item.get("title", "")),
                supplier_name=str(item.get("supplier_name", "")),
                current_price=str(item.get("current_price", "")),
                last_price=str(item.get("last_price", "")),
                published_range=str(item.get("published_range", "")),
                first_price=str(item.get("first_price", "")),
                first_price_tag=str(item.get("first_price_tag", "")),
                baseline=str(item.get("baseline", "")),
                last_updated=str(item.get("last_updated", "")),
                variation=str(item.get("variation", "")),
                history=str(item.get("history", "")),
                url=str(item.get("url", "")),
                snapshot_count=str(item.get("snapshot_count", "")),
                price_min=str(item.get("price_min", "")),
                price_max=str(item.get("price_max", "")),
                currency=str(item.get("currency", "")),
            )
            for item in rows
        ]

    def refresh_alibaba_tracking(self) -> None:
        try:
            rows = services.list_alibaba_tracked()
        except Exception as exc:  # noqa: BLE001 — sanitized before display
            self.alibaba_tracking_error = services.sanitize_alibaba_error(exc)
            return
        self.alibaba_tracking_error = ""
        self._apply_tracked_payload(rows)

    def follow_alibaba_product(self, product_id: str) -> None:
        row = next((item for item in self.alibaba_results if item.product_id == product_id), None)
        if row is None:
            self.alibaba_tracking_error = "No se encontró el producto cargado."
            return
        payload = {
            "product_id": row.product_id,
            "title": row.title,
            "url": row.url,
            "representative": row.representative,
            "price": row.price,
            "price_min": row.price_min,
            "price_max": row.price_max,
            "currency": row.currency,
            "supplier_name": row.supplier_name,
            "supplier_country": row.supplier_country,
        }
        try:
            services.follow_alibaba_price(payload, self.alibaba_query)
        except Exception as exc:  # noqa: BLE001 — sanitized before display
            message = str(exc).strip() or services.sanitize_alibaba_error(exc)
            self.alibaba_tracking_error = message
            return
        self.alibaba_tracking_error = ""
        self.refresh_alibaba_tracking()

    def unfollow_alibaba_product(self, product_id: str) -> None:
        try:
            services.unfollow_alibaba_price(product_id)
        except Exception as exc:  # noqa: BLE001 — sanitized before display
            message = str(exc).strip() or services.sanitize_alibaba_error(exc)
            self.alibaba_tracking_error = message
            return
        self.alibaba_tracking_error = ""
        self.refresh_alibaba_tracking()

    def toggle_alibaba_refresh_selection(self, product_id: str) -> None:
        selected = services.clamp_alibaba_refresh_selection(self.alibaba_refresh_selected_ids)
        if product_id in selected:
            selected = [item for item in selected if item != product_id]
        else:
            selected = services.clamp_alibaba_refresh_selection([*selected, product_id])
        self.alibaba_refresh_selected_ids = selected

    def select_visible_alibaba_tracked(self) -> None:
        visible = [row.product_id for row in self.alibaba_tracked_rows if row.product_id]
        self.alibaba_refresh_selected_ids = services.clamp_alibaba_refresh_selection(visible)

    def _open_alibaba_refresh_confirm(self, product_ids: list[str]) -> None:
        selected = services.clamp_alibaba_refresh_selection(product_ids)
        if not selected:
            self.alibaba_tracking_error = services.ALIBABA_REFRESH_EMPTY_SELECTION
            return
        try:
            confirmation = services.alibaba_refresh_confirmation(len(selected))
        except ValueError as error:
            self.alibaba_tracking_error = str(error)
            return
        self.alibaba_tracking_error = ""
        self.alibaba_refresh_pending_ids = selected
        self.alibaba_refresh_operation_id = uuid.uuid4().hex
        self.alibaba_refresh_confirm_intro = confirmation["intro"]
        self.alibaba_refresh_confirm_count = confirmation["selected"]
        self.alibaba_refresh_confirm_open = True

    def request_alibaba_refresh_selected(self) -> None:
        self._open_alibaba_refresh_confirm(list(self.alibaba_refresh_selected_ids))

    def request_alibaba_refresh_one(self, product_id: str) -> None:
        self._open_alibaba_refresh_confirm([product_id])

    def cancel_alibaba_refresh(self) -> None:
        self.alibaba_refresh_confirm_open = False
        self.alibaba_refresh_pending_ids = []

    @rx.event(background=True)
    async def confirm_alibaba_refresh(self) -> None:
        async with self:
            if self.alibaba_refresh_is_loading:
                return
            product_ids = list(self.alibaba_refresh_pending_ids)
            operation_id = self.alibaba_refresh_operation_id
            self.alibaba_refresh_is_loading = True
            self.alibaba_refresh_confirm_open = False
            self.alibaba_tracking_error = ""
        try:
            summary = await asyncio.to_thread(
                services.refresh_alibaba_tracked,
                product_ids,
                operation_id,
            )
        except Exception as exc:  # noqa: BLE001 — sanitized before display
            message = str(exc).strip() or services.sanitize_alibaba_error(exc)
            async with self:
                self.alibaba_refresh_is_loading = False
                self.alibaba_tracking_error = message
            return
        async with self:
            self.alibaba_refresh_is_loading = False
            self.alibaba_refresh_summary = dict(summary)
            self.alibaba_refresh_pending_ids = []
            self.refresh_alibaba_tracking()

    @rx.var
    def alibaba_tracked_view_rows(self) -> list[AlibabaTrackedRow]:
        from bera_price_tracker.gui.tracking_display import tracking_image_url

        selected = set(self.alibaba_refresh_selected_ids)
        open_ids = set(self.alibaba_history_open_ids)
        result_images = {
            row.product_id: row.image_url for row in self.alibaba_results if row.product_id
        }
        rows: list[AlibabaTrackedRow] = []
        for row in self.alibaba_tracked_rows:
            is_selected = bool(row.product_id) and row.product_id in selected
            history_open = bool(row.product_id) and row.product_id in open_ids
            image_url = tracking_image_url(
                row.product_id,
                tracked_image=row.image_url,
                result_images=result_images,
            )
            updates: dict[str, object] = {}
            if row.selected != is_selected:
                updates["selected"] = is_selected
            if row.history_open != history_open:
                updates["history_open"] = history_open
            if row.image_url != image_url:
                updates["image_url"] = image_url
            rows.append(row.model_copy(update=updates) if updates else row)
        return rows

    @rx.var
    def alibaba_refresh_has_summary(self) -> bool:
        return bool(self.alibaba_refresh_summary)

    @rx.var
    def alibaba_followed_ids(self) -> list[str]:
        return [row.product_id for row in self.alibaba_tracked_rows if row.product_id]

    @rx.var
    def alibaba_has_tracked_rows(self) -> bool:
        return len(self.alibaba_tracked_rows) > 0

    @rx.var
    def alibaba_sort_label(self) -> str:
        return ALIBABA_SORT_LABELS.get(self.alibaba_sort, "Relevancia original")

    @rx.var
    def alibaba_chart_scope_label(self) -> str:
        return ALIBABA_SCOPE_LABELS.get(self.alibaba_chart_scope, "Todos los precios")

    @rx.var
    def alibaba_min_relevance_label(self) -> str:
        return ALIBABA_MIN_RELEVANCE_LABELS.get(self.alibaba_min_relevance, "Todas")

    @rx.var
    def alibaba_min_reputation_label(self) -> str:
        return ALIBABA_MIN_REPUTATION_LABELS.get(self.alibaba_min_reputation, "Todas")

    @rx.var
    def alibaba_filter_error(self) -> str:
        _minimum, _maximum, error = analysis.validate_price_filters(
            self.alibaba_price_min, self.alibaba_price_max
        )
        return error

    @rx.var
    def alibaba_visible_rows(self) -> list[AlibabaResultRow]:
        minimum, maximum, error = analysis.validate_price_filters(
            self.alibaba_price_min, self.alibaba_price_max
        )
        if error:
            minimum = None
            maximum = None
        return analysis.apply_table_view(
            self.alibaba_results,
            sort=self.alibaba_sort,
            minimum=minimum,
            maximum=maximum,
            hide_outliers=self.alibaba_hide_outliers,
            min_relevance=self.alibaba_min_relevance,
            min_reputation=self.alibaba_min_reputation,
            weights=RankingWeights(
                relevance=self.alibaba_applied_relevance_weight,
                opportunity=self.alibaba_applied_opportunity_weight,
                reputation=self.alibaba_applied_reputation_weight,
            ),
        )

    @rx.var
    def alibaba_table_rows(self) -> list[AlibabaResultRow]:
        followed = set(self.alibaba_followed_ids)
        rows: list[AlibabaResultRow] = []
        for row in self.alibaba_visible_rows:
            is_followed = bool(row.product_id) and row.product_id in followed
            if row.is_followed == is_followed:
                rows.append(row)
                continue
            rows.append(row.model_copy(update={"is_followed": is_followed}))
        return rows

    @rx.var
    def alibaba_counter(self) -> str:
        return analysis.showing_counter(len(self.alibaba_visible_rows), len(self.alibaba_results))

    @rx.var
    def alibaba_weights_total(self) -> int:
        return (
            self.alibaba_relevance_weight
            + self.alibaba_opportunity_weight
            + self.alibaba_reputation_weight
        )

    @rx.var
    def alibaba_weights_error(self) -> str:
        return validate_ranking_weights(
            self.alibaba_relevance_weight,
            self.alibaba_opportunity_weight,
            self.alibaba_reputation_weight,
        )

    @rx.var
    def alibaba_weights_valid(self) -> bool:
        return self.alibaba_weights_error == ""

    @rx.var
    def alibaba_top_results(self) -> list[dict[str, str]]:
        return analysis.top_result_cards(self.alibaba_visible_rows)

    @rx.var
    def alibaba_has_top_results(self) -> bool:
        return len(self.alibaba_top_results) > 0

    @rx.var
    def alibaba_histogram(self) -> list[dict[str, str]]:
        values = analysis.rows_representatives(self.alibaba_results)
        scoped = analysis.select_chart_values(
            values,
            self.alibaba_chart_scope,
            analysis.parse_decimal_text(self.alibaba_stats_raw.get("lower_fence", "")),
            analysis.parse_decimal_text(self.alibaba_stats_raw.get("upper_fence", "")),
        )
        return analysis.build_histogram(scoped)

    @rx.var
    def alibaba_histogram_has_data(self) -> bool:
        return len(self.alibaba_histogram) > 0

    @rx.var
    def alibaba_boxplot(self) -> dict[str, str]:
        return analysis.boxplot_geometry(
            analysis.parse_decimal_text(self.alibaba_stats_raw.get("minimum", "")),
            analysis.parse_decimal_text(self.alibaba_stats_raw.get("p25", "")),
            analysis.parse_decimal_text(self.alibaba_stats_raw.get("median", "")),
            analysis.parse_decimal_text(self.alibaba_stats_raw.get("p75", "")),
            analysis.parse_decimal_text(self.alibaba_stats_raw.get("maximum", "")),
        )

    @rx.var
    def alibaba_boxplot_available(self) -> bool:
        return self.alibaba_boxplot.get("available", "") == "1"

    @rx.var
    def alibaba_negotiation_option_keys(self) -> list[str]:
        return [item["key"] for item in self._alibaba_negotiation_catalog()]

    @rx.var
    def alibaba_negotiation_option_labels(self) -> list[str]:
        return [f"{item['key']} · {item['label']}" for item in self._alibaba_negotiation_catalog()]

    @rx.var
    def alibaba_has_negotiation_products(self) -> bool:
        return len(self.alibaba_negotiation_option_keys) > 0

    @rx.var
    def alibaba_negotiation_selected_label(self) -> str:
        for item in self._alibaba_negotiation_catalog():
            if item["key"] == self.alibaba_negotiation_product_key:
                return f"{item['key']} · {item['label']}"
        return ""

    @rx.var
    def alibaba_negotiation_is_unattractive(self) -> bool:
        return self.alibaba_negotiation_attractiveness == "ECONOMICALLY_UNATTRACTIVE"

    @rx.var
    def ml_sort_label(self) -> str:
        return ML_SORT_LABELS.get(self.ml_sort, "Original")

    @rx.var
    def ml_min_relevance_label(self) -> str:
        return ML_MIN_RELEVANCE_LABELS.get(self.ml_min_relevance, "60+")

    @rx.var
    def ml_filter_error(self) -> str:
        _minimum, _maximum, error = analysis.validate_price_filters(
            self.ml_price_min, self.ml_price_max
        )
        return error

    @rx.var
    def ml_visible_rows(self) -> list[MercadoLibreResultRow]:
        minimum, maximum, error = analysis.validate_price_filters(
            self.ml_price_min, self.ml_price_max
        )
        if error:
            minimum = None
            maximum = None
        return analysis.apply_table_view(
            self.ml_results,
            sort=self.ml_sort,
            minimum=minimum,
            maximum=maximum,
            hide_outliers=self.ml_hide_outliers,
            min_relevance=self.ml_min_relevance,
        )

    @rx.var
    def ml_counter(self) -> str:
        return analysis.showing_counter(len(self.ml_visible_rows), len(self.ml_results))

    @rx.var
    def ml_live_summary(self) -> dict[str, str]:
        return services.mercadolibre_summary_from_rows(
            self._ml_benchmark_row_maps(),
            min_relevance=self.ml_min_relevance,
            total_results=len(self.ml_results),
        )

    @rx.var
    def ml_comparison_comparable(self) -> bool:
        return self.ml_has_comparison and self.ml_comparison.get("comparable") == "1"

    @rx.var
    def ml_show_alibaba_association(self) -> bool:
        if not self.ml_has_alibaba_context or self.ml_ui_status != UI_SUCCESS:
            return False
        if self.ml_query.strip() != self.ml_last_search_query.strip():
            return False
        return self.ml_alibaba_context.get("external_id", "") == self.ml_association_product_id

    @rx.var
    def facebook_product_show_provenance(self) -> bool:
        if self.facebook_product_ui_status != UI_SUCCESS:
            return False
        if self.facebook_product_query.strip() != self.facebook_product_last_search_query.strip():
            return False
        return (
            bool(self.facebook_product_association_product_id)
            and self.facebook_product_association_product_id == self._facebook_product_active_id()
            and self.facebook_product_provenance.get("external_id", "")
            == self.facebook_product_association_product_id
        )

    @rx.var
    def ml_alibaba_association(self) -> dict[str, str]:
        if not self.ml_show_alibaba_association:
            return services.empty_alibaba_ml_association()
        selected_id = self.ml_alibaba_context.get("external_id", "")
        landed = self._landed_for_ml_product_currency(
            selected_id, self.ml_alibaba_context.get("currency")
        )
        context = services.build_alibaba_ml_context(
            external_id=selected_id,
            title=self.ml_alibaba_context.get("title", ""),
            supplier=self.ml_alibaba_context.get("supplier", ""),
            supplier_price=self.ml_alibaba_context.get("supplier_price", ""),
            currency=self.ml_alibaba_context.get("currency", ""),
            desired_quantity=self.ml_alibaba_context.get("desired_quantity", ""),
            landed_row=landed,
        )
        comparison = None
        if context["has_landed"] == "1":
            comparison = services.compare_mercadolibre_with_landed_cost(
                self._ml_benchmark_row_maps(),
                landed,
                min_relevance=self.ml_min_relevance,
            )
        return services.build_alibaba_ml_association(context, self.ml_live_summary, comparison)

    @rx.var
    def search_cta_label(self) -> str:
        return search_scope.cta_label(self.search_mode, self.search_platform)

    @rx.var
    def search_callout_primary(self) -> str:
        primary, _secondary = search_scope.search_callout(self.search_limit)
        return primary

    @rx.var
    def search_callout_secondary(self) -> str:
        _primary, secondary = search_scope.search_callout(self.search_limit)
        return secondary

    @rx.var
    def search_is_busy(self) -> bool:
        providers = self._search_providers()
        if self.search_session_providers:
            loading = self._generic_session_loading_flags()
            return any(loading.get(provider, False) for provider in providers)
        flags = {
            PLATFORM_ALIBABA: self.alibaba_is_loading,
            PLATFORM_FACEBOOK: self.facebook_product_is_loading,
            PLATFORM_ML: self.ml_is_loading,
        }
        return any(flags[provider] for provider in providers)

    @rx.var
    def search_progress_rows(self) -> list[SearchProgressRow]:
        rows: list[SearchProgressRow] = []
        for provider in self._search_providers():
            _count, detail = self._progress_count_and_detail(provider)
            rows.append(
                SearchProgressRow(
                    platform=provider,
                    label=search_scope.PLATFORM_LABELS[provider],
                    detail=detail,
                )
            )
        return rows

    def _live_search_providers(self) -> tuple[str, ...]:
        try:
            return search_scope.providers_for(self.search_mode, self.search_platform)
        except ValueError:
            return search_scope.ALL_PLATFORMS

    def _search_providers(self) -> tuple[str, ...]:
        if self.search_session_providers:
            return tuple(self.search_session_providers)
        return self._live_search_providers()

    def _generic_session_is_loading(
        self, stored_generation: int, stored_status: str, live_loading: bool
    ) -> bool:
        """Owned LOADING snapshots are still running. Finished owned snapshots ignore later live loads."""

        if stored_generation == self.search_generation:
            return stored_status == UI_LOADING
        return bool(live_loading)

    def _generic_session_loading_flags(self) -> dict[str, bool]:
        return {
            PLATFORM_ALIBABA: self._generic_session_is_loading(
                self.generic_session_alibaba.generation,
                self.generic_session_alibaba.status,
                self.alibaba_is_loading,
            ),
            PLATFORM_FACEBOOK: self._generic_session_is_loading(
                self.generic_session_facebook.generation,
                self.generic_session_facebook.status,
                self.facebook_product_is_loading,
            ),
            PLATFORM_ML: self._generic_session_is_loading(
                self.generic_session_ml.generation,
                self.generic_session_ml.status,
                self.ml_is_loading,
            ),
        }

    def _owned_progress_detail(
        self, *, provider: str, status: str, rows: list[Any]
    ) -> tuple[str, str]:
        count = str(len(self._canonical_search_rows(list(rows), status)))
        detail = search_scope.progress_label(status, count)
        if provider == PLATFORM_FACEBOOK and status == UI_SUCCESS:
            detail = f"{count} resultados válidos"
        return count, detail

    def _progress_count_and_detail(self, provider: str) -> tuple[str, str]:
        if provider == PLATFORM_ALIBABA:
            if self.generic_session_alibaba.generation == self.search_generation:
                alibaba_owned = self._owned_generic_alibaba()
                return self._owned_progress_detail(
                    provider=provider,
                    status=alibaba_owned.status,
                    rows=list(alibaba_owned.rows),
                )
            count = str(self.alibaba_summary.get("resultados") or len(self.alibaba_results))
            return count, search_scope.progress_label(self.alibaba_ui_status, count)
        if provider == PLATFORM_FACEBOOK:
            if self.generic_session_facebook.generation == self.search_generation:
                facebook_owned = self._owned_generic_facebook()
                return self._owned_progress_detail(
                    provider=provider,
                    status=facebook_owned.status,
                    rows=list(facebook_owned.rows),
                )
            count = str(
                self.facebook_product_summary.get("usable") or len(self.facebook_product_results)
            )
            detail = search_scope.progress_label(self.facebook_product_ui_status, count)
            if self.facebook_product_ui_status == UI_SUCCESS:
                detail = f"{count} resultados válidos"
            return count, detail
        if self.generic_session_ml.generation == self.search_generation:
            ml_owned = self._owned_generic_ml()
            return self._owned_progress_detail(
                provider=provider, status=ml_owned.status, rows=list(ml_owned.rows)
            )
        count = str(self.ml_summary.get("comparables") or len(self.ml_results))
        return count, search_scope.progress_label(self.ml_ui_status, count)

    @rx.var
    def search_session_phase(self) -> str:
        alibaba = self._owned_generic_alibaba()
        facebook = self._owned_generic_facebook()
        ml = self._owned_generic_ml()
        loading = self._generic_session_loading_flags()
        return search_session.session_phase(
            session_active=self.search_session_active,
            providers=self._search_providers(),
            loading=loading,
            statuses={
                PLATFORM_ALIBABA: alibaba.status,
                PLATFORM_FACEBOOK: facebook.status,
                PLATFORM_ML: ml.status,
            },
        )

    @rx.var
    def search_shows_setup(self) -> bool:
        return search_session.shows_setup(self.search_session_phase)

    @rx.var
    def search_shows_results(self) -> bool:
        return search_session.shows_results(self.search_session_phase)

    @rx.var
    def search_mode_label(self) -> str:
        mode = self.search_session_mode or self.search_mode
        return MODE_LABELS.get(mode, MODE_LABELS[MODE_MULTI])

    @rx.var
    def search_duration_label(self) -> str:
        return search_session.format_session_duration(self.search_elapsed_ms)

    @rx.var
    def search_total_results(self) -> str:
        alibaba = self._owned_generic_alibaba()
        facebook = self._owned_generic_facebook()
        ml = self._owned_generic_ml()
        return str(
            len(self._canonical_search_rows(list(alibaba.rows), alibaba.status))
            + len(self._canonical_search_rows(list(facebook.rows), facebook.status))
            + len(self._canonical_search_rows(list(ml.rows), ml.status))
        )

    @rx.var
    def price_distribution_tracks(self) -> list[dict[str, str]]:
        alibaba = self._owned_generic_alibaba()
        facebook = self._owned_generic_facebook()
        ml = self._owned_generic_ml()
        alibaba_stats = dict(alibaba.metadata.get("stats_raw") or {})
        facebook_stats_rows = list(facebook.metadata.get("statistics") or ())
        facebook_stats = facebook_stats_rows[0] if facebook_stats_rows else None
        ml_summary = self._visible_generic_ml_summary(ml)
        tracks = [
            search_session.boxplot_track(
                platform=PLATFORM_ALIBABA,
                minimum=alibaba_stats.get("minimum", ""),
                p25=alibaba_stats.get("p25", ""),
                median=alibaba_stats.get("median", ""),
                p75=alibaba_stats.get("p75", ""),
                maximum=alibaba_stats.get("maximum", ""),
                currency="USD",
                basis="USD",
            ),
            search_session.boxplot_track(
                platform=PLATFORM_FACEBOOK,
                minimum=getattr(facebook_stats, "minimum", ""),
                p25=getattr(facebook_stats, "p25", ""),
                median=getattr(facebook_stats, "median", ""),
                p75=getattr(facebook_stats, "p75", ""),
                maximum=getattr(facebook_stats, "maximum", ""),
                currency=getattr(facebook_stats, "currency", ""),
                basis=getattr(facebook_stats, "basis", ""),
            ),
            search_session.boxplot_track(
                platform=PLATFORM_ML,
                minimum=ml_summary.get("minimo", ""),
                p25=ml_summary.get("p25", ""),
                median=ml_summary.get("mediana", ""),
                p75=ml_summary.get("p75", ""),
                maximum=ml_summary.get("maximo", ""),
                currency=ml_summary.get("currency", ""),
                basis=ml_summary.get("currency", ""),
            ),
        ]
        return search_session.align_boxplot_tracks(tracks)

    @rx.var
    def search_quick_insight(self) -> str:
        return search_session.quick_insight(self.price_distribution_tracks)

    @rx.var
    def best_opportunity_available(self) -> bool:
        return (
            search_session.best_opportunity_copy(self._best_alibaba_row()).get("available") == "1"
        )

    @rx.var
    def best_opportunity_heading(self) -> str:
        return search_session.best_opportunity_copy(self._best_alibaba_row())["heading"]

    @rx.var
    def best_opportunity_detail(self) -> str:
        return search_session.best_opportunity_copy(self._best_alibaba_row())["detail"]

    def _best_alibaba_row(self) -> AlibabaResultRow | None:
        owned = self._owned_generic_alibaba()
        rows = [
            row
            for row in self._canonical_search_rows(list(owned.rows), owned.status)
            if isinstance(row, AlibabaResultRow)
        ]
        if not rows:
            return None
        return max(rows, key=lambda item: item.score_value)

    @rx.var
    def page_heading(self) -> str:
        context = self.ml_alibaba_context or self.facebook_product_alibaba_context
        return comparison.page_heading(
            alibaba_query=self.alibaba_query,
            facebook_query=self.facebook_product_query,
            ml_query=self.ml_query,
            h0019_query=self.query,
            alibaba_status=self.alibaba_ui_status,
            facebook_status=self.facebook_product_ui_status,
            ml_status=self.ml_ui_status,
            h0019_status=self.ui_status,
            workspace_view=self.workspace_view,
            facebook_association_id=self.facebook_product_association_product_id,
            ml_association_id=self.ml_association_product_id,
            context_id=str(context.get("external_id") or ""),
            context_title=str(context.get("title") or ""),
        )

    @rx.var
    def page_subtitle(self) -> str:
        parts: list[str] = []
        if self.ml_has_alibaba_context:
            title = str(self.ml_alibaba_context.get("title") or "").strip()
            if title:
                parts.append(title)
        elif self.facebook_product_has_alibaba_context:
            title = str(self.facebook_product_alibaba_context.get("title") or "").strip()
            if title:
                parts.append(title)
        if self.alibaba_ui_status == UI_SUCCESS and self.alibaba_summary.get("resultados"):
            parts.append(f"Alibaba · {self.alibaba_summary['resultados']} resultados")
        return " · ".join(parts)

    def _clear_generic_session_alibaba(self) -> None:
        self.generic_session_alibaba = GenericAlibabaSessionSnapshot()

    def _clear_generic_session_facebook(self) -> None:
        self.generic_session_facebook = GenericFacebookSessionSnapshot()

    def _clear_generic_session_ml(self) -> None:
        self.generic_session_ml = GenericMercadoLibreSessionSnapshot()

    def _replace_generic_session_alibaba(
        self,
        *,
        status: str,
        rows: list[AlibabaResultRow],
        summary: dict[str, str],
        stats_raw: dict[str, str],
        error: str,
    ) -> None:
        self.generic_session_alibaba = GenericAlibabaSessionSnapshot(
            generation=self.search_generation,
            status=status,
            rows=list(rows),
            summary=dict(summary),
            stats_raw=dict(stats_raw),
            error=error,
            requested_limit=self._generic_display_limit(),
        )

    def _replace_generic_session_facebook(
        self,
        *,
        status: str,
        rows: list[FacebookProductResultRow],
        summary: dict[str, str],
        statistics: list[FacebookCurrencyStatsRow],
        error: str,
    ) -> None:
        self.generic_session_facebook = GenericFacebookSessionSnapshot(
            generation=self.search_generation,
            status=status,
            rows=list(rows),
            summary=dict(summary),
            statistics=list(statistics),
            error=error,
            requested_limit=self._generic_display_limit(),
        )

    def _replace_generic_session_ml(
        self,
        *,
        status: str,
        rows: list[MercadoLibreResultRow],
        pipeline_summary: Mapping[str, str],
        error: str,
    ) -> None:
        diagnostic = self._generic_ml_statistics_from_rows(
            self._canonical_search_rows(list(rows), status),
            pipeline_summary=dict(pipeline_summary),
        )
        self.generic_session_ml = GenericMercadoLibreSessionSnapshot(
            generation=self.search_generation,
            status=status,
            rows=list(rows),
            summary=dict(diagnostic),
            diagnostic_summary=dict(diagnostic),
            error=error,
            requested_limit=self._generic_display_limit(),
        )

    def _stored_alibaba_snapshot(self) -> GenericSessionProviderSnapshot[AlibabaResultRow]:
        stored = self.generic_session_alibaba
        return GenericSessionProviderSnapshot(
            generation=stored.generation,
            status=stored.status,
            rows=tuple(stored.rows),
            summary=dict(stored.summary),
            error=stored.error,
            metadata={
                "stats_raw": dict(stored.stats_raw),
                "requested_limit": stored.requested_limit,
            },
        )

    def _live_alibaba_snapshot(self) -> GenericSessionProviderSnapshot[AlibabaResultRow]:
        return GenericSessionProviderSnapshot(
            generation=GENERIC_SESSION_UNSET_GENERATION,
            status=self.alibaba_ui_status,
            rows=tuple(self.alibaba_results),
            summary=dict(self.alibaba_summary),
            error=self.alibaba_error,
            metadata={
                "stats_raw": dict(self.alibaba_stats_raw),
                "requested_limit": self._generic_display_limit(),
            },
        )

    def _owned_generic_alibaba(self) -> GenericSessionProviderSnapshot[AlibabaResultRow]:
        return owned_generic_session_provider(
            stored=self._stored_alibaba_snapshot(),
            active_generation=self.search_generation,
            live=self._live_alibaba_snapshot(),
        )

    def _stored_facebook_snapshot(
        self,
    ) -> GenericSessionProviderSnapshot[FacebookProductResultRow]:
        stored = self.generic_session_facebook
        return GenericSessionProviderSnapshot(
            generation=stored.generation,
            status=stored.status,
            rows=tuple(stored.rows),
            summary=dict(stored.summary),
            error=stored.error,
            metadata={
                "statistics": tuple(stored.statistics),
                "requested_limit": stored.requested_limit,
            },
        )

    def _live_facebook_snapshot(self) -> GenericSessionProviderSnapshot[FacebookProductResultRow]:
        return GenericSessionProviderSnapshot(
            generation=GENERIC_SESSION_UNSET_GENERATION,
            status=self.facebook_product_ui_status,
            rows=tuple(self.facebook_product_results),
            summary=dict(self.facebook_product_summary),
            error=self.facebook_product_error,
            metadata={
                "statistics": tuple(self.facebook_product_statistics),
                "requested_limit": self._generic_display_limit(),
            },
        )

    def _owned_generic_facebook(self) -> GenericSessionProviderSnapshot[FacebookProductResultRow]:
        return owned_generic_session_provider(
            stored=self._stored_facebook_snapshot(),
            active_generation=self.search_generation,
            live=self._live_facebook_snapshot(),
        )

    def _stored_ml_snapshot(self) -> GenericSessionProviderSnapshot[MercadoLibreResultRow]:
        stored = self.generic_session_ml
        return GenericSessionProviderSnapshot(
            generation=stored.generation,
            status=stored.status,
            rows=tuple(stored.rows),
            summary=dict(stored.summary),
            error=stored.error,
            metadata={
                "diagnostic_summary": dict(stored.diagnostic_summary),
                "requested_limit": stored.requested_limit,
            },
        )

    def _live_ml_snapshot(self) -> GenericSessionProviderSnapshot[MercadoLibreResultRow]:
        diagnostic = self._generic_ml_statistics_from_rows(
            self._canonical_search_rows(list(self.ml_results), self.ml_ui_status),
            pipeline_summary=dict(self.ml_summary),
        )
        return GenericSessionProviderSnapshot(
            generation=GENERIC_SESSION_UNSET_GENERATION,
            status=self.ml_ui_status,
            rows=tuple(self.ml_results),
            summary=dict(diagnostic),
            error=self.ml_error,
            metadata={
                "diagnostic_summary": dict(diagnostic),
                "requested_limit": self._generic_display_limit(),
            },
        )

    def _owned_generic_ml(self) -> GenericSessionProviderSnapshot[MercadoLibreResultRow]:
        return owned_generic_session_provider(
            stored=self._stored_ml_snapshot(),
            active_generation=self.search_generation,
            live=self._live_ml_snapshot(),
        )

    def _generic_display_limit(self) -> int:
        """Display limit owned by the active generic generation, not the live UI control."""

        if self.search_session_limit >= 1:
            return self.search_session_limit
        return self.search_limit

    @rx.var
    def generic_display_limit(self) -> int:
        return self._generic_display_limit()

    def _canonical_search_rows(self, rows: list[Any], status: str) -> list[Any]:
        """Frozen generic-search prefix. Ignores specialized sort/filter projections."""

        return list(comparison.canonical_provider_rows(rows, status, self._generic_display_limit()))

    def _generic_ml_statistics_from_rows(
        self,
        rows: list[Any],
        *,
        pipeline_summary: Mapping[str, str],
    ) -> dict[str, str]:
        """Visible generic ML stats from canonical rows. Never apply specialized filters."""

        computed = services.mercadolibre_summary_from_rows(
            [_ml_row_mapping(item) for item in rows if isinstance(item, MercadoLibreResultRow)],
            min_relevance=0,
            total_results=len(rows),
        )
        merged = dict(computed)
        for key in ("requested", "fetched", "usable", "rejected"):
            value = str(pipeline_summary.get(key, "") or "").strip()
            if value:
                merged[key] = value
        return merged

    def _visible_generic_ml_summary(
        self,
        snapshot: GenericSessionProviderSnapshot[MercadoLibreResultRow],
    ) -> dict[str, str]:
        canonical = self._canonical_search_rows(list(snapshot.rows), snapshot.status)
        pipeline = dict(snapshot.metadata.get("diagnostic_summary") or snapshot.summary)
        return self._generic_ml_statistics_from_rows(canonical, pipeline_summary=pipeline)

    def _ml_diagnostic_summary_from(
        self,
        *,
        summary: Mapping[str, str],
        live_summary: Mapping[str, str],
    ) -> dict[str, str]:
        merged = dict(live_summary)
        for key in ("requested", "fetched", "usable", "rejected"):
            value = summary.get(key, "")
            if value:
                merged[key] = value
        return merged

    def _ml_diagnostic_summary(self) -> dict[str, str]:
        return self._ml_diagnostic_summary_from(
            summary=self.ml_summary,
            live_summary=dict(self.ml_live_summary),
        )

    @rx.var
    def marketplace_summaries(self) -> list[MarketplaceSummaryCard]:
        raw = marketplace_summary.build_marketplace_summaries(
            alibaba_ui_status=self.alibaba_ui_status,
            alibaba_summary=self.alibaba_summary,
            alibaba_rows=self.alibaba_visible_rows,
            facebook_ui_status=self.facebook_product_ui_status,
            facebook_summary=self.facebook_product_summary,
            facebook_statistics=self.facebook_product_statistics,
            facebook_rows=self.facebook_product_results,
            facebook_error=self.facebook_product_error,
            ml_ui_status=self.ml_ui_status,
            ml_summary=self._ml_diagnostic_summary(),
            ml_rows=self.ml_visible_rows,
        )
        attached = search_diagnostics.attach_diagnostics(
            raw,
            [
                search_diagnostics.alibaba_diagnostic(
                    ui_status=self.alibaba_ui_status,
                    summary=self.alibaba_summary,
                    requested_limit=self.search_limit,
                    usable_rows=len(self.alibaba_results),
                    error=self.alibaba_error,
                ),
                search_diagnostics.facebook_diagnostic(
                    ui_status=self.facebook_product_ui_status,
                    summary=self.facebook_product_summary,
                    requested_limit=self.search_limit,
                    usable_rows=len(self.facebook_product_results),
                    error=self.facebook_product_error,
                ),
                search_diagnostics.mercadolibre_diagnostic(
                    ui_status=self.ml_ui_status,
                    summary=self._ml_diagnostic_summary(),
                    requested_limit=self.search_limit,
                    usable_rows=len(self.ml_results),
                    error=self.ml_error,
                ),
            ],
            open_platforms=self.diagnostic_open_platforms,
        )
        return [MarketplaceSummaryCard.model_validate(item) for item in attached]

    @rx.var
    def generic_marketplace_summaries(self) -> list[MarketplaceSummaryCard]:
        alibaba = self._owned_generic_alibaba()
        facebook = self._owned_generic_facebook()
        ml = self._owned_generic_ml()
        canonical_alibaba = self._canonical_search_rows(list(alibaba.rows), alibaba.status)
        canonical_facebook = self._canonical_search_rows(list(facebook.rows), facebook.status)
        canonical_ml = self._canonical_search_rows(list(ml.rows), ml.status)
        ml_summary = self._visible_generic_ml_summary(ml)
        display_limit = self._generic_display_limit()
        alibaba_limit = int(alibaba.metadata.get("requested_limit") or display_limit)
        facebook_limit = int(facebook.metadata.get("requested_limit") or display_limit)
        ml_limit = int(ml.metadata.get("requested_limit") or display_limit)
        raw = marketplace_summary.build_marketplace_summaries(
            alibaba_ui_status=alibaba.status,
            alibaba_summary=dict(alibaba.summary),
            alibaba_rows=canonical_alibaba,
            facebook_ui_status=facebook.status,
            facebook_summary=dict(facebook.summary),
            facebook_statistics=list(facebook.metadata.get("statistics") or ()),
            facebook_rows=canonical_facebook,
            facebook_error=facebook.error,
            ml_ui_status=ml.status,
            ml_summary=ml_summary,
            ml_rows=canonical_ml,
        )
        attached = search_diagnostics.attach_diagnostics(
            raw,
            [
                search_diagnostics.alibaba_diagnostic(
                    ui_status=alibaba.status,
                    summary=dict(alibaba.summary),
                    requested_limit=alibaba_limit,
                    usable_rows=len(canonical_alibaba),
                    error=alibaba.error,
                ),
                search_diagnostics.facebook_diagnostic(
                    ui_status=facebook.status,
                    summary=dict(facebook.summary),
                    requested_limit=facebook_limit,
                    usable_rows=len(canonical_facebook),
                    error=facebook.error,
                ),
                search_diagnostics.mercadolibre_diagnostic(
                    ui_status=ml.status,
                    summary=ml_summary,
                    requested_limit=ml_limit,
                    usable_rows=len(canonical_ml),
                    error=ml.error,
                ),
            ],
            open_platforms=self.diagnostic_open_platforms,
        )
        return [MarketplaceSummaryCard.model_validate(item) for item in attached]

    @rx.var
    def comparison_rows(self) -> list[ComparisonRow]:
        fallback = (
            self.alibaba_query.strip()
            or self.facebook_product_query.strip()
            or self.ml_query.strip()
        )
        raw = comparison.build_comparison_rows(
            alibaba_rows=self.alibaba_visible_rows,
            facebook_rows=self.facebook_product_results,
            ml_rows=self.ml_visible_rows,
            alibaba_status=self.alibaba_ui_status,
            facebook_status=self.facebook_product_ui_status,
            ml_status=self.ml_ui_status,
            alibaba_context=self.ml_alibaba_context or self.facebook_product_alibaba_context,
            facebook_association_id=self.facebook_product_association_product_id,
            ml_association_id=self.ml_association_product_id,
            ml_comparison=self.ml_comparison if self.ml_has_comparison else None,
            landed=self.alibaba_landed_result if self.alibaba_landed_has_result else None,
            landed_product_id=self.alibaba_landed_product_id,
            fallback_title=fallback,
        )
        return [ComparisonRow.model_validate(item) for item in raw]

    @rx.var
    def has_comparison_rows(self) -> bool:
        return len(self.comparison_rows) > 0

    @rx.var
    def positional_comparison_rows(self) -> list[ComparisonRow]:
        alibaba = self._owned_generic_alibaba()
        facebook = self._owned_generic_facebook()
        ml = self._owned_generic_ml()
        raw = comparison.build_positional_comparison_rows(
            alibaba_rows=list(alibaba.rows),
            facebook_rows=list(facebook.rows),
            ml_rows=list(ml.rows),
            alibaba_status=alibaba.status,
            facebook_status=facebook.status,
            ml_status=ml.status,
            display_limit=self._generic_display_limit(),
        )
        return [ComparisonRow.model_validate(item) for item in raw]

    @rx.var
    def has_positional_comparison_rows(self) -> bool:
        return len(self.positional_comparison_rows) > 0

    def current_export_listing_count(self) -> int:
        alibaba = self._owned_generic_alibaba()
        facebook = self._owned_generic_facebook()
        ml = self._owned_generic_ml()
        count = 0
        if alibaba.status == UI_SUCCESS:
            count += len(self._canonical_search_rows(list(alibaba.rows), alibaba.status))
        if facebook.status == UI_SUCCESS:
            count += len(self._canonical_search_rows(list(facebook.rows), facebook.status))
        if ml.status == UI_SUCCESS:
            count += len(self._canonical_search_rows(list(ml.rows), ml.status))
        return count

    @rx.var
    def export_enabled(self) -> bool:
        return search_diagnostics.export_enabled(
            phase=self.search_session_phase,
            listing_count=self.current_export_listing_count(),
        )

    def toggle_provider_diagnostic(self, platform_id: str) -> None:
        current = list(self.diagnostic_open_platforms)
        key = str(platform_id or "")
        if not key:
            return
        if key in current:
            self.diagnostic_open_platforms = [item for item in current if item != key]
        else:
            self.diagnostic_open_platforms = [*current, key]

    def export_current_search(self) -> object:
        """Download current-session listings as CSV. Zero provider I/O."""

        alibaba = self._owned_generic_alibaba()
        facebook = self._owned_generic_facebook()
        ml = self._owned_generic_ml()
        canonical_alibaba = self._canonical_search_rows(list(alibaba.rows), alibaba.status)
        canonical_facebook = self._canonical_search_rows(list(facebook.rows), facebook.status)
        canonical_ml = self._canonical_search_rows(list(ml.rows), ml.status)
        ml_summary = self._visible_generic_ml_summary(ml)
        display_limit = self._generic_display_limit()
        alibaba_limit = int(alibaba.metadata.get("requested_limit") or display_limit)
        facebook_limit = int(facebook.metadata.get("requested_limit") or display_limit)
        ml_limit = int(ml.metadata.get("requested_limit") or display_limit)
        if not search_diagnostics.export_enabled(
            phase=self.search_session_phase,
            listing_count=self.current_export_listing_count(),
        ):
            return None
        alibaba_diag = search_diagnostics.alibaba_diagnostic(
            ui_status=alibaba.status,
            summary=dict(alibaba.summary),
            requested_limit=alibaba_limit,
            usable_rows=len(canonical_alibaba),
            error=alibaba.error,
        )
        facebook_diag = search_diagnostics.facebook_diagnostic(
            ui_status=facebook.status,
            summary=dict(facebook.summary),
            requested_limit=facebook_limit,
            usable_rows=len(canonical_facebook),
            error=facebook.error,
        )
        ml_diag = search_diagnostics.mercadolibre_diagnostic(
            ui_status=ml.status,
            summary=ml_summary,
            requested_limit=ml_limit,
            usable_rows=len(canonical_ml),
            error=ml.error,
        )
        rows = search_export.listing_rows_for_export(
            search_query=self.search_session_query or self.search_query,
            searched_at=self.search_completed_at,
            search_mode=self.search_mode_label,
            requested_limit=self._generic_display_limit(),
            alibaba_status=alibaba.status,
            alibaba_rows=canonical_alibaba,
            alibaba_diagnostic=alibaba_diag,
            facebook_status=facebook.status,
            facebook_rows=canonical_facebook,
            facebook_diagnostic=facebook_diag,
            ml_status=ml.status,
            ml_rows=canonical_ml,
            ml_diagnostic=ml_diag,
        )
        if not rows:
            return None
        payload = search_export.render_csv(rows)
        filename = search_export.export_filename(
            searched_at=self.search_completed_at,
            query=self.search_session_query or self.search_query,
        )
        return rx.download(data=payload, filename=filename, mime_type="text/csv;charset=utf-8")
