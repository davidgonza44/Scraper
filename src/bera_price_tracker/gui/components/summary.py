# mypy: disable-error-code="index,attr-defined,type-arg,arg-type,no-untyped-def,call-arg,func-returns-value"
"""Three consistent marketplace summary cards."""

from __future__ import annotations

import reflex as rx

from bera_price_tracker.gui import styles
from bera_price_tracker.gui.components.primitives import status_badge
from bera_price_tracker.gui.state import TrackerState


def marketplace_summary_card(card: rx.Var) -> rx.Component:
    accent = rx.cond(
        card["platform"] == "Alibaba",
        styles.ALIBABA,
        rx.cond(
            card["platform"] == "Facebook Marketplace",
            styles.FACEBOOK,
            styles.MERCADOLIBRE,
        ),
    )
    return rx.box(
        rx.hstack(
            rx.box(width="3px", height="28px", background_color=accent, border_radius="2px"),
            rx.text(card["platform"], size="3", weight="medium", color=styles.TEXT_PRIMARY),
            rx.spacer(),
            rx.cond(
                card["platform"] == "Alibaba",
                status_badge(card["result_count"] + " · " + card["status_label"], tone="alibaba"),
                rx.cond(
                    card["platform"] == "Facebook Marketplace",
                    status_badge(
                        card["result_count"] + " · " + card["status_label"], tone="facebook"
                    ),
                    status_badge(
                        card["result_count"] + " · " + card["status_label"], tone="mercadolibre"
                    ),
                ),
            ),
            width="100%",
            align="center",
        ),
        rx.hstack(
            rx.vstack(
                rx.text("Mínimo", size="1", color=styles.TEXT_MUTED),
                rx.text(card["minimum"], size="3", weight="medium", color=styles.TEXT_PRIMARY),
                spacing="0",
                align_items="start",
            ),
            rx.vstack(
                rx.text("Mediana", size="1", color=styles.TEXT_MUTED),
                rx.text(card["median"], size="3", weight="medium", color=styles.TEXT_PRIMARY),
                spacing="0",
                align_items="start",
            ),
            rx.vstack(
                rx.text("Promedio", size="1", color=styles.TEXT_MUTED),
                rx.text(card["average"], size="3", weight="medium", color=styles.TEXT_PRIMARY),
                spacing="0",
                align_items="start",
            ),
            rx.vstack(
                rx.text("Mejor", size="1", color=styles.TEXT_MUTED),
                rx.text(card["minimum"], size="3", weight="bold", color=styles.POSITIVE),
                spacing="0",
                align_items="start",
            ),
            spacing="6",
            padding_top="14px",
            width="100%",
            flex_wrap="wrap",
        ),
        rx.cond(
            card["range"] != "—",
            rx.text("Rango: " + card["range"], size="1", color=styles.TEXT_MUTED, padding_top="10px"),
        ),
        rx.cond(
            card["meta_one"] != "",
            rx.text(card["meta_one"], size="1", color=styles.TEXT_SECONDARY, padding_top="4px"),
        ),
        rx.cond(
            card["meta_two"] != "",
            rx.text(card["meta_two"], size="1", color=styles.TEXT_SECONDARY),
        ),
        rx.cond(
            card["note"] != "",
            rx.text(card["note"], size="1", color=styles.TEXT_MUTED, padding_top="6px"),
        ),
        **styles.SURFACE_STYLE,
        padding="18px 20px",
        min_width="0",
        flex="1",
    )


def marketplace_summary_row() -> rx.Component:
    return rx.hstack(
        rx.foreach(TrackerState.marketplace_summaries, marketplace_summary_card),
        spacing="3",
        width="100%",
        align="stretch",
        flex_wrap="wrap",
        class_name="bera-summary-row",
    )
