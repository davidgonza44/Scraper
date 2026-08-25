# mypy: disable-error-code="index,attr-defined,type-arg,arg-type,no-untyped-def,call-arg,func-returns-value,operator"
"""Horizontal same-product comparison matrix."""

from __future__ import annotations

import reflex as rx

from bera_price_tracker.gui import styles
from bera_price_tracker.gui.components.media import product_thumbnail
from bera_price_tracker.gui.components.primitives import empty_state, price_metric, status_badge
from bera_price_tracker.gui.state import TrackerState


def _listing_link(url: object, label: str = "Ver publicación") -> rx.Component:
    return rx.cond(
        url != "",
        rx.link(
            rx.hstack(
                rx.text(label, size="1", weight="medium"),
                rx.icon("external-link", size=12),
                spacing="1",
                align="center",
            ),
            href=url,
            is_external=True,
            color=styles.PRIMARY,
            padding_top="8px",
        ),
        rx.fragment(),
    )


def _empty_cell(label: str) -> rx.Component:
    return rx.box(
        rx.text(label, size="2", color=styles.TEXT_MUTED),
        padding="8px 0",
    )


def product_cell(row: rx.Var) -> rx.Component:
    return rx.hstack(
        product_thumbnail(row["product_image_url"], alt=row["product_title"]),
        rx.vstack(
            rx.text(row["product_title"], size="2", weight="medium", color=styles.TEXT_PRIMARY),
            rx.text(row["product_subtitle"], size="1", color=styles.TEXT_MUTED),
            spacing="1",
            align_items="start",
            min_width="0",
        ),
        spacing="3",
        align="start",
        min_width="220px",
    )


def marketplace_cell(
    *,
    has_listing: object,
    image_url: object,
    title: object,
    price: object,
    price_color: str,
    line_one: object,
    line_two: object,
    line_three: object,
    relevance: object,
    match_label: object,
    url: object,
    empty_label: str,
) -> rx.Component:
    return rx.cond(
        has_listing,
        rx.vstack(
            product_thumbnail(image_url, alt=title, size="64px"),
            price_metric(price, color=price_color),
            rx.cond(line_one != "", rx.text(line_one, size="1", color=styles.TEXT_MUTED)),
            rx.cond(line_two != "", rx.text(line_two, size="1", color=styles.TEXT_SECONDARY)),
            rx.cond(line_three != "", rx.text(line_three, size="1", color=styles.TEXT_SECONDARY)),
            rx.cond(
                match_label != "",
                status_badge(match_label, tone="neutral"),
            ),
            rx.cond(
                relevance != "",
                rx.hstack(
                    rx.text("Relevancia", size="1", color=styles.TEXT_MUTED),
                    rx.text(relevance, size="1", color=styles.TEXT_MUTED),
                    spacing="1",
                ),
            ),
            _listing_link(url),
            spacing="1",
            align_items="start",
            min_width="190px",
        ),
        _empty_cell(empty_label),
    )


def analysis_cell(row: rx.Var) -> rx.Component:
    return rx.cond(
        row["analysis_available"],
        rx.vstack(
            rx.text(row["analysis_heading"], size="2", weight="medium", color=styles.TEXT_PRIMARY),
            rx.text(row["analysis_detail"], size="1", color=styles.TEXT_SECONDARY),
            spacing="1",
            align_items="start",
            min_width="160px",
        ),
        rx.text("Análisis no disponible", size="2", color=styles.TEXT_MUTED),
    )


def comparison_row(row: rx.Var) -> rx.Component:
    return rx.box(
        product_cell(row),
        marketplace_cell(
            has_listing=row["alibaba_has_listing"],
            image_url=row["alibaba_image_url"],
            title=row["alibaba_title"],
            price=row["alibaba_price"],
            price_color=styles.ALIBABA,
            line_one=row["alibaba_range"],
            line_two=row["alibaba_moq"],
            line_three=row["alibaba_supplier"],
            relevance=row["alibaba_relevance"],
            match_label=row["alibaba_match_label"],
            url=row["alibaba_url"],
            empty_label="Sin resultado Alibaba",
        ),
        marketplace_cell(
            has_listing=row["facebook_has_listing"],
            image_url=row["facebook_image_url"],
            title=row["facebook_title"],
            price=row["facebook_price"],
            price_color=styles.FACEBOOK,
            line_one=row["facebook_usd_note"],
            line_two=row["facebook_source_note"],
            line_three=row["facebook_location"],
            relevance=row["facebook_relevance"],
            match_label=row["facebook_match_label"],
            url=row["facebook_url"],
            empty_label="Sin resultado Facebook",
        ),
        marketplace_cell(
            has_listing=row["ml_has_listing"],
            image_url=row["ml_image_url"],
            title=row["ml_title"],
            price=row["ml_price"],
            price_color=styles.MERCADOLIBRE,
            line_one=row["ml_condition"],
            line_two=row["ml_seller"],
            line_three="",
            relevance=row["ml_relevance"],
            match_label=row["ml_match_label"],
            url=row["ml_url"],
            empty_label="Sin resultado Mercado Libre",
        ),
        analysis_cell(row),
        display="grid",
        grid_template_columns="minmax(220px, 1.2fr) repeat(3, minmax(190px, 1fr)) minmax(160px, 0.8fr)",
        column_gap="20px",
        align_items="start",
        padding="18px 20px",
        border_top=f"1px solid {styles.BORDER}",
        min_width="1100px",
    )


def comparison_matrix() -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.vstack(
                rx.text(
                    "Comparación de mercado", size="4", weight="medium", color=styles.TEXT_PRIMARY
                ),
                rx.text(
                    "Productos comparables en distintas plataformas",
                    size="2",
                    color=styles.TEXT_MUTED,
                ),
                spacing="1",
                align_items="start",
            ),
            width="100%",
            padding="18px 20px 0",
        ),
        rx.cond(
            TrackerState.has_comparison_rows,
            rx.box(
                rx.box(
                    rx.text("Producto", size="1", weight="medium", color=styles.TEXT_MUTED),
                    rx.text("Alibaba", size="1", weight="medium", color=styles.ALIBABA),
                    rx.text(
                        "Facebook Marketplace", size="1", weight="medium", color=styles.FACEBOOK
                    ),
                    rx.text("Mercado Libre", size="1", weight="medium", color=styles.MERCADOLIBRE),
                    rx.text("Análisis", size="1", weight="medium", color=styles.TEXT_MUTED),
                    display="grid",
                    grid_template_columns="minmax(220px, 1.2fr) repeat(3, minmax(190px, 1fr)) minmax(160px, 0.8fr)",
                    column_gap="20px",
                    padding="12px 20px",
                    min_width="1100px",
                ),
                rx.foreach(TrackerState.comparison_rows, comparison_row),
                overflow_x="auto",
                width="100%",
            ),
            empty_state(
                "Todavía no hay una comparación",
                "Busca en Alibaba y, si corresponde, abre comparables de Facebook o Mercado Libre.",
            ),
        ),
        **styles.SURFACE_STYLE,
        width="100%",
        overflow="hidden",
        class_name="bera-comparison-matrix",
    )
