# mypy: disable-error-code="index,attr-defined,type-arg,arg-type,no-untyped-def,call-arg,func-returns-value"
"""Polished Alibaba tracking cards with collapsed history."""

from __future__ import annotations

import reflex as rx

from bera_price_tracker.gui import styles
from bera_price_tracker.gui.components.media import product_thumbnail
from bera_price_tracker.gui.state import TrackerState


def history_accordion(item: rx.Var) -> rx.Component:
    return rx.box(
        rx.button(
            rx.hstack(
                rx.icon("chevron-down", size=14),
                rx.text("Ver historial (" + item["snapshot_count"] + ")", size="2", weight="medium"),
                spacing="2",
                align="center",
            ),
            on_click=lambda: TrackerState.toggle_alibaba_history(item["product_id"]),
            variant="ghost",
            color=styles.TEXT_SECONDARY,
            padding="0",
            height="auto",
            cursor="pointer",
        ),
        rx.cond(
            item["history_open"],
            rx.text(
                item["history"],
                size="1",
                color=styles.TEXT_MUTED,
                white_space="pre-line",
                padding_top="8px",
            ),
        ),
        padding_top="8px",
    )


def tracking_card(item: rx.Var) -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.checkbox(
                checked=item["selected"],
                on_change=lambda _checked: TrackerState.toggle_alibaba_refresh_selection(
                    item["product_id"]
                ),
            ),
            product_thumbnail(item["image_url"], alt=item["title"]),
            rx.vstack(
                rx.text(item["title"], size="3", weight="medium", color=styles.TEXT_PRIMARY),
                rx.text("Proveedor: " + item["supplier_name"], size="1", color=styles.TEXT_MUTED),
                spacing="1",
                align_items="start",
                min_width="0",
                flex="1",
            ),
            rx.vstack(
                rx.text(item["current_price"], weight="bold", color=styles.ALIBABA, size="6"),
                rx.cond(
                    item["published_range"] != "",
                    rx.text("Rango: " + item["published_range"], size="1", color=styles.TEXT_MUTED),
                ),
                rx.text("Baseline: " + item["baseline"], size="1", color=styles.TEXT_SECONDARY),
                rx.cond(
                    item["variation"] == "—",
                    rx.tooltip(
                        rx.text("Variación: —", size="1", color=styles.TEXT_PRIMARY),
                        content=(
                            "Se necesita una segunda comprobación comparable para "
                            "calcular la variación."
                        ),
                    ),
                    rx.text("Variación: " + item["variation"], size="1", color=styles.TEXT_PRIMARY),
                ),
                rx.text(
                    "Última actualización: " + item["last_updated"],
                    size="1",
                    color=styles.TEXT_MUTED,
                ),
                spacing="1",
                align_items="end",
            ),
            width="100%",
            align="start",
            spacing="4",
        ),
        rx.cond(
            item["first_price_tag"] != "",
            rx.tooltip(
                rx.text(
                    "Precio observado al seguir: " + item["first_price"] + " · Discovery",
                    size="1",
                    color=styles.TEXT_MUTED,
                    padding_top="8px",
                ),
                content=(
                    "Este precio proviene de la búsqueda inicial y puede "
                    "representar un rango. Las variaciones comienzan cuando se "
                    "obtiene un precio comparable mediante seguimiento."
                ),
            ),
            rx.text(
                "Precio observado al seguir: " + item["first_price"],
                size="1",
                color=styles.TEXT_MUTED,
                padding_top="8px",
            ),
        ),
        history_accordion(item),
        rx.hstack(
            rx.button(
                "Actualizar",
                on_click=TrackerState.request_alibaba_refresh_one(item["product_id"]),
                size="2",
                **styles.SECONDARY_BUTTON_STYLE,
            ),
            rx.button(
                "Dejar de seguir",
                on_click=TrackerState.unfollow_alibaba_product(item["product_id"]),
                size="2",
                **styles.SECONDARY_BUTTON_STYLE,
            ),
            rx.button(
                "Buscar comparables en Venezuela",
                on_click=TrackerState.prepare_ml_comparables_from_alibaba_tracked(item["product_id"]),
                size="2",
                **styles.SECONDARY_BUTTON_STYLE,
            ),
            rx.button(
                "Buscar comparables en Facebook",
                on_click=TrackerState.prepare_facebook_comparables_from_alibaba_tracked(
                    item["product_id"]
                ),
                size="2",
                **styles.SECONDARY_BUTTON_STYLE,
            ),
            spacing="2",
            padding_top="12px",
            flex_wrap="wrap",
        ),
        **styles.SURFACE_STYLE,
        padding="16px 18px",
        width="100%",
    )
