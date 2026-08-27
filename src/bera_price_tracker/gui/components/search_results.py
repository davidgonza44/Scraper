# mypy: disable-error-code="index,attr-defined,type-arg,arg-type,no-untyped-def,call-arg,func-returns-value,operator"
"""Completed search-session presentation matching REFERENCE B."""

from __future__ import annotations

import reflex as rx

from bera_price_tracker.gui import styles
from bera_price_tracker.gui.brands import PLATFORM_ALIBABA, PLATFORM_FACEBOOK
from bera_price_tracker.gui.components.brands import (
    marketplace_brand_alibaba,
    marketplace_brand_facebook,
    marketplace_brand_ml,
)
from bera_price_tracker.gui.components.comparison import positional_comparison_matrix
from bera_price_tracker.gui.components.primitives import action_button
from bera_price_tracker.gui.components.summary import generic_marketplace_summary_row
from bera_price_tracker.gui.state import TrackerState


def _status_icon() -> rx.Component:
    return rx.cond(
        TrackerState.search_session_phase == "COMPLETE",
        rx.hstack(
            rx.icon("circle-check", size=18, color=styles.POSITIVE),
            rx.text("Búsqueda completada", size="2", weight="medium", color=styles.POSITIVE),
            spacing="2",
            align="center",
        ),
        rx.cond(
            TrackerState.search_session_phase == "PARTIAL",
            rx.hstack(
                rx.icon("triangle-alert", size=18, color=styles.WARNING),
                rx.text(
                    "Búsqueda completada con incidencias",
                    size="2",
                    weight="medium",
                    color=styles.WARNING,
                ),
                spacing="2",
                align="center",
            ),
            rx.hstack(
                rx.icon("circle-alert", size=18, color=styles.DANGER),
                rx.text("Búsqueda con error", size="2", weight="medium", color=styles.DANGER),
                spacing="2",
                align="center",
            ),
        ),
    )


def results_header() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.heading(
                "Resultados de búsqueda",
                size="6",
                weight="bold",
                color=styles.TEXT_PRIMARY,
                style={"font_size": "24px", "letter_spacing": "-0.03em"},
            ),
            _status_icon(),
            spacing="3",
            align="center",
            flex_wrap="wrap",
        ),
        rx.text(TrackerState.search_session_query, size="2", color=styles.TEXT_MUTED),
        spacing="1",
        align_items="start",
        width="100%",
    )


def results_toolbar() -> rx.Component:
    return rx.hstack(
        rx.hstack(
            rx.icon("scale", size=14, color=styles.TEXT_MUTED),
            rx.text("Modo de búsqueda:", size="1", color=styles.TEXT_MUTED),
            rx.text(TrackerState.search_mode_label, size="1", weight="medium"),
            spacing="2",
            align="center",
        ),
        rx.hstack(
            rx.text("Resultados por plataforma:", size="1", color=styles.TEXT_MUTED),
            rx.text(TrackerState.generic_display_limit.to_string(), size="1", weight="medium"),
            spacing="2",
            align="center",
        ),
        rx.hstack(
            rx.text("Fecha de búsqueda:", size="1", color=styles.TEXT_MUTED),
            rx.text(TrackerState.search_completed_at, size="1", weight="medium"),
            spacing="2",
            align="center",
        ),
        rx.spacer(),
        action_button(
            "Nueva búsqueda",
            on_click=TrackerState.start_new_search,
            variant="outline",
            icon="search",
        ),
        width="100%",
        align="center",
        padding="10px 0",
        border_bottom=f"1px solid {styles.BORDER}",
        flex_wrap="wrap",
        spacing="4",
    )


def _boxplot_row(track: rx.Var) -> rx.Component:
    return rx.vstack(
        rx.cond(
            track["platform"] == PLATFORM_ALIBABA,
            marketplace_brand_alibaba(size=16),
            rx.cond(
                track["platform"] == PLATFORM_FACEBOOK,
                marketplace_brand_facebook(size=16),
                marketplace_brand_ml(size=16),
            ),
        ),
        rx.cond(
            track["available"] == "1",
            rx.box(
                rx.box(
                    class_name="bera-boxplot-whisker",
                    style={"left": "0%", "width": "100%"},
                ),
                rx.box(
                    class_name=track["box_class"],
                    style={
                        "left": track["box_left"],
                        "width": track["box_width"],
                    },
                ),
                rx.box(
                    class_name="bera-boxplot-median",
                    style={"left": track["median_left"]},
                ),
                class_name="bera-boxplot-track",
                width="100%",
            ),
            rx.text("No comparable", size="1", color=styles.TEXT_MUTED),
        ),
        spacing="1",
        width="100%",
        align_items="start",
    )


def search_summary_rail() -> rx.Component:
    return rx.vstack(
        rx.box(
            rx.text("Resumen de la búsqueda", size="2", weight="bold", color=styles.TEXT_PRIMARY),
            rx.vstack(
                rx.hstack(
                    rx.text("Plataformas", size="1", color=styles.TEXT_MUTED),
                    rx.spacer(),
                    rx.hstack(
                        marketplace_brand_alibaba(size=16, show_name=False),
                        marketplace_brand_facebook(size=16, show_name=False),
                        marketplace_brand_ml(size=16, show_name=False),
                        spacing="2",
                        align="center",
                    ),
                    width="100%",
                ),
                rx.hstack(
                    rx.text("Resultados por plataforma", size="1", color=styles.TEXT_MUTED),
                    rx.spacer(),
                    rx.text(
                        TrackerState.generic_display_limit.to_string(), size="1", weight="medium"
                    ),
                    width="100%",
                ),
                rx.hstack(
                    rx.text("Total de resultados", size="1", color=styles.TEXT_MUTED),
                    rx.spacer(),
                    rx.text(TrackerState.search_total_results, size="1", weight="medium"),
                    width="100%",
                ),
                rx.hstack(
                    rx.text("Tiempo de ejecución", size="1", color=styles.TEXT_MUTED),
                    rx.spacer(),
                    rx.text(TrackerState.search_duration_label, size="1", weight="medium"),
                    width="100%",
                ),
                spacing="2",
                width="100%",
                padding_top="10px",
            ),
            **styles.SURFACE_STYLE,
            padding="14px",
            width="100%",
        ),
        rx.box(
            rx.text("Mejor oportunidad encontrada", size="2", weight="bold"),
            rx.cond(
                TrackerState.best_opportunity_available,
                rx.vstack(
                    rx.text(
                        TrackerState.best_opportunity_heading,
                        size="2",
                        weight="medium",
                        color=styles.TEXT_PRIMARY,
                    ),
                    rx.text(
                        TrackerState.best_opportunity_detail, size="1", color=styles.TEXT_MUTED
                    ),
                    spacing="1",
                    align_items="start",
                ),
                rx.text("Análisis no disponible", size="2", color=styles.TEXT_MUTED),
            ),
            background_color="#EEF2FF",
            border="1px solid #C7D2FE",
            border_radius=styles.RADIUS_SM,
            padding="14px",
            width="100%",
        ),
        rx.box(
            rx.text("Distribución de precios", size="2", weight="bold"),
            rx.text("USD comparable · sin conversión", size="1", color=styles.TEXT_MUTED),
            rx.vstack(
                rx.foreach(TrackerState.price_distribution_tracks, _boxplot_row),
                spacing="3",
                width="100%",
                padding_top="10px",
            ),
            **styles.SURFACE_STYLE,
            padding="14px",
            width="100%",
        ),
        rx.cond(
            TrackerState.search_quick_insight != "",
            rx.box(
                rx.hstack(
                    rx.icon("lightbulb", size=14, color=styles.POSITIVE),
                    rx.text("Insight rápido", size="1", weight="medium", color=styles.POSITIVE),
                    spacing="2",
                ),
                rx.text(
                    TrackerState.search_quick_insight,
                    size="1",
                    color=styles.TEXT_PRIMARY,
                    padding_top="6px",
                ),
                background_color=styles.POSITIVE_BG,
                border_radius=styles.RADIUS_SM,
                padding="10px 12px",
                width="100%",
            ),
            rx.fragment(),
        ),
        spacing="3",
        width="100%",
        class_name="bera-results-rail",
    )


def results_section_nav() -> rx.Component:
    return rx.hstack(
        rx.text(
            "Comparación de productos",
            size="2",
            weight="medium",
            color=styles.PRIMARY,
            border_bottom=f"2px solid {styles.PRIMARY}",
            padding_bottom="6px",
        ),
        rx.spacer(),
        rx.button(
            rx.hstack(
                rx.icon("download", size=14),
                rx.text("Exportar"),
                spacing="2",
            ),
            on_click=TrackerState.export_current_search,
            disabled=~TrackerState.export_enabled,
            title=rx.cond(
                TrackerState.export_enabled,
                "Descargar CSV de la búsqueda actual",
                "La exportación no está disponible",
            ),
            aria_label=rx.cond(
                TrackerState.export_enabled,
                "Exportar resultados a CSV",
                "Exportar, no disponible",
            ),
            **styles.SECONDARY_BUTTON_STYLE,
            opacity=rx.cond(TrackerState.export_enabled, "1", "0.55"),
        ),
        width="100%",
        align="end",
        padding_bottom="8px",
        border_bottom=f"1px solid {styles.BORDER}",
    )


def search_results_view() -> rx.Component:
    return rx.vstack(
        results_header(),
        results_toolbar(),
        generic_marketplace_summary_row(),
        rx.box(
            rx.box(
                results_section_nav(),
                positional_comparison_matrix(),
                flex="1",
                min_width="0",
                class_name="bera-results-main",
            ),
            search_summary_rail(),
            class_name="bera-results-layout",
            width="100%",
        ),
        spacing="3",
        width="100%",
        align_items="stretch",
    )
