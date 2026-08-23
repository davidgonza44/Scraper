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
from bera_price_tracker.application.services import alibaba_credit_warning
from bera_price_tracker.gui import analysis, services

UI_INITIAL = "INITIAL"
UI_LOADING = "LOADING"
UI_SUCCESS = "SUCCESS"
UI_EMPTY = "EMPTY"
UI_ERROR = "ERROR"

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
    first_price: str = ""
    last_updated: str = ""
    variation: str = ""
    history: str = ""
    url: str = ""
    snapshot_count: str = ""
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
                self.alibaba_is_loading = False
                self.alibaba_error = message
                self.alibaba_results = []
                self.alibaba_summary = {}
                self.alibaba_stats_raw = {}
                self.alibaba_ui_status = UI_ERROR
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
            self.alibaba_is_loading = False
            self.alibaba_error = ""
            self.alibaba_results = rows
            self.alibaba_summary = dict(payload.get("summary") or {})
            self.alibaba_stats_raw = dict(payload.get("stats_raw") or {})
            self.alibaba_ui_status = str(payload.get("ui_status") or UI_EMPTY)

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

    def _apply_tracked_payload(self, rows: list[dict[str, str]]) -> None:
        self.alibaba_tracked_rows = [
            AlibabaTrackedRow(
                product_id=str(item.get("product_id", "")),
                title=str(item.get("title", "")),
                supplier_name=str(item.get("supplier_name", "")),
                current_price=str(item.get("current_price", "")),
                first_price=str(item.get("first_price", "")),
                last_updated=str(item.get("last_updated", "")),
                variation=str(item.get("variation", "")),
                history=str(item.get("history", "")),
                url=str(item.get("url", "")),
                snapshot_count=str(item.get("snapshot_count", "")),
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
