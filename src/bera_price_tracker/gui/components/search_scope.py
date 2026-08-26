# mypy: disable-error-code="index,attr-defined,type-arg,arg-type,no-untyped-def,call-arg,func-returns-value,operator"
"""Reusable multi-market / single-market search setup panel."""

from __future__ import annotations

import os

import reflex as rx

from bera_price_tracker.gui import styles
from bera_price_tracker.gui.brands import PLATFORM_ALIBABA, PLATFORM_FACEBOOK, PLATFORM_ML
from bera_price_tracker.gui.components.brands import (
    _tile_card,
    marketplace_brand_alibaba,
    marketplace_brand_facebook,
    marketplace_brand_ml,
)
from bera_price_tracker.gui.search_scope import (
    MODE_DESCRIPTIONS,
    MODE_LABELS,
    MODE_MULTI,
    MODE_SINGLE,
    SEARCH_LIMIT_OPTIONS,
    SEARCH_SETUP_SUBTITLE,
    SEARCH_SETUP_TITLE,
)
from bera_price_tracker.gui.search_session import should_render_search_fixtures
from bera_price_tracker.gui.state import TrackerState


def search_setup_header() -> rx.Component:
    return rx.vstack(
        rx.heading(
            SEARCH_SETUP_TITLE,
            size="6",
            weight="bold",
            color=styles.TEXT_PRIMARY,
            style={"font_size": "26px", "letter_spacing": "-0.03em", "line_height": "1.2"},
        ),
        rx.text(SEARCH_SETUP_SUBTITLE, size="2", color=styles.TEXT_MUTED),
        spacing="1",
        align_items="start",
        width="100%",
        padding_bottom="4px",
    )


def search_query_field() -> rx.Component:
    return rx.vstack(
        rx.text("¿Qué producto quieres buscar?", **styles.LABEL_STYLE),
        rx.box(
            rx.box(
                rx.icon("search", size=16, color=styles.TEXT_MUTED),
                class_name="bera-query-icon",
            ),
            rx.input(
                value=TrackerState.search_query,
                on_change=TrackerState.set_search_query,
                placeholder="Mouse inalámbrico",
                width="100%",
                **styles.INPUT_STYLE,
            ),
            rx.cond(
                TrackerState.search_query != "",
                rx.box(
                    rx.icon(
                        "x",
                        size=16,
                        color=styles.TEXT_MUTED,
                        cursor="pointer",
                        on_click=TrackerState.clear_search_query,
                    ),
                    class_name="bera-query-clear",
                ),
                rx.fragment(),
            ),
            class_name="bera-query-wrap",
            width="100%",
        ),
        spacing="1",
        width="100%",
        align_items="start",
    )


def search_mode_selector() -> rx.Component:
    return rx.vstack(
        rx.text("Modo de búsqueda", **styles.LABEL_STYLE),
        rx.hstack(
            _tile_card(
                selected=TrackerState.search_mode == MODE_MULTI,
                on_click=TrackerState.set_search_mode_multi,
                mark=rx.icon("scale", size=18, color=styles.PRIMARY),
                title=MODE_LABELS[MODE_MULTI],
                detail=MODE_DESCRIPTIONS[MODE_MULTI],
            ),
            _tile_card(
                selected=TrackerState.search_mode == MODE_SINGLE,
                on_click=TrackerState.set_search_mode_single,
                mark=rx.icon("target", size=18, color=styles.PRIMARY),
                title=MODE_LABELS[MODE_SINGLE],
                detail=MODE_DESCRIPTIONS[MODE_SINGLE],
            ),
            spacing="3",
            width="100%",
            align="stretch",
            class_name="bera-mode-row",
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def results_limit_select(*, label: str = "Resultados por plataforma") -> rx.Component:
    options = [str(item) for item in SEARCH_LIMIT_OPTIONS]
    return rx.vstack(
        rx.text(label, **styles.LABEL_STYLE),
        rx.select(
            options,
            value=TrackerState.search_limit.to_string(),
            on_change=TrackerState.set_search_limit,
            width="140px",
            **styles.SELECT_STYLE,
        ),
        spacing="1",
        align_items="start",
    )


def marketplace_selector() -> rx.Component:
    return rx.vstack(
        rx.text("Selecciona la plataforma", **styles.LABEL_STYLE),
        rx.hstack(
            _tile_card(
                selected=TrackerState.search_platform == PLATFORM_ALIBABA,
                on_click=TrackerState.set_search_platform_alibaba,
                mark=marketplace_brand_alibaba(show_name=True),
                title="",
            ),
            _tile_card(
                selected=TrackerState.search_platform == PLATFORM_FACEBOOK,
                on_click=TrackerState.set_search_platform_facebook,
                mark=marketplace_brand_facebook(show_name=True),
                title="",
            ),
            _tile_card(
                selected=TrackerState.search_platform == PLATFORM_ML,
                on_click=TrackerState.set_search_platform_ml,
                mark=marketplace_brand_ml(show_name=True),
                title="",
            ),
            spacing="2",
            width="100%",
            align="stretch",
            class_name="bera-platform-row",
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _preview_tile(mark: rx.Component) -> rx.Component:
    return rx.box(
        rx.vstack(
            mark,
            rx.text(
                TrackerState.search_limit.to_string() + " resultados",
                size="1",
                color=styles.TEXT_MUTED,
            ),
            spacing="1",
            align_items="start",
            width="100%",
        ),
        **styles.UNSELECTED_CARD_STYLE,
        padding="12px 14px",
        flex="1",
        min_width="0",
    )


def _multi_platform_preview() -> rx.Component:
    return rx.hstack(
        _preview_tile(marketplace_brand_alibaba()),
        _preview_tile(marketplace_brand_facebook()),
        _preview_tile(marketplace_brand_ml()),
        spacing="2",
        width="100%",
        class_name="bera-platform-row",
    )


def search_summary_callout() -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.icon("info", size=14, color=styles.PRIMARY),
            rx.vstack(
                rx.text(TrackerState.search_callout_primary, size="2", color=styles.TEXT_PRIMARY),
                rx.text(TrackerState.search_callout_secondary, size="1", color=styles.TEXT_MUTED),
                spacing="0",
                align_items="start",
            ),
            spacing="2",
            align="start",
        ),
        **styles.CALLOUT_STYLE,
        width="100%",
    )


def provider_progress() -> rx.Component:
    return rx.hstack(
        rx.foreach(TrackerState.search_progress_rows, _progress_chip),
        spacing="2",
        width="100%",
        class_name="bera-platform-row",
    )


def _progress_chip(row: rx.Var) -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.cond(
                row["platform"] == PLATFORM_ALIBABA,
                marketplace_brand_alibaba(size=18),
                rx.cond(
                    row["platform"] == PLATFORM_FACEBOOK,
                    marketplace_brand_facebook(size=18),
                    marketplace_brand_ml(size=18),
                ),
            ),
            rx.spacer(),
            rx.text(row["detail"], size="1", color=styles.TEXT_MUTED),
            width="100%",
            align="center",
        ),
        **styles.UNSELECTED_CARD_STYLE,
        padding="8px 12px",
        min_width="0",
        flex="1",
    )


def _cta() -> rx.Component:
    return rx.button(
        rx.cond(
            TrackerState.search_is_busy,
            rx.hstack(rx.spinner(size="1"), rx.text("Buscando..."), spacing="2"),
            rx.hstack(
                rx.icon("search", size=16),
                rx.text(TrackerState.search_cta_label),
                spacing="2",
                align="center",
            ),
        ),
        on_click=TrackerState.run_scoped_search,
        disabled=TrackerState.search_is_busy,
        **styles.BUTTON_STYLE,
        padding_x="18px",
    )


def _fixture_controls() -> rx.Component:
    if not should_render_search_fixtures(os.environ):
        return rx.fragment()
    return rx.hstack(
        rx.button(
            "Vista de prueba · buscando",
            on_click=TrackerState.apply_running_search_fixture,
            **styles.SECONDARY_BUTTON_STYLE,
        ),
        rx.button(
            "Vista de prueba · completa",
            on_click=TrackerState.apply_complete_search_fixture,
            **styles.SECONDARY_BUTTON_STYLE,
        ),
        rx.button(
            "Vista de prueba · error parcial",
            on_click=TrackerState.apply_partial_search_fixture,
            **styles.SECONDARY_BUTTON_STYLE,
        ),
        rx.button(
            "Vista de prueba · diagnósticos",
            on_click=TrackerState.apply_zero_result_diagnostic_fixture,
            **styles.SECONDARY_BUTTON_STYLE,
        ),
        spacing="2",
        flex_wrap="wrap",
    )


def multi_market_search_panel() -> rx.Component:
    lower = rx.cond(
        TrackerState.search_mode == MODE_MULTI,
        rx.vstack(
            results_limit_select(label="Resultados por plataforma"),
            _multi_platform_preview(),
            search_summary_callout(),
            spacing="3",
            width="100%",
        ),
        rx.vstack(
            marketplace_selector(),
            results_limit_select(label="Cantidad de resultados"),
            search_summary_callout(),
            spacing="3",
            width="100%",
        ),
    )
    return rx.box(
        rx.vstack(
            search_query_field(),
            search_mode_selector(),
            lower,
            rx.cond(
                TrackerState.search_error != "",
                rx.text(TrackerState.search_error, color=styles.DANGER, size="2"),
            ),
            rx.cond(TrackerState.search_is_busy, provider_progress(), rx.fragment()),
            rx.hstack(rx.spacer(), _fixture_controls(), _cta(), width="100%", align="center"),
            spacing="3",
            width="100%",
        ),
        **styles.SURFACE_STYLE,
        padding="16px 18px",
        width="100%",
    )


def search_setup_view() -> rx.Component:
    return rx.vstack(
        search_setup_header(),
        multi_market_search_panel(),
        spacing="3",
        width="100%",
        align_items="stretch",
    )
