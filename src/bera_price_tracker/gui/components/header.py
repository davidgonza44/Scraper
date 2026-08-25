# mypy: disable-error-code="index,attr-defined,type-arg,arg-type,no-untyped-def,call-arg,func-returns-value,operator"
"""Page header with real search context and reserved export affordance."""

from __future__ import annotations

import reflex as rx

from bera_price_tracker.gui import styles
from bera_price_tracker.gui.components.primitives import action_button
from bera_price_tracker.gui.state import TrackerState


def page_header() -> rx.Component:
    return rx.hstack(
        rx.vstack(
            rx.heading(
                TrackerState.page_heading,
                size="7",
                weight="medium",
                color=styles.TEXT_PRIMARY,
                style={"font_size": "28px", "letter_spacing": "-0.03em", "line_height": "1.2"},
            ),
            rx.cond(
                TrackerState.page_subtitle != "",
                rx.text(TrackerState.page_subtitle, size="2", color=styles.TEXT_MUTED),
            ),
            spacing="1",
            align_items="start",
            min_width="0",
        ),
        rx.spacer(),
        rx.hstack(
            action_button(
                "Nueva búsqueda",
                on_click=TrackerState.show_searches,
                icon="search",
            ),
            rx.button(
                rx.hstack(
                    rx.icon("download", size=16),
                    rx.text("Exportar · no disponible"),
                    spacing="2",
                    align="center",
                ),
                disabled=True,
                title="La exportación no está disponible",
                aria_label="Exportar, no disponible",
                background=styles.SURFACE,
                color=styles.TEXT_PRIMARY,
                border=f"1px solid {styles.BORDER_STRONG}",
                border_radius=styles.RADIUS_SM,
                height=styles.CONTROL_HEIGHT,
                min_height=styles.CONTROL_HEIGHT,
                font_size="14px",
                font_weight="600",
                padding_x="16px",
                opacity="0.55",
                cursor="not-allowed",
            ),
            spacing="3",
            flex_wrap="wrap",
        ),
        width="100%",
        align="start",
        padding_bottom="22px",
        spacing="4",
        flex_wrap="wrap",
    )
