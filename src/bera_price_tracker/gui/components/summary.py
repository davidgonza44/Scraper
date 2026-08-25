# mypy: disable-error-code="index,attr-defined,type-arg,arg-type,no-untyped-def,call-arg,func-returns-value,operator"
"""Three consistent marketplace summary cards."""

from __future__ import annotations

import reflex as rx

from bera_price_tracker.gui import styles
from bera_price_tracker.gui.brands import PLATFORM_ALIBABA, PLATFORM_FACEBOOK
from bera_price_tracker.gui.components.brands import (
    marketplace_brand_alibaba,
    marketplace_brand_facebook,
    marketplace_brand_ml,
)
from bera_price_tracker.gui.components.primitives import rating_stars, status_badge
from bera_price_tracker.gui.state import TrackerState


def _platform_mark(card: rx.Var) -> rx.Component:
    return rx.cond(
        card["platform_id"] == PLATFORM_ALIBABA,
        marketplace_brand_alibaba(),
        rx.cond(
            card["platform_id"] == PLATFORM_FACEBOOK,
            marketplace_brand_facebook(),
            marketplace_brand_ml(),
        ),
    )


def marketplace_summary_card(card: rx.Var) -> rx.Component:
    return rx.box(
        rx.hstack(
            _platform_mark(card),
            rx.spacer(),
            rx.cond(
                card["platform_id"] == PLATFORM_ALIBABA,
                status_badge(card["result_count"] + " resultados", tone="alibaba"),
                rx.cond(
                    card["platform_id"] == PLATFORM_FACEBOOK,
                    status_badge(card["result_count"] + " resultados", tone="facebook"),
                    status_badge(card["result_count"] + " resultados", tone="mercadolibre"),
                ),
            ),
            width="100%",
            align="center",
        ),
        rx.hstack(
            rx.vstack(
                rx.text("Promedio", size="1", color=styles.TEXT_MUTED),
                rx.text(card["average"], size="4", weight="bold", color=styles.TEXT_PRIMARY),
                spacing="0",
                align_items="start",
            ),
            rx.vstack(
                rx.text("Mediana", size="1", color=styles.TEXT_MUTED),
                rx.text(card["median"], size="4", weight="bold", color=styles.TEXT_PRIMARY),
                spacing="0",
                align_items="start",
            ),
            rx.vstack(
                rx.text("Mejor precio", size="1", color=styles.TEXT_MUTED),
                rx.text(card["minimum"], size="4", weight="bold", color=styles.POSITIVE),
                spacing="0",
                align_items="start",
            ),
            spacing="5",
            padding_top="12px",
            width="100%",
            flex_wrap="wrap",
        ),
        rx.cond(
            card["range"] != "—",
            rx.box(
                rx.text(
                    "Rango de precios: " + card["range"],
                    size="1",
                    color=styles.TEXT_SECONDARY,
                ),
                class_name="bera-range-strip",
                margin_top="10px",
            ),
            rx.fragment(),
        ),
        rx.cond(
            card["meta_one"] != "",
            rx.text(card["meta_one"], size="1", color=styles.TEXT_SECONDARY, padding_top="8px"),
        ),
        rx.hstack(
            rx.cond(
                card["meta_two"] != "",
                rx.text(card["meta_two"], size="1", color=styles.TEXT_SECONDARY),
                rx.fragment(),
            ),
            rx.spacer(),
            rating_stars(card["rating_available"], card["rating_filled"], card["rating_label"]),
            width="100%",
            align="center",
            padding_top="6px",
        ),
        rx.cond(
            card["note"] != "",
            rx.text(card["note"], size="1", color=styles.TEXT_MUTED, padding_top="6px"),
        ),
        **styles.SURFACE_STYLE,
        padding="14px 16px",
        min_width="0",
        flex="1",
    )


def marketplace_summary_row() -> rx.Component:
    return rx.hstack(
        rx.foreach(TrackerState.marketplace_summaries, marketplace_summary_card),
        spacing="3",
        width="100%",
        align="stretch",
        class_name="bera-summary-row",
    )
