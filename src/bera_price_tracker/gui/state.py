"""TrackerState — serializable fields only. Collect via services."""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal, InvalidOperation

import reflex as rx

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
from bera_price_tracker.application.services import (
    alibaba_credit_warning,
    mercadolibre_credit_warning,
)
from bera_price_tracker.gui import analysis, services

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


class DetailItem(rx.Base):
    label: str = ""
    value: str = ""


class AlibabaTrackedRow(rx.Base):
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


class AlibabaResultRow(rx.Base):
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


class MercadoLibreResultRow(rx.Base):
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


class ResultRow(rx.Base):
    title: str = ""
    price: str = ""
    price_raw: str = ""
    currency: str = ""
    compatibility: str = ""
    city: str = ""
    source: str = ""
    url: str = ""
    details_items: list[DetailItem] = []


class TrackerState(rx.State):
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

    def show_facebook_tab(self) -> None:
        self.marketplace_tab = "facebook"

    def show_alibaba_tab(self) -> None:
        self.marketplace_tab = "alibaba"
        self.refresh_alibaba_tracking()

    def show_mercadolibre_tab(self) -> None:
        self.marketplace_tab = "mercadolibre"

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
        landed = self.alibaba_landed_result if self.alibaba_landed_has_result else None
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
                image_url=str(item.get("image_url", "")),
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
    ) -> None:
        # A second search cannot start while alibaba_is_loading is True, so this
        # in-flight request still owns the loading flag when query/limit changed.
        if (
            request_query.strip() != self.alibaba_query.strip()
            or request_limit != self.alibaba_limit
        ):
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
        keep_user_query = (
            not product_changed or self.ml_query_origin == services.ML_QUERY_ORIGIN_USER
        )
        self.ml_alibaba_context = context
        self.ml_has_alibaba_context = True
        if keep_user_query:
            self.ml_query = services.suggest_mercadolibre_query(
                current_query=self.ml_query,
                fallback_query=self.alibaba_query,
            )
            if not self.ml_query_origin and self.ml_query:
                self.ml_query_origin = services.ML_QUERY_ORIGIN_FALLBACK
        else:
            self.ml_query = services.suggest_mercadolibre_query(
                current_query="",
                fallback_query=self.alibaba_query,
            )
            self.ml_query_origin = services.ML_QUERY_ORIGIN_FALLBACK if self.ml_query else ""
        self._reset_product_translation_state(configured=services.azure_translator_is_configured())
        self.marketplace_tab = "mercadolibre"
        if product_changed:
            self.ml_results = []
            self.ml_summary = {}
            self.ml_ui_status = UI_INITIAL
            self.ml_error = ""
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
    ) -> None:
        # A second search cannot start while ml_is_loading is True, so this
        # in-flight request still owns the loading flag when context/query changed.
        current_product_id = self._ml_active_search_product_id()
        if search_product_id != current_product_id or query.strip() != self.ml_query.strip():
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
                thumbnail_url=str(item.get("thumbnail_url", "")),
                country=str(item.get("country", "—")),
                representative=str(item.get("representative", "")),
                relevance_value=int(item.get("relevance_value", 0) or 0),
                relevance=str(item.get("relevance", "")),
                relevance_label=str(item.get("relevance_label", "")),
                relevance_tokens=str(item.get("relevance_tokens", "")),
                is_outlier=bool(item.get("is_outlier", False)),
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
            )

    def compare_ml_with_landed_cost(self) -> None:
        if self.ml_has_alibaba_context:
            selected_id = self.ml_alibaba_context.get("external_id", "")
            landed = self._landed_for_ml_product_currency(
                selected_id, self.ml_alibaba_context.get("currency")
            )
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
        selected = set(self.alibaba_refresh_selected_ids)
        rows: list[AlibabaTrackedRow] = []
        for row in self.alibaba_tracked_rows:
            is_selected = bool(row.product_id) and row.product_id in selected
            if row.selected == is_selected:
                rows.append(row)
                continue
            rows.append(row.copy(update={"selected": is_selected}))
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
            rows.append(row.copy(update={"is_followed": is_followed}))
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
