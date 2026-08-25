# mypy: disable-error-code="index,attr-defined,type-arg,arg-type,no-untyped-def,call-arg,func-returns-value,operator"
"""Reusable multi-market / single-market search panel."""

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
    PLATFORM_LABELS,
    SEARCH_LIMIT_OPTIONS,
)
from bera_price_tracker.gui.state import TrackerState

_UI_FIXTURES = os.environ.get("BERA_UI_FIXTURES") == "1"


def search_mode_selector() -> rx.Component:
    return rx.vstack(
        rx.text("Modo de búsqueda", **styles.LABEL_STYLE),
        rx.vstack(
            _tile_card(
                selected=TrackerState.search_mode == MODE_MULTI,
                on_click=TrackerState.set_search_mode_multi,
                mark=rx.icon("scale", size=20, color=styles.PRIMARY),
                title=MODE_LABELS[MODE_MULTI],
                detail=MODE_DESCRIPTIONS[MODE_MULTI],
            ),
            _tile_card(
                selected=TrackerState.search_mode == MODE_SINGLE,
                on_click=TrackerState.set_search_mode_single,
                mark=rx.icon("target", size=20, color=styles.PRIMARY),
                title=MODE_LABELS[MODE_SINGLE],
                detail=MODE_DESCRIPTIONS[MODE_SINGLE],
            ),
            spacing="2",
            width="100%",
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def results_limit_select() -> rx.Component:
    options = [str(item) for item in SEARCH_LIMIT_OPTIONS]
    return rx.vstack(
        rx.text("Resultados por plataforma", **styles.LABEL_STYLE),
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
                mark=marketplace_brand_alibaba(),
                title=PLATFORM_LABELS[PLATFORM_ALIBABA],
            ),
            _tile_card(
                selected=TrackerState.search_platform == PLATFORM_FACEBOOK,
                on_click=TrackerState.set_search_platform_facebook,
                mark=marketplace_brand_facebook(),
                title=PLATFORM_LABELS[PLATFORM_FACEBOOK],
            ),
            _tile_card(
                selected=TrackerState.search_platform == PLATFORM_ML,
                on_click=TrackerState.set_search_platform_ml,
                mark=marketplace_brand_ml(),
                title=PLATFORM_LABELS[PLATFORM_ML],
            ),
            spacing="2",
            width="100%",
            align="stretch",
            flex_wrap="wrap",
            class_name="bera-marketplace-selector",
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _multi_platform_preview() -> rx.Component:
    return rx.hstack(
        rx.box(
            marketplace_brand_alibaba(),
            rx.text(PLATFORM_LABELS[PLATFORM_ALIBABA], size="2", weight="medium"),
            **styles.UNSELECTED_CARD_STYLE,
            padding="12px 14px",
            display="flex",
            align_items="center",
            gap="10px",
            flex="1",
        ),
        rx.box(
            marketplace_brand_facebook(),
            rx.text(PLATFORM_LABELS[PLATFORM_FACEBOOK], size="2", weight="medium"),
            **styles.UNSELECTED_CARD_STYLE,
            padding="12px 14px",
            display="flex",
            align_items="center",
            gap="10px",
            flex="1",
        ),
        rx.box(
            marketplace_brand_ml(),
            **styles.UNSELECTED_CARD_STYLE,
            padding="12px 14px",
            display="flex",
            align_items="center",
            gap="10px",
            flex="1",
        ),
        spacing="2",
        width="100%",
        flex_wrap="wrap",
        class_name="bera-multi-brand-row",
    )


def search_summary_callout() -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.icon("info", size=16, color=styles.PRIMARY),
            rx.vstack(
                rx.text(TrackerState.search_callout_primary, size="2", color=styles.TEXT_PRIMARY),
                rx.text(TrackerState.search_callout_secondary, size="1", color=styles.TEXT_MUTED),
                spacing="0",
                align_items="start",
            ),
            spacing="3",
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
        flex_wrap="wrap",
    )


def _progress_chip(row: rx.Var) -> rx.Component:
    return rx.box(
        rx.text(row["label"], size="2", weight="medium", color=styles.TEXT_PRIMARY),
        rx.text(row["detail"], size="1", color=styles.TEXT_MUTED),
        **styles.UNSELECTED_CARD_STYLE,
        padding="10px 12px",
        min_width="160px",
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


def multi_market_search_panel() -> rx.Component:
    lower = rx.cond(
        TrackerState.search_mode == MODE_MULTI,
        rx.vstack(
            _multi_platform_preview(),
            search_summary_callout(),
            spacing="3",
            width="100%",
        ),
        rx.vstack(
            marketplace_selector(),
            search_summary_callout(),
            spacing="3",
            width="100%",
        ),
    )
    fixture = (
        rx.button(
            "Vista de prueba · error parcial",
            on_click=TrackerState.apply_partial_search_fixture,
            **styles.SECONDARY_BUTTON_STYLE,
        )
        if _UI_FIXTURES
        else rx.fragment()
    )
    return rx.box(
        rx.vstack(
            rx.vstack(
                rx.text("¿Qué producto quieres buscar?", **styles.LABEL_STYLE),
                rx.input(
                    value=TrackerState.search_query,
                    on_change=TrackerState.set_search_query,
                    placeholder="Mouse inalámbrico",
                    width="100%",
                    **styles.INPUT_STYLE,
                ),
                spacing="1",
                width="100%",
                align_items="start",
            ),
            search_mode_selector(),
            results_limit_select(),
            lower,
            rx.cond(
                TrackerState.search_error != "",
                rx.text(TrackerState.search_error, color=styles.DANGER, size="2"),
            ),
            provider_progress(),
            rx.hstack(rx.spacer(), fixture, _cta(), width="100%", align="center"),
            spacing="4",
            width="100%",
        ),
        **styles.SURFACE_STYLE,
        padding="20px 22px",
        width="100%",
    )
