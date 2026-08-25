# mypy: disable-error-code="index,attr-defined,type-arg,arg-type,no-untyped-def,call-arg,func-returns-value"
"""Compact search toolbar."""

from __future__ import annotations

import reflex as rx

from bera_price_tracker.gui import styles
from bera_price_tracker.gui.state import TrackerState


def compact_alibaba_search() -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.vstack(
                rx.text("Consulta", **styles.LABEL_STYLE),
                rx.input(
                    value=TrackerState.alibaba_query,
                    on_change=TrackerState.set_alibaba_query,
                    placeholder="Mouse inalámbrico 2.4 GHz recargable",
                    width="100%",
                    **styles.INPUT_STYLE,
                ),
                spacing="1",
                width="100%",
                align_items="start",
            ),
            rx.vstack(
                rx.text("Límite", **styles.LABEL_STYLE),
                rx.input(
                    type="number",
                    min=1,
                    max=500,
                    value=TrackerState.alibaba_limit,
                    on_change=TrackerState.set_alibaba_limit,
                    width="88px",
                    **styles.INPUT_STYLE,
                ),
                spacing="1",
                align_items="start",
            ),
            rx.button(
                rx.cond(
                    TrackerState.alibaba_is_loading,
                    rx.hstack(rx.spinner(size="1"), rx.text("Buscando..."), spacing="2"),
                    rx.text("Buscar productos"),
                ),
                on_click=TrackerState.search_alibaba,
                disabled=TrackerState.alibaba_is_loading,
                **styles.BUTTON_STYLE,
            ),
            spacing="3",
            width="100%",
            align="end",
            flex_wrap="wrap",
        ),
        rx.cond(
            TrackerState.alibaba_warning != "",
            rx.text(TrackerState.alibaba_warning, color=styles.DANGER, size="2", padding_top="8px"),
        ),
        **styles.SURFACE_STYLE,
        padding="16px 18px",
        width="100%",
    )
